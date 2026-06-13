# services/vectoplan-library/src/library/read_models/db_library_tree_builder.py
"""
DB-Library-Tree-Builder für die VECTOPLAN Creative Library.

Diese Datei baut API-nahe Tree-Responses aus veröffentlichten DB-Daten.

Zielpfad:

    creative_library Tabellen
        → repository
        → library_published_service
        → db_library_tree_builder
        → GET /api/v1/vplib/library/tree

Tree-Zielstruktur:

    root
      domain
        category
          subcategory
            item_ids

Wichtig:

- keine Flask-Abhängigkeit
- keine SQLAlchemy-Session
- keine Datenbankzugriffe
- keine Schreiboperationen
- kein Filesystem-Scan
- keine Scanner-/Reader-/Validator-Imports
- tolerant gegenüber SQLAlchemy-Objekten, Dicts, Dataclasses und Domainmodellen
- kompatibel mit der bisherigen Tree-Response-Struktur
- primär auf veröffentlichte DB-Daten ausgelegt

Primäre technische Identität:

    vplib_uid

Semantische Identitäten:

    family_id
    package_id
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
        PublishedFamilySummary,
        PublishedLibraryStats,
    )
except Exception as import_error:  # pragma: no cover - defensive fallback
    DEFAULT_PUBLICATION_SOURCE = "database"
    PublishedFamilySummary = None  # type: ignore
    PublishedLibraryStats = None  # type: ignore
    _PUBLICATION_IMPORT_ERROR = import_error
else:
    _PUBLICATION_IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

DB_LIBRARY_TREE_BUILDER_NAME = "db_library_tree_builder"
DB_LIBRARY_TREE_COMPONENT_NAME = "creative_library_db_tree_builder"
DB_LIBRARY_TREE_API_VERSION = "v1"
DB_LIBRARY_TREE_MODEL_VERSION = "db-library-tree.v1"

__version__ = "0.1.0"


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_SOURCE = DEFAULT_PUBLICATION_SOURCE or "database"
DEFAULT_ROOT_ID = "root"
DEFAULT_ROOT_LABEL = "Library"
DEFAULT_UNKNOWN_LABEL = "Unbekannt"
DEFAULT_TREE_LIMIT = 10000

DEFAULT_INCLUDE_EMPTY_NODES = False
DEFAULT_INCLUDE_ITEM_SUMMARIES = False
DEFAULT_INCLUDE_COUNTS = True
DEFAULT_INCLUDE_METADATA = False


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DbLibraryTreeStatus(str, Enum):
    """Status eines Tree-Builds."""

    OK = "ok"
    EMPTY = "empty"
    PARTIAL = "partial"
    ERROR = "error"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


class DbLibraryTreeNodeType(str, Enum):
    """Node-Typen des Library-Trees."""

    ROOT = "root"
    DOMAIN = "domain"
    CATEGORY = "category"
    SUBCATEGORY = "subcategory"
    ITEM = "item"

    @classmethod
    def values(cls) -> Tuple[str, ...]:
        return tuple(item.value for item in cls)


# ---------------------------------------------------------------------------
# Normalization helpers with caches
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1024)
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


@lru_cache(maxsize=1024)
def normalize_label(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()

    if not text:
        return None

    return text


@lru_cache(maxsize=1024)
def normalize_string_cached(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def clear_db_library_tree_builder_caches() -> Dict[str, Any]:
    """Leert alle lokalen Caches dieses Builders."""

    normalize_slug.cache_clear()
    normalize_label.cache_clear()
    normalize_string_cached.cache_clear()

    return {
        "ok": True,
        "cleared": [
            "normalize_slug",
            "normalize_label",
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


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DbLibraryTreeBuilderOptions:
    """Optionen für DB-Library-Tree-Building."""

    include_empty_nodes: bool = DEFAULT_INCLUDE_EMPTY_NODES
    include_item_summaries: bool = DEFAULT_INCLUDE_ITEM_SUMMARIES
    include_counts: bool = DEFAULT_INCLUDE_COUNTS
    include_metadata: bool = DEFAULT_INCLUDE_METADATA

    root_id: str = DEFAULT_ROOT_ID
    root_label: str = DEFAULT_ROOT_LABEL
    unknown_label: str = DEFAULT_UNKNOWN_LABEL

    item_limit: int = DEFAULT_TREE_LIMIT
    source: str = DEFAULT_SOURCE

    def normalized(self) -> "DbLibraryTreeBuilderOptions":
        return DbLibraryTreeBuilderOptions(
            include_empty_nodes=bool(self.include_empty_nodes),
            include_item_summaries=bool(self.include_item_summaries),
            include_counts=bool(self.include_counts),
            include_metadata=bool(self.include_metadata),
            root_id=normalize_string(self.root_id) or DEFAULT_ROOT_ID,
            root_label=normalize_label(self.root_label) or DEFAULT_ROOT_LABEL,
            unknown_label=normalize_label(self.unknown_label) or DEFAULT_UNKNOWN_LABEL,
            item_limit=max(0, safe_int(self.item_limit, DEFAULT_TREE_LIMIT)),
            source=normalize_string(self.source) or DEFAULT_SOURCE,
        )


@dataclass
class DbLibraryTreeNode:
    """Tree Node für Domain/Kategorie/Subkategorie/Item."""

    id: str
    label: str
    type: str = DbLibraryTreeNodeType.ROOT.value
    parent_id: Optional[str] = None
    path: Optional[str] = None
    item_ids: List[str] = field(default_factory=list)
    children: List["DbLibraryTreeNode"] = field(default_factory=list)
    count: int = 0
    item_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_child(self, node: "DbLibraryTreeNode") -> "DbLibraryTreeNode":
        for existing in self.children:
            if existing.id == node.id:
                return existing

        self.children.append(node)
        return node

    def add_item_id(self, item_id: str) -> None:
        if item_id and item_id not in self.item_ids:
            self.item_ids.append(item_id)
            self.item_count = len(self.item_ids)
            self.count = max(self.count, self.item_count)

    def increment_count(self, value: int = 1) -> None:
        self.count += value

    def sort_recursive(self) -> None:
        self.children.sort(
            key=lambda node: (
                node.type,
                node.label.lower(),
                node.id,
            )
        )

        for child in self.children:
            child.sort_recursive()

    def to_dict(
        self,
        *,
        include_counts: bool = True,
        include_metadata: bool = False,
    ) -> Dict[str, Any]:
        payload = {
            "id": self.id,
            "label": self.label,
            "type": self.type,
            "parent_id": self.parent_id,
            "path": self.path or self.id,
            "item_ids": list(self.item_ids),
            "children": [
                child.to_dict(
                    include_counts=include_counts,
                    include_metadata=include_metadata,
                )
                for child in self.children
            ],
        }

        if include_counts:
            payload["count"] = self.count
            payload["item_count"] = self.item_count

        if include_metadata:
            payload["metadata"] = json_safe(self.metadata)

        return payload


@dataclass
class DbLibraryTreeBuildResult:
    """Ergebnis eines Tree-Builds."""

    ok: bool = True
    status: str = DbLibraryTreeStatus.OK.value
    tree: Optional[DbLibraryTreeNode] = None
    items: List[Any] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    source: str = DEFAULT_SOURCE
    filters: Dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=utcnow)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(
        self,
        *,
        include_item_summaries: bool = False,
        include_counts: bool = True,
        include_metadata: bool = False,
    ) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "source": self.source,
            "tree": self.tree.to_dict(
                include_counts=include_counts,
                include_metadata=include_metadata,
            ) if self.tree else None,
            "items": [
                summary_to_dict(item, include_metadata=include_metadata)
                for item in self.items
            ] if include_item_summaries else [],
            "count": self.tree.count if self.tree else 0,
            "stats": json_safe(self.stats),
            "filters": json_safe(self.filters),
            "generated_at": safe_isoformat(self.generated_at),
            "warnings": json_safe(self.warnings),
            "errors": json_safe(self.errors),
            "metadata": json_safe(self.metadata) if include_metadata else {},
        }


# ---------------------------------------------------------------------------
# Summary normalization
# ---------------------------------------------------------------------------


def _require_publication_domain() -> None:
    if _PUBLICATION_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Publication domain models are not available: "
            f"{_PUBLICATION_IMPORT_ERROR.__class__.__name__}: {_PUBLICATION_IMPORT_ERROR}"
        )


def build_summary(value: Any) -> Any:
    """Normalisiert DB-/Repository-Row in PublishedFamilySummary."""

    _require_publication_domain()

    if PublishedFamilySummary is not None and isinstance(value, PublishedFamilySummary):
        return value

    return PublishedFamilySummary.from_mapping(value)  # type: ignore[union-attr]


def build_summaries(values: Iterable[Any], *, limit: int = DEFAULT_TREE_LIMIT) -> List[Any]:
    """Normalisiert mehrere Rows in PublishedFamilySummary-Liste."""

    result = []

    for value in truncate_list(list(values), limit):
        result.append(build_summary(value))

    return result


def summary_to_dict(summary: Any, *, include_metadata: bool = False) -> Dict[str, Any]:
    """Serialisiert Summary robust."""

    if hasattr(summary, "to_dict") and callable(summary.to_dict):
        try:
            return summary.to_dict(
                include_payload=False,
                include_metadata=include_metadata,
                include_assets=True,
                include_revision=True,
            )
        except TypeError:
            try:
                return summary.to_dict()
            except Exception:
                pass

    return json_safe(to_mapping(summary))


def summary_item_id(summary: Any) -> Optional[str]:
    """Bestimmt stabile Item-ID für Tree item_ids."""

    return normalize_string(
        first_non_empty(
            getattr(summary, "id", None),
            getattr(summary, "family_id", None),
            getattr(summary, "vplib_uid", None),
            getattr(summary, "package_id", None),
        )
    )


def summary_domain(summary: Any, *, unknown: str = DEFAULT_UNKNOWN_LABEL) -> Tuple[str, str]:
    raw = first_non_empty(getattr(summary, "domain", None), "unknown")
    slug = normalize_slug(raw) or "unknown"
    label = normalize_label(raw) or unknown
    return slug, label


def summary_category(summary: Any, *, unknown: str = DEFAULT_UNKNOWN_LABEL) -> Tuple[str, str]:
    raw = first_non_empty(getattr(summary, "category", None), "unknown")
    slug = normalize_slug(raw) or "unknown"
    label = normalize_label(raw) or unknown
    return slug, label


def summary_subcategory(summary: Any, *, unknown: str = DEFAULT_UNKNOWN_LABEL) -> Tuple[str, str]:
    raw = first_non_empty(getattr(summary, "subcategory", None), "unknown")
    slug = normalize_slug(raw) or "unknown"
    label = normalize_label(raw) or unknown
    return slug, label


# ---------------------------------------------------------------------------
# Tree construction
# ---------------------------------------------------------------------------


def make_tree_node(
    *,
    node_id: str,
    label: Optional[str] = None,
    node_type: str = DbLibraryTreeNodeType.ROOT.value,
    parent_id: Optional[str] = None,
    path: Optional[str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbLibraryTreeNode:
    """Erzeugt Tree Node."""

    return DbLibraryTreeNode(
        id=node_id,
        label=label or node_id,
        type=node_type,
        parent_id=parent_id,
        path=path or node_id,
        metadata=dict(metadata or {}),
    )


def add_item_to_tree(
    root: DbLibraryTreeNode,
    summary: Any,
    *,
    options: DbLibraryTreeBuilderOptions,
    node_maps: Optional[Dict[str, Dict[Any, DbLibraryTreeNode]]] = None,
) -> None:
    """Fügt eine Summary in den Tree ein."""

    item_id = summary_item_id(summary)

    if not item_id:
        return

    domain_slug, domain_label = summary_domain(summary, unknown=options.unknown_label)
    category_slug, category_label = summary_category(summary, unknown=options.unknown_label)
    subcategory_slug, subcategory_label = summary_subcategory(summary, unknown=options.unknown_label)

    if node_maps is None:
        node_maps = {
            "domain": {},
            "category": {},
            "subcategory": {},
        }

    domain_key = domain_slug
    category_key = (domain_slug, category_slug)
    subcategory_key = (domain_slug, category_slug, subcategory_slug)

    domain_node = node_maps["domain"].get(domain_key)

    if domain_node is None:
        domain_node = make_tree_node(
            node_id=domain_slug,
            label=domain_label,
            node_type=DbLibraryTreeNodeType.DOMAIN.value,
            parent_id=root.id,
            path=domain_slug,
            metadata={
                "domain": domain_slug,
            },
        )
        root.add_child(domain_node)
        node_maps["domain"][domain_key] = domain_node

    category_node = node_maps["category"].get(category_key)

    if category_node is None:
        category_node = make_tree_node(
            node_id=f"{domain_slug}/{category_slug}",
            label=category_label,
            node_type=DbLibraryTreeNodeType.CATEGORY.value,
            parent_id=domain_node.id,
            path=f"{domain_slug}/{category_slug}",
            metadata={
                "domain": domain_slug,
                "category": category_slug,
            },
        )
        domain_node.add_child(category_node)
        node_maps["category"][category_key] = category_node

    subcategory_node = node_maps["subcategory"].get(subcategory_key)

    if subcategory_node is None:
        subcategory_node = make_tree_node(
            node_id=f"{domain_slug}/{category_slug}/{subcategory_slug}",
            label=subcategory_label,
            node_type=DbLibraryTreeNodeType.SUBCATEGORY.value,
            parent_id=category_node.id,
            path=f"{domain_slug}/{category_slug}/{subcategory_slug}",
            metadata={
                "domain": domain_slug,
                "category": category_slug,
                "subcategory": subcategory_slug,
            },
        )
        category_node.add_child(subcategory_node)
        node_maps["subcategory"][subcategory_key] = subcategory_node

    subcategory_node.add_item_id(item_id)

    if options.include_item_summaries:
        item_node = make_tree_node(
            node_id=item_id,
            label=getattr(summary, "label", None) or item_id,
            node_type=DbLibraryTreeNodeType.ITEM.value,
            parent_id=subcategory_node.id,
            path=f"{subcategory_node.path}/{item_id}",
            metadata={
                "summary": summary_to_dict(summary, include_metadata=options.include_metadata),
            },
        )
        subcategory_node.add_child(item_node)

    # Counts hochzählen.
    root.increment_count(1)
    domain_node.increment_count(1)
    category_node.increment_count(1)


def prune_empty_nodes(node: DbLibraryTreeNode) -> Optional[DbLibraryTreeNode]:
    """
    Entfernt leere Nodes rekursiv.

    Root bleibt erhalten.
    """

    pruned_children: List[DbLibraryTreeNode] = []

    for child in node.children:
        pruned = prune_empty_nodes(child)

        if pruned is not None:
            pruned_children.append(pruned)

    node.children = pruned_children

    if node.type == DbLibraryTreeNodeType.ROOT.value:
        return node

    if node.item_ids or node.children or node.count > 0:
        return node

    return None


def build_tree_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
) -> DbLibraryTreeNode:
    """Baut Tree Node aus PublishedFamilySummary-Liste."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    root = make_tree_node(
        node_id=options.root_id,
        label=options.root_label,
        node_type=DbLibraryTreeNodeType.ROOT.value,
        parent_id=None,
        path=options.root_id,
        metadata={
            "source": options.source,
            "builder": DB_LIBRARY_TREE_BUILDER_NAME,
        },
    )

    node_maps: Dict[str, Dict[Any, DbLibraryTreeNode]] = {
        "domain": {},
        "category": {},
        "subcategory": {},
    }

    for summary in summaries:
        add_item_to_tree(
            root,
            summary,
            options=options,
            node_maps=node_maps,
        )

    if not options.include_empty_nodes:
        root = prune_empty_nodes(root) or root

    root.sort_recursive()
    return root


