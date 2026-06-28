# services/vectoplan-library/src/library/services/library_taxonomy_user_service.py
"""
Service for user-resolved VECTOPLAN Library Taxonomy.

Diese Datei baut die fachliche Service-Schicht über:

- src/library/repositories/library_taxonomy_repository.py
- models/library_taxonomy.py

Ziel:

    System Taxonomy
        + User Taxonomy Nodes
        + User Taxonomy Overrides
        -> resolved taxonomy for user_id
        -> Creative Inventory Navigation
        -> Create Options
        -> User-owned tabs/categories/subcategories

Aufgaben:

- resolved taxonomy für user_id bauen
- eigene Reiter/Domains anlegen
- eigene Kategorien anlegen
- eigene Subkategorien anlegen
- Usernodes ändern/löschen/wiederherstellen
- Systemnodes per Override ausblenden
- Systemnodes per Override umbenennen
- Systemnodes per Override sortieren
- Navigation/Create-Options aus resolved taxonomy bauen
- Audit-Payloads lesbar bereitstellen

Architekturregeln:

- Service enthält keine Flask-Route.
- Service enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über LibraryTaxonomyRepository.
- User-Erweiterungen sind User-Nodes.
- Änderungen an Systemnodes sind User-Overrides.
- Systemnodes werden nicht pro User kopiert.
- Service erzeugt keine Tabellen.
- Service führt keine Migration aus.
- Service führt kein db.create_all() aus.
- Service öffnet keine aktive DB-Verbindung beim Import.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_scope="user:1" bei Usernodes.
- owner_scope="system" bei Systemnodes.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_TAXONOMY_USER_SERVICE_VERSION: Final[str] = "vectoplan_library.service.library_taxonomy_user.v1"

DEFAULT_USER_ID: Final[int] = 1

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_USER: Final[str] = "user"

NODE_TYPE_DOMAIN: Final[str] = "domain"
NODE_TYPE_CATEGORY: Final[str] = "category"
NODE_TYPE_SUBCATEGORY: Final[str] = "subcategory"

ACTION_HIDE: Final[str] = "hide"
ACTION_RESTORE: Final[str] = "restore"
ACTION_RENAME: Final[str] = "rename"
ACTION_REORDER: Final[str] = "reorder"
ACTION_MOVE: Final[str] = "move"
ACTION_PATCH: Final[str] = "patch"
ACTION_DELETE: Final[str] = "delete"

STATUS_OK: Final[str] = "ok"
STATUS_INVALID_REQUEST: Final[str] = "invalid_request"
STATUS_NOT_FOUND: Final[str] = "not_found"
STATUS_FAILED: Final[str] = "failed"

MAX_LIMIT: Final[int] = 2000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryTaxonomyUserServiceError(RuntimeError):
    """Base error for LibraryTaxonomyUserService."""


class LibraryTaxonomyUserServiceImportError(LibraryTaxonomyUserServiceError):
    """Raised when repository imports fail."""


class LibraryTaxonomyUserServiceValidationError(LibraryTaxonomyUserServiceError):
    """Raised when input payload is invalid."""

    def __init__(self, message: str, *, errors: Iterable[Any] | None = None) -> None:
        super().__init__(message)
        self.errors = [str(error) for error in (errors or [])]


class LibraryTaxonomyUserServiceNotFoundError(LibraryTaxonomyUserServiceError):
    """Raised when a requested taxonomy entity cannot be found."""


class LibraryTaxonomyUserServiceConflictError(LibraryTaxonomyUserServiceError):
    """Raised when a requested operation conflicts with taxonomy ownership."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> ModuleType:
    """Loads library_taxonomy_repository defensively."""
    errors: list[str] = []

    for module_name in (
        "library.repositories.library_taxonomy_repository",
        "src.library.repositories.library_taxonomy_repository",
        "vectoplan_library.library.repositories.library_taxonomy_repository",
        "vectoplan_library.src.library.repositories.library_taxonomy_repository",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryTaxonomyUserServiceImportError(
        "Could not import library_taxonomy_repository. "
        + " | ".join(errors)
    )


def _repo_module() -> ModuleType:
    """Short alias for repository module."""
    return _load_repository_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "selectable"}:
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


def first_non_empty(*values: Any) -> Any:
    """Returns first non-empty value."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Builds taxonomy path."""
    helper = getattr(_repo_module(), "taxonomy_path_for", None)

    if callable(helper):
        try:
            return helper(domain=domain, category=category, subcategory=subcategory)
        except Exception:
            pass

    parts = [
        optional_string(domain),
        optional_string(category),
        optional_string(subcategory),
    ]
    cleaned = [part for part in parts if part]
    return "/".join(cleaned) if cleaned else None


