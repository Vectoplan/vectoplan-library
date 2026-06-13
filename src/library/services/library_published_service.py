# services/vectoplan-library/src/library/services/library_published_service.py
"""
DB-basierter Published-Service für die VECTOPLAN Creative Library.

Diese Datei stellt den produktiven Lesepfad bereit:

    creative_library Tabellen
        → repository
        → library_published_service
        → publication / inventory Domain-Modelle
        → API-Routen
        → Editor / Admin / Creative Library / Inventar

Aufgaben:

- veröffentlichte Blocks/Families aus der DB listen
- veröffentlichte Detaildaten laden
- Varianten eines veröffentlichten Eintrags laden
- Creative-Library-Tree aus DB-Daten bauen
- Inventarzustand aus DB-Daten bauen
- Health für DB-Read-Pfad liefern
- optional Debug-/Fallback-freundlich bleiben

Wichtige Architekturregeln:

- Dieser Service scannt nicht selbst.
- Dieser Service schreibt nicht in die Datenbank.
- Dieser Service liest standardmäßig aus dem Repository.
- Das Repository kapselt SQLAlchemy und models/creative_library.py.
- Die produktiven GET-Routen sollen später standardmäßig diesen Service nutzen.
- Der alte filesystem-basierte library_block_service kann als Debug-Pfad erhalten bleiben.

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id
    variant_id
"""

from __future__ import annotations

import importlib
import os
import threading
import traceback as traceback_module
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Domain imports
# ---------------------------------------------------------------------------

from ..domain.publication import (
    DEFAULT_PUBLICATION_SOURCE,
    PublishedAssetRef,
    PublishedFamilyDetail,
    PublishedFamilySummary,
    PublishedLibraryListResult,
    PublishedLibraryStats,
    PublishedRevisionSummary,
    PublishedValidationSummary,
    PublishedVariantSummary,
    build_error_publication_response,
    build_not_found_publication_response,
    build_published_detail_response,
    build_published_family_summaries,
    build_published_family_summary,
    build_published_list_response,
)

from ..domain.inventory import (
    DEFAULT_INVENTORY_MODE,
    DEFAULT_INVENTORY_SCOPE,
    DEFAULT_INVENTORY_SOURCE,
    InventoryAssetRef,
    InventoryPlacementInfo,
    InventorySlot,
    InventoryState,
    InventoryStats,
    InventoryVariantRef,
    build_empty_inventory_response,
    build_error_inventory_response,
    build_inventory_response,
    build_inventory_state,
)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

LIBRARY_PUBLISHED_SERVICE_NAME = "library_published_service"
LIBRARY_PUBLISHED_COMPONENT_NAME = "creative_library_published_read_service"
LIBRARY_PUBLISHED_API_VERSION = "v1"
LIBRARY_PUBLISHED_IMPLEMENTATION_STAGE = "db-published-read-service"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Environment / defaults
# ---------------------------------------------------------------------------

ENV_PUBLISHED_READ_ENABLED = "VPLIB_LIBRARY_PUBLISHED_READ_ENABLED"
ENV_PUBLISHED_READ_STRICT = "VPLIB_LIBRARY_PUBLISHED_READ_STRICT"
ENV_PUBLISHED_DEFAULT_LIMIT = "VPLIB_LIBRARY_PUBLISHED_DEFAULT_LIMIT"
ENV_PUBLISHED_MAX_LIMIT = "VPLIB_LIBRARY_PUBLISHED_MAX_LIMIT"
ENV_PUBLISHED_INCLUDE_UNPUBLISHED = "VPLIB_LIBRARY_PUBLISHED_INCLUDE_UNPUBLISHED"
ENV_PUBLISHED_INCLUDE_DELETED = "VPLIB_LIBRARY_PUBLISHED_INCLUDE_DELETED"

DEFAULT_PUBLISHED_READ_ENABLED = True
DEFAULT_PUBLISHED_READ_STRICT = False
DEFAULT_PUBLISHED_LIMIT = 100
DEFAULT_PUBLISHED_MAX_LIMIT = 1000
DEFAULT_TREE_ITEM_LIMIT = 10000
DEFAULT_INVENTORY_SLOT_LIMIT = 512

DEFAULT_REPOSITORY_IMPORT_PATH = "library.repositories.sql"


# ---------------------------------------------------------------------------
# Internal caches
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.RLock()
_IMPORT_CACHE: Dict[str, ModuleType] = {}
_IMPORT_ERROR_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_SERVICE: Optional["LibraryPublishedService"] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LibraryPublishedServiceError(RuntimeError):
    """Basisklasse für Published-Service-Fehler."""


class LibraryPublishedServiceDisabledError(LibraryPublishedServiceError):
    """Published-DB-Read-Service ist deaktiviert."""


class LibraryPublishedServiceImportError(LibraryPublishedServiceError):
    """Benötigtes Modul oder Repository konnte nicht importiert werden."""


class LibraryPublishedNotFound(LibraryPublishedServiceError):
    """Veröffentlichter Library-Eintrag wurde nicht gefunden."""


