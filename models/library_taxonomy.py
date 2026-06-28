# services/vectoplan-library/models/library_taxonomy.py
"""
Database models for VECTOPLAN Library Taxonomy.

Diese Datei modelliert die Taxonomie-Schicht für:

- Reiter / Domains
- Kategorien
- Subkategorien
- System-Taxonomie
- User-eigene Taxonomie
- User-Overrides auf System-Taxonomie
- Taxonomie-Audit

Ziel:

    Backend-owned taxonomy / definitions
        -> LibraryTaxonomyNode system-owned
        -> User-created LibraryTaxonomyNode
        -> LibraryTaxonomyOverride
        -> resolved taxonomy for user_id
        -> Creative Inventory / Create Flow / Generator

Wichtige Architekturregeln:

- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt keine Migration aus.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei spricht keine Datenbankverbindung aktiv an.
- Diese Datei enthält keine Route.
- Diese Datei enthält keine Service- oder Repository-Logik.
- System-Taxonomie wird nicht direkt überschrieben.
- User-Änderungen werden als User-Nodes oder Overrides gespeichert.
- owner_user_id=None bedeutet system-owned.
- owner_scope="system" bedeutet globale Systemtaxonomie.
- owner_scope="user:<id>" bedeutet User-Erweiterung.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Eigene User-Reiter/Kategorien/Subkategorien werden als source_scope="user"
  gespeichert.
- Ausblenden, Umbenennen, Sortieren oder Wiederherstellen von System-Nodes
  wird über LibraryTaxonomyOverride gespeichert.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Metadata / constants
# ---------------------------------------------------------------------------

LIBRARY_TAXONOMY_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.library_taxonomy.models.v1"
DEFAULT_USER_ID: Final[int] = 1

MAX_UID_LENGTH: Final[int] = 80
MAX_KEY_LENGTH: Final[int] = 255
MAX_NODE_KEY_LENGTH: Final[int] = 160
MAX_NODE_TYPE_LENGTH: Final[int] = 40
MAX_LABEL_LENGTH: Final[int] = 255
MAX_STATUS_LENGTH: Final[int] = 40
MAX_SOURCE_SCOPE_LENGTH: Final[int] = 40
MAX_OWNER_SCOPE_LENGTH: Final[int] = 120
MAX_TAXONOMY_PART_LENGTH: Final[int] = 120
MAX_TAXONOMY_PATH_LENGTH: Final[int] = 512
MAX_ICON_LENGTH: Final[int] = 120
MAX_COLOR_LENGTH: Final[int] = 40
MAX_ACTION_LENGTH: Final[int] = 80

NODE_TYPE_DOMAIN: Final[str] = "domain"
NODE_TYPE_CATEGORY: Final[str] = "category"
NODE_TYPE_SUBCATEGORY: Final[str] = "subcategory"

TAXONOMY_NODE_TYPES: Final[tuple[str, ...]] = (
    NODE_TYPE_DOMAIN,
    NODE_TYPE_CATEGORY,
    NODE_TYPE_SUBCATEGORY,
)

RESERVED_TAXONOMY_PARTS: Final[tuple[str, ...]] = (
    "api",
    "admin",
    "system",
    "null",
    "none",
    "undefined",
)


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

class LibraryTaxonomySourceScope(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    IMPORTED = "imported"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryTaxonomyNodeType(str, enum.Enum):
    DOMAIN = NODE_TYPE_DOMAIN
    CATEGORY = NODE_TYPE_CATEGORY
    SUBCATEGORY = NODE_TYPE_SUBCATEGORY

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryTaxonomyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    HIDDEN = "hidden"
    DEPRECATED = "deprecated"
    INVALID = "invalid"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryTaxonomyOverrideAction(str, enum.Enum):
    HIDE = "hide"
    RESTORE = "restore"
    RENAME = "rename"
    REORDER = "reorder"
    MOVE = "move"
    PATCH = "patch"
    DELETE = "delete"

    @property
    def key(self) -> str:
        return str(self.value)


class LibraryTaxonomyAuditEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    RESTORED = "restored"
    MOVED = "moved"
    OVERRIDE_CREATED = "override_created"
    OVERRIDE_UPDATED = "override_updated"
    OVERRIDE_DELETED = "override_deleted"
    SEED_IMPORTED = "seed_imported"

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


@lru_cache(maxsize=4096)
def _cached_ascii_fold(value: str) -> str:
    """Kleine Umlaut-/Sonderzeichen-Normalisierung ohne externe Abhängigkeit."""
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
        "é": "e",
        "è": "e",
        "ê": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ú": "u",
        "ù": "u",
        "û": "u",
    }

    result = value

    for source, target in replacements.items():
        result = result.replace(source, target)

    return result


@lru_cache(maxsize=8192)
def _cached_slugify(value: str, max_length: int = MAX_TAXONOMY_PART_LENGTH) -> str:
    """Cached slugify für Taxonomie-Parts."""
    text = _cached_ascii_fold(value).strip().lower()
    text = text.replace("\\", "/")
    text = text.replace("/", "-")
    text = text.replace(".", "-")
    text = text.replace("_", "-")

    cleaned: list[str] = []
    previous_dash = False

    for char in text:
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue

        if char == "-":
            if not previous_dash:
                cleaned.append("-")
                previous_dash = True
            continue

        if not previous_dash:
            cleaned.append("-")
            previous_dash = True

    result = "".join(cleaned).strip("-")

    if result in RESERVED_TAXONOMY_PARTS:
        result = f"{result}-node"

    return result[:max_length] if result else ""


def normalize_taxonomy_part(value: Any, *, field_name: str, required: bool = False) -> str | None:
    """Normalisiert einen einzelnen Taxonomie-Part."""
    text = normalize_optional_string(value, max_length=MAX_TAXONOMY_PART_LENGTH)

    if not text:
        if required:
            raise ValueError(f"{field_name} is required.")
        return None

    slug = _cached_slugify(text, MAX_TAXONOMY_PART_LENGTH)

    if not slug:
        if required:
            raise ValueError(f"{field_name} is required.")
        return None

    return slug


def normalize_taxonomy_label(value: Any, *, fallback: Any = None) -> str | None:
    """Normalisiert Taxonomie-Labels. Fallback kann Slug sein."""
    label = normalize_optional_string(value, max_length=MAX_LABEL_LENGTH)

    if label:
        return label

    fallback_text = normalize_optional_string(fallback, max_length=MAX_LABEL_LENGTH)
    if not fallback_text:
        return None

    return fallback_text.replace("-", " ").replace("_", " ").strip().title()


def normalize_source_scope(value: Any, *, default: str = LibraryTaxonomySourceScope.SYSTEM.value) -> str:
    """Normalisiert source_scope."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "core": LibraryTaxonomySourceScope.SYSTEM.value,
        "default": LibraryTaxonomySourceScope.SYSTEM.value,
        "global": LibraryTaxonomySourceScope.SYSTEM.value,
        "system": LibraryTaxonomySourceScope.SYSTEM.value,
        "user": LibraryTaxonomySourceScope.USER.value,
        "custom": LibraryTaxonomySourceScope.USER.value,
        "import": LibraryTaxonomySourceScope.IMPORTED.value,
        "imported": LibraryTaxonomySourceScope.IMPORTED.value,
        "generated": LibraryTaxonomySourceScope.GENERATED.value,
        "generator": LibraryTaxonomySourceScope.GENERATED.value,
    }

    return aliases.get(text, text if text else default)[:MAX_SOURCE_SCOPE_LENGTH]


