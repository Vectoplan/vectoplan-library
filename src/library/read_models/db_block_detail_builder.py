# services/vectoplan-library/src/library/read_models/db_block_detail_builder.py
"""
DB-Block-Detail-Builder für die VECTOPLAN Creative Library.

Diese Datei baut API-nahe Detail-Responses aus DB-/Repository-Daten.

Zielpfad:

    creative_library Tabellen
        → repository
        → library_published_service
        → db_block_detail_builder
        → GET /api/v1/vplib/library/blocks/<block_id>

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Session
- keine Datenbankzugriffe
- keine Schreiboperationen
- kein Filesystem-Scan
- keine Scanner-/Reader-/Validator-Imports
- tolerant gegenüber SQLAlchemy-Objekten, Dicts, Dataclasses und Domainmodellen
- kompatibel mit der bisherigen Detailresponse-Struktur
- primär auf veröffentlichte DB-Daten ausgelegt

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id
    variant_id

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
        PublishedFamilyDetail,
        PublishedFamilySummary,
        PublishedRevisionSummary,
        PublishedValidationSummary,
        PublishedVariantSummary,
        build_error_publication_response,
        build_not_found_publication_response,
    )
except Exception as import_error:  # pragma: no cover - defensive import fallback
    DEFAULT_PUBLICATION_SOURCE = "database"

    PublishedAssetRef = None  # type: ignore
    PublishedFamilyDetail = None  # type: ignore
    PublishedFamilySummary = None  # type: ignore
    PublishedRevisionSummary = None  # type: ignore
    PublishedValidationSummary = None  # type: ignore
    PublishedVariantSummary = None  # type: ignore
    build_error_publication_response = None  # type: ignore
    build_not_found_publication_response = None  # type: ignore
    _PUBLICATION_IMPORT_ERROR = import_error
else:
    _PUBLICATION_IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

DB_BLOCK_DETAIL_BUILDER_NAME = "db_block_detail_builder"
DB_BLOCK_DETAIL_COMPONENT_NAME = "creative_library_db_block_detail_builder"
DB_BLOCK_DETAIL_API_VERSION = "v1"
DB_BLOCK_DETAIL_MODEL_VERSION = "db-block-detail.v1"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SOURCE = DEFAULT_PUBLICATION_SOURCE or "database"

DEFAULT_INCLUDE_RAW_DOCUMENTS = False
DEFAULT_INCLUDE_PAYLOAD = True
DEFAULT_INCLUDE_METADATA = True
DEFAULT_INCLUDE_DOCUMENTS = True
DEFAULT_INCLUDE_ASSETS = True
DEFAULT_INCLUDE_VARIANTS = True
DEFAULT_INCLUDE_VALIDATION = True

DEFAULT_DOCUMENT_LIMIT = 10000
DEFAULT_VARIANT_LIMIT = 1000
DEFAULT_ASSET_LIMIT = 1000
DEFAULT_ISSUE_LIMIT = 1000


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DbBlockDetailStatus(str, Enum):
    """Status eines Detail-Builds."""

    OK = "ok"
    NOT_FOUND = "not_found"
    PARTIAL = "partial"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class DbDocumentGroup(str, Enum):
    """Bekannte Dokumentgruppen eines VPLIB-Packages."""

    ROOT = "root"
    FAMILY = "family"
    VARIANTS = "variants"
    EDITOR = "editor"
    RENDER = "render"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    MANUFACTURER = "manufacturer"
    ANALYSIS = "analysis"
    DYNAMIC = "dynamic"
    DOCS = "docs"
    TESTS = "tests"
    ASSETS = "assets"
    UNKNOWN = "unknown"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1024)
def normalize_document_path(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip().replace("\\", "/")

    while "//" in text:
        text = text.replace("//", "/")

    text = text.lstrip("/")

    return text or None


@lru_cache(maxsize=1024)
def document_group_for_path(value: Any) -> str:
    path = normalize_document_path(value)

    if not path:
        return DbDocumentGroup.UNKNOWN.value

    if "/" not in path:
        return DbDocumentGroup.ROOT.value

    prefix = path.split("/", 1)[0].strip().lower()

    if prefix in DbDocumentGroup.values():
        return prefix

    return DbDocumentGroup.UNKNOWN.value


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


def clear_db_block_detail_builder_caches() -> Dict[str, Any]:
    """Leert alle lokalen Caches dieses Builders."""

    normalize_document_path.cache_clear()
    document_group_for_path.cache_clear()
    normalize_slug.cache_clear()
    normalize_string_cached.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_document_path",
            "document_group_for_path",
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


def truncate_list(values: Sequence[Any], limit: int) -> List[Any]:
    if limit <= 0:
        return []

    return list(values[:limit])


def object_id(value: Any) -> Any:
    data = to_mapping(value)

    return first_non_empty(
        data.get("id"),
        data.get("pk"),
        data.get("uuid"),
        data.get("family_db_id"),
        data.get("revision_db_id"),
    )


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DbBlockDetailBuilderOptions:
    """Optionen für DB-Block-Detail-Building."""

    include_raw_documents: bool = DEFAULT_INCLUDE_RAW_DOCUMENTS
    include_payload: bool = DEFAULT_INCLUDE_PAYLOAD
    include_metadata: bool = DEFAULT_INCLUDE_METADATA
    include_documents: bool = DEFAULT_INCLUDE_DOCUMENTS
    include_assets: bool = DEFAULT_INCLUDE_ASSETS
    include_variants: bool = DEFAULT_INCLUDE_VARIANTS
    include_validation: bool = DEFAULT_INCLUDE_VALIDATION

    document_limit: int = DEFAULT_DOCUMENT_LIMIT
    variant_limit: int = DEFAULT_VARIANT_LIMIT
    asset_limit: int = DEFAULT_ASSET_LIMIT
    issue_limit: int = DEFAULT_ISSUE_LIMIT

    source: str = DEFAULT_SOURCE

    def normalized(self) -> "DbBlockDetailBuilderOptions":
        return DbBlockDetailBuilderOptions(
            include_raw_documents=bool(self.include_raw_documents),
            include_payload=bool(self.include_payload),
            include_metadata=bool(self.include_metadata),
            include_documents=bool(self.include_documents),
            include_assets=bool(self.include_assets),
            include_variants=bool(self.include_variants),
            include_validation=bool(self.include_validation),
            document_limit=max(0, safe_int(self.document_limit, DEFAULT_DOCUMENT_LIMIT)),
            variant_limit=max(0, safe_int(self.variant_limit, DEFAULT_VARIANT_LIMIT)),
            asset_limit=max(0, safe_int(self.asset_limit, DEFAULT_ASSET_LIMIT)),
            issue_limit=max(0, safe_int(self.issue_limit, DEFAULT_ISSUE_LIMIT)),
            source=normalize_string(self.source) or DEFAULT_SOURCE,
        )


@dataclass
class DbBlockDetailSourceBundle:
    """
    Bündelt Repository-Daten zu einer Family-Detailantwort.

    Unterstützte Repository-Form:
        {
            "family": ...,
            "revision": ...,
            "variants": [...],
            "assets": [...],
            "documents": [...],
            "issues": [...]
        }
    """

    family: Any
    revision: Any = None
    variants: List[Any] = field(default_factory=list)
    assets: List[Any] = field(default_factory=list)
    documents: List[Any] = field(default_factory=list)
    issues: List[Any] = field(default_factory=list)
    raw_documents: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> "DbBlockDetailSourceBundle":
        if isinstance(value, cls):
            return value

        data = to_mapping(value)

        if "family" in data:
            family = data.get("family")
        elif "summary" in data:
            family = data.get("summary")
        else:
            family = value

        revision = first_non_empty(
            data.get("revision"),
            data.get("latest_revision"),
        )

        raw_documents = first_non_empty(
            data.get("raw_documents"),
            data.get("documents_payload"),
            to_mapping(revision).get("raw_documents") if revision is not None else None,
            to_mapping(revision).get("documents") if revision is not None else None,
            {},
        )

        return cls(
            family=family,
            revision=revision,
            variants=listify(data.get("variants")),
            assets=listify(data.get("assets")),
            documents=listify(data.get("documents")),
            issues=listify(data.get("issues")),
            raw_documents=dict(raw_documents or {}),
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )


@dataclass
class DbDocumentEntry:
    """API-nahe Dokumentrepräsentation für Detailantworten."""

    relative_path: Optional[str] = None
    group: str = DbDocumentGroup.UNKNOWN.value
    name: Optional[str] = None
    module: Optional[str] = None
    document_type: Optional[str] = None
    checksum: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Any) -> "DbDocumentEntry":
        data = to_mapping(value)

        relative_path = normalize_document_path(
            first_non_empty(
                data.get("relative_path"),
                data.get("path"),
                data.get("document_path"),
            )
        )

        payload = first_non_empty(
            data.get("payload"),
            data.get("document"),
            {},
        )

        group = first_non_empty(
            data.get("group"),
            data.get("module"),
            document_group_for_path(relative_path),
        )

        return cls(
            relative_path=relative_path,
            group=str(group or DbDocumentGroup.UNKNOWN.value),
            name=first_non_empty(
                data.get("name"),
                relative_path.split("/")[-1] if relative_path else None,
            ),
            module=first_non_empty(data.get("module"), group),
            document_type=first_non_empty(data.get("document_type"), data.get("type")),
            checksum=data.get("checksum"),
            payload=dict(payload or {}) if isinstance(payload, Mapping) else {"value": payload},
            metadata=dict(data.get("metadata") or data.get("meta") or {}),
        )

    def to_dict(self, *, include_payload: bool = True, include_metadata: bool = True) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "path": self.relative_path,
            "group": self.group,
            "name": self.name,
            "module": self.module,
            "document_type": self.document_type,
            "type": self.document_type,
            "checksum": self.checksum,
            "payload": json_safe(self.payload) if include_payload else {},
            "metadata": json_safe(self.metadata) if include_metadata else {},
        }


@dataclass
class DbBlockDetailBuildResult:
    """Ergebnis eines Detail-Builds."""

    ok: bool = True
    status: str = DbBlockDetailStatus.OK.value
    detail: Any = None
    identifier: Optional[str] = None
    source: str = DEFAULT_SOURCE
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(
        self,
        *,
        include_raw_documents: bool = DEFAULT_INCLUDE_RAW_DOCUMENTS,
        include_payload: bool = DEFAULT_INCLUDE_PAYLOAD,
        include_metadata: bool = DEFAULT_INCLUDE_METADATA,
    ) -> Dict[str, Any]:
        if self.detail is None:
            return {
                "ok": self.ok,
                "status": self.status,
                "identifier": self.identifier,
                "source": self.source,
                "warnings": json_safe(self.warnings),
                "errors": json_safe(self.errors),
                "generated_at": safe_isoformat(self.generated_at),
                "metadata": json_safe(self.metadata),
            }

        if hasattr(self.detail, "to_dict") and callable(self.detail.to_dict):
            try:
                payload = self.detail.to_dict(
                    include_raw_documents=include_raw_documents,
                    include_payload=include_payload,
                    include_metadata=include_metadata,
                )
            except TypeError:
                payload = self.detail.to_dict()
        else:
            payload = json_safe(to_mapping(self.detail))

        payload.setdefault("ok", self.ok)
        payload.setdefault("status", self.status)
        payload.setdefault("identifier", self.identifier)
        payload.setdefault("source", self.source)
        payload.setdefault("warnings", json_safe(self.warnings))
        payload.setdefault("errors", json_safe(self.errors))
        payload.setdefault("generated_at", safe_isoformat(self.generated_at))
        payload.setdefault("metadata", json_safe(self.metadata) if include_metadata else {})
        return payload


# ---------------------------------------------------------------------------
# Domain builders
# ---------------------------------------------------------------------------


def _require_publication_domain() -> None:
    if _PUBLICATION_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Publication domain models are not available: "
            f"{_PUBLICATION_IMPORT_ERROR.__class__.__name__}: {_PUBLICATION_IMPORT_ERROR}"
        )


def normalize_asset_refs(assets: Iterable[Any]) -> List[Any]:
    """Normalisiert Asset-Objekte in PublishedAssetRef-Objekte."""

    _require_publication_domain()

    result = []

    for asset in assets:
        if PublishedAssetRef is not None and isinstance(asset, PublishedAssetRef):
            result.append(asset)
        else:
            result.append(PublishedAssetRef.from_mapping(asset))  # type: ignore[union-attr]

    return result


def normalize_variant_refs(variants: Iterable[Any]) -> List[Any]:
    """Normalisiert Varianten in PublishedVariantSummary-Objekte."""

    _require_publication_domain()

    result = []

    for variant in variants:
        if PublishedVariantSummary is not None and isinstance(variant, PublishedVariantSummary):
            result.append(variant)
        else:
            result.append(PublishedVariantSummary.from_mapping(variant))  # type: ignore[union-attr]

    return result


def normalize_revision(revision: Any) -> Any:
    """Normalisiert Revision in PublishedRevisionSummary."""

    _require_publication_domain()

    if revision is None:
        return None

    if PublishedRevisionSummary is not None and isinstance(revision, PublishedRevisionSummary):
        return revision

    return PublishedRevisionSummary.from_mapping(revision)  # type: ignore[union-attr]


def find_asset_by_role(assets: Iterable[Any], roles: Sequence[str]) -> Any:
    """Findet erstes Asset mit passender Rolle."""

    role_set = {str(role).strip().lower() for role in roles if str(role).strip()}

    for asset in normalize_asset_refs(assets):
        role = str(getattr(asset, "role", "") or "").strip().lower()

        if role in role_set:
            return asset

    return None


def build_validation_summary(
    family: Any,
    *,
    revision: Any = None,
    issues: Optional[Iterable[Any]] = None,
) -> Any:
    """Baut PublishedValidationSummary aus Family/Revision/Issues."""

    _require_publication_domain()

    family_data = to_mapping(family)
    revision_data = to_mapping(revision)

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


def normalize_documents(
    documents: Iterable[Any],
    *,
    raw_documents: Optional[Mapping[str, Any]] = None,
) -> List[DbDocumentEntry]:
    """
    Normalisiert Dokumentlisten und ergänzt Dokumente aus raw_documents.

    Repository-Formen:
        - Document rows
        - [{"relative_path": ..., "payload": ...}]
        - raw_documents mapping {path: payload}
    """

    entries: List[DbDocumentEntry] = []
    seen_paths: set[str] = set()

    for document in documents:
        entry = DbDocumentEntry.from_mapping(document)

        if not entry.relative_path:
            continue

        if entry.relative_path in seen_paths:
            continue

        entries.append(entry)
        seen_paths.add(entry.relative_path)

    for path, payload in (raw_documents or {}).items():
        normalized_path = normalize_document_path(path)

        if not normalized_path or normalized_path in seen_paths:
            continue

        entries.append(
            DbDocumentEntry(
                relative_path=normalized_path,
                group=document_group_for_path(normalized_path),
                name=normalized_path.split("/")[-1],
                module=document_group_for_path(normalized_path),
                document_type="json" if normalized_path.endswith(".json") else None,
                payload=dict(payload or {}) if isinstance(payload, Mapping) else {"value": payload},
                metadata={"source": "raw_documents"},
            )
        )
        seen_paths.add(normalized_path)

    return sorted(
        entries,
        key=lambda item: (
            item.group,
            item.relative_path or "",
        ),
    )


def group_documents(entries: Iterable[DbDocumentEntry]) -> Dict[str, List[Dict[str, Any]]]:
    """Gruppiert Dokumente nach VPLIB-Modulgruppe."""

    result: Dict[str, List[Dict[str, Any]]] = {
        group: []
        for group in DbDocumentGroup.values()
    }

    for entry in entries:
        group = entry.group if entry.group in result else DbDocumentGroup.UNKNOWN.value
        result[group].append(entry.to_dict())

    return result


def extract_document_payload_by_path(
    entries: Iterable[DbDocumentEntry],
    path: str,
) -> Dict[str, Any]:
    normalized_path = normalize_document_path(path)

    for entry in entries:
        if entry.relative_path == normalized_path:
            return dict(entry.payload or {})

    return {}


def build_family_summary(
    bundle: DbBlockDetailSourceBundle,
) -> Any:
    """Baut PublishedFamilySummary für die Detailantwort."""

    _require_publication_domain()

    family_data = to_mapping(bundle.family)
    revision = normalize_revision(bundle.revision)

    assets = normalize_asset_refs(bundle.assets)
    icon = find_asset_by_role(assets, ("icon",))
    preview = find_asset_by_role(assets, ("preview", "thumbnail"))

    if revision is not None:
        family_data["latest_revision"] = revision.to_dict()

    if icon is not None:
        family_data["icon"] = icon.to_dict()

    if preview is not None:
        family_data["preview"] = preview.to_dict()

    if not family_data.get("validation"):
        family_data["validation"] = build_validation_summary(
            bundle.family,
            revision=bundle.revision,
            issues=bundle.issues,
        ).to_dict()

    if not family_data.get("variant_count"):
        family_data["variant_count"] = len(bundle.variants)

    if not family_data.get("asset_count"):
        family_data["asset_count"] = len(bundle.assets)

    if not family_data.get("document_count"):
        family_data["document_count"] = len(bundle.documents) or len(bundle.raw_documents)

    family_data.setdefault("source", DEFAULT_SOURCE)

    return PublishedFamilySummary.from_mapping(family_data)  # type: ignore[union-attr]


def build_detail_from_bundle(
    bundle: DbBlockDetailSourceBundle,
    *,
    options: Optional[DbBlockDetailBuilderOptions] = None,
) -> Any:
    """Baut PublishedFamilyDetail aus Repository-Bundle."""

    _require_publication_domain()

    options = (options or DbBlockDetailBuilderOptions()).normalized()

    summary = build_family_summary(bundle)
    revision = normalize_revision(bundle.revision)
    variants = normalize_variant_refs(bundle.variants)
    assets = normalize_asset_refs(bundle.assets)
    documents = normalize_documents(
        bundle.documents,
        raw_documents=bundle.raw_documents,
    )

    validation = build_validation_summary(
        bundle.family,
        revision=bundle.revision,
        issues=bundle.issues,
    )

    raw_documents = dict(bundle.raw_documents or {})

    if not raw_documents and revision is not None:
        revision_data = to_mapping(revision)
        raw_documents = dict(
            first_non_empty(
                revision_data.get("raw_documents"),
                revision_data.get("documents"),
                {},
            )
            or {}
        )

    return PublishedFamilyDetail(  # type: ignore[operator]
        summary=summary,
        revision=revision,
        variants=truncate_list(variants, options.variant_limit),
        assets=truncate_list(assets, options.asset_limit),
        documents=[
            entry.to_dict(
                include_payload=True,
                include_metadata=True,
            )
            for entry in truncate_list(documents, options.document_limit)
        ],
        raw_documents=raw_documents if options.include_raw_documents else {},
        validation=validation,
        payload={
            "document_groups": group_documents(documents),
            "package": build_package_payload(bundle, documents),
            "family": build_family_payload(bundle, documents),
            "profiles": build_profile_payload(bundle, documents),
        },
        metadata={
            **bundle.metadata,
            "source": options.source,
            "builder": DB_BLOCK_DETAIL_BUILDER_NAME,
            "document_count": len(documents),
            "variant_count": len(variants),
            "asset_count": len(assets),
        },
    )


def build_package_payload(
    bundle: DbBlockDetailSourceBundle,
    documents: Iterable[DbDocumentEntry],
) -> Dict[str, Any]:
    """Baut package-ähnlichen Payload aus Revision/Manifest."""

    manifest = extract_document_payload_by_path(documents, "vplib.manifest.json")
    revision_data = to_mapping(bundle.revision)
    family_data = to_mapping(bundle.family)

    return {
        "vplib_uid": first_non_empty(
            manifest.get("vplib_uid"),
            revision_data.get("vplib_uid"),
            family_data.get("vplib_uid"),
        ),
        "family_id": first_non_empty(
            manifest.get("family_id"),
            revision_data.get("family_id"),
            family_data.get("family_id"),
        ),
        "package_id": first_non_empty(
            manifest.get("package_id"),
            revision_data.get("package_id"),
            family_data.get("package_id"),
        ),
        "package_version": first_non_empty(
            manifest.get("package_version"),
            manifest.get("version"),
            revision_data.get("package_version"),
        ),
        "schema_version": first_non_empty(
            manifest.get("schema_version"),
            revision_data.get("schema_version"),
        ),
        "revision_hash": first_non_empty(
            revision_data.get("revision_hash"),
            family_data.get("revision_hash"),
        ),
        "manifest": manifest,
    }


def build_family_payload(
    bundle: DbBlockDetailSourceBundle,
    documents: Iterable[DbDocumentEntry],
) -> Dict[str, Any]:
    """Baut family-ähnlichen Payload aus Family/Identity/Classification."""

    identity = extract_document_payload_by_path(documents, "family/identity.json")
    classification = extract_document_payload_by_path(documents, "family/classification.json")
    family_data = to_mapping(bundle.family)

    return {
        "identity": identity,
        "classification": classification,
        "family_id": first_non_empty(
            identity.get("family_id"),
            family_data.get("family_id"),
        ),
        "label": first_non_empty(
            identity.get("label"),
            identity.get("name"),
            family_data.get("label"),
            family_data.get("name"),
        ),
        "object_kind": first_non_empty(
            identity.get("object_kind"),
            family_data.get("object_kind"),
        ),
    }


def build_profile_payload(
    bundle: DbBlockDetailSourceBundle,
    documents: Iterable[DbDocumentEntry],
) -> Dict[str, Any]:
    """Baut profilartige Gruppierung aus bekannten Dokumenten."""

    groups = {
        "editor": [
            "editor/inventory.json",
            "editor/placement.json",
            "editor/targeting.json",
            "editor/anchors.json",
        ],
        "render": [
            "render/render_variants.json",
            "render/bounds.json",
            "render/materials.json",
        ],
        "physical": [
            "physical/base.json",
            "physical/dimensions.json",
            "physical/collision.json",
            "physical/occupancy.json",
        ],
        "material": [
            "material/base.json",
            "material/performance.json",
        ],
        "calculation": [
            "calculation/variables.json",
            "calculation/formulas.json",
            "calculation/quantities.json",
            "calculation/measure_logic.json",
        ],
        "manufacturer": [
            "manufacturer/contract.json",
            "manufacturer/override_slots.json",
        ],
        "dynamic": [
            "dynamic/context_rules.json",
            "dynamic/bindings.json",
            "dynamic/generator.json",
        ],
    }

    payload: Dict[str, Any] = {}

    for group_name, paths in groups.items():
        group_payload: Dict[str, Any] = {}

        for path in paths:
            document = extract_document_payload_by_path(documents, path)

            if document:
                key = path.split("/", 1)[1].removesuffix(".json")
                group_payload[key] = document

        payload[group_name] = group_payload

    return payload


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def build_detail_result_from_db_payload(
    payload: Any,
    *,
    options: Optional[DbBlockDetailBuilderOptions] = None,
    identifier: Optional[str] = None,
) -> DbBlockDetailBuildResult:
    """Baut DbBlockDetailBuildResult aus Repository-Payload."""

    options = (options or DbBlockDetailBuilderOptions()).normalized()

    try:
        bundle = DbBlockDetailSourceBundle.from_any(payload)
        detail = build_detail_from_bundle(
            bundle,
            options=options,
        )

        summary = getattr(detail, "summary", None)
        identifier_value = first_non_empty(
            identifier,
            getattr(summary, "family_id", None),
            getattr(summary, "vplib_uid", None),
            getattr(summary, "package_id", None),
        )

        return DbBlockDetailBuildResult(
            ok=True,
            status=DbBlockDetailStatus.OK.value,
            detail=detail,
            identifier=identifier_value,
            source=options.source,
            metadata={
                "builder": DB_BLOCK_DETAIL_BUILDER_NAME,
            },
        )

    except Exception as exc:
        return DbBlockDetailBuildResult(
            ok=False,
            status=DbBlockDetailStatus.ERROR.value,
            detail=None,
            identifier=identifier,
            source=options.source,
            errors=[
                {
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }
            ],
            metadata={
                "builder": DB_BLOCK_DETAIL_BUILDER_NAME,
            },
        )


def build_detail_response_from_db_payload(
    payload: Any,
    *,
    options: Optional[DbBlockDetailBuilderOptions] = None,
    identifier: Optional[str] = None,
) -> Dict[str, Any]:
    """API-kompatible Detailresponse aus Repository-Payload."""

    options = (options or DbBlockDetailBuilderOptions()).normalized()

    result = build_detail_result_from_db_payload(
        payload,
        options=options,
        identifier=identifier,
    )

    return result.to_dict(
        include_raw_documents=options.include_raw_documents,
        include_payload=options.include_payload,
        include_metadata=options.include_metadata,
    )


def build_not_found_detail_response(
    identifier: Any,
    *,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Not-found Detailresponse."""

    if callable(build_not_found_publication_response):
        return build_not_found_publication_response(
            identifier,
            message=message,
        )

    return {
        "ok": False,
        "status": DbBlockDetailStatus.NOT_FOUND.value,
        "identifier": str(identifier) if identifier is not None else None,
        "message": message or f"Published library item not found: {identifier}",
        "generated_at": safe_isoformat(utcnow()),
    }


