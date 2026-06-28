# services/vectoplan-library/src/library/services/library_definition_seed_service.py
"""
Seed service for VECTOPLAN Library Definition Catalog.

Diese Datei importiert die Definitions-JSONs aus:

    src/library/definitions/data/*.json

in die DB-Tabellen aus:

    models/library_definitions.py

Ziel:

    definitions/data/*.json
        -> LibraryDefinitionSeedService
        -> LibraryDefinitionRepository
        -> library_definition_* Tabellen
        -> LibraryDefinitionCatalogService
        -> /api/v1/vplib/definitions/*

Unterstützte Dataset-Dateien:

- document_types.v1.json
- variables.v1.json
- units.v1.json
- materials.v1.json
- object_kinds.v1.json
- family_profiles.v1.json
- variant_profiles.v1.json
- profile_bindings.v1.json

Architekturregeln:

- Diese Datei enthält keine Flask-Route.
- Diese Datei enthält keine UI-Logik.
- Diese Datei enthält keine SQLAlchemy-Queries direkt.
- DB-Zugriffe laufen über LibraryDefinitionRepository.
- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt keine Migration aus.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei spricht keine Datenbankverbindung beim Import an.
- Der Seed ist idempotent:
    gleiche dataset_key + definition_key -> update
    neue definition_key -> insert
    fehlende System-Keys -> optional deprecated
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- Systemdefinitionen werden source_scope="system".
- owner_user_id bleibt None.
- user_id=1 bleibt für spätere User-Overlays vorbereitet.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Iterable, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_DEFINITION_SEED_SERVICE_VERSION: Final[str] = "vectoplan_library.service.library_definition_seed.v1"

DEFAULT_DEFINITIONS_VERSION: Final[str] = "v1"
DEFAULT_SOURCE_SCOPE: Final[str] = "system"
DEFAULT_TRIGGERED_BY: Final[str] = "definition_seed_service"

DATASET_DOCUMENT_TYPES: Final[str] = "document_types"
DATASET_VARIABLES: Final[str] = "variables"
DATASET_UNITS: Final[str] = "units"
DATASET_MATERIALS: Final[str] = "materials"
DATASET_OBJECT_KINDS: Final[str] = "object_kinds"
DATASET_FAMILY_PROFILES: Final[str] = "family_profiles"
DATASET_VARIANT_PROFILES: Final[str] = "variant_profiles"
DATASET_PROFILE_BINDINGS: Final[str] = "profile_bindings"

DEFAULT_DATASET_ORDER: Final[tuple[str, ...]] = (
    DATASET_UNITS,
    DATASET_DOCUMENT_TYPES,
    DATASET_MATERIALS,
    DATASET_OBJECT_KINDS,
    DATASET_VARIABLES,
    DATASET_FAMILY_PROFILES,
    DATASET_VARIANT_PROFILES,
    DATASET_PROFILE_BINDINGS,
)

DEFAULT_DATASET_FILENAMES: Final[dict[str, str]] = {
    DATASET_DOCUMENT_TYPES: "document_types.v1.json",
    DATASET_VARIABLES: "variables.v1.json",
    DATASET_UNITS: "units.v1.json",
    DATASET_MATERIALS: "materials.v1.json",
    DATASET_OBJECT_KINDS: "object_kinds.v1.json",
    DATASET_FAMILY_PROFILES: "family_profiles.v1.json",
    DATASET_VARIANT_PROFILES: "variant_profiles.v1.json",
    DATASET_PROFILE_BINDINGS: "profile_bindings.v1.json",
}

REQUIRED_DATASET_PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "dataset",
    "items",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LibraryDefinitionSeedServiceError(RuntimeError):
    """Base error for LibraryDefinitionSeedService."""


class LibraryDefinitionSeedImportError(LibraryDefinitionSeedServiceError):
    """Raised when repository import fails."""


class LibraryDefinitionSeedFileNotFoundError(LibraryDefinitionSeedServiceError):
    """Raised when a dataset file cannot be found."""


class LibraryDefinitionSeedPayloadError(LibraryDefinitionSeedServiceError):
    """Raised when a dataset JSON payload is invalid."""


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

    raise LibraryDefinitionSeedImportError(
        "Could not import library_definition_repository. "
        + " | ".join(errors)
    )


def _repo_module() -> ModuleType:
    """Short alias for repository module."""
    return _load_repository_module()


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def clean_string(value: Any, *, fallback: str = "") -> str:
    """Converts value to safe stripped string."""
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


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """Normalizes boolean-like values."""
    if isinstance(value, bool):
        return value

    if value is None:
        return default

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive"}:
        return False

    return default


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


def item_list_from_payload(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Extracts items[] from dataset payload."""
    data = normalize_json_mapping(payload)
    items = data.get("items")

    if not isinstance(items, list):
        return []

    result: list[dict[str, Any]] = []

    for item in items:
        if isinstance(item, Mapping):
            result.append(normalize_json_mapping(item))

    return result