def owner_scope_for(
    *,
    source_scope: Any = LibraryTaxonomySourceScope.SYSTEM.value,
    owner_user_id: Any = None,
) -> str:
    """
    Baut einen stabilen owner_scope.

    PostgreSQL behandelt NULL in UniqueConstraints nicht als gleich.
    Deshalb wird für eindeutige Taxonomie-Nodes zusätzlich ein nicht-nullbarer
    owner_scope gespeichert.
    """

    scope = normalize_source_scope(source_scope)
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == LibraryTaxonomySourceScope.SYSTEM.value and user_id is None:
        return LibraryTaxonomySourceScope.SYSTEM.value

    if scope == LibraryTaxonomySourceScope.USER.value:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope or LibraryTaxonomySourceScope.SYSTEM.value


def normalize_node_type(value: Any, *, default: str | None = None) -> str:
    """Normalisiert Node-Type."""
    text = enum_value(value, default=default or "").strip().lower()

    aliases = {
        "tab": NODE_TYPE_DOMAIN,
        "reiter": NODE_TYPE_DOMAIN,
        "domain": NODE_TYPE_DOMAIN,
        "root": NODE_TYPE_DOMAIN,
        "category": NODE_TYPE_CATEGORY,
        "kategorie": NODE_TYPE_CATEGORY,
        "cat": NODE_TYPE_CATEGORY,
        "subcategory": NODE_TYPE_SUBCATEGORY,
        "sub_category": NODE_TYPE_SUBCATEGORY,
        "sub-category": NODE_TYPE_SUBCATEGORY,
        "unterkategorie": NODE_TYPE_SUBCATEGORY,
        "sub": NODE_TYPE_SUBCATEGORY,
    }

    normalized = aliases.get(text, text)

    if normalized not in TAXONOMY_NODE_TYPES:
        raise ValueError(f"Invalid taxonomy node_type: {value!r}")

    return normalized


def infer_node_type(
    *,
    node_type: Any = None,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    taxonomy_path: Any = None,
    default: str = NODE_TYPE_DOMAIN,
) -> str:
    """Leitet Node-Type aus explizitem Wert oder Pfad/Parts ab."""
    if node_type is not None and str(node_type).strip():
        return normalize_node_type(node_type)

    parts = parse_taxonomy_path(taxonomy_path)

    if subcategory is not None and str(subcategory).strip():
        return NODE_TYPE_SUBCATEGORY

    if len(parts) >= 3:
        return NODE_TYPE_SUBCATEGORY

    if category is not None and str(category).strip():
        return NODE_TYPE_CATEGORY

    if len(parts) == 2:
        return NODE_TYPE_CATEGORY

    if domain is not None and str(domain).strip():
        return NODE_TYPE_DOMAIN

    if len(parts) == 1:
        return NODE_TYPE_DOMAIN

    return normalize_node_type(default)


@lru_cache(maxsize=8192)
def _cached_parse_taxonomy_path(path: str) -> tuple[str, ...]:
    """Cached parser für Taxonomiepfade."""
    cleaned = path.replace("\\", "/").replace(".", "/")
    raw_parts = [part for part in cleaned.split("/") if part and part.strip()]
    result: list[str] = []

    for part in raw_parts[:3]:
        normalized = normalize_taxonomy_part(part, field_name="taxonomy_path_part", required=False)
        if normalized:
            result.append(normalized)

    return tuple(result)


def parse_taxonomy_path(path: Any) -> tuple[str, ...]:
    """Parst Taxonomiepfad zu maximal drei normalisierten Parts."""
    text = normalize_optional_string(path, max_length=MAX_TAXONOMY_PATH_LENGTH)
    if not text:
        return tuple()

    return _cached_parse_taxonomy_path(text)