def build_tree_from_db_rows(
    rows: Iterable[Any],
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
) -> Tuple[DbLibraryTreeNode, List[Any]]:
    """Normalisiert Rows und baut Tree."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    summaries = build_summaries(
        rows,
        limit=options.item_limit,
    )

    tree = build_tree_from_summaries(
        summaries,
        options=options,
    )

    return tree, summaries


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def build_tree_stats(summaries: Iterable[Any], tree: Optional[DbLibraryTreeNode] = None) -> Dict[str, Any]:
    """Baut Stats für Tree-Response."""

    items = list(summaries)

    if PublishedLibraryStats is not None:
        try:
            base = PublishedLibraryStats.from_families(items).to_dict()  # type: ignore[union-attr]
        except Exception:
            base = {}
    else:
        base = {}

    domains = {getattr(item, "domain", None) for item in items if getattr(item, "domain", None)}
    categories = {
        (getattr(item, "domain", None), getattr(item, "category", None))
        for item in items
        if getattr(item, "domain", None) and getattr(item, "category", None)
    }
    subcategories = {
        (
            getattr(item, "domain", None),
            getattr(item, "category", None),
            getattr(item, "subcategory", None),
        )
        for item in items
        if getattr(item, "domain", None)
        and getattr(item, "category", None)
        and getattr(item, "subcategory", None)
    }

    base.update(
        {
            "item_count": len(items),
            "domain_count": len(domains),
            "category_count": len(categories),
            "subcategory_count": len(subcategories),
            "tree_count": tree.count if tree else len(items),
        }
    )

    return base


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------


def build_tree_result_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbLibraryTreeBuildResult:
    """Baut DbLibraryTreeBuildResult aus PublishedFamilySummary-Liste."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()
    items = list(summaries)

    tree = build_tree_from_summaries(
        items,
        options=options,
    )

    status = DbLibraryTreeStatus.OK.value if items else DbLibraryTreeStatus.EMPTY.value

    return DbLibraryTreeBuildResult(
        ok=True,
        status=status,
        tree=tree,
        items=items,
        stats=build_tree_stats(items, tree),
        source=options.source,
        filters=dict(filters or {}),
        metadata=dict(metadata or {}),
    )


