# services/vectoplan-library/src/library/repositories/library_definition_repository.py
"""
Repository for VECTOPLAN Library Definition Catalog.

Diese Datei kapselt alle DB-Zugriffe auf:

- library_definition_datasets
- library_definition_seed_runs
- library_definition_variables
- library_definition_units
- library_definition_materials
- library_definition_document_types
- library_definition_object_kinds
- library_definition_family_profiles
- library_definition_variant_profiles
- library_definition_profile_bindings
- library_definition_overrides

Ziel:

    definitions/data/*.json
        -> Seed-Service
        -> LibraryDefinitionRepository
        -> PostgreSQL Definition Tables
        -> LibraryDefinitionCatalogService
        -> /api/v1/vplib/definitions/*

Architekturregeln:

- Repository enthält keine Flask-Routes.
- Repository enthält keine UI-Logik.
- Repository enthält keine VPLIB-Generatorlogik.
- Repository erzeugt keine Tabellen.
- Repository führt keine Migration aus.
- Repository führt kein db.create_all() aus.
- Repository öffnet keine aktive DB-Verbindung beim Import.
- Repository darf schreiben, aber nur über explizite Methoden.
- Business-Auflösung wie "Create Context vollständig bauen" gehört in den Service.
- Dieses Repository liefert dafür robuste DB-Rohdaten und einfache resolved Payloads.

Phase 1:

- user_id darf weiterhin 1 sein.
- Systemdefinitionen bleiben source_scope="system", owner_user_id=None.
- Userdefinitionen bleiben source_scope="user", owner_user_id=1.
- PATCH auf Systemdefinition sollte später im Service als Override abgebildet werden.
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

LIBRARY_DEFINITION_REPOSITORY_VERSION: Final[str] = "vectoplan_library.repository.library_definition.v1"

DEFAULT_USER_ID: Final[int] = 1
DEFAULT_DEFINITIONS_VERSION: Final[str] = "v1"

DATASET_VARIABLES: Final[str] = "variables"
DATASET_UNITS: Final[str] = "units"
DATASET_MATERIALS: Final[str] = "materials"
DATASET_DOCUMENT_TYPES: Final[str] = "document_types"
DATASET_OBJECT_KINDS: Final[str] = "object_kinds"
DATASET_FAMILY_PROFILES: Final[str] = "family_profiles"
DATASET_VARIANT_PROFILES: Final[str] = "variant_profiles"
DATASET_PROFILE_BINDINGS: Final[str] = "profile_bindings"

SYSTEM_SCOPE: Final[str] = "system"
USER_SCOPE: Final[str] = "user"

STATUS_ACTIVE: Final[str] = "active"
STATUS_DEPRECATED: Final[str] = "deprecated"
STATUS_DELETED: Final[str] = "deleted"

DATASET_KEYS: Final[tuple[str, ...]] = (
    DATASET_VARIABLES,
    DATASET_UNITS,
    DATASET_MATERIALS,
    DATASET_DOCUMENT_TYPES,
    DATASET_OBJECT_KINDS,
    DATASET_FAMILY_PROFILES,
    DATASET_VARIANT_PROFILES,
    DATASET_PROFILE_BINDINGS,
)

_DATASET_KEY_COLUMN_MAP: Final[dict[str, str]] = {
    DATASET_VARIABLES: "variable_key",
    DATASET_UNITS: "unit_id",
    DATASET_MATERIALS: "material_id",
    DATASET_DOCUMENT_TYPES: "document_type_id",
    DATASET_OBJECT_KINDS: "object_kind_id",
    DATASET_FAMILY_PROFILES: "family_profile_id",
    DATASET_VARIANT_PROFILES: "variant_profile_id",
    DATASET_PROFILE_BINDINGS: "binding_id",
}

_DATASET_MODEL_NAME_MAP: Final[dict[str, str]] = {
    DATASET_VARIABLES: "LibraryDefinitionVariable",
    DATASET_UNITS: "LibraryDefinitionUnit",
    DATASET_MATERIALS: "LibraryDefinitionMaterial",
    DATASET_DOCUMENT_TYPES: "LibraryDefinitionDocumentType",
    DATASET_OBJECT_KINDS: "LibraryDefinitionObjectKind",
    DATASET_FAMILY_PROFILES: "LibraryDefinitionFamilyProfile",
    DATASET_VARIANT_PROFILES: "LibraryDefinitionVariantProfile",
    DATASET_PROFILE_BINDINGS: "LibraryDefinitionProfileBinding",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryDefinitionRepositoryError(RuntimeError):
    """Base error for LibraryDefinitionRepository."""


class LibraryDefinitionRepositoryImportError(LibraryDefinitionRepositoryError):
    """Raised when model/db imports fail."""


class LibraryDefinitionNotFoundError(LibraryDefinitionRepositoryError):
    """Raised when a requested definition cannot be found."""


class LibraryDefinitionConflictError(LibraryDefinitionRepositoryError):
    """Raised when a write operation would violate repository invariants."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """Loads the central Flask-SQLAlchemy extension defensively."""
    errors: list[str] = []

    for module_name in (
        "extensions",
        "src.extensions",
        "vectoplan_library.extensions",
    ):
        try:
            module = importlib.import_module(module_name)
            db_obj = getattr(module, "db", None)
            if db_obj is not None:
                return db_obj
            errors.append(f"{module_name}: db missing")
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryDefinitionRepositoryImportError(
        "Could not import SQLAlchemy extension `db`. "
        + " | ".join(errors)
    )


@lru_cache(maxsize=1)
def _load_definition_models_module() -> ModuleType:
    """Loads models.library_definitions defensively."""
    errors: list[str] = []

    for module_name in (
        "models.library_definitions",
        "src.models.library_definitions",
        "vectoplan_library.models.library_definitions",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryDefinitionRepositoryImportError(
        "Could not import library definition models. "
        + " | ".join(errors)
    )


def _models() -> ModuleType:
    """Short alias for lazy model module access."""
    return _load_definition_models_module()


def _db() -> Any:
    """Short alias for lazy db access."""
    return _load_db()


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
    """Normalizes optional string values."""
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


def normalize_int(value: Any, *, default: int | None = 0, minimum: int | None = None) -> int | None:
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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return default


def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalizes mapping values."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

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


def clean_dataset_key(dataset_key: Any) -> str:
    """Normalizes dataset keys through model helper when available."""
    model_module = _models()
    helper = getattr(model_module, "clean_dataset_key", None)

    if callable(helper):
        return str(helper(dataset_key))

    key = clean_string(dataset_key).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "documents": DATASET_DOCUMENT_TYPES,
        "documenttypes": DATASET_DOCUMENT_TYPES,
        "document_types": DATASET_DOCUMENT_TYPES,
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


def owner_scope_for(*, source_scope: Any = SYSTEM_SCOPE, owner_user_id: Any = None) -> str:
    """Builds a stable owner_scope."""
    model_module = _models()
    helper = getattr(model_module, "owner_scope_for", None)

    if callable(helper):
        return str(helper(source_scope=source_scope, owner_user_id=owner_user_id))

    scope = clean_string(source_scope, fallback=SYSTEM_SCOPE).lower()
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == SYSTEM_SCOPE and user_id is None:
        return SYSTEM_SCOPE

    if scope == USER_SCOPE:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope


def definition_key_from_item(dataset_key: Any, item: Mapping[str, Any]) -> str:
    """Extracts a stable key from a definition item."""
    key = clean_dataset_key(dataset_key)
    data = normalize_json_mapping(item)

    model_module = _models()
    helper = getattr(model_module, "definition_key_from_item", None)

    if callable(helper):
        try:
            return str(helper(data))
        except Exception:
            pass

    preferred_keys = ("key", "id", "variable_key", "unit_id", "material_id", "document_type_id", "object_kind_id")
    for field_name in preferred_keys:
        value = data.get(field_name)
        if value is not None and str(value).strip():
            return str(value).strip().lower().replace("/", ".").replace(" ", "_")

    column_name = _DATASET_KEY_COLUMN_MAP.get(key, "definition_key")
    value = data.get(column_name)
    if value is not None and str(value).strip():
        return str(value).strip().lower().replace("/", ".").replace(" ", "_")

    raise ValueError(f"Could not determine definition key for dataset {dataset_key!r}.")


def item_list_from_dataset_payload(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extracts items[] from a dataset payload."""
    data = normalize_json_mapping(payload)
    items = data.get("items")

    if not isinstance(items, list):
        return []

    result: list[dict[str, Any]] = []

    for item in items:
        if isinstance(item, Mapping):
            result.append(normalize_json_mapping(item))

    return result


