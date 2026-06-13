# services/vectoplan-library/src/library/read_models/db_block_summary_builder.py
"""
DB-Block-Summary-Builder für die VECTOPLAN Creative Library.

Diese Datei baut API-nahe Listen-/Summary-Responses aus DB-Daten.

Zielpfad:

    creative_library Tabellen
        → repository
        → library_published_service
        → db_block_summary_builder
        → GET /api/v1/vplib/library/blocks

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Session
- keine Datenbankzugriffe
- keine Schreiboperationen
- kein Filesystem-Scan
- keine Scanner-/Reader-/Validator-Imports
- tolerant gegenüber SQLAlchemy-Objekten, Dicts, Dataclasses und Domainmodellen
- kompatibel mit der bisherigen Blocks-Response-Struktur
- primär auf veröffentlichte DB-Daten ausgelegt

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id

Dieser Builder ersetzt nicht das Repository. Er formt nur bereits geladene
DB-/Repository-Daten in API-kompatible Read-Models.
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
# Domain imports
# ---------------------------------------------------------------------------

try:
    from ..domain.publication import (
        DEFAULT_PUBLICATION_SOURCE,
        PublishedAssetRef,
        PublishedFamilySummary,
        PublishedLibraryListResult,
        PublishedLibraryStats,
        PublishedRevisionSummary,
        PublishedValidationSummary,
        build_error_publication_response,
        build_published_family_summary,
        build_published_family_summaries,
        build_published_list_response,
    )
except Exception as import_error:  # pragma: no cover - defensive import fallback
    DEFAULT_PUBLICATION_SOURCE = "database"

    PublishedAssetRef = None  # type: ignore
    PublishedFamilySummary = None  # type: ignore
    PublishedLibraryListResult = None  # type: ignore
    PublishedLibraryStats = None  # type: ignore
    PublishedRevisionSummary = None  # type: ignore
    PublishedValidationSummary = None  # type: ignore
    build_error_publication_response = None  # type: ignore
    build_published_family_summary = None  # type: ignore
    build_published_family_summaries = None  # type: ignore
    build_published_list_response = None  # type: ignore
    _PUBLICATION_IMPORT_ERROR = import_error
else:
    _PUBLICATION_IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

DB_BLOCK_SUMMARY_BUILDER_NAME = "db_block_summary_builder"
DB_BLOCK_SUMMARY_COMPONENT_NAME = "creative_library_db_block_summary_builder"
DB_BLOCK_SUMMARY_API_VERSION = "v1"
DB_BLOCK_SUMMARY_MODEL_VERSION = "db-block-summary.v1"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

DEFAULT_SORT_FIELD = "taxonomy_label"
DEFAULT_SORT_DIRECTION = "asc"

DEFAULT_INCLUDE_PAYLOAD = False
DEFAULT_INCLUDE_METADATA = False
DEFAULT_INCLUDE_ASSETS = True
DEFAULT_INCLUDE_REVISION = True

DEFAULT_SOURCE = DEFAULT_PUBLICATION_SOURCE or "database"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DbBlockSummaryStatus(str, Enum):
    """Status eines Summary-Builds."""

    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class DbBlockSummarySortField(str, Enum):
    """Unterstützte Sortierfelder."""

    TAXONOMY_LABEL = "taxonomy_label"
    LABEL = "label"
    FAMILY_ID = "family_id"
    VPLIB_UID = "vplib_uid"
    DOMAIN = "domain"
    CATEGORY = "category"
    SUBCATEGORY = "subcategory"
    OBJECT_KIND = "object_kind"
    PUBLISHED_AT = "published_at"
    UPDATED_AT = "updated_at"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def normalize_sort_field(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")

    aliases = {
        "name": DbBlockSummarySortField.LABEL.value,
        "title": DbBlockSummarySortField.LABEL.value,
        "id": DbBlockSummarySortField.FAMILY_ID.value,
        "uid": DbBlockSummarySortField.VPLIB_UID.value,
        "taxonomy": DbBlockSummarySortField.TAXONOMY_LABEL.value,
        "path": DbBlockSummarySortField.TAXONOMY_LABEL.value,
        "published": DbBlockSummarySortField.PUBLISHED_AT.value,
        "modified": DbBlockSummarySortField.UPDATED_AT.value,
        "updated": DbBlockSummarySortField.UPDATED_AT.value,
    }

    if text in aliases:
        return aliases[text]

    if text in DbBlockSummarySortField.values():
        return text

    return DEFAULT_SORT_FIELD


@lru_cache(maxsize=64)
def normalize_sort_direction(value: Any) -> str:
    text = str(value or "").strip().lower()

    if text in {"desc", "descending", "-1", "reverse"}:
        return "desc"

    return "asc"


@lru_cache(maxsize=512)
def normalize_slug(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return (
        text.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
    )


@lru_cache(maxsize=512)
def normalize_string_cached(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def clear_db_block_summary_builder_caches() -> Dict[str, Any]:
    """Leert alle lokalen Caches dieses Builders."""

    normalize_sort_field.cache_clear()
    normalize_sort_direction.cache_clear()
    normalize_slug.cache_clear()
    normalize_string_cached.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_sort_field",
            "normalize_sort_direction",
            "normalize_slug",
            "normalize_string_cached",
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

    if text in {"1", "true", "yes", "y", "on", "active", "enabled", "published", "visible"}:
        return True

    if text in {"0", "false", "no", "n", "off", "inactive", "disabled", "deleted", "hidden"}:
        return False

    return default


def normalize_string(value: Any) -> Optional[str]:
    return normalize_string_cached(value)


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
        except TypeError:
            try:
                result = value.to_dict(flat=True)
                if isinstance(result, Mapping):
                    return dict(result)
            except Exception:
                pass
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


def bounded_limit(value: Any, *, default: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT) -> int:
    limit = safe_int(value, default)

    if limit <= 0:
        return default

    return min(limit, max_limit)


def safe_offset(value: Any) -> int:
    return max(0, safe_int(value, 0))


def object_id(value: Any) -> Any:
    data = to_mapping(value)

    return first_non_empty(
        data.get("id"),
        data.get("pk"),
        data.get("uuid"),
        data.get("family_db_id"),
    )


def listify(value: Any) -> List[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    return [value]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DbBlockSummaryBuilderOptions:
    """
    Optionen für DB-Block-Summary-Building.

    include_unpublished / include_deleted:
        Builder-seitige Filterung. Normalerweise sollte das Repository bereits
        korrekt filtern; diese Optionen bleiben für Sicherheit und Tests.

    include_payload / include_metadata:
        Steuert die API-Ausgabe.

    sort_field / sort_direction:
        Sortierung nach normalisierten Summary-Feldern.

    limit / offset:
        Pagination auf Builder-Ebene.
    """

    include_unpublished: bool = False
    include_deleted: bool = False
    enabled_only: bool = True

    include_payload: bool = DEFAULT_INCLUDE_PAYLOAD
    include_metadata: bool = DEFAULT_INCLUDE_METADATA
    include_assets: bool = DEFAULT_INCLUDE_ASSETS
    include_revision: bool = DEFAULT_INCLUDE_REVISION

    sort_field: str = DEFAULT_SORT_FIELD
    sort_direction: str = DEFAULT_SORT_DIRECTION

    limit: int = DEFAULT_LIMIT
    offset: int = 0

    source: str = DEFAULT_SOURCE

    def normalized(self) -> "DbBlockSummaryBuilderOptions":
        return DbBlockSummaryBuilderOptions(
            include_unpublished=bool(self.include_unpublished),
            include_deleted=bool(self.include_deleted),
            enabled_only=bool(self.enabled_only),
            include_payload=bool(self.include_payload),
            include_metadata=bool(self.include_metadata),
            include_assets=bool(self.include_assets),
            include_revision=bool(self.include_revision),
            sort_field=normalize_sort_field(self.sort_field),
            sort_direction=normalize_sort_direction(self.sort_direction),
            limit=bounded_limit(self.limit),
            offset=safe_offset(self.offset),
            source=normalize_string(self.source) or DEFAULT_SOURCE,
        )


@dataclass
class DbBlockSummarySourceBundle:
    """
    Bündelt Repository-Daten zu einer Family.

    Unterstützt Formen:
        - family only
        - family + latest_revision
        - family + assets
        - family + variants/documents metadata
    """

    family: Any
    latest_revision: Any = None
    assets: List[Any] = field(default_factory=list)
    variants: List[Any] = field(default_factory=list)
    documents: List[Any] = field(default_factory=list)
    issues: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> "DbBlockSummarySourceBundle":
        if isinstance(value, cls):
            return value

        data = to_mapping(value)

        # Repository-Detailform.
        if "family" in data:
            return cls(
                family=data.get("family"),
                latest_revision=first_non_empty(
                    data.get("latest_revision"),
                    data.get("revision"),
                ),
                assets=listify(data.get("assets")),
                variants=listify(data.get("variants")),
                documents=listify(data.get("documents")),
                issues=listify(data.get("issues")),
                metadata=dict(data.get("metadata") or data.get("meta") or {}),
            )

        # Bereits flache Family/Summary.
        return cls(
            family=value,
            latest_revision=first_non_empty(
                data.get("latest_revision"),
                data.get("revision"),
            ),
            assets=listify(data.get("assets")),
            variants=listify(data.get("variants")),
            documents=listify(data.get("documents")),
            issues=listify(data.get("issues")),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )


@dataclass
class DbBlockSummaryBuildResult:
    """Ergebnis eines Summary-Builds."""

    ok: bool = True
    status: str = DbBlockSummaryStatus.OK.value
    items: List[Any] = field(default_factory=list)
    invalid_items: List[Any] = field(default_factory=list)
    skipped_items: List[Any] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    filters: Dict[str, Any] = field(default_factory=dict)
    pagination: Dict[str, Any] = field(default_factory=dict)
    source: str = DEFAULT_SOURCE
    generated_at: datetime = field(default_factory=utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(
        self,
        *,
        include_payload: bool = DEFAULT_INCLUDE_PAYLOAD,
        include_metadata: bool = DEFAULT_INCLUDE_METADATA,
        include_assets: bool = DEFAULT_INCLUDE_ASSETS,
        include_revision: bool = DEFAULT_INCLUDE_REVISION,
    ) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "count": len(self.items),
            "items": [
                summary_to_dict(
                    item,
                    include_payload=include_payload,
                    include_metadata=include_metadata,
                    include_assets=include_assets,
                    include_revision=include_revision,
                )
                for item in self.items
            ],
            "invalid_count": len(self.invalid_items),
            "skipped_count": len(self.skipped_items),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "stats": json_safe(self.stats),
            "filters": json_safe(self.filters),
            "pagination": json_safe(self.pagination),
            "source": self.source,
            "generated_at": safe_isoformat(self.generated_at),
            "metadata": json_safe(self.metadata),
            "warnings": json_safe(self.warnings),
            "errors": json_safe(self.errors),
        }


# ---------------------------------------------------------------------------
# Domain summary builders
# ---------------------------------------------------------------------------


def _require_publication_domain() -> None:
    if _PUBLICATION_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Publication domain models are not available: "
            f"{_PUBLICATION_IMPORT_ERROR.__class__.__name__}: {_PUBLICATION_IMPORT_ERROR}"
        )


def build_asset_refs(assets: Iterable[Any]) -> List[Any]:
    """Normalisiert Asset-Objekte in PublishedAssetRef-Objekte."""

    _require_publication_domain()

    result = []

    for asset in assets:
        if PublishedAssetRef is not None and isinstance(asset, PublishedAssetRef):
            result.append(asset)
        else:
            result.append(PublishedAssetRef.from_mapping(asset))  # type: ignore[union-attr]

    return result


def find_asset_by_role(assets: Iterable[Any], roles: Sequence[str]) -> Any:
    """Findet erstes Asset mit passender Rolle."""

    role_set = {str(role).strip().lower() for role in roles if str(role).strip()}

    for asset in build_asset_refs(assets):
        role = str(getattr(asset, "role", "") or "").strip().lower()

        if role in role_set:
            return asset

    return None


def infer_validation_summary(
    family: Any,
    *,
    latest_revision: Any = None,
    issues: Optional[Iterable[Any]] = None,
) -> Any:
    """Baut PublishedValidationSummary aus Family/Revision/Issues."""

    _require_publication_domain()

    family_data = to_mapping(family)
    revision_data = to_mapping(latest_revision)

    validation_payload = first_non_empty(
        family_data.get("validation"),
        family_data.get("validation_payload"),
        revision_data.get("validation"),
        revision_data.get("validation_payload"),
        {},
    )

    issue_items = list(issues or [])
    warning_count = 0
    error_count = 0
    fatal_count = 0

    for issue in issue_items:
        issue_data = to_mapping(issue)
        severity = str(first_non_empty(issue_data.get("severity"), issue_data.get("level"), "")).lower()

        if severity == "warning":
            warning_count += 1
        elif severity == "fatal":
            fatal_count += 1
        elif severity == "error":
            error_count += 1

    validation_data = to_mapping(validation_payload)
    validation_data.setdefault("issue_count", len(issue_items))
    validation_data.setdefault("warning_count", warning_count)
    validation_data.setdefault("error_count", error_count)
    validation_data.setdefault("fatal_count", fatal_count)

    if not validation_data.get("status"):
        validation_data["status"] = "valid" if error_count == 0 and fatal_count == 0 else "invalid"

    return PublishedValidationSummary.from_mapping(validation_data)  # type: ignore[union-attr]


def build_summary_from_db_bundle(
    bundle: DbBlockSummarySourceBundle,
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
) -> Any:
    """Baut PublishedFamilySummary aus einem SourceBundle."""

    _require_publication_domain()

    options = (options or DbBlockSummaryBuilderOptions()).normalized()

    family_data = to_mapping(bundle.family)
    revision_data = to_mapping(bundle.latest_revision)

    asset_refs = build_asset_refs(bundle.assets)
    icon = find_asset_by_role(asset_refs, ("icon",))
    preview = find_asset_by_role(asset_refs, ("preview", "thumbnail"))

    if bundle.latest_revision is not None:
        family_data["latest_revision"] = PublishedRevisionSummary.from_mapping(revision_data).to_dict()  # type: ignore[union-attr]

    if icon is not None:
        family_data["icon"] = icon.to_dict()

    if preview is not None:
        family_data["preview"] = preview.to_dict()

    if not family_data.get("validation"):
        family_data["validation"] = infer_validation_summary(
            bundle.family,
            latest_revision=bundle.latest_revision,
            issues=bundle.issues,
        ).to_dict()

    if not family_data.get("variant_count"):
        family_data["variant_count"] = len(bundle.variants)

    if not family_data.get("asset_count"):
        family_data["asset_count"] = len(bundle.assets)

    if not family_data.get("document_count"):
        family_data["document_count"] = len(bundle.documents)

    family_data.setdefault("source", options.source)

    return PublishedFamilySummary.from_mapping(family_data)  # type: ignore[union-attr]


def build_summary_from_db_row(
    row: Any,
    *,
    latest_revision: Any = None,
    assets: Optional[Iterable[Any]] = None,
    variants: Optional[Iterable[Any]] = None,
    documents: Optional[Iterable[Any]] = None,
    issues: Optional[Iterable[Any]] = None,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
) -> Any:
    """Baut PublishedFamilySummary aus einer DB-Zeile oder flachen Repository-Antwort."""

    if isinstance(row, DbBlockSummarySourceBundle):
        bundle = row
    else:
        row_data = to_mapping(row)

        if "family" in row_data:
            bundle = DbBlockSummarySourceBundle.from_any(row)
        else:
            bundle = DbBlockSummarySourceBundle(
                family=row,
                latest_revision=latest_revision,
                assets=list(assets or []),
                variants=list(variants or []),
                documents=list(documents or []),
                issues=list(issues or []),
            )

    return build_summary_from_db_bundle(
        bundle,
        options=options,
    )


def build_summaries_from_db_rows(
    rows: Iterable[Any],
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
) -> List[Any]:
    """Baut PublishedFamilySummary-Liste aus DB-/Repository-Rows."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()
    summaries: List[Any] = []

    for row in rows:
        summary = build_summary_from_db_row(
            row,
            options=options,
        )
        summaries.append(summary)

    return summaries