def build_tree_result_from_db_rows(
    rows: Iterable[Any],
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> DbLibraryTreeBuildResult:
    """Baut DbLibraryTreeBuildResult direkt aus DB-/Repository-Rows."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    tree, summaries = build_tree_from_db_rows(
        rows,
        options=options,
    )

    status = DbLibraryTreeStatus.OK.value if summaries else DbLibraryTreeStatus.EMPTY.value

    return DbLibraryTreeBuildResult(
        ok=True,
        status=status,
        tree=tree,
        items=summaries,
        stats=build_tree_stats(summaries, tree),
        source=options.source,
        filters=dict(filters or {}),
        metadata=dict(metadata or {}),
    )


def build_tree_response_from_summaries(
    summaries: Iterable[Any],
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Tree-Response aus Summaries."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    result = build_tree_result_from_summaries(
        summaries,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    return result.to_dict(
        include_item_summaries=options.include_item_summaries,
        include_counts=options.include_counts,
        include_metadata=options.include_metadata,
    )


def build_tree_response_from_db_rows(
    rows: Iterable[Any],
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """API-kompatible Tree-Response direkt aus DB-/Repository-Rows."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    result = build_tree_result_from_db_rows(
        rows,
        options=options,
        filters=filters,
        metadata=metadata,
    )

    return result.to_dict(
        include_item_summaries=options.include_item_summaries,
        include_counts=options.include_counts,
        include_metadata=options.include_metadata,
    )