def infer_dataset_key_from_filename(file_path: Path | str) -> str | None:
    """Infers dataset key from filenames like variables.v1.json."""
    path = Path(file_path)
    name = path.name

    if not name.endswith(".json"):
        return None

    stem = name[:-5]
    parts = stem.split(".")

    if not parts:
        return None

    return clean_dataset_key(parts[0])


def safe_path(value: Any) -> Path:
    """Converts value to Path."""
    try:
        return Path(str(value)).expanduser()
    except Exception as exc:
        raise LibraryDefinitionSeedFileNotFoundError(f"Invalid path: {value!r}") from exc


def read_json_file(file_path: Path | str) -> dict[str, Any]:
    """Reads a JSON file as mapping."""
    path = safe_path(file_path)

    if not path.exists():
        raise LibraryDefinitionSeedFileNotFoundError(f"Definition JSON file does not exist: {path}")

    if not path.is_file():
        raise LibraryDefinitionSeedFileNotFoundError(f"Definition JSON path is not a file: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8-sig")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LibraryDefinitionSeedPayloadError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise LibraryDefinitionSeedPayloadError(f"Definition JSON root must be an object: {path}")

    return normalize_json_mapping(payload)


def validate_dataset_payload(
    payload: Mapping[str, Any],
    *,
    expected_dataset_key: Any | None = None,
    source_file_path: Any | None = None,
) -> dict[str, Any]:
    """Validates and normalizes a dataset payload."""
    data = normalize_json_mapping(payload)
    expected_key = clean_dataset_key(expected_dataset_key) if expected_dataset_key else None
    payload_key = optional_string(data.get("dataset"))

    if not payload_key and expected_key:
        data["dataset"] = expected_key
        payload_key = expected_key

    if not payload_key:
        inferred = infer_dataset_key_from_filename(source_file_path) if source_file_path else None
        if inferred:
            data["dataset"] = inferred
            payload_key = inferred

    if not payload_key:
        raise LibraryDefinitionSeedPayloadError("Dataset payload requires `dataset` field.")

    normalized_payload_key = clean_dataset_key(payload_key)

    if expected_key and normalized_payload_key != expected_key:
        raise LibraryDefinitionSeedPayloadError(
            f"Dataset mismatch: expected {expected_key!r}, got {normalized_payload_key!r}."
        )

    data["dataset"] = normalized_payload_key

    items = data.get("items")
    if not isinstance(items, list):
        raise LibraryDefinitionSeedPayloadError(
            f"Dataset {normalized_payload_key!r} requires `items` list."
        )

    data["items"] = [
        normalize_json_mapping(item)
        for item in items
        if isinstance(item, Mapping)
    ]

    data.setdefault("definitions_version", DEFAULT_DEFINITIONS_VERSION)

    if source_file_path:
        data["_source_file_path"] = str(source_file_path)

    return data