# ---------------------------------------------------------------------------
# Filtering / sorting / pagination
# ---------------------------------------------------------------------------


def summary_is_published(summary: Any) -> bool:
    return bool(getattr(summary, "is_published", False))


def summary_is_deleted(summary: Any) -> bool:
    return bool(getattr(summary, "is_deleted", False))


def summary_enabled(summary: Any) -> bool:
    return bool(getattr(summary, "enabled", True))


def filter_summaries(
    summaries: Iterable[Any],
    *,
    domain: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    object_kind: Optional[str] = None,
    q: Optional[str] = None,
    include_unpublished: bool = False,
    include_deleted: bool = False,
    enabled_only: bool = True,
) -> List[Any]:
    """Builder-seitige Filterung für bereits geladene Summaries."""

    domain_norm = normalize_slug(domain)
    category_norm = normalize_slug(category)
    subcategory_norm = normalize_slug(subcategory)
    object_kind_norm = normalize_string(object_kind)
    query = normalize_string(q)

    result: List[Any] = []

    for item in summaries:
        if not include_unpublished and not summary_is_published(item):
            continue

        if not include_deleted and summary_is_deleted(item):
            continue

        if enabled_only and not summary_enabled(item):
            continue

        if domain_norm and getattr(item, "domain", None) != domain_norm:
            continue

        if category_norm and getattr(item, "category", None) != category_norm:
            continue

        if subcategory_norm and getattr(item, "subcategory", None) != subcategory_norm:
            continue

        if object_kind_norm and getattr(item, "object_kind", None) != object_kind_norm:
            continue

        if query:
            haystack = " ".join(
                str(value or "")
                for value in (
                    getattr(item, "label", None),
                    getattr(item, "name", None),
                    getattr(item, "description", None),
                    getattr(item, "family_id", None),
                    getattr(item, "package_id", None),
                    getattr(item, "vplib_uid", None),
                    getattr(item, "domain", None),
                    getattr(item, "category", None),
                    getattr(item, "subcategory", None),
                    getattr(item, "object_kind", None),
                )
            ).lower()

            if query.lower() not in haystack:
                continue

        result.append(item)

    return result


