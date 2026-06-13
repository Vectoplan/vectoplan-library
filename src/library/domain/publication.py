# services/vectoplan-library/src/library/domain/publication.py
"""
Domain-Modelle für veröffentlichte Creative-Library-Daten.

Diese Datei beschreibt API-/Service-taugliche Strukturen für den produktiven
DB-Lesepfad:

    creative_library Tabellen
        → library_published_service
        → db_read_models
        → API-Routen
        → Editor / Admin / Creative Library / Inventar

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Abhängigkeit
- keine Repository-Imports
- keine Scanner-Imports
- keine Schreiboperationen
- robust serialisierbar
- tolerant gegenüber SQLAlchemy-Objekten, Dicts, Dataclasses und Fremdobjekten
- geeignet für API-Responses, Admin-UI, Tests und spätere Editor-Integration

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id
    variant_id

Die Datenbank soll die veröffentlichte, validierte Library-Wahrheit liefern.
Diese Datei modelliert diese veröffentlichte Sicht, nicht den rohen Filesystem-
Scan.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

PUBLICATION_COMPONENT_NAME = "creative_library_publication"
PUBLICATION_API_VERSION = "v1"
PUBLICATION_MODEL_VERSION = "publication.v1"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PUBLICATION_STATUS = "published"
DEFAULT_PUBLICATION_VISIBILITY = "visible"
DEFAULT_PUBLICATION_SOURCE = "database"

DEFAULT_SUMMARY_LIMIT = 5000
DEFAULT_ASSET_LIMIT = 500
DEFAULT_REVISION_LIMIT = 100
DEFAULT_ISSUE_LIMIT = 500


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LibraryPublicationStatus(str, Enum):
    """Veröffentlichungsstatus einer Family oder Revision."""

    UNKNOWN = "unknown"
    DRAFT = "draft"
    PENDING = "pending"
    PUBLISHED = "published"
    ACTIVE = "active"
    UNPUBLISHED = "unpublished"
    INACTIVE = "inactive"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"
    DELETED = "deleted"
    INVALID = "invalid"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibraryPublicationVisibility(str, Enum):
    """Sichtbarkeit eines veröffentlichten Eintrags."""

    UNKNOWN = "unknown"
    VISIBLE = "visible"
    HIDDEN = "hidden"
    INTERNAL = "internal"
    ADMIN_ONLY = "admin_only"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibraryPublicationSource(str, Enum):
    """Quelle der veröffentlichten Daten."""

    UNKNOWN = "unknown"
    DATABASE = "database"
    FILESYSTEM = "filesystem"
    SYNC = "sync"
    MANUAL = "manual"
    IMPORT = "import"
    API = "api"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibraryValidationStatus(str, Enum):
    """Validierungsstatus eines veröffentlichten Library-Eintrags."""

    UNKNOWN = "unknown"
    VALID = "valid"
    INVALID = "invalid"
    PARTIAL = "partial"
    WARNING = "warning"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class LibraryPublishedObjectKind(str, Enum):
    """Bekannte technische Object-Kinds."""

    CELL_BLOCK = "cell_block"
    MULTI_CELL_MODULE = "multi_cell_module"
    CATALOG_OBJECT = "catalog_object"
    ADAPTIVE_SYSTEM = "adaptive_system"
    UNKNOWN = "unknown"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=512)
def normalize_publication_status(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "ok": LibraryPublicationStatus.PUBLISHED.value,
        "live": LibraryPublicationStatus.PUBLISHED.value,
        "enabled": LibraryPublicationStatus.PUBLISHED.value,
        "visible": LibraryPublicationStatus.PUBLISHED.value,
        "published_active": LibraryPublicationStatus.PUBLISHED.value,
        "disabled": LibraryPublicationStatus.INACTIVE.value,
        "not_published": LibraryPublicationStatus.UNPUBLISHED.value,
        "removed": LibraryPublicationStatus.DELETED.value,
        "soft_deleted": LibraryPublicationStatus.DELETED.value,
        "trash": LibraryPublicationStatus.DELETED.value,
        "failed": LibraryPublicationStatus.ERROR.value,
        "failure": LibraryPublicationStatus.ERROR.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibraryPublicationStatus.values():
        return text

    return LibraryPublicationStatus.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_publication_visibility(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "show": LibraryPublicationVisibility.VISIBLE.value,
        "shown": LibraryPublicationVisibility.VISIBLE.value,
        "public": LibraryPublicationVisibility.VISIBLE.value,
        "enabled": LibraryPublicationVisibility.VISIBLE.value,
        "hide": LibraryPublicationVisibility.HIDDEN.value,
        "hidden": LibraryPublicationVisibility.HIDDEN.value,
        "invisible": LibraryPublicationVisibility.HIDDEN.value,
        "admin": LibraryPublicationVisibility.ADMIN_ONLY.value,
        "admin": LibraryPublicationVisibility.ADMIN_ONLY.value,
        "adminonly": LibraryPublicationVisibility.ADMIN_ONLY.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibraryPublicationVisibility.values():
        return text

    return LibraryPublicationVisibility.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_publication_source(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "db": LibraryPublicationSource.DATABASE.value,
        "sql": LibraryPublicationSource.DATABASE.value,
        "postgres": LibraryPublicationSource.DATABASE.value,
        "postgresql": LibraryPublicationSource.DATABASE.value,
        "file": LibraryPublicationSource.FILESYSTEM.value,
        "files": LibraryPublicationSource.FILESYSTEM.value,
        "fs": LibraryPublicationSource.FILESYSTEM.value,
        "scanner": LibraryPublicationSource.SYNC.value,
        "db_sync": LibraryPublicationSource.SYNC.value,
        "upload": LibraryPublicationSource.IMPORT.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibraryPublicationSource.values():
        return text

    return LibraryPublicationSource.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_validation_status(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "ok": LibraryValidationStatus.VALID.value,
        "success": LibraryValidationStatus.VALID.value,
        "passed": LibraryValidationStatus.VALID.value,
        "pass": LibraryValidationStatus.VALID.value,
        "warn": LibraryValidationStatus.WARNING.value,
        "warnings": LibraryValidationStatus.WARNING.value,
        "failed": LibraryValidationStatus.ERROR.value,
        "failure": LibraryValidationStatus.ERROR.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibraryValidationStatus.values():
        return text

    return LibraryValidationStatus.UNKNOWN.value


@lru_cache(maxsize=256)
def normalize_object_kind(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "block": LibraryPublishedObjectKind.CELL_BLOCK.value,
        "cell": LibraryPublishedObjectKind.CELL_BLOCK.value,
        "cellblock": LibraryPublishedObjectKind.CELL_BLOCK.value,
        "multi_cell": LibraryPublishedObjectKind.MULTI_CELL_MODULE.value,
        "module": LibraryPublishedObjectKind.MULTI_CELL_MODULE.value,
        "object": LibraryPublishedObjectKind.CATALOG_OBJECT.value,
        "catalog": LibraryPublishedObjectKind.CATALOG_OBJECT.value,
        "catalogue_object": LibraryPublishedObjectKind.CATALOG_OBJECT.value,
        "adaptive": LibraryPublishedObjectKind.ADAPTIVE_SYSTEM.value,
        "system": LibraryPublishedObjectKind.ADAPTIVE_SYSTEM.value,
    }

    if text in aliases:
        return aliases[text]

    if text in LibraryPublishedObjectKind.values():
        return text

    return LibraryPublishedObjectKind.UNKNOWN.value


def clear_publication_caches() -> Dict[str, Any]:
    """Leert alle lokalen Normalisierungs-Caches."""

    normalize_publication_status.cache_clear()
    normalize_publication_visibility.cache_clear()
    normalize_publication_source.cache_clear()
    normalize_validation_status.cache_clear()
    normalize_object_kind.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_publication_status",
            "normalize_publication_visibility",
            "normalize_publication_source",
            "normalize_validation_status",
            "normalize_object_kind",
        ],
    }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def safe_isoformat(value: Any) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.isoformat()

    text = str(value).strip()
    return text or None


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "on", "enabled", "active", "visible"}:
        return True

    if text in {"0", "false", "no", "n", "off", "disabled", "inactive", "hidden"}:
        return False

    return default


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def normalize_slug(value: Any) -> Optional[str]:
    text = normalize_string(value)

    if not text:
        return None

    return (
        text.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


def normalize_vplib_uid(value: Any) -> Optional[str]:
    text = normalize_string(value)
    return text.lower() if text else None


def normalize_taxonomy_path(
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> Optional[str]:
    parts = [
        normalize_slug(domain),
        normalize_slug(category),
        normalize_slug(subcategory),
    ]

    clean = [part for part in parts if part]

    if not clean:
        return None

    return "/".join(clean)


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def json_safe(value: Any) -> Any:
    """Konvertiert typische Python-Objekte in JSON-kompatible Strukturen."""

    if value is None:
        return None

    if is_dataclass(value):
        return json_safe(asdict(value))

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Enum):
        return value.value

    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def to_mapping(value: Any) -> Dict[str, Any]:
    """
    Konvertiert Mapping, Dataclass, SQLAlchemy-Objekt oder Fremdobjekt in Dict.

    Diese Funktion ist defensiv und wirft nicht bei einzelnen kaputten
    Attributen.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if is_dataclass(value):
        return dict(asdict(value))

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            result = value.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
        except Exception:
            pass

    table = getattr(value.__class__, "__table__", None)
    columns = getattr(table, "columns", None)

    if columns is not None:
        result: Dict[str, Any] = {}

        try:
            for column in columns:
                name = column.name
                try:
                    result[name] = getattr(value, name)
                except Exception:
                    continue
            return result
        except Exception:
            pass

    result = {}

    for name in dir(value):
        if name.startswith("_"):
            continue

        try:
            item = getattr(value, name)
        except Exception:
            continue

        if callable(item):
            continue

        result[name] = item

    return result


