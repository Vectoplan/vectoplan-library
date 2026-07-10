# services/vectoplan-library/src/library/services/library_definition_catalog_service.py
"""
Service for VECTOPLAN Library Definition Catalog.

Diese Datei baut API-fähige Definition-Payloads aus zwei kontrollierten Quellen:

1. PostgreSQL über LibraryDefinitionRepository
2. JSON-Definitionsregistry als read-only Baseline und Ausfallsicherung

Die Datenbank behält Vorrang. Fehlende oder vorübergehend nicht erreichbare
Definitionen werden aus der Registry ergänzt. Dadurch bleibt insbesondere der
Create-Flow für ``simple_cell_block.v1`` funktionsfähig, bevor oder während der
Definitionskatalog geseedet wird.

Der Service liefert:

- Current Catalog
- Dataset Payloads
- Variables nach profile_id
- resolved Variant Profiles
- resolved Family Profiles
- resolved Create Context
- Profile Binding Auflösung
- Sections + vollständige Variable-Definitionen
- Upload Constraints aus document_types
- Defaults / Required / Optional / Summary Fields

Ziel:

    LibraryDefinitionRepository -----+
                                     |
    DefinitionRegistry --------------+-> LibraryDefinitionCatalogService
                                           -> routes/library_definition_routes.py
                                           -> Create UI / Variant Drawer
                                           -> Upload Fields / Generator / Download

Architekturregeln:

- Service enthält keine Flask-Route.
- Service enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über LibraryDefinitionRepository.
- Flask-SQLAlchemy-Repositories werden nur in aktivem App-Kontext aufgerufen.
- Außerhalb des App-Kontexts wird ohne Stacktrace auf die Registry zurückgefallen.
- Registry-Zugriffe laufen über definition_registry.py.
- Identische Definitionen werden dataset-spezifisch und deterministisch dedupliziert.
- Der Service schreibt standardmäßig nichts.
- Registry-Daten sind Baseline; DB- und User-Werte haben Vorrang.
- User-Änderungen/Overrides werden im Repository gelesen, hier nur aufgelöst.
- Create Context ist ein reines Payload-Produkt für UI/Generator.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Fokus ist read-only Catalog/API.
- Seed-Logik liegt später in library_definition_seed_service.py.
"""

from __future__ import annotations

import copy
import importlib
import json
import logging
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION: Final[str] = "vectoplan_library.service.library_definition_catalog.v2"

DEFAULT_USER_ID: Final[int] = 1

DATASET_VARIABLES: Final[str] = "variables"
DATASET_UNITS: Final[str] = "units"
DATASET_MATERIALS: Final[str] = "materials"
DATASET_DOCUMENT_TYPES: Final[str] = "document_types"
DATASET_OBJECT_KINDS: Final[str] = "object_kinds"
DATASET_FAMILY_PROFILES: Final[str] = "family_profiles"
DATASET_VARIANT_PROFILES: Final[str] = "variant_profiles"
DATASET_PROFILE_BINDINGS: Final[str] = "profile_bindings"

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

DEFAULT_SOURCE: Final[str] = "db"
REGISTRY_SOURCE: Final[str] = "registry"
MERGED_SOURCE: Final[str] = "db+registry"
DEFAULT_SCOPE: Final[str] = "resolved"

STARTER_VARIANT_PROFILE_ID: Final[str] = "simple_cell_block.v1"
STARTER_FAMILY_PROFILE_ID: Final[str] = "simple_cell_block"
STARTER_OBJECT_KIND: Final[str] = "cell_block"

DEFAULT_REGISTRY_CACHE_TTL_SECONDS: Final[float] = 30.0
DEFAULT_REPOSITORY_ERROR_LOG_TTL_SECONDS: Final[float] = 60.0
MAX_REPOSITORY_ERROR_HISTORY: Final[int] = 20
MAX_REPOSITORY_ERROR_SIGNATURES: Final[int] = 64
MAX_OPERATION_CACHE_ENTRIES: Final[int] = 128

REPOSITORY_CONTEXT_SKIPPED: Final[str] = "repository_skipped_no_application_context"

_REGISTRY_LIST_METHODS: Final[Mapping[str, str]] = {
    DATASET_VARIABLES: "list_variables",
    DATASET_UNITS: "list_units",
    DATASET_MATERIALS: "list_materials",
    DATASET_DOCUMENT_TYPES: "list_document_types",
    DATASET_OBJECT_KINDS: "list_object_kinds",
    DATASET_FAMILY_PROFILES: "list_family_profiles",
    DATASET_VARIANT_PROFILES: "list_variant_profiles",
    DATASET_PROFILE_BINDINGS: "list_profile_bindings",
}

_REGISTRY_GET_METHODS: Final[Mapping[str, str]] = {
    DATASET_VARIABLES: "get_variable",
    DATASET_UNITS: "get_unit",
    DATASET_MATERIALS: "get_material",
    DATASET_DOCUMENT_TYPES: "get_document_type",
    DATASET_OBJECT_KINDS: "get_object_kind",
    DATASET_FAMILY_PROFILES: "get_family_profile",
    DATASET_VARIANT_PROFILES: "get_variant_profile",
    DATASET_PROFILE_BINDINGS: "get_profile_binding",
}

_LOGGER = logging.getLogger(__name__)
_SERVICE_INSTANCES_LOCK = threading.RLock()
_SERVICE_INSTANCES: "weakref.WeakSet[LibraryDefinitionCatalogService]" = weakref.WeakSet()

DOCUMENT_VALUE_TYPES: Final[tuple[str, ...]] = (
    "document_list",
    "file",
    "file_list",
)