def summary_sort_key(summary: Any, sort_field: str) -> Tuple[Any, ...]:
    field = normalize_sort_field(sort_field)

    if field == DbBlockSummarySortField.TAXONOMY_LABEL.value:
        return (
            getattr(summary, "domain", None) or "",
            getattr(summary, "category", None) or "",
            getattr(summary, "subcategory", None) or "",
            getattr(summary, "label", None) or "",
            getattr(summary, "family_id", None) or "",
        )

    if field == DbBlockSummarySortField.LABEL.value:
        return (
            getattr(summary, "label", None) or "",
            getattr(summary, "family_id", None) or "",
        )

    if field == DbBlockSummarySortField.FAMILY_ID.value:
        return (getattr(summary, "family_id", None) or "",)

    if field == DbBlockSummarySortField.VPLIB_UID.value:
        return (getattr(summary, "vplib_uid", None) or "",)

    if field == DbBlockSummarySortField.DOMAIN.value:
        return (
            getattr(summary, "domain", None) or "",
            getattr(summary, "category", None) or "",
            getattr(summary, "subcategory", None) or "",
        )

    if field == DbBlockSummarySortField.CATEGORY.value:
        return (
            getattr(summary, "category", None) or "",
            getattr(summary, "subcategory", None) or "",
            getattr(summary, "label", None) or "",
        )

    if field == DbBlockSummarySortField.SUBCATEGORY.value:
        return (
            getattr(summary, "subcategory", None) or "",
            getattr(summary, "label", None) or "",
        )

    if field == DbBlockSummarySortField.OBJECT_KIND.value:
        return (
            getattr(summary, "object_kind", None) or "",
            getattr(summary, "label", None) or "",
        )

    if field == DbBlockSummarySortField.PUBLISHED_AT.value:
        return (
            safe_isoformat(getattr(summary, "published_at", None)) or "",
            getattr(summary, "label", None) or "",
        )

    if field == DbBlockSummarySortField.UPDATED_AT.value:
        return (
            safe_isoformat(getattr(summary, "updated_at", None)) or "",
            getattr(summary, "label", None) or "",
        )

    return (
        getattr(summary, "label", None) or "",
        getattr(summary, "family_id", None) or "",
    )