def build_taxonomy_path(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    node_type: Any = None,
) -> str:
    """Baut kanonischen Taxonomiepfad."""
    normalized_node_type = normalize_node_type(node_type or infer_node_type(domain=domain, category=category, subcategory=subcategory))

    normalized_domain = normalize_taxonomy_part(domain, field_name="domain", required=True)

    if normalized_node_type == NODE_TYPE_DOMAIN:
        return normalized_domain or ""

    normalized_category = normalize_taxonomy_part(category, field_name="category", required=True)

    if normalized_node_type == NODE_TYPE_CATEGORY:
        return "/".join(part for part in (normalized_domain, normalized_category) if part)

    normalized_subcategory = normalize_taxonomy_part(subcategory, field_name="subcategory", required=True)

    return "/".join(part for part in (normalized_domain, normalized_category, normalized_subcategory) if part)


def taxonomy_parts_from_payload(payload: Mapping[str, Any] | None) -> dict[str, str | None]:
    """Extrahiert domain/category/subcategory/node_type/path robust aus Payload."""
    data = normalize_json_mapping(payload)
    path_parts = parse_taxonomy_path(first_non_empty(data.get("taxonomy_path"), data.get("path")))

    domain = normalize_taxonomy_part(
        first_non_empty(data.get("domain"), path_parts[0] if len(path_parts) > 0 else None),
        field_name="domain",
        required=False,
    )
    category = normalize_taxonomy_part(
        first_non_empty(data.get("category"), path_parts[1] if len(path_parts) > 1 else None),
        field_name="category",
        required=False,
    )
    subcategory = normalize_taxonomy_part(
        first_non_empty(data.get("subcategory"), path_parts[2] if len(path_parts) > 2 else None),
        field_name="subcategory",
        required=False,
    )

    node_type = infer_node_type(
        node_type=data.get("node_type") or data.get("type"),
        domain=domain,
        category=category,
        subcategory=subcategory,
        taxonomy_path=data.get("taxonomy_path") or data.get("path"),
    )

    if node_type == NODE_TYPE_DOMAIN:
        domain = domain or normalize_taxonomy_part(first_non_empty(data.get("slug"), data.get("id"), data.get("key")), field_name="domain")
        category = None
        subcategory = None

    if node_type == NODE_TYPE_CATEGORY:
        category = category or normalize_taxonomy_part(first_non_empty(data.get("slug"), data.get("id"), data.get("key")), field_name="category")
        subcategory = None

    if node_type == NODE_TYPE_SUBCATEGORY:
        subcategory = subcategory or normalize_taxonomy_part(first_non_empty(data.get("slug"), data.get("id"), data.get("key")), field_name="subcategory")

    taxonomy_path = None
    if domain:
        taxonomy_path = build_taxonomy_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
            node_type=node_type,
        )

    return {
        "node_type": node_type,
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "taxonomy_path": taxonomy_path,
    }