class LibraryPublishedValidationError(LibraryPublishedServiceError):
    """Ungültige Argumente für Published-Service."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LibraryPublishedServiceConfig:
    """
    Konfiguration für LibraryPublishedService.

    repository:
        Optional injiziertes Repository.

    repository_factory:
        Optional Callable, das ein Repository liefert.

    enabled:
        Wenn False, verweigert der Service Leseoperationen.

    strict:
        Wenn True, werden fehlende Repository-Funktionen härter behandelt.

    default_limit / max_limit:
        Pagination Defaults für Listenrouten.

    include_unpublished_by_default:
        Nur für Admin-/Debug-Sichten sinnvoll. Produktiv False.

    include_deleted_by_default:
        Nur für Admin-/Debug-Sichten sinnvoll. Produktiv False.
    """

    repository: Any = None
    repository_factory: Any = None

    enabled: bool = DEFAULT_PUBLISHED_READ_ENABLED
    strict: bool = DEFAULT_PUBLISHED_READ_STRICT

    repository_import_path: str = DEFAULT_REPOSITORY_IMPORT_PATH

    default_limit: int = DEFAULT_PUBLISHED_LIMIT
    max_limit: int = DEFAULT_PUBLISHED_MAX_LIMIT

    include_unpublished_by_default: bool = False
    include_deleted_by_default: bool = False
    enabled_only_by_default: bool = True

    include_payload_by_default: bool = False
    include_metadata_by_default: bool = False
    include_raw_documents_by_default: bool = False


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


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if value is None:
        return default

    try:
        return int(value)
    except Exception:
        return default


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

    if text in {"1", "true", "yes", "y", "on", "active", "enabled", "published"}:
        return True

    if text in {"0", "false", "no", "n", "off", "inactive", "disabled", "deleted"}:
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


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def json_safe(value: Any) -> Any:
    """Defensiv JSON-kompatible Struktur bauen."""

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

    return value


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


def object_id(value: Any) -> Any:
    data = to_mapping(value)

    return first_non_empty(
        data.get("id"),
        data.get("pk"),
        data.get("uuid"),
        data.get("family_db_id"),
        data.get("revision_db_id"),
    )


def bounded_limit(value: Any, *, default: int, max_limit: int) -> int:
    limit = safe_int(value, default)

    if limit <= 0:
        return default

    return min(limit, max_limit)


def safe_offset(value: Any) -> int:
    return max(0, safe_int(value, 0))


def exception_payload(exc: BaseException, *, include_traceback: bool = False) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "error_type": exc.__class__.__name__,
        "error": str(exc),
    }

    if include_traceback:
        payload["traceback"] = traceback_module.format_exc()

    return payload


# ---------------------------------------------------------------------------
# Safe imports
# ---------------------------------------------------------------------------


def safe_import_module(
    module_path: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """Importiert ein Modul robust und cached Modul oder Fehler."""

    normalized_path = str(module_path or "").strip()

    if not normalized_path:
        if required:
            raise LibraryPublishedServiceImportError("Empty import path.")
        return None

    with _CACHE_LOCK:
        if not force_reload and normalized_path in _IMPORT_CACHE:
            return _IMPORT_CACHE[normalized_path]

    try:
        with _CACHE_LOCK:
            if force_reload and normalized_path in _IMPORT_CACHE:
                module = importlib.reload(_IMPORT_CACHE[normalized_path])
            else:
                module = importlib.import_module(normalized_path)

            _IMPORT_CACHE[normalized_path] = module
            _IMPORT_ERROR_CACHE.pop(normalized_path, None)
            return module

    except Exception as exc:
        payload = {
            "module_path": normalized_path,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "traceback": traceback_module.format_exc(),
        }

        with _CACHE_LOCK:
            _IMPORT_CACHE.pop(normalized_path, None)
            _IMPORT_ERROR_CACHE[normalized_path] = payload

        if required:
            raise LibraryPublishedServiceImportError(
                f"Unable to import {normalized_path}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        return None


def clear_library_published_import_cache() -> Dict[str, Any]:
    """Leert nur Import-Caches dieses Moduls."""

    with _CACHE_LOCK:
        modules = sorted(_IMPORT_CACHE.keys())
        errors = sorted(_IMPORT_ERROR_CACHE.keys())
        _IMPORT_CACHE.clear()
        _IMPORT_ERROR_CACHE.clear()

    return {
        "ok": True,
        "cleared_modules": modules,
        "cleared_import_errors": errors,
    }


# ---------------------------------------------------------------------------
# Mapping builders
# ---------------------------------------------------------------------------


def find_asset_by_role(assets: Iterable[Any], roles: Sequence[str]) -> Optional[PublishedAssetRef]:
    """Findet erstes Asset mit passender Rolle."""

    role_set = {str(role).strip().lower() for role in roles if str(role).strip()}

    for asset in assets:
        asset_ref = asset if isinstance(asset, PublishedAssetRef) else PublishedAssetRef.from_mapping(asset)
        role = str(asset_ref.role or "").strip().lower()

        if role in role_set:
            return asset_ref

    return None


def normalize_family_summary(
    family: Any,
    *,
    latest_revision: Any = None,
    assets: Optional[Iterable[Any]] = None,
) -> PublishedFamilySummary:
    """Baut PublishedFamilySummary aus Repository-Family plus optionalen Zusatzdaten."""

    family_data = to_mapping(family)

    if latest_revision is not None:
        family_data["latest_revision"] = PublishedRevisionSummary.from_mapping(latest_revision).to_dict()

    asset_refs = [
        item if isinstance(item, PublishedAssetRef) else PublishedAssetRef.from_mapping(item)
        for item in (assets or [])
    ]

    icon = find_asset_by_role(asset_refs, ("icon",))
    preview = find_asset_by_role(asset_refs, ("preview", "thumbnail"))

    if icon:
        family_data["icon"] = icon.to_dict()

    if preview:
        family_data["preview"] = preview.to_dict()

    return PublishedFamilySummary.from_mapping(family_data)


def normalize_family_detail_payload(value: Any) -> PublishedFamilyDetail:
    """
    Baut PublishedFamilyDetail aus Repository-Antwort.

    Unterstützte Repository-Form:
        {
          "family": ...,
          "revision": ...,
          "variants": [...],
          "assets": [...],
          "documents": [...]
        }

    Falls nur ein Family-Objekt kommt, wird daraus eine Minimaldetailantwort.
    """

    data = to_mapping(value)

    family = first_non_empty(data.get("family"), data.get("summary"), value)
    revision = data.get("revision")
    variants = data.get("variants") or []
    assets = data.get("assets") or []
    documents = data.get("documents") or []

    summary = normalize_family_summary(
        family,
        latest_revision=revision,
        assets=assets,
    )

    revision_summary = (
        PublishedRevisionSummary.from_mapping(revision)
        if revision is not None
        else summary.latest_revision
    )

    variant_items = [
        item if isinstance(item, PublishedVariantSummary) else PublishedVariantSummary.from_mapping(item)
        for item in variants
    ]

    asset_items = [
        item if isinstance(item, PublishedAssetRef) else PublishedAssetRef.from_mapping(item)
        for item in assets
    ]

    document_items = [
        to_mapping(item)
        for item in documents
    ]

    raw_documents = first_non_empty(
        data.get("raw_documents"),
        data.get("documents_payload"),
        to_mapping(revision).get("raw_documents") if revision is not None else None,
        to_mapping(revision).get("documents") if revision is not None else None,
        {},
    )

    validation = PublishedValidationSummary.from_mapping(
        first_non_empty(
            data.get("validation"),
            to_mapping(revision).get("validation_payload") if revision is not None else None,
            to_mapping(family).get("validation"),
            {},
        )
    )

    return PublishedFamilyDetail(
        summary=summary,
        revision=revision_summary,
        variants=variant_items,
        assets=asset_items,
        documents=document_items,
        raw_documents=dict(raw_documents or {}),
        validation=validation,
        payload=dict(data.get("payload") or {}),
        metadata=dict(data.get("metadata") or data.get("meta") or {}),
    )


def normalize_variant_items(values: Iterable[Any]) -> List[PublishedVariantSummary]:
    return [
        item if isinstance(item, PublishedVariantSummary) else PublishedVariantSummary.from_mapping(item)
        for item in values
    ]


def build_inventory_slot_from_family(
    family: Any,
    *,
    slot_index: int,
    variant: Any = None,
    assets: Optional[Iterable[Any]] = None,
) -> InventorySlot:
    """Baut einen Inventarslot aus einer veröffentlichten Family."""

    summary = normalize_family_summary(family, assets=assets)

    asset_refs = [
        item if isinstance(item, PublishedAssetRef) else PublishedAssetRef.from_mapping(item)
        for item in (assets or [])
    ]

    icon = find_asset_by_role(asset_refs, ("icon",))
    preview = find_asset_by_role(asset_refs, ("preview", "thumbnail"))

    variant_ref = InventoryVariantRef.from_mapping(variant) if variant is not None else None

    return InventorySlot(
        slot_index=slot_index,
        slot_id=f"slot_{slot_index}",
        status="active",
        source=DEFAULT_INVENTORY_SOURCE,
        scope=DEFAULT_INVENTORY_SCOPE,
        mode=DEFAULT_INVENTORY_MODE,
        vplib_uid=summary.vplib_uid,
        family_id=summary.family_id,
        package_id=summary.package_id,
        variant_id=variant_ref.variant_id if variant_ref else summary.default_variant_id,
        label=summary.label,
        description=summary.description,
        family_slug=summary.family_slug,
        object_kind=summary.object_kind,
        domain=summary.domain,
        category=summary.category,
        subcategory=summary.subcategory,
        taxonomy_path=summary.taxonomy_path,
        enabled=summary.enabled,
        visible=summary.visible,
        active=summary.is_published,
        locked=False,
        pinned=False,
        selected=False,
        sort_order=slot_index,
        icon=InventoryAssetRef.from_mapping(icon.to_dict()) if icon else None,
        preview=InventoryAssetRef.from_mapping(preview.to_dict()) if preview else None,
        assets=[
            InventoryAssetRef.from_mapping(asset.to_dict())
            for asset in asset_refs
        ],
        variant=variant_ref,
        placement=InventoryPlacementInfo.from_mapping(summary.payload.get("placement") if isinstance(summary.payload, Mapping) else {}),
        revision_hash=summary.revision_hash,
        publication_status=summary.publication_status,
        validation_status=summary.validation.status if summary.validation else None,
        published_at=summary.published_at,
        updated_at=summary.updated_at,
        metadata={
            "source": "family_fallback",
        },
    )


def build_inventory_slot_from_db_slot(slot: Any, *, fallback_slot_index: int = 0) -> InventorySlot:
    """Baut InventorySlot aus Repository-/DB-Slot."""

    return InventorySlot.from_mapping(slot, fallback_slot_index=fallback_slot_index)


# ---------------------------------------------------------------------------
# Tree builder
# ---------------------------------------------------------------------------


def make_tree_node(
    *,
    node_id: str,
    label: Optional[str] = None,
    node_type: str = "node",
    parent_id: Optional[str] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": node_id,
        "label": label or node_id,
        "type": node_type,
        "parent_id": parent_id,
        "path": path or node_id,
        "children": [],
        "item_ids": [],
        "count": 0,
        "metadata": {},
    }


def build_published_tree_from_summaries(items: Iterable[PublishedFamilySummary]) -> Dict[str, Any]:
    """
    Baut Tree-Struktur:

        root
          domain
            category
              subcategory
                item_ids
    """

    root = make_tree_node(
        node_id="root",
        label="Library",
        node_type="root",
        parent_id=None,
        path="root",
    )

    domain_nodes: Dict[str, Dict[str, Any]] = {}
    category_nodes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    subcategory_nodes: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for item in items:
        domain = item.domain or "unknown"
        category = item.category or "unknown"
        subcategory = item.subcategory or "unknown"
        item_id = item.id or item.vplib_uid or item.family_id or item.package_id

        if not item_id:
            continue

        if domain not in domain_nodes:
            domain_node = make_tree_node(
                node_id=domain,
                label=domain,
                node_type="domain",
                parent_id="root",
                path=domain,
            )
            domain_nodes[domain] = domain_node
            root["children"].append(domain_node)

        domain_node = domain_nodes[domain]

        category_key = (domain, category)
        if category_key not in category_nodes:
            category_node = make_tree_node(
                node_id=f"{domain}/{category}",
                label=category,
                node_type="category",
                parent_id=domain_node["id"],
                path=f"{domain}/{category}",
            )
            category_nodes[category_key] = category_node
            domain_node["children"].append(category_node)

        category_node = category_nodes[category_key]

        subcategory_key = (domain, category, subcategory)
        if subcategory_key not in subcategory_nodes:
            subcategory_node = make_tree_node(
                node_id=f"{domain}/{category}/{subcategory}",
                label=subcategory,
                node_type="subcategory",
                parent_id=category_node["id"],
                path=f"{domain}/{category}/{subcategory}",
            )
            subcategory_nodes[subcategory_key] = subcategory_node
            category_node["children"].append(subcategory_node)

        subcategory_node = subcategory_nodes[subcategory_key]
        subcategory_node["item_ids"].append(item_id)
        subcategory_node["count"] += 1
        category_node["count"] += 1
        domain_node["count"] += 1
        root["count"] += 1

    return root


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------


class LibraryPublishedService:
    """DB-basierter Leseservice für veröffentlichte Creative-Library-Daten."""

    def __init__(
        self,
        *,
        repository: Any = None,
        repository_factory: Any = None,
        config: Optional[LibraryPublishedServiceConfig] = None,
    ) -> None:
        if config is None:
            config = LibraryPublishedServiceConfig(
                repository=repository,
                repository_factory=repository_factory,
                enabled=env_bool(ENV_PUBLISHED_READ_ENABLED, DEFAULT_PUBLISHED_READ_ENABLED),
                strict=env_bool(ENV_PUBLISHED_READ_STRICT, DEFAULT_PUBLISHED_READ_STRICT),
                default_limit=env_int(ENV_PUBLISHED_DEFAULT_LIMIT, DEFAULT_PUBLISHED_LIMIT),
                max_limit=env_int(ENV_PUBLISHED_MAX_LIMIT, DEFAULT_PUBLISHED_MAX_LIMIT),
                include_unpublished_by_default=env_bool(
                    ENV_PUBLISHED_INCLUDE_UNPUBLISHED,
                    False,
                ),
                include_deleted_by_default=env_bool(
                    ENV_PUBLISHED_INCLUDE_DELETED,
                    False,
                ),
            )

        self.config = config
        self._repository = repository if repository is not None else config.repository
        self._repository_factory = (
            repository_factory
            if repository_factory is not None
            else config.repository_factory
        )

    # ------------------------------------------------------------------
    # Dependency loading
    # ------------------------------------------------------------------

    def get_repository(self) -> Any:
        """Liefert Repository für DB-Read-Zugriffe."""

        if self._repository is not None:
            return self._repository

        if callable(self._repository_factory):
            self._repository = self._repository_factory()
            return self._repository

        module = safe_import_module(self.config.repository_import_path, required=True)

        for function_name in (
            "get_creative_library_repository",
            "get_default_creative_library_repository",
            "create_creative_library_repository",
        ):
            factory = getattr(module, function_name, None)

            if callable(factory):
                self._repository = factory()
                return self._repository

        raise LibraryPublishedServiceImportError(
            "No repository factory found. Expected one of: "
            "get_creative_library_repository, "
            "get_default_creative_library_repository, "
            "create_creative_library_repository."
        )

    def _assert_enabled(self) -> None:
        if not self.config.enabled:
            raise LibraryPublishedServiceDisabledError(
                f"Published DB read service is disabled. "
                f"Enable {ENV_PUBLISHED_READ_ENABLED}=true."
            )

    # ------------------------------------------------------------------
    # Public read operations
    # ------------------------------------------------------------------

    def list_published_blocks(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        q: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        include_unpublished: Optional[bool] = None,
        include_deleted: Optional[bool] = None,
        enabled_only: Optional[bool] = None,
        include_payload: Optional[bool] = None,
        include_metadata: Optional[bool] = None,
    ) -> PublishedLibraryListResult:
        """Liest veröffentlichte Blocks/Families aus der DB."""

        self._assert_enabled()

        repository = self.get_repository()

        list_function = getattr(repository, "list_published_families", None)
        if not callable(list_function):
            raise LibraryPublishedServiceImportError(
                "Repository does not expose list_published_families(...)."
            )

        resolved_limit = bounded_limit(
            limit,
            default=self.config.default_limit,
            max_limit=self.config.max_limit,
        )

        include_unpublished_effective = (
            self.config.include_unpublished_by_default
            if include_unpublished is None
            else bool(include_unpublished)
        )

        include_deleted_effective = (
            self.config.include_deleted_by_default
            if include_deleted is None
            else bool(include_deleted)
        )

        enabled_only_effective = (
            self.config.enabled_only_by_default
            if enabled_only is None
            else bool(enabled_only)
        )

        rows = list_function(
            domain=normalize_slug(domain),
            category=normalize_slug(category),
            subcategory=normalize_slug(subcategory),
            object_kind=normalize_string(object_kind),
            q=normalize_string(q),
            include_unpublished=include_unpublished_effective,
            include_deleted=include_deleted_effective,
            enabled_only=enabled_only_effective,
            limit=resolved_limit,
            offset=safe_offset(offset),
        )

        summaries = [
            normalize_family_summary(row)
            for row in rows
        ]

        result = PublishedLibraryListResult.from_items(
            summaries,
            filters={
                "domain": normalize_slug(domain),
                "category": normalize_slug(category),
                "subcategory": normalize_slug(subcategory),
                "object_kind": normalize_string(object_kind),
                "q": normalize_string(q),
                "include_unpublished": include_unpublished_effective,
                "include_deleted": include_deleted_effective,
                "enabled_only": enabled_only_effective,
            },
            pagination={
                "limit": resolved_limit,
                "offset": safe_offset(offset),
                "returned": len(summaries),
            },
            metadata={
                "source": "database",
                "service": LIBRARY_PUBLISHED_SERVICE_NAME,
                "include_payload": self.config.include_payload_by_default if include_payload is None else bool(include_payload),
                "include_metadata": self.config.include_metadata_by_default if include_metadata is None else bool(include_metadata),
            },
        )

        return result

    def list_published_blocks_response(self, **kwargs: Any) -> Dict[str, Any]:
        """API-taugliche Response für Blocks-Liste."""

        include_payload = bool(
            kwargs.pop(
                "include_payload",
                self.config.include_payload_by_default,
            )
        )
        include_metadata = bool(
            kwargs.pop(
                "include_metadata",
                self.config.include_metadata_by_default,
            )
        )

        try:
            result = self.list_published_blocks(
                include_payload=include_payload,
                include_metadata=include_metadata,
                **kwargs,
            )

            return result.to_dict(
                include_payload=include_payload,
                include_metadata=include_metadata,
            )

        except Exception as exc:
            return build_error_publication_response(
                exc,
                message="Failed to list published library blocks.",
            )

    def get_published_block_detail(
        self,
        identifier: str,
        *,
        include_unpublished: bool = False,
        include_raw_documents: Optional[bool] = None,
    ) -> PublishedFamilyDetail:
        """Liest Detaildaten eines veröffentlichten Blocks aus der DB."""

        self._assert_enabled()

        ident = normalize_string(identifier)

        if not ident:
            raise LibraryPublishedValidationError("identifier is required.")

        repository = self.get_repository()

        detail_function = getattr(repository, "get_published_family_detail", None)
        if not callable(detail_function):
            raise LibraryPublishedServiceImportError(
                "Repository does not expose get_published_family_detail(...)."
            )

        try:
            detail_payload = detail_function(
                ident,
                include_unpublished=include_unpublished,
            )
        except Exception as exc:
            raise LibraryPublishedNotFound(str(exc)) from exc

        return normalize_family_detail_payload(detail_payload)

    def get_published_block_detail_response(
        self,
        identifier: str,
        *,
        include_unpublished: bool = False,
        include_raw_documents: Optional[bool] = None,
        include_payload: Optional[bool] = None,
        include_metadata: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """API-taugliche Response für Block-Detail."""

        try:
            detail = self.get_published_block_detail(
                identifier,
                include_unpublished=include_unpublished,
                include_raw_documents=include_raw_documents,
            )

            return detail.to_dict(
                include_raw_documents=self.config.include_raw_documents_by_default
                if include_raw_documents is None
                else bool(include_raw_documents),
                include_payload=self.config.include_payload_by_default
                if include_payload is None
                else bool(include_payload),
                include_metadata=self.config.include_metadata_by_default
                if include_metadata is None
                else bool(include_metadata),
            )

        except LibraryPublishedNotFound:
            return build_not_found_publication_response(identifier)

        except Exception as exc:
            return build_error_publication_response(
                exc,
                message="Failed to load published library block detail.",
            )

    def get_published_block_variants(
        self,
        identifier: str,
        *,
        include_unpublished: bool = False,
    ) -> List[PublishedVariantSummary]:
        """Liest Varianten eines veröffentlichten Blocks aus der DB."""

        self._assert_enabled()

        ident = normalize_string(identifier)

        if not ident:
            raise LibraryPublishedValidationError("identifier is required.")

        repository = self.get_repository()

        variants_function = getattr(repository, "get_family_variants", None)
        if not callable(variants_function):
            raise LibraryPublishedServiceImportError(
                "Repository does not expose get_family_variants(...)."
            )

        rows = variants_function(
            ident,
            include_unpublished=include_unpublished,
        )

        return normalize_variant_items(rows)

    def get_published_block_variants_response(
        self,
        identifier: str,
        *,
        include_unpublished: bool = False,
    ) -> Dict[str, Any]:
        """API-taugliche Variantenantwort."""

        try:
            variants = self.get_published_block_variants(
                identifier,
                include_unpublished=include_unpublished,
            )

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
                "source": DEFAULT_PUBLICATION_SOURCE,
                "generated_at": safe_isoformat(utcnow()),
            }

        except LibraryPublishedNotFound:
            return build_not_found_publication_response(identifier)

        except Exception as exc:
            return build_error_publication_response(
                exc,
                message="Failed to load published library block variants.",
            )

    def get_published_tree(
        self,
        *,
        include_unpublished: Optional[bool] = None,
        include_deleted: Optional[bool] = None,
        enabled_only: Optional[bool] = None,
        limit: int = DEFAULT_TREE_ITEM_LIMIT,
    ) -> Dict[str, Any]:
        """Baut Creative-Library-Tree aus veröffentlichten DB-Families."""

        self._assert_enabled()

        list_result = self.list_published_blocks(
            limit=limit,
            offset=0,
            include_unpublished=include_unpublished,
            include_deleted=include_deleted,
            enabled_only=enabled_only,
        )

        tree = build_published_tree_from_summaries(list_result.items)

        return {
            "ok": True,
            "status": "ok",
            "source": DEFAULT_PUBLICATION_SOURCE,
            "tree": tree,
            "count": tree.get("count", 0),
            "stats": list_result.stats.to_dict(),
            "generated_at": safe_isoformat(utcnow()),
        }

    def get_published_tree_response(self, **kwargs: Any) -> Dict[str, Any]:
        """API-taugliche Tree-Response."""

        try:
            return self.get_published_tree(**kwargs)
        except Exception as exc:
            return build_error_publication_response(
                exc,
                message="Failed to build published library tree.",
            )

    def get_inventory_state(
        self,
        *,
        include_inactive: bool = False,
        fallback_from_published_families: bool = True,
        slot_limit: int = DEFAULT_INVENTORY_SLOT_LIMIT,
    ) -> InventoryState:
        """Liest Inventarzustand aus DB; optional Fallback aus published Families."""

        self._assert_enabled()

        repository = self.get_repository()

        slots: List[InventorySlot] = []

        list_slots = getattr(repository, "list_inventory_slots", None)
        if callable(list_slots):
            raw_slots = list_slots(include_inactive=include_inactive)
            slots = [
                build_inventory_slot_from_db_slot(slot, fallback_slot_index=index)
                for index, slot in enumerate(raw_slots)
            ]

        if not slots and fallback_from_published_families:
            families = self.list_published_blocks(
                limit=slot_limit,
                include_unpublished=False,
                include_deleted=False,
                enabled_only=True,
            ).items

            for index, family in enumerate(families[:slot_limit]):
                slots.append(
                    build_inventory_slot_from_family(
                        family,
                        slot_index=index,
                    )
                )

        return InventoryState.from_slots(
            slots,
            scope=DEFAULT_INVENTORY_SCOPE,
            mode=DEFAULT_INVENTORY_MODE,
            source=DEFAULT_INVENTORY_SOURCE,
            filters={
                "include_inactive": include_inactive,
                "fallback_from_published_families": fallback_from_published_families,
                "slot_limit": slot_limit,
            },
            metadata={
                "service": LIBRARY_PUBLISHED_SERVICE_NAME,
            },
        )

    def get_inventory_response(
        self,
        *,
        include_inactive: bool = False,
        fallback_from_published_families: bool = True,
        slot_limit: int = DEFAULT_INVENTORY_SLOT_LIMIT,
        include_payload: Optional[bool] = None,
        include_metadata: Optional[bool] = None,
        include_assets: bool = True,
    ) -> Dict[str, Any]:
        """API-taugliche Inventarantwort."""

        try:
            state = self.get_inventory_state(
                include_inactive=include_inactive,
                fallback_from_published_families=fallback_from_published_families,
                slot_limit=slot_limit,
            )

            return state.to_dict(
                include_payload=self.config.include_payload_by_default
                if include_payload is None
                else bool(include_payload),
                include_metadata=self.config.include_metadata_by_default
                if include_metadata is None
                else bool(include_metadata),
                include_assets=include_assets,
                slot_limit=slot_limit,
            )

        except Exception as exc:
            return build_error_inventory_response(
                exc,
                message="Failed to load library inventory.",
            )

    # ------------------------------------------------------------------
    # Counts / status
    # ------------------------------------------------------------------

    def get_publication_status(self) -> Dict[str, Any]:
        """Liefert kompakten DB-Publication-Status."""

        self._assert_enabled()

        repository = self.get_repository()

        count_function = getattr(repository, "count_published_families", None)

        published_count = None
        total_count = None

        if callable(count_function):
            published_count = count_function(
                include_unpublished=False,
                include_deleted=False,
            )
            total_count = count_function(
                include_unpublished=True,
                include_deleted=True,
            )

        return {
            "ok": True,
            "status": "ok",
            "source": DEFAULT_PUBLICATION_SOURCE,
            "published_count": published_count,
            "total_count": total_count,
            "generated_at": safe_isoformat(utcnow()),
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(
        self,
        *,
        check_repository: bool = False,
        include_traceback: bool = False,
    ) -> Dict[str, Any]:
        """Health-Check des Published-Read-Service."""

        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        repository_health: Dict[str, Any] = {
            "checked": check_repository,
            "available": None,
        }

        if not self.config.enabled:
            warnings.append(
                {
                    "scope": "config",
                    "warning": "Published DB read service is disabled.",
                    "env": ENV_PUBLISHED_READ_ENABLED,
                }
            )

        if check_repository:
            try:
                repository = self.get_repository()
                health_function = getattr(repository, "health", None)

                if callable(health_function):
                    repository_health = health_function(
                        strict=self.config.strict,
                        check_session=True,
                        include_traceback=include_traceback,
                    )
                else:
                    repository_health = {
                        "checked": True,
                        "available": repository is not None,
                        "status": "loaded_no_health_function",
                    }

                if not repository_health.get("ok", repository_health.get("available", False)):
                    errors.append(
                        {
                            "scope": "repository",
                            "error": "Repository health is not ok.",
                            "health": repository_health,
                        }
                    )

            except Exception as exc:
                payload = exception_payload(exc, include_traceback=include_traceback)
                payload["scope"] = "repository"
                errors.append(payload)
                repository_health = {
                    "checked": True,
                    "available": False,
                    "error": payload,
                }

        ok = not errors

        if not ok:
            status = "error"
        elif warnings:
            status = "partial"
        else:
            status = "ok"

        return {
            "ok": ok,
            "status": status,
            "component": LIBRARY_PUBLISHED_COMPONENT_NAME,
            "service": LIBRARY_PUBLISHED_SERVICE_NAME,
            "api_version": LIBRARY_PUBLISHED_API_VERSION,
            "implementation_stage": LIBRARY_PUBLISHED_IMPLEMENTATION_STAGE,
            "version": __version__,
            "config": {
                "enabled": self.config.enabled,
                "strict": self.config.strict,
                "repository_import_path": self.config.repository_import_path,
                "default_limit": self.config.default_limit,
                "max_limit": self.config.max_limit,
                "include_unpublished_by_default": self.config.include_unpublished_by_default,
                "include_deleted_by_default": self.config.include_deleted_by_default,
                "enabled_only_by_default": self.config.enabled_only_by_default,
            },
            "repository": repository_health,
            "imports": {
                "cached_modules": sorted(_IMPORT_CACHE.keys()),
                "cached_errors": _IMPORT_ERROR_CACHE,
            },
            "warnings": warnings,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Module-level factory / API
# ---------------------------------------------------------------------------


def create_library_published_service(
    *,
    repository: Any = None,
    repository_factory: Any = None,
    config: Optional[LibraryPublishedServiceConfig] = None,
) -> LibraryPublishedService:
    """Erstellt eine neue Published-Service-Instanz."""

    return LibraryPublishedService(
        repository=repository,
        repository_factory=repository_factory,
        config=config,
    )


def get_library_published_service(
    *,
    use_cache: bool = True,
    force_new: bool = False,
    repository: Any = None,
    repository_factory: Any = None,
    config: Optional[LibraryPublishedServiceConfig] = None,
) -> LibraryPublishedService:
    """Liefert den Default-Published-Service."""

    global _DEFAULT_SERVICE

    if force_new or not use_cache:
        return create_library_published_service(
            repository=repository,
            repository_factory=repository_factory,
            config=config,
        )

    with _CACHE_LOCK:
        if _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = create_library_published_service(
                repository=repository,
                repository_factory=repository_factory,
                config=config,
            )

        return _DEFAULT_SERVICE


def list_published_blocks(**kwargs: Any) -> PublishedLibraryListResult:
    service = get_library_published_service()
    return service.list_published_blocks(**kwargs)


def list_published_blocks_response(**kwargs: Any) -> Dict[str, Any]:
    service = get_library_published_service()
    return service.list_published_blocks_response(**kwargs)


def get_published_block_detail(identifier: str, **kwargs: Any) -> PublishedFamilyDetail:
    service = get_library_published_service()
    return service.get_published_block_detail(identifier, **kwargs)


def get_published_block_detail_response(identifier: str, **kwargs: Any) -> Dict[str, Any]:
    service = get_library_published_service()
    return service.get_published_block_detail_response(identifier, **kwargs)


def get_published_block_variants(identifier: str, **kwargs: Any) -> List[PublishedVariantSummary]:
    service = get_library_published_service()
    return service.get_published_block_variants(identifier, **kwargs)


def get_published_block_variants_response(identifier: str, **kwargs: Any) -> Dict[str, Any]:
    service = get_library_published_service()
    return service.get_published_block_variants_response(identifier, **kwargs)


def get_published_tree(**kwargs: Any) -> Dict[str, Any]:
    service = get_library_published_service()
    return service.get_published_tree(**kwargs)


def get_published_tree_response(**kwargs: Any) -> Dict[str, Any]:
    service = get_library_published_service()
    return service.get_published_tree_response(**kwargs)


def get_inventory_state(**kwargs: Any) -> InventoryState:
    service = get_library_published_service()
    return service.get_inventory_state(**kwargs)


def get_inventory_response(**kwargs: Any) -> Dict[str, Any]:
    service = get_library_published_service()
    return service.get_inventory_response(**kwargs)


def get_publication_status() -> Dict[str, Any]:
    service = get_library_published_service()
    return service.get_publication_status()


def get_library_published_service_health(
    *,
    check_repository: bool = False,
    include_traceback: bool = False,
) -> Dict[str, Any]:
    service = get_library_published_service()

    return service.health(
        check_repository=check_repository,
        include_traceback=include_traceback,
    )


def assert_library_published_service_ready(
    *,
    check_repository: bool = True,
) -> Dict[str, Any]:
    health = get_library_published_service_health(
        check_repository=check_repository,
    )

    if not health.get("ok"):
        raise LibraryPublishedServiceError(
            "Library published service is not ready "
            f"(status={health.get('status')}, errors={health.get('errors')})."
        )

    return health


def clear_library_published_service_cache() -> Dict[str, Any]:
    """Leert Import- und Default-Service-Caches."""

    global _DEFAULT_SERVICE

    with _CACHE_LOCK:
        _DEFAULT_SERVICE = None

    import_result = clear_library_published_import_cache()

    return {
        "ok": True,
        "default_service_cleared": True,
        "imports": import_result,
    }


clear_library_published_service_caches = clear_library_published_service_cache
clear_published_service_cache = clear_library_published_service_cache
clear_published_service_caches = clear_library_published_service_cache


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "LIBRARY_PUBLISHED_SERVICE_NAME",
    "LIBRARY_PUBLISHED_COMPONENT_NAME",
    "LIBRARY_PUBLISHED_API_VERSION",
    "LIBRARY_PUBLISHED_IMPLEMENTATION_STAGE",

    # Env/defaults
    "ENV_PUBLISHED_READ_ENABLED",
    "ENV_PUBLISHED_READ_STRICT",
    "ENV_PUBLISHED_DEFAULT_LIMIT",
    "ENV_PUBLISHED_MAX_LIMIT",
    "ENV_PUBLISHED_INCLUDE_UNPUBLISHED",
    "ENV_PUBLISHED_INCLUDE_DELETED",
    "DEFAULT_PUBLISHED_READ_ENABLED",
    "DEFAULT_PUBLISHED_READ_STRICT",
    "DEFAULT_PUBLISHED_LIMIT",
    "DEFAULT_PUBLISHED_MAX_LIMIT",
    "DEFAULT_TREE_ITEM_LIMIT",
    "DEFAULT_INVENTORY_SLOT_LIMIT",
    "DEFAULT_REPOSITORY_IMPORT_PATH",

    # Exceptions
    "LibraryPublishedServiceError",
    "LibraryPublishedServiceDisabledError",
    "LibraryPublishedServiceImportError",
    "LibraryPublishedNotFound",
    "LibraryPublishedValidationError",

    # Config/service
    "LibraryPublishedServiceConfig",
    "LibraryPublishedService",

    # Helpers
    "utcnow",
    "safe_isoformat",
    "env_bool",
    "env_int",
    "safe_int",
    "safe_bool",
    "normalize_string",
    "normalize_slug",
    "normalize_vplib_uid",
    "first_non_empty",
    "json_safe",
    "to_mapping",
    "object_id",
    "bounded_limit",
    "safe_offset",
    "exception_payload",

    # Imports/cache
    "safe_import_module",
    "clear_library_published_import_cache",

    # Builders
    "find_asset_by_role",
    "normalize_family_summary",
    "normalize_family_detail_payload",
    "normalize_variant_items",
    "build_inventory_slot_from_family",
    "build_inventory_slot_from_db_slot",
    "make_tree_node",
    "build_published_tree_from_summaries",

    # Factory/API
    "create_library_published_service",
    "get_library_published_service",
    "list_published_blocks",
    "list_published_blocks_response",
    "get_published_block_detail",
    "get_published_block_detail_response",
    "get_published_block_variants",
    "get_published_block_variants_response",
    "get_published_tree",
    "get_published_tree_response",
    "get_inventory_state",
    "get_inventory_response",
    "get_publication_status",
    "get_library_published_service_health",
    "assert_library_published_service_ready",
    "clear_library_published_service_cache",
    "clear_library_published_service_caches",
    "clear_published_service_cache",
    "clear_published_service_caches",
]