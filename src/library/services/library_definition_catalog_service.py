# services/vectoplan-library/src/library/services/library_definition_catalog_service.py
"""
Service for VECTOPLAN Library Definition Catalog.

Diese Datei baut API-fähige Definition-Payloads aus dem Repository:

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

    LibraryDefinitionRepository
        -> LibraryDefinitionCatalogService
        -> routes/library_definition_routes.py
        -> Create UI / Variant Drawer / Upload Fields / Generator

Architekturregeln:

- Service enthält keine Flask-Route.
- Service enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über LibraryDefinitionRepository.
- Service schreibt standardmäßig nichts.
- User-Änderungen/Overrides werden im Repository gelesen, hier nur aufgelöst.
- Create Context ist ein reines Payload-Produkt für UI/Generator.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Fokus ist read-only Catalog/API.
- Seed-Logik liegt später in library_definition_seed_service.py.
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

LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION: Final[str] = "vectoplan_library.service.library_definition_catalog.v1"

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
DEFAULT_SCOPE: Final[str] = "resolved"

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
    """Normalizes dataset key through repository helper when available."""
    helper = getattr(_repo_module(), "clean_dataset_key", None)

    if callable(helper):
        return str(helper(dataset_key))

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
    """Indexes serialized definitions by dataset-specific key."""
    result: dict[str, dict[str, Any]] = {}

    for value in values or ():
        payload = normalize_json_mapping(value)
        key = get_definition_key(dataset_key, payload)

        if key:
            result[key] = payload

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
    """Health payload for service."""

    ok: bool
    repository_health: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "ok": self.ok,
            "healthy": self.ok,
            "repository_health": normalize_json_mapping(self.repository_health),
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LibraryDefinitionCatalogService:
    """
    High-level service for API-ready Library Definition Catalog payloads.

    Args:
        repository:
            Optional LibraryDefinitionRepository instance.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository or self._create_repository()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_repository(self) -> Any:
        repo_module = _repo_module()
        factory = getattr(repo_module, "create_library_definition_repository", None)

        if callable(factory):
            return factory()

        repo_class = getattr(repo_module, "LibraryDefinitionRepository", None)
        if repo_class is None:
            raise LibraryDefinitionCatalogImportError("LibraryDefinitionRepository class is not available.")

        return repo_class()

    # ------------------------------------------------------------------
    # Current catalog
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
        """Builds current catalog payload."""
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)
        normalized_scope = clean_string(scope, fallback=DEFAULT_SCOPE)

        if not resolved:
            payload = self.repository.get_current_catalog(
                user_id=normalized_user_id,
                include_overrides=include_overrides,
                include_inactive=include_inactive,
                include_deleted=include_deleted,
            )
            payload["scope"] = normalized_scope
            payload["resolved"] = False
            return payload

        datasets: dict[str, list[dict[str, Any]]] = {}

        for dataset_key in DATASET_KEYS:
            datasets[dataset_key] = self.repository.get_resolved_dataset_payload(
                dataset_key,
                user_id=normalized_user_id,
                include_inactive=include_inactive,
            )

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "source": DEFAULT_SOURCE,
            "scope": normalized_scope,
            "resolved": True,
            "user_id": normalized_user_id,
            "datasets": datasets,
            "summary": self._build_catalog_summary(datasets),
            "supports_create_context": True,
            "supports_upload_constraints": True,
            "supports_user_overrides": True,
        }

    def get_dataset(
        self,
        dataset_key: Any,
        *,
        user_id: Any = DEFAULT_USER_ID,
        resolved: bool = True,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        """Returns one dataset payload."""
        key = clean_dataset_key(dataset_key)
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)

        if resolved:
            items = self.repository.get_resolved_dataset_payload(
                key,
                user_id=normalized_user_id,
                include_inactive=include_inactive,
            )
        else:
            items = self.repository.list_definition_payloads(
                key,
                user_id=normalized_user_id,
                include_system=True,
                include_user=True,
                include_inactive=include_inactive,
            )

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "dataset_key": key,
            "user_id": normalized_user_id,
            "resolved": resolved,
            "count": len(items),
            "items": items,
        }

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
        """Returns variables, optionally filtered by profile_id."""
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)
        profile = optional_string(profile_id)

        if resolved:
            variables = self.repository.get_resolved_dataset_payload(
                DATASET_VARIABLES,
                user_id=normalized_user_id,
                include_inactive=include_inactive,
            )
        else:
            variables = self.repository.list_variables(user_id=normalized_user_id, as_dict=True)

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
            "count": len(variables),
            "items": variables,
        }

    def get_units(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_UNITS, user_id=user_id)

    def get_materials(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_MATERIALS, user_id=user_id)

    def get_document_types(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_DOCUMENT_TYPES, user_id=user_id)

    def get_object_kinds(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_OBJECT_KINDS, user_id=user_id)

    def get_family_profiles(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_FAMILY_PROFILES, user_id=user_id)

    def get_variant_profiles(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        return self.get_dataset(DATASET_VARIANT_PROFILES, user_id=user_id)

    def get_profile_bindings(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
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
        """Returns one definition payload."""
        payload = self.repository.get_definition_payload(
            dataset_key,
            definition_key,
            user_id=normalize_user_id(user_id, default=DEFAULT_USER_ID),
            prefer_user=True,
        )

        if payload is None and required:
            raise LibraryDefinitionCatalogNotFoundError(
                f"Definition {definition_key!r} in dataset {dataset_key!r} was not found."
            )

        return payload

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
        """
        Enriches a variant profile with variable definitions and upload constraints.

        Input variant profile fields expected:
        - sections
        - required_fields
        - optional_fields
        - summary_fields
        - default_values
        - document_types
        """
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)
        profile = normalize_json_mapping(variant_profile)
        profile_id = get_definition_key(DATASET_VARIANT_PROFILES, profile)

        variables = self.repository.get_resolved_dataset_payload(DATASET_VARIABLES, user_id=normalized_user_id)
        document_types = self.repository.get_resolved_dataset_payload(DATASET_DOCUMENT_TYPES, user_id=normalized_user_id)
        units = self.repository.get_resolved_dataset_payload(DATASET_UNITS, user_id=normalized_user_id)

        variables = [
            variable
            for variable in variables
            if profile_matches_applies_to(variable, profile_id)
        ]

        variable_index = index_payloads_by_key(DATASET_VARIABLES, variables)
        document_type_index = index_payloads_by_key(DATASET_DOCUMENT_TYPES, document_types)
        unit_index = index_payloads_by_key(DATASET_UNITS, units)

        required_fields = set(dedupe_strings(profile.get("required_fields") or profile.get("requiredFields") or []))
        optional_fields = set(dedupe_strings(profile.get("optional_fields") or profile.get("optionalFields") or []))
        summary_fields = set(dedupe_strings(profile.get("summary_fields") or profile.get("summaryFields") or []))
        default_values = normalize_json_mapping(profile.get("default_values") or profile.get("defaultValues"))

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
        """Resolves one section with enriched field definitions."""
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
            "upload_field_count": len([field for field in resolved_fields if field.get("upload")]),
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
        """Resolves one field entry with its variable definition."""
        field_payload = normalize_field_entry(field)
        field_key = optional_string(field_payload.get("field_key"))

        variable = dict(variable_index.get(field_key or "", {}))
        unit_id = optional_string(variable.get("unit") or variable.get("unit_id"))
        unit = unit_index.get(unit_id or "")

        is_required = bool(field_key and field_key in required_fields) or normalize_bool(variable.get("required_default"), default=False)
        is_optional = bool(field_key and field_key in optional_fields)
        is_summary = bool(field_key and field_key in summary_fields)

        default_value = None
        if field_key and field_key in default_values:
            default_value = normalize_json_value(default_values[field_key])
        elif "default_value" in variable:
            default_value = normalize_json_value(variable.get("default_value"))

        upload_constraints = None
        if variable and is_document_variable(variable):
            upload_constraints = self.build_upload_constraints_for_variable(variable, document_type_index=document_type_index)

        result = {
            **field_payload,
            "field_key": field_key,
            "key": field_key,
            "required": is_required,
            "optional": is_optional,
            "summary": is_summary,
            "default_value": default_value,
            "variable": variable or None,
            "unit": unit,
            "upload": upload_constraints,
        }

        if variable:
            result.setdefault("label", variable.get("label"))
            result.setdefault("description", variable.get("description"))
            result.setdefault("value_type", variable.get("value_type"))
            result.setdefault("widget", variable.get("widget"))
            result.setdefault("group", variable.get("group") or variable.get("group_key"))

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
        """Builds upload constraints from a document variable and document type."""
        variable_payload = normalize_json_mapping(variable)
        document_type_id = extract_document_type_id(variable_payload)

        if not document_type_id:
            return {
                "enabled": True,
                "document_type": None,
                "multiple": True,
                "source": "variable",
                "reason": "variable has document-like value_type but no document_type metadata",
            }

        index = dict(document_type_index or {})
        document_type = index.get(document_type_id)

        if document_type is None:
            document_type = self.repository.get_definition_payload(
                DATASET_DOCUMENT_TYPES,
                document_type_id,
                user_id=DEFAULT_USER_ID,
                prefer_user=True,
            )

        doc = normalize_json_mapping(document_type)

        return {
            "enabled": True,
            "document_type": document_type_id,
            "document_type_definition": doc or None,
            "label": doc.get("label") or variable_payload.get("label"),
            "allowed_mime_types": normalize_json_list(doc.get("allowed_mime_types")),
            "allowed_extensions": normalize_json_list(doc.get("allowed_extensions")),
            "max_size_mb": doc.get("max_size_mb"),
            "multiple": normalize_bool(doc.get("multiple"), default=True),
            "field_key": variable_payload.get("variable_key") or variable_payload.get("key"),
            "value_type": variable_payload.get("value_type"),
            "widget": variable_payload.get("widget"),
            "source": "document_type",
        }

    def get_upload_constraints(
        self,
        *,
        user_id: Any = DEFAULT_USER_ID,
        document_type: Any = None,
        field_key: Any = None,
        variable_key: Any = None,
    ) -> dict[str, Any]:
        """Returns upload constraints by document_type or variable field."""
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)
        document_types = self.repository.get_resolved_dataset_payload(DATASET_DOCUMENT_TYPES, user_id=normalized_user_id)
        document_type_index = index_payloads_by_key(DATASET_DOCUMENT_TYPES, document_types)

        target_variable_key = optional_string(variable_key or field_key)

        if target_variable_key:
            variable = self.repository.get_definition_payload(
                DATASET_VARIABLES,
                target_variable_key,
                user_id=normalized_user_id,
                prefer_user=True,
            )

            if not variable:
                raise LibraryDefinitionCatalogNotFoundError(f"Variable {target_variable_key!r} was not found.")

            constraints = self.build_upload_constraints_for_variable(
                variable,
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
            raise LibraryDefinitionCatalogNotFoundError(f"Document type {target_document_type!r} was not found.")

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "user_id": normalized_user_id,
            "document_type": target_document_type,
            "constraints": {
                "enabled": True,
                "document_type": target_document_type,
                "document_type_definition": doc,
                "label": doc.get("label"),
                "allowed_mime_types": normalize_json_list(doc.get("allowed_mime_types")),
                "allowed_extensions": normalize_json_list(doc.get("allowed_extensions")),
                "max_size_mb": doc.get("max_size_mb"),
                "multiple": normalize_bool(doc.get("multiple"), default=True),
                "source": "document_type",
            },
        }

    # ------------------------------------------------------------------
    # Create context
    # ------------------------------------------------------------------

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
        """Builds resolved create context."""
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

        binding = self.repository.find_profile_binding(
            user_id=query.user_id,
            domain=query.domain,
            category=query.category,
            subcategory=query.subcategory,
            object_kind=query.object_kind,
        )

        resolved_family_profile_id = query.family_profile_id or optional_string(
            binding.get("family_profile_id") if binding else None
        )
        resolved_variant_profile_id = query.variant_profile_id or optional_string(
            binding.get("variant_profile_id") if binding else None
        )

        if not resolved_family_profile_id:
            raise LibraryDefinitionCreateContextError(
                "Could not resolve family_profile_id from request or profile binding."
            )

        if not resolved_variant_profile_id:
            raise LibraryDefinitionCreateContextError(
                "Could not resolve variant_profile_id from request or profile binding."
            )

        family_profile = self.get_family_profile(
            resolved_family_profile_id,
            user_id=query.user_id,
            required=True,
        )
        variant_profile = self.get_variant_profile(
            resolved_variant_profile_id,
            user_id=query.user_id,
            resolved=True,
            required=True,
        )

        variables = self.get_variables(
            user_id=query.user_id,
            profile_id=resolved_variant_profile_id,
        ) if query.include_variables else {"items": []}

        units = self.get_units(user_id=query.user_id) if query.include_units else {"items": []}
        materials = self.get_materials(user_id=query.user_id) if query.include_materials else {"items": []}
        document_types = self.get_document_types(user_id=query.user_id)

        result = {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "source": DEFAULT_SOURCE,
            "scope": "create_context",
            "resolved": True,
            "user_id": query.user_id,
            "request": query.to_dict(),
            "taxonomy": {
                "domain": query.domain,
                "category": query.category,
                "subcategory": query.subcategory,
                "taxonomy_path": "/".join(part for part in (query.domain, query.category, query.subcategory) if part) or None,
            },
            "object_kind": query.object_kind,
            "profile_binding": binding,
            "family_profile_id": resolved_family_profile_id,
            "variant_profile_id": resolved_variant_profile_id,
            "family_profile": family_profile,
            "variant_profile": variant_profile,
            "variables": variables.get("items", []),
            "units": units.get("items", []),
            "materials": materials.get("items", []),
            "document_types": document_types.get("items", []),
            "upload_fields": normalize_json_list(variant_profile.get("upload_fields") if variant_profile else []),
            "sections": normalize_json_list(variant_profile.get("sections") if variant_profile else []),
            "defaults": normalize_json_mapping(variant_profile.get("default_values") if variant_profile else {}),
            "required_fields": normalize_json_list(variant_profile.get("required_fields") if variant_profile else []),
            "optional_fields": normalize_json_list(variant_profile.get("optional_fields") if variant_profile else []),
            "summary_fields": normalize_json_list(variant_profile.get("summary_fields") if variant_profile else []),
        }

        if query.include_catalog:
            result["catalog"] = self.get_current_catalog(user_id=query.user_id, resolved=True)

        return result

    # ------------------------------------------------------------------
    # Summary / options
    # ------------------------------------------------------------------

    def get_summary(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        """Returns compact definition catalog summary."""
        catalog = self.get_current_catalog(user_id=user_id, resolved=True)
        datasets = normalize_json_mapping(catalog.get("datasets"))

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "user_id": normalize_user_id(user_id, default=DEFAULT_USER_ID),
            "dataset_counts": {
                key: len(normalize_json_list(value))
                for key, value in datasets.items()
            },
            "summary": normalize_json_mapping(catalog.get("summary")),
        }

    def get_create_options(self, *, user_id: Any = DEFAULT_USER_ID) -> dict[str, Any]:
        """
        Returns compact options for create UI.

        This is not full create context. It only provides selectable base lists.
        """
        normalized_user_id = normalize_user_id(user_id, default=DEFAULT_USER_ID)

        return {
            "schema_version": LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION,
            "user_id": normalized_user_id,
            "object_kinds": self.get_object_kinds(user_id=normalized_user_id).get("items", []),
            "family_profiles": self.get_family_profiles(user_id=normalized_user_id).get("items", []),
            "variant_profiles": self.get_variant_profiles(user_id=normalized_user_id).get("items", []),
            "profile_bindings": self.get_profile_bindings(user_id=normalized_user_id).get("items", []),
            "document_types": self.get_document_types(user_id=normalized_user_id).get("items", []),
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns service health snapshot."""
        try:
            repository_health = self.repository.get_health() if hasattr(self.repository, "get_health") else {}
            return ServiceHealth(ok=True, repository_health=repository_health).to_dict()
        except Exception as exc:
            return ServiceHealth(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            ).to_dict()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_catalog_summary(self, datasets: Mapping[str, Any]) -> dict[str, Any]:
        """Builds compact catalog summary."""
        data = normalize_json_mapping(datasets)

        counts = {
            dataset_key: len(normalize_json_list(data.get(dataset_key)))
            for dataset_key in DATASET_KEYS
        }

        return {
            "dataset_count": len(DATASET_KEYS),
            "definition_count": sum(counts.values()),
            "counts": counts,
            "has_variables": counts.get(DATASET_VARIABLES, 0) > 0,
            "has_units": counts.get(DATASET_UNITS, 0) > 0,
            "has_materials": counts.get(DATASET_MATERIALS, 0) > 0,
            "has_document_types": counts.get(DATASET_DOCUMENT_TYPES, 0) > 0,
            "has_object_kinds": counts.get(DATASET_OBJECT_KINDS, 0) > 0,
            "has_family_profiles": counts.get(DATASET_FAMILY_PROFILES, 0) > 0,
            "has_variant_profiles": counts.get(DATASET_VARIANT_PROFILES, 0) > 0,
            "has_profile_bindings": counts.get(DATASET_PROFILE_BINDINGS, 0) > 0,
        }


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_definition_catalog_service(repository: Any | None = None) -> LibraryDefinitionCatalogService:
    """Factory for dependency injection."""
    return LibraryDefinitionCatalogService(repository=repository)


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION


def clear_library_definition_catalog_service_caches() -> dict[str, Any]:
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
    "LIBRARY_DEFINITION_CATALOG_SERVICE_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_SOURCE",
    "DEFAULT_SCOPE",
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
    "get_service_version",
    "clear_library_definition_catalog_service_caches",
]