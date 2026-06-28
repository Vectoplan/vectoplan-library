# services/vectoplan-library/src/library/services/creative_library_service.py
"""
Service for VECTOPLAN Creative Library published state.

Diese Datei bildet die fachliche Service-Schicht über:

- src/library/repositories/creative_library_repository.py
- models/creative_library.py

Ziel:

    src/library/source/*
        -> scanner
        -> sync/publish bundle
        -> CreativeLibraryService
        -> CreativeLibraryRepository
        -> PostgreSQL published Creative Library
        -> API/UI read model

Aufgaben:

- veröffentlichte Creative Library lesen
- einzelne Items/Families lesen
- Items nach Taxonomie filtern
- Current Revision auflösen
- Revisionen/Varianten/Assets/Dokumente lesen
- Publish-/Sync-Bundles idempotent in DB übernehmen
- Scan-Runs und Scan-Issues verwalten
- Hotbar-/Inventory-Slots lesen und setzen
- API-fähige Payloads liefern

Architekturregeln:

- Service enthält keine Flask-Route.
- Service enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über CreativeLibraryRepository.
- Service erzeugt keine Tabellen.
- Service führt keine Migration aus.
- Service führt kein db.create_all() aus.
- Service öffnet keine aktive DB-Verbindung beim Import.
- `vplib_uid` wird aus Package/Manifest übernommen, nicht von der DB erzeugt.
- GET /scan darf diesen Service nur lesend/planend verwenden.
- POST /sync oder Publish darf diesen Service schreibend verwenden.
- Draft Working State liegt in creative_library_draft_service.py.
- User Collections/Overrides liegen in creative_library_user_service.py.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Hotbar-Slots bleiben 9.
"""

from __future__ import annotations

import importlib
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_SERVICE_VERSION: Final[str] = "vectoplan_library.service.creative_library.v1"

DEFAULT_USER_ID: Final[int] = 1
DEFAULT_HOTBAR_SLOT_COUNT: Final[int] = 9

STATUS_OK: Final[str] = "ok"
STATUS_FAILED: Final[str] = "failed"
STATUS_INVALID_REQUEST: Final[str] = "invalid_request"
STATUS_NOT_FOUND: Final[str] = "not_found"
STATUS_NOT_IMPLEMENTED: Final[str] = "not_implemented"

ITEM_STATUS_ACTIVE: Final[str] = "active"
ITEM_STATUS_DELETED: Final[str] = "deleted"
ITEM_STATUS_PUBLISHED: Final[str] = "published"

SOURCE_SCOPE_SYSTEM: Final[str] = "system"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"
SOURCE_SCOPE_USER: Final[str] = "user"

DEFAULT_LIMIT: Final[int] = 250
MAX_LIMIT: Final[int] = 5000