def build_empty_tree_response(
    *,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
    filters: Optional[Mapping[str, Any]] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Leere Tree-Response."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    root = make_tree_node(
        node_id=options.root_id,
        label=options.root_label,
        node_type=DbLibraryTreeNodeType.ROOT.value,
        path=options.root_id,
        metadata={
            "source": options.source,
            "builder": DB_LIBRARY_TREE_BUILDER_NAME,
        },
    )

    result = DbLibraryTreeBuildResult(
        ok=True,
        status=DbLibraryTreeStatus.EMPTY.value,
        tree=root,
        items=[],
        stats={
            "item_count": 0,
            "domain_count": 0,
            "category_count": 0,
            "subcategory_count": 0,
            "tree_count": 0,
        },
        source=options.source,
        filters=dict(filters or {}),
        metadata=dict(metadata or {}),
    )

    return result.to_dict(
        include_item_summaries=options.include_item_summaries,
        include_counts=options.include_counts,
        include_metadata=options.include_metadata,
    )


def build_error_tree_response(
    error: Any,
    *,
    message: Optional[str] = None,
    options: Optional[DbLibraryTreeBuilderOptions] = None,
) -> Dict[str, Any]:
    """Fehlerhafte Tree-Response."""

    options = (options or DbLibraryTreeBuilderOptions()).normalized()

    return {
        "ok": False,
        "status": DbLibraryTreeStatus.ERROR.value,
        "message": message or str(error),
        "error_type": error.__class__.__name__ if error is not None else None,
        "tree": None,
        "items": [],
        "count": 0,
        "stats": {},
        "filters": {},
        "source": options.source,
        "generated_at": safe_isoformat(utcnow()),
    }