def to_dict_or_payload(value: Any, *, include_payload: bool = True) -> dict[str, Any]:
    """Serializes model objects defensively."""
    if value is None:
        return {}

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            try:
                return normalize_json_mapping(value.to_dict(include_payload=include_payload))
            except TypeError:
                return normalize_json_mapping(value.to_dict())
        except Exception:
            pass

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    result: dict[str, Any] = {}

    for field_name in (
        "id",
        "definition_uid",
        "dataset_key",
        "definition_key",
        "label",
        "name",
        "description",
        "source_scope",
        "owner_user_id",
        "owner_scope",
        "status",
        "active",
        "visible",
        "sort_order",
    ):
        try:
            if hasattr(value, field_name):
                result[field_name] = normalize_json_value(getattr(value, field_name))
        except Exception:
            continue

    return result


def _dedupe_preserve_order(values: Iterable[Any]) -> tuple[Any, ...]:
    """Dedupe helper preserving order."""
    result: list[Any] = []
    seen: set[str] = set()

    for value in values or ():
        key = repr(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)

    return tuple(result)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DefinitionQuery:
    """Structured query options for definition reads."""

    dataset_key: str | None = None
    user_id: int | None = None
    source_scope: str | None = None
    owner_scope: str | None = None
    status: str | None = None
    include_system: bool = True
    include_user: bool = True
    include_inactive: bool = False
    include_deleted: bool = False
    sort: bool = True

    def resolved_dataset_key(self) -> str | None:
        if self.dataset_key is None:
            return None
        return clean_dataset_key(self.dataset_key)

    def resolved_user_id(self) -> int | None:
        return normalize_user_id(self.user_id, default=None)

    def resolved_owner_scopes(self) -> tuple[str, ...]:
        scopes: list[str] = []

        if self.owner_scope:
            scopes.append(self.owner_scope)
            return tuple(_dedupe_preserve_order(scopes))

        if self.include_system:
            scopes.append(SYSTEM_SCOPE)

        if self.include_user:
            user_id = self.resolved_user_id()
            if user_id is not None:
                scopes.append(f"user:{user_id}")

        return tuple(_dedupe_preserve_order(scopes))