VPLIB_UID_FIELD: Final[str] = "vplib_uid"
VPLIB_UID_KEYS: Final[tuple[str, ...]] = (
    "vplib_uid",
    "vplibUid",
    "vplib_uid_v1",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreativeLibraryServiceError(RuntimeError):
    """Base error for CreativeLibraryService."""


class CreativeLibraryServiceImportError(CreativeLibraryServiceError):
    """Raised when dependencies cannot be imported."""


class CreativeLibraryServiceValidationError(CreativeLibraryServiceError):
    """Raised when service input is invalid."""

    def __init__(self, message: str, *, errors: Iterable[Any] | None = None) -> None:
        super().__init__(message)
        self.errors = [str(error) for error in (errors or [])]


class CreativeLibraryServiceNotFoundError(CreativeLibraryServiceError):
    """Raised when an entity cannot be found."""


class CreativeLibraryServiceConflictError(CreativeLibraryServiceError):
    """Raised when a requested operation conflicts with current state."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> ModuleType:
    """Loads creative_library_repository defensively."""
    errors: list[str] = []

    for module_name in (
        "library.repositories.creative_library_repository",
        "src.library.repositories.creative_library_repository",
        "vectoplan_library.library.repositories.creative_library_repository",
        "vectoplan_library.src.library.repositories.creative_library_repository",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryServiceImportError(
        "Could not import creative_library_repository. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_definition_catalog_service_module() -> ModuleType:
    """Loads optional definition catalog service."""
    errors: list[str] = []

    for module_name in (
        "library.services.library_definition_catalog_service",
        "src.library.services.library_definition_catalog_service",
        "vectoplan_library.library.services.library_definition_catalog_service",
        "vectoplan_library.src.library.services.library_definition_catalog_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryServiceImportError(
        "Could not import library_definition_catalog_service. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_file_service_module() -> ModuleType:
    """Loads optional file service."""
    errors: list[str] = []

    for module_name in (
        "library.services.library_file_service",
        "src.library.services.library_file_service",
        "vectoplan_library.library.services.library_file_service",
        "vectoplan_library.src.library.services.library_file_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryServiceImportError(
        "Could not import library_file_service. "
        + " | ".join(errors)
    )


def _repo_module() -> ModuleType:
    return _load_repository_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_string(value: Any, *, fallback: str = "") -> str:
    try:
        if value is None:
            return fallback
        text = str(value).replace("\x00", "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def optional_string(value: Any, *, max_length: int | None = None) -> str | None:
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
    return normalize_int(value, default=default, minimum=1)


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "published", "visible", "current"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "deleted", "hidden"}:
        return False

    return default


def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": normalize_json_value(value)}

    return {str(key): normalize_json_value(child_value) for key, child_value in value.items()}


def normalize_json_list(value: Iterable[Any] | None) -> list[Any]:
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


def to_dict_or_payload(value: Any, **kwargs: Any) -> dict[str, Any]:
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


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def compact_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: normalize_json_value(value)
        for key, value in normalize_json_mapping(payload).items()
        if value is not None
    }


def normalize_vplib_uid_safe(value: Any) -> str | None:
    if value is None:
        return None

    try:
        from vplib.vplib_id_service import normalize_vplib_uid

        uid = normalize_vplib_uid(value)
        if uid:
            return str(uid)
    except Exception:
        pass

    try:
        from src.vplib.vplib_id_service import normalize_vplib_uid  # type: ignore

        uid = normalize_vplib_uid(value)
        if uid:
            return str(uid)
    except Exception:
        pass

    try:
        parsed = uuid.UUID(str(value).strip())
        return str(parsed).lower()
    except Exception:
        return None


def extract_vplib_uid(value: Any, *, _depth: int = 0) -> str | None:
    if value is None or _depth > 6:
        return None

    direct = normalize_vplib_uid_safe(value)
    if direct:
        return direct

    if isinstance(value, Mapping):
        for key in VPLIB_UID_KEYS:
            if key in value:
                uid = normalize_vplib_uid_safe(value.get(key))
                if uid:
                    return uid

        if "vplib.manifest.json" in value:
            uid = extract_vplib_uid(value.get("vplib.manifest.json"), _depth=_depth + 1)
            if uid:
                return uid

        for nested_key in (
            "manifest",
            "manifest_payload",
            "vplib_manifest",
            "data",
            "payload",
            "draft",
            "publish",
            "document_bundle",
            "family_payload",
            "item",
            "revision",
        ):
            uid = extract_vplib_uid(value.get(nested_key), _depth=_depth + 1)
            if uid:
                return uid

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return extract_vplib_uid(value.to_dict(), _depth=_depth + 1)
        except Exception:
            pass

    return None


def extract_first_mapping(payload: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return normalize_json_mapping(value)
    return {}


def extract_first_list(payload: Mapping[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return normalize_json_list(value)
    return []


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class LibraryQuery:
    """Query object for published library reads."""

    user_id: int | None = None
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    object_kind: str | None = None
    status: str | None = None
    source_scope: str | None = None
    include_deleted: bool = False
    include_current_revision: bool = True
    include_revisions: bool = False
    include_variants: bool = False
    include_assets: bool = False
    include_documents: bool = False
    active_only: bool = True
    visible_only: bool = False
    limit: int = DEFAULT_LIMIT
    offset: int = 0

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "LibraryQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=None),
            domain=optional_string(data.get("domain")),
            category=optional_string(data.get("category")),
            subcategory=optional_string(data.get("subcategory")),
            object_kind=optional_string(data.get("object_kind")),
            status=optional_string(data.get("status")),
            source_scope=optional_string(data.get("source_scope")),
            include_deleted=normalize_bool(data.get("include_deleted"), default=False),
            include_current_revision=normalize_bool(data.get("include_current_revision"), default=True),
            include_revisions=normalize_bool(data.get("include_revisions"), default=False),
            include_variants=normalize_bool(data.get("include_variants"), default=False),
            include_assets=normalize_bool(data.get("include_assets"), default=False),
            include_documents=normalize_bool(data.get("include_documents"), default=False),
            active_only=normalize_bool(data.get("active_only"), default=True),
            visible_only=normalize_bool(data.get("visible_only"), default=False),
            limit=normalize_int(data.get("limit"), default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT) or DEFAULT_LIMIT,
            offset=normalize_int(data.get("offset"), default=0, minimum=0) or 0,
        )

    def to_item_query_payload(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "object_kind": self.object_kind,
            "status": self.status,
            "source_scope": self.source_scope,
            "include_deleted": self.include_deleted,
            "active_only": self.active_only,
            "visible_only": self.visible_only,
            "limit": self.limit,
            "offset": self.offset,
        }


@dataclass(slots=True)
class PublishOptions:
    """Options for publish/sync bundle writes."""

    user_id: int | None = DEFAULT_USER_ID
    source_scope: str = SOURCE_SCOPE_IMPORTED
    mark_current: bool = True
    replace_children: bool = False
    validate: bool = True
    commit: bool = True
    scan_run_ref: Any = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "PublishOptions":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID),
            source_scope=optional_string(data.get("source_scope")) or SOURCE_SCOPE_IMPORTED,
            mark_current=normalize_bool(data.get("mark_current"), default=True),
            replace_children=normalize_bool(data.get("replace_children"), default=False),
            validate=normalize_bool(data.get("validate"), default=True),
            commit=normalize_bool(data.get("commit"), default=True),
            scan_run_ref=first_non_empty(data.get("scan_run_ref"), data.get("scan_run_id"), data.get("scan_run_uid")),
        )


@dataclass(slots=True)
class CreativeLibraryServiceResult:
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
            "schema_version": CREATIVE_LIBRARY_SERVICE_VERSION,
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

class CreativeLibraryService:
    """
    High-level service for published Creative Library state.

    Args:
        repository:
            Optional CreativeLibraryRepository.
        definition_service:
            Optional Definition Catalog service.
        file_service:
            Optional Library File service.
    """

    def __init__(
        self,
        repository: Any | None = None,
        definition_service: Any | None = None,
        file_service: Any | None = None,
    ) -> None:
        self.repository = repository or self._create_repository()
        self.definition_service = definition_service or self._create_definition_service()
        self.file_service = file_service or self._create_file_service()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_repository(self) -> Any:
        module = _repo_module()
        factory = getattr(module, "create_creative_library_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(module, "CreativeLibraryRepository", None)
        if repo_class is None:
            raise CreativeLibraryServiceImportError("CreativeLibraryRepository class is not available.")

        return repo_class()

    def _create_definition_service(self) -> Any | None:
        try:
            module = _load_definition_catalog_service_module()
            factory = getattr(module, "create_library_definition_catalog_service", None)

            if callable(factory):
                return factory()

            service_class = getattr(module, "LibraryDefinitionCatalogService", None)
            if service_class is not None:
                return service_class()
        except Exception:
            return None

        return None

    def _create_file_service(self) -> Any | None:
        try:
            module = _load_file_service_module()
            factory = getattr(module, "create_library_file_service", None)

            if callable(factory):
                return factory()

            service_class = getattr(module, "LibraryFileService", None)
            if service_class is not None:
                return service_class()
        except Exception:
            return None

        return None

    # ------------------------------------------------------------------
    # Published read API
    # ------------------------------------------------------------------

    def get_library(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        object_kind: Any = None,
        status: Any = None,
        source_scope: Any = None,
        include_deleted: bool = False,
        include_current_revision: bool = True,
        include_revisions: bool = False,
        include_variants: bool = False,
        include_assets: bool = False,
        include_documents: bool = False,
        active_only: bool = True,
        visible_only: bool = False,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Returns published library payload."""
        try:
            query = LibraryQuery.from_payload(
                {
                    "user_id": user_id,
                    "domain": domain,
                    "category": category,
                    "subcategory": subcategory,
                    "object_kind": object_kind,
                    "status": status,
                    "source_scope": source_scope,
                    "include_deleted": include_deleted,
                    "include_current_revision": include_current_revision,
                    "include_revisions": include_revisions,
                    "include_variants": include_variants,
                    "include_assets": include_assets,
                    "include_documents": include_documents,
                    "active_only": active_only,
                    "visible_only": visible_only,
                    "limit": limit,
                    "offset": offset,
                }
            )

            payload = self.repository.get_library_payload(
                query=query.to_item_query_payload(),
                include_current_revision=query.include_current_revision,
                include_variants=query.include_variants,
                include_assets=query.include_assets,
                include_documents=query.include_documents,
            )

            if query.include_revisions:
                for item in payload.get("items", []):
                    item_id = item.get("id")
                    if item_id is not None:
                        item["revisions"] = self.repository.list_revisions(
                            query={"item_id": item_id, "include_deleted": query.include_deleted},
                            as_dict=True,
                        )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_library",
                payload={
                    "query": query.to_item_query_payload(),
                    **payload,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="get_library")

    def list_items(self, **kwargs: Any) -> dict[str, Any]:
        """Lists published items."""
        try:
            query = LibraryQuery.from_payload(kwargs)

            items = self.repository.list_item_payloads(
                query=query.to_item_query_payload(),
                include_current_revision=query.include_current_revision,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_items",
                payload={
                    "query": query.to_item_query_payload(),
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_items")

    def get_item(
        self,
        item_ref: Any,
        *,
        include_current_revision: bool = True,
        include_revisions: bool = False,
        include_variants: bool = True,
        include_assets: bool = True,
        include_documents: bool = True,
    ) -> dict[str, Any]:
        """Returns one published item."""
        try:
            payload = self.repository.get_item_payload(
                item_ref,
                include_current_revision=include_current_revision,
                include_revisions=include_revisions,
                include_variants=include_variants,
                include_assets=include_assets,
                include_documents=include_documents,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_item",
                payload={
                    "item": payload,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="get_item")

    def get_item_by_vplib_uid(self, vplib_uid: Any, **kwargs: Any) -> dict[str, Any]:
        """Returns one published item by vplib_uid."""
        item = self.repository.get_item_by_vplib_uid(vplib_uid)

        if item is None:
            return CreativeLibraryServiceResult(
                ok=False,
                status=STATUS_NOT_FOUND,
                action="get_item_by_vplib_uid",
                errors=[f"Item with vplib_uid {vplib_uid!r} was not found."],
            ).to_dict()

        return self.get_item(getattr(item, "id", None), **kwargs)

    def list_revisions(self, item_ref: Any | None = None, **kwargs: Any) -> dict[str, Any]:
        """Lists revisions."""
        try:
            query = dict(kwargs)

            if item_ref is not None:
                item = self.repository.require_item(item_ref)
                query["item_id"] = getattr(item, "id", None)

            items = self.repository.list_revisions(query=query, as_dict=True)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_revisions",
                payload={
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_revisions")

    def list_variants(self, **kwargs: Any) -> dict[str, Any]:
        """Lists variants."""
        try:
            items = self.repository.list_variants(query=kwargs, as_dict=True)
            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_variants",
                payload={"count": len(items), "items": items},
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="list_variants")

    def list_assets(self, **kwargs: Any) -> dict[str, Any]:
        """Lists assets."""
        try:
            items = self.repository.list_assets(query=kwargs, as_dict=True)
            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_assets",
                payload={"count": len(items), "items": items},
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="list_assets")

    def list_documents(self, **kwargs: Any) -> dict[str, Any]:
        """Lists documents."""
        try:
            items = self.repository.list_documents(query=kwargs, as_dict=True)
            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_documents",
                payload={"count": len(items), "items": items},
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="list_documents")

    # ------------------------------------------------------------------
    # Publish / sync API
    # ------------------------------------------------------------------

    def publish_bundle(
        self,
        publish_payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = SOURCE_SCOPE_IMPORTED,
        mark_current: bool = True,
        replace_children: bool = False,
        validate: bool = True,
        scan_run_ref: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Publishes a normalized bundle into published Creative Library tables.

        Expected payload shapes:
            - DraftService build_publish_bundle()
            - library_create_service build_publish_bundle_from_create_payload()
            - scanner sync package payload
        """
        options = PublishOptions.from_payload(
            {
                "user_id": user_id,
                "source_scope": source_scope,
                "mark_current": mark_current,
                "replace_children": replace_children,
                "validate": validate,
                "scan_run_ref": scan_run_ref,
                "commit": commit,
            }
        )

        data = normalize_json_mapping(publish_payload)

        try:
            if options.validate:
                self.validate_publish_payload_or_raise(data)

            item_payload = self.build_item_payload_from_publish_payload(data, source_scope=options.source_scope)
            item, item_created = self.repository.upsert_item(item_payload, commit=False)

            revision_payload = self.build_revision_payload_from_publish_payload(data, item=item, scan_run_ref=options.scan_run_ref)
            revision = self.repository.create_revision(
                getattr(item, "id", None),
                revision_payload,
                mark_current=options.mark_current,
                commit=False,
            )

            child_payload = self.publish_children(
                data,
                item=item,
                revision=revision,
                replace_existing=options.replace_children,
                commit=False,
            )

            if options.commit:
                self.repository.commit()
            else:
                self.repository.flush()

            item_result = self.repository.get_item_payload(
                getattr(item, "id", None),
                include_current_revision=True,
                include_revisions=False,
                include_variants=True,
                include_assets=True,
                include_documents=True,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="publish_bundle",
                payload={
                    "created": item_created,
                    "updated": not item_created,
                    "item": item_result,
                    "revision": to_dict_or_payload(revision),
                    "children": child_payload,
                    "vplib_uid": extract_vplib_uid(data),
                },
            ).to_dict()

        except Exception as exc:
            if options.commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="publish_bundle")

    def publish_document_bundle(self, publish_payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Alias for publish adapters."""
        return self.publish_bundle(publish_payload, **kwargs)

    def publish_from_draft(self, publish_payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Alias for DraftService publish adapter detection."""
        return self.publish_bundle(publish_payload, source_scope=SOURCE_SCOPE_GENERATED, **kwargs)

    def publish_draft(
        self,
        *,
        draft_ref: Any = None,
        publish_payload: Mapping[str, Any] | None = None,
        user_id: Any = DEFAULT_USER_ID,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Adapter-compatible publish_draft signature."""
        payload = normalize_json_mapping(publish_payload)
        if draft_ref is not None:
            payload.setdefault("source_draft_ref", draft_ref)
        return self.publish_bundle(payload, user_id=user_id, source_scope=SOURCE_SCOPE_GENERATED, **kwargs)

    def publish(self, publish_payload: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
        """Generic publish alias."""
        return self.publish_bundle(publish_payload, **kwargs)

    def sync_package_payload(
        self,
        package_payload: Mapping[str, Any],
        *,
        scan_run_ref: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Sync alias used by scanner/sync services."""
        return self.publish_bundle(
            package_payload,
            source_scope=SOURCE_SCOPE_IMPORTED,
            scan_run_ref=scan_run_ref,
            commit=commit,
        )

    def validate_publish_payload_or_raise(self, publish_payload: Mapping[str, Any]) -> None:
        """Validates minimum required publish payload."""
        data = normalize_json_mapping(publish_payload)
        errors: list[str] = []

        uid = extract_vplib_uid(data)
        if not uid:
            errors.append("publish payload requires valid vplib_uid")

        family_id = first_non_empty(
            data.get("family_id"),
            extract_first_mapping(data, "manifest_payload", "manifest").get("family_id"),
            extract_first_mapping(data, "family_payload", "family").get("family_id"),
        )
        if not family_id:
            errors.append("publish payload requires family_id")

        package_id = first_non_empty(
            data.get("package_id"),
            extract_first_mapping(data, "manifest_payload", "manifest").get("package_id"),
        )
        if not package_id:
            errors.append("publish payload requires package_id")

        if errors:
            raise CreativeLibraryServiceValidationError("Invalid publish payload.", errors=errors)

    def build_item_payload_from_publish_payload(self, publish_payload: Mapping[str, Any], *, source_scope: Any = SOURCE_SCOPE_IMPORTED) -> dict[str, Any]:
        """Builds repository item payload from publish bundle."""
        data = normalize_json_mapping(publish_payload)

        manifest = extract_first_mapping(data, "manifest_payload", "manifest")
        family = extract_first_mapping(data, "family_payload", "family")
        classification = extract_first_mapping(data, "classification_payload", "classification")

        uid = extract_vplib_uid(data)

        return compact_payload(
            {
                "vplib_uid": uid,
                "family_id": first_non_empty(data.get("family_id"), manifest.get("family_id"), family.get("family_id")),
                "package_id": first_non_empty(data.get("package_id"), manifest.get("package_id")),
                "source_scope": source_scope,
                "source_path": first_non_empty(data.get("source_path"), manifest.get("source_path"), classification.get("source_path")),
                "classification_path": first_non_empty(data.get("classification_path"), manifest.get("classification_path"), classification.get("classification_path")),
                "domain": first_non_empty(data.get("domain"), manifest.get("domain"), classification.get("domain")),
                "category": first_non_empty(data.get("category"), manifest.get("category"), classification.get("category")),
                "subcategory": first_non_empty(data.get("subcategory"), manifest.get("subcategory"), classification.get("subcategory")),
                "object_kind": first_non_empty(data.get("object_kind"), manifest.get("object_kind"), classification.get("object_kind")),
                "label": first_non_empty(data.get("title"), data.get("label"), data.get("name"), manifest.get("family_name"), family.get("label"), family.get("name")),
                "name": first_non_empty(data.get("name"), data.get("title"), data.get("label"), manifest.get("family_name"), family.get("label")),
                "title": first_non_empty(data.get("title"), data.get("label"), data.get("name"), family.get("label")),
                "description": first_non_empty(data.get("description"), family.get("description")),
                "status": ITEM_STATUS_PUBLISHED,
                "active": True,
                "visible": True,
                "manifest_payload": manifest,
                "classification_payload": classification,
                "payload": data,
                "metadata": {
                    "published_by": CREATIVE_LIBRARY_SERVICE_VERSION,
                    "source": data.get("source"),
                    "source_draft_ref": data.get("source_draft_ref"),
                    "draft_id": data.get("draft_id"),
                    "draft_uid": data.get("draft_uid"),
                },
            }
        )

    def build_revision_payload_from_publish_payload(self, publish_payload: Mapping[str, Any], *, item: Any, scan_run_ref: Any = None) -> dict[str, Any]:
        """Builds repository revision payload from publish bundle."""
        data = normalize_json_mapping(publish_payload)

        manifest = extract_first_mapping(data, "manifest_payload", "manifest")
        modules = extract_first_mapping(data, "modules_payload", "modules")
        family = extract_first_mapping(data, "family_payload", "family")
        classification = extract_first_mapping(data, "classification_payload", "classification")
        generator = extract_first_mapping(data, "generator_payload", "generator")

        scan_run_id = None
        if scan_run_ref is not None:
            scan_run = self.repository.get_scan_run(scan_run_ref)
            scan_run_id = getattr(scan_run, "id", None) if scan_run is not None else None

        return compact_payload(
            {
                "version": first_non_empty(data.get("version"), data.get("package_version"), manifest.get("package_version")),
                "revision_number": data.get("revision_number"),
                "source_path": first_non_empty(data.get("source_path"), manifest.get("source_path"), getattr(item, "source_path", None)),
                "scan_run_id": scan_run_id,
                "manifest_payload": manifest,
                "modules_payload": modules,
                "family_payload": family,
                "classification_payload": classification,
                "document_bundle": extract_first_mapping(data, "document_bundle"),
                "generator_payload": generator,
                "payload": data,
                "metadata": {
                    "source": data.get("source"),
                    "draft_id": data.get("draft_id"),
                    "draft_uid": data.get("draft_uid"),
                    "source_draft_ref": data.get("source_draft_ref"),
                },
                "active": True,
            }
        )

    def publish_children(
        self,
        publish_payload: Mapping[str, Any],
        *,
        item: Any,
        revision: Any,
        replace_existing: bool = False,
        commit: bool = False,
    ) -> dict[str, Any]:
        """Creates variants/assets/documents for a published revision."""
        data = normalize_json_mapping(publish_payload)

        item_ref = getattr(item, "id", None)
        revision_ref = getattr(revision, "id", None)

        variant_payloads = self.extract_variant_payloads(data)
        asset_payloads = self.extract_asset_payloads(data)
        document_payloads = self.extract_document_payloads(data)

        created_variants = []
        created_assets = []
        created_documents = []

        # replace_existing is intentionally conservative. Full child deletion can
        # be added later when DB constraints are final. For now new revision_id
        # naturally scopes children to the published revision.
        _replace_existing_ignored = replace_existing

        for variant_payload in variant_payloads:
            variant, _created = self.repository.upsert_variant(
                variant_payload,
                item_ref=item_ref,
                revision_ref=revision_ref,
                commit=False,
            )
            created_variants.append(to_dict_or_payload(variant))

        for asset_payload in asset_payloads:
            variant_ref = first_non_empty(asset_payload.get("variant_ref"), asset_payload.get("variant_uid"), asset_payload.get("variant_id_db"))
            asset = self.repository.create_asset(
                asset_payload,
                item_ref=item_ref,
                revision_ref=revision_ref,
                variant_ref=variant_ref,
                commit=False,
            )
            created_assets.append(to_dict_or_payload(asset))

        for document_payload in document_payloads:
            variant_ref = first_non_empty(document_payload.get("variant_ref"), document_payload.get("variant_uid"), document_payload.get("variant_id_db"))
            document = self.repository.create_document(
                document_payload,
                item_ref=item_ref,
                revision_ref=revision_ref,
                variant_ref=variant_ref,
                commit=False,
            )
            created_documents.append(to_dict_or_payload(document))

        if commit:
            self.repository.commit()
        else:
            self.repository.flush()

        return {
            "variants": created_variants,
            "assets": created_assets,
            "documents": created_documents,
            "counts": {
                "variant_count": len(created_variants),
                "asset_count": len(created_assets),
                "document_count": len(created_documents),
            },
        }

    def extract_variant_payloads(self, publish_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Extracts normalized variant payloads."""
        data = normalize_json_mapping(publish_payload)
        raw_variants = extract_first_list(data, "variants", "variant_payloads")

        result: list[dict[str, Any]] = []

        for index, raw in enumerate(raw_variants):
            if not isinstance(raw, Mapping):
                continue

            item = normalize_json_mapping(raw)
            variant_id = first_non_empty(item.get("variant_id"), item.get("variant_key"), item.get("key"), "default" if index == 0 else f"variant_{index + 1}")

            result.append(
                compact_payload(
                    {
                        "variant_id": variant_id,
                        "variant_key": item.get("variant_key") or variant_id,
                        "label": first_non_empty(item.get("label"), item.get("name"), variant_id),
                        "description": item.get("description"),
                        "status": item.get("status") or ITEM_STATUS_ACTIVE,
                        "sort_order": first_non_empty(item.get("sort_order"), index),
                        "definition_values": first_non_empty(item.get("definition_values_json"), item.get("definition_values"), item.get("overrides")),
                        "summary": first_non_empty(item.get("summary_json"), item.get("summary")),
                        "payload": item,
                        "metadata": item.get("metadata") or item.get("metadata_json"),
                        "active": item.get("active", True),
                        "visible": item.get("visible", True),
                    }
                )
            )

        if not result:
            result.append(
                {
                    "variant_id": "default",
                    "variant_key": "default",
                    "label": "Default",
                    "status": ITEM_STATUS_ACTIVE,
                    "sort_order": 0,
                    "definition_values": {},
                    "summary": {},
                    "payload": {"source": "generated_default"},
                    "active": True,
                    "visible": True,
                }
            )

        return result

    def extract_asset_payloads(self, publish_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Extracts normalized asset payloads."""
        data = normalize_json_mapping(publish_payload)
        raw_assets = extract_first_list(data, "assets", "asset_payloads")

        result: list[dict[str, Any]] = []

        for index, raw in enumerate(raw_assets):
            if not isinstance(raw, Mapping):
                continue

            item = normalize_json_mapping(raw)
            result.append(
                compact_payload(
                    {
                        "asset_kind": item.get("asset_kind") or item.get("kind"),
                        "role": item.get("role"),
                        "variant_ref": first_non_empty(item.get("variant_ref"), item.get("variant_uid"), item.get("variant_id_db")),
                        "library_file_id": item.get("library_file_id"),
                        "file_version_id": item.get("file_version_id"),
                        "file_uid": item.get("file_uid"),
                        "source_path": item.get("source_path"),
                        "storage_path": item.get("storage_path"),
                        "filename": first_non_empty(item.get("filename"), item.get("original_filename")),
                        "mime_type": first_non_empty(item.get("mime_type"), item.get("content_type")),
                        "size_bytes": item.get("size_bytes"),
                        "sha256": item.get("sha256"),
                        "sort_order": first_non_empty(item.get("sort_order"), index),
                        "status": item.get("status") or ITEM_STATUS_ACTIVE,
                        "payload": item,
                        "metadata": item.get("metadata") or item.get("metadata_json"),
                        "active": item.get("active", True),
                        "visible": item.get("visible", True),
                    }
                )
            )

        return result

    def extract_document_payloads(self, publish_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Extracts normalized document payloads."""
        data = normalize_json_mapping(publish_payload)
        raw_documents = extract_first_list(data, "documents", "document_payloads")

        # Also convert document_bundle flat documents into document rows.
        document_bundle = extract_first_mapping(data, "document_bundle")
        if document_bundle:
            for key, value in document_bundle.items():
                if key in {"manifest", "family", "classification", "modules", "variants", "assets", "documents", "generator"}:
                    continue
                raw_documents.append(
                    {
                        "document_type": "bundle_document",
                        "field_key": key,
                        "title": key,
                        "payload": {
                            "content": value,
                            "source": "document_bundle",
                        },
                    }
                )

        result: list[dict[str, Any]] = []

        for index, raw in enumerate(raw_documents):
            if not isinstance(raw, Mapping):
                continue

            item = normalize_json_mapping(raw)
            result.append(
                compact_payload(
                    {
                        "document_kind": item.get("document_kind") or item.get("kind"),
                        "document_type": item.get("document_type") or item.get("type"),
                        "field_key": item.get("field_key") or item.get("key"),
                        "title": first_non_empty(item.get("title"), item.get("label"), item.get("field_key")),
                        "variant_ref": first_non_empty(item.get("variant_ref"), item.get("variant_uid"), item.get("variant_id_db")),
                        "library_file_id": item.get("library_file_id"),
                        "file_version_id": item.get("file_version_id"),
                        "file_uid": item.get("file_uid"),
                        "storage_path": item.get("storage_path"),
                        "url": item.get("url"),
                        "sort_order": first_non_empty(item.get("sort_order"), index),
                        "status": item.get("status") or ITEM_STATUS_ACTIVE,
                        "payload": item.get("payload") if isinstance(item.get("payload"), Mapping) else item,
                        "metadata": item.get("metadata") or item.get("metadata_json"),
                        "active": item.get("active", True),
                        "visible": item.get("visible", True),
                    }
                )
            )

        return result

    # ------------------------------------------------------------------
    # Direct write pass-throughs
    # ------------------------------------------------------------------

    def upsert_item(self, payload: Mapping[str, Any], *, commit: bool = True) -> dict[str, Any]:
        """Upserts item only."""
        try:
            item, created = self.repository.upsert_item(payload, commit=commit)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="upsert_item",
                payload={
                    "created": created,
                    "updated": not created,
                    "item": to_dict_or_payload(item),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="upsert_item")

    def create_revision(self, item_ref: Any, payload: Mapping[str, Any], *, mark_current: bool = True, commit: bool = True) -> dict[str, Any]:
        """Creates revision for item."""
        try:
            revision = self.repository.create_revision(
                item_ref,
                payload,
                mark_current=mark_current,
                commit=commit,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="create_revision",
                payload={
                    "revision": to_dict_or_payload(revision),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="create_revision")

    def set_current_revision(self, revision_ref: Any, *, commit: bool = True) -> dict[str, Any]:
        """Marks a revision as current."""
        try:
            revision = self.repository.set_current_revision(revision_ref, commit=commit)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="set_current_revision",
                payload={
                    "revision": to_dict_or_payload(revision),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="set_current_revision")

    def delete_item(self, item_ref: Any, *, commit: bool = True) -> dict[str, Any]:
        """Soft-deletes published item."""
        try:
            deleted = self.repository.soft_delete_item(item_ref, commit=commit)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_item",
                payload={
                    "deleted": deleted,
                    "item_ref": item_ref,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="delete_item")

    # ------------------------------------------------------------------
    # Scan helpers
    # ------------------------------------------------------------------

    def start_scan_run(self, payload: Mapping[str, Any] | None = None, *, commit: bool = True) -> dict[str, Any]:
        """Starts a scan run record."""
        try:
            scan_run = self.repository.start_scan_run(payload, commit=commit)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="start_scan_run",
                payload={
                    "scan_run": to_dict_or_payload(scan_run),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="start_scan_run")

    def finish_scan_run(
        self,
        scan_run_ref: Any,
        *,
        status: Any = "completed",
        counters: Mapping[str, Any] | None = None,
        errors: Iterable[Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Finishes scan run record."""
        try:
            scan_run = self.repository.finish_scan_run(
                scan_run_ref,
                status=status,
                counters=counters,
                errors=errors,
                commit=commit,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="finish_scan_run",
                payload={
                    "scan_run": to_dict_or_payload(scan_run),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="finish_scan_run")

    def record_scan_issue(self, scan_run_ref: Any, payload: Mapping[str, Any], *, commit: bool = True) -> dict[str, Any]:
        """Records scan issue."""
        try:
            issue = self.repository.record_scan_issue(scan_run_ref, payload, commit=commit)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="record_scan_issue",
                payload={
                    "issue": to_dict_or_payload(issue),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="record_scan_issue")

    def list_scan_runs(self, **kwargs: Any) -> dict[str, Any]:
        """Lists scan runs."""
        try:
            items = self.repository.list_scan_runs(query=kwargs, as_dict=True)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_scan_runs",
                payload={
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_scan_runs")

    def list_scan_issues(self, scan_run_ref: Any | None = None, **kwargs: Any) -> dict[str, Any]:
        """Lists scan issues."""
        try:
            items = self.repository.list_scan_issues(scan_run_ref, **kwargs)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_scan_issues",
                payload={
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_scan_issues")

    # ------------------------------------------------------------------
    # Inventory slots
    # ------------------------------------------------------------------

    def list_inventory_slots(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        """Lists published-library inventory slots."""
        try:
            items = self.repository.list_inventory_slots(user_id=user_id, as_dict=True)

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_inventory_slots",
                payload={
                    "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
                    "slot_count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_inventory_slots")

    def set_inventory_slot(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        slot_index: Any,
        item_ref: Any = None,
        variant_ref: Any = None,
        payload: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Sets one inventory/hotbar slot."""
        try:
            slot = self.repository.set_inventory_slot(
                user_id=user_id,
                slot_index=slot_index,
                item_ref=item_ref,
                variant_ref=variant_ref,
                payload=payload,
                commit=commit,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="set_inventory_slot",
                payload={
                    "slot": to_dict_or_payload(slot),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="set_inventory_slot")

    def clear_inventory_slot(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        slot_index: Any,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Clears one inventory/hotbar slot."""
        try:
            cleared = self.repository.clear_inventory_slot(
                user_id=user_id,
                slot_index=slot_index,
                commit=commit,
            )

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="clear_inventory_slot",
                payload={
                    "cleared": cleared,
                    "slot_index": slot_index,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="clear_inventory_slot")

    # ------------------------------------------------------------------
    # Options / diagnostics
    # ------------------------------------------------------------------

    def get_create_options(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        """Returns definition-backed create options when available."""
        if self.definition_service is None:
            return CreativeLibraryServiceResult(
                ok=False,
                status=STATUS_NOT_IMPLEMENTED,
                action="get_create_options",
                errors=["Definition catalog service is not available."],
            ).to_dict()

        try:
            method = getattr(self.definition_service, "get_create_options", None)
            if not callable(method):
                raise RuntimeError("Definition service has no get_create_options method.")

            result = self._call_service_method(method, {"user_id": user_id})

            return CreativeLibraryServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_create_options",
                payload={
                    "options": normalize_json_value(result),
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="get_create_options")

    def get_health(self) -> dict[str, Any]:
        """Returns service health snapshot."""
        repository_health = {}

        try:
            if hasattr(self.repository, "get_health") and callable(self.repository.get_health):
                repository_health = self.repository.get_health()
        except Exception as exc:
            repository_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        definition_health = {}
        try:
            if self.definition_service is not None and hasattr(self.definition_service, "get_health"):
                definition_health = self.definition_service.get_health()
        except Exception as exc:
            definition_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        file_health = {}
        try:
            if self.file_service is not None and hasattr(self.file_service, "get_health"):
                file_health = self.file_service.get_health()
        except Exception as exc:
            file_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": CREATIVE_LIBRARY_SERVICE_VERSION,
            "ok": True,
            "healthy": True,
            "service": type(self).__name__,
            "repository_health": normalize_json_mapping(repository_health),
            "definition_service_available": self.definition_service is not None,
            "definition_service_health": normalize_json_mapping(definition_health),
            "file_service_available": self.file_service is not None,
            "file_service_health": normalize_json_mapping(file_health),
            "supports_get_library": True,
            "supports_get_item": True,
            "supports_publish_bundle": True,
            "supports_sync_package_payload": True,
            "supports_revisions": True,
            "supports_variants": True,
            "supports_assets": True,
            "supports_documents": True,
            "supports_scan_runs": True,
            "supports_scan_issues": True,
            "supports_inventory_slots": True,
            "vplib_uid_created_by_database": False,
        }

    def exception_result(self, exc: Exception, *, action: str) -> dict[str, Any]:
        """Maps exception to service result."""
        lowered = f"{type(exc).__name__} {exc}".lower()

        status = STATUS_FAILED

        if "notfound" in lowered or "not found" in lowered:
            status = STATUS_NOT_FOUND
        elif "invalid" in lowered or "required" in lowered or "validation" in lowered:
            status = STATUS_INVALID_REQUEST
        elif "not implemented" in lowered or "not available" in lowered:
            status = STATUS_NOT_IMPLEMENTED

        errors = getattr(exc, "errors", None)
        if errors:
            error_list = [str(error) for error in errors]
        else:
            error_list = [str(exc)]

        return CreativeLibraryServiceResult(
            ok=False,
            status=status,
            action=action,
            errors=error_list,
        ).to_dict()

    # ------------------------------------------------------------------
    # Internal service helper
    # ------------------------------------------------------------------

    def _call_service_method(self, method: Callable[..., Any], kwargs: Mapping[str, Any]) -> Any:
        cleaned = {
            key: value
            for key, value in kwargs.items()
            if value is not None
        }

        try:
            return method(**cleaned)
        except TypeError:
            try:
                return method(cleaned)
            except TypeError:
                return method()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_creative_library_service(
    repository: Any | None = None,
    definition_service: Any | None = None,
    file_service: Any | None = None,
) -> CreativeLibraryService:
    """Factory for dependency injection."""
    return CreativeLibraryService(
        repository=repository,
        definition_service=definition_service,
        file_service=file_service,
    )


@lru_cache(maxsize=1)
def get_service_version() -> str:
    return CREATIVE_LIBRARY_SERVICE_VERSION


def clear_creative_library_service_caches() -> dict[str, Any]:
    """Clears service import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_repository_module,
        _load_definition_catalog_service_module,
        _load_file_service_module,
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


# Compatibility aliases.
LibraryService = CreativeLibraryService
PublishedLibraryService = CreativeLibraryService
create_library_service = create_creative_library_service
create_published_library_service = create_creative_library_service


__all__ = [
    "CREATIVE_LIBRARY_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_HOTBAR_SLOT_COUNT",
    "STATUS_OK",
    "STATUS_FAILED",
    "STATUS_INVALID_REQUEST",
    "STATUS_NOT_FOUND",
    "STATUS_NOT_IMPLEMENTED",
    "ITEM_STATUS_ACTIVE",
    "ITEM_STATUS_DELETED",
    "ITEM_STATUS_PUBLISHED",
    "SOURCE_SCOPE_SYSTEM",
    "SOURCE_SCOPE_IMPORTED",
    "SOURCE_SCOPE_GENERATED",
    "SOURCE_SCOPE_USER",
    "VPLIB_UID_FIELD",
    "VPLIB_UID_KEYS",

    # Exceptions
    "CreativeLibraryServiceError",
    "CreativeLibraryServiceImportError",
    "CreativeLibraryServiceValidationError",
    "CreativeLibraryServiceNotFoundError",
    "CreativeLibraryServiceConflictError",

    # Dataclasses
    "LibraryQuery",
    "PublishOptions",
    "CreativeLibraryServiceResult",

    # Service
    "CreativeLibraryService",
    "LibraryService",
    "PublishedLibraryService",
    "create_creative_library_service",
    "create_library_service",
    "create_published_library_service",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_user_id",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "to_dict_or_payload",
    "first_non_empty",
    "compact_payload",
    "normalize_vplib_uid_safe",
    "extract_vplib_uid",
    "extract_first_mapping",
    "extract_first_list",
    "get_service_version",
    "clear_creative_library_service_caches",
]