# ---------------------------------------------------------------------------
# Options builders
# ---------------------------------------------------------------------------


def build_options_from_query(
    query: Optional[Mapping[str, Any]] = None,
    *,
    defaults: Optional[DbLibraryTreeBuilderOptions] = None,
) -> DbLibraryTreeBuilderOptions:
    """
    Baut Builder-Optionen aus Query-/Request-Parametern.

    Diese Funktion importiert kein Flask. Übergib request.args als Mapping.
    """

    data = dict(query or {})
    defaults = defaults or DbLibraryTreeBuilderOptions()

    return DbLibraryTreeBuilderOptions(
        include_empty_nodes=safe_bool(
            first_non_empty(data.get("include_empty_nodes"), data.get("empty_nodes")),
            defaults.include_empty_nodes,
        ),
        include_item_summaries=safe_bool(
            first_non_empty(data.get("include_item_summaries"), data.get("items")),
            defaults.include_item_summaries,
        ),
        include_counts=safe_bool(
            first_non_empty(data.get("include_counts"), data.get("counts")),
            defaults.include_counts,
        ),
        include_metadata=safe_bool(
            first_non_empty(data.get("include_metadata"), data.get("metadata")),
            defaults.include_metadata,
        ),
        root_id=first_non_empty(data.get("root_id"), defaults.root_id),
        root_label=first_non_empty(data.get("root_label"), defaults.root_label),
        unknown_label=first_non_empty(data.get("unknown_label"), defaults.unknown_label),
        item_limit=safe_int(data.get("limit"), defaults.item_limit),
        source=first_non_empty(data.get("source"), defaults.source),
    ).normalized()