def infer_node_type(
    *,
    node_type: Any = None,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    parent_node_id: Any = None,
) -> str:
    """Infers node type."""
    helper = getattr(_repo_module(), "infer_node_type", None)

    if callable(helper):
        try:
            return str(
                helper(
                    node_type=node_type,
                    domain=domain,
                    category=category,
                    subcategory=subcategory,
                    parent_node_id=parent_node_id,
                )
            )
        except Exception:
            pass

    explicit = optional_string(node_type)
    if explicit:
        return explicit

    if subcategory:
        return NODE_TYPE_SUBCATEGORY

    if category:
        return NODE_TYPE_CATEGORY

    return NODE_TYPE_DOMAIN


def node_is_system(node: Any | Mapping[str, Any] | None) -> bool:
    """Checks whether node belongs to system taxonomy."""
    if node is None:
        return False

    if isinstance(node, Mapping):
        owner_scope = optional_string(node.get("owner_scope"))
        source_scope = optional_string(node.get("source_scope"))
    else:
        owner_scope = optional_string(getattr(node, "owner_scope", None))
        source_scope = optional_string(getattr(node, "source_scope", None))

    return owner_scope == SOURCE_SCOPE_SYSTEM or source_scope == SOURCE_SCOPE_SYSTEM


def node_is_user(node: Any | Mapping[str, Any] | None, *, user_id: Any = DEFAULT_USER_ID) -> bool:
    """Checks whether node is owned by user."""
    if node is None:
        return False

    normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)

    if isinstance(node, Mapping):
        owner_scope = optional_string(node.get("owner_scope"))
        owner_user_id = normalize_user_id(node.get("owner_user_id"), default=None)
    else:
        owner_scope = optional_string(getattr(node, "owner_scope", None))
        owner_user_id = normalize_user_id(getattr(node, "owner_user_id", None), default=None)

    return owner_scope == f"user:{normalized_user_id}" or owner_user_id == normalized_user_id