WILDCARD_PROFILE_IDS: Final[tuple[str, ...]] = (
    "all",
    "*",
    "__all__",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryDefinitionCatalogServiceError(RuntimeError):
    """Base error for LibraryDefinitionCatalogService."""


class LibraryDefinitionCatalogImportError(LibraryDefinitionCatalogServiceError):
    """Raised when repository imports fail."""


class LibraryDefinitionCatalogRegistryError(LibraryDefinitionCatalogServiceError):
    """Raised when the JSON definitions registry cannot be accessed."""


class LibraryDefinitionCatalogNotFoundError(LibraryDefinitionCatalogServiceError):
    """Raised when a required definition cannot be resolved."""


class LibraryDefinitionCreateContextError(LibraryDefinitionCatalogServiceError):
    """Raised when create-context resolution fails."""


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> ModuleType:
    """Loads library_definition_repository defensively."""
    errors: list[str] = []

    for module_name in (
        "library.repositories.library_definition_repository",
        "src.library.repositories.library_definition_repository",
        "vectoplan_library.library.repositories.library_definition_repository",
        "vectoplan_library.src.library.repositories.library_definition_repository",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryDefinitionCatalogImportError(
        "Could not import library_definition_repository. "
        + " | ".join(errors)
    )


def _repo_module() -> ModuleType:
    """Short alias for lazy repository module."""
    return _load_repository_module()


@lru_cache(maxsize=1)
def _load_registry_module() -> ModuleType:
    """Loads definition_registry defensively without creating import cycles."""
    errors: list[str] = []

    for module_name in (
        "library.definitions.definition_registry",
        "src.library.definitions.definition_registry",
        "vectoplan_library.library.definitions.definition_registry",
        "vectoplan_library.src.library.definitions.definition_registry",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise LibraryDefinitionCatalogRegistryError(
        "Could not import definition_registry. " + " | ".join(errors)
    )


def _registry_module() -> ModuleType:
    """Short alias for the lazy registry module."""
    return _load_registry_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_string(value: Any, *, fallback: str = "") -> str:
    """Converts a value to safe stripped string."""
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

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "required"}:
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


def clean_dataset_key(dataset_key: Any) -> str:
    """
    Normalizes a dataset key.

    Repository normalization is preferred when the repository module is
    importable. Import errors are intentionally swallowed here so registry-only
    fallback remains operational during DB/bootstrap failures.
    """
    try:
        helper = getattr(_repo_module(), "clean_dataset_key", None)
    except Exception:
        helper = None

    if callable(helper):
        try:
            return str(helper(dataset_key))
        except Exception:
            _LOGGER.exception(
                "Repository dataset-key normalization failed; "
                "using local normalization."
            )

    return clean_string(dataset_key).lower().replace("-", "_").replace(" ", "_")


def first_non_empty(*values: Any) -> Any:
    """Returns first non-empty value."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def dedupe_strings(values: Iterable[Any]) -> list[str]:
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


def get_payload_key(payload: Mapping[str, Any], *field_names: str) -> str | None:
    """Gets first non-empty key from payload fields."""
    data = normalize_json_mapping(payload)

    for field_name in field_names:
        value = optional_string(data.get(field_name))
        if value:
            return value

    return None


def get_definition_key(dataset_key: Any, payload: Mapping[str, Any]) -> str | None:
    """Gets dataset-specific definition key from a serialized payload."""
    key = clean_dataset_key(dataset_key)
    data = normalize_json_mapping(payload)

    field_names_by_dataset = {
        DATASET_VARIABLES: ("variable_key", "definition_key", "key", "id"),
        DATASET_UNITS: ("unit_id", "definition_key", "id", "key"),
        DATASET_MATERIALS: ("material_id", "definition_key", "id", "key"),
        DATASET_DOCUMENT_TYPES: ("document_type_id", "definition_key", "id", "key"),
        DATASET_OBJECT_KINDS: ("object_kind_id", "definition_key", "id", "key"),
        DATASET_FAMILY_PROFILES: ("family_profile_id", "definition_key", "id", "key"),
        DATASET_VARIANT_PROFILES: ("variant_profile_id", "definition_key", "id", "key"),
        DATASET_PROFILE_BINDINGS: ("binding_id", "definition_key", "id", "key"),
    }

    return get_payload_key(data, *field_names_by_dataset.get(key, ("definition_key", "key", "id")))


def index_payloads_by_key(dataset_key: Any, values: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Indexes deduplicated definitions by their dataset-specific technical key."""
    result: dict[str, dict[str, Any]] = {}

    for payload in dedupe_definition_payloads(dataset_key, values):
        key = get_definition_key(dataset_key, payload)
        if not key:
            continue

        result[key] = payload
        folded = clean_string(key).casefold()
        if folded and folded != key:
            result.setdefault(folded, payload)

    return result


def index_payloads_by_any_key(
    values: Iterable[Mapping[str, Any]],
    *,
    keys: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Indexes payloads by multiple possible fields."""
    result: dict[str, dict[str, Any]] = {}

    for value in values or ():
        payload = normalize_json_mapping(value)

        for key_name in keys:
            key_value = optional_string(payload.get(key_name))
            if key_value:
                result[key_value] = payload

    return result


def profile_matches_applies_to(variable: Mapping[str, Any], profile_id: Any) -> bool:
    """Checks whether a variable applies to a profile."""
    if not profile_id:
        return True

    profile = clean_string(profile_id)
    applies_to = {clean_string(item) for item in normalize_json_list(variable.get("applies_to"))}

    if not applies_to:
        return True

    if applies_to.intersection(WILDCARD_PROFILE_IDS):
        return True

    return profile in applies_to


def is_document_variable(variable: Mapping[str, Any]) -> bool:
    """Checks whether variable represents a file/document upload."""
    value_type = clean_string(variable.get("value_type")).lower()
    metadata = normalize_json_mapping(variable.get("metadata") or variable.get("meta"))

    if value_type in DOCUMENT_VALUE_TYPES:
        return True

    if metadata.get("document_type"):
        return True

    if variable.get("document_type"):
        return True

    return False


def extract_document_type_id(variable: Mapping[str, Any]) -> str | None:
    """Extracts document_type from variable payload."""
    metadata = normalize_json_mapping(variable.get("metadata") or variable.get("meta"))

    return optional_string(
        first_non_empty(
            variable.get("document_type"),
            metadata.get("document_type"),
            metadata.get("documentType"),
        )
    )


def normalize_field_entry(field: Any) -> dict[str, Any]:
    """Normalizes section field entries."""
    if isinstance(field, Mapping):
        data = normalize_json_mapping(field)
        field_key = optional_string(
            first_non_empty(
                data.get("field_key"),
                data.get("key"),
                data.get("id"),
                data.get("variable_key"),
            )
        )
        data["field_key"] = field_key
        return data

    field_key = optional_string(field)
    return {
        "field_key": field_key,
        "key": field_key,
    }


def has_flask_application_context() -> bool:
    """
    Returns whether a Flask application context is active.

    A missing Flask runtime means no Flask application context is available.
    Framework-independent injected repositories bypass this helper by setting
    ``repository_requires_app_context=False``.
    """
    try:
        from flask import has_app_context
    except Exception:
        return False

    try:
        return bool(has_app_context())
    except Exception:
        return False


def is_application_context_error(exc: BaseException | None) -> bool:
    """Detects Flask/SQLAlchemy context failures without importing internals."""
    if exc is None:
        return False

    try:
        text = f"{type(exc).__name__}: {exc}".casefold()
    except Exception:
        return False

    return any(
        token in text
        for token in (
            "working outside of application context",
            "working outside of request context",
            "no application found",
            "application context",
            "_app_ctx_id",
        )
    )


def normalize_definition_identity(dataset_key: Any, payload: Mapping[str, Any]) -> str | None:
    """Returns a case-insensitive, dataset-specific technical identity."""
    key = get_definition_key(dataset_key, payload)
    if not key:
        return None

    normalized = clean_string(key).casefold()
    return normalized or None


def _semantic_payload_value(value: Any) -> Any:
    """Builds a stable JSON-compatible representation for semantic comparisons."""
    if isinstance(value, Mapping):
        ignored_keys = {
            "catalog_source",
            "repository_error",
            "source_details",
            "loaded_at",
            "resolved_at",
            "created_at",
            "updated_at",
        }
        return {
            str(key): _semantic_payload_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key) not in ignored_keys
        }

    if isinstance(value, (list, tuple)):
        return [_semantic_payload_value(item) for item in value]

    if isinstance(value, set):
        normalized_items = [_semantic_payload_value(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str),
        )

    return normalize_json_value(value)


def semantic_payload_fingerprint(payload: Mapping[str, Any]) -> str:
    """Returns a deterministic semantic fingerprint without volatile metadata."""
    try:
        normalized = _semantic_payload_value(payload)
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        try:
            return repr(normalize_json_mapping(payload))
        except Exception:
            return repr(payload)


def _payload_information_score(value: Any) -> int:
    """Scores payload richness for deterministic duplicate reconciliation."""
    if value is None:
        return 0

    if isinstance(value, str):
        return 0 if not value.strip() else min(len(value.strip()), 128)

    if isinstance(value, (int, float, bool)):
        return 1

    if isinstance(value, Mapping):
        score = 0
        for child in value.values():
            child_score = _payload_information_score(child)
            if child_score > 0:
                score += 1 + child_score
        return score

    if isinstance(value, (list, tuple, set)):
        return sum(1 + _payload_information_score(item) for item in value)

    return 1


def merge_definition_payloads(
    existing: Mapping[str, Any],
    incoming: Mapping[str, Any],
    *,
    prefer_incoming: bool,
) -> dict[str, Any]:
    """
    Reconciles duplicate definitions deterministically.

    Repository values always take precedence over registry values. Duplicates from
    the same source keep the richer payload, while missing fields are filled from
    the other payload. Lists named ``aliases`` are unioned in stable order.
    """
    left = normalize_json_mapping(existing)
    right = normalize_json_mapping(incoming)

    if prefer_incoming:
        primary = right
        secondary = left
    else:
        left_score = _payload_information_score(left)
        right_score = _payload_information_score(right)
        primary, secondary = (right, left) if right_score > left_score else (left, right)

    result = copy.deepcopy(primary)

    for key, value in secondary.items():
        if key not in result or result.get(key) in (None, "", [], {}):
            result[key] = copy.deepcopy(value)
            continue

        if key in {"aliases", "alias"}:
            current = normalize_json_list(result.get(key))
            extra = normalize_json_list(value)
            result[key] = dedupe_strings([*current, *extra])
            continue

        if isinstance(result.get(key), Mapping) and isinstance(value, Mapping):
            nested = normalize_json_mapping(result.get(key))
            for nested_key, nested_value in normalize_json_mapping(value).items():
                if nested_key not in nested or nested.get(nested_key) in (None, "", [], {}):
                    nested[nested_key] = copy.deepcopy(nested_value)
            result[key] = nested

    return result


def dedupe_definition_payloads(
    dataset_key: Any,
    values: Iterable[Mapping[str, Any]],
    *,
    prefer_incoming_duplicates: bool = False,
) -> list[dict[str, Any]]:
    """
    Deduplicates definitions by technical identity and semantic fingerprint.

    Items without a technical key are retained once per semantic fingerprint.
    Order remains stable.
    """
    result: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    unkeyed_fingerprints: set[str] = set()

    for raw_value in values or ():
        if not isinstance(raw_value, Mapping):
            continue

        payload = normalize_json_mapping(raw_value)
        identity = normalize_definition_identity(dataset_key, payload)

        if identity:
            if identity in positions:
                position = positions[identity]
                result[position] = merge_definition_payloads(
                    result[position],
                    payload,
                    prefer_incoming=prefer_incoming_duplicates,
                )
                continue

            positions[identity] = len(result)
            result.append(payload)
            continue

        fingerprint = semantic_payload_fingerprint(payload)
        if fingerprint in unkeyed_fingerprints:
            continue

        unkeyed_fingerprints.add(fingerprint)
        result.append(payload)

    return result


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CreateContextQuery:
    """Input for create-context resolution."""

    user_id: int | None = DEFAULT_USER_ID
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    object_kind: str | None = None
    family_profile_id: str | None = None
    variant_profile_id: str | None = None
    include_catalog: bool = False
    include_variables: bool = True
    include_upload_constraints: bool = True
    include_materials: bool = True
    include_units: bool = True

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "CreateContextQuery":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        return cls(
            user_id=normalize_user_id(data.get("user_id"), default=DEFAULT_USER_ID),
            domain=optional_string(data.get("domain")),
            category=optional_string(data.get("category")),
            subcategory=optional_string(data.get("subcategory")),
            object_kind=optional_string(data.get("object_kind") or data.get("objectKind")),
            family_profile_id=optional_string(data.get("family_profile_id") or data.get("familyProfileId")),
            variant_profile_id=optional_string(data.get("variant_profile_id") or data.get("variantProfileId")),
            include_catalog=normalize_bool(data.get("include_catalog"), default=False),
            include_variables=normalize_bool(data.get("include_variables"), default=True),
            include_upload_constraints=normalize_bool(data.get("include_upload_constraints"), default=True),
            include_materials=normalize_bool(data.get("include_materials"), default=True),
            include_units=normalize_bool(data.get("include_units"), default=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "object_kind": self.object_kind,
            "family_profile_id": self.family_profile_id,
            "variant_profile_id": self.variant_profile_id,
            "include_catalog": self.include_catalog,
            "include_variables": self.include_variables,
            "include_upload_constraints": self.include_upload_constraints,
            "include_materials": self.include_materials,
            "include_units": self.include_units,
        }


@dataclass(slots=True)
class ServiceHealth:
    """Health payload for the DB-plus-registry catalog service."""

    ok: bool
    healthy: bool
    ready: bool
    status: str
    repository_health: dict[str, Any] = field(default_factory=dict)
    registry_health: dict[str, Any] = field(default_factory=dict)
    starter_profile_available: bool = False
    repository_error: str | None = None
    registry_error: str | None = None
    repository_context_available: bool = False
    repository_requires_app_context: bool = True
    repository_call_count: int = 0
    repository_success_count: int = 0
    repository_skip_count: int = 0
    repository_error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "ok": self.ok,
            "healthy": self.healthy,
            "ready": self.ready,
            "status": self.status,
            "source": MERGED_SOURCE,
            "starter_profile": {
                "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
                "family_profile_id": STARTER_FAMILY_PROFILE_ID,
                "object_kind": STARTER_OBJECT_KIND,
                "available": self.starter_profile_available,
            },
            "repository_health": normalize_json_mapping(self.repository_health),
            "registry_health": normalize_json_mapping(self.registry_health),
            "repository_error": self.repository_error,
            "registry_error": self.registry_error,
            "repository_runtime": {
                "context_available": self.repository_context_available,
                "requires_app_context": self.repository_requires_app_context,
                "call_count": self.repository_call_count,
                "success_count": self.repository_success_count,
                "skip_count": self.repository_skip_count,
                "error_count": self.repository_error_count,
            },
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LibraryDefinitionCatalogService:
    """
    High-level service for API-ready Library Definition Catalog payloads.

    Source order:
    1. Repository / PostgreSQL, including resolved user overrides.
    2. JSON registry as immutable baseline and read-only fallback.

    Repository values are never cached across independent public operations because
    user overrides and freshly seeded DB values must become visible immediately.
    A short-lived operation cache only deduplicates identical reads inside one
    create-context/catalog build. Serialized registry data is cached by generation.

    Default repositories are treated as Flask-SQLAlchemy dependencies and therefore
    are called only while an application context is active. Injected repositories
    remain framework-independent unless ``repository_requires_app_context`` is set.
    """

    def __init__(
        self,
        repository: Any | None = None,
        *,
        registry: Any | None = None,
        allow_registry_fallback: bool = True,
        registry_cache_ttl_seconds: float = DEFAULT_REGISTRY_CACHE_TTL_SECONDS,
        repository_requires_app_context: bool | None = None,
        repository_error_log_ttl_seconds: float = DEFAULT_REPOSITORY_ERROR_LOG_TTL_SECONDS,
        operation_cache_enabled: bool = True,
    ) -> None:
        self.allow_registry_fallback = bool(allow_registry_fallback)
        self._injected_registry = registry
        self._repository_was_injected = repository is not None
        self._repository_requires_app_context = (
            bool(repository_requires_app_context)
            if repository_requires_app_context is not None
            else not self._repository_was_injected
        )
        self._repository_error_log_ttl_seconds = self._normalize_error_log_ttl(
            repository_error_log_ttl_seconds
        )
        self._operation_cache_enabled = bool(operation_cache_enabled)

        self._repository_init_error: str | None = None
        self._registry_error: str | None = None
        self._repository_errors: list[str] = []
        self._repository_error_counts: dict[str, int] = {}
        self._repository_error_last_logged: dict[str, float] = {}
        self._repository_call_count = 0
        self._repository_success_count = 0
        self._repository_skip_count = 0
        self._repository_deferred = False
        self._repository_lock = threading.RLock()

        self._cache_lock = threading.RLock()
        self._registry_cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._registry_identity: int | None = None
        self._registry_cache_ttl_seconds = self._normalize_cache_ttl(
            registry_cache_ttl_seconds
        )
        self._operation_local = threading.local()

        if repository is not None:
            self.repository = repository
        elif self._repository_requires_app_context and not has_flask_application_context():
            # Defer construction during imports, Alembic autogeneration and prestart.
            self.repository = None
            self._repository_deferred = True
        else:
            try:
                self.repository = self._create_repository()
            except Exception as exc:
                self.repository = None
                self._repository_init_error = self._format_error(exc)
                self._log_once(
                    "repository_initialization",
                    logging.ERROR,
                    "Definition repository initialization failed; registry fallback will be used.",
                    exc=exc,
                )
                if not self.allow_registry_fallback:
                    raise

        with _SERVICE_INSTANCES_LOCK:
            _SERVICE_INSTANCES.add(self)

    # ------------------------------------------------------------------
    # Construction and source access
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_cache_ttl(value: Any) -> float:
        try:
            ttl = float(value)
        except Exception:
            return DEFAULT_REGISTRY_CACHE_TTL_SECONDS
        return max(0.0, min(ttl, 3600.0))

    @staticmethod
    def _format_error(exc: BaseException) -> str:
        return f"{type(exc).__name__}: {exc}"

    @staticmethod
    def _normalize_error_log_ttl(value: Any) -> float:
        try:
            ttl = float(value)
        except Exception:
            return DEFAULT_REPOSITORY_ERROR_LOG_TTL_SECONDS
        return max(0.0, min(ttl, 3600.0))

    def _log_once(
        self,
        signature: str,
        level: int,
        message: str,
        *,
        exc: BaseException | None = None,
    ) -> None:
        """Logs a repeated runtime failure at most once per configured TTL."""
        now = time.monotonic()
        normalized_signature = clean_string(signature, fallback="unknown")
        last_logged = self._repository_error_last_logged.get(
            normalized_signature,
            0.0,
        )

        if (
            self._repository_error_log_ttl_seconds > 0
            and last_logged > 0
            and now - last_logged < self._repository_error_log_ttl_seconds
        ):
            return

        self._repository_error_last_logged[normalized_signature] = now

        try:
            if exc is not None and level >= logging.ERROR:
                _LOGGER.log(
                    level,
                    message,
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
            elif exc is not None:
                _LOGGER.log(
                    level,
                    "%s (%s)",
                    message,
                    self._format_error(exc),
                )
            else:
                _LOGGER.log(level, message)
        except Exception:
            # Logging must never interrupt catalog resolution.
            return

        if len(self._repository_error_last_logged) > MAX_REPOSITORY_ERROR_SIGNATURES:
            oldest = sorted(
                self._repository_error_last_logged,
                key=self._repository_error_last_logged.get,
            )[: max(1, MAX_REPOSITORY_ERROR_SIGNATURES // 4)]
            for key in oldest:
                self._repository_error_last_logged.pop(key, None)

    def _repository_context_available(self) -> bool:
        if not self._repository_requires_app_context:
            return True
        return has_flask_application_context()

    @contextmanager
    def _operation_cache_scope(self):
        """
        Enables a thread-local, call-scoped cache.

        Nested scopes share one cache and the outermost scope clears it. This keeps
        repository data fresh across requests while avoiding repeated identical
        dataset reads during one create-context build.
        """
        if not self._operation_cache_enabled:
            yield
            return

        local = self._operation_local
        depth = int(getattr(local, "depth", 0) or 0)

        if depth == 0:
            local.cache = {}

        local.depth = depth + 1

        try:
            yield
        finally:
            next_depth = max(0, int(getattr(local, "depth", 1) or 1) - 1)
            local.depth = next_depth
            if next_depth == 0:
                local.cache = {}

    def _operation_cache_get(self, key: tuple[Any, ...]) -> Any | None:
        if not self._operation_cache_enabled:
            return None

        try:
            if int(getattr(self._operation_local, "depth", 0) or 0) <= 0:
                return None

            cache = getattr(self._operation_local, "cache", None)
            if not isinstance(cache, dict) or key not in cache:
                return None

            return copy.deepcopy(cache[key])
        except Exception:
            return None

    def _operation_cache_set(self, key: tuple[Any, ...], value: Any) -> None:
        if not self._operation_cache_enabled:
            return

        try:
            if int(getattr(self._operation_local, "depth", 0) or 0) <= 0:
                return

            cache = getattr(self._operation_local, "cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._operation_local.cache = cache

            cache[key] = copy.deepcopy(value)

            if len(cache) > MAX_OPERATION_CACHE_ENTRIES:
                first_key = next(iter(cache))
                cache.pop(first_key, None)
        except Exception:
            return

    def _create_repository(self) -> Any:
        repo_module = _repo_module()
        factory = getattr(repo_module, "create_library_definition_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(repo_module, "LibraryDefinitionRepository", None)
        if repo_class is None:
            raise LibraryDefinitionCatalogImportError(
                "LibraryDefinitionRepository class is not available."
            )

        return repo_class()

    def _ensure_repository(self) -> Any | None:
        """Lazily creates the default repository once an app context exists."""
        if self.repository is not None:
            return self.repository

        if not self._repository_deferred:
            return None

        if not self._repository_context_available():
            return None

        with self._repository_lock:
            if self.repository is not None:
                return self.repository

            try:
                self.repository = self._create_repository()
                self._repository_deferred = False
                self._repository_init_error = None
                return self.repository
            except Exception as exc:
                self._repository_deferred = False
                self._repository_init_error = self._format_error(exc)
                self._remember_repository_error(self._repository_init_error)
                self._log_once(
                    "repository_deferred_initialization",
                    logging.ERROR,
                    "Deferred definition repository initialization failed.",
                    exc=exc,
                )
                if not self.allow_registry_fallback:
                    raise
                return None

    def _get_registry(self) -> Any | None:
        if not self.allow_registry_fallback:
            return None

        try:
            if self._injected_registry is not None:
                registry = self._injected_registry
            else:
                module = _registry_module()
                getter = getattr(module, "get_definition_registry", None)
                if not callable(getter):
                    raise LibraryDefinitionCatalogRegistryError(
                        "definition_registry.get_definition_registry is not available."
                    )
                registry = getter()

            if registry is None:
                raise LibraryDefinitionCatalogRegistryError(
                    "Definition registry getter returned None."
                )

            identity = id(registry)
            with self._cache_lock:
                if self._registry_identity != identity:
                    self._registry_cache.clear()
                    self._registry_identity = identity

            self._registry_error = None
            return registry
        except Exception as exc:
            self._registry_error = self._format_error(exc)
            self._log_once(
                "registry_access",
                logging.ERROR,
                "Definition registry access failed.",
                exc=exc,
            )
            return None

    def _repository_call(
        self,
        method_name: str,
        *args: Any,
        default: Any = None,
        **kwargs: Any,
    ) -> tuple[bool, Any, str | None]:
        """
        Calls a repository method only when its runtime prerequisites are present.

        Default repositories are Flask-SQLAlchemy backed. During import, migration,
        prestart and standalone diagnostics there may be no application context; in
        that case the call is skipped before touching ``db.session`` and registry
        fallback continues without a traceback.
        """
        self._repository_call_count += 1

        if not self._repository_context_available():
            self._repository_skip_count += 1
            error = REPOSITORY_CONTEXT_SKIPPED
            self._remember_repository_error(error, count_as_error=False)

            if not self.allow_registry_fallback:
                raise LibraryDefinitionCatalogServiceError(error)

            return False, default, error

        repository = self._ensure_repository()

        if repository is None:
            error = self._repository_init_error or "Repository is unavailable."
            self._remember_repository_error(error)
            return False, default, error

        method = getattr(repository, method_name, None)
        if not callable(method):
            error = f"Repository method {method_name!r} is not available."
            self._remember_repository_error(error)
            self._log_once(
                f"repository_method_missing:{method_name}",
                logging.WARNING,
                error,
            )
            if not self.allow_registry_fallback:
                raise LibraryDefinitionCatalogServiceError(error)
            return False, default, error

        try:
            result = method(*args, **kwargs)
            self._repository_success_count += 1
            return True, result, None
        except Exception as exc:
            context_failure = is_application_context_error(exc)

            if context_failure:
                self._repository_skip_count += 1
                error = f"{method_name}: {REPOSITORY_CONTEXT_SKIPPED}"
                self._remember_repository_error(error, count_as_error=False)
                self._log_once(
                    f"repository_context:{method_name}",
                    logging.DEBUG,
                    (
                        f"Definition repository call {method_name!r} was skipped "
                        "because no Flask application context is active."
                    ),
                    exc=exc,
                )
            else:
                error = f"{method_name}: {self._format_error(exc)}"
                self._remember_repository_error(error)
                self._log_once(
                    f"repository_call:{method_name}:{type(exc).__name__}:{exc}",
                    logging.ERROR,
                    f"Definition repository call failed: {method_name}",
                    exc=exc,
                )

            if not self.allow_registry_fallback:
                raise LibraryDefinitionCatalogServiceError(error) from exc

            return False, default, error

    def _remember_repository_error(
        self,
        error: str,
        *,
        count_as_error: bool = True,
    ) -> None:
        normalized = clean_string(error)
        if not normalized:
            return

        if count_as_error:
            self._repository_error_counts[normalized] = (
                self._repository_error_counts.get(normalized, 0) + 1
            )

        if normalized in self._repository_errors:
            self._repository_errors.remove(normalized)

        self._repository_errors.append(normalized)

        if len(self._repository_errors) > MAX_REPOSITORY_ERROR_HISTORY:
            del self._repository_errors[:-MAX_REPOSITORY_ERROR_HISTORY]

        if len(self._repository_error_counts) > MAX_REPOSITORY_ERROR_SIGNATURES:
            retained = set(self._repository_errors)
            self._repository_error_counts = {
                key: value
                for key, value in self._repository_error_counts.items()
                if key in retained
            }

    def clear_instance_cache(self) -> dict[str, Any]:
        with self._cache_lock:
            before = len(self._registry_cache)
            self._registry_cache.clear()
            self._registry_identity = None

        try:
            operation_entries = len(
                getattr(self._operation_local, "cache", {}) or {}
            )
            self._operation_local.cache = {}
            self._operation_local.depth = 0
        except Exception:
            operation_entries = 0

        return {
            "ok": True,
            "component": "library.definition_catalog.instance_cache",
            "cleared": before,
            "operation_cache_cleared": operation_entries,
        }

    def _cache_get(self, key: tuple[Any, ...]) -> Any | None:
        if self._registry_cache_ttl_seconds <= 0:
            return None

        now = time.monotonic()

        with self._cache_lock:
            entry = self._registry_cache.get(key)
            if entry is None:
                return None

            expires_at, value = entry
            if expires_at < now:
                self._registry_cache.pop(key, None)
                return None

            try:
                return copy.deepcopy(value)
            except Exception:
                return normalize_json_value(value)

    def _cache_set(self, key: tuple[Any, ...], value: Any) -> None:
        if self._registry_cache_ttl_seconds <= 0:
            return

        try:
            cached_value = copy.deepcopy(value)
        except Exception:
            cached_value = normalize_json_value(value)

        expires_at = time.monotonic() + self._registry_cache_ttl_seconds

        with self._cache_lock:
            self._registry_cache[key] = (expires_at, cached_value)

            # Hard upper bound for long-lived worker processes.
            if len(self._registry_cache) > 128:
                oldest_keys = sorted(
                    self._registry_cache,
                    key=lambda cache_key: self._registry_cache[cache_key][0],
                )[:32]
                for old_key in oldest_keys:
                    self._registry_cache.pop(old_key, None)

    # ------------------------------------------------------------------
    # Registry serialization and lookups
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize_registry_definition(
        definition: Any,
        *,
        include_inactive: bool = True,
    ) -> dict[str, Any] | None:
        if definition is None:
            return None

        if isinstance(definition, Mapping):
            payload = normalize_json_mapping(definition)
        else:
            to_dict = getattr(definition, "to_dict", None)
            payload: dict[str, Any] | None = None

            if callable(to_dict):
                attempts = (
                    {
                        "include_extra": True,
                        "include_inactive": include_inactive,
                        "language": "de",
                    },
                    {
                        "include_extra": True,
                        "include_inactive": include_inactive,
                    },
                    {"include_extra": True},
                    {},
                )

                for kwargs in attempts:
                    try:
                        result = to_dict(**kwargs)
                    except TypeError:
                        continue
                    except Exception:
                        _LOGGER.exception(
                            "Could not serialize registry definition with %s.",
                            kwargs,
                        )
                        continue

                    if isinstance(result, Mapping):
                        payload = normalize_json_mapping(result)
                        break

            if payload is None:
                try:
                    payload = normalize_json_mapping(vars(definition))
                except Exception:
                    return None

        if not include_inactive and not normalize_bool(
            payload.get("active"),
            default=True,
        ):
            return None

        return payload

    def _registry_dataset_payloads(
        self,
        dataset_key: str,
        *,
        include_inactive: bool,
    ) -> list[dict[str, Any]]:
        registry = self._get_registry()
        if registry is None:
            return []

        cache_key = (
            "registry_dataset",
            id(registry),
            dataset_key,
            bool(include_inactive),
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return normalize_json_list(cached)

        method_name = _REGISTRY_LIST_METHODS.get(dataset_key)
        method = getattr(registry, method_name, None) if method_name else None
        if not callable(method):
            return []

        try:
            definitions = method(include_inactive=include_inactive)
        except TypeError:
            try:
                definitions = method()
            except Exception:
                _LOGGER.exception(
                    "Registry dataset lookup failed for %s.",
                    dataset_key,
                )
                return []
        except Exception:
            _LOGGER.exception(
                "Registry dataset lookup failed for %s.",
                dataset_key,
            )
            return []

        payloads: list[dict[str, Any]] = []

        for definition in definitions or ():
            payload = self._serialize_registry_definition(
                definition,
                include_inactive=include_inactive,
            )
            if payload is None:
                continue
            payloads.append(payload)

        payloads = dedupe_definition_payloads(dataset_key, payloads)
        self._cache_set(cache_key, payloads)
        return normalize_json_list(payloads)

    def _registry_definition_payload(
        self,
        dataset_key: str,
        definition_key: str,
        *,
        include_inactive: bool = True,
    ) -> dict[str, Any] | None:
        registry = self._get_registry()
        if registry is None:
            return None

        normalized_key = clean_string(definition_key)
        if not normalized_key:
            return None

        cache_key = (
            "registry_definition",
            id(registry),
            dataset_key,
            normalized_key.casefold(),
            bool(include_inactive),
        )
        cached = self._cache_get(cache_key)
        if cached is not None:
            return normalize_json_mapping(cached)

        method_name = _REGISTRY_GET_METHODS.get(dataset_key)
        method = getattr(registry, method_name, None) if method_name else None
        if not callable(method):
            return None

        try:
            definition = method(normalized_key)
        except Exception:
            _LOGGER.exception(
                "Registry definition lookup failed: dataset=%s key=%s",
                dataset_key,
                normalized_key,
            )
            return None

        payload = self._serialize_registry_definition(
            definition,
            include_inactive=include_inactive,
        )
        if payload is None:
            return None

        payload = self._with_catalog_source(payload, REGISTRY_SOURCE)
        self._cache_set(cache_key, payload)
        return normalize_json_mapping(payload)

    @staticmethod
    def _with_catalog_source(
        payload: Mapping[str, Any],
        source: str,
    ) -> dict[str, Any]:
        result = normalize_json_mapping(payload)
        result.setdefault("catalog_source", source)
        return result

    @staticmethod
    def _source_label(
        *,
        repository_count: int,
        registry_count: int,
        repository_ok: bool,
    ) -> str:
        if repository_count > 0 and registry_count > 0:
            return MERGED_SOURCE
        if repository_count > 0:
            return DEFAULT_SOURCE
        if registry_count > 0:
            return REGISTRY_SOURCE
        if repository_ok:
            return DEFAULT_SOURCE
        return "none"

    @staticmethod
    def _combine_source_labels(values: Iterable[Any]) -> str:
        sources = {
            clean_string(value)
            for value in values or ()
            if clean_string(value) not in {"", "none", "disabled"}
        }

        if MERGED_SOURCE in sources:
            return MERGED_SOURCE
        if DEFAULT_SOURCE in sources and REGISTRY_SOURCE in sources:
            return MERGED_SOURCE
        if DEFAULT_SOURCE in sources:
            return DEFAULT_SOURCE
        if REGISTRY_SOURCE in sources:
            return REGISTRY_SOURCE
        return "none"

    @staticmethod
    def _merge_dataset_items(
        dataset_key: str,
        registry_items: Iterable[Mapping[str, Any]],
        repository_items: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Merge immutable registry baseline with DB/resolved values.

        Both sources are deduplicated before merging. Registry order remains stable.
        A repository item with the same technical identity overrides registry values
        in-place while retaining missing baseline fields. Repository-only definitions
        are appended in repository order.
        """
        normalized_registry = dedupe_definition_payloads(
            dataset_key,
            registry_items,
        )
        normalized_repository = dedupe_definition_payloads(
            dataset_key,
            repository_items,
            prefer_incoming_duplicates=True,
        )

        merged: list[dict[str, Any]] = []
        positions: dict[str, int] = {}
        unkeyed_fingerprints: set[str] = set()

        for raw_item in normalized_registry:
            item = LibraryDefinitionCatalogService._with_catalog_source(
                raw_item,
                REGISTRY_SOURCE,
            )
            identity = normalize_definition_identity(dataset_key, item)

            if identity:
                positions[identity] = len(merged)
                merged.append(item)
                continue

            fingerprint = semantic_payload_fingerprint(item)
            if fingerprint in unkeyed_fingerprints:
                continue

            unkeyed_fingerprints.add(fingerprint)
            merged.append(item)

        for raw_item in normalized_repository:
            item = LibraryDefinitionCatalogService._with_catalog_source(
                raw_item,
                DEFAULT_SOURCE,
            )
            identity = normalize_definition_identity(dataset_key, item)

            if identity and identity in positions:
                position = positions[identity]
                merged[position] = merge_definition_payloads(
                    merged[position],
                    item,
                    prefer_incoming=True,
                )
                merged[position]["catalog_source"] = DEFAULT_SOURCE
                continue

            if identity:
                positions[identity] = len(merged)
                merged.append(item)
                continue

            fingerprint = semantic_payload_fingerprint(item)
            if fingerprint in unkeyed_fingerprints:
                continue

            unkeyed_fingerprints.add(fingerprint)
            merged.append(item)

        return merged

    # ------------------------------------------------------------------
    # Current catalog and datasets
    # ------------------------------------------------------------------

    def get_current_catalog(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        scope: Any = DEFAULT_SCOPE,
        include_overrides: bool = True,
        include_inactive: bool = False,
        include_deleted: bool = False,
        resolved: bool = True,
    ) -> dict[str, Any]:
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )
        normalized_scope = clean_string(scope, fallback=DEFAULT_SCOPE)

        if not resolved:
            repository_ok, payload, repository_error = self._repository_call(
                "get_current_catalog",
                user_id=normalized_user_id,
                include_overrides=include_overrides,
                include_inactive=include_inactive,
                include_deleted=include_deleted,
                default=None,
            )

            if repository_ok and isinstance(payload, Mapping):
                result = normalize_json_mapping(payload)
                result["scope"] = normalized_scope
                result["resolved"] = False
                result.setdefault("source", DEFAULT_SOURCE)
                return result

            # Fall through to registry-backed dataset payload when DB is absent.
            datasets = {
                dataset_key: self._registry_dataset_payloads(
                    dataset_key,
                    include_inactive=include_inactive,
                )
                for dataset_key in DATASET_KEYS
            }
            return {
                "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
                "source": REGISTRY_SOURCE,
                "scope": normalized_scope,
                "resolved": False,
                "user_id": normalized_user_id,
                "datasets": datasets,
                "summary": self._build_catalog_summary(datasets),
                "repository_error": repository_error,
                "supports_create_context": True,
                "supports_upload_constraints": True,
                "supports_user_overrides": False,
            }

        datasets: dict[str, list[dict[str, Any]]] = {}
        sources: dict[str, Any] = {}

        for dataset_key in DATASET_KEYS:
            dataset_payload = self.get_dataset(
                dataset_key,
                user_id=normalized_user_id,
                resolved=True,
                include_inactive=include_inactive,
            )
            datasets[dataset_key] = normalize_json_list(
                dataset_payload.get("items")
            )
            sources[dataset_key] = normalize_json_mapping(
                dataset_payload.get("sources")
            )

        source_values = {
            clean_string(sources[dataset_key].get("source"))
            for dataset_key in DATASET_KEYS
            if isinstance(sources.get(dataset_key), Mapping)
            and len(normalize_json_list(datasets.get(dataset_key))) > 0
        }
        catalog_source = self._combine_source_labels(source_values)

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "source": catalog_source,
            "scope": normalized_scope,
            "resolved": True,
            "user_id": normalized_user_id,
            "datasets": datasets,
            "dataset_sources": sources,
            "summary": self._build_catalog_summary(datasets),
            "supports_create_context": True,
            "supports_upload_constraints": True,
            "supports_user_overrides": self.repository is not None,
            "registry_fallback_enabled": self.allow_registry_fallback,
        }

    def get_dataset(
        self,
        dataset_key: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        resolved: bool = True,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        key = clean_dataset_key(dataset_key)
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )
        cache_key = (
            "dataset",
            key,
            normalized_user_id,
            bool(resolved),
            bool(include_inactive),
        )
        cached = self._operation_cache_get(cache_key)
        if isinstance(cached, Mapping):
            return normalize_json_mapping(cached)

        if resolved:
            repository_ok, repository_items, repository_error = self._repository_call(
                "get_resolved_dataset_payload",
                key,
                user_id=normalized_user_id,
                include_inactive=include_inactive,
                default=[],
            )
        else:
            repository_ok, repository_items, repository_error = self._repository_call(
                "list_definition_payloads",
                key,
                user_id=normalized_user_id,
                include_system=True,
                include_user=True,
                include_inactive=include_inactive,
                default=[],
            )

        normalized_repository_items = dedupe_definition_payloads(
            key,
            [
                normalize_json_mapping(item)
                for item in normalize_json_list(repository_items)
                if isinstance(item, Mapping)
            ],
            prefer_incoming_duplicates=True,
        )

        registry_items = (
            dedupe_definition_payloads(
                key,
                self._registry_dataset_payloads(
                    key,
                    include_inactive=include_inactive,
                ),
            )
            if self.allow_registry_fallback
            else []
        )

        items = self._merge_dataset_items(
            key,
            registry_items,
            normalized_repository_items,
        )

        source = self._source_label(
            repository_count=len(normalized_repository_items),
            registry_count=len(registry_items),
            repository_ok=repository_ok,
        )

        result = {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "dataset_key": key,
            "user_id": normalized_user_id,
            "resolved": bool(resolved),
            "source": source,
            "count": len(items),
            "items": items,
            "sources": {
                "source": source,
                "repository_ok": repository_ok,
                "repository_context_available": self._repository_context_available(),
                "repository_count": len(normalized_repository_items),
                "registry_count": len(registry_items),
                "merged_count": len(items),
                "repository_error": repository_error,
            },
        }
        self._operation_cache_set(cache_key, result)
        return result

    # ------------------------------------------------------------------
    # Dataset convenience methods
    # ------------------------------------------------------------------

    def get_variables(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        profile_id: Any = None,
        resolved: bool = True,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )
        profile = optional_string(profile_id)

        dataset = self.get_dataset(
            DATASET_VARIABLES,
            user_id=normalized_user_id,
            resolved=resolved,
            include_inactive=include_inactive,
        )
        variables = [
            normalize_json_mapping(variable)
            for variable in normalize_json_list(dataset.get("items"))
            if isinstance(variable, Mapping)
        ]

        if profile:
            variables = [
                variable
                for variable in variables
                if profile_matches_applies_to(variable, profile)
            ]

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "dataset_key": DATASET_VARIABLES,
            "user_id": normalized_user_id,
            "profile_id": profile,
            "source": dataset.get("source"),
            "count": len(variables),
            "items": variables,
            "sources": dataset.get("sources"),
        }

    def get_units(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_UNITS, user_id=user_id)

    def get_materials(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_MATERIALS, user_id=user_id)

    def get_document_types(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        return self.get_dataset(DATASET_DOCUMENT_TYPES, user_id=user_id)

    def get_object_kinds(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        return self.get_dataset(DATASET_OBJECT_KINDS, user_id=user_id)

    def get_family_profiles(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        return self.get_dataset(DATASET_FAMILY_PROFILES, user_id=user_id)

    def get_variant_profiles(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        return self.get_dataset(DATASET_VARIANT_PROFILES, user_id=user_id)

    def get_profile_bindings(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        return self.get_dataset(DATASET_PROFILE_BINDINGS, user_id=user_id)

    # ------------------------------------------------------------------
    # Single definition resolution
    # ------------------------------------------------------------------

    def get_definition(
        self,
        dataset_key: Any,
        definition_key: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        required: bool = False,
    ) -> dict[str, Any] | None:
        key = clean_dataset_key(dataset_key)
        requested_key = clean_string(definition_key)
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )

        if not requested_key:
            if required:
                raise LibraryDefinitionCatalogNotFoundError(
                    f"A definition key is required for dataset {key!r}."
                )
            return None

        cache_key = (
            "definition",
            key,
            requested_key.casefold(),
            normalized_user_id,
        )
        cached = self._operation_cache_get(cache_key)
        if isinstance(cached, Mapping):
            return normalize_json_mapping(cached)

        repository_ok, repository_payload, repository_error = self._repository_call(
            "get_definition_payload",
            key,
            requested_key,
            user_id=normalized_user_id,
            prefer_user=True,
            default=None,
        )

        if isinstance(repository_payload, Mapping):
            result = self._with_catalog_source(
                repository_payload,
                DEFAULT_SOURCE,
            )
            self._operation_cache_set(cache_key, result)
            return result

        registry_payload = (
            self._registry_definition_payload(
                key,
                requested_key,
                include_inactive=True,
            )
            if self.allow_registry_fallback
            else None
        )
        if registry_payload is not None:
            result = normalize_json_mapping(registry_payload)
            result.setdefault("registry_fallback", True)
            if (
                repository_error
                and REPOSITORY_CONTEXT_SKIPPED not in repository_error
            ):
                result.setdefault("repository_error", repository_error)
            self._operation_cache_set(cache_key, result)
            return result

        if required:
            source_status = (
                f"repository_ok={repository_ok}, "
                f"repository_error={repository_error!r}, "
                f"registry_error={self._registry_error!r}"
            )
            raise LibraryDefinitionCatalogNotFoundError(
                f"Definition {requested_key!r} in dataset {key!r} was not found "
                f"({source_status})."
            )

        return None

    def get_family_profile(
        self,
        family_profile_id: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        required: bool = False,
    ) -> dict[str, Any] | None:
        return self.get_definition(
            DATASET_FAMILY_PROFILES,
            family_profile_id,
            user_id=user_id,
            required=required,
        )

    def get_variant_profile(
        self,
        variant_profile_id: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        resolved: bool = False,
        required: bool = False,
    ) -> dict[str, Any] | None:
        profile = self.get_definition(
            DATASET_VARIANT_PROFILES,
            variant_profile_id,
            user_id=user_id,
            required=required,
        )

        if profile is None:
            return None

        if not resolved:
            return profile

        return self.resolve_variant_profile(
            profile,
            user_id=user_id,
        )

    # ------------------------------------------------------------------
    # Resolved profile payloads
    # ------------------------------------------------------------------

    def resolve_variant_profile(
        self,
        variant_profile: Mapping[str, Any],
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )
        profile = normalize_json_mapping(variant_profile)
        profile_id = get_definition_key(
            DATASET_VARIANT_PROFILES,
            profile,
        )

        variables_payload = self.get_dataset(
            DATASET_VARIABLES,
            user_id=normalized_user_id,
            resolved=True,
        )
        document_types_payload = self.get_dataset(
            DATASET_DOCUMENT_TYPES,
            user_id=normalized_user_id,
            resolved=True,
        )
        units_payload = self.get_dataset(
            DATASET_UNITS,
            user_id=normalized_user_id,
            resolved=True,
        )

        variables = [
            normalize_json_mapping(variable)
            for variable in normalize_json_list(
                variables_payload.get("items")
            )
            if isinstance(variable, Mapping)
            and profile_matches_applies_to(variable, profile_id)
        ]
        document_types = [
            normalize_json_mapping(item)
            for item in normalize_json_list(
                document_types_payload.get("items")
            )
            if isinstance(item, Mapping)
        ]
        units = [
            normalize_json_mapping(item)
            for item in normalize_json_list(units_payload.get("items"))
            if isinstance(item, Mapping)
        ]

        variable_index = index_payloads_by_key(
            DATASET_VARIABLES,
            variables,
        )
        document_type_index = index_payloads_by_key(
            DATASET_DOCUMENT_TYPES,
            document_types,
        )
        unit_index = index_payloads_by_key(
            DATASET_UNITS,
            units,
        )

        required_fields = set(
            dedupe_strings(
                profile.get("required_fields")
                or profile.get("requiredFields")
                or []
            )
        )
        optional_fields = set(
            dedupe_strings(
                profile.get("optional_fields")
                or profile.get("optionalFields")
                or []
            )
        )
        summary_fields = set(
            dedupe_strings(
                profile.get("summary_fields")
                or profile.get("summaryFields")
                or []
            )
        )
        default_values = normalize_json_mapping(
            profile.get("default_values")
            or profile.get("defaultValues")
        )

        sections = [
            self.resolve_section(
                section,
                variable_index=variable_index,
                document_type_index=document_type_index,
                unit_index=unit_index,
                required_fields=required_fields,
                optional_fields=optional_fields,
                summary_fields=summary_fields,
                default_values=default_values,
            )
            for section in normalize_json_list(profile.get("sections"))
            if isinstance(section, Mapping)
        ]

        all_field_keys = dedupe_strings(
            [
                field.get("field_key")
                for section in sections
                for field in normalize_json_list(section.get("fields"))
                if isinstance(field, Mapping)
            ]
        )

        upload_fields = [
            field
            for section in sections
            for field in normalize_json_list(section.get("fields"))
            if isinstance(field, Mapping) and field.get("upload")
        ]

        missing_variable_definitions = [
            field_key
            for field_key in all_field_keys
            if field_key not in variable_index
        ]

        resolved_profile = dict(profile)
        resolved_profile.update(
            {
                "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
                "resolved": True,
                "profile_id": profile_id,
                "variant_profile_id": profile_id,
                "sections": sections,
                "field_keys": all_field_keys,
                "required_fields": sorted(required_fields),
                "optional_fields": sorted(optional_fields),
                "summary_fields": sorted(summary_fields),
                "default_values": default_values,
                "upload_fields": upload_fields,
                "upload_field_count": len(upload_fields),
                "field_count": len(all_field_keys),
                "missing_variable_definitions": missing_variable_definitions,
                "source_details": {
                    "profile": profile.get("catalog_source"),
                    "variables": variables_payload.get("source"),
                    "document_types": document_types_payload.get("source"),
                    "units": units_payload.get("source"),
                },
            }
        )
        return resolved_profile

    def resolve_section(
        self,
        section: Mapping[str, Any],
        *,
        variable_index: Mapping[str, Mapping[str, Any]],
        document_type_index: Mapping[str, Mapping[str, Any]],
        unit_index: Mapping[str, Mapping[str, Any]],
        required_fields: set[str],
        optional_fields: set[str],
        summary_fields: set[str],
        default_values: Mapping[str, Any],
    ) -> dict[str, Any]:
        section_payload = normalize_json_mapping(section)
        raw_fields = normalize_json_list(section_payload.get("fields"))

        resolved_fields = [
            self.resolve_field(
                field,
                variable_index=variable_index,
                document_type_index=document_type_index,
                unit_index=unit_index,
                required_fields=required_fields,
                optional_fields=optional_fields,
                summary_fields=summary_fields,
                default_values=default_values,
            )
            for field in raw_fields
        ]

        section_id = optional_string(
            first_non_empty(
                section_payload.get("id"),
                section_payload.get("key"),
                section_payload.get("section_id"),
            )
        )

        return {
            **section_payload,
            "section_id": section_id,
            "id": section_id or section_payload.get("id"),
            "fields": resolved_fields,
            "field_count": len(resolved_fields),
            "upload_field_count": len(
                [field for field in resolved_fields if field.get("upload")]
            ),
        }

    def resolve_field(
        self,
        field: Any,
        *,
        variable_index: Mapping[str, Mapping[str, Any]],
        document_type_index: Mapping[str, Mapping[str, Any]],
        unit_index: Mapping[str, Mapping[str, Any]],
        required_fields: set[str],
        optional_fields: set[str],
        summary_fields: set[str],
        default_values: Mapping[str, Any],
    ) -> dict[str, Any]:
        field_payload = normalize_field_entry(field)
        field_key = optional_string(field_payload.get("field_key"))

        variable = dict(variable_index.get(field_key or "", {}))
        unit_id = optional_string(
            variable.get("unit") or variable.get("unit_id")
        )
        unit = unit_index.get(unit_id or "")

        is_required = bool(
            field_key and field_key in required_fields
        ) or normalize_bool(
            variable.get("required_default"),
            default=False,
        )
        is_optional = bool(
            field_key and field_key in optional_fields
        )
        is_summary = bool(
            field_key and field_key in summary_fields
        )

        default_value = None
        if field_key and field_key in default_values:
            default_value = normalize_json_value(default_values[field_key])
        elif "default_value" in variable:
            default_value = normalize_json_value(
                variable.get("default_value")
            )

        upload_constraints = None
        if variable and is_document_variable(variable):
            upload_constraints = self.build_upload_constraints_for_variable(
                variable,
                document_type_index=document_type_index,
            )

        result = {
            **field_payload,
            "field_key": field_key,
            "key": field_key,
            "required": is_required,
            "optional": is_optional,
            "summary": is_summary,
            "default_value": default_value,
            "variable": variable or None,
            "variable_resolved": bool(variable),
            "unit": unit,
            "upload": upload_constraints,
        }

        if variable:
            result.setdefault("label", variable.get("label"))
            result.setdefault(
                "description",
                variable.get("description"),
            )
            result.setdefault(
                "value_type",
                variable.get("value_type"),
            )
            result.setdefault("widget", variable.get("widget"))
            result.setdefault(
                "group",
                variable.get("group") or variable.get("group_key"),
            )

        return result

    # ------------------------------------------------------------------
    # Upload constraints
    # ------------------------------------------------------------------

    def build_upload_constraints_for_variable(
        self,
        variable: Mapping[str, Any],
        *,
        document_type_index: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        variable_payload = normalize_json_mapping(variable)
        document_type_id = extract_document_type_id(variable_payload)

        if not document_type_id:
            return {
                "enabled": True,
                "document_type": None,
                "multiple": True,
                "source": "variable",
                "reason": (
                    "variable has document-like value_type but no "
                    "document_type metadata"
                ),
            }

        index = dict(document_type_index or {})
        document_type = index.get(document_type_id)

        if document_type is None:
            document_type = self.get_definition(
                DATASET_DOCUMENT_TYPES,
                document_type_id,
                user_id=DEFAULT_USER_ID,
                required=False,
            )

        doc = normalize_json_mapping(document_type)

        return {
            "enabled": True,
            "document_type": document_type_id,
            "document_type_definition": doc or None,
            "label": doc.get("label") or variable_payload.get("label"),
            "allowed_mime_types": normalize_json_list(
                doc.get("allowed_mime_types")
            ),
            "allowed_extensions": normalize_json_list(
                doc.get("allowed_extensions")
            ),
            "max_size_mb": doc.get("max_size_mb"),
            "multiple": normalize_bool(
                doc.get("multiple"),
                default=True,
            ),
            "field_key": (
                variable_payload.get("variable_key")
                or variable_payload.get("key")
            ),
            "value_type": variable_payload.get("value_type"),
            "widget": variable_payload.get("widget"),
            "source": (
                doc.get("catalog_source")
                or "document_type"
            ),
        }

    def get_upload_constraints(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        document_type: Any = None,
        field_key: Any = None,
        variable_key: Any = None,
    ) -> dict[str, Any]:
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )
        document_types_payload = self.get_dataset(
            DATASET_DOCUMENT_TYPES,
            user_id=normalized_user_id,
            resolved=True,
        )
        document_type_index = index_payloads_by_key(
            DATASET_DOCUMENT_TYPES,
            normalize_json_list(document_types_payload.get("items")),
        )

        target_variable_key = optional_string(
            variable_key or field_key
        )

        if target_variable_key:
            variable = self.get_definition(
                DATASET_VARIABLES,
                target_variable_key,
                user_id=normalized_user_id,
                required=True,
            )

            constraints = self.build_upload_constraints_for_variable(
                variable or {},
                document_type_index=document_type_index,
            )

            return {
                "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
                "user_id": normalized_user_id,
                "field_key": target_variable_key,
                "constraints": constraints,
            }

        target_document_type = optional_string(document_type)

        if not target_document_type:
            raise ValueError("document_type or field_key is required.")

        doc = document_type_index.get(target_document_type)
        if not doc:
            doc = self.get_definition(
                DATASET_DOCUMENT_TYPES,
                target_document_type,
                user_id=normalized_user_id,
                required=False,
            )

        if not doc:
            raise LibraryDefinitionCatalogNotFoundError(
                f"Document type {target_document_type!r} was not found."
            )

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "user_id": normalized_user_id,
            "document_type": target_document_type,
            "constraints": {
                "enabled": True,
                "document_type": target_document_type,
                "document_type_definition": doc,
                "label": doc.get("label"),
                "allowed_mime_types": normalize_json_list(
                    doc.get("allowed_mime_types")
                ),
                "allowed_extensions": normalize_json_list(
                    doc.get("allowed_extensions")
                ),
                "max_size_mb": doc.get("max_size_mb"),
                "multiple": normalize_bool(
                    doc.get("multiple"),
                    default=True,
                ),
                "source": (
                    doc.get("catalog_source")
                    or "document_type"
                ),
            },
        }

    # ------------------------------------------------------------------
    # Create context and profile resolution
    # ------------------------------------------------------------------

    def _get_registry_profile_binding(
        self,
        query: CreateContextQuery,
    ) -> dict[str, Any] | None:
        registry = self._get_registry()
        if registry is None:
            return None

        finder = getattr(registry, "find_best_profile_binding", None)
        if not callable(finder):
            return None

        try:
            binding = finder(
                domain=query.domain,
                category=query.category,
                subcategory=query.subcategory,
                object_kind=query.object_kind,
                family_profile_id=query.family_profile_id,
            )
        except Exception:
            _LOGGER.exception("Registry profile binding resolution failed.")
            return None

        payload = self._serialize_registry_definition(binding)
        if payload is None:
            return None

        return self._with_catalog_source(payload, REGISTRY_SOURCE)

    def _resolve_family_profile_id_from_registry(
        self,
        query: CreateContextQuery,
    ) -> tuple[str | None, dict[str, Any] | None]:
        registry = self._get_registry()
        resolver = (
            getattr(registry, "resolve_family_profile_for_context", None)
            if registry is not None
            else None
        )
        if not callable(resolver):
            return None, None

        try:
            result = resolver(
                domain=query.domain,
                category=query.category,
                subcategory=query.subcategory,
                object_kind=query.object_kind,
                family_profile_id=query.family_profile_id,
            )
        except Exception:
            _LOGGER.exception(
                "Registry family profile resolution failed."
            )
            return None, None

        payload = normalize_json_mapping(result)
        if not normalize_bool(payload.get("ok"), default=False):
            return None, payload

        return optional_string(
            payload.get("family_profile_id")
        ), payload

    def _resolve_variant_profile_id_from_registry(
        self,
        query: CreateContextQuery,
        *,
        family_profile_id: str | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        registry = self._get_registry()
        resolver = (
            getattr(registry, "resolve_variant_profile_for_context", None)
            if registry is not None
            else None
        )
        if not callable(resolver):
            return None, None

        try:
            result = resolver(
                domain=query.domain,
                category=query.category,
                subcategory=query.subcategory,
                object_kind=query.object_kind,
                family_profile_id=family_profile_id,
                variant_profile_id=query.variant_profile_id,
            )
        except Exception:
            _LOGGER.exception(
                "Registry variant profile resolution failed."
            )
            return None, None

        payload = normalize_json_mapping(result)
        if not normalize_bool(payload.get("ok"), default=False):
            return None, payload

        return optional_string(
            payload.get("variant_profile_id")
        ), payload

    def get_create_context(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        object_kind: Any = None,
        family_profile_id: Any = None,
        variant_profile_id: Any = None,
        include_catalog: bool = False,
    ) -> dict[str, Any]:
        """Builds one create-context inside a short-lived repository read cache."""
        with self._operation_cache_scope():
            return self._get_create_context_impl(
                user_id=user_id,
                domain=domain,
                category=category,
                subcategory=subcategory,
                object_kind=object_kind,
                family_profile_id=family_profile_id,
                variant_profile_id=variant_profile_id,
                include_catalog=include_catalog,
            )

    def _get_create_context_impl(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        object_kind: Any = None,
        family_profile_id: Any = None,
        variant_profile_id: Any = None,
        include_catalog: bool = False,
    ) -> dict[str, Any]:
        query = CreateContextQuery.from_payload(
            {
                "user_id": user_id,
                "domain": domain,
                "category": category,
                "subcategory": subcategory,
                "object_kind": object_kind,
                "family_profile_id": family_profile_id,
                "variant_profile_id": variant_profile_id,
                "include_catalog": include_catalog,
            }
        )

        repository_binding_ok, repository_binding, binding_error = (
            self._repository_call(
                "find_profile_binding",
                user_id=query.user_id,
                domain=query.domain,
                category=query.category,
                subcategory=query.subcategory,
                object_kind=query.object_kind,
                default=None,
            )
        )
        binding = (
            normalize_json_mapping(repository_binding)
            if isinstance(repository_binding, Mapping)
            else None
        )
        public_binding_error = (
            None
            if binding_error and REPOSITORY_CONTEXT_SKIPPED in binding_error
            else binding_error
        )

        if not binding:
            binding = self._get_registry_profile_binding(query)

        resolved_family_profile_id = (
            query.family_profile_id
            or optional_string(
                binding.get("family_profile_id")
                if binding
                else None
            )
        )
        family_resolution: dict[str, Any] | None = None

        if not resolved_family_profile_id:
            (
                resolved_family_profile_id,
                family_resolution,
            ) = self._resolve_family_profile_id_from_registry(query)

        if not resolved_family_profile_id:
            raise LibraryDefinitionCreateContextError(
                "Could not resolve family_profile_id from request, "
                "repository binding, registry binding or object-kind defaults."
            )

        family_profile = self.get_family_profile(
            resolved_family_profile_id,
            user_id=query.user_id,
            required=True,
        )
        canonical_family_profile_id = (
            get_definition_key(
                DATASET_FAMILY_PROFILES,
                family_profile or {},
            )
            or resolved_family_profile_id
        )

        resolved_variant_profile_id = (
            query.variant_profile_id
            or optional_string(
                binding.get("variant_profile_id")
                if binding
                else None
            )
        )

        if not resolved_variant_profile_id and family_profile:
            resolved_variant_profile_id = optional_string(
                first_non_empty(
                    family_profile.get("default_variant_profile_id"),
                    family_profile.get("defaultVariantProfileId"),
                )
            )

        variant_resolution: dict[str, Any] | None = None
        if not resolved_variant_profile_id:
            (
                resolved_variant_profile_id,
                variant_resolution,
            ) = self._resolve_variant_profile_id_from_registry(
                query,
                family_profile_id=canonical_family_profile_id,
            )

        if not resolved_variant_profile_id and query.object_kind:
            object_kind_definition = self.get_definition(
                DATASET_OBJECT_KINDS,
                query.object_kind,
                user_id=query.user_id,
                required=False,
            )
            if object_kind_definition:
                resolved_variant_profile_id = optional_string(
                    first_non_empty(
                        object_kind_definition.get(
                            "default_variant_profile_id"
                        ),
                        object_kind_definition.get(
                            "defaultVariantProfileId"
                        ),
                    )
                )

        if not resolved_variant_profile_id:
            raise LibraryDefinitionCreateContextError(
                "Could not resolve variant_profile_id from request, "
                "profile binding, family defaults, object-kind defaults "
                "or registry resolution."
            )

        variant_profile = self.get_variant_profile(
            resolved_variant_profile_id,
            user_id=query.user_id,
            resolved=True,
            required=True,
        )
        canonical_variant_profile_id = (
            get_definition_key(
                DATASET_VARIANT_PROFILES,
                variant_profile or {},
            )
            or resolved_variant_profile_id
        )

        variables = (
            self.get_variables(
                user_id=query.user_id,
                profile_id=canonical_variant_profile_id,
            )
            if query.include_variables
            else {"items": [], "source": "disabled"}
        )
        units = (
            self.get_units(user_id=query.user_id)
            if query.include_units
            else {"items": [], "source": "disabled"}
        )
        materials = (
            self.get_materials(user_id=query.user_id)
            if query.include_materials
            else {"items": [], "source": "disabled"}
        )
        document_types = self.get_document_types(
            user_id=query.user_id
        )

        source_values = {
            clean_string(
                (family_profile or {}).get("catalog_source")
            ),
            clean_string(
                (variant_profile or {}).get("catalog_source")
            ),
        }
        for dataset_payload in (
            variables,
            units,
            materials,
            document_types,
        ):
            if normalize_json_list(dataset_payload.get("items")):
                source_values.add(
                    clean_string(dataset_payload.get("source"))
                )
        source_values.discard("")
        source = self._combine_source_labels(source_values)

        result = {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "source": source,
            "scope": "create_context",
            "resolved": True,
            "ready": True,
            "user_id": query.user_id,
            "request": query.to_dict(),
            "taxonomy": {
                "domain": query.domain,
                "category": query.category,
                "subcategory": query.subcategory,
                "taxonomy_path": "/".join(
                    part
                    for part in (
                        query.domain,
                        query.category,
                        query.subcategory,
                    )
                    if part
                )
                or None,
            },
            "object_kind": query.object_kind,
            "profile_binding": binding,
            "binding_source": (
                (binding or {}).get("catalog_source")
                or (
                    DEFAULT_SOURCE
                    if repository_binding_ok
                    else REGISTRY_SOURCE
                )
            ),
            "binding_error": public_binding_error,
            "repository_context_available": self._repository_context_available(),
            "family_profile_id": canonical_family_profile_id,
            "variant_profile_id": canonical_variant_profile_id,
            "family_profile": family_profile,
            "variant_profile": variant_profile,
            "variables": variables.get("items", []),
            "units": units.get("items", []),
            "materials": materials.get("items", []),
            "document_types": document_types.get("items", []),
            "upload_fields": normalize_json_list(
                variant_profile.get("upload_fields")
                if variant_profile
                else []
            ),
            "sections": normalize_json_list(
                variant_profile.get("sections")
                if variant_profile
                else []
            ),
            "defaults": normalize_json_mapping(
                variant_profile.get("default_values")
                if variant_profile
                else {}
            ),
            "required_fields": normalize_json_list(
                variant_profile.get("required_fields")
                if variant_profile
                else []
            ),
            "optional_fields": normalize_json_list(
                variant_profile.get("optional_fields")
                if variant_profile
                else []
            ),
            "summary_fields": normalize_json_list(
                variant_profile.get("summary_fields")
                if variant_profile
                else []
            ),
            "resolution": {
                "family": family_resolution,
                "variant": variant_resolution,
            },
            "source_details": {
                "family_profile": (
                    family_profile or {}
                ).get("catalog_source"),
                "variant_profile": (
                    variant_profile or {}
                ).get("catalog_source"),
                "variables": variables.get("source"),
                "units": units.get("source"),
                "materials": materials.get("source"),
                "document_types": document_types.get("source"),
            },
        }

        if query.include_catalog:
            result["catalog"] = self.get_current_catalog(
                user_id=query.user_id,
                resolved=True,
            )

        return result

    # ------------------------------------------------------------------
    # Summary / options
    # ------------------------------------------------------------------

    def get_summary(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        catalog = self.get_current_catalog(
            user_id=user_id,
            resolved=True,
        )
        datasets = normalize_json_mapping(
            catalog.get("datasets")
        )

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "user_id": normalize_user_id(
                user_id,
                default=DEFAULT_USER_ID,
            ),
            "source": catalog.get("source"),
            "dataset_counts": {
                key: len(normalize_json_list(value))
                for key, value in datasets.items()
            },
            "summary": normalize_json_mapping(
                catalog.get("summary")
            ),
        }

    def get_create_options(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
    ) -> dict[str, Any]:
        normalized_user_id = normalize_user_id(
            user_id,
            default=DEFAULT_USER_ID,
        )

        object_kinds = self.get_object_kinds(
            user_id=normalized_user_id
        )
        family_profiles = self.get_family_profiles(
            user_id=normalized_user_id
        )
        variant_profiles = self.get_variant_profiles(
            user_id=normalized_user_id
        )
        profile_bindings = self.get_profile_bindings(
            user_id=normalized_user_id
        )
        document_types = self.get_document_types(
            user_id=normalized_user_id
        )

        starter_profile_available = any(
            get_definition_key(
                DATASET_VARIANT_PROFILES,
                item,
            )
            == STARTER_VARIANT_PROFILE_ID
            for item in normalize_json_list(
                variant_profiles.get("items")
            )
            if isinstance(item, Mapping)
        )

        option_datasets = (
            object_kinds,
            family_profiles,
            variant_profiles,
            profile_bindings,
            document_types,
        )
        options_source = self._combine_source_labels(
            dataset.get("source")
            for dataset in option_datasets
            if normalize_json_list(dataset.get("items"))
        )

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "user_id": normalized_user_id,
            "source": options_source,
            "ready": starter_profile_available,
            "starter_profile": {
                "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
                "family_profile_id": STARTER_FAMILY_PROFILE_ID,
                "object_kind": STARTER_OBJECT_KIND,
                "available": starter_profile_available,
            },
            "object_kinds": object_kinds.get("items", []),
            "family_profiles": family_profiles.get("items", []),
            "variant_profiles": variant_profiles.get("items", []),
            "profile_bindings": profile_bindings.get("items", []),
            "document_types": document_types.get("items", []),
            "source_details": {
                "object_kinds": object_kinds.get("source"),
                "family_profiles": family_profiles.get("source"),
                "variant_profiles": variant_profiles.get("source"),
                "profile_bindings": profile_bindings.get("source"),
                "document_types": document_types.get("source"),
            },
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        repository_health: dict[str, Any] = {}
        repository_error = self._repository_init_error
        repository_context_available = self._repository_context_available()
        repository = (
            self._ensure_repository()
            if repository_context_available
            else self.repository
        )

        if repository is not None:
            method = getattr(repository, "get_health", None)
            if callable(method):
                repository_ok_call, repository_payload, call_error = self._repository_call(
                    "get_health",
                    default=None,
                )
                if repository_ok_call and isinstance(repository_payload, Mapping):
                    repository_health = normalize_json_mapping(repository_payload)
                    repository_error = None
                elif call_error and REPOSITORY_CONTEXT_SKIPPED in call_error:
                    repository_health = {
                        "ok": False,
                        "available": True,
                        "status": "context_unavailable",
                        "detail": (
                            "Repository health was not executed because no Flask "
                            "application context is active."
                        ),
                    }
                    repository_error = REPOSITORY_CONTEXT_SKIPPED
                elif call_error:
                    repository_health = {
                        "ok": False,
                        "available": True,
                        "status": "error",
                    }
                    repository_error = call_error
            else:
                repository_health = {
                    "ok": repository_context_available,
                    "available": True,
                    "status": (
                        "available"
                        if repository_context_available
                        else "context_unavailable"
                    ),
                    "detail": "repository has no get_health method",
                }
                if not repository_context_available:
                    repository_error = REPOSITORY_CONTEXT_SKIPPED
        elif self._repository_deferred:
            repository_health = {
                "ok": False,
                "available": True,
                "status": "deferred",
                "detail": (
                    "Repository construction is deferred until a Flask application "
                    "context is active."
                ),
            }
            repository_error = REPOSITORY_CONTEXT_SKIPPED
        elif self._repository_init_error:
            repository_health = {
                "ok": False,
                "available": False,
                "status": "initialization_failed",
                "detail": self._repository_init_error,
            }

        repository_ok = normalize_bool(
            repository_health.get("ok"),
            default=(
                self.repository is not None
                and repository_error is None
                and repository_context_available
            ),
        )

        registry_health: dict[str, Any] = {}
        registry = self._get_registry()
        registry_error = self._registry_error

        if registry is not None:
            health_method = getattr(registry, "health", None)
            try:
                if callable(health_method):
                    registry_health = normalize_json_mapping(
                        health_method()
                    )
                else:
                    registry_health = {
                        "ok": True,
                        "status": "available",
                    }
            except Exception as exc:
                registry_error = self._format_error(exc)
                self._log_once(
                    "registry_health",
                    logging.ERROR,
                    "Definition registry health check failed.",
                    exc=exc,
                )

        registry_ok = normalize_bool(
            registry_health.get("ok"),
            default=registry is not None and registry_error is None,
        )

        starter_profile_available = False
        if registry is not None:
            has_profile = getattr(
                registry,
                "has_variant_profile",
                None,
            )
            try:
                if callable(has_profile):
                    starter_profile_available = bool(
                        has_profile(
                            STARTER_VARIANT_PROFILE_ID,
                            require_active=True,
                        )
                    )
                else:
                    getter = getattr(
                        registry,
                        "get_variant_profile",
                        None,
                    )
                    starter_profile_available = bool(
                        callable(getter)
                        and getter(STARTER_VARIANT_PROFILE_ID)
                    )
            except Exception as exc:
                self._log_once(
                    "starter_profile_registry_health",
                    logging.WARNING,
                    "Starter variant profile registry check failed.",
                    exc=exc,
                )

        if not starter_profile_available:
            try:
                starter_profile_available = (
                    self.get_definition(
                        DATASET_VARIANT_PROFILES,
                        STARTER_VARIANT_PROFILE_ID,
                        required=False,
                    )
                    is not None
                )
            except Exception:
                starter_profile_available = False

        ready = starter_profile_available and (
            repository_ok or registry_ok
        )
        healthy = repository_ok and registry_ok and ready
        ok = ready

        if healthy:
            status = "healthy"
        elif ready:
            status = "degraded"
        else:
            status = "unavailable"

        result = ServiceHealth(
            ok=ok,
            healthy=healthy,
            ready=ready,
            status=status,
            repository_health=repository_health,
            registry_health=registry_health,
            starter_profile_available=starter_profile_available,
            repository_error=repository_error,
            registry_error=registry_error,
            repository_context_available=repository_context_available,
            repository_requires_app_context=self._repository_requires_app_context,
            repository_call_count=self._repository_call_count,
            repository_success_count=self._repository_success_count,
            repository_skip_count=self._repository_skip_count,
            repository_error_count=sum(self._repository_error_counts.values()),
        ).to_dict()
        result["repository_diagnostics"] = {
            "recent_errors": list(self._repository_errors),
            "error_counts": dict(self._repository_error_counts),
            "fallback_enabled": self.allow_registry_fallback,
            "repository_injected": self._repository_was_injected,
        }
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_catalog_summary(
        self,
        datasets: Mapping[str, Any],
    ) -> dict[str, Any]:
        data = normalize_json_mapping(datasets)

        counts = {
            dataset_key: len(
                normalize_json_list(data.get(dataset_key))
            )
            for dataset_key in DATASET_KEYS
        }

        return {
            "dataset_count": len(DATASET_KEYS),
            "definition_count": sum(counts.values()),
            "counts": counts,
            "has_variables": counts.get(DATASET_VARIABLES, 0) > 0,
            "has_units": counts.get(DATASET_UNITS, 0) > 0,
            "has_materials": counts.get(DATASET_MATERIALS, 0) > 0,
            "has_document_types": (
                counts.get(DATASET_DOCUMENT_TYPES, 0) > 0
            ),
            "has_object_kinds": (
                counts.get(DATASET_OBJECT_KINDS, 0) > 0
            ),
            "has_family_profiles": (
                counts.get(DATASET_FAMILY_PROFILES, 0) > 0
            ),
            "has_variant_profiles": (
                counts.get(DATASET_VARIANT_PROFILES, 0) > 0
            ),
            "has_profile_bindings": (
                counts.get(DATASET_PROFILE_BINDINGS, 0) > 0
            ),
            "starter_variant_profile_id": STARTER_VARIANT_PROFILE_ID,
            "starter_variant_profile_available": any(
                get_definition_key(
                    DATASET_VARIANT_PROFILES,
                    item,
                )
                == STARTER_VARIANT_PROFILE_ID
                for item in normalize_json_list(
                    data.get(DATASET_VARIANT_PROFILES)
                )
                if isinstance(item, Mapping)
            ),
        }




# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_definition_catalog_service(
    repository: Any | None = None,
    *,
    registry: Any | None = None,
    allow_registry_fallback: bool = True,
    registry_cache_ttl_seconds: float = DEFAULT_REGISTRY_CACHE_TTL_SECONDS,
    repository_requires_app_context: bool | None = None,
    repository_error_log_ttl_seconds: float = DEFAULT_REPOSITORY_ERROR_LOG_TTL_SECONDS,
    operation_cache_enabled: bool = True,
) -> LibraryDefinitionCatalogService:
    """Factory for repository and registry dependency injection."""
    return LibraryDefinitionCatalogService(
        repository=repository,
        registry=registry,
        allow_registry_fallback=allow_registry_fallback,
        registry_cache_ttl_seconds=registry_cache_ttl_seconds,
        repository_requires_app_context=repository_requires_app_context,
        repository_error_log_ttl_seconds=repository_error_log_ttl_seconds,
        operation_cache_enabled=operation_cache_enabled,
    )


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION


def clear_library_definition_catalog_service_caches() -> dict[str, Any]:
    """Clears import caches, registry cache and live instance serialization caches."""
    cleared: list[str] = []
    errors: list[str] = []
    cleared_instance_entries = 0

    for cached_func in (
        _load_repository_module,
        _load_registry_module,
        get_service_version,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(
                getattr(cached_func, "__name__", str(cached_func))
            )
        except Exception as exc:
            errors.append(
                f"{getattr(cached_func, '__name__', cached_func)}: "
                f"{type(exc).__name__}: {exc}"
            )

    try:
        registry_module = _registry_module()
        clear_registry_cache = getattr(
            registry_module,
            "clear_definition_registry_cache",
            None,
        )
        if callable(clear_registry_cache):
            clear_registry_cache(clear_last_known_good=False)
            cleared.append("definition_registry")
    except Exception as exc:
        errors.append(
            f"definition_registry: {type(exc).__name__}: {exc}"
        )

    with _SERVICE_INSTANCES_LOCK:
        instances = list(_SERVICE_INSTANCES)

    for instance in instances:
        try:
            result = instance.clear_instance_cache()
            cleared_instance_entries += int(result.get("cleared", 0))
        except Exception as exc:
            errors.append(
                f"instance_cache: {type(exc).__name__}: {exc}"
            )

    return {
        "ok": not errors,
        "cleared": cleared,
        "cleared_instance_count": len(instances),
        "cleared_instance_entries": cleared_instance_entries,
        "errors": errors,
    }


__all__ = [
    "LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_SOURCE",
    "REGISTRY_SOURCE",
    "MERGED_SOURCE",
    "DEFAULT_SCOPE",
    "STARTER_VARIANT_PROFILE_ID",
    "STARTER_FAMILY_PROFILE_ID",
    "STARTER_OBJECT_KIND",
    "DEFAULT_REGISTRY_CACHE_TTL_SECONDS",
    "DEFAULT_REPOSITORY_ERROR_LOG_TTL_SECONDS",
    "MAX_REPOSITORY_ERROR_HISTORY",
    "MAX_REPOSITORY_ERROR_SIGNATURES",
    "MAX_OPERATION_CACHE_ENTRIES",
    "REPOSITORY_CONTEXT_SKIPPED",
    "DATASET_VARIABLES",
    "DATASET_UNITS",
    "DATASET_MATERIALS",
    "DATASET_DOCUMENT_TYPES",
    "DATASET_OBJECT_KINDS",
    "DATASET_FAMILY_PROFILES",
    "DATASET_VARIANT_PROFILES",
    "DATASET_PROFILE_BINDINGS",
    "DATASET_KEYS",
    "DOCUMENT_VALUE_TYPES",
    "WILDCARD_PROFILE_IDS",

    # Exceptions
    "LibraryDefinitionCatalogServiceError",
    "LibraryDefinitionCatalogImportError",
    "LibraryDefinitionCatalogRegistryError",
    "LibraryDefinitionCatalogNotFoundError",
    "LibraryDefinitionCreateContextError",

    # Dataclasses
    "CreateContextQuery",
    "ServiceHealth",

    # Service
    "LibraryDefinitionCatalogService",
    "create_library_definition_catalog_service",

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
    "first_non_empty",
    "dedupe_strings",
    "get_payload_key",
    "get_definition_key",
    "index_payloads_by_key",
    "index_payloads_by_any_key",
    "profile_matches_applies_to",
    "is_document_variable",
    "extract_document_type_id",
    "normalize_field_entry",
    "has_flask_application_context",
    "is_application_context_error",
    "normalize_definition_identity",
    "semantic_payload_fingerprint",
    "merge_definition_payloads",
    "dedupe_definition_payloads",
    "get_service_version",
    "clear_library_definition_catalog_service_caches",
]