def build_error_detail_response(
    error: Any,
    *,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Error Detailresponse."""

    if callable(build_error_publication_response):
        return build_error_publication_response(
            error,
            message=message,
        )

    return {
        "ok": False,
        "status": DbBlockDetailStatus.ERROR.value,
        "message": message or str(error),
        "error_type": error.__class__.__name__ if error is not None else None,
        "generated_at": safe_isoformat(utcnow()),
    }


def build_variants_response_from_db_payload(
    payload: Any,
    *,
    identifier: Optional[str] = None,
    options: Optional[DbBlockDetailBuilderOptions] = None,
) -> Dict[str, Any]:
    """
    Baut API-kompatible Variantenantwort aus Detail-Payload oder Variantenliste.
    """

    options = (options or DbBlockDetailBuilderOptions()).normalized()

    data = to_mapping(payload)

    if "variants" in data:
        raw_variants = data.get("variants") or []
    elif isinstance(payload, (list, tuple)):
        raw_variants = list(payload)
    else:
        bundle = DbBlockDetailSourceBundle.from_any(payload)
        raw_variants = bundle.variants

    variants = normalize_variant_refs(raw_variants)
    variants = truncate_list(variants, options.variant_limit)

    return {
        "ok": True,
        "status": "ok",
        "block_id": identifier,
        "identifier": identifier,
        "count": len(variants),
        "variants": [
            item.to_dict()
            for item in variants
        ],
        "source": options.source,
        "generated_at": safe_isoformat(utcnow()),
    }


# ---------------------------------------------------------------------------
# Options builders
# ---------------------------------------------------------------------------


def build_options_from_query(
    query: Optional[Mapping[str, Any]] = None,
    *,
    defaults: Optional[DbBlockDetailBuilderOptions] = None,
) -> DbBlockDetailBuilderOptions:
    """
    Baut Builder-Optionen aus Query-/Request-Parametern.

    Diese Funktion importiert kein Flask. Übergib request.args als Mapping.
    """

    data = dict(query or {})
    defaults = defaults or DbBlockDetailBuilderOptions()

    return DbBlockDetailBuilderOptions(
        include_raw_documents=safe_bool(
            first_non_empty(data.get("include_raw_documents"), data.get("raw_documents")),
            defaults.include_raw_documents,
        ),
        include_payload=safe_bool(
            first_non_empty(data.get("include_payload"), data.get("payload")),
            defaults.include_payload,
        ),
        include_metadata=safe_bool(
            first_non_empty(data.get("include_metadata"), data.get("metadata")),
            defaults.include_metadata,
        ),
        include_documents=safe_bool(
            first_non_empty(data.get("include_documents"), data.get("documents")),
            defaults.include_documents,
        ),
        include_assets=safe_bool(
            first_non_empty(data.get("include_assets"), data.get("assets")),
            defaults.include_assets,
        ),
        include_variants=safe_bool(
            first_non_empty(data.get("include_variants"), data.get("variants")),
            defaults.include_variants,
        ),
        include_validation=safe_bool(
            first_non_empty(data.get("include_validation"), data.get("validation")),
            defaults.include_validation,
        ),
        document_limit=safe_int(data.get("document_limit"), defaults.document_limit),
        variant_limit=safe_int(data.get("variant_limit"), defaults.variant_limit),
        asset_limit=safe_int(data.get("asset_limit"), defaults.asset_limit),
        issue_limit=safe_int(data.get("issue_limit"), defaults.issue_limit),
        source=first_non_empty(data.get("source"), defaults.source),
    ).normalized()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def get_db_block_detail_builder_health() -> Dict[str, Any]:
    """Leichter Health-Check für diesen Builder."""

    return {
        "ok": _PUBLICATION_IMPORT_ERROR is None,
        "status": "ok" if _PUBLICATION_IMPORT_ERROR is None else "error",
        "component": DB_BLOCK_DETAIL_COMPONENT_NAME,
        "builder": DB_BLOCK_DETAIL_BUILDER_NAME,
        "api_version": DB_BLOCK_DETAIL_API_VERSION,
        "model_version": DB_BLOCK_DETAIL_MODEL_VERSION,
        "version": __version__,
        "publication_domain_available": _PUBLICATION_IMPORT_ERROR is None,
        "publication_domain_error": None
        if _PUBLICATION_IMPORT_ERROR is None
        else {
            "type": _PUBLICATION_IMPORT_ERROR.__class__.__name__,
            "message": str(_PUBLICATION_IMPORT_ERROR),
        },
        "defaults": {
            "source": DEFAULT_SOURCE,
            "include_raw_documents": DEFAULT_INCLUDE_RAW_DOCUMENTS,
            "include_payload": DEFAULT_INCLUDE_PAYLOAD,
            "include_metadata": DEFAULT_INCLUDE_METADATA,
            "include_documents": DEFAULT_INCLUDE_DOCUMENTS,
            "include_assets": DEFAULT_INCLUDE_ASSETS,
            "include_variants": DEFAULT_INCLUDE_VARIANTS,
            "include_validation": DEFAULT_INCLUDE_VALIDATION,
            "document_limit": DEFAULT_DOCUMENT_LIMIT,
            "variant_limit": DEFAULT_VARIANT_LIMIT,
            "asset_limit": DEFAULT_ASSET_LIMIT,
            "issue_limit": DEFAULT_ISSUE_LIMIT,
        },
        "enums": {
            "status": list(DbBlockDetailStatus.values()),
            "document_group": list(DbDocumentGroup.values()),
        },
        "cache": {
            "normalize_document_path": normalize_document_path.cache_info()._asdict(),
            "document_group_for_path": document_group_for_path.cache_info()._asdict(),
            "normalize_slug": normalize_slug.cache_info()._asdict(),
            "normalize_string_cached": normalize_string_cached.cache_info()._asdict(),
        },
    }


def assert_db_block_detail_builder_ready() -> Dict[str, Any]:
    """Wirft RuntimeError, wenn der Builder nicht bereit ist."""

    health = get_db_block_detail_builder_health()

    if not health.get("ok"):
        raise RuntimeError(
            "DB block detail builder is not ready: "
            f"{health.get('publication_domain_error')}"
        )

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "DB_BLOCK_DETAIL_BUILDER_NAME",
    "DB_BLOCK_DETAIL_COMPONENT_NAME",
    "DB_BLOCK_DETAIL_API_VERSION",
    "DB_BLOCK_DETAIL_MODEL_VERSION",

    # Defaults
    "DEFAULT_SOURCE",
    "DEFAULT_INCLUDE_RAW_DOCUMENTS",
    "DEFAULT_INCLUDE_PAYLOAD",
    "DEFAULT_INCLUDE_METADATA",
    "DEFAULT_INCLUDE_DOCUMENTS",
    "DEFAULT_INCLUDE_ASSETS",
    "DEFAULT_INCLUDE_VARIANTS",
    "DEFAULT_INCLUDE_VALIDATION",
    "DEFAULT_DOCUMENT_LIMIT",
    "DEFAULT_VARIANT_LIMIT",
    "DEFAULT_ASSET_LIMIT",
    "DEFAULT_ISSUE_LIMIT",

    # Enums
    "DbBlockDetailStatus",
    "DbDocumentGroup",

    # Options/result models
    "DbBlockDetailBuilderOptions",
    "DbBlockDetailSourceBundle",
    "DbDocumentEntry",
    "DbBlockDetailBuildResult",

    # Generic helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_string",
    "normalize_slug",
    "normalize_vplib_uid",
    "normalize_taxonomy_path",
    "normalize_document_path",
    "document_group_for_path",
    "first_non_empty",
    "json_safe",
    "to_mapping",
    "listify",
    "truncate_list",
    "object_id",
    "clear_db_block_detail_builder_caches",

    # Domain builders
    "normalize_asset_refs",
    "normalize_variant_refs",
    "normalize_revision",
    "find_asset_by_role",
    "build_validation_summary",
    "normalize_documents",
    "group_documents",
    "extract_document_payload_by_path",
    "build_family_summary",
    "build_detail_from_bundle",
    "build_package_payload",
    "build_family_payload",
    "build_profile_payload",

    # Response builders
    "build_detail_result_from_db_payload",
    "build_detail_response_from_db_payload",
    "build_not_found_detail_response",
    "build_error_detail_response",
    "build_variants_response_from_db_payload",

    # Query helpers
    "build_options_from_query",

    # Health
    "get_db_block_detail_builder_health",
    "assert_db_block_detail_builder_ready",
]