def build_filters_from_query(query: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Extrahiert fachliche Tree-Filter aus Query-Mapping."""

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


def get_db_library_tree_builder_health() -> Dict[str, Any]:
    """Leichter Health-Check für diesen Builder."""

    return {
        "ok": _PUBLICATION_IMPORT_ERROR is None,
        "status": "ok" if _PUBLICATION_IMPORT_ERROR is None else "error",
        "component": DB_LIBRARY_TREE_COMPONENT_NAME,
        "builder": DB_LIBRARY_TREE_BUILDER_NAME,
        "api_version": DB_LIBRARY_TREE_API_VERSION,
        "model_version": DB_LIBRARY_TREE_MODEL_VERSION,
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
            "root_id": DEFAULT_ROOT_ID,
            "root_label": DEFAULT_ROOT_LABEL,
            "unknown_label": DEFAULT_UNKNOWN_LABEL,
            "tree_limit": DEFAULT_TREE_LIMIT,
            "include_empty_nodes": DEFAULT_INCLUDE_EMPTY_NODES,
            "include_item_summaries": DEFAULT_INCLUDE_ITEM_SUMMARIES,
            "include_counts": DEFAULT_INCLUDE_COUNTS,
            "include_metadata": DEFAULT_INCLUDE_METADATA,
        },
        "enums": {
            "status": list(DbLibraryTreeStatus.values()),
            "node_type": list(DbLibraryTreeNodeType.values()),
        },
        "cache": {
            "normalize_slug": normalize_slug.cache_info()._asdict(),
            "normalize_label": normalize_label.cache_info()._asdict(),
            "normalize_string_cached": normalize_string_cached.cache_info()._asdict(),
        },
    }


def assert_db_library_tree_builder_ready() -> Dict[str, Any]:
    """Wirft RuntimeError, wenn der Builder nicht bereit ist."""

    health = get_db_library_tree_builder_health()

    if not health.get("ok"):
        raise RuntimeError(
            "DB library tree builder is not ready: "
            f"{health.get('publication_domain_error')}"
        )

    return health


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "DB_LIBRARY_TREE_BUILDER_NAME",
    "DB_LIBRARY_TREE_COMPONENT_NAME",
    "DB_LIBRARY_TREE_API_VERSION",
    "DB_LIBRARY_TREE_MODEL_VERSION",

    # Defaults
    "DEFAULT_SOURCE",
    "DEFAULT_ROOT_ID",
    "DEFAULT_ROOT_LABEL",
    "DEFAULT_UNKNOWN_LABEL",
    "DEFAULT_TREE_LIMIT",
    "DEFAULT_INCLUDE_EMPTY_NODES",
    "DEFAULT_INCLUDE_ITEM_SUMMARIES",
    "DEFAULT_INCLUDE_COUNTS",
    "DEFAULT_INCLUDE_METADATA",

    # Enums
    "DbLibraryTreeStatus",
    "DbLibraryTreeNodeType",

    # Options/models
    "DbLibraryTreeBuilderOptions",
    "DbLibraryTreeNode",
    "DbLibraryTreeBuildResult",

    # Generic helpers
    "utcnow",
    "safe_isoformat",
    "safe_int",
    "safe_bool",
    "normalize_slug",
    "normalize_label",
    "normalize_string",
    "normalize_vplib_uid",
    "first_non_empty",
    "json_safe",
    "to_mapping",
    "listify",
    "truncate_list",
    "clear_db_library_tree_builder_caches",

    # Summary helpers
    "build_summary",
    "build_summaries",
    "summary_to_dict",
    "summary_item_id",
    "summary_domain",
    "summary_category",
    "summary_subcategory",

    # Tree construction
    "make_tree_node",
    "add_item_to_tree",
    "prune_empty_nodes",
    "build_tree_from_summaries",
    "build_tree_from_db_rows",
    "build_tree_stats",

    # Response builders
    "build_tree_result_from_summaries",
    "build_tree_result_from_db_rows",
    "build_tree_response_from_summaries",
    "build_tree_response_from_db_rows",
    "build_empty_tree_response",
    "build_error_tree_response",

    # Query helpers
    "build_options_from_query",
    "build_filters_from_query",

    # Health
    "get_db_library_tree_builder_health",
    "assert_db_library_tree_builder_ready",
]