def truncate_list(values: Sequence[Any], limit: int) -> List[Any]:
    if limit <= 0:
        return []

    return list(values[:limit])


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass
class PublishedAssetRef:
    """
    Leichte Asset-Referenz für published API responses.

    Wird z. B. für Icon, Preview, GLB, Render-Varianten oder technische
    Dokumente verwendet.
    """

    role: Optional[str] = None
    asset_type: Optional[str] = None
    path: Optional[str] = None
    relative_path: Optional[str] = None
    uri: Optional[str] = None
    label: Optional[str] = None
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedAssetRef":
        data = to_mapping(value)

        return cls(
            role=data.get("role"),
            asset_type=data.get("asset_type") or data.get("type"),
            path=data.get("path"),
            relative_path=data.get("relative_path"),
            uri=data.get("uri") or data.get("url"),
            label=data.get("label") or data.get("name"),
            mime_type=data.get("mime_type"),
            checksum=data.get("checksum") or data.get("sha256"),
            size_bytes=data.get("size_bytes"),
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "asset_type": self.asset_type,
            "type": self.asset_type,
            "path": self.path,
            "relative_path": self.relative_path,
            "uri": self.uri,
            "label": self.label,
            "mime_type": self.mime_type,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
        }


@dataclass
class PublishedValidationSummary:
    """Kompakte Validierungsinformation für einen veröffentlichten Eintrag."""

    status: str = LibraryValidationStatus.UNKNOWN.value
    valid: Optional[bool] = None
    issue_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    fatal_count: int = 0
    last_validated_at: Optional[datetime] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.status = normalize_validation_status(self.status)
        self.issue_count = safe_int(self.issue_count)
        self.warning_count = safe_int(self.warning_count)
        self.error_count = safe_int(self.error_count)
        self.fatal_count = safe_int(self.fatal_count)

        if self.valid is None:
            self.valid = self.status == LibraryValidationStatus.VALID.value and self.error_count == 0 and self.fatal_count == 0

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedValidationSummary":
        data = to_mapping(value)

        return cls(
            status=data.get("status") or data.get("validation_status") or LibraryValidationStatus.UNKNOWN.value,
            valid=data.get("valid"),
            issue_count=data.get("issue_count", data.get("issues", 0)),
            warning_count=data.get("warning_count", data.get("warnings", 0)),
            error_count=data.get("error_count", data.get("errors", 0)),
            fatal_count=data.get("fatal_count", data.get("fatals", 0)),
            last_validated_at=data.get("last_validated_at") or data.get("validated_at"),
            payload=dict(data.get("payload") or data.get("validation_payload") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "valid": self.valid,
            "issue_count": self.issue_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "fatal_count": self.fatal_count,
            "last_validated_at": safe_isoformat(self.last_validated_at),
            "payload": json_safe(self.payload),
        }


@dataclass
class PublishedRevisionSummary:
    """Kompakte Information über eine veröffentlichte Family-Revision."""

    revision_db_id: Any = None
    revision_id: Optional[str] = None
    vplib_uid: Optional[str] = None
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    revision_hash: Optional[str] = None
    previous_revision_hash: Optional[str] = None
    package_version: Optional[str] = None
    schema_version: Optional[str] = None
    validation_status: str = LibraryValidationStatus.UNKNOWN.value
    publication_status: str = LibraryPublicationStatus.PUBLISHED.value
    scan_run_id: Any = None
    source_path: Optional[str] = None
    variant_count: int = 0
    asset_count: int = 0
    document_count: int = 0
    issue_count: int = 0
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vplib_uid = normalize_vplib_uid(self.vplib_uid)
        self.family_id = normalize_string(self.family_id)
        self.package_id = normalize_string(self.package_id)
        self.revision_hash = normalize_string(self.revision_hash)
        self.previous_revision_hash = normalize_string(self.previous_revision_hash)
        self.validation_status = normalize_validation_status(self.validation_status)
        self.publication_status = normalize_publication_status(self.publication_status)
        self.variant_count = safe_int(self.variant_count)
        self.asset_count = safe_int(self.asset_count)
        self.document_count = safe_int(self.document_count)
        self.issue_count = safe_int(self.issue_count)

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedRevisionSummary":
        data = to_mapping(value)

        return cls(
            revision_db_id=first_non_empty(data.get("revision_db_id"), data.get("id"), data.get("pk")),
            revision_id=data.get("revision_id"),
            vplib_uid=data.get("vplib_uid"),
            family_id=data.get("family_id"),
            package_id=data.get("package_id"),
            revision_hash=data.get("revision_hash") or data.get("hash") or data.get("content_hash"),
            previous_revision_hash=data.get("previous_revision_hash"),
            package_version=data.get("package_version"),
            schema_version=data.get("schema_version"),
            validation_status=data.get("validation_status") or data.get("status"),
            publication_status=data.get("publication_status") or data.get("status") or LibraryPublicationStatus.PUBLISHED.value,
            scan_run_id=data.get("scan_run_id"),
            source_path=data.get("source_path"),
            variant_count=data.get("variant_count", 0),
            asset_count=data.get("asset_count", 0),
            document_count=data.get("document_count", 0),
            issue_count=data.get("issue_count", 0),
            created_at=data.get("created_at"),
            published_at=data.get("published_at"),
            updated_at=data.get("updated_at"),
            payload=dict(
                data.get("payload")
                or data.get("summary_payload")
                or data.get("detail_payload")
                or {}
            ),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "revision_db_id": self.revision_db_id,
            "revision_id": self.revision_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "revision_hash": self.revision_hash,
            "previous_revision_hash": self.previous_revision_hash,
            "package_version": self.package_version,
            "schema_version": self.schema_version,
            "validation_status": self.validation_status,
            "publication_status": self.publication_status,
            "scan_run_id": self.scan_run_id,
            "source_path": self.source_path,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "issue_count": self.issue_count,
            "created_at": safe_isoformat(self.created_at),
            "published_at": safe_isoformat(self.published_at),
            "updated_at": safe_isoformat(self.updated_at),
            "payload": json_safe(self.payload),
            "metadata": json_safe(self.metadata),
        }


@dataclass
class PublishedVariantSummary:
    """Kompakte veröffentlichte Varianteninformation."""

    variant_db_id: Any = None
    variant_id: Optional[str] = None
    vplib_uid: Optional[str] = None
    family_id: Optional[str] = None
    revision_hash: Optional[str] = None
    label: Optional[str] = None
    description: Optional[str] = None
    is_default: bool = False
    enabled: bool = True
    visible: bool = True
    sort_order: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)
    resolved_payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vplib_uid = normalize_vplib_uid(self.vplib_uid)
        self.family_id = normalize_string(self.family_id)
        self.variant_id = normalize_string(self.variant_id)
        self.revision_hash = normalize_string(self.revision_hash)
        self.is_default = safe_bool(self.is_default)
        self.enabled = safe_bool(self.enabled, True)
        self.visible = safe_bool(self.visible, True)
        self.sort_order = safe_int(self.sort_order)

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedVariantSummary":
        data = to_mapping(value)
        variant_id = first_non_empty(data.get("variant_id"), data.get("id_in_family"), data.get("id"))

        return cls(
            variant_db_id=first_non_empty(data.get("variant_db_id"), data.get("id"), data.get("pk")),
            variant_id=variant_id,
            vplib_uid=data.get("vplib_uid"),
            family_id=data.get("family_id"),
            revision_hash=data.get("revision_hash"),
            label=data.get("label") or data.get("name") or variant_id,
            description=data.get("description"),
            is_default=data.get("is_default", data.get("default", False)),
            enabled=data.get("enabled", True),
            visible=data.get("visible", True),
            sort_order=data.get("sort_order", 0),
            payload=dict(data.get("payload") or {}),
            resolved_payload=dict(data.get("resolved_payload") or data.get("resolved") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_db_id": self.variant_db_id,
            "variant_id": self.variant_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "revision_hash": self.revision_hash,
            "label": self.label,
            "description": self.description,
            "is_default": self.is_default,
            "enabled": self.enabled,
            "visible": self.visible,
            "sort_order": self.sort_order,
            "payload": json_safe(self.payload),
            "resolved_payload": json_safe(self.resolved_payload),
            "metadata": json_safe(self.metadata),
        }


@dataclass
class PublishedFamilySummary:
    """
    Kompakte veröffentlichte Family-Summary für Listen, Tree und Creative Grid.

    Diese Struktur ist die DB-basierte Entsprechung zur bisherigen
    filesystem-basierten LibraryItem-Summary.
    """

    family_db_id: Any = None
    vplib_uid: Optional[str] = None
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    family_slug: Optional[str] = None
    slug: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    object_kind: str = LibraryPublishedObjectKind.UNKNOWN.value
    domain: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    taxonomy_path: Optional[str] = None
    classification_path: Optional[str] = None
    source_path: Optional[str] = None
    package_root: Optional[str] = None
    enabled: bool = True
    visible: bool = True
    publication_status: str = LibraryPublicationStatus.PUBLISHED.value
    visibility: str = LibraryPublicationVisibility.VISIBLE.value
    source: str = LibraryPublicationSource.DATABASE.value
    default_variant_id: Optional[str] = None
    variant_count: int = 0
    asset_count: int = 0
    document_count: int = 0
    revision_count: int = 0
    latest_revision_hash: Optional[str] = None
    published_revision_hash: Optional[str] = None
    revision_hash: Optional[str] = None
    validation: PublishedValidationSummary = field(default_factory=PublishedValidationSummary)
    latest_revision: Optional[PublishedRevisionSummary] = None
    icon: Optional[PublishedAssetRef] = None
    preview: Optional[PublishedAssetRef] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    scanned_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.vplib_uid = normalize_vplib_uid(self.vplib_uid)
        self.family_id = normalize_string(self.family_id)
        self.package_id = normalize_string(self.package_id)
        self.family_slug = normalize_slug(first_non_empty(self.family_slug, self.slug))
        self.slug = normalize_slug(first_non_empty(self.slug, self.family_slug))
        self.label = normalize_string(first_non_empty(self.label, self.name, self.family_slug, self.family_id))
        self.name = normalize_string(first_non_empty(self.name, self.label))
        self.object_kind = normalize_object_kind(self.object_kind)
        self.domain = normalize_slug(self.domain)
        self.category = normalize_slug(self.category)
        self.subcategory = normalize_slug(self.subcategory)
        self.taxonomy_path = self.taxonomy_path or normalize_taxonomy_path(
            self.domain,
            self.category,
            self.subcategory,
        )
        self.classification_path = self.classification_path or self.taxonomy_path
        self.publication_status = normalize_publication_status(self.publication_status)
        self.visibility = normalize_publication_visibility(self.visibility)
        self.source = normalize_publication_source(self.source)
        self.enabled = safe_bool(self.enabled, True)
        self.visible = safe_bool(self.visible, True)
        self.variant_count = safe_int(self.variant_count)
        self.asset_count = safe_int(self.asset_count)
        self.document_count = safe_int(self.document_count)
        self.revision_count = safe_int(self.revision_count)
        self.latest_revision_hash = normalize_string(self.latest_revision_hash)
        self.published_revision_hash = normalize_string(self.published_revision_hash)
        self.revision_hash = normalize_string(first_non_empty(self.revision_hash, self.published_revision_hash, self.latest_revision_hash))

        if not isinstance(self.validation, PublishedValidationSummary):
            self.validation = PublishedValidationSummary.from_mapping(self.validation)

        if self.latest_revision is not None and not isinstance(self.latest_revision, PublishedRevisionSummary):
            self.latest_revision = PublishedRevisionSummary.from_mapping(self.latest_revision)

        if self.icon is not None and not isinstance(self.icon, PublishedAssetRef):
            self.icon = PublishedAssetRef.from_mapping(self.icon)

        if self.preview is not None and not isinstance(self.preview, PublishedAssetRef):
            self.preview = PublishedAssetRef.from_mapping(self.preview)

        self.tags = [
            str(tag).strip()
            for tag in self.tags
            if str(tag).strip()
        ]

    @property
    def id(self) -> Optional[str]:
        """
        Kompatibilitäts-ID für ältere LibraryItem-Responses.

        Die fachlich bevorzugte technische ID bleibt vplib_uid. Für bestehende
        UI-/API-Stellen kann family_id weiter als sichtbare id genutzt werden.
        """

        return self.family_id or self.vplib_uid or self.package_id

    @property
    def is_published(self) -> bool:
        return (
            self.publication_status
            in {
                LibraryPublicationStatus.PUBLISHED.value,
                LibraryPublicationStatus.ACTIVE.value,
            }
            and self.enabled
            and self.visible
            and self.deleted_at is None
        )

    @property
    def is_deleted(self) -> bool:
        return self.publication_status == LibraryPublicationStatus.DELETED.value or self.deleted_at is not None

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedFamilySummary":
        data = to_mapping(value)

        payload = dict(
            data.get("payload")
            or data.get("summary_payload")
            or data.get("detail_payload")
            or {}
        )

        metadata = dict(data.get("metadata") or data.get("meta") or {})

        validation_payload = first_non_empty(
            data.get("validation"),
            data.get("validation_payload"),
            payload.get("validation") if isinstance(payload, Mapping) else None,
            {},
        )

        revision_payload = first_non_empty(
            data.get("latest_revision"),
            data.get("revision"),
            None,
        )

        icon_payload = first_non_empty(
            data.get("icon"),
            data.get("icon_asset"),
            metadata.get("icon") if isinstance(metadata, Mapping) else None,
            None,
        )

        preview_payload = first_non_empty(
            data.get("preview"),
            data.get("preview_asset"),
            metadata.get("preview") if isinstance(metadata, Mapping) else None,
            None,
        )

        domain = first_non_empty(data.get("domain"), data.get("domain_id"))
        category = first_non_empty(data.get("category"), data.get("category_id"))
        subcategory = first_non_empty(data.get("subcategory"), data.get("subcategory_id"))

        return cls(
            family_db_id=first_non_empty(data.get("family_db_id"), data.get("id"), data.get("pk")),
            vplib_uid=data.get("vplib_uid"),
            family_id=data.get("family_id"),
            package_id=data.get("package_id"),
            family_slug=first_non_empty(data.get("family_slug"), data.get("slug")),
            slug=first_non_empty(data.get("slug"), data.get("family_slug")),
            label=first_non_empty(data.get("label"), data.get("name")),
            name=first_non_empty(data.get("name"), data.get("label")),
            description=data.get("description"),
            object_kind=data.get("object_kind"),
            domain=domain,
            category=category,
            subcategory=subcategory,
            taxonomy_path=first_non_empty(data.get("taxonomy_path"), data.get("classification_path")),
            classification_path=data.get("classification_path"),
            source_path=data.get("source_path"),
            package_root=data.get("package_root"),
            enabled=data.get("enabled", True),
            visible=data.get("visible", True),
            publication_status=first_non_empty(data.get("publication_status"), data.get("status"), DEFAULT_PUBLICATION_STATUS),
            visibility=first_non_empty(data.get("visibility"), DEFAULT_PUBLICATION_VISIBILITY),
            source=first_non_empty(data.get("source"), DEFAULT_PUBLICATION_SOURCE),
            default_variant_id=data.get("default_variant_id"),
            variant_count=data.get("variant_count", 0),
            asset_count=data.get("asset_count", 0),
            document_count=data.get("document_count", 0),
            revision_count=data.get("revision_count", 0),
            latest_revision_hash=first_non_empty(data.get("latest_revision_hash"), data.get("revision_hash")),
            published_revision_hash=first_non_empty(data.get("published_revision_hash"), data.get("revision_hash")),
            revision_hash=data.get("revision_hash"),
            validation=PublishedValidationSummary.from_mapping(validation_payload),
            latest_revision=PublishedRevisionSummary.from_mapping(revision_payload) if revision_payload else None,
            icon=PublishedAssetRef.from_mapping(icon_payload) if icon_payload else None,
            preview=PublishedAssetRef.from_mapping(preview_payload) if preview_payload else None,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            scanned_at=data.get("scanned_at"),
            published_at=data.get("published_at"),
            deleted_at=data.get("deleted_at"),
            tags=list(data.get("tags") or metadata.get("tags") or []),
            payload=payload,
            metadata=metadata,
        )

    def to_dict(
        self,
        *,
        include_payload: bool = True,
        include_metadata: bool = True,
        include_assets: bool = True,
        include_revision: bool = True,
    ) -> Dict[str, Any]:
        return {
            "id": self.id,
            "family_db_id": self.family_db_id,
            "vplib_uid": self.vplib_uid,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "family_slug": self.family_slug,
            "slug": self.slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "object_kind": self.object_kind,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "classification_path": self.classification_path,
            "source_path": self.source_path,
            "package_root": self.package_root,
            "enabled": self.enabled,
            "visible": self.visible,
            "publication_status": self.publication_status,
            "visibility": self.visibility,
            "source": self.source,
            "is_published": self.is_published,
            "is_deleted": self.is_deleted,
            "default_variant_id": self.default_variant_id,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "revision_count": self.revision_count,
            "latest_revision_hash": self.latest_revision_hash,
            "published_revision_hash": self.published_revision_hash,
            "revision_hash": self.revision_hash,
            "validation": self.validation.to_dict(),
            "latest_revision": self.latest_revision.to_dict() if include_revision and self.latest_revision else None,
            "icon": self.icon.to_dict() if include_assets and self.icon else None,
            "preview": self.preview.to_dict() if include_assets and self.preview else None,
            "created_at": safe_isoformat(self.created_at),
            "updated_at": safe_isoformat(self.updated_at),
            "scanned_at": safe_isoformat(self.scanned_at),
            "published_at": safe_isoformat(self.published_at),
            "deleted_at": safe_isoformat(self.deleted_at),
            "tags": list(self.tags),
            "payload": json_safe(self.payload) if include_payload else {},
            "metadata": json_safe(self.metadata) if include_metadata else {},
        }


@dataclass
class PublishedFamilyDetail:
    """
    Detailantwort einer veröffentlichten Family.

    Enthält Summary, aktuelle Revision, Varianten, Assets, Dokumente und
    optional rohe Payloads.
    """

    summary: PublishedFamilySummary
    revision: Optional[PublishedRevisionSummary] = None
    variants: List[PublishedVariantSummary] = field(default_factory=list)
    assets: List[PublishedAssetRef] = field(default_factory=list)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    raw_documents: Dict[str, Any] = field(default_factory=dict)
    validation: Optional[PublishedValidationSummary] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if not isinstance(self.summary, PublishedFamilySummary):
            self.summary = PublishedFamilySummary.from_mapping(self.summary)

        if self.revision is not None and not isinstance(self.revision, PublishedRevisionSummary):
            self.revision = PublishedRevisionSummary.from_mapping(self.revision)

        self.variants = [
            item if isinstance(item, PublishedVariantSummary) else PublishedVariantSummary.from_mapping(item)
            for item in self.variants
        ]

        self.assets = [
            item if isinstance(item, PublishedAssetRef) else PublishedAssetRef.from_mapping(item)
            for item in self.assets
        ]

        self.documents = [
            json_safe(to_mapping(item))
            for item in self.documents
        ]

        if self.validation is not None and not isinstance(self.validation, PublishedValidationSummary):
            self.validation = PublishedValidationSummary.from_mapping(self.validation)

        if self.validation is None:
            self.validation = self.summary.validation

        if self.revision is None:
            self.revision = self.summary.latest_revision

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedFamilyDetail":
        data = to_mapping(value)

        summary_payload = first_non_empty(data.get("summary"), data.get("family"), data)

        return cls(
            summary=PublishedFamilySummary.from_mapping(summary_payload),
            revision=PublishedRevisionSummary.from_mapping(data.get("revision")) if data.get("revision") else None,
            variants=[
                PublishedVariantSummary.from_mapping(item)
                for item in data.get("variants", []) or []
            ],
            assets=[
                PublishedAssetRef.from_mapping(item)
                for item in data.get("assets", []) or []
            ],
            documents=[
                to_mapping(item)
                for item in data.get("documents", []) or []
            ],
            raw_documents=dict(data.get("raw_documents") or {}),
            validation=PublishedValidationSummary.from_mapping(data.get("validation")) if data.get("validation") else None,
            payload=dict(data.get("payload") or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
            generated_at=data.get("generated_at") or utcnow(),
        )

    def to_dict(
        self,
        *,
        include_raw_documents: bool = False,
        include_payload: bool = True,
        include_metadata: bool = True,
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "status": "ok",
            "summary": self.summary.to_dict(
                include_payload=include_payload,
                include_metadata=include_metadata,
                include_assets=True,
                include_revision=True,
            ),
            "revision": self.revision.to_dict() if self.revision else None,
            "variants": [
                item.to_dict()
                for item in self.variants
            ],
            "assets": [
                item.to_dict()
                for item in self.assets
            ],
            "documents": json_safe(self.documents),
            "raw_documents": json_safe(self.raw_documents) if include_raw_documents else {},
            "validation": self.validation.to_dict() if self.validation else None,
            "payload": json_safe(self.payload) if include_payload else {},
            "metadata": json_safe(self.metadata) if include_metadata else {},
            "generated_at": safe_isoformat(self.generated_at),
        }


@dataclass
class PublishedLibraryStats:
    """Aggregierte Zähler für veröffentlichte Library-Daten."""

    total_count: int = 0
    published_count: int = 0
    unpublished_count: int = 0
    deleted_count: int = 0
    invalid_count: int = 0
    domain_count: int = 0
    category_count: int = 0
    subcategory_count: int = 0
    variant_count: int = 0
    asset_count: int = 0
    document_count: int = 0
    revision_count: int = 0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, safe_int(getattr(self, field_name), 0))

    @classmethod
    def from_families(cls, families: Iterable[PublishedFamilySummary]) -> "PublishedLibraryStats":
        items = [
            item if isinstance(item, PublishedFamilySummary) else PublishedFamilySummary.from_mapping(item)
            for item in families
        ]

        domains = {item.domain for item in items if item.domain}
        categories = {(item.domain, item.category) for item in items if item.domain and item.category}
        subcategories = {
            (item.domain, item.category, item.subcategory)
            for item in items
            if item.domain and item.category and item.subcategory
        }

        return cls(
            total_count=len(items),
            published_count=sum(1 for item in items if item.is_published),
            unpublished_count=sum(1 for item in items if not item.is_published and not item.is_deleted),
            deleted_count=sum(1 for item in items if item.is_deleted),
            invalid_count=sum(1 for item in items if item.validation and not item.validation.valid),
            domain_count=len(domains),
            category_count=len(categories),
            subcategory_count=len(subcategories),
            variant_count=sum(item.variant_count for item in items),
            asset_count=sum(item.asset_count for item in items),
            document_count=sum(item.document_count for item in items),
            revision_count=sum(item.revision_count for item in items),
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "PublishedLibraryStats":
        data = to_mapping(value)

        return cls(
            total_count=data.get("total_count", data.get("total", 0)),
            published_count=data.get("published_count", data.get("published", 0)),
            unpublished_count=data.get("unpublished_count", data.get("unpublished", 0)),
            deleted_count=data.get("deleted_count", data.get("deleted", 0)),
            invalid_count=data.get("invalid_count", data.get("invalid", 0)),
            domain_count=data.get("domain_count", data.get("domains", 0)),
            category_count=data.get("category_count", data.get("categories", 0)),
            subcategory_count=data.get("subcategory_count", data.get("subcategories", 0)),
            variant_count=data.get("variant_count", data.get("variants", 0)),
            asset_count=data.get("asset_count", data.get("assets", 0)),
            document_count=data.get("document_count", data.get("documents", 0)),
            revision_count=data.get("revision_count", data.get("revisions", 0)),
        )

    def to_dict(self) -> Dict[str, int]:
        return {
            "total_count": self.total_count,
            "published_count": self.published_count,
            "unpublished_count": self.unpublished_count,
            "deleted_count": self.deleted_count,
            "invalid_count": self.invalid_count,
            "domain_count": self.domain_count,
            "category_count": self.category_count,
            "subcategory_count": self.subcategory_count,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "revision_count": self.revision_count,
        }


@dataclass
class PublishedLibraryListResult:
    """
    Ergebnis für GET /api/v1/vplib/library/blocks aus DB-Sicht.
    """

    ok: bool = True
    status: str = "ok"
    items: List[PublishedFamilySummary] = field(default_factory=list)
    stats: PublishedLibraryStats = field(default_factory=PublishedLibraryStats)
    filters: Dict[str, Any] = field(default_factory=dict)
    pagination: Dict[str, Any] = field(default_factory=dict)
    source: str = LibraryPublicationSource.DATABASE.value
    generated_at: datetime = field(default_factory=utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.items = [
            item if isinstance(item, PublishedFamilySummary) else PublishedFamilySummary.from_mapping(item)
            for item in self.items
        ]

        if not isinstance(self.stats, PublishedLibraryStats):
            self.stats = PublishedLibraryStats.from_mapping(self.stats)

        if self.stats.total_count == 0 and self.items:
            self.stats = PublishedLibraryStats.from_families(self.items)

        self.source = normalize_publication_source(self.source)

    @classmethod
    def from_items(
        cls,
        items: Iterable[Any],
        *,
        filters: Optional[Mapping[str, Any]] = None,
        pagination: Optional[Mapping[str, Any]] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> "PublishedLibraryListResult":
        summaries = [
            item if isinstance(item, PublishedFamilySummary) else PublishedFamilySummary.from_mapping(item)
            for item in items
        ]

        return cls(
            ok=True,
            status="ok",
            items=summaries,
            stats=PublishedLibraryStats.from_families(summaries),
            filters=dict(filters or {}),
            pagination=dict(pagination or {}),
            metadata=dict(metadata or {}),
        )

    def to_dict(
        self,
        *,
        include_payload: bool = False,
        include_metadata: bool = False,
        item_limit: int = DEFAULT_SUMMARY_LIMIT,
    ) -> Dict[str, Any]:
        items = truncate_list(self.items, item_limit)

        return {
            "ok": self.ok,
            "status": self.status,
            "count": len(items),
            "total_count": self.stats.total_count,
            "items": [
                item.to_dict(
                    include_payload=include_payload,
                    include_metadata=include_metadata,
                    include_assets=True,
                    include_revision=True,
                )
                for item in items
            ],
            "items_truncated": len(self.items) > item_limit,
            "stats": self.stats.to_dict(),
            "filters": json_safe(self.filters),
            "pagination": json_safe(self.pagination),
            "source": self.source,
            "generated_at": safe_isoformat(self.generated_at),
            "metadata": json_safe(self.metadata) if include_metadata else {},
        }


# ---------------------------------------------------------------------------
# Builders / response helpers
# ---------------------------------------------------------------------------


def build_published_family_summary(value: Any) -> PublishedFamilySummary:
    return value if isinstance(value, PublishedFamilySummary) else PublishedFamilySummary.from_mapping(value)


def build_published_family_summaries(values: Iterable[Any]) -> List[PublishedFamilySummary]:
    return [build_published_family_summary(value) for value in values]


def build_published_detail_response(
    detail: Any,
    *,
    include_raw_documents: bool = False,
    include_payload: bool = True,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    item = detail if isinstance(detail, PublishedFamilyDetail) else PublishedFamilyDetail.from_mapping(detail)

    return item.to_dict(
        include_raw_documents=include_raw_documents,
        include_payload=include_payload,
        include_metadata=include_metadata,
    )


def build_published_list_response(
    items: Iterable[Any],
    *,
    filters: Optional[Mapping[str, Any]] = None,
    pagination: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
    include_payload: bool = False,
    include_metadata: bool = False,
) -> Dict[str, Any]:
    result = PublishedLibraryListResult.from_items(
        items,
        filters=filters,
        pagination=pagination,
        metadata=metadata,
    )

    return result.to_dict(
        include_payload=include_payload,
        include_metadata=include_metadata,
    )


def build_not_found_publication_response(
    identifier: Any,
    *,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "not_found",
        "identifier": str(identifier) if identifier is not None else None,
        "message": message or f"Published library item not found: {identifier}",
        "generated_at": safe_isoformat(utcnow()),
    }


def build_error_publication_response(
    error: Any,
    *,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "error",
        "message": message or str(error),
        "error_type": error.__class__.__name__ if error is not None else None,
        "generated_at": safe_isoformat(utcnow()),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def get_publication_health() -> Dict[str, Any]:
    """Leichter Health-Check für die Publication-Domain-Datei."""

    return {
        "ok": True,
        "status": "ok",
        "component": PUBLICATION_COMPONENT_NAME,
        "api_version": PUBLICATION_API_VERSION,
        "model_version": PUBLICATION_MODEL_VERSION,
        "version": __version__,
        "enums": {
            "publication_status": list(LibraryPublicationStatus.values()),
            "publication_visibility": list(LibraryPublicationVisibility.values()),
            "publication_source": list(LibraryPublicationSource.values()),
            "validation_status": list(LibraryValidationStatus.values()),
            "object_kind": list(LibraryPublishedObjectKind.values()),
        },
        "cache": {
            "normalize_publication_status": normalize_publication_status.cache_info()._asdict(),
            "normalize_publication_visibility": normalize_publication_visibility.cache_info()._asdict(),
            "normalize_publication_source": normalize_publication_source.cache_info()._asdict(),
            "normalize_validation_status": normalize_validation_status.cache_info()._asdict(),
            "normalize_object_kind": normalize_object_kind.cache_info()._asdict(),
        },
    }


def assert_publication_ready() -> Dict[str, Any]:
    health = get_publication_health()

    if not health.get("ok"):
        raise RuntimeError("Publication domain models are not ready.")

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "PUBLICATION_COMPONENT_NAME",
    "PUBLICATION_API_VERSION",
    "PUBLICATION_MODEL_VERSION",
    "DEFAULT_PUBLICATION_STATUS",
    "DEFAULT_PUBLICATION_VISIBILITY",
    "DEFAULT_PUBLICATION_SOURCE",

    # Enums
    "LibraryPublicationStatus",
    "LibraryPublicationVisibility",
    "LibraryPublicationSource",
    "LibraryValidationStatus",
    "LibraryPublishedObjectKind",

    # Helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_string",
    "normalize_slug",
    "normalize_vplib_uid",
    "normalize_taxonomy_path",
    "normalize_publication_status",
    "normalize_publication_visibility",
    "normalize_publication_source",
    "normalize_validation_status",
    "normalize_object_kind",
    "clear_publication_caches",
    "json_safe",
    "to_mapping",
    "first_non_empty",

    # Models
    "PublishedAssetRef",
    "PublishedValidationSummary",
    "PublishedRevisionSummary",
    "PublishedVariantSummary",
    "PublishedFamilySummary",
    "PublishedFamilyDetail",
    "PublishedLibraryStats",
    "PublishedLibraryListResult",

    # Builders
    "build_published_family_summary",
    "build_published_family_summaries",
    "build_published_detail_response",
    "build_published_list_response",
    "build_not_found_publication_response",
    "build_error_publication_response",

    # Health
    "get_publication_health",
    "assert_publication_ready",
]