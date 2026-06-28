# services/vectoplan-library/src/library/services/creative_library_draft_service.py
"""
Service for VECTOPLAN Creative Library Drafts.

Diese Datei bildet die fachliche Service-Schicht über:

- src/library/repositories/creative_library_draft_repository.py
- models/creative_library_drafts.py

Ziel:

    Generator / Create Flow / Edit Flow
        -> CreativeLibraryDraftService
        -> CreativeLibraryDraftRepository
        -> Draft speichern
        -> Draft validieren
        -> Publish Bundle vorbereiten
        -> optional Publish Adapter aufrufen
        -> CreativeLibraryRevision / Variant / Asset / Document

Aufgaben:

- Drafts erstellen
- Drafts lesen/listen
- Drafts aktualisieren
- Draft-Variants verwalten
- Draft-Assets verwalten
- Draft-Documents verwalten
- Validation Issues speichern
- Draft validieren
- Publish Payload / DocumentBundle vorbereiten
- Draft publishen, wenn ein Publisher-Service vorhanden ist
- Draft verwerfen/löschen
- Audit Events auslesen
- API-fähige Payloads liefern

Architekturregeln:

- Service enthält keine Flask-Route.
- Service enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über CreativeLibraryDraftRepository.
- Datei-Uploads laufen über LibraryFileService, wenn vorhanden.
- Definitionen/Create Context laufen über LibraryDefinitionCatalogService, wenn vorhanden.
- Published-Revisions werden nur über optionalen Publish Adapter erzeugt.
- Ohne Publish Adapter wird nur ein Publish-Plan zurückgegeben bzw. publish als
  not_implemented beantwortet.
- Service erzeugt keine Tabellen.
- Service führt keine Migration aus.
- Service führt kein db.create_all() aus.
- Service öffnet keine aktive DB-Verbindung beim Import.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- owner_user_id=1 bei User-Drafts.
- owner_scope="user:1".
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION: Final[str] = "vectoplan_library.service.creative_library_draft.v1"

DEFAULT_USER_ID: Final[int] = 1

SOURCE_SCOPE_USER: Final[str] = "user"
SOURCE_SCOPE_GENERATED: Final[str] = "generated"
SOURCE_SCOPE_IMPORTED: Final[str] = "imported"

DRAFT_MODE_CREATE: Final[str] = "create"
DRAFT_MODE_UPDATE: Final[str] = "update"
DRAFT_MODE_IMPORT: Final[str] = "import"
DRAFT_MODE_GENERATE: Final[str] = "generate"

DRAFT_STATUS_DRAFT: Final[str] = "draft"
DRAFT_STATUS_VALIDATING: Final[str] = "validating"
DRAFT_STATUS_VALID: Final[str] = "valid"
DRAFT_STATUS_INVALID: Final[str] = "invalid"
DRAFT_STATUS_PUBLISHED: Final[str] = "published"
DRAFT_STATUS_DISCARDED: Final[str] = "discarded"
DRAFT_STATUS_DELETED: Final[str] = "deleted"

ISSUE_SEVERITY_INFO: Final[str] = "info"
ISSUE_SEVERITY_WARNING: Final[str] = "warning"
ISSUE_SEVERITY_ERROR: Final[str] = "error"
ISSUE_SEVERITY_BLOCKING: Final[str] = "blocking"

STATUS_OK: Final[str] = "ok"
STATUS_INVALID_REQUEST: Final[str] = "invalid_request"
STATUS_NOT_FOUND: Final[str] = "not_found"
STATUS_FAILED: Final[str] = "failed"
STATUS_NOT_IMPLEMENTED: Final[str] = "not_implemented"

DEFAULT_LIMIT: Final[int] = 100
MAX_LIMIT: Final[int] = 1000


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreativeLibraryDraftServiceError(RuntimeError):
    """Base error for CreativeLibraryDraftService."""


class CreativeLibraryDraftServiceImportError(CreativeLibraryDraftServiceError):
    """Raised when service dependencies cannot be imported."""


class CreativeLibraryDraftServiceValidationError(CreativeLibraryDraftServiceError):
    """Raised when service input or draft validation fails."""

    def __init__(self, message: str, *, errors: Iterable[Any] | None = None) -> None:
        super().__init__(message)
        self.errors = [str(error) for error in (errors or [])]


class CreativeLibraryDraftServiceNotFoundError(CreativeLibraryDraftServiceError):
    """Raised when a requested draft entity cannot be found."""


class CreativeLibraryDraftServiceConflictError(CreativeLibraryDraftServiceError):
    """Raised when a draft operation conflicts with current state."""


class CreativeLibraryDraftPublishNotAvailableError(CreativeLibraryDraftServiceError):
    """Raised when publishing is requested but no publisher adapter is available."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> ModuleType:
    """Loads creative_library_draft_repository defensively."""
    errors: list[str] = []

    for module_name in (
        "library.repositories.creative_library_draft_repository",
        "src.library.repositories.creative_library_draft_repository",
        "vectoplan_library.library.repositories.creative_library_draft_repository",
        "vectoplan_library.src.library.repositories.creative_library_draft_repository",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryDraftServiceImportError(
        "Could not import creative_library_draft_repository. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_definition_service_module() -> ModuleType:
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

    raise CreativeLibraryDraftServiceImportError(
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

    raise CreativeLibraryDraftServiceImportError(
        "Could not import library_file_service. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_publish_service_module() -> ModuleType:
    """
    Loads optional publish adapter service.

    This is intentionally tolerant because the concrete published service name
    may differ between project revisions.
    """
    errors: list[str] = []

    for module_name in (
        "library.services.creative_library_publish_service",
        "src.library.services.creative_library_publish_service",
        "library.services.library_published_service",
        "src.library.services.library_published_service",
        "library.services.library_db_sync_service",
        "src.library.services.library_db_sync_service",
        "vectoplan_library.library.services.creative_library_publish_service",
        "vectoplan_library.src.library.services.creative_library_publish_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise CreativeLibraryDraftServiceImportError(
        "Could not import a Creative Library publish adapter. "
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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "valid", "publish"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "invalid"}:
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


def issue_is_blocking(issue: Mapping[str, Any] | Any) -> bool:
    """Checks whether validation issue is blocking."""
    helper = getattr(_repo_module(), "issue_is_blocking", None)

    if callable(helper):
        try:
            return bool(helper(issue))
        except Exception:
            pass

    if isinstance(issue, Mapping):
        payload = normalize_json_mapping(issue)
        severity = clean_string(payload.get("severity")).lower()
        return normalize_bool(payload.get("blocking"), default=False) or severity in {
            ISSUE_SEVERITY_ERROR,
            ISSUE_SEVERITY_BLOCKING,
        }

    severity = clean_string(getattr(issue, "severity", "")).lower()
    return normalize_bool(getattr(issue, "blocking", None), default=False) or severity in {
        ISSUE_SEVERITY_ERROR,
        ISSUE_SEVERITY_BLOCKING,
    }


def payload_has_any(payload: Mapping[str, Any], *keys: str) -> bool:
    """Checks whether payload has any non-empty key."""
    data = normalize_json_mapping(payload)

    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return True

    return False


def compact_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    """Removes None values at top level."""
    return {
        key: normalize_json_value(child)
        for key, child in normalize_json_mapping(value).items()
        if child is not None
    }


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DraftInput:
    """Normalized draft creation/update input."""

    user_id: int = DEFAULT_USER_ID
    mode: str = DRAFT_MODE_CREATE
    source_scope: str = SOURCE_SCOPE_USER
    target_item_id: int | None = None
    target_vplib_uid: str | None = None
    base_revision_id: int | None = None
    published_revision_id: int | None = None
    family_id: str | None = None
    package_id: str | None = None
    vplib_uid: str | None = None
    title: str | None = None
    label: str | None = None
    name: str | None = None
    description: str | None = None
    family_payload: dict[str, Any] = field(default_factory=dict)
    classification_payload: dict[str, Any] = field(default_factory=dict)
    manifest_payload: dict[str, Any] = field(default_factory=dict)
    modules_payload: dict[str, Any] = field(default_factory=dict)
    generator_payload: dict[str, Any] = field(default_factory=dict)
    validation_payload: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    variants: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    validation_issues: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "DraftInput":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        title = optional_string(first_non_empty(data.get("title"), data.get("label"), data.get("name")))

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID) or DEFAULT_USER_ID,
            mode=clean_string(data.get("mode"), fallback=DRAFT_MODE_CREATE),
            source_scope=clean_string(data.get("source_scope"), fallback=SOURCE_SCOPE_USER),
            target_item_id=normalize_int(data.get("target_item_id"), default=None, minimum=1),
            target_vplib_uid=optional_string(data.get("target_vplib_uid") or data.get("vplib_uid")),
            base_revision_id=normalize_int(data.get("base_revision_id"), default=None, minimum=1),
            published_revision_id=normalize_int(data.get("published_revision_id"), default=None, minimum=1),
            family_id=optional_string(data.get("family_id")),
            package_id=optional_string(data.get("package_id")),
            vplib_uid=optional_string(data.get("vplib_uid") or data.get("target_vplib_uid")),
            title=title,
            label=optional_string(data.get("label") or title),
            name=optional_string(data.get("name") or title),
            description=optional_string(data.get("description")),
            family_payload=normalize_json_mapping(data.get("family_payload") or data.get("family")),
            classification_payload=normalize_json_mapping(data.get("classification_payload") or data.get("classification")),
            manifest_payload=normalize_json_mapping(data.get("manifest_payload") or data.get("manifest")),
            modules_payload=normalize_json_mapping(data.get("modules_payload") or data.get("modules")),
            generator_payload=normalize_json_mapping(data.get("generator_payload") or data.get("generator")),
            validation_payload=normalize_json_mapping(data.get("validation_payload") or data.get("validation")),
            payload=normalize_json_mapping(data.get("payload") or data),
            metadata=normalize_json_mapping(data.get("metadata")),
            variants=[
                normalize_json_mapping(item)
                for item in normalize_json_list(data.get("variants"))
                if isinstance(item, Mapping)
            ],
            assets=[
                normalize_json_mapping(item)
                for item in normalize_json_list(data.get("assets"))
                if isinstance(item, Mapping)
            ],
            documents=[
                normalize_json_mapping(item)
                for item in normalize_json_list(data.get("documents"))
                if isinstance(item, Mapping)
            ],
            validation_issues=[
                normalize_json_mapping(item)
                for item in normalize_json_list(data.get("validation_issues") or data.get("issues"))
                if isinstance(item, Mapping)
            ],
        )

    def validate(self) -> None:
        errors: list[str] = []

        if self.mode not in {DRAFT_MODE_CREATE, DRAFT_MODE_UPDATE, DRAFT_MODE_IMPORT, DRAFT_MODE_GENERATE}:
            errors.append(f"invalid mode {self.mode!r}")

        if self.mode == DRAFT_MODE_UPDATE and not self.target_item_id and not self.target_vplib_uid and not self.base_revision_id:
            errors.append("update draft requires target_item_id, target_vplib_uid or base_revision_id")

        if not self.title and not self.label and not self.name and not self.family_id and not self.vplib_uid:
            errors.append("draft requires title, label, name, family_id or vplib_uid")

        if errors:
            raise CreativeLibraryDraftServiceValidationError("Invalid draft input.", errors=errors)

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "mode": self.mode,
            "source_scope": self.source_scope,
            "target_item_id": self.target_item_id,
            "target_vplib_uid": self.target_vplib_uid,
            "base_revision_id": self.base_revision_id,
            "published_revision_id": self.published_revision_id,
            "family_id": self.family_id,
            "package_id": self.package_id,
            "vplib_uid": self.vplib_uid,
            "title": self.title,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "family_payload": normalize_json_mapping(self.family_payload),
            "classification_payload": normalize_json_mapping(self.classification_payload),
            "manifest_payload": normalize_json_mapping(self.manifest_payload),
            "modules_payload": normalize_json_mapping(self.modules_payload),
            "generator_payload": normalize_json_mapping(self.generator_payload),
            "validation_payload": normalize_json_mapping(self.validation_payload),
            "payload": normalize_json_mapping(self.payload),
            "metadata": normalize_json_mapping(self.metadata),
        }


@dataclass(slots=True)
class DraftValidationIssueInput:
    """Normalized validation issue input."""

    severity: str = ISSUE_SEVERITY_ERROR
    code: str = "validation_error"
    message: str = "Validation issue"
    field_key: str | None = None
    path: str | None = None
    blocking: bool = True
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DraftValidationIssueInput":
        data = normalize_json_mapping(payload)
        severity = clean_string(data.get("severity"), fallback=ISSUE_SEVERITY_ERROR).lower()

        return cls(
            severity=severity,
            code=clean_string(data.get("code"), fallback="validation_error"),
            message=clean_string(data.get("message"), fallback="Validation issue"),
            field_key=optional_string(data.get("field_key")),
            path=optional_string(data.get("path")),
            blocking=normalize_bool(data.get("blocking"), default=severity in {ISSUE_SEVERITY_ERROR, ISSUE_SEVERITY_BLOCKING}),
            payload=data,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "field_key": self.field_key,
            "path": self.path,
            "blocking": self.blocking,
            "payload": normalize_json_mapping(self.payload),
        }


@dataclass(slots=True)
class DraftServiceResult:
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
            "schema_version": CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION,
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

class CreativeLibraryDraftService:
    """
    High-level service for Creative Library Draft workflows.

    Args:
        repository:
            Optional CreativeLibraryDraftRepository instance.
        definition_service:
            Optional LibraryDefinitionCatalogService instance.
        file_service:
            Optional LibraryFileService instance.
        publish_adapter:
            Optional service/object that can publish a prepared draft bundle.
    """

    def __init__(
        self,
        repository: Any | None = None,
        definition_service: Any | None = None,
        file_service: Any | None = None,
        publish_adapter: Any | None = None,
    ) -> None:
        self.repository = repository or self._create_repository()
        self.definition_service = definition_service or self._create_definition_service()
        self.file_service = file_service or self._create_file_service()
        self.publish_adapter = publish_adapter or self._create_publish_adapter()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_repository(self) -> Any:
        repo_module = _repo_module()
        factory = getattr(repo_module, "create_creative_library_draft_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(repo_module, "CreativeLibraryDraftRepository", None)
        if repo_class is None:
            raise CreativeLibraryDraftServiceImportError("CreativeLibraryDraftRepository class is not available.")

        return repo_class()

    def _create_definition_service(self) -> Any | None:
        try:
            module = _load_definition_service_module()
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

    def _create_publish_adapter(self) -> Any | None:
        try:
            module = _load_publish_service_module()

            for factory_name in (
                "create_creative_library_publish_service",
                "create_library_published_service",
                "get_library_published_service",
                "create_library_db_sync_service",
                "get_default_library_published_service",
            ):
                factory = getattr(module, factory_name, None)
                if callable(factory):
                    return factory()

            for class_name in (
                "CreativeLibraryPublishService",
                "LibraryPublishedService",
                "LibraryDbSyncService",
            ):
                service_class = getattr(module, class_name, None)
                if service_class is not None:
                    return service_class()
        except Exception:
            return None

        return None

    # ------------------------------------------------------------------
    # Draft reads
    # ------------------------------------------------------------------

    def list_drafts(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        status: Any = None,
        mode: Any = None,
        target_vplib_uid: Any = None,
        include_deleted: bool = False,
        include_published: bool = True,
        include_discarded: bool = False,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Lists draft summaries."""
        try:
            query = {
                "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
                "status": optional_string(status),
                "mode": optional_string(mode),
                "target_vplib_uid": optional_string(target_vplib_uid),
                "include_deleted": include_deleted,
                "include_published": include_published,
                "include_discarded": include_discarded,
                "limit": normalize_int(limit, default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT),
                "offset": normalize_int(offset, default=0, minimum=0),
            }
            items = self.repository.list_draft_payloads(query=query, include_summary=True)

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_drafts",
                payload={
                    "query": query,
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_drafts")

    def get_draft(
        self,
        draft_ref: Any,
        *,
        include_variants: bool = True,
        include_assets: bool = True,
        include_documents: bool = True,
        include_issues: bool = True,
        include_audit: bool = False,
        include_summary: bool = True,
    ) -> dict[str, Any]:
        """Returns one draft payload."""
        try:
            payload = self.repository.get_draft_payload(
                draft_ref,
                include_variants=include_variants,
                include_assets=include_assets,
                include_documents=include_documents,
                include_issues=include_issues,
                include_audit=include_audit,
                include_summary=include_summary,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="get_draft",
                payload={"draft": payload},
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="get_draft")

    # ------------------------------------------------------------------
    # Draft writes
    # ------------------------------------------------------------------

    def create_draft(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        auto_validate: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Creates a draft with optional initial variants/assets/documents/issues."""
        try:
            draft_input = DraftInput.from_payload(payload, user_id=user_id)
            draft_input.validate()

            draft = self.repository.create_draft(
                draft_input.to_payload(),
                owner_user_id=draft_input.user_id,
                source_scope=draft_input.source_scope,
                created_by_user_id=draft_input.user_id,
                commit=False,
                audit=True,
            )

            draft_id = getattr(draft, "id", None)

            created_children = self._create_initial_children(
                draft_id,
                variants=draft_input.variants,
                assets=draft_input.assets,
                documents=draft_input.documents,
                validation_issues=draft_input.validation_issues,
                user_id=draft_input.user_id,
            )

            validation_result = None
            if auto_validate:
                validation_result = self._validate_draft_internal(
                    draft_id,
                    user_id=draft_input.user_id,
                    replace_existing=True,
                    commit=False,
                )

            if commit:
                self.repository.commit()
            else:
                self.repository.flush()

            draft_payload = self.repository.get_draft_payload(
                draft_id,
                include_variants=True,
                include_assets=True,
                include_documents=True,
                include_issues=True,
                include_summary=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="create_draft",
                payload={
                    "created": True,
                    "draft": draft_payload,
                    "children": created_children,
                    "validation": validation_result,
                },
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="create_draft")

    def update_draft(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        auto_validate: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Updates a draft and optionally upserts children."""
        try:
            data = normalize_json_mapping(payload)
            normalized_user_id = normalize_user_id(user_id or data.get("user_id"), default=DEFAULT_USER_ID)

            draft = self.repository.update_draft(
                draft_ref,
                data,
                user_id=normalized_user_id,
                allow_locked=normalize_bool(data.get("allow_locked"), default=False),
                commit=False,
                audit=True,
            )
            draft_id = getattr(draft, "id", None)

            child_results = self._upsert_children_from_payload(
                draft_id,
                data,
                user_id=normalized_user_id,
            )

            validation_result = None
            if auto_validate or normalize_bool(data.get("auto_validate"), default=False):
                validation_result = self._validate_draft_internal(
                    draft_id,
                    user_id=normalized_user_id,
                    replace_existing=True,
                    commit=False,
                )

            if commit:
                self.repository.commit()
            else:
                self.repository.flush()

            draft_payload = self.repository.get_draft_payload(
                draft_id,
                include_variants=True,
                include_assets=True,
                include_documents=True,
                include_issues=True,
                include_summary=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="update_draft",
                payload={
                    "updated": True,
                    "draft": draft_payload,
                    "children": child_results,
                    "validation": validation_result,
                },
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="update_draft")

    def discard_draft(
        self,
        draft_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Discards a draft."""
        try:
            discarded = self.repository.discard_draft(
                draft_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="discard_draft",
                payload={
                    "discarded": discarded,
                    "draft_ref": draft_ref,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="discard_draft")

    def delete_draft(
        self,
        draft_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Soft-deletes a draft."""
        try:
            deleted = self.repository.soft_delete_draft(
                draft_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="delete_draft",
                payload={
                    "deleted": deleted,
                    "draft_ref": draft_ref,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="delete_draft")

    # ------------------------------------------------------------------
    # Child operations
    # ------------------------------------------------------------------

    def add_variant(self, draft_ref: Any, payload: Mapping[str, Any], *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Adds a draft variant."""
        return self._child_action(
            action="add_variant",
            callback=lambda: self.repository.add_variant(draft_ref, payload, user_id=user_id, commit=commit, audit=True),
            payload_key="variant",
        )

    def update_variant(self, variant_ref: Any, payload: Mapping[str, Any], *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Updates a draft variant."""
        return self._child_action(
            action="update_variant",
            callback=lambda: self.repository.update_variant(variant_ref, payload, user_id=user_id, commit=commit, audit=True),
            payload_key="variant",
        )

    def delete_variant(self, variant_ref: Any, *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Soft-deletes a draft variant."""
        try:
            deleted = self.repository.soft_delete_variant(variant_ref, user_id=user_id, commit=commit, audit=True)
            return DraftServiceResult(ok=True, status=STATUS_OK, action="delete_variant", payload={"deleted": deleted, "variant_ref": variant_ref}).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="delete_variant")

    def add_asset(self, draft_ref: Any, payload: Mapping[str, Any], *, draft_variant_ref: Any = None, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Adds a draft asset."""
        return self._child_action(
            action="add_asset",
            callback=lambda: self.repository.add_asset(draft_ref, payload, draft_variant_ref=draft_variant_ref, user_id=user_id, commit=commit, audit=True),
            payload_key="asset",
        )

    def update_asset(self, asset_ref: Any, payload: Mapping[str, Any], *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Updates a draft asset."""
        return self._child_action(
            action="update_asset",
            callback=lambda: self.repository.update_asset(asset_ref, payload, user_id=user_id, commit=commit, audit=True),
            payload_key="asset",
        )

    def delete_asset(self, asset_ref: Any, *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Soft-deletes a draft asset."""
        try:
            deleted = self.repository.soft_delete_asset(asset_ref, user_id=user_id, commit=commit, audit=True)
            return DraftServiceResult(ok=True, status=STATUS_OK, action="delete_asset", payload={"deleted": deleted, "asset_ref": asset_ref}).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="delete_asset")

    def add_document(self, draft_ref: Any, payload: Mapping[str, Any], *, draft_variant_ref: Any = None, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Adds a draft document."""
        return self._child_action(
            action="add_document",
            callback=lambda: self.repository.add_document(draft_ref, payload, draft_variant_ref=draft_variant_ref, user_id=user_id, commit=commit, audit=True),
            payload_key="document",
        )

    def update_document(self, document_ref: Any, payload: Mapping[str, Any], *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Updates a draft document."""
        return self._child_action(
            action="update_document",
            callback=lambda: self.repository.update_document(document_ref, payload, user_id=user_id, commit=commit, audit=True),
            payload_key="document",
        )

    def delete_document(self, document_ref: Any, *, user_id: Any = DEFAULT_USER_ID, commit: bool = True) -> dict[str, Any]:
        """Soft-deletes a draft document."""
        try:
            deleted = self.repository.soft_delete_document(document_ref, user_id=user_id, commit=commit, audit=True)
            return DraftServiceResult(ok=True, status=STATUS_OK, action="delete_document", payload={"deleted": deleted, "document_ref": document_ref}).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action="delete_document")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_draft(
        self,
        draft_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        replace_existing: bool = True,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Validates draft and stores validation issues."""
        try:
            result = self._validate_draft_internal(
                draft_ref,
                user_id=user_id,
                replace_existing=replace_existing,
                commit=commit,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="validate_draft",
                payload=result,
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="validate_draft")

    def set_validation_issues(
        self,
        draft_ref: Any,
        issues: Iterable[Mapping[str, Any]],
        *,
        user_id: Any = DEFAULT_USER_ID,
        replace_existing: bool = True,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Stores externally computed validation issues."""
        try:
            normalized_issues = [
                DraftValidationIssueInput.from_payload(item).to_payload()
                for item in issues or ()
            ]

            result = self.repository.set_validation_results(
                draft_ref,
                normalized_issues,
                user_id=user_id,
                replace_existing=replace_existing,
                commit=commit,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="set_validation_issues",
                payload=result,
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="set_validation_issues")

    def _validate_draft_internal(
        self,
        draft_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        replace_existing: bool = True,
        commit: bool = False,
    ) -> dict[str, Any]:
        """Internal validation without service envelope."""
        self.repository.mark_validating(draft_ref, user_id=user_id, commit=False)
        draft_payload = self.repository.get_draft_payload(
            draft_ref,
            include_variants=True,
            include_assets=True,
            include_documents=True,
            include_issues=False,
            include_summary=False,
        )

        issues = self.build_validation_issues(draft_payload)
        result = self.repository.set_validation_results(
            draft_ref,
            issues,
            user_id=user_id,
            replace_existing=replace_existing,
            commit=commit,
        )
        return normalize_json_mapping(result)

    def build_validation_issues(self, draft_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """
        Builds baseline validation issues.

        This is intentionally conservative. Domain-specific validation can later
        be added through Definition Catalog/Create Context validators.
        """
        draft = normalize_json_mapping(draft_payload)
        issues: list[dict[str, Any]] = []

        def add_issue(
            *,
            code: str,
            message: str,
            severity: str = ISSUE_SEVERITY_ERROR,
            field_key: str | None = None,
            path: str | None = None,
            blocking: bool | None = None,
        ) -> None:
            issues.append(
                DraftValidationIssueInput(
                    severity=severity,
                    code=code,
                    message=message,
                    field_key=field_key,
                    path=path,
                    blocking=blocking if blocking is not None else severity in {ISSUE_SEVERITY_ERROR, ISSUE_SEVERITY_BLOCKING},
                    payload={
                        "source": "creative_library_draft_service",
                    },
                ).to_payload()
            )

        if not payload_has_any(draft, "title", "label", "name", "family_id", "vplib_uid", "target_vplib_uid"):
            add_issue(
                code="draft.identity_missing",
                message="Draft requires title, label, name, family_id, vplib_uid or target_vplib_uid.",
                field_key="title",
                path="draft",
            )

        mode = clean_string(draft.get("mode"), fallback=DRAFT_MODE_CREATE)
        if mode == DRAFT_MODE_UPDATE and not payload_has_any(draft, "target_item_id", "target_vplib_uid", "base_revision_id"):
            add_issue(
                code="draft.update_target_missing",
                message="Update draft requires target_item_id, target_vplib_uid or base_revision_id.",
                field_key="target_item_id",
                path="draft",
            )

        manifest = normalize_json_mapping(draft.get("manifest_payload") or draft.get("manifest"))
        if not manifest and not draft.get("target_vplib_uid") and not draft.get("vplib_uid"):
            add_issue(
                code="draft.manifest_missing",
                message="Draft has no manifest payload or vplib_uid. Publish will not be possible until identity is resolved.",
                severity=ISSUE_SEVERITY_WARNING,
                field_key="manifest_payload",
                path="draft.manifest_payload",
                blocking=False,
            )

        variants = normalize_json_list(draft.get("variants"))
        if not variants:
            add_issue(
                code="draft.variants_missing",
                message="Draft has no variants.",
                severity=ISSUE_SEVERITY_WARNING,
                field_key="variants",
                path="draft.variants",
                blocking=False,
            )

        for index, variant in enumerate(variants):
            if not isinstance(variant, Mapping):
                continue

            variant_payload = normalize_json_mapping(variant)
            if not payload_has_any(variant_payload, "variant_id", "variant_key", "draft_variant_uid"):
                add_issue(
                    code="draft_variant.identity_missing",
                    message=f"Variant at index {index} has no variant_id, variant_key or draft_variant_uid.",
                    severity=ISSUE_SEVERITY_WARNING,
                    field_key="variant_id",
                    path=f"variants[{index}]",
                    blocking=False,
                )

            values = normalize_json_mapping(
                variant_payload.get("definition_values_json")
                or variant_payload.get("definition_values")
            )
            if not values:
                add_issue(
                    code="draft_variant.values_missing",
                    message=f"Variant at index {index} has no definition values.",
                    severity=ISSUE_SEVERITY_WARNING,
                    field_key="definition_values",
                    path=f"variants[{index}].definition_values",
                    blocking=False,
                )

        documents = normalize_json_list(draft.get("documents"))
        for index, document in enumerate(documents):
            if not isinstance(document, Mapping):
                continue

            doc_payload = normalize_json_mapping(document)
            if not payload_has_any(doc_payload, "library_file_id", "file_uid", "url", "storage_path"):
                add_issue(
                    code="draft_document.file_reference_missing",
                    message=f"Document at index {index} has no library_file_id, file_uid, url or storage_path.",
                    severity=ISSUE_SEVERITY_WARNING,
                    field_key="documents",
                    path=f"documents[{index}]",
                    blocking=False,
                )

        return issues

    # ------------------------------------------------------------------
    # Publish preparation / publish
    # ------------------------------------------------------------------

    def prepare_publish_payload(
        self,
        draft_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        validate_first: bool = True,
        allow_invalid: bool = False,
    ) -> dict[str, Any]:
        """Builds publish-ready payload without writing published library tables."""
        try:
            if validate_first:
                validation = self._validate_draft_internal(
                    draft_ref,
                    user_id=user_id,
                    replace_existing=True,
                    commit=False,
                )
            else:
                validation = {
                    "valid": not self.repository.has_blocking_issues(draft_ref),
                }

            valid = normalize_bool(validation.get("valid"), default=False)

            if not valid and not allow_invalid:
                if validate_first:
                    self.repository.flush()

                return DraftServiceResult(
                    ok=False,
                    status=STATUS_INVALID_REQUEST,
                    action="prepare_publish_payload",
                    payload={
                        "draft_ref": draft_ref,
                        "valid": False,
                        "validation": validation,
                    },
                    errors=["Draft has blocking validation issues and cannot be prepared for publish."],
                ).to_dict()

            draft_payload = self.repository.get_draft_payload(
                draft_ref,
                include_variants=True,
                include_assets=True,
                include_documents=True,
                include_issues=True,
                include_summary=True,
            )

            publish_payload = self.build_publish_bundle(draft_payload)

            self.repository.flush()

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="prepare_publish_payload",
                payload={
                    "draft": draft_payload,
                    "publish": publish_payload,
                    "validation": validation,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="prepare_publish_payload")

    def publish_draft(
        self,
        draft_ref: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        validate_first: bool = True,
        allow_invalid: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """
        Publishes draft through optional publish adapter.

        The service does not write CreativeLibraryRevision directly. It calls a
        detected adapter method if available.
        """
        try:
            prepared_response = self.prepare_publish_payload(
                draft_ref,
                user_id=user_id,
                validate_first=validate_first,
                allow_invalid=allow_invalid,
            )

            if not prepared_response.get("ok"):
                return prepared_response

            prepared_payload = normalize_json_mapping(prepared_response.get("payload"))
            publish_payload = normalize_json_mapping(prepared_payload.get("publish"))

            if self.publish_adapter is None:
                return DraftServiceResult(
                    ok=False,
                    status=STATUS_NOT_IMPLEMENTED,
                    action="publish_draft",
                    payload={
                        "draft_ref": draft_ref,
                        "publish": publish_payload,
                    },
                    errors=[
                        "No publish adapter is available. Draft was validated and publish payload was prepared, but no published Creative Library revision was written."
                    ],
                ).to_dict()

            publish_result = self._call_publish_adapter(
                self.publish_adapter,
                draft_ref=draft_ref,
                publish_payload=publish_payload,
                user_id=user_id,
            )

            published_revision_id = self._extract_published_revision_id(publish_result)

            self.repository.mark_published(
                draft_ref,
                published_revision_id=published_revision_id,
                user_id=user_id,
                commit=commit,
            )

            draft_payload = self.repository.get_draft_payload(
                draft_ref,
                include_variants=True,
                include_assets=True,
                include_documents=True,
                include_issues=True,
                include_summary=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="publish_draft",
                payload={
                    "draft": draft_payload,
                    "publish_result": normalize_json_value(publish_result),
                    "published_revision_id": published_revision_id,
                },
            ).to_dict()

        except Exception as exc:
            if commit:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            return self.exception_result(exc, action="publish_draft")

    def build_publish_bundle(self, draft_payload: Mapping[str, Any]) -> dict[str, Any]:
        """Builds a publish bundle from draft payload."""
        draft = normalize_json_mapping(draft_payload)

        manifest = normalize_json_mapping(draft.get("manifest_payload") or draft.get("manifest"))
        family = normalize_json_mapping(draft.get("family_payload") or draft.get("family"))
        classification = normalize_json_mapping(draft.get("classification_payload") or draft.get("classification"))
        modules = normalize_json_mapping(draft.get("modules_payload") or draft.get("modules"))
        generator = normalize_json_mapping(draft.get("generator_payload") or draft.get("generator"))

        variants = [
            self._publish_variant_payload(item)
            for item in normalize_json_list(draft.get("variants"))
            if isinstance(item, Mapping)
        ]
        assets = [
            self._publish_asset_payload(item)
            for item in normalize_json_list(draft.get("assets"))
            if isinstance(item, Mapping)
        ]
        documents = [
            self._publish_document_payload(item)
            for item in normalize_json_list(draft.get("documents"))
            if isinstance(item, Mapping)
        ]

        return {
            "schema_version": CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION,
            "source": "creative_library_draft",
            "draft_id": draft.get("id"),
            "draft_uid": draft.get("draft_uid"),
            "owner_user_id": draft.get("owner_user_id"),
            "mode": draft.get("mode"),
            "target_item_id": draft.get("target_item_id"),
            "target_vplib_uid": draft.get("target_vplib_uid"),
            "base_revision_id": draft.get("base_revision_id"),
            "family_id": draft.get("family_id"),
            "package_id": draft.get("package_id"),
            "vplib_uid": draft.get("vplib_uid") or draft.get("target_vplib_uid"),
            "title": draft.get("title") or draft.get("label") or draft.get("name"),
            "description": draft.get("description"),
            "family_payload": family,
            "classification_payload": classification,
            "manifest_payload": manifest,
            "modules_payload": modules,
            "generator_payload": generator,
            "variants": variants,
            "assets": assets,
            "documents": documents,
            "counts": {
                "variant_count": len(variants),
                "asset_count": len(assets),
                "document_count": len(documents),
            },
            "document_bundle": {
                "manifest": manifest,
                "family": family,
                "classification": classification,
                "modules": modules,
                "variants": variants,
                "assets": assets,
                "documents": documents,
                "generator": generator,
            },
        }

    # ------------------------------------------------------------------
    # File integration
    # ------------------------------------------------------------------

    def attach_uploaded_file_as_document(
        self,
        draft_ref: Any,
        *,
        content: Any,
        document_type: Any,
        field_key: Any = None,
        draft_variant_ref: Any = None,
        user_id: Any = DEFAULT_USER_ID,
        original_filename: Any = None,
        mime_type: Any = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Uploads file through LibraryFileService and adds draft document."""
        if self.file_service is None:
            return DraftServiceResult(
                ok=False,
                status=STATUS_NOT_IMPLEMENTED,
                action="attach_uploaded_file_as_document",
                errors=["LibraryFileService is not available."],
            ).to_dict()

        try:
            draft = self.repository.require_draft(draft_ref)
            upload_result = self.file_service.upload(
                content=content,
                original_filename=original_filename,
                mime_type=mime_type,
                document_type=document_type,
                field_key=field_key,
                context_type="creative_draft",
                context_db_id=getattr(draft, "id", None),
                context_uid=getattr(draft, "draft_uid", None),
                user_id=user_id,
                owner_user_id=user_id,
                commit=True,
            )

            if not upload_result.get("ok"):
                return upload_result

            upload_payload = normalize_json_mapping(upload_result.get("payload"))
            file_payload = normalize_json_mapping(upload_payload.get("file"))
            version_payload = normalize_json_mapping(upload_payload.get("version"))

            document = self.repository.add_document(
                getattr(draft, "id", None),
                {
                    "document_type": document_type,
                    "field_key": field_key,
                    "library_file_id": file_payload.get("id"),
                    "file_version_id": version_payload.get("id"),
                    "file_uid": file_payload.get("file_uid"),
                    "title": file_payload.get("original_filename"),
                    "payload": {
                        "upload_result": upload_result,
                    },
                },
                draft_variant_ref=draft_variant_ref,
                user_id=user_id,
                commit=commit,
                audit=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="attach_uploaded_file_as_document",
                payload={
                    "draft": self.repository.get_draft_payload(getattr(draft, "id", None), include_documents=True, include_summary=True),
                    "document": to_dict_or_payload(document),
                    "upload": upload_result,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="attach_uploaded_file_as_document")

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    def list_audit_events(
        self,
        *,
        draft_ref: Any = None,
        user_id: Any = None,
        event_type: Any = None,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Lists draft audit events."""
        try:
            items = self.repository.list_audit_events(
                draft_ref=draft_ref,
                user_id=user_id,
                event_type=event_type,
                limit=limit,
                offset=offset,
                as_dict=True,
            )

            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action="list_audit_events",
                payload={
                    "count": len(items),
                    "items": items,
                },
            ).to_dict()

        except Exception as exc:
            return self.exception_result(exc, action="list_audit_events")

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

        definition_health = {}
        try:
            if self.definition_service is not None and hasattr(self.definition_service, "get_health"):
                definition_health = self.definition_service.get_health()
        except Exception as exc:
            definition_health = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        file_health = {}
        try:
            if self.file_service is not None and hasattr(self.file_service, "get_health"):
                file_health = self.file_service.get_health()
        except Exception as exc:
            file_health = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        return {
            "schema_version": CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION,
            "ok": True,
            "healthy": True,
            "service": type(self).__name__,
            "repository_health": normalize_json_mapping(repository_health),
            "definition_service_available": self.definition_service is not None,
            "definition_service_health": normalize_json_mapping(definition_health),
            "file_service_available": self.file_service is not None,
            "file_service_health": normalize_json_mapping(file_health),
            "publish_adapter_available": self.publish_adapter is not None,
            "supports_create_draft": True,
            "supports_update_draft": True,
            "supports_validate_draft": True,
            "supports_prepare_publish_payload": True,
            "supports_publish_draft": self.publish_adapter is not None,
            "supports_variants": True,
            "supports_assets": True,
            "supports_documents": True,
            "supports_validation_issues": True,
            "supports_file_attach": self.file_service is not None,
            "supports_audit": True,
        }

    def exception_result(self, exc: Exception, *, action: str) -> dict[str, Any]:
        """Maps exception to service result."""
        lowered = f"{type(exc).__name__} {exc}".lower()

        status = STATUS_FAILED

        if "notfound" in lowered or "not found" in lowered:
            status = STATUS_NOT_FOUND
        elif "not implemented" in lowered or "not available" in lowered:
            status = STATUS_NOT_IMPLEMENTED
        elif "invalid" in lowered or "required" in lowered or "validation" in lowered:
            status = STATUS_INVALID_REQUEST

        errors = getattr(exc, "errors", None)
        if errors:
            error_list = [str(error) for error in errors]
        else:
            error_list = [str(exc)]

        return DraftServiceResult(
            ok=False,
            status=status,
            action=action,
            errors=error_list,
        ).to_dict()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_initial_children(
        self,
        draft_ref: Any,
        *,
        variants: Iterable[Mapping[str, Any]],
        assets: Iterable[Mapping[str, Any]],
        documents: Iterable[Mapping[str, Any]],
        validation_issues: Iterable[Mapping[str, Any]],
        user_id: Any,
    ) -> dict[str, Any]:
        """Creates initial draft children."""
        created_variants = [
            to_dict_or_payload(
                self.repository.add_variant(
                    draft_ref,
                    variant,
                    user_id=user_id,
                    commit=False,
                    audit=True,
                )
            )
            for variant in variants or ()
        ]

        created_assets = [
            to_dict_or_payload(
                self.repository.add_asset(
                    draft_ref,
                    asset,
                    draft_variant_ref=asset.get("draft_variant_id") or asset.get("draft_variant_uid"),
                    user_id=user_id,
                    commit=False,
                    audit=True,
                )
            )
            for asset in assets or ()
        ]

        created_documents = [
            to_dict_or_payload(
                self.repository.add_document(
                    draft_ref,
                    document,
                    draft_variant_ref=document.get("draft_variant_id") or document.get("draft_variant_uid"),
                    user_id=user_id,
                    commit=False,
                    audit=True,
                )
            )
            for document in documents or ()
        ]

        created_issues = [
            to_dict_or_payload(
                self.repository.add_validation_issue(
                    draft_ref,
                    DraftValidationIssueInput.from_payload(issue).to_payload(),
                    draft_variant_ref=issue.get("draft_variant_id") or issue.get("draft_variant_uid"),
                    user_id=user_id,
                    commit=False,
                    audit=False,
                )
            )
            for issue in validation_issues or ()
        ]

        return {
            "variants": created_variants,
            "assets": created_assets,
            "documents": created_documents,
            "validation_issues": created_issues,
            "counts": {
                "variant_count": len(created_variants),
                "asset_count": len(created_assets),
                "document_count": len(created_documents),
                "validation_issue_count": len(created_issues),
            },
        }

    def _upsert_children_from_payload(
        self,
        draft_ref: Any,
        payload: Mapping[str, Any],
        *,
        user_id: Any,
    ) -> dict[str, Any]:
        """Upserts child arrays from update payload."""
        data = normalize_json_mapping(payload)

        result = {
            "variants": [],
            "assets": [],
            "documents": [],
            "validation_issues": [],
        }

        for variant in normalize_json_list(data.get("variants")):
            if not isinstance(variant, Mapping):
                continue
            item = normalize_json_mapping(variant)
            ref = first_non_empty(item.get("draft_variant_id"), item.get("draft_variant_uid"), item.get("id"))
            if ref:
                obj = self.repository.update_variant(ref, item, user_id=user_id, commit=False, audit=True)
            else:
                obj = self.repository.add_variant(draft_ref, item, user_id=user_id, commit=False, audit=True)
            result["variants"].append(to_dict_or_payload(obj))

        for asset in normalize_json_list(data.get("assets")):
            if not isinstance(asset, Mapping):
                continue
            item = normalize_json_mapping(asset)
            ref = first_non_empty(item.get("asset_id"), item.get("asset_uid"), item.get("id"))
            if ref:
                obj = self.repository.update_asset(ref, item, user_id=user_id, commit=False, audit=True)
            else:
                obj = self.repository.add_asset(
                    draft_ref,
                    item,
                    draft_variant_ref=item.get("draft_variant_id") or item.get("draft_variant_uid"),
                    user_id=user_id,
                    commit=False,
                    audit=True,
                )
            result["assets"].append(to_dict_or_payload(obj))

        for document in normalize_json_list(data.get("documents")):
            if not isinstance(document, Mapping):
                continue
            item = normalize_json_mapping(document)
            ref = first_non_empty(item.get("document_id"), item.get("document_uid"), item.get("id"))
            if ref:
                obj = self.repository.update_document(ref, item, user_id=user_id, commit=False, audit=True)
            else:
                obj = self.repository.add_document(
                    draft_ref,
                    item,
                    draft_variant_ref=item.get("draft_variant_id") or item.get("draft_variant_uid"),
                    user_id=user_id,
                    commit=False,
                    audit=True,
                )
            result["documents"].append(to_dict_or_payload(obj))

        if "validation_issues" in data or "issues" in data:
            issues = [
                DraftValidationIssueInput.from_payload(issue).to_payload()
                for issue in normalize_json_list(data.get("validation_issues") or data.get("issues"))
                if isinstance(issue, Mapping)
            ]
            validation = self.repository.set_validation_results(
                draft_ref,
                issues,
                user_id=user_id,
                replace_existing=normalize_bool(data.get("replace_validation_issues"), default=True),
                commit=False,
            )
            result["validation_issues"] = normalize_json_list(validation.get("issues"))

        result["counts"] = {
            "variant_count": len(result["variants"]),
            "asset_count": len(result["assets"]),
            "document_count": len(result["documents"]),
            "validation_issue_count": len(result["validation_issues"]),
        }
        return result

    def _child_action(
        self,
        *,
        action: str,
        callback: Callable[[], Any],
        payload_key: str,
    ) -> dict[str, Any]:
        """Runs child callback with standard envelope."""
        try:
            obj = callback()
            return DraftServiceResult(
                ok=True,
                status=STATUS_OK,
                action=action,
                payload={
                    payload_key: to_dict_or_payload(obj),
                },
            ).to_dict()
        except Exception as exc:
            return self.exception_result(exc, action=action)

    def _publish_variant_payload(self, variant: Mapping[str, Any]) -> dict[str, Any]:
        """Converts draft variant to publish variant payload."""
        payload = normalize_json_mapping(variant)
        return compact_payload(
            {
                "source_draft_variant_id": payload.get("id"),
                "source_draft_variant_uid": payload.get("draft_variant_uid") or payload.get("variant_uid"),
                "variant_id": payload.get("variant_id") or payload.get("variant_key"),
                "variant_key": payload.get("variant_key"),
                "label": payload.get("label") or payload.get("name") or payload.get("variant_id"),
                "sort_order": payload.get("sort_order"),
                "definition_values_json": payload.get("definition_values_json") or payload.get("definition_values"),
                "summary_json": payload.get("summary_json") or payload.get("summary"),
                "payload": payload.get("payload"),
                "meta": payload.get("meta"),
                "metadata_json": payload.get("metadata_json") or payload.get("metadata"),
            }
        )

    def _publish_asset_payload(self, asset: Mapping[str, Any]) -> dict[str, Any]:
        """Converts draft asset to publish asset payload."""
        payload = normalize_json_mapping(asset)
        return compact_payload(
            {
                "source_draft_asset_id": payload.get("id"),
                "asset_uid": payload.get("asset_uid"),
                "draft_variant_id": payload.get("draft_variant_id"),
                "asset_kind": payload.get("asset_kind"),
                "role": payload.get("role"),
                "library_file_id": payload.get("library_file_id"),
                "file_version_id": payload.get("file_version_id"),
                "file_uid": payload.get("file_uid"),
                "source_path": payload.get("source_path"),
                "storage_path": payload.get("storage_path"),
                "filename": payload.get("filename"),
                "mime_type": payload.get("mime_type"),
                "size_bytes": payload.get("size_bytes"),
                "sha256": payload.get("sha256"),
                "sort_order": payload.get("sort_order"),
                "payload": payload.get("payload"),
                "meta": payload.get("meta"),
                "metadata_json": payload.get("metadata_json") or payload.get("metadata"),
            }
        )

    def _publish_document_payload(self, document: Mapping[str, Any]) -> dict[str, Any]:
        """Converts draft document to publish document payload."""
        payload = normalize_json_mapping(document)
        return compact_payload(
            {
                "source_draft_document_id": payload.get("id"),
                "document_uid": payload.get("document_uid"),
                "draft_variant_id": payload.get("draft_variant_id"),
                "document_kind": payload.get("document_kind"),
                "document_type": payload.get("document_type"),
                "field_key": payload.get("field_key"),
                "title": payload.get("title") or payload.get("label"),
                "url": payload.get("url"),
                "library_file_id": payload.get("library_file_id"),
                "file_version_id": payload.get("file_version_id"),
                "file_uid": payload.get("file_uid"),
                "storage_path": payload.get("storage_path"),
                "sort_order": payload.get("sort_order"),
                "payload": payload.get("payload"),
                "meta": payload.get("meta"),
                "metadata_json": payload.get("metadata_json") or payload.get("metadata"),
            }
        )

    def _call_publish_adapter(
        self,
        adapter: Any,
        *,
        draft_ref: Any,
        publish_payload: Mapping[str, Any],
        user_id: Any,
    ) -> Any:
        """Calls available publish adapter method."""
        for method_name in (
            "publish_draft",
            "publish_from_draft",
            "publish_document_bundle",
            "publish_bundle",
            "publish",
        ):
            method = getattr(adapter, method_name, None)
            if not callable(method):
                continue

            try:
                return method(
                    draft_ref=draft_ref,
                    publish_payload=publish_payload,
                    user_id=user_id,
                )
            except TypeError:
                try:
                    return method(publish_payload, user_id=user_id)
                except TypeError:
                    return method(publish_payload)

        raise CreativeLibraryDraftPublishNotAvailableError(
            "Publish adapter does not expose publish_draft, publish_from_draft, publish_document_bundle, publish_bundle or publish."
        )

    def _extract_published_revision_id(self, publish_result: Any) -> int | None:
        """Extracts published revision id from adapter result."""
        data = normalize_json_mapping(publish_result)

        for key in (
            "published_revision_id",
            "revision_id",
            "creative_library_revision_id",
            "id",
        ):
            value = normalize_int(data.get(key), default=None, minimum=1)
            if value is not None:
                return value

        payload = normalize_json_mapping(data.get("payload"))
        for key in (
            "published_revision_id",
            "revision_id",
            "creative_library_revision_id",
            "id",
        ):
            value = normalize_int(payload.get(key), default=None, minimum=1)
            if value is not None:
                return value

        revision = normalize_json_mapping(payload.get("revision") or data.get("revision"))
        for key in ("id", "revision_id"):
            value = normalize_int(revision.get(key), default=None, minimum=1)
            if value is not None:
                return value

        return None


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_creative_library_draft_service(
    repository: Any | None = None,
    definition_service: Any | None = None,
    file_service: Any | None = None,
    publish_adapter: Any | None = None,
) -> CreativeLibraryDraftService:
    """Factory for dependency injection."""
    return CreativeLibraryDraftService(
        repository=repository,
        definition_service=definition_service,
        file_service=file_service,
        publish_adapter=publish_adapter,
    )


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION


def clear_creative_library_draft_service_caches() -> dict[str, Any]:
    """Clears service import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_repository_module,
        _load_definition_service_module,
        _load_file_service_module,
        _load_publish_service_module,
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
    "CREATIVE_LIBRARY_DRAFT_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "SOURCE_SCOPE_USER",
    "SOURCE_SCOPE_GENERATED",
    "SOURCE_SCOPE_IMPORTED",
    "DRAFT_MODE_CREATE",
    "DRAFT_MODE_UPDATE",
    "DRAFT_MODE_IMPORT",
    "DRAFT_MODE_GENERATE",
    "DRAFT_STATUS_DRAFT",
    "DRAFT_STATUS_VALIDATING",
    "DRAFT_STATUS_VALID",
    "DRAFT_STATUS_INVALID",
    "DRAFT_STATUS_PUBLISHED",
    "DRAFT_STATUS_DISCARDED",
    "DRAFT_STATUS_DELETED",
    "ISSUE_SEVERITY_INFO",
    "ISSUE_SEVERITY_WARNING",
    "ISSUE_SEVERITY_ERROR",
    "ISSUE_SEVERITY_BLOCKING",
    "STATUS_OK",
    "STATUS_INVALID_REQUEST",
    "STATUS_NOT_FOUND",
    "STATUS_FAILED",
    "STATUS_NOT_IMPLEMENTED",

    # Exceptions
    "CreativeLibraryDraftServiceError",
    "CreativeLibraryDraftServiceImportError",
    "CreativeLibraryDraftServiceValidationError",
    "CreativeLibraryDraftServiceNotFoundError",
    "CreativeLibraryDraftServiceConflictError",
    "CreativeLibraryDraftPublishNotAvailableError",

    # Dataclasses
    "DraftInput",
    "DraftValidationIssueInput",
    "DraftServiceResult",

    # Service
    "CreativeLibraryDraftService",
    "create_creative_library_draft_service",

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
    "to_dict_or_payload",
    "issue_is_blocking",
    "payload_has_any",
    "compact_payload",
    "get_service_version",
    "clear_creative_library_draft_service_caches",
]