def default_definition_data_dir() -> Path:
    """
    Resolves default definitions data directory.

    Expected file location:

        src/library/services/library_definition_seed_service.py

    Expected data path:

        src/library/definitions/data
    """
    current = Path(__file__).resolve()

    candidates = (
        current.parents[1] / "definitions" / "data",
        current.parents[2] / "library" / "definitions" / "data",
        Path.cwd() / "src" / "library" / "definitions" / "data",
        Path.cwd() / "library" / "definitions" / "data",
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    return candidates[0]


def dataset_filename(dataset_key: Any, *, definitions_version: Any = DEFAULT_DEFINITIONS_VERSION) -> str:
    """Returns expected dataset filename."""
    key = clean_dataset_key(dataset_key)
    version = clean_string(definitions_version, fallback=DEFAULT_DEFINITIONS_VERSION)

    default_name = DEFAULT_DATASET_FILENAMES.get(key)
    if default_name and version == DEFAULT_DEFINITIONS_VERSION:
        return default_name

    return f"{key}.{version}.json"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DefinitionSeedOptions:
    """Options for seed operation."""

    data_dir: Path | None = None
    dataset_keys: tuple[str, ...] = DEFAULT_DATASET_ORDER
    definitions_version: str = DEFAULT_DEFINITIONS_VERSION
    source_scope: str = DEFAULT_SOURCE_SCOPE
    owner_user_id: int | None = None
    triggered_by: str = DEFAULT_TRIGGERED_BY
    deprecated_missing_system_items: bool = False
    strict: bool = False
    dry_run: bool = False
    commit: bool = True
    continue_on_error: bool = True

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None = None, **kwargs: Any) -> "DefinitionSeedOptions":
        data = normalize_json_mapping(payload)
        data.update({key: value for key, value in kwargs.items() if value is not None})

        raw_dataset_keys = data.get("dataset_keys") or data.get("datasets") or DEFAULT_DATASET_ORDER

        dataset_keys = tuple(
            clean_dataset_key(value)
            for value in normalize_json_list(raw_dataset_keys)
            if clean_string(value)
        )

        return cls(
            data_dir=safe_path(data["data_dir"]) if data.get("data_dir") else None,
            dataset_keys=dataset_keys or DEFAULT_DATASET_ORDER,
            definitions_version=clean_string(data.get("definitions_version"), fallback=DEFAULT_DEFINITIONS_VERSION),
            source_scope=clean_string(data.get("source_scope"), fallback=DEFAULT_SOURCE_SCOPE),
            owner_user_id=normalize_int(data.get("owner_user_id"), default=None, minimum=1),
            triggered_by=clean_string(data.get("triggered_by"), fallback=DEFAULT_TRIGGERED_BY),
            deprecated_missing_system_items=normalize_bool(data.get("deprecated_missing_system_items"), default=False),
            strict=normalize_bool(data.get("strict"), default=False),
            dry_run=normalize_bool(data.get("dry_run"), default=False),
            commit=normalize_bool(data.get("commit"), default=True),
            continue_on_error=normalize_bool(data.get("continue_on_error"), default=True),
        )

    def resolved_data_dir(self) -> Path:
        return self.data_dir or default_definition_data_dir()

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_dir": str(self.resolved_data_dir()),
            "dataset_keys": list(self.dataset_keys),
            "definitions_version": self.definitions_version,
            "source_scope": self.source_scope,
            "owner_user_id": self.owner_user_id,
            "triggered_by": self.triggered_by,
            "deprecated_missing_system_items": self.deprecated_missing_system_items,
            "strict": self.strict,
            "dry_run": self.dry_run,
            "commit": self.commit,
            "continue_on_error": self.continue_on_error,
        }