def sort_summaries(
    summaries: Iterable[Any],
    *,
    sort_field: str = DEFAULT_SORT_FIELD,
    sort_direction: str = DEFAULT_SORT_DIRECTION,
) -> List[Any]:
    """Sortiert Summaries stabil."""

    direction = normalize_sort_direction(sort_direction)

    return sorted(
        list(summaries),
        key=lambda item: summary_sort_key(item, sort_field),
        reverse=direction == "desc",
    )


def paginate_summaries(
    summaries: Sequence[Any],
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Paginierte Summary-Liste plus Pagination-Payload."""

    resolved_limit = bounded_limit(limit)
    resolved_offset = safe_offset(offset)
    total = len(summaries)

    items = list(summaries[resolved_offset : resolved_offset + resolved_limit])

    return items, {
        "limit": resolved_limit,
        "offset": resolved_offset,
        "returned": len(items),
        "total": total,
        "has_more": resolved_offset + len(items) < total,
        "next_offset": resolved_offset + len(items) if resolved_offset + len(items) < total else None,
    }


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def summary_to_dict(
    summary: Any,
    *,
    include_payload: bool = DEFAULT_INCLUDE_PAYLOAD,
    include_metadata: bool = DEFAULT_INCLUDE_METADATA,
    include_assets: bool = DEFAULT_INCLUDE_ASSETS,
    include_revision: bool = DEFAULT_INCLUDE_REVISION,
) -> Dict[str, Any]:
    """Serialisiert Summary robust."""

    if hasattr(summary, "to_dict") and callable(summary.to_dict):
        try:
            return summary.to_dict(
                include_payload=include_payload,
                include_metadata=include_metadata,
                include_assets=include_assets,
                include_revision=include_revision,
            )
        except TypeError:
            try:
                return summary.to_dict()
            except Exception:
                pass

    return json_safe(to_mapping(summary))


def build_block_summary_result_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbBlockSummaryBuildResult:
    """Baut DbBlockSummaryBuildResult aus normalisierten Summaries."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()
    filters_data = dict(filters or {})

    filtered = filter_summaries(
        summaries,
        domain=filters_data.get("domain"),
        category=filters_data.get("category"),
        subcategory=filters_data.get("subcategory"),
        object_kind=filters_data.get("object_kind"),
        q=filters_data.get("q"),
        include_unpublished=options.include_unpublished,
        include_deleted=options.include_deleted,
        enabled_only=options.enabled_only,
    )

    sorted_items = sort_summaries(
        filtered,
        sort_field=options.sort_field,
        sort_direction=options.sort_direction,
    )

    paginated_items, pagination = paginate_summaries(
        sorted_items,
        limit=options.limit,
        offset=options.offset,
    )

    if PublishedLibraryStats is not None:
        stats = PublishedLibraryStats.from_families(sorted_items).to_dict()  # type: ignore[union-attr]
    else:
        stats = {
            "total_count": len(sorted_items),
        }

    status = DbBlockSummaryStatus.OK.value if paginated_items else DbBlockSummaryStatus.EMPTY.value

    return DbBlockSummaryBuildResult(
        ok=True,
        status=status,
        items=paginated_items,
        stats=stats,
        filters={
            **filters_data,
            "include_unpublished": options.include_unpublished,
            "include_deleted": options.include_deleted,
            "enabled_only": options.enabled_only,
            "sort_field": options.sort_field,
            "sort_direction": options.sort_direction,
        },
        pagination=pagination,
        source=options.source,
        metadata=dict(metadata or {}),
    )


def build_block_summary_result_from_db_rows(
    rows: Iterable[Any],
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbBlockSummaryBuildResult:
    """Baut DbBlockSummaryBuildResult direkt aus DB-/Repository-Rows."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()
    summaries = build_summaries_from_db_rows(rows, options=options)

    return build_block_summary_result_from_summaries(
        summaries,
        options=options,
        filters=filters,
        metadata=metadata,
    )


def build_blocks_response_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Blocks-Response aus PublishedFamilySummary-Liste."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()

    result = build_block_summary_result_from_summaries(
        summaries,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    return result.to_dict(
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
        include_assets=options.include_assets,
        include_revision=options.include_revision,
    )


def build_blocks_response_from_db_rows(
    rows: Iterable[Any],
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Blocks-Response direkt aus DB-/Repository-Rows."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()

    result = build_block_summary_result_from_db_rows(
        rows,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    return result.to_dict(
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
        include_assets=options.include_assets,
        include_revision=options.include_revision,
    )


def build_single_summary_dict(
    row: Any,
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
) -> Dict[str, Any]:
    """Baut einzelnes Summary-Dict aus DB-/Repository-Row."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()

    summary = build_summary_from_db_row(
        row,
        options=options,
    )

    return summary_to_dict(
        summary,
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
        include_assets=options.include_assets,
        include_revision=options.include_revision,
    )


def build_empty_blocks_response(
    *,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Leere Blocks-Response."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()

    result = DbBlockSummaryBuildResult(
        ok=True,
        status=DbBlockSummaryStatus.EMPTY.value,
        items=[],
        stats={
            "total_count": 0,
            "published_count": 0,
            "variant_count": 0,
            "asset_count": 0,
            "document_count": 0,
        },
        filters=dict(filters or {}),
        pagination={
            "limit": options.limit,
            "offset": options.offset,
            "returned": 0,
            "total": 0,
            "has_more": False,
            "next_offset": None,
        },
        source=options.source,
        metadata=dict(metadata or {}),
    )

    return result.to_dict(
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
        include_assets=options.include_assets,
        include_revision=options.include_revision,
    )


def build_error_blocks_response(
    error: Any,
    *,
    message: Optional[str] = None,
    options: Optional[DbBlockSummaryBuilderOptions] = None,
) -> Dict[str, Any]:
    """Fehlerhafte Blocks-Response."""

    options = (options or DbBlockSummaryBuilderOptions()).normalized()

    return {
        "ok": False,
        "status": DbBlockSummaryStatus.ERROR.value,
        "message": message or str(error),
        "error_type": error.__class__.__name__ if error is not None else None,
        "count": 0,
        "items": [],
        "stats": {},
        "filters": {},
        "pagination": {
            "limit": options.limit,
            "offset": options.offset,
            "returned": 0,
            "total": 0,
            "has_more": False,
            "next_offset": None,
        },
        "source": options.source,
        "generated_at": safe_isoformat(utcnow()),
    }


# ---------------------------------------------------------------------------
# Options builders
# ---------------------------------------------------------------------------


def build_options_from_query(
    query: Optional[Mapping[str, Any]] = None,
    *,
    defaults: Optional[DbBlockSummaryBuilderOptions] = None,
) -> DbBlockSummaryBuilderOptions:
    """
    Baut Builder-Optionen aus Query-/Request-Parametern.

    Diese Funktion importiert kein Flask. Übergib request.args als Mapping.
    """

    data = dict(query or {})
    defaults = defaults or DbBlockSummaryBuilderOptions()

    return DbBlockSummaryBuilderOptions(
        include_unpublished=safe_bool(
            first_non_empty(data.get("include_unpublished"), data.get("unpublished")),
            defaults.include_unpublished,
        ),
        include_deleted=safe_bool(
            first_non_empty(data.get("include_deleted"), data.get("deleted")),
            defaults.include_deleted,
        ),
        enabled_only=safe_bool(
            first_non_empty(data.get("enabled_only"), data.get("enabled")),
            defaults.enabled_only,
        ),
        include_payload=safe_bool(
            first_non_empty(data.get("include_payload"), data.get("payload")),
            defaults.include_payload,
        ),
        include_metadata=safe_bool(
            first_non_empty(data.get("include_metadata"), data.get("metadata")),
            defaults.include_metadata,
        ),
        include_assets=safe_bool(
            first_non_empty(data.get("include_assets"), data.get("assets")),
            defaults.include_assets,
        ),
        include_revision=safe_bool(
            first_non_empty(data.get("include_revision"), data.get("revision")),
            defaults.include_revision,
        ),
        sort_field=first_non_empty(data.get("sort"), data.get("sort_field"), defaults.sort_field),
        sort_direction=first_non_empty(data.get("direction"), data.get("sort_direction"), defaults.sort_direction),
        limit=safe_int(data.get("limit"), defaults.limit),
        offset=safe_int(data.get("offset"), defaults.offset),
        source=first_non_empty(data.get("source"), defaults.source),
    ).normalized()


def build_filters_from_query(query: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Extrahiert fachliche Blocks-Filter aus Query-Mapping."""

    data = dict(query or {})

    return {
        "domain": normalize_slug(data.get("domain")),
        "category": normalize_slug(data.get("category")),
        "subcategory": normalize_slug(data.get("subcategory")),
        "object_kind": normalize_string(data.get("object_kind")),
        "q": normalize_string(first_non_empty(data.get("q"), data.get("search"))),
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def get_db_block_summary_builder_health() -> Dict[str, Any]:
    """Leichter Health-Check für diesen Builder."""

    return {
        "ok": _PUBLICATION_IMPORT_ERROR is None,
        "status": "ok" if _PUBLICATION_IMPORT_ERROR is None else "error",
        "component": DB_BLOCK_SUMMARY_COMPONENT_NAME,
        "builder": DB_BLOCK_SUMMARY_BUILDER_NAME,
        "api_version": DB_BLOCK_SUMMARY_API_VERSION,
        "model_version": DB_BLOCK_SUMMARY_MODEL_VERSION,
        "version": __version__,
        "publication_domain_available": _PUBLICATION_IMPORT_ERROR is None,
        "publication_domain_error": None
        if _PUBLICATION_IMPORT_ERROR is None
        else {
            "type": _PUBLICATION_IMPORT_ERROR.__class__.__name__,
            "message": str(_PUBLICATION_IMPORT_ERROR),
        },
        "defaults": {
            "limit": DEFAULT_LIMIT,
            "max_limit": MAX_LIMIT,
            "sort_field": DEFAULT_SORT_FIELD,
            "sort_direction": DEFAULT_SORT_DIRECTION,
            "source": DEFAULT_SOURCE,
        },
        "enums": {
            "status": list(DbBlockSummaryStatus.values()),
            "sort_field": list(DbBlockSummarySortField.values()),
        },
        "cache": {
            "normalize_sort_field": normalize_sort_field.cache_info()._asdict(),
            "normalize_sort_direction": normalize_sort_direction.cache_info()._asdict(),
            "normalize_slug": normalize_slug.cache_info()._asdict(),
            "normalize_string_cached": normalize_string_cached.cache_info()._asdict(),
        },
    }


def assert_db_block_summary_builder_ready() -> Dict[str, Any]:
    """Wirft RuntimeError, wenn der Builder nicht bereit ist."""

    health = get_db_block_summary_builder_health()

    if not health.get("ok"):
        raise RuntimeError(
            "DB block summary builder is not ready: "
            f"{health.get('publication_domain_error')}"
        )

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "DB_BLOCK_SUMMARY_BUILDER_NAME",
    "DB_BLOCK_SUMMARY_COMPONENT_NAME",
    "DB_BLOCK_SUMMARY_API_VERSION",
    "DB_BLOCK_SUMMARY_MODEL_VERSION",

    # Defaults
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "DEFAULT_SORT_FIELD",
    "DEFAULT_SORT_DIRECTION",
    "DEFAULT_INCLUDE_PAYLOAD",
    "DEFAULT_INCLUDE_METADATA",
    "DEFAULT_INCLUDE_ASSETS",
    "DEFAULT_INCLUDE_REVISION",
    "DEFAULT_SOURCE",

    # Enums
    "DbBlockSummaryStatus",
    "DbBlockSummarySortField",

    # Options/result models
    "DbBlockSummaryBuilderOptions",
    "DbBlockSummarySourceBundle",
    "DbBlockSummaryBuildResult",

    # Generic helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_string",
    "normalize_slug",
    "normalize_vplib_uid",
    "normalize_taxonomy_path",
    "normalize_sort_field",
    "normalize_sort_direction",
    "first_non_empty",
    "json_safe",
    "to_mapping",
    "bounded_limit",
    "safe_offset",
    "object_id",
    "listify",
    "clear_db_block_summary_builder_caches",

    # Domain builders
    "build_asset_refs",
    "find_asset_by_role",
    "infer_validation_summary",
    "build_summary_from_db_bundle",
    "build_summary_from_db_row",
    "build_summaries_from_db_rows",

    # Filtering/sorting/pagination
    "summary_is_published",
    "summary_is_deleted",
    "summary_enabled",
    "filter_summaries",
    "summary_sort_key",
    "sort_summaries",
    "paginate_summaries",

    # Response builders
    "summary_to_dict",
    "build_block_summary_result_from_summaries",
    "build_block_summary_result_from_db_rows",
    "build_blocks_response_from_summaries",
    "build_blocks_response_from_db_rows",
    "build_single_summary_dict",
    "build_empty_blocks_response",
    "build_error_blocks_response",

    # Query helpers
    "build_options_from_query",
    "build_filters_from_query",

    # Health
    "get_db_block_summary_builder_health",
    "assert_db_block_summary_builder_ready",
]