def to_dict_or_payload(value: Any, **kwargs: Any) -> dict[str, Any]:
    """Serializes model objects defensively."""
    helper = getattr(_repo_module(), "to_dict_or_payload", None)

    if callable(helper):
        try:
            return normalize_json_mapping(helper(value, **kwargs))
        except Exception:
            pass

    if value is None:
        return {}

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_json_mapping(value.to_dict(**kwargs))
        except TypeError:
            try:
                return normalize_json_mapping(value.to_dict())
            except Exception:
                pass
        except Exception:
            pass

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    return {"value": str(value)}


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    """Dedupe values as strings preserving order."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        text = clean_string(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)

    return result


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TaxonomyContextQuery:
    """Request object for taxonomy reads."""

    user_id: int = DEFAULT_USER_ID
    include_hidden: bool = False
    include_deleted: bool = False
    include_tree: bool = True
    include_nodes: bool = True
    include_create_options: bool = False

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "TaxonomyContextQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            include_hidden=normalize_bool(data.get("include_hidden"), default=False),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            include_tree=normalize_bool(data.get("include_tree"), default=True),
            include_nodes=normalize_bool(data.get("include_nodes"), default=True),
            include_create_options=normalize_bool(data.get("include_create_options"), default=False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "include_hidden": self.include_hidden,
            "include_deleted": self.include_deleted,
            "include_tree": self.include_tree,
            "include_nodes": self.include_nodes,
            "include_create_options": self.include_create_options,
        }


@dataclass(slots=True)
class TaxonomyNodeInput:
    """Normalized taxonomy node input."""

    user_id: int = DEFAULT_USER_ID
    node_type: str | None = None
    parent_node_uid: str | None = None
    parent_node_id: int | None = None
    parent_taxonomy_path: str | None = None
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    taxonomy_path: str | None = None
    node_key: str | None = None
    slug: str | None = None
    label: str | None = None
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int = 0
    active: bool = True
    visible: bool = True
    selectable: bool = True
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "TaxonomyNodeInput":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        domain = optional_string(data.get("domain"))
        category = optional_string(data.get("category"))
        subcategory = optional_string(data.get("subcategory"))
        taxonomy_path = optional_string(data.get("taxonomy_path")) or taxonomy_path_for(
            domain=domain,
            category=category,
            subcategory=subcategory,
        )

        node_type = infer_node_type(
            node_type=data.get("node_type"),
            domain=domain,
            category=category,
            subcategory=subcategory,
            parent_node_id=data.get("parent_node_id"),
        )

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            node_type=node_type,
            parent_node_uid=optional_string(data.get("parent_node_uid")),
            parent_node_id=normalize_int(data.get("parent_node_id"), default=None, minimum=1),
            parent_taxonomy_path=optional_string(data.get("parent_taxonomy_path")),
            domain=domain,
            category=category,
            subcategory=subcategory,
            taxonomy_path=taxonomy_path,
            node_key=optional_string(data.get("node_key") or data.get("key") or taxonomy_path),
            slug=optional_string(data.get("slug")),
            label=optional_string(data.get("label") or data.get("name")),
            name=optional_string(data.get("name") or data.get("label")),
            description=optional_string(data.get("description")),
            icon=optional_string(data.get("icon")),
            color=optional_string(data.get("color")),
            sort_order=normalize_int(data.get("sort_order"), default=0, minimum=0) or 0,
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            selectable=normalize_bool(data.get("selectable"), default=True),
            payload=normalize_json_mapping(data.get("payload") or data),
            metadata=normalize_json_mapping(data.get("metadata")),
        )

    def validate(self) -> None:
        errors: list[str] = []

        if self.node_type not in {NODE_TYPE_DOMAIN, NODE_TYPE_CATEGORY, NODE_TYPE_SUBCATEGORY}:
            errors.append(f"invalid node_type {self.node_type!r}")

        if self.node_type == NODE_TYPE_DOMAIN and not self.domain:
            errors.append("domain is required for domain node")

        if self.node_type == NODE_TYPE_CATEGORY and not self.category:
            errors.append("category is required for category node")

        if self.node_type == NODE_TYPE_SUBCATEGORY and not self.subcategory:
            errors.append("subcategory is required for subcategory node")

        if not self.label and not self.name:
            errors.append("label or name is required")

        if errors:
            raise LibraryTaxonomyUserServiceValidationError(
                "Invalid taxonomy node input.",
                errors=errors,
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "node_type": self.node_type,
            "parent_node_uid": self.parent_node_uid,
            "parent_node_id": self.parent_node_id,
            "parent_taxonomy_path": self.parent_taxonomy_path,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "node_key": self.node_key,
            "slug": self.slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "sort_order": self.sort_order,
            "active": self.active,
            "visible": self.visible,
            "selectable": self.selectable,
            "payload": normalize_json_mapping(self.payload),
            "metadata": normalize_json_mapping(self.metadata),
        }


@dataclass(slots=True)
class TaxonomyActionInput:
    """Normalized taxonomy action input."""

    user_id: int = DEFAULT_USER_ID
    node_ref: str | int | None = None
    action: str = ACTION_PATCH
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int | None = None
    parent_node_uid: str | None = None
    payload_patch: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "TaxonomyActionInput":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            node_ref=first_non_empty(data.get("node_ref"), data.get("node_uid"), data.get("node_id"), data.get("target_node_uid")),
            action=clean_string(data.get("action") or data.get("override_action"), fallback=ACTION_PATCH).lower(),
            label=optional_string(data.get("label") or data.get("label_override")),
            description=optional_string(data.get("description") or data.get("description_override")),
            icon=optional_string(data.get("icon") or data.get("icon_override")),
            color=optional_string(data.get("color") or data.get("color_override")),
            sort_order=normalize_int(data.get("sort_order") or data.get("sort_order_override"), default=None, minimum=0),
            parent_node_uid=optional_string(data.get("parent_node_uid") or data.get("parent_node_uid_override")),
            payload_patch=normalize_json_mapping(data.get("payload_patch") or data.get("patch")),
            metadata=normalize_json_mapping(data.get("metadata")),
        )

    def to_override_payload(self, *, target_node_uid: str) -> dict[str, Any]:
        payload = {
            "user_id": self.user_id,
            "target_node_uid": target_node_uid,
            "override_action": self.action,
            "active": True,
            "payload_patch": normalize_json_mapping(self.payload_patch),
            "metadata": normalize_json_mapping(self.metadata),
        }

        if self.action == ACTION_HIDE:
            payload["visible_override"] = False

        if self.action == ACTION_RESTORE:
            payload["visible_override"] = True
            payload["active_override"] = True
            payload["selectable_override"] = True

        if self.label is not None:
            payload["label_override"] = self.label

        if self.description is not None:
            payload["description_override"] = self.description

        if self.icon is not None:
            payload["icon_override"] = self.icon

        if self.color is not None:
            payload["color_override"] = self.color

        if self.sort_order is not None:
            payload["sort_order_override"] = self.sort_order

        if self.parent_node_uid is not None:
            payload["parent_node_uid_override"] = self.parent_node_uid

        return payload


@dataclass(slots=True)
class TaxonomyServiceResult:
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
            "schema_version": LIBRARY_TAXONOMY_USER_SERVICE_VERSION,
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

class LibraryTaxonomyUserService:
    """
    High-level service for user-resolved taxonomy.

    Args:
        repository:
            Optional LibraryTaxonomyRepository instance.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository or self._create_repository()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_repository(self) -> Any:
        repo_module = _repo_module()
        factory = getattr(repo_module, "create_library_taxonomy_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(repo_module, "LibraryTaxonomyRepository", None)
        if repo_class is None:
            raise LibraryTaxonomyUserServiceImportError("LibraryTaxonomyRepository class is not available.")

        return repo_class()

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_resolved_taxonomy(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
        include_tree: bool = True,
        include_nodes: bool = True,
        include_create_options: bool = False,
    ) -> dict[str, Any]:
        """Returns resolved taxonomy payload for user."""
        query = TaxonomyContextQuery.from_payload(
            {
                "user_id": user_id,
                "include_hidden": include_hidden,
                "include_deleted": include_deleted,
                "include_tree": include_tree,
                "include_nodes": include_nodes,
                "include_create_options": include_create_options,
            }
        )

        resolved_payload = self.repository.get_resolved_taxonomy_payload(
            user_id=query.user_id,
            include_hidden=query.include_hidden,
            include_deleted=query.include_deleted,
        )

        nodes = normalize_json_list(resolved_payload.get("nodes"))
        tree = normalize_json_mapping(resolved_payload.get("tree"))

        payload = {
            "schema_version": LIBRARY_TAXONOMY_USER_SERVICE_VERSION,
            "user_id": query.user_id,
            "resolved": True,
            "include_hidden": query.include_hidden,
            "include_deleted": query.include_deleted,
            "node_count": len(nodes),
        }

        if query.include_nodes:
            payload["nodes"] = nodes

        if query.include_tree:
            payload["tree"] = tree

        if query.include_create_options:
            payload["create_options"] = self.build_create_options_from_nodes(nodes)

        return TaxonomyServiceResult(
            ok=True,
            status=STATUS_OK,
            action="get_resolved_taxonomy",
            payload=payload,
        ).to_dict()

    def list_nodes(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = None,
        node_type: Any = None,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        taxonomy_path: Any = None,
        include_system: bool = True,
        include_user: bool = True,
        active_only: bool = True,
        visible_only: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Lists taxonomy nodes."""
        query = {
            "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
            "source_scope": optional_string(source_scope),
            "node_type": optional_string(node_type),
            "domain": optional_string(domain),
            "category": optional_string(category),
            "subcategory": optional_string(subcategory),
            "taxonomy_path": optional_string(taxonomy_path),
            "include_system": include_system,
            "include_user": include_user,
            "active_only": active_only,
            "visible_only": visible_only,
            "include_deleted": include_deleted,
            "limit": MAX_LIMIT,
        }

        nodes = self.repository.list_node_payloads(query=query)

        return TaxonomyServiceResult(
            ok=True,
            status=STATUS_OK,
            action="list_nodes",
            payload={
                "query": normalize_json_mapping(query),
                "count": len(nodes),
                "items": nodes,
            },
        ).to_dict()

    def get_node(self, node_ref: Any) -> dict[str, Any]:
        """Returns one taxonomy node."""
        try:
            node = self.repository.require_node(node_ref)
            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_node",
                payload={"item": to_dict_or_payload(node)},
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="get_node")

    def get_create_options(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_hidden: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """
        Returns taxonomy options for create UI.

        Output:
        - domains
        - categories_by_domain
        - subcategories_by_category_path
        - flat nodes
        """
        nodes = self.repository.get_resolved_nodes(
            user_id=user_id,
            include_hidden=include_hidden,
            include_deleted=include_deleted,
            as_tree=False,
        )

        if not isinstance(nodes, list):
            nodes = []

        options = self.build_create_options_from_nodes(nodes)

        return TaxonomyServiceResult(
            ok=True,
            status=STATUS_OK,
            action="get_create_options",
            payload={
                "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
                **options,
            },
        ).to_dict()

    # ------------------------------------------------------------------
    # Node write API
    # ------------------------------------------------------------------

    def create_node(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates a user-owned taxonomy node."""
        try:
            node_input = TaxonomyNodeInput.from_payload(payload, user_id=user_id)
            node_input.validate()

            parent = self.resolve_parent_for_node_input(node_input)

            node = self.repository.create_node(
                node_input.to_payload(),
                source_scope=SOURCE_SCOPE_USER,
                owner_user_id=node_input.user_id,
                created_by_user_id=node_input.user_id,
                parent=parent,
                commit=commit,
                audit=True,
            )

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="create_node",
                payload={
                    "created": True,
                    "item": to_dict_or_payload(node),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="create_node")

    def create_domain(
        self,
        *,
        domain: Any,
        label: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        sort_order: Any = 0,
        payload: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates a user-owned domain/tab."""
        data = normalize_json_mapping(payload)
        data.update(
            {
                "user_id": user_id,
                "node_type": NODE_TYPE_DOMAIN,
                "domain": domain,
                "taxonomy_path": optional_string(domain),
                "label": label or domain,
                "sort_order": sort_order,
            }
        )
        return self.create_node(data, user_id=user_id, commit=commit)

    def create_category(
        self,
        *,
        domain: Any,
        category: Any,
        label: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        sort_order: Any = 0,
        payload: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates a user-owned category."""
        data = normalize_json_mapping(payload)
        data.update(
            {
                "user_id": user_id,
                "node_type": NODE_TYPE_CATEGORY,
                "domain": domain,
                "category": category,
                "taxonomy_path": taxonomy_path_for(domain=domain, category=category),
                "parent_taxonomy_path": optional_string(domain),
                "label": label or category,
                "sort_order": sort_order,
            }
        )
        return self.create_node(data, user_id=user_id, commit=commit)

    def create_subcategory(
        self,
        *,
        domain: Any,
        category: Any,
        subcategory: Any,
        label: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        sort_order: Any = 0,
        payload: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates a user-owned subcategory."""
        data = normalize_json_mapping(payload)
        data.update(
            {
                "user_id": user_id,
                "node_type": NODE_TYPE_SUBCATEGORY,
                "domain": domain,
                "category": category,
                "subcategory": subcategory,
                "taxonomy_path": taxonomy_path_for(domain=domain, category=category, subcategory=subcategory),
                "parent_taxonomy_path": taxonomy_path_for(domain=domain, category=category),
                "label": label or subcategory,
                "sort_order": sort_order,
            }
        )
        return self.create_node(data, user_id=user_id, commit=commit)

    def update_node(
        self,
        node_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Updates a node.

        - User node: direct update.
        - System node: creates/updates user override with action=patch.
        """
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

            if node_is_system(node):
                override, created = self.repository.upsert_override(
                    {
                        **normalize_json_mapping(payload),
                        "target_node_uid": getattr(node, "node_uid", None),
                        "override_action": ACTION_PATCH,
                        "payload_patch": normalize_json_mapping(payload),
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=normalized_user_id,
                    updated_by_user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                return TaxonomyServiceResult(
                    ok=True,
                    status=STATUS_OK,
                    action="update_system_node_override",
                    payload={
                        "created": created,
                        "updated": not created,
                        "node": to_dict_or_payload(node),
                        "override": to_dict_or_payload(override),
                    },
                ).to_dict()

            if not node_is_user(node, user_id=normalized_user_id):
                raise LibraryTaxonomyUserServiceConflictError("User can only update own taxonomy nodes or override system nodes.")

            updated = self.repository.update_node(
                node_ref,
                payload,
                user_id=normalized_user_id,
                commit=commit,
                audit=True,
            )

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="update_node",
                payload={
                    "updated": True,
                    "item": to_dict_or_payload(updated),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="update_node")

    def delete_node(
        self,
        node_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Deletes or hides a node.

        - User node: soft delete.
        - System node: hide override.
        """
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

            if node_is_system(node):
                override = self.repository.hide_system_node_for_user(
                    node_ref,
                    user_id=normalized_user_id,
                    commit=commit,
                )

                return TaxonomyServiceResult(
                    ok=True,
                    status=STATUS_OK,
                    action="hide_system_node",
                    payload={
                        "hidden": True,
                        "node": to_dict_or_payload(node),
                        "override": to_dict_or_payload(override),
                    },
                ).to_dict()

            if not node_is_user(node, user_id=normalized_user_id):
                raise LibraryTaxonomyUserServiceConflictError("User can only delete own taxonomy nodes or hide system nodes.")

            deleted = self.repository.soft_delete_node(
                node_ref,
                user_id=normalized_user_id,
                commit=commit,
                audit=True,
            )

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_node",
                payload={
                    "deleted": deleted,
                    "node_ref": node_ref,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="delete_node")

    def restore_node(
        self,
        node_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Restores a node.

        - User node: restore direct.
        - System node: create restore override.
        """
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

            if node_is_system(node):
                override, created = self.repository.upsert_override(
                    {
                        "target_node_uid": getattr(node, "node_uid", None),
                        "override_action": ACTION_RESTORE,
                        "visible_override": True,
                        "active_override": True,
                        "selectable_override": True,
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=normalized_user_id,
                    updated_by_user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )

                return TaxonomyServiceResult(
                    ok=True,
                    status=STATUS_OK,
                    action="restore_system_node",
                    payload={
                        "created": created,
                        "restored": True,
                        "node": to_dict_or_payload(node),
                        "override": to_dict_or_payload(override),
                    },
                ).to_dict()

            restored = self.repository.restore_node(
                node_ref,
                user_id=normalized_user_id,
                commit=commit,
                audit=True,
            )

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="restore_node",
                payload={
                    "restored": True,
                    "item": to_dict_or_payload(restored),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="restore_node")

    # ------------------------------------------------------------------
    # Override action API
    # ------------------------------------------------------------------

    def hide_node(
        self,
        node_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Hides a system node by override or a user node directly."""
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID

            if node_is_system(node):
                override = self.repository.hide_system_node_for_user(
                    node_ref,
                    user_id=normalized_user_id,
                    commit=commit,
                )
                payload = {
                    "node": to_dict_or_payload(node),
                    "override": to_dict_or_payload(override),
                }
            else:
                updated = self.repository.update_node(
                    node_ref,
                    {"visible": False, "status": "hidden"},
                    user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                payload = {"node": to_dict_or_payload(updated)}

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="hide_node",
                payload=payload,
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="hide_node")

    def rename_node(
        self,
        node_ref: Any,
        *,
        label: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Renames node directly or via override."""
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID
            new_label = optional_string(label)

            if not new_label:
                raise LibraryTaxonomyUserServiceValidationError("label is required.")

            if node_is_system(node):
                override = self.repository.rename_system_node_for_user(
                    node_ref,
                    label=new_label,
                    user_id=normalized_user_id,
                    commit=commit,
                )
                payload = {
                    "node": to_dict_or_payload(node),
                    "override": to_dict_or_payload(override),
                }
            else:
                updated = self.repository.update_node(
                    node_ref,
                    {"label": new_label, "name": new_label},
                    user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                payload = {"node": to_dict_or_payload(updated)}

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="rename_node",
                payload=payload,
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="rename_node")

    def reorder_node(
        self,
        node_ref: Any,
        *,
        sort_order: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Reorders node directly or via override."""
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID
            normalized_sort_order = normalize_int(sort_order, default=0, minimum=0) or 0

            if node_is_system(node):
                override, created = self.repository.upsert_override(
                    {
                        "target_node_uid": getattr(node, "node_uid", None),
                        "override_action": ACTION_REORDER,
                        "sort_order_override": normalized_sort_order,
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=normalized_user_id,
                    updated_by_user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                payload = {
                    "created": created,
                    "node": to_dict_or_payload(node),
                    "override": to_dict_or_payload(override),
                }
            else:
                updated = self.repository.update_node(
                    node_ref,
                    {"sort_order": normalized_sort_order},
                    user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                payload = {"node": to_dict_or_payload(updated)}

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="reorder_node",
                payload=payload,
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="reorder_node")

    def move_node(
        self,
        node_ref: Any,
        *,
        parent_node_ref: Any,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Moves node directly or via override."""
        try:
            node = self.repository.require_node(node_ref, include_deleted=True)
            parent = self.repository.require_node(parent_node_ref, include_deleted=False)
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID
            parent_uid = getattr(parent, "node_uid", None)

            if not parent_uid:
                raise LibraryTaxonomyUserServiceValidationError("parent node has no node_uid.")

            if node_is_system(node):
                override, created = self.repository.upsert_override(
                    {
                        "target_node_uid": getattr(node, "node_uid", None),
                        "override_action": ACTION_MOVE,
                        "parent_node_uid_override": parent_uid,
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=normalized_user_id,
                    updated_by_user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                payload = {
                    "created": created,
                    "node": to_dict_or_payload(node),
                    "parent": to_dict_or_payload(parent),
                    "override": to_dict_or_payload(override),
                }
            else:
                updated = self.repository.update_node(
                    node_ref,
                    {
                        "parent_node_id": getattr(parent, "id", None),
                        "parent_node_uid": parent_uid,
                        "parent_taxonomy_path": getattr(parent, "taxonomy_path", None),
                    },
                    user_id=normalized_user_id,
                    commit=commit,
                    audit=True,
                )
                payload = {
                    "node": to_dict_or_payload(updated),
                    "parent": to_dict_or_payload(parent),
                }

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="move_node",
                payload=payload,
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="move_node")

    def create_override(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates or updates a user override explicitly."""
        try:
            action_input = TaxonomyActionInput.from_payload(payload, user_id=user_id)

            if not action_input.node_ref:
                raise LibraryTaxonomyUserServiceValidationError("node_ref, node_uid or target_node_uid is required.")

            node = self.repository.require_node(action_input.node_ref, include_deleted=True)
            target_uid = getattr(node, "node_uid", None)

            if not target_uid:
                raise LibraryTaxonomyUserServiceValidationError("target node has no node_uid.")

            override, created = self.repository.upsert_override(
                action_input.to_override_payload(target_node_uid=target_uid),
                user_id=action_input.user_id,
                created_by_user_id=action_input.user_id,
                updated_by_user_id=action_input.user_id,
                commit=commit,
                audit=True,
            )

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="create_override",
                payload={
                    "created": created,
                    "updated": not created,
                    "node": to_dict_or_payload(node),
                    "override": to_dict_or_payload(override),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="create_override")

    def delete_override(
        self,
        *,
        override_ref: Any = None,
        node_ref: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Soft-deletes an override by override_ref or node_ref."""
        try:
            normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID) or DEFAULT_USER_ID
            target_node_uid = None

            if node_ref is not None:
                node = self.repository.require_node(node_ref, include_deleted=True)
                target_node_uid = getattr(node, "node_uid", None)

            deleted = self.repository.soft_delete_override(
                override_ref=override_ref,
                user_id=normalized_user_id,
                target_node_uid=target_node_uid,
                commit=commit,
                audit=True,
            )

            return TaxonomyServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_override",
                payload={
                    "deleted": deleted,
                    "override_ref": override_ref,
                    "node_ref": node_ref,
                    "target_node_uid": target_node_uid,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="delete_override")

    def list_overrides(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        target_node_uid: Any = None,
        active_only: bool = True,
    ) -> dict[str, Any]:
        """Lists user overrides."""
        query = {
            "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
            "target_node_uid": optional_string(target_node_uid),
            "active_only": active_only,
            "limit": MAX_LIMIT,
        }
        items = self.repository.list_override_payloads(query=query)

        return TaxonomyServiceResult(
            ok=True,
            status=STATUS_OK,
            action="list_overrides",
            payload={
                "query": query,
                "count": len(items),
                "items": items,
            },
        ).to_dict()

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def list_audit_events(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        event_type: Any = None,
        node_uid: Any = None,
        target_node_uid: Any = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Lists taxonomy audit events."""
        items = self.repository.list_audit_events(
            user_id=user_id,
            event_type=event_type,
            node_uid=node_uid,
            target_node_uid=target_node_uid,
            limit=limit,
            offset=offset,
            as_dict=True,
        )

        return TaxonomyServiceResult(
            ok=True,
            status=STATUS_OK,
            action="list_audit_events",
            payload={
                "count": len(items),
                "items": items,
            },
        ).to_dict()

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def build_create_options_from_nodes(self, nodes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        """Builds create-options payload from resolved nodes."""
        values = [normalize_json_mapping(node) for node in nodes]

        domains: list[dict[str, Any]] = []
        categories_by_domain: dict[str, list[dict[str, Any]]] = {}
        subcategories_by_category_path: dict[str, list[dict[str, Any]]] = {}

        for node in values:
            node_type = clean_string(node.get("node_type")) or infer_node_type(
                domain=node.get("domain"),
                category=node.get("category"),
                subcategory=node.get("subcategory"),
            )

            domain = optional_string(node.get("domain"))
            category = optional_string(node.get("category"))
            taxonomy_path = optional_string(node.get("taxonomy_path"))

            option = self.node_to_option(node)

            if node_type == NODE_TYPE_DOMAIN and domain:
                domains.append(option)

            elif node_type == NODE_TYPE_CATEGORY and domain:
                categories_by_domain.setdefault(domain, []).append(option)

            elif node_type == NODE_TYPE_SUBCATEGORY and domain and category:
                parent_path = taxonomy_path_for(domain=domain, category=category)
                if parent_path:
                    subcategories_by_category_path.setdefault(parent_path, []).append(option)

            elif taxonomy_path:
                parts = taxonomy_path.split("/")
                if len(parts) == 1:
                    domains.append(option)
                elif len(parts) == 2:
                    categories_by_domain.setdefault(parts[0], []).append(option)
                elif len(parts) >= 3:
                    parent_path = "/".join(parts[:2])
                    subcategories_by_category_path.setdefault(parent_path, []).append(option)

        domains = self.sort_options(domains)

        for key in list(categories_by_domain.keys()):
            categories_by_domain[key] = self.sort_options(categories_by_domain[key])

        for key in list(subcategories_by_category_path.keys()):
            subcategories_by_category_path[key] = self.sort_options(subcategories_by_category_path[key])

        return {
            "domains": domains,
            "categories_by_domain": categories_by_domain,
            "subcategories_by_category_path": subcategories_by_category_path,
            "domain_count": len(domains),
            "category_count": sum(len(items) for items in categories_by_domain.values()),
            "subcategory_count": sum(len(items) for items in subcategories_by_category_path.values()),
        }

    def node_to_option(self, node: Mapping[str, Any]) -> dict[str, Any]:
        """Converts node payload to compact UI option."""
        payload = normalize_json_mapping(node)
        return {
            "node_uid": payload.get("node_uid"),
            "node_type": payload.get("node_type"),
            "node_key": payload.get("node_key"),
            "slug": payload.get("slug"),
            "value": payload.get("taxonomy_path") or payload.get("node_key") or payload.get("slug"),
            "label": payload.get("label") or payload.get("name") or payload.get("node_key"),
            "description": payload.get("description"),
            "domain": payload.get("domain"),
            "category": payload.get("category"),
            "subcategory": payload.get("subcategory"),
            "taxonomy_path": payload.get("taxonomy_path"),
            "parent_node_uid": payload.get("parent_node_uid"),
            "source_scope": payload.get("source_scope"),
            "owner_user_id": payload.get("owner_user_id"),
            "owner_scope": payload.get("owner_scope"),
            "active": payload.get("active", True),
            "visible": payload.get("visible", True),
            "selectable": payload.get("selectable", True),
            "sort_order": payload.get("sort_order", 0),
            "icon": payload.get("icon"),
            "color": payload.get("color"),
        }

    def sort_options(self, values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Sorts option payloads."""
        items = [normalize_json_mapping(item) for item in values]
        items.sort(
            key=lambda item: (
                normalize_int(item.get("sort_order"), default=0) or 0,
                clean_string(item.get("label") or item.get("value") or item.get("taxonomy_path")),
            )
        )
        return items

    def resolve_parent_for_node_input(self, node_input: TaxonomyNodeInput) -> Any | None:
        """Finds parent node for new category/subcategory when possible."""
        if node_input.parent_node_id:
            return self.repository.get_node_by_id(node_input.parent_node_id)

        if node_input.parent_node_uid:
            return self.repository.get_node_by_uid(node_input.parent_node_uid)

        if node_input.parent_taxonomy_path:
            return self.repository.get_node_by_path(
                node_input.parent_taxonomy_path,
                user_id=node_input.user_id,
                prefer_user=True,
            )

        if node_input.node_type == NODE_TYPE_CATEGORY and node_input.domain:
            return self.repository.get_node_by_path(
                taxonomy_path_for(domain=node_input.domain),
                user_id=node_input.user_id,
                prefer_user=True,
            )

        if node_input.node_type == NODE_TYPE_SUBCATEGORY and node_input.domain and node_input.category:
            return self.repository.get_node_by_path(
                taxonomy_path_for(domain=node_input.domain, category=node_input.category),
                user_id=node_input.user_id,
                prefer_user=True,
            )

        return None

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns service health snapshot."""
        repository_health = {}

        try:
            if hasattr(self.repository, "get_health") and callable(self.repository.get_health):
                repository_health = self.repository.get_health()
        except Exception as exc:
            repository_health = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        return {
            "schema_version": LIBRARY_TAXONOMY_USER_SERVICE_VERSION,
            "ok": True,
            "healthy": True,
            "service": type(self).__name__,
            "repository_health": normalize_json_mapping(repository_health),
            "supports_resolved_taxonomy": True,
            "supports_create_options": True,
            "supports_create_domain": True,
            "supports_create_category": True,
            "supports_create_subcategory": True,
            "supports_system_hide_override": True,
            "supports_system_rename_override": True,
            "supports_system_reorder_override": True,
            "supports_user_node_update": True,
            "supports_user_node_delete": True,
            "supports_audit": True,
        }

    def exception_result(self, exc: Exception, *, action: str) -> dict[str, Any]:
        """Maps exception to service result."""
        lowered = f"{type(exc).__name__} {exc}".lower()

        status = STATUS_FAILED

        if "notfound" in lowered or "not found" in lowered:
            status = STATUS_NOT_FOUND
        elif "invalid" in lowered or "required" in lowered or "validation" in lowered:
            status = STATUS_INVALID_REQUEST

        errors = getattr(exc, "errors", None)
        if errors:
            error_list = [str(error) for error in errors]
        else:
            error_list = [str(exc)]

        return TaxonomyServiceResult(
            ok=False,
            status=status,
            action=action,
            errors=error_list,
        ).to_dict()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_taxonomy_user_service(repository: Any | None = None) -> LibraryTaxonomyUserService:
    """Factory for dependency injection."""
    return LibraryTaxonomyUserService(repository=repository)


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return LIBRARY_TAXONOMY_USER_SERVICE_VERSION


def clear_library_taxonomy_user_service_caches() -> dict[str, Any]:
    """Clears service import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_repository_module,
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
    "LIBRARY_TAXONOMY_USER_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_USER",
    "NODE_TYPE_DOMAIN",
    "NODE_TYPE_CATEGORY",
    "NODE_TYPE_SUBCATEGORY",
    "ACTION_HIDE",
    "ACTION_RESTORE",
    "ACTION_RENAME",
    "ACTION_REORDER",
    "ACTION_MOVE",
    "ACTION_PATCH",
    "ACTION_DELETE",
    "STATUS_OK",
    "STATUS_INVALID_REQUEST",
    "STATUS_NOT_FOUND",
    "STATUS_FAILED",

    # Exceptions
    "LibraryTaxonomyUserServiceError",
    "LibraryTaxonomyUserServiceImportError",
    "LibraryTaxonomyUserServiceValidationError",
    "LibraryTaxonomyUserServiceNotFoundError",
    "LibraryTaxonomyUserServiceConflictError",

    # Dataclasses
    "TaxonomyContextQuery",
    "TaxonomyNodeInput",
    "TaxonomyActionInput",
    "TaxonomyServiceResult",

    # Service
    "LibraryTaxonomyUserService",
    "create_library_taxonomy_user_service",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_user_id",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "first_non_empty",
    "taxonomy_path_for",
    "infer_node_type",
    "node_is_system",
    "node_is_user",
    "to_dict_or_payload",
    "get_service_version",
    "clear_library_taxonomy_user_service_caches",
]