@dataclass(slots=True)
class DefinitionSeedDatasetResult:
    """Result for one seeded dataset."""

    dataset_key: str
    file_path: str | None = None
    dataset_id: int | None = None
    item_count: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    deprecated_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    dry_run: bool = False
    errors: list[str] = field(default_factory=list)
    definition_keys: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def add_error(self, message: Any) -> None:
        self.error_count += 1
        self.errors.append(str(message))

    @classmethod
    def from_repository_result(
        cls,
        repository_result: Any,
        *,
        dataset_key: Any,
        file_path: Any = None,
        dry_run: bool = False,
    ) -> "DefinitionSeedDatasetResult":
        if hasattr(repository_result, "to_dict") and callable(repository_result.to_dict):
            data = normalize_json_mapping(repository_result.to_dict())
        elif isinstance(repository_result, Mapping):
            data = normalize_json_mapping(repository_result)
        else:
            data = {}

        return cls(
            dataset_key=clean_dataset_key(data.get("dataset_key") or dataset_key),
            file_path=str(file_path) if file_path else None,
            dataset_id=normalize_int(data.get("dataset_id"), default=None, minimum=1),
            item_count=normalize_int(data.get("item_count") or data.get("total_count"), default=0, minimum=0) or 0,
            inserted_count=normalize_int(data.get("inserted_count"), default=0, minimum=0) or 0,
            updated_count=normalize_int(data.get("updated_count"), default=0, minimum=0) or 0,
            unchanged_count=normalize_int(data.get("unchanged_count"), default=0, minimum=0) or 0,
            deprecated_count=normalize_int(data.get("deprecated_count"), default=0, minimum=0) or 0,
            skipped_count=normalize_int(data.get("skipped_count"), default=0, minimum=0) or 0,
            error_count=normalize_int(data.get("error_count"), default=0, minimum=0) or 0,
            dry_run=dry_run,
            errors=[str(error) for error in normalize_json_list(data.get("errors"))],
            definition_keys=[str(key) for key in normalize_json_list(data.get("definition_keys"))],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LIBRARY_DEFINITION_SEED_SERVICE_VERSION,
            "ok": self.ok,
            "dataset_key": self.dataset_key,
            "file_path": self.file_path,
            "dataset_id": self.dataset_id,
            "item_count": self.item_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "deprecated_count": self.deprecated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "dry_run": self.dry_run,
            "definition_keys": list(self.definition_keys),
            "errors": list(self.errors),
        }