@dataclass(slots=True)
class DefinitionBulkUpsertResult:
    """Result for bulk upsert operations."""

    dataset_key: str
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    deprecated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    errors: list[str] = field(default_factory=list)
    definition_keys: list[str] = field(default_factory=list)
    dataset_id: int | None = None

    @property
    def total_count(self) -> int:
        return (
            self.inserted_count
            + self.updated_count
            + self.unchanged_count
            + self.deprecated_count
            + self.skipped_count
            + self.error_count
        )

    def add_error(self, message: Any) -> None:
        self.error_count += 1
        self.errors.append(str(message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIBRARY_DEFINITION_REPOSITORY_VERSION,
            "dataset_key": self.dataset_key,
            "dataset_id": self.dataset_id,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "deprecated_count": self.deprecated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "total_count": self.total_count,
            "definition_keys": list(self.definition_keys),
            "errors": list(self.errors),
        }


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class LibraryDefinitionRepository:
    """
    SQLAlchemy repository for Library Definition Catalog.

    Args:
        session:
            Optional SQLAlchemy session. If omitted, db.session is used lazily.

    Commit strategy:
        - Methods accept commit=False by default.
        - With commit=False, repository flushes where IDs are needed but leaves
          transaction ownership to the caller/service.
        - With commit=True, repository commits and rolls back on error.
    """

    def __init__(self, session: Any | None = None) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Session / model access
    # ------------------------------------------------------------------

    @property
    def session(self) -> Any:
        if self._session is not None:
            return self._session
        return _db().session

    @property
    def models(self) -> ModuleType:
        return _models()

    def model_for_dataset(self, dataset_key: Any) -> type[Any]:
        """Returns the SQLAlchemy model class for a dataset."""
        key = clean_dataset_key(dataset_key)

        helper = getattr(self.models, "model_class_for_dataset", None)
        if callable(helper):
            return helper(key)

        model_name = _DATASET_MODEL_NAME_MAP.get(key)
        if not model_name:
            raise ValueError(f"Unknown definition dataset: {dataset_key!r}")

        model = getattr(self.models, model_name, None)
        if model is None:
            raise LibraryDefinitionRepositoryImportError(
                f"Model class {model_name!r} is not exported by library_definitions.py."
            )

        return model

    def key_column_for_dataset(self, dataset_key: Any) -> str:
        """Returns the dataset-specific key column."""
        key = clean_dataset_key(dataset_key)
        return _DATASET_KEY_COLUMN_MAP.get(key, "definition_key")

    def query_for_dataset(self, dataset_key: Any) -> Any:
        """Returns a SQLAlchemy query for a dataset model."""
        return self.session.query(self.model_for_dataset(dataset_key))

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def _finish_write(self, *, commit: bool) -> None:
        if commit:
            self.session.commit()
        else:
            self.session.flush()

    # ------------------------------------------------------------------
    # Dataset reads
    # ------------------------------------------------------------------

    def list_dataset_keys(self) -> tuple[str, ...]:
        """Returns known dataset keys."""
        model_value = getattr(self.models, "LIBRARY_DEFINITION_DATASET_KEYS", None)
        if model_value:
            return tuple(str(value) for value in model_value)
        return DATASET_KEYS

    def get_dataset(
        self,
        dataset_key: Any,
        *,
        active_only: bool = False,
        for_update: bool = False,
    ) -> Any | None:
        """Returns one dataset row by dataset_key."""
        key = clean_dataset_key(dataset_key)
        model = self.models.LibraryDefinitionDataset

        query = self.session.query(model).filter(model.dataset_key == key)

        if active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        if for_update:
            try:
                query = query.with_for_update()
            except Exception:
                pass

        return query.one_or_none()

    def require_dataset(self, dataset_key: Any, *, active_only: bool = False) -> Any:
        """Returns one dataset row or raises."""
        dataset = self.get_dataset(dataset_key, active_only=active_only)
        if dataset is None:
            raise LibraryDefinitionNotFoundError(f"Definition dataset {dataset_key!r} was not found.")
        return dataset

    def list_datasets(
        self,
        *,
        active_only: bool = True,
        include_payload: bool = False,
    ) -> list[dict[str, Any]]:
        """Lists definition datasets."""
        model = self.models.LibraryDefinitionDataset
        query = self.session.query(model)

        if active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        query = query.order_by(model.dataset_key.asc())

        return [
            dataset.to_dict(include_payload=include_payload)
            if hasattr(dataset, "to_dict")
            else to_dict_or_payload(dataset, include_payload=include_payload)
            for dataset in query.all()
        ]

    # ------------------------------------------------------------------
    # Dataset writes / seed support
    # ------------------------------------------------------------------

    def upsert_dataset(
        self,
        payload: Mapping[str, Any],
        *,
        dataset_key: Any = None,
        source_file_path: Any = None,
        metadata: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Creates or updates a LibraryDefinitionDataset row."""
        data = normalize_json_mapping(payload)
        key = clean_dataset_key(dataset_key or data.get("dataset"))

        try:
            dataset = self.get_dataset(key, for_update=True)

            if dataset is None:
                dataset = self.models.LibraryDefinitionDataset.create_from_payload(
                    data,
                    dataset_key=key,
                    source_file_path=source_file_path,
                    metadata=metadata,
                )
                self.session.add(dataset)
            else:
                dataset.update_from_payload(
                    data,
                    source_file_path=source_file_path,
                    metadata=metadata,
                )

            self._finish_write(commit=commit)
            return dataset

        except Exception:
            if commit:
                self.rollback()
            raise

    def mark_dataset_deprecated(
        self,
        dataset_key: Any,
        *,
        commit: bool = False,
    ) -> bool:
        """Marks a dataset as deprecated."""
        dataset = self.get_dataset(dataset_key)

        if dataset is None:
            return False

        try:
            if hasattr(dataset, "mark_deprecated") and callable(dataset.mark_deprecated):
                dataset.mark_deprecated()
            else:
                dataset.status = STATUS_DEPRECATED
                dataset.active = False

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Definition reads
    # ------------------------------------------------------------------

    def list_definitions(
        self,
        dataset_key: Any,
        *,
        query_options: DefinitionQuery | None = None,
        user_id: Any = None,
        include_system: bool = True,
        include_user: bool = True,
        include_inactive: bool = False,
        include_deleted: bool = False,
        source_scope: Any = None,
        owner_scope: Any = None,
        status: Any = None,
        as_dict: bool = False,
    ) -> list[Any]:
        """Lists definitions from a dataset."""
        key = clean_dataset_key(dataset_key)

        options = query_options or DefinitionQuery(
            dataset_key=key,
            user_id=normalize_user_id(user_id, default=None),
            source_scope=optional_string(source_scope),
            owner_scope=optional_string(owner_scope),
            status=optional_string(status),
            include_system=include_system,
            include_user=include_user,
            include_inactive=include_inactive,
            include_deleted=include_deleted,
        )

        model = self.model_for_dataset(key)
        query = self.session.query(model)

        owner_scopes = options.resolved_owner_scopes()
        if owner_scopes and hasattr(model, "owner_scope"):
            query = query.filter(model.owner_scope.in_(owner_scopes))

        if options.source_scope and hasattr(model, "source_scope"):
            query = query.filter(model.source_scope == options.source_scope)

        if options.status and hasattr(model, "status"):
            query = query.filter(model.status == options.status)

        if not options.include_inactive:
            if hasattr(model, "active"):
                query = query.filter(model.active.is_(True))
            if hasattr(model, "visible"):
                query = query.filter(model.visible.is_(True))

        if not options.include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if options.sort:
            query = self._apply_definition_sort(query, model)

        values = query.all()

        if as_dict:
            return [to_dict_or_payload(value) for value in values]

        return values

    def list_definition_payloads(
        self,
        dataset_key: Any,
        *,
        user_id: Any = None,
        include_system: bool = True,
        include_user: bool = True,
        include_inactive: bool = False,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        """Lists definitions as dictionaries."""
        return self.list_definitions(
            dataset_key,
            user_id=user_id,
            include_system=include_system,
            include_user=include_user,
            include_inactive=include_inactive,
            include_deleted=include_deleted,
            as_dict=True,
        )

    def get_definition(
        self,
        dataset_key: Any,
        definition_key: Any,
        *,
        user_id: Any = None,
        prefer_user: bool = True,
        include_inactive: bool = False,
        include_deleted: bool = False,
        source_scope: Any = None,
        owner_scope: Any = None,
        for_update: bool = False,
    ) -> Any | None:
        """Gets one definition by dataset key and definition key."""
        key = clean_dataset_key(dataset_key)
        normalized_definition_key = clean_string(definition_key).lower()
        model = self.model_for_dataset(key)
        key_column_name = self.key_column_for_dataset(key)
        key_column = getattr(model, key_column_name, getattr(model, "definition_key", None))

        if key_column is None:
            raise LibraryDefinitionRepositoryError(
                f"Model for dataset {key!r} has no key column {key_column_name!r}."
            )

        query = self.session.query(model).filter(key_column == normalized_definition_key)

        if source_scope and hasattr(model, "source_scope"):
            query = query.filter(model.source_scope == source_scope)

        if owner_scope and hasattr(model, "owner_scope"):
            query = query.filter(model.owner_scope == owner_scope)
        else:
            owner_scopes: list[str] = []
            normalized_user_id = normalize_user_id(user_id, default=None)

            if prefer_user and normalized_user_id is not None:
                owner_scopes.append(f"user:{normalized_user_id}")

            owner_scopes.append(SYSTEM_SCOPE)

            if not prefer_user and normalized_user_id is not None:
                owner_scopes.append(f"user:{normalized_user_id}")

            if hasattr(model, "owner_scope"):
                query = query.filter(model.owner_scope.in_(tuple(_dedupe_preserve_order(owner_scopes))))

        if not include_inactive:
            if hasattr(model, "active"):
                query = query.filter(model.active.is_(True))
            if hasattr(model, "visible"):
                query = query.filter(model.visible.is_(True))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        if for_update:
            try:
                query = query.with_for_update()
            except Exception:
                pass

        values = query.all()

        if not values:
            return None

        if owner_scope or source_scope:
            return values[0]

        if prefer_user:
            normalized_user_id = normalize_user_id(user_id, default=None)
            user_scope = f"user:{normalized_user_id}" if normalized_user_id is not None else None

            if user_scope:
                for value in values:
                    if getattr(value, "owner_scope", None) == user_scope:
                        return value

        for value in values:
            if getattr(value, "owner_scope", None) == SYSTEM_SCOPE:
                return value

        return values[0]

    def require_definition(
        self,
        dataset_key: Any,
        definition_key: Any,
        *,
        user_id: Any = None,
        prefer_user: bool = True,
    ) -> Any:
        """Gets one definition or raises."""
        definition = self.get_definition(
            dataset_key,
            definition_key,
            user_id=user_id,
            prefer_user=prefer_user,
        )

        if definition is None:
            raise LibraryDefinitionNotFoundError(
                f"Definition {definition_key!r} in dataset {dataset_key!r} was not found."
            )

        return definition

    def get_definition_payload(
        self,
        dataset_key: Any,
        definition_key: Any,
        *,
        user_id: Any = None,
        prefer_user: bool = True,
    ) -> dict[str, Any] | None:
        """Gets one definition as dictionary."""
        definition = self.get_definition(
            dataset_key,
            definition_key,
            user_id=user_id,
            prefer_user=prefer_user,
        )

        if definition is None:
            return None

        return to_dict_or_payload(definition)

    # ------------------------------------------------------------------
    # Convenience read methods
    # ------------------------------------------------------------------

    def list_variables(self, *, user_id: Any = None, profile_id: Any = None, as_dict: bool = True) -> list[Any]:
        values = self.list_definitions(DATASET_VARIABLES, user_id=user_id, as_dict=as_dict)

        if not profile_id:
            return values

        profile = clean_string(profile_id)

        if as_dict:
            return [
                value
                for value in values
                if profile in {str(item) for item in normalize_json_list(value.get("applies_to"))}
                or "all" in {str(item) for item in normalize_json_list(value.get("applies_to"))}
            ]

        return [
            value
            for value in values
            if hasattr(value, "applies_to_profile") and value.applies_to_profile(profile)
            or "all" in {str(item) for item in normalize_json_list(getattr(value, "applies_to_json", []))}
        ]

    def list_units(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_UNITS, user_id=user_id, as_dict=as_dict)

    def list_materials(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_MATERIALS, user_id=user_id, as_dict=as_dict)

    def list_document_types(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_DOCUMENT_TYPES, user_id=user_id, as_dict=as_dict)

    def list_object_kinds(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_OBJECT_KINDS, user_id=user_id, as_dict=as_dict)

    def list_family_profiles(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_FAMILY_PROFILES, user_id=user_id, as_dict=as_dict)

    def list_variant_profiles(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_VARIANT_PROFILES, user_id=user_id, as_dict=as_dict)

    def list_profile_bindings(self, *, user_id: Any = None, as_dict: bool = True) -> list[Any]:
        return self.list_definitions(DATASET_PROFILE_BINDINGS, user_id=user_id, as_dict=as_dict)

    # ------------------------------------------------------------------
    # Definition writes
    # ------------------------------------------------------------------

    def upsert_definition(
        self,
        dataset_key: Any,
        item: Mapping[str, Any],
        *,
        dataset: Any | None = None,
        source_scope: Any = SYSTEM_SCOPE,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
        commit: bool = False,
    ) -> tuple[Any, bool]:
        """
        Creates or updates a definition.

        Returns:
            (definition, created)
        """
        key = clean_dataset_key(dataset_key)
        data = normalize_json_mapping(item)
        definition_key = definition_key_from_item(key, data)
        normalized_source_scope = clean_string(source_scope, fallback=SYSTEM_SCOPE)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)
        normalized_owner_scope = owner_scope_for(
            source_scope=normalized_source_scope,
            owner_user_id=normalized_owner_user_id,
        )

        try:
            model = self.model_for_dataset(key)
            definition = self.get_definition(
                key,
                definition_key,
                source_scope=normalized_source_scope,
                owner_scope=normalized_owner_scope,
                include_inactive=True,
                include_deleted=True,
                for_update=True,
            )

            created = definition is None

            if created:
                creator = getattr(model, "create_from_item", None)
                if not callable(creator):
                    raise LibraryDefinitionRepositoryError(
                        f"Model {model.__name__} does not expose create_from_item()."
                    )

                definition = creator(
                    data,
                    dataset=dataset,
                    source_scope=normalized_source_scope,
                    owner_user_id=normalized_owner_user_id,
                    created_by_user_id=created_by_user_id,
                )
                self.session.add(definition)
            else:
                updater = getattr(definition, "update_from_item", None)
                if not callable(updater):
                    raise LibraryDefinitionRepositoryError(
                        f"Definition model {type(definition).__name__} does not expose update_from_item()."
                    )

                updater(
                    data,
                    dataset=dataset,
                    source_scope=normalized_source_scope,
                    owner_user_id=normalized_owner_user_id,
                    created_by_user_id=created_by_user_id,
                    updated_by_user_id=updated_by_user_id,
                )

            self._finish_write(commit=commit)
            return definition, created

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_definition(
        self,
        dataset_key: Any,
        definition_key: Any,
        *,
        user_id: Any = None,
        source_scope: Any | None = None,
        owner_scope: Any | None = None,
        commit: bool = False,
    ) -> bool:
        """Soft-deletes a definition row."""
        definition = self.get_definition(
            dataset_key,
            definition_key,
            user_id=user_id,
            source_scope=source_scope,
            owner_scope=owner_scope,
            include_inactive=True,
            include_deleted=True,
            for_update=True,
        )

        if definition is None:
            return False

        try:
            if getattr(definition, "owner_scope", None) == SYSTEM_SCOPE and owner_scope is None and source_scope is None:
                raise LibraryDefinitionConflictError(
                    "System definitions should not be deleted directly. "
                    "Create a user override or mark as deprecated through seed logic."
                )

            if hasattr(definition, "mark_deleted") and callable(definition.mark_deleted):
                definition.mark_deleted(user_id=user_id)
            else:
                definition.status = STATUS_DELETED
                definition.active = False
                definition.visible = False

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    def mark_definition_deprecated(
        self,
        dataset_key: Any,
        definition_key: Any,
        *,
        source_scope: Any = SYSTEM_SCOPE,
        commit: bool = False,
    ) -> bool:
        """Marks a system/imported/generated definition as deprecated."""
        normalized_owner_scope = owner_scope_for(source_scope=source_scope, owner_user_id=None)

        definition = self.get_definition(
            dataset_key,
            definition_key,
            source_scope=source_scope,
            owner_scope=normalized_owner_scope,
            include_inactive=True,
            include_deleted=True,
            for_update=True,
        )

        if definition is None:
            return False

        try:
            definition.status = STATUS_DEPRECATED
            definition.active = False
            if hasattr(definition, "visible"):
                definition.visible = False
            if hasattr(definition, "touch") and callable(definition.touch):
                definition.touch()

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    def bulk_upsert_dataset_items(
        self,
        dataset_key: Any,
        dataset_payload: Mapping[str, Any],
        *,
        source_file_path: Any = None,
        source_scope: Any = SYSTEM_SCOPE,
        owner_user_id: Any = None,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
        deprecated_missing_system_items: bool = False,
        commit: bool = False,
    ) -> DefinitionBulkUpsertResult:
        """
        Upserts a full dataset payload.

        This is intended for the seed service.

        Behavior:
        - Creates/updates LibraryDefinitionDataset.
        - Creates/updates every item in payload["items"].
        - Optionally deprecates missing system items.
        """
        key = clean_dataset_key(dataset_key)
        result = DefinitionBulkUpsertResult(dataset_key=key)

        try:
            dataset = self.upsert_dataset(
                dataset_payload,
                dataset_key=key,
                source_file_path=source_file_path,
                metadata={"source_scope": source_scope},
                commit=False,
            )
            self.session.flush()

            result.dataset_id = getattr(dataset, "id", None)

            seen_keys: set[str] = set()
            items = item_list_from_dataset_payload(dataset_payload)

            for item in items:
                try:
                    definition_key = definition_key_from_item(key, item)
                    seen_keys.add(definition_key)

                    _definition, created = self.upsert_definition(
                        key,
                        item,
                        dataset=dataset,
                        source_scope=source_scope,
                        owner_user_id=owner_user_id,
                        created_by_user_id=created_by_user_id,
                        updated_by_user_id=updated_by_user_id,
                        commit=False,
                    )

                    if created:
                        result.inserted_count += 1
                    else:
                        result.updated_count += 1

                    result.definition_keys.append(definition_key)

                except Exception as exc:
                    result.add_error(f"{key}: {exc}")

            if deprecated_missing_system_items and clean_string(source_scope) == SYSTEM_SCOPE:
                result.deprecated_count += self.deprecate_missing_system_definitions(
                    key,
                    existing_keys=seen_keys,
                    commit=False,
                )

            self._finish_write(commit=commit)
            return result

        except Exception:
            if commit:
                self.rollback()
            raise

    def deprecate_missing_system_definitions(
        self,
        dataset_key: Any,
        *,
        existing_keys: Iterable[str],
        commit: bool = False,
    ) -> int:
        """Marks system definitions missing from a seed payload as deprecated."""
        key = clean_dataset_key(dataset_key)
        existing = {clean_string(value).lower() for value in existing_keys if clean_string(value)}
        model = self.model_for_dataset(key)
        key_column = getattr(model, self.key_column_for_dataset(key), getattr(model, "definition_key"))

        query = self.session.query(model)

        if hasattr(model, "owner_scope"):
            query = query.filter(model.owner_scope == SYSTEM_SCOPE)

        if hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        count = 0

        try:
            for definition in query.all():
                current_key = clean_string(getattr(definition, self.key_column_for_dataset(key), None)).lower()

                if not current_key or current_key in existing:
                    continue

                definition.status = STATUS_DEPRECATED
                definition.active = False

                if hasattr(definition, "visible"):
                    definition.visible = False

                if hasattr(definition, "touch") and callable(definition.touch):
                    definition.touch()

                count += 1

            self._finish_write(commit=commit)
            return count

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Overrides
    # ------------------------------------------------------------------

    def list_overrides(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        dataset_key: Any | None = None,
        target_key: Any | None = None,
        active_only: bool = True,
        include_deleted: bool = False,
    ) -> list[Any]:
        """Lists user definition overrides."""
        model = self.models.LibraryDefinitionOverride
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)

        query = self.session.query(model).filter(model.user_id == normalized_user_id)

        if dataset_key:
            query = query.filter(model.dataset_key == clean_dataset_key(dataset_key))

        if target_key:
            query = query.filter(model.target_key == clean_string(target_key).lower())

        if active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        if not include_deleted and hasattr(model, "status"):
            query = query.filter(model.status != STATUS_DELETED)

        query = query.order_by(model.dataset_key.asc(), model.target_key.asc(), model.id.asc())
        return query.all()

    def list_override_payloads(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        dataset_key: Any | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """Lists overrides as dictionaries."""
        return [
            to_dict_or_payload(override)
            for override in self.list_overrides(
                user_id=user_id,
                dataset_key=dataset_key,
                active_only=active_only,
            )
        ]

    def get_override(
        self,
        *,
        user_id: Any,
        dataset_key: Any,
        target_key: Any,
        active_only: bool = True,
        for_update: bool = False,
    ) -> Any | None:
        """Gets one override by unique user/dataset/target."""
        model = self.models.LibraryDefinitionOverride

        query = (
            self.session.query(model)
            .filter(model.user_id == normalize_user_id(user_id, default=DEFAULT_USER_ID))
            .filter(model.dataset_key == clean_dataset_key(dataset_key))
            .filter(model.target_key == clean_string(target_key).lower())
        )

        if active_only and hasattr(model, "active"):
            query = query.filter(model.active.is_(True))

        if for_update:
            try:
                query = query.with_for_update()
            except Exception:
                pass

        return query.one_or_none()

    def upsert_override(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
        created_by_user_id: Any = None,
        updated_by_user_id: Any = None,
        commit: bool = False,
    ) -> tuple[Any, bool]:
        """
        Creates or updates a user override.

        Returns:
            (override, created)
        """
        data = normalize_json_mapping(payload)
        dataset_key = clean_dataset_key(data.get("dataset_key") or data.get("dataset"))
        target_key = clean_string(data.get("target_key") or data.get("definition_key") or data.get("key")).lower()

        if not target_key:
            raise ValueError("target_key is required for definition override.")

        normalized_user_id = normalize_user_id(user_id or data.get("user_id"), default=DEFAULT_USER_ID)

        try:
            override = self.get_override(
                user_id=normalized_user_id,
                dataset_key=dataset_key,
                target_key=target_key,
                active_only=False,
                for_update=True,
            )
            created = override is None

            if created:
                override = self.models.LibraryDefinitionOverride.create_from_payload(
                    {
                        **data,
                        "dataset_key": dataset_key,
                        "target_key": target_key,
                        "user_id": normalized_user_id,
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=created_by_user_id,
                )
                self.session.add(override)
            else:
                incoming = self.models.LibraryDefinitionOverride.create_from_payload(
                    {
                        **data,
                        "dataset_key": dataset_key,
                        "target_key": target_key,
                        "user_id": normalized_user_id,
                    },
                    user_id=normalized_user_id,
                    created_by_user_id=created_by_user_id,
                )

                for field_name in (
                    "target_definition_uid",
                    "target_type",
                    "override_action",
                    "status",
                    "active",
                    "visible_override",
                    "active_override",
                    "label_override",
                    "description_override",
                    "sort_order_override",
                    "payload_patch",
                    "value_override_json",
                    "before_json",
                    "after_json",
                    "meta",
                    "metadata_json",
                ):
                    if hasattr(override, field_name) and hasattr(incoming, field_name):
                        setattr(override, field_name, getattr(incoming, field_name))

                updater_id = normalize_user_id(updated_by_user_id, default=None)
                if updater_id is not None and hasattr(override, "updated_by_user_id"):
                    override.updated_by_user_id = updater_id

                if hasattr(override, "touch") and callable(override.touch):
                    override.touch()

            self._finish_write(commit=commit)
            return override, created

        except Exception:
            if commit:
                self.rollback()
            raise

    def soft_delete_override(
        self,
        *,
        user_id: Any,
        dataset_key: Any,
        target_key: Any,
        commit: bool = False,
    ) -> bool:
        """Soft-deletes a user override."""
        override = self.get_override(
            user_id=user_id,
            dataset_key=dataset_key,
            target_key=target_key,
            active_only=False,
            for_update=True,
        )

        if override is None:
            return False

        try:
            if hasattr(override, "mark_deleted") and callable(override.mark_deleted):
                override.mark_deleted(user_id=user_id)
            else:
                override.active = False
                override.status = STATUS_DELETED

            self._finish_write(commit=commit)
            return True

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Current catalog / resolved helpers
    # ------------------------------------------------------------------

    def get_current_catalog(
        self,
        *,
        user_id: Any = None,
        include_overrides: bool = True,
        include_inactive: bool = False,
        include_deleted: bool = False,
    ) -> dict[str, Any]:
        """
        Builds the raw current catalog payload.

        This method performs a simple dataset-by-dataset read and attaches user
        overrides. Deeper create-context resolution is handled by the catalog
        service.
        """
        normalized_user_id = normalize_user_id(user_id, default=None)
        catalog: dict[str, Any] = {
            "schema_version": LIBRARY_DEFINITION_REPOSITORY_VERSION,
            "user_id": normalized_user_id,
            "datasets": {},
            "overrides": {},
        }

        for dataset_key in self.list_dataset_keys():
            catalog["datasets"][dataset_key] = self.list_definition_payloads(
                dataset_key,
                user_id=normalized_user_id,
                include_system=True,
                include_user=normalized_user_id is not None,
                include_inactive=include_inactive,
                include_deleted=include_deleted,
            )

            if include_overrides and normalized_user_id is not None:
                catalog["overrides"][dataset_key] = self.list_override_payloads(
                    user_id=normalized_user_id,
                    dataset_key=dataset_key,
                    active_only=not include_deleted,
                )

        return catalog

    def get_resolved_dataset_payload(
        self,
        dataset_key: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Returns a simple resolved dataset.

        Merge rule:
            system definitions
              + user definitions with same key override system
              + active user overrides patch/hide/rename/reorder
        """
        key = clean_dataset_key(dataset_key)
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)

        system_values = self.list_definition_payloads(
            key,
            include_system=True,
            include_user=False,
            include_inactive=include_inactive,
        )
        user_values = self.list_definition_payloads(
            key,
            user_id=normalized_user_id,
            include_system=False,
            include_user=True,
            include_inactive=include_inactive,
        )
        overrides = self.list_override_payloads(
            user_id=normalized_user_id,
            dataset_key=key,
            active_only=True,
        )

        by_key: dict[str, dict[str, Any]] = {}

        for value in system_values:
            definition_key = self._payload_definition_key(key, value)
            if definition_key:
                by_key[definition_key] = dict(value)

        for value in user_values:
            definition_key = self._payload_definition_key(key, value)
            if definition_key:
                by_key[definition_key] = dict(value)

        for override in overrides:
            target_key = clean_string(override.get("target_key")).lower()
            if not target_key or target_key not in by_key:
                continue

            by_key[target_key] = self.apply_override_payload(by_key[target_key], override)

        values = [
            value
            for value in by_key.values()
            if include_inactive or normalize_bool(value.get("active"), default=True)
        ]

        values.sort(key=lambda item: (normalize_int(item.get("sort_order"), default=0) or 0, clean_string(item.get("label") or item.get("definition_key"))))
        return values

    def apply_override_payload(
        self,
        definition_payload: Mapping[str, Any],
        override_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Applies a lightweight override payload to a definition payload."""
        result = normalize_json_mapping(definition_payload)
        override = normalize_json_mapping(override_payload)

        if not override or not normalize_bool(override.get("active"), default=True):
            return result

        action = clean_string(override.get("override_action") or override.get("action")).lower()

        if action == "hide":
            result["visible"] = False
            result["hidden_by_override"] = True

        if action == "restore":
            result["visible"] = True
            result["hidden_by_override"] = False

        if override.get("visible_override") is not None:
            result["visible"] = normalize_bool(override.get("visible_override"), default=result.get("visible", True))

        if override.get("active_override") is not None:
            result["active"] = normalize_bool(override.get("active_override"), default=result.get("active", True))

        for source_key, target_key in (
            ("label_override", "label"),
            ("description_override", "description"),
            ("sort_order_override", "sort_order"),
        ):
            if override.get(source_key) is not None:
                result[target_key] = override[source_key]

        patch = normalize_json_mapping(override.get("payload_patch"))
        if patch:
            result["payload"] = {
                **normalize_json_mapping(result.get("payload")),
                **patch,
            }

        result["override"] = override
        return result

    # ------------------------------------------------------------------
    # Profile binding lookup
    # ------------------------------------------------------------------

    def find_profile_binding(
        self,
        *,
        user_id: Any = None,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        object_kind: Any = None,
        include_inactive: bool = False,
    ) -> dict[str, Any] | None:
        """
        Finds the best profile binding as dictionary.

        Matching is tolerant:
        - exact object_kind/domain/category/subcategory wins
        - missing fields in binding are treated as wildcard
        - lower priority value wins
        """
        bindings = self.list_profile_bindings(
            user_id=user_id,
            as_dict=True,
        )

        normalized_context = {
            "domain": optional_string(domain),
            "category": optional_string(category),
            "subcategory": optional_string(subcategory),
            "object_kind": optional_string(object_kind),
        }

        candidates: list[tuple[int, int, dict[str, Any]]] = []

        for binding in bindings:
            if not include_inactive and not normalize_bool(binding.get("active"), default=True):
                continue

            if not self._binding_matches(binding, normalized_context):
                continue

            specificity = sum(
                1
                for field_name in ("domain", "category", "subcategory", "object_kind")
                if binding.get(field_name)
            )
            priority = normalize_int(binding.get("priority"), default=1000, minimum=0) or 1000
            candidates.append((priority, -specificity, binding))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))
        return candidates[0][2]

    # ------------------------------------------------------------------
    # Seed run support
    # ------------------------------------------------------------------

    def start_seed_run(
        self,
        *,
        source_label: Any = None,
        source_root: Any = None,
        triggered_by: Any = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
        metadata: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Creates a seed run row."""
        model = self.models.LibraryDefinitionSeedRun

        try:
            seed_run = model.start(
                source_label=source_label,
                source_root=source_root,
                triggered_by=triggered_by,
                definitions_version=definitions_version,
                metadata=metadata,
            )
            self.session.add(seed_run)
            self._finish_write(commit=commit)
            return seed_run

        except Exception:
            if commit:
                self.rollback()
            raise

    def finish_seed_run(
        self,
        seed_run: Any,
        *,
        status: Any = "completed",
        summary: Mapping[str, Any] | None = None,
        errors: Iterable[Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Finishes a seed run row."""
        try:
            seed_run.finish(status=status, summary=summary, errors=errors)
            self._finish_write(commit=commit)
            return seed_run

        except Exception:
            if commit:
                self.rollback()
            raise

    def apply_seed_run_counts(
        self,
        seed_run: Any,
        *,
        counts: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> Any:
        """Applies counts to a seed run row."""
        try:
            seed_run.apply_counts(counts)
            self._finish_write(commit=commit)
            return seed_run

        except Exception:
            if commit:
                self.rollback()
            raise

    # ------------------------------------------------------------------
    # Health / diagnostics
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns repository health snapshot without querying live DB connection explicitly."""
        model_health = {}

        try:
            candidate = getattr(self.models, "get_library_definition_models_health", None)
            if callable(candidate):
                model_health = candidate()
        except Exception as exc:
            model_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        return {
            "schema_version": LIBRARY_DEFINITION_REPOSITORY_VERSION,
            "ok": True,
            "repository": type(self).__name__,
            "dataset_keys": list(self.list_dataset_keys()),
            "dataset_model_names": dict(_DATASET_MODEL_NAME_MAP),
            "dataset_key_columns": dict(_DATASET_KEY_COLUMN_MAP),
            "has_session": self._session is not None,
            "uses_default_db_session": self._session is None,
            "models_health": model_health,
            "supports_datasets": True,
            "supports_seed_runs": True,
            "supports_definition_upserts": True,
            "supports_definition_overrides": True,
            "supports_current_catalog": True,
            "supports_profile_binding_lookup": True,
        }

    # ------------------------------------------------------------------
    # Internal query helpers
    # ------------------------------------------------------------------

    def _apply_definition_sort(self, query: Any, model: type[Any]) -> Any:
        """Applies stable ordering to definition queries."""
        order_fields = []

        for field_name in ("sort_order", "label", "definition_key", "id"):
            column = getattr(model, field_name, None)
            if column is not None:
                try:
                    order_fields.append(column.asc())
                except Exception:
                    pass

        if order_fields:
            try:
                return query.order_by(*order_fields)
            except Exception:
                return query

        return query

    def _payload_definition_key(self, dataset_key: Any, payload: Mapping[str, Any]) -> str | None:
        """Gets definition key from serialized payload."""
        key = clean_dataset_key(dataset_key)
        data = normalize_json_mapping(payload)
        column_name = self.key_column_for_dataset(key)

        for field_name in (column_name, "definition_key", "key", "id"):
            value = data.get(field_name)
            if value is not None and str(value).strip():
                return str(value).strip().lower()

        return None

    def _binding_matches(self, binding: Mapping[str, Any], context: Mapping[str, Any]) -> bool:
        """Checks whether a binding matches a create context."""
        for field_name in ("domain", "category", "subcategory", "object_kind"):
            expected = optional_string(binding.get(field_name))
            actual = optional_string(context.get(field_name))

            if expected is None:
                continue

            if expected != actual:
                return False

        return True


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_definition_repository(session: Any | None = None) -> LibraryDefinitionRepository:
    """Factory for dependency injection."""
    return LibraryDefinitionRepository(session=session)


@lru_cache(maxsize=1)
def get_repository_version() -> str:
    """Cached repository version helper."""
    return LIBRARY_DEFINITION_REPOSITORY_VERSION


def clear_library_definition_repository_caches() -> dict[str, Any]:
    """Clears import/static caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _load_definition_models_module,
        get_repository_version,
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
    "LIBRARY_DEFINITION_REPOSITORY_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_DEFINITIONS_VERSION",
    "DATASET_VARIABLES",
    "DATASET_UNITS",
    "DATASET_MATERIALS",
    "DATASET_DOCUMENT_TYPES",
    "DATASET_OBJECT_KINDS",
    "DATASET_FAMILY_PROFILES",
    "DATASET_VARIANT_PROFILES",
    "DATASET_PROFILE_BINDINGS",
    "DATASET_KEYS",
    "SYSTEM_SCOPE",
    "USER_SCOPE",
    "STATUS_ACTIVE",
    "STATUS_DEPRECATED",
    "STATUS_DELETED",

    # Exceptions
    "LibraryDefinitionRepositoryError",
    "LibraryDefinitionRepositoryImportError",
    "LibraryDefinitionNotFoundError",
    "LibraryDefinitionConflictError",

    # Dataclasses
    "DefinitionQuery",
    "DefinitionBulkUpsertResult",

    # Repository
    "LibraryDefinitionRepository",
    "create_library_definition_repository",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_int",
    "normalize_user_id",
    "normalize_bool",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "clean_dataset_key",
    "owner_scope_for",
    "definition_key_from_item",
    "item_list_from_dataset_payload",
    "to_dict_or_payload",
    "get_repository_version",
    "clear_library_definition_repository_caches",
]