def parent_path_for(
    *,
    node_type: Any,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Ermittelt kanonischen Parent-Pfad."""
    normalized_node_type = normalize_node_type(node_type)

    if normalized_node_type == NODE_TYPE_DOMAIN:
        return None

    if normalized_node_type == NODE_TYPE_CATEGORY:
        normalized_domain = normalize_taxonomy_part(domain, field_name="domain", required=True)
        return normalized_domain

    normalized_domain = normalize_taxonomy_part(domain, field_name="domain", required=True)
    normalized_category = normalize_taxonomy_part(category, field_name="category", required=True)
    return f"{normalized_domain}/{normalized_category}"


def node_depth_for(node_type: Any) -> int:
    """Gibt Tiefe 1..3 für Node-Type zurück."""
    normalized = normalize_node_type(node_type)

    if normalized == NODE_TYPE_DOMAIN:
        return 1

    if normalized == NODE_TYPE_CATEGORY:
        return 2

    return 3


def node_key_for(
    *,
    node_type: Any,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    taxonomy_path: Any = None,
) -> str:
    """Baut stabilen node_key."""
    normalized_type = normalize_node_type(node_type)

    path = normalize_optional_string(taxonomy_path, max_length=MAX_TAXONOMY_PATH_LENGTH)
    if not path:
        path = build_taxonomy_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
            node_type=normalized_type,
        )

    return f"{normalized_type}:{path}"[:MAX_KEY_LENGTH]


def normalize_status(
    value: Any,
    *,
    default: str = LibraryTaxonomyStatus.ACTIVE.value,
    active: Any = None,
    visible: Any = None,
) -> str:
    """Normalisiert Status mit aktiv/visible-Fallback."""
    if value is not None:
        text = enum_value(value, default=default).strip().lower()
        return text[:MAX_STATUS_LENGTH] if text else default

    if active is not None and not normalize_bool(active, default=True):
        return LibraryTaxonomyStatus.INACTIVE.value

    if visible is not None and not normalize_bool(visible, default=True):
        return LibraryTaxonomyStatus.HIDDEN.value

    return default


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

class LibraryTaxonomyNode(TimestampMixin, JsonMixin, db.Model):
    """
    Ein Taxonomie-Node.

    node_type:
    - domain       = Reiter / Tab
    - category     = Kategorie unter Domain
    - subcategory  = Subkategorie unter Kategorie

    System-Nodes:
    - source_scope="system"
    - owner_user_id=None
    - owner_scope="system"

    User-Nodes:
    - source_scope="user"
    - owner_user_id=1 in Phase 1
    - owner_scope="user:1"
    """

    __tablename__ = "library_taxonomy_nodes"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    node_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    parent_node_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_taxonomy_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=LibraryTaxonomySourceScope.SYSTEM.value,
        index=True,
    )
    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=LibraryTaxonomySourceScope.SYSTEM.value,
        index=True,
    )

    base_node_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    node_type = db.Column(db.String(MAX_NODE_TYPE_LENGTH), nullable=False, index=True)
    node_depth = db.Column(db.Integer, nullable=False, default=1, index=True)

    node_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)
    slug = db.Column(db.String(MAX_NODE_KEY_LENGTH), nullable=False, index=True)

    domain = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    category = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    subcategory = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)

    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=False, index=True)
    parent_taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    icon = db.Column(db.String(MAX_ICON_LENGTH), nullable=True)
    color = db.Column(db.String(MAX_COLOR_LENGTH), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryTaxonomyStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    selectable = db.Column(db.Boolean, nullable=False, default=True)
    allow_children = db.Column(db.Boolean, nullable=False, default=True)
    is_leaf = db.Column(db.Boolean, nullable=False, default=False, index=True)
    system_required = db.Column(db.Boolean, nullable=False, default=False)
    locked = db.Column(db.Boolean, nullable=False, default=False)

    tags_json = db.Column(db.JSON, nullable=False, default=list)
    aliases_json = db.Column(db.JSON, nullable=False, default=list)
    i18n_json = db.Column(db.JSON, nullable=False, default=dict)
    ui_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    parent = db.relationship(
        "LibraryTaxonomyNode",
        remote_side=[id],
        back_populates="children",
        foreign_keys=[parent_node_id],
        lazy="joined",
    )
    children = db.relationship(
        "LibraryTaxonomyNode",
        back_populates="parent",
        foreign_keys=[parent_node_id],
        lazy="selectin",
    )
    overrides = db.relationship(
        "LibraryTaxonomyOverride",
        back_populates="target_node",
        foreign_keys="LibraryTaxonomyOverride.target_node_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "node_type", "taxonomy_path", name="uq_library_taxonomy_node_owner_type_path"),
        db.Index("ix_library_taxonomy_nodes_path_active", "taxonomy_path", "active", "visible"),
        db.Index("ix_library_taxonomy_nodes_parent_sort", "parent_node_id", "sort_order"),
        db.Index("ix_library_taxonomy_nodes_tree_lookup", "domain", "category", "subcategory"),
        db.Index("ix_library_taxonomy_nodes_owner_status", "owner_scope", "status", "active", "visible"),
        db.Index("ix_library_taxonomy_nodes_source_type", "source_scope", "node_type"),
    )

    def __repr__(self) -> str:
        return f"<LibraryTaxonomyNode id={self.id!r} type={self.node_type!r} path={self.taxonomy_path!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        source_scope: Any = LibraryTaxonomySourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        parent: "LibraryTaxonomyNode | None" = None,
        created_by_user_id: Any = None,
    ) -> "LibraryTaxonomyNode":
        """Erstellt einen Taxonomie-Node aus Payload."""
        obj = cls()
        obj.update_from_payload(
            payload,
            source_scope=source_scope,
            owner_user_id=owner_user_id,
            parent=parent,
            created_by_user_id=created_by_user_id,
        )
        return obj

    def update_from_payload(
        self,
        payload: Mapping[str, Any] | None,
        *,
        source_scope: Any = LibraryTaxonomySourceScope.SYSTEM.value,
        owner_user_id: Any = None,
        parent: "LibraryTaxonomyNode | None" = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
    ) -> None:
        """Aktualisiert mutable Felder aus Payload."""
        data = normalize_json_mapping(payload)
        parts = taxonomy_parts_from_payload(data)

        node_type = normalize_node_type(parts["node_type"])
        domain = parts["domain"]
        category = parts["category"]
        subcategory = parts["subcategory"]

        if parent is not None:
            if node_type == NODE_TYPE_CATEGORY and not domain:
                domain = parent.domain
            elif node_type == NODE_TYPE_SUBCATEGORY:
                domain = domain or parent.domain
                category = category or parent.category or parent.slug

        taxonomy_path = parts["taxonomy_path"]
        if not taxonomy_path:
            taxonomy_path = build_taxonomy_path(
                domain=domain,
                category=category,
                subcategory=subcategory,
                node_type=node_type,
            )

        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)
        normalized_owner_scope = owner_scope_for(
            source_scope=normalized_source_scope,
            owner_user_id=normalized_owner_user_id,
        )

        if not getattr(self, "node_uid", None):
            self.node_uid = normalize_optional_string(first_non_empty(data.get("node_uid"), data.get("uid")), max_length=MAX_UID_LENGTH) or new_uid()

        self.parent = parent
        self.parent_node_id = getattr(parent, "id", None)

        self.source_scope = normalized_source_scope
        self.owner_user_id = normalized_owner_user_id
        self.owner_scope = normalized_owner_scope
        self.base_node_uid = normalize_optional_string(
            first_non_empty(data.get("base_node_uid"), data.get("baseNodeUid")),
            max_length=MAX_UID_LENGTH,
        )

        self.node_type = node_type
        self.node_depth = node_depth_for(node_type)

        self.domain = domain
        self.category = category
        self.subcategory = subcategory
        self.taxonomy_path = taxonomy_path
        self.parent_taxonomy_path = parent_path_for(
            node_type=node_type,
            domain=domain,
            category=category,
            subcategory=subcategory,
        )

        self.node_key = node_key_for(
            node_type=node_type,
            domain=domain,
            category=category,
            subcategory=subcategory,
            taxonomy_path=taxonomy_path,
        )

        self.slug = normalize_taxonomy_part(
            first_non_empty(
                data.get("slug"),
                data.get("key"),
                data.get("id"),
                subcategory if node_type == NODE_TYPE_SUBCATEGORY else None,
                category if node_type == NODE_TYPE_CATEGORY else None,
                domain,
            ),
            field_name="slug",
            required=True,
        ) or ""

        self.label = normalize_taxonomy_label(first_non_empty(data.get("label"), data.get("name")), fallback=self.slug)
        self.name = normalize_taxonomy_label(first_non_empty(data.get("name"), data.get("label")), fallback=self.slug)
        self.description = normalize_optional_string(data.get("description"))

        ui = normalize_json_mapping(data.get("ui"))
        metadata = normalize_json_mapping(data.get("metadata"))

        self.icon = normalize_optional_string(first_non_empty(data.get("icon"), ui.get("icon")), max_length=MAX_ICON_LENGTH)
        self.color = normalize_optional_string(first_non_empty(data.get("color"), ui.get("color")), max_length=MAX_COLOR_LENGTH)
        self.sort_order = normalize_int(data.get("sort_order"), default=0, minimum=0) or 0

        self.active = normalize_bool(data.get("active"), default=True)
        self.visible = normalize_bool(data.get("visible"), default=True)
        self.status = normalize_status(data.get("status"), active=self.active, visible=self.visible)

        self.selectable = normalize_bool(
            first_non_empty(data.get("selectable"), metadata.get("selectable")),
            default=node_type == NODE_TYPE_SUBCATEGORY,
        )
        self.allow_children = normalize_bool(
            first_non_empty(data.get("allow_children"), metadata.get("allow_children")),
            default=node_type != NODE_TYPE_SUBCATEGORY,
        )
        self.is_leaf = normalize_bool(
            first_non_empty(data.get("is_leaf"), metadata.get("is_leaf")),
            default=node_type == NODE_TYPE_SUBCATEGORY,
        )
        self.system_required = normalize_bool(
            first_non_empty(data.get("system_required"), metadata.get("system_required")),
            default=normalized_source_scope == LibraryTaxonomySourceScope.SYSTEM.value,
        )
        self.locked = normalize_bool(
            first_non_empty(data.get("locked"), metadata.get("locked")),
            default=False,
        )

        self.tags_json = normalize_json_list(data.get("tags"))
        self.aliases_json = normalize_json_list(data.get("aliases"))
        self.i18n_json = normalize_json_mapping(data.get("i18n"))
        self.ui_json = ui

        self.payload = data
        self.meta = normalize_json_mapping(data.get("meta"))
        self.metadata_json = metadata

        creator_id = normalize_user_id(created_by_user_id, default=None)
        updater_id = normalize_user_id(updated_by_user_id, default=None)

        if getattr(self, "created_by_user_id", None) is None and creator_id is not None:
            self.created_by_user_id = creator_id

        if updater_id is not None:
            self.updated_by_user_id = updater_id

        self.deleted_at = None if self.status != LibraryTaxonomyStatus.DELETED.value else self.deleted_at
        self.touch()

    def is_system_owned(self) -> bool:
        return self.owner_scope == LibraryTaxonomySourceScope.SYSTEM.value and self.owner_user_id is None

    def is_user_owned(self) -> bool:
        return self.source_scope == LibraryTaxonomySourceScope.USER.value or self.owner_user_id is not None

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für Taxonomie-Node."""
        if self.locked or self.system_required:
            raise ValueError("Cannot delete a locked or system-required taxonomy node directly.")

        self.status = LibraryTaxonomyStatus.DELETED.value
        self.active = False
        self.visible = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt einen gelöschten Node wieder her."""
        self.status = LibraryTaxonomyStatus.ACTIVE.value
        self.active = True
        self.visible = True
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(
        self,
        *,
        include_children: bool = False,
        include_overrides: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "node_db_id": self.id,
            "node_uid": self.node_uid,
            "parent_node_id": self.parent_node_id,
            "source_scope": self.source_scope,
            "owner_user_id": self.owner_user_id,
            "owner_scope": self.owner_scope,
            "base_node_uid": self.base_node_uid,
            "node_type": self.node_type,
            "node_depth": self.node_depth,
            "node_key": self.node_key,
            "slug": self.slug,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "parent_taxonomy_path": self.parent_taxonomy_path,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "sort_order": self.sort_order,
            "status": self.status,
            "active": self.active,
            "visible": self.visible,
            "selectable": self.selectable,
            "allow_children": self.allow_children,
            "is_leaf": self.is_leaf,
            "system_required": self.system_required,
            "locked": self.locked,
            "tags": normalize_json_list(self.tags_json),
            "aliases": normalize_json_list(self.aliases_json),
            "i18n": normalize_json_mapping(self.i18n_json),
            "ui": normalize_json_mapping(self.ui_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_children:
            children = list(getattr(self, "children", []) or [])
            children.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "label", "") or ""))
            result["children"] = [child.to_dict(include_children=False, include_overrides=include_overrides) for child in children]

        if include_overrides:
            overrides = list(getattr(self, "overrides", []) or [])
            overrides.sort(key=lambda item: normalize_int(getattr(item, "id", 0), default=0) or 0)
            result["overrides"] = [override.to_dict(include_target=False) for override in overrides]

        return result


class LibraryTaxonomyOverride(TimestampMixin, JsonMixin, db.Model):
    """
    User-Override auf einen Taxonomie-Node.

    Beispiele:

    - User blendet System-Reiter aus.
    - User benennt Kategorie nur für sich um.
    - User sortiert Subkategorien anders.
    - User stellt ausgeblendeten Node wieder her.
    """

    __tablename__ = "library_taxonomy_overrides"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    override_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    user_id = db.Column(db.BigInteger, nullable=False, default=DEFAULT_USER_ID, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=False, default=f"user:{DEFAULT_USER_ID}", index=True)

    target_node_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_taxonomy_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    target_node_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    target_node_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=True, index=True)
    target_taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)
    target_node_type = db.Column(db.String(MAX_NODE_TYPE_LENGTH), nullable=True, index=True)

    override_action = db.Column(
        db.String(MAX_ACTION_LENGTH),
        nullable=False,
        default=LibraryTaxonomyOverrideAction.PATCH.value,
        index=True,
    )
    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=LibraryTaxonomyStatus.ACTIVE.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)

    visible_override = db.Column(db.Boolean, nullable=True)
    active_override = db.Column(db.Boolean, nullable=True)
    selectable_override = db.Column(db.Boolean, nullable=True)

    label_override = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description_override = db.Column(db.Text, nullable=True)
    icon_override = db.Column(db.String(MAX_ICON_LENGTH), nullable=True)
    color_override = db.Column(db.String(MAX_COLOR_LENGTH), nullable=True)
    sort_order_override = db.Column(db.Integer, nullable=True)

    parent_node_uid_override = db.Column(db.String(MAX_UID_LENGTH), nullable=True)
    parent_taxonomy_path_override = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True)

    payload_patch = db.Column(db.JSON, nullable=False, default=dict)
    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)

    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    target_node = db.relationship(
        "LibraryTaxonomyNode",
        back_populates="overrides",
        foreign_keys=[target_node_id],
        lazy="joined",
    )

    __table_args__ = (
        db.UniqueConstraint("user_id", "target_node_uid", name="uq_library_taxonomy_override_user_node_uid"),
        db.Index("ix_library_taxonomy_overrides_user_active", "user_id", "active", "status"),
        db.Index("ix_library_taxonomy_overrides_target_path", "target_taxonomy_path", "target_node_type"),
        db.Index("ix_library_taxonomy_overrides_action", "override_action", "status"),
    )

    def __repr__(self) -> str:
        return f"<LibraryTaxonomyOverride user_id={self.user_id!r} target={self.target_node_uid!r} action={self.override_action!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        target_node: LibraryTaxonomyNode | None = None,
        user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
    ) -> "LibraryTaxonomyOverride":
        """Erstellt einen User-Override aus Payload."""
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(first_non_empty(data.get("user_id"), user_id), default=DEFAULT_USER_ID) or DEFAULT_USER_ID

        action = enum_value(
            first_non_empty(data.get("override_action"), data.get("action")),
            default=LibraryTaxonomyOverrideAction.PATCH.value,
        )

        target_path = normalize_optional_string(
            first_non_empty(
                data.get("target_taxonomy_path"),
                data.get("taxonomy_path"),
                getattr(target_node, "taxonomy_path", None),
            ),
            max_length=MAX_TAXONOMY_PATH_LENGTH,
        )

        target_type = normalize_optional_string(
            first_non_empty(
                data.get("target_node_type"),
                data.get("node_type"),
                getattr(target_node, "node_type", None),
            ),
            max_length=MAX_NODE_TYPE_LENGTH,
        )

        return cls(
            override_uid=normalize_optional_string(first_non_empty(data.get("override_uid"), data.get("uid")), max_length=MAX_UID_LENGTH) or new_uid(),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id}",
            target_node=target_node,
            target_node_id=getattr(target_node, "id", None),
            target_node_uid=normalize_optional_string(
                first_non_empty(data.get("target_node_uid"), getattr(target_node, "node_uid", None)),
                max_length=MAX_UID_LENGTH,
            ),
            target_node_key=normalize_optional_string(
                first_non_empty(data.get("target_node_key"), getattr(target_node, "node_key", None)),
                max_length=MAX_KEY_LENGTH,
            ),
            target_taxonomy_path=target_path,
            target_node_type=target_type,
            override_action=action,
            status=normalize_status(data.get("status"), default=LibraryTaxonomyStatus.ACTIVE.value),
            active=normalize_bool(data.get("active"), default=True),
            visible_override=data.get("visible_override") if isinstance(data.get("visible_override"), bool) else data.get("visible") if isinstance(data.get("visible"), bool) else None,
            active_override=data.get("active_override") if isinstance(data.get("active_override"), bool) else None,
            selectable_override=data.get("selectable_override") if isinstance(data.get("selectable_override"), bool) else None,
            label_override=normalize_optional_string(first_non_empty(data.get("label_override"), data.get("label")), max_length=MAX_LABEL_LENGTH),
            description_override=normalize_optional_string(first_non_empty(data.get("description_override"), data.get("description"))),
            icon_override=normalize_optional_string(first_non_empty(data.get("icon_override"), data.get("icon")), max_length=MAX_ICON_LENGTH),
            color_override=normalize_optional_string(first_non_empty(data.get("color_override"), data.get("color")), max_length=MAX_COLOR_LENGTH),
            sort_order_override=normalize_int(first_non_empty(data.get("sort_order_override"), data.get("sort_order")), default=None, minimum=0),
            parent_node_uid_override=normalize_optional_string(data.get("parent_node_uid_override"), max_length=MAX_UID_LENGTH),
            parent_taxonomy_path_override=normalize_optional_string(data.get("parent_taxonomy_path_override"), max_length=MAX_TAXONOMY_PATH_LENGTH),
            payload_patch=normalize_json_mapping(first_non_empty(data.get("payload_patch"), data.get("patch"))),
            before_json=normalize_json_mapping(data.get("before")),
            after_json=normalize_json_mapping(data.get("after")),
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        """Soft-delete für Override."""
        self.status = LibraryTaxonomyStatus.DELETED.value
        self.active = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def restore(self, *, user_id: Any = None) -> None:
        """Stellt Override wieder her."""
        self.status = LibraryTaxonomyStatus.ACTIVE.value
        self.active = True
        self.deleted_at = None
        self.deleted_by_user_id = None
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_target: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "override_db_id": self.id,
            "override_uid": self.override_uid,
            "user_id": self.user_id,
            "owner_scope": self.owner_scope,
            "target_node_id": self.target_node_id,
            "target_node_uid": self.target_node_uid,
            "target_node_key": self.target_node_key,
            "target_taxonomy_path": self.target_taxonomy_path,
            "target_node_type": self.target_node_type,
            "override_action": self.override_action,
            "status": self.status,
            "active": self.active,
            "visible_override": self.visible_override,
            "active_override": self.active_override,
            "selectable_override": self.selectable_override,
            "label_override": self.label_override,
            "description_override": self.description_override,
            "icon_override": self.icon_override,
            "color_override": self.color_override,
            "sort_order_override": self.sort_order_override,
            "parent_node_uid_override": self.parent_node_uid_override,
            "parent_taxonomy_path_override": self.parent_taxonomy_path_override,
            "payload_patch": normalize_json_mapping(self.payload_patch),
            "before": normalize_json_mapping(self.before_json),
            "after": normalize_json_mapping(self.after_json),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_target:
            result["target_node"] = self.target_node.to_dict(include_children=False, include_overrides=False) if self.target_node is not None else None

        return result


class LibraryTaxonomyAuditEvent(TimestampMixin, JsonMixin, db.Model):
    """Audit-Event für Taxonomieoperationen."""

    __tablename__ = "library_taxonomy_audit_events"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    event_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    event_type = db.Column(db.String(120), nullable=False, index=True)

    user_id = db.Column(db.BigInteger, nullable=True, index=True)
    owner_scope = db.Column(db.String(MAX_OWNER_SCOPE_LENGTH), nullable=True, index=True)

    node_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_taxonomy_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    override_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_taxonomy_overrides.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    node_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)
    override_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    node_type = db.Column(db.String(MAX_NODE_TYPE_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)

    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)
    diff_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    node = db.relationship("LibraryTaxonomyNode", foreign_keys=[node_id], lazy="joined")
    override = db.relationship("LibraryTaxonomyOverride", foreign_keys=[override_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_library_taxonomy_audit_user_event", "user_id", "event_type", "created_at"),
        db.Index("ix_library_taxonomy_audit_node_event", "node_uid", "event_type", "created_at"),
        db.Index("ix_library_taxonomy_audit_path_event", "taxonomy_path", "event_type", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LibraryTaxonomyAuditEvent id={self.id!r} event_type={self.event_type!r} path={self.taxonomy_path!r}>"

    @classmethod
    def create_event(
        cls,
        *,
        event_type: Any,
        user_id: Any = None,
        node: LibraryTaxonomyNode | None = None,
        override: LibraryTaxonomyOverride | None = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryTaxonomyAuditEvent":
        data = normalize_json_mapping(payload)
        normalized_user_id = normalize_user_id(first_non_empty(user_id, data.get("user_id")), default=None)

        target_node = node or getattr(override, "target_node", None)

        return cls(
            event_uid=new_uid(),
            event_type=enum_value(event_type, default=LibraryTaxonomyAuditEventType.UPDATED.value),
            user_id=normalized_user_id,
            owner_scope=f"user:{normalized_user_id}" if normalized_user_id else None,
            node=node,
            node_id=getattr(target_node, "id", None),
            override=override,
            override_id=getattr(override, "id", None),
            node_uid=getattr(target_node, "node_uid", None),
            override_uid=getattr(override, "override_uid", None),
            node_type=getattr(target_node, "node_type", None),
            taxonomy_path=getattr(target_node, "taxonomy_path", None) or getattr(override, "target_taxonomy_path", None),
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
            "node_id": self.node_id,
            "override_id": self.override_id,
            "node_uid": self.node_uid,
            "override_uid": self.override_uid,
            "node_type": self.node_type,
            "taxonomy_path": self.taxonomy_path,
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
# Resolved payload helpers
# ---------------------------------------------------------------------------

def apply_override_to_node_payload(
    node_payload: Mapping[str, Any],
    override_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Wendet einen Override auf einen serialisierten Node an.

    Diese Funktion ist bewusst model-unabhängig, damit Repository/Service sie
    später für resolved taxonomy verwenden können.
    """

    result = normalize_json_mapping(node_payload)
    override = normalize_json_mapping(override_payload)

    if not override or not normalize_bool(override.get("active"), default=True):
        return result

    action = clean_string(override.get("override_action") or override.get("action")).lower()

    if action == LibraryTaxonomyOverrideAction.HIDE.value:
        result["visible"] = False
        result["hidden_by_override"] = True

    if action == LibraryTaxonomyOverrideAction.RESTORE.value:
        result["visible"] = True
        result["hidden_by_override"] = False

    if "visible_override" in override and override.get("visible_override") is not None:
        result["visible"] = normalize_bool(override.get("visible_override"), default=result.get("visible", True))

    if "active_override" in override and override.get("active_override") is not None:
        result["active"] = normalize_bool(override.get("active_override"), default=result.get("active", True))

    if "selectable_override" in override and override.get("selectable_override") is not None:
        result["selectable"] = normalize_bool(override.get("selectable_override"), default=result.get("selectable", True))

    for source_key, target_key in (
        ("label_override", "label"),
        ("description_override", "description"),
        ("icon_override", "icon"),
        ("color_override", "color"),
        ("sort_order_override", "sort_order"),
    ):
        value = override.get(source_key)
        if value is not None:
            result[target_key] = value

    patch = normalize_json_mapping(override.get("payload_patch"))
    if patch:
        result["payload"] = merge_json(result.get("payload") if isinstance(result.get("payload"), Mapping) else None, patch)

    result["override"] = override
    return result


def build_taxonomy_tree_from_nodes(nodes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Baut eine einfache Domain->Category->Subcategory Baumstruktur aus Payloads.

    Diese Funktion ist absichtlich unabhängig vom DB-Query.
    """

    normalized_nodes = [normalize_json_mapping(node) for node in nodes]
    by_path: dict[str, dict[str, Any]] = {}

    for node in normalized_nodes:
        path = normalize_optional_string(node.get("taxonomy_path"), max_length=MAX_TAXONOMY_PATH_LENGTH)
        if not path:
            continue

        item = dict(node)
        item.setdefault("children", [])
        by_path[path] = item

    roots: list[dict[str, Any]] = []

    for path, item in sorted(by_path.items(), key=lambda pair: (len(pair[0].split("/")), pair[1].get("sort_order") or 0, pair[0])):
        parent_path = normalize_optional_string(item.get("parent_taxonomy_path"), max_length=MAX_TAXONOMY_PATH_LENGTH)

        if parent_path and parent_path in by_path:
            by_path[parent_path].setdefault("children", []).append(item)
        else:
            roots.append(item)

    def _sort_children(node: dict[str, Any]) -> None:
        children = node.get("children")
        if not isinstance(children, list):
            return

        children.sort(key=lambda child: (normalize_int(child.get("sort_order"), default=0) or 0, clean_string(child.get("label") or child.get("slug"))))

        for child in children:
            if isinstance(child, dict):
                _sort_children(child)

    roots.sort(key=lambda child: (normalize_int(child.get("sort_order"), default=0) or 0, clean_string(child.get("label") or child.get("slug"))))

    for root in roots:
        _sort_children(root)

    return roots


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_library_taxonomy_models() -> tuple[type[Any], ...]:
    """Gibt alle echten Modelklassen dieser Datei zurück."""
    return (
        LibraryTaxonomyNode,
        LibraryTaxonomyOverride,
        LibraryTaxonomyAuditEvent,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_library_taxonomy_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_library_taxonomy_models()


def get_library_taxonomy_model_names() -> tuple[str, ...]:
    """Gibt alle Modelklassennamen zurück."""
    return tuple(model.__name__ for model in iter_library_taxonomy_models())


def get_library_taxonomy_table_names() -> tuple[str, ...]:
    """Gibt alle Tabellennamen zurück."""
    return tuple(str(getattr(model, "__tablename__", "")) for model in iter_library_taxonomy_models())


def get_library_taxonomy_models_health() -> dict[str, Any]:
    """JSON-kompatibler Health-Snapshot dieser Model-Datei."""
    model_names = get_library_taxonomy_model_names()
    table_names = get_library_taxonomy_table_names()

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
            "schema_version": LIBRARY_TAXONOMY_MODELS_SCHEMA_VERSION,
            "healthy": healthy,
            "ok": healthy,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "node_types": list(TAXONOMY_NODE_TYPES),
            "supports_system_taxonomy": True,
            "supports_user_taxonomy": True,
            "supports_taxonomy_overrides": True,
            "supports_taxonomy_audit": True,
            "supports_resolved_tree_helpers": True,
        }
    except Exception as exc:
        return {
            "schema_version": LIBRARY_TAXONOMY_MODELS_SCHEMA_VERSION,
            "healthy": False,
            "ok": False,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_library_taxonomy_models_ready() -> None:
    """Wirft RuntimeError, wenn die Taxonomy-Models nicht bereit sind."""
    health = get_library_taxonomy_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"Library taxonomy models are not ready: {health}")


def clear_library_taxonomy_model_caches() -> dict[str, Any]:
    """Leert interne Caches dieser Datei."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _cached_ascii_fold,
        _cached_slugify,
        _cached_parse_taxonomy_path,
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
    "LIBRARY_TAXONOMY_MODELS_SCHEMA_VERSION",
    "DEFAULT_USER_ID",
    "NODE_TYPE_DOMAIN",
    "NODE_TYPE_CATEGORY",
    "NODE_TYPE_SUBCATEGORY",
    "TAXONOMY_NODE_TYPES",
    "RESERVED_TAXONOMY_PARTS",

    # Enums
    "LibraryTaxonomySourceScope",
    "LibraryTaxonomyNodeType",
    "LibraryTaxonomyStatus",
    "LibraryTaxonomyOverrideAction",
    "LibraryTaxonomyAuditEventType",

    # Models
    "LibraryTaxonomyNode",
    "LibraryTaxonomyOverride",
    "LibraryTaxonomyAuditEvent",

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
    "normalize_user_id",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "merge_json",
    "stable_json_hash",
    "normalize_taxonomy_part",
    "normalize_taxonomy_label",
    "normalize_source_scope",
    "owner_scope_for",
    "normalize_node_type",
    "infer_node_type",
    "parse_taxonomy_path",
    "build_taxonomy_path",
    "taxonomy_parts_from_payload",
    "parent_path_for",
    "node_depth_for",
    "node_key_for",
    "normalize_status",
    "apply_override_to_node_payload",
    "build_taxonomy_tree_from_nodes",

    # Model discovery / health
    "iter_library_taxonomy_models",
    "iter_models",
    "get_models",
    "get_library_taxonomy_model_names",
    "get_library_taxonomy_table_names",
    "get_library_taxonomy_models_health",
    "assert_library_taxonomy_models_ready",
    "clear_library_taxonomy_model_caches",
]