@dataclass(slots=True)
class DefinitionSeedResult:
    """Result for a full seed operation."""

    options: DefinitionSeedOptions
    seed_run_id: int | None = None
    seed_run_uid: str | None = None
    status: str = "pending"
    dataset_results: list[DefinitionSeedDatasetResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def dataset_count(self) -> int:
        return len(self.dataset_results)

    @property
    def item_count(self) -> int:
        return sum(result.item_count for result in self.dataset_results)

    @property
    def inserted_count(self) -> int:
        return sum(result.inserted_count for result in self.dataset_results)

    @property
    def updated_count(self) -> int:
        return sum(result.updated_count for result in self.dataset_results)

    @property
    def unchanged_count(self) -> int:
        return sum(result.unchanged_count for result in self.dataset_results)

    @property
    def deprecated_count(self) -> int:
        return sum(result.deprecated_count for result in self.dataset_results)

    @property
    def skipped_count(self) -> int:
        return sum(result.skipped_count for result in self.dataset_results)

    @property
    def error_count(self) -> int:
        return len(self.errors) + sum(result.error_count for result in self.dataset_results)

    @property
    def ok(self) -> bool:
        return self.error_count == 0

    def add_dataset_result(self, result: DefinitionSeedDatasetResult) -> None:
        self.dataset_results.append(result)

    def add_error(self, message: Any) -> None:
        self.errors.append(str(message))

    def finish_status(self) -> str:
        if self.options.dry_run:
            return "skipped"

        if self.error_count <= 0:
            return "completed"

        if self.dataset_results:
            return "partial"

        return "failed"

    def counts_payload(self) -> dict[str, Any]:
        return {
            "dataset_count": self.dataset_count,
            "item_count": self.item_count,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "deprecated_count": self.deprecated_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
        }

    def summary_payload(self) -> dict[str, Any]:
        return {
            "schema_version": LIBRARY_DEFINITION_SEED_SERVICE_VERSION,
            "status": self.status,
            "ok": self.ok,
            "seed_run_id": self.seed_run_id,
            "seed_run_uid": self.seed_run_uid,
            "options": self.options.to_dict(),
            "counts": self.counts_payload(),
            "datasets": [result.to_dict() for result in self.dataset_results],
            "errors": list(self.errors),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.summary_payload()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class LibraryDefinitionSeedService:
    """
    Service for idempotent import of definition JSON files.

    Args:
        repository:
            Optional LibraryDefinitionRepository instance.
        data_dir:
            Optional default data directory.
    """

    def __init__(self, repository: Any | None = None, data_dir: Path | str | None = None) -> None:
        self.repository = repository or self._create_repository()
        self.data_dir = safe_path(data_dir) if data_dir is not None else default_definition_data_dir()

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
            raise LibraryDefinitionSeedImportError("LibraryDefinitionRepository class is not available.")

        return repo_class()

    # ------------------------------------------------------------------
    # File discovery
    # ------------------------------------------------------------------

    def get_data_dir(self, data_dir: Path | str | None = None) -> Path:
        """Returns effective data directory."""
        return safe_path(data_dir) if data_dir is not None else self.data_dir

    def get_dataset_file(
        self,
        dataset_key: Any,
        *,
        data_dir: Path | str | None = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
        required: bool = True,
    ) -> Path | None:
        """Resolves dataset JSON file path."""
        key = clean_dataset_key(dataset_key)
        root = self.get_data_dir(data_dir)
        filename = dataset_filename(key, definitions_version=definitions_version)

        candidates = [
            root / filename,
            root / DEFAULT_DATASET_FILENAMES.get(key, filename),
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        if required:
            raise LibraryDefinitionSeedFileNotFoundError(
                f"Could not find definition dataset file for {key!r} in {root}."
            )

        return None

    def list_dataset_files(
        self,
        *,
        data_dir: Path | str | None = None,
        dataset_keys: Iterable[Any] | None = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
        required: bool = False,
    ) -> list[Path]:
        """Lists available dataset files in configured order."""
        keys = tuple(clean_dataset_key(key) for key in (dataset_keys or DEFAULT_DATASET_ORDER))
        result: list[Path] = []

        for key in keys:
            path = self.get_dataset_file(
                key,
                data_dir=data_dir,
                definitions_version=definitions_version,
                required=required,
            )
            if path is not None:
                result.append(path)

        return result

    def load_dataset_payload(
        self,
        dataset_key: Any,
        *,
        file_path: Path | str | None = None,
        data_dir: Path | str | None = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
    ) -> dict[str, Any]:
        """Loads and validates one dataset payload."""
        key = clean_dataset_key(dataset_key)
        path = safe_path(file_path) if file_path is not None else self.get_dataset_file(
            key,
            data_dir=data_dir,
            definitions_version=definitions_version,
            required=True,
        )

        payload = read_json_file(path)

        return validate_dataset_payload(
            payload,
            expected_dataset_key=key,
            source_file_path=path,
        )

    def load_file_payload(self, file_path: Path | str) -> tuple[str, dict[str, Any]]:
        """Loads and validates any dataset file."""
        path = safe_path(file_path)
        inferred_key = infer_dataset_key_from_filename(path)
        payload = read_json_file(path)
        validated = validate_dataset_payload(
            payload,
            expected_dataset_key=inferred_key,
            source_file_path=path,
        )
        return clean_dataset_key(validated.get("dataset")), validated

    # ------------------------------------------------------------------
    # Seed operations
    # ------------------------------------------------------------------

    def seed_all(
        self,
        *,
        options: DefinitionSeedOptions | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Seeds all configured datasets.

        Returns JSON-compatible result payload.
        """
        seed_options = (
            options
            if isinstance(options, DefinitionSeedOptions)
            else DefinitionSeedOptions.from_payload(options, **kwargs)
        )

        if seed_options.data_dir is None:
            seed_options.data_dir = self.data_dir

        result = DefinitionSeedResult(options=seed_options, status="running")
        seed_run = None

        try:
            if not seed_options.dry_run:
                seed_run = self.repository.start_seed_run(
                    source_label="library_definitions",
                    source_root=str(seed_options.resolved_data_dir()),
                    triggered_by=seed_options.triggered_by,
                    definitions_version=seed_options.definitions_version,
                    metadata={
                        "schema_version": LIBRARY_DEFINITION_SEED_SERVICE_VERSION,
                        "dataset_keys": list(seed_options.dataset_keys),
                        "source_scope": seed_options.source_scope,
                        "owner_user_id": seed_options.owner_user_id,
                    },
                    commit=False,
                )
                result.seed_run_id = getattr(seed_run, "id", None)
                result.seed_run_uid = getattr(seed_run, "run_uid", None)

            for dataset_key in seed_options.dataset_keys:
                try:
                    dataset_result = self.seed_dataset(
                        dataset_key,
                        options=seed_options,
                        commit=False,
                    )
                    result.add_dataset_result(dataset_result)

                except Exception as exc:
                    message = f"{dataset_key}: {type(exc).__name__}: {exc}"
                    result.add_error(message)

                    if seed_options.strict or not seed_options.continue_on_error:
                        raise

            result.status = result.finish_status()

            if not seed_options.dry_run and seed_run is not None:
                self.repository.apply_seed_run_counts(
                    seed_run,
                    counts=result.counts_payload(),
                    commit=False,
                )
                self.repository.finish_seed_run(
                    seed_run,
                    status=result.status,
                    summary=result.summary_payload(),
                    errors=result.errors,
                    commit=False,
                )

                if seed_options.commit:
                    self.repository.commit()
                else:
                    self.repository.flush()

            return result.to_dict()

        except Exception:
            result.status = "failed"

            if not seed_options.dry_run:
                try:
                    self.repository.rollback()
                except Exception:
                    pass

                try:
                    failed_run = self.repository.start_seed_run(
                        source_label="library_definitions",
                        source_root=str(seed_options.resolved_data_dir()),
                        triggered_by=seed_options.triggered_by,
                        definitions_version=seed_options.definitions_version,
                        metadata={
                            "schema_version": LIBRARY_DEFINITION_SEED_SERVICE_VERSION,
                            "failed": True,
                            "errors": list(result.errors),
                        },
                        commit=False,
                    )
                    failed_run_id = getattr(failed_run, "id", None)
                    failed_run_uid = getattr(failed_run, "run_uid", None)
                    self.repository.finish_seed_run(
                        failed_run,
                        status="failed",
                        summary=result.summary_payload(),
                        errors=result.errors,
                        commit=seed_options.commit,
                    )
                    result.seed_run_id = result.seed_run_id or failed_run_id
                    result.seed_run_uid = result.seed_run_uid or failed_run_uid
                except Exception:
                    try:
                        self.repository.rollback()
                    except Exception:
                        pass

            raise

    def seed_dataset(
        self,
        dataset_key: Any,
        *,
        options: DefinitionSeedOptions | None = None,
        file_path: Path | str | None = None,
        payload: Mapping[str, Any] | None = None,
        commit: bool = False,
    ) -> DefinitionSeedDatasetResult:
        """Seeds one dataset."""
        seed_options = options or DefinitionSeedOptions(data_dir=self.data_dir)
        key = clean_dataset_key(dataset_key)

        resolved_file_path: Path | None = None

        if payload is None:
            resolved_file_path = safe_path(file_path) if file_path is not None else self.get_dataset_file(
                key,
                data_dir=seed_options.resolved_data_dir(),
                definitions_version=seed_options.definitions_version,
                required=True,
            )
            dataset_payload = self.load_dataset_payload(
                key,
                file_path=resolved_file_path,
                definitions_version=seed_options.definitions_version,
            )
        else:
            dataset_payload = validate_dataset_payload(
                payload,
                expected_dataset_key=key,
                source_file_path=file_path,
            )
            resolved_file_path = safe_path(file_path) if file_path is not None else None

        items = item_list_from_payload(dataset_payload)

        if seed_options.dry_run:
            return DefinitionSeedDatasetResult(
                dataset_key=key,
                file_path=str(resolved_file_path) if resolved_file_path else None,
                item_count=len(items),
                skipped_count=len(items),
                dry_run=True,
                definition_keys=self._extract_definition_keys_for_preview(key, items),
            )

        repository_result = self.repository.bulk_upsert_dataset_items(
            key,
            dataset_payload,
            source_file_path=str(resolved_file_path) if resolved_file_path else None,
            source_scope=seed_options.source_scope,
            owner_user_id=seed_options.owner_user_id,
            created_by_user_id=None,
            updated_by_user_id=None,
            deprecated_missing_system_items=seed_options.deprecated_missing_system_items,
            commit=commit,
        )

        result = DefinitionSeedDatasetResult.from_repository_result(
            repository_result,
            dataset_key=key,
            file_path=resolved_file_path,
            dry_run=False,
        )
        result.item_count = len(items)
        return result

    def seed_file(
        self,
        file_path: Path | str,
        *,
        options: DefinitionSeedOptions | None = None,
        commit: bool = False,
    ) -> DefinitionSeedDatasetResult:
        """Seeds one arbitrary dataset JSON file."""
        key, payload = self.load_file_payload(file_path)

        return self.seed_dataset(
            key,
            options=options,
            file_path=file_path,
            payload=payload,
            commit=commit,
        )

    def seed_files(
        self,
        file_paths: Iterable[Path | str],
        *,
        options: DefinitionSeedOptions | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Seeds explicit dataset files."""
        seed_options = options or DefinitionSeedOptions(data_dir=self.data_dir, commit=commit)
        result = DefinitionSeedResult(options=seed_options, status="running")

        try:
            for file_path in file_paths:
                try:
                    dataset_result = self.seed_file(
                        file_path,
                        options=seed_options,
                        commit=False,
                    )
                    result.add_dataset_result(dataset_result)
                except Exception as exc:
                    result.add_error(f"{file_path}: {type(exc).__name__}: {exc}")
                    if seed_options.strict or not seed_options.continue_on_error:
                        raise

            result.status = result.finish_status()

            if not seed_options.dry_run:
                if commit:
                    self.repository.commit()
                else:
                    self.repository.flush()

            return result.to_dict()

        except Exception:
            if not seed_options.dry_run:
                try:
                    self.repository.rollback()
                except Exception:
                    pass
            raise

    # ------------------------------------------------------------------
    # Preview / validation
    # ------------------------------------------------------------------

    def preview_seed_all(
        self,
        *,
        data_dir: Path | str | None = None,
        dataset_keys: Iterable[Any] | None = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
    ) -> dict[str, Any]:
        """Parses seed files without DB writes."""
        options = DefinitionSeedOptions(
            data_dir=safe_path(data_dir) if data_dir is not None else self.data_dir,
            dataset_keys=tuple(clean_dataset_key(key) for key in (dataset_keys or DEFAULT_DATASET_ORDER)),
            definitions_version=clean_string(definitions_version, fallback=DEFAULT_DEFINITIONS_VERSION),
            dry_run=True,
            commit=False,
        )

        return self.seed_all(options=options)

    def validate_dataset_files(
        self,
        *,
        data_dir: Path | str | None = None,
        dataset_keys: Iterable[Any] | None = None,
        definitions_version: Any = DEFAULT_DEFINITIONS_VERSION,
    ) -> dict[str, Any]:
        """Validates all configured dataset files without DB writes."""
        root = self.get_data_dir(data_dir)
        keys = tuple(clean_dataset_key(key) for key in (dataset_keys or DEFAULT_DATASET_ORDER))

        results: list[dict[str, Any]] = []
        errors: list[str] = []

        for key in keys:
            try:
                file_path = self.get_dataset_file(
                    key,
                    data_dir=root,
                    definitions_version=definitions_version,
                    required=True,
                )
                payload = self.load_dataset_payload(
                    key,
                    file_path=file_path,
                    definitions_version=definitions_version,
                )
                items = item_list_from_payload(payload)

                results.append(
                    {
                        "dataset_key": key,
                        "file_path": str(file_path),
                        "valid": True,
                        "item_count": len(items),
                        "definitions_version": payload.get("definitions_version"),
                    }
                )
            except Exception as exc:
                message = f"{key}: {type(exc).__name__}: {exc}"
                errors.append(message)
                results.append(
                    {
                        "dataset_key": key,
                        "file_path": None,
                        "valid": False,
                        "item_count": 0,
                        "error": message,
                    }
                )

        return {
            "schema_version": LIBRARY_DEFINITION_SEED_SERVICE_VERSION,
            "ok": not errors,
            "data_dir": str(root),
            "definitions_version": clean_string(definitions_version, fallback=DEFAULT_DEFINITIONS_VERSION),
            "dataset_count": len(results),
            "valid_count": len([result for result in results if result.get("valid")]),
            "error_count": len(errors),
            "datasets": results,
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health(self) -> dict[str, Any]:
        """Returns service health snapshot."""
        data_dir = self.get_data_dir()

        try:
            repository_health = self.repository.get_health() if hasattr(self.repository, "get_health") else {}
        except Exception as exc:
            repository_health = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        available_files = []
        missing_files = []

        for dataset_key in DEFAULT_DATASET_ORDER:
            path = self.get_dataset_file(dataset_key, required=False)
            if path is not None:
                available_files.append(str(path))
            else:
                missing_files.append(dataset_filename(dataset_key))

        return {
            "schema_version": LIBRARY_DEFINITION_SEED_SERVICE_VERSION,
            "ok": True,
            "service": type(self).__name__,
            "data_dir": str(data_dir),
            "data_dir_exists": data_dir.exists(),
            "dataset_order": list(DEFAULT_DATASET_ORDER),
            "available_files": available_files,
            "available_file_count": len(available_files),
            "missing_files": missing_files,
            "missing_file_count": len(missing_files),
            "repository_health": repository_health,
            "supports_seed_all": True,
            "supports_seed_dataset": True,
            "supports_seed_files": True,
            "supports_preview": True,
            "supports_validation": True,
            "supports_deprecate_missing_system_items": True,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _extract_definition_keys_for_preview(
        self,
        dataset_key: Any,
        items: Iterable[Mapping[str, Any]],
    ) -> list[str]:
        """Extracts definition keys using repository helper where possible."""
        repo_module = _repo_module()
        helper = getattr(repo_module, "definition_key_from_item", None)
        result: list[str] = []

        for item in items:
            try:
                if callable(helper):
                    result.append(str(helper(dataset_key, item)))
                else:
                    result.append(clean_string(item.get("key") or item.get("id")))
            except Exception:
                continue

        return [key for key in result if key]


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def create_library_definition_seed_service(
    repository: Any | None = None,
    data_dir: Path | str | None = None,
) -> LibraryDefinitionSeedService:
    """Factory for dependency injection."""
    return LibraryDefinitionSeedService(repository=repository, data_dir=data_dir)


@lru_cache(maxsize=1)
def get_service_version() -> str:
    """Cached service version helper."""
    return LIBRARY_DEFINITION_SEED_SERVICE_VERSION


def clear_library_definition_seed_service_caches() -> dict[str, Any]:
    """Clears service caches."""
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
    "LIBRARY_DEFINITION_SEED_SERVICE_VERSION",
    "DEFAULT_DEFINITIONS_VERSION",
    "DEFAULT_SOURCE_SCOPE",
    "DEFAULT_TRIGGERED_BY",
    "DATASET_DOCUMENT_TYPES",
    "DATASET_VARIABLES",
    "DATASET_UNITS",
    "DATASET_MATERIALS",
    "DATASET_OBJECT_KINDS",
    "DATASET_FAMILY_PROFILES",
    "DATASET_VARIANT_PROFILES",
    "DATASET_PROFILE_BINDINGS",
    "DEFAULT_DATASET_ORDER",
    "DEFAULT_DATASET_FILENAMES",

    # Exceptions
    "LibraryDefinitionSeedServiceError",
    "LibraryDefinitionSeedImportError",
    "LibraryDefinitionSeedFileNotFoundError",
    "LibraryDefinitionSeedPayloadError",

    # Dataclasses
    "DefinitionSeedOptions",
    "DefinitionSeedDatasetResult",
    "DefinitionSeedResult",

    # Service
    "LibraryDefinitionSeedService",
    "create_library_definition_seed_service",

    # Helpers
    "clean_string",
    "optional_string",
    "normalize_bool",
    "normalize_int",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "clean_dataset_key",
    "item_list_from_payload",
    "infer_dataset_key_from_filename",
    "safe_path",
    "read_json_file",
    "validate_dataset_payload",
    "default_definition_data_dir",
    "dataset_filename",
    "get_service_version",
    "clear_library_definition_seed_service_caches",
]