# services/vectoplan-library/src/config/library_settings.py
"""
Library Settings für die fachliche Creative-Library-Schicht.

Diese Datei konfiguriert die neue `/src/library`-Ebene, die oberhalb des
bestehenden `/src/vplib`-Kerns arbeitet.

Zuständigkeit dieser Datei:

- Pfade für `src/library/source`
- Pfade für spätere `creative_library`
- Route-Prefix und Route-Pfade für Library-APIs
- Scan-Verhalten für Block-/Objektpakete
- Reader-Verhalten für VPLIB-Package-Dokumente
- Taxonomie-Verhalten für Reiter/Kategorie/Subkategorie
- robuste ENV-Auswertung
- JSON-kompatible Settings-Summaries
- defensive Directory-Checks
- Settings-Cache mit Reset-Funktion

Diese Datei führt bewusst keinen Scan aus und schreibt standardmäßig nichts
ins Dateisystem. Sie ist reine Konfiguration und sicher beim Import.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Source-Pfad
    - Navigation
    - Labels
    - Sortierung

Kanonischer Source-Pfad:

    src/library/source/{domain}/{category}/{subcategory}/{family_slug}/

Version 0.2.0:

- `family/classification.json` ist Pflichtdatei.
- ScanOptions enthalten Taxonomie-, Reader- und Discovery-Flags.
- ReadOptions enthalten Taxonomie- und Tree-Flags.
- RoutePlan enthält Cache-Clear-Route.
- Settings enthalten `taxonomy_options`.
- ENV-Aliase für Taxonomie, leere Tree-Knoten, Legacy-Pfade und Reader ergänzt.
- Health zeigt Taxonomieoptionen und Source-Pfad-Regeln.
"""

from __future__ import annotations

import os
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_SETTINGS_VERSION: Final[str] = "0.2.0"
LIBRARY_SETTINGS_COMPONENT: Final[str] = "library-settings"

DEFAULT_LIBRARY_ROUTE_PREFIX: Final[str] = "/api/v1/vplib/library"

DEFAULT_HEALTH_ROUTE_PATH: Final[str] = "/health"
DEFAULT_SCAN_ROUTE_PATH: Final[str] = "/scan"
DEFAULT_BLOCKS_ROUTE_PATH: Final[str] = "/blocks"
DEFAULT_TREE_ROUTE_PATH: Final[str] = "/tree"
DEFAULT_CACHE_CLEAR_ROUTE_PATH: Final[str] = "/cache/clear"

DEFAULT_BLOCK_DETAIL_ROUTE_TEMPLATE: Final[str] = "/blocks/<block_id>"
DEFAULT_BLOCK_VARIANTS_ROUTE_TEMPLATE: Final[str] = "/blocks/<block_id>/variants"

DEFAULT_SOURCE_DIRECTORY_RELATIVE: Final[str] = "src/library/source"
DEFAULT_LIBRARY_PACKAGE_DIRECTORY_RELATIVE: Final[str] = "src/library"
DEFAULT_CREATIVE_LIBRARY_DIRECTORY_RELATIVE: Final[str] = "creative_library"
DEFAULT_GENERATED_LIBRARY_DIRECTORY_RELATIVE: Final[str] = "generated/library"
DEFAULT_LIBRARY_CACHE_DIRECTORY_RELATIVE: Final[str] = "generated/library_cache"

CANONICAL_SOURCE_DEPTH: Final[int] = 4
LEGACY_SOURCE_DEPTH: Final[int] = 3
CANONICAL_SOURCE_PATH_PATTERN: Final[str] = "{domain}/{category}/{subcategory}/{family_slug}"
LEGACY_SOURCE_PATH_PATTERN: Final[str] = "{domain}/{category}/{family_slug}"

DEFAULT_SCAN_RECURSIVE: Final[bool] = True
DEFAULT_SCAN_MAX_DEPTH: Final[int] = 12
DEFAULT_SCAN_FOLLOW_SYMLINKS: Final[bool] = False
DEFAULT_INCLUDE_INVALID_IN_SCAN: Final[bool] = True
DEFAULT_AUTO_SCAN_ON_REQUEST: Final[bool] = True
DEFAULT_FAIL_ON_DUPLICATE_IDS: Final[bool] = True
DEFAULT_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY: Final[bool] = True

DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT: Final[bool] = True
DEFAULT_VALIDATE_TAXONOMY_PATH: Final[bool] = True
DEFAULT_READ_MINIMAL_METADATA: Final[bool] = True

DEFAULT_READ_ALL_JSON_DOCUMENTS: Final[bool] = True
DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES: Final[bool] = True
DEFAULT_FAIL_ON_JSON_ERROR: Final[bool] = False
DEFAULT_FAIL_ON_MISSING_REQUIRED: Final[bool] = False
DEFAULT_MAX_JSON_FILE_SIZE_BYTES: Final[int] = 5 * 1024 * 1024
MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT: Final[int] = 100 * 1024 * 1024
DEFAULT_TEXT_ENCODING: Final[str] = "utf-8-sig"
DEFAULT_PRESERVE_DISCOVERY_METADATA: Final[bool] = True

DEFAULT_LIST_INCLUDE_INVALID: Final[bool] = False
DEFAULT_DETAIL_INCLUDE_RAW_DOCUMENTS: Final[bool] = True
DEFAULT_DETAIL_INCLUDE_VALIDATION_REPORT: Final[bool] = True
DEFAULT_USE_TAXONOMY_LABELS: Final[bool] = True
DEFAULT_INCLUDE_EMPTY_TAXONOMY_NODES: Final[bool] = False
DEFAULT_INCLUDE_INACTIVE_TAXONOMY_NODES: Final[bool] = False
DEFAULT_INCLUDE_TAXONOMY_PAYLOAD: Final[bool] = False
DEFAULT_FORCE_TAXONOMY_RELOAD: Final[bool] = False
DEFAULT_VALIDATE_TAXONOMY: Final[bool] = True
DEFAULT_REQUIRE_TAXONOMY: Final[bool] = True

DEFAULT_CACHE_ENABLED: Final[bool] = False
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 5
MAX_CACHE_TTL_SECONDS: Final[int] = 86400

DEFAULT_ALLOWED_MANIFEST_FILENAMES: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
)

DEFAULT_REQUIRED_PACKAGE_FILES: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
    "vplib.modules.json",
    "family/identity.json",
    "family/classification.json",
    "variants/index.json",
    "variants/default.json",
)

DEFAULT_OPTIONAL_SUMMARY_FILES: Final[tuple[str, ...]] = (
    "family/lifecycle.json",
    "family/aliases.json",
    "family/metadata.json",
    "editor/inventory.json",
    "editor/placement.json",
    "render/render_variants.json",
    "render/bounds.json",
    "render/materials.json",
    "physical/base.json",
    "physical/dimensions.json",
    "physical/collision.json",
    "material/base.json",
    "calculation/variables.json",
    "calculation/formulas.json",
    "calculation/quantities.json",
    "calculation/measure_logic.json",
    "manufacturer/contract.json",
)

DEFAULT_IGNORED_DIRECTORY_NAMES: Final[tuple[str, ...]] = (
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "tmp",
    "temp",
)

DEFAULT_IGNORED_FILE_SUFFIXES: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
)

ENV_SERVICE_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SERVICE_ROOT",
    "LIBRARY_SERVICE_ROOT",
)

ENV_SRC_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SRC_ROOT",
    "LIBRARY_SRC_ROOT",
)

ENV_LIBRARY_PACKAGE_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_PACKAGE_ROOT",
    "VECTOPLAN_LIBRARY_LIBRARY_ROOT",
    "LIBRARY_PACKAGE_ROOT",
    "LIBRARY_ROOT",
)

ENV_SOURCE_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SOURCE_ROOT",
    "VPLIB_CREATE_SOURCE_ROOT",
    "VPLIB_LIBRARY_SOURCE_ROOT",
    "LIBRARY_SOURCE_ROOT",
    "LIBRARY_SRC_SOURCE_ROOT",
)

ENV_CREATIVE_LIBRARY_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_CREATIVE_ROOT",
    "VECTOPLAN_CREATIVE_LIBRARY_ROOT",
    "VPLIB_CREATIVE_LIBRARY_ROOT",
    "LIBRARY_CREATIVE_ROOT",
    "CREATIVE_LIBRARY_ROOT",
)

ENV_GENERATED_LIBRARY_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_GENERATED_ROOT",
    "VPLIB_LIBRARY_GENERATED_ROOT",
    "LIBRARY_GENERATED_ROOT",
)

ENV_LIBRARY_CACHE_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_CACHE_ROOT",
    "VPLIB_LIBRARY_CACHE_ROOT",
    "LIBRARY_CACHE_ROOT",
)

ENV_ROUTE_PREFIX_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_ROUTE_PREFIX",
    "VPLIB_LIBRARY_ROUTE_PREFIX",
    "LIBRARY_ROUTE_PREFIX",
)

ENV_RUN_MODE_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_RUN_MODE",
    "LIBRARY_RUN_MODE",
    "FLASK_ENV",
)

ENV_LIBRARY_TAXONOMY_ROOT_ALIASES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_TAXONOMY_ROOT",
    "VPLIB_LIBRARY_TAXONOMY_ROOT",
    "LIBRARY_TAXONOMY_ROOT",
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryDirectoryPlan:
    """Zentrale Pfadkonfiguration der Creative-Library-Schicht."""

    service_root: Path
    src_root: Path
    library_package_root: Path
    source_root: Path
    creative_library_root: Path
    generated_library_root: Path
    library_cache_root: Path
    taxonomy_root: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "service_root": str(self.service_root),
            "src_root": str(self.src_root),
            "library_package_root": str(self.library_package_root),
            "source_root": str(self.source_root),
            "creative_library_root": str(self.creative_library_root),
            "generated_library_root": str(self.generated_library_root),
            "library_cache_root": str(self.library_cache_root),
            "taxonomy_root": str(self.taxonomy_root),
        }


@dataclass(frozen=True)
class LibraryRoutePlan:
    """
    Route-Konfiguration für die Library-API.

    Der Prefix wird separat gehalten, damit Flask-Blueprints sauber mit
    `url_prefix` registriert werden können.
    """

    route_prefix: str
    health_route_path: str
    scan_route_path: str
    blocks_route_path: str
    tree_route_path: str
    cache_clear_route_path: str
    block_detail_route_template: str
    block_variants_route_template: str

    @property
    def health_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.health_route_path)

    @property
    def scan_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.scan_route_path)

    @property
    def blocks_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.blocks_route_path)

    @property
    def tree_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.tree_route_path)

    @property
    def cache_clear_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.cache_clear_route_path)

    @property
    def block_detail_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.block_detail_route_template)

    @property
    def block_variants_full_path(self) -> str:
        return join_route_path(self.route_prefix, self.block_variants_route_template)

    def to_dict(self) -> dict[str, str]:
        return {
            "route_prefix": self.route_prefix,
            "health_route_path": self.health_route_path,
            "scan_route_path": self.scan_route_path,
            "blocks_route_path": self.blocks_route_path,
            "tree_route_path": self.tree_route_path,
            "cache_clear_route_path": self.cache_clear_route_path,
            "block_detail_route_template": self.block_detail_route_template,
            "block_variants_route_template": self.block_variants_route_template,
            "health_full_path": self.health_full_path,
            "scan_full_path": self.scan_full_path,
            "blocks_full_path": self.blocks_full_path,
            "tree_full_path": self.tree_full_path,
            "cache_clear_full_path": self.cache_clear_full_path,
            "block_detail_full_path": self.block_detail_full_path,
            "block_variants_full_path": self.block_variants_full_path,
        }


@dataclass(frozen=True)
class LibraryTaxonomyOptions:
    """Zentrale Taxonomie-Optionen für Scan, Read-Models und Routes."""

    validate_taxonomy: bool
    require_taxonomy: bool
    validate_taxonomy_path: bool
    use_taxonomy_labels: bool
    include_empty_taxonomy_nodes: bool
    include_inactive_taxonomy_nodes: bool
    include_taxonomy_payload: bool
    force_taxonomy_reload: bool
    include_legacy_source_layout: bool
    require_canonical_source_path: bool
    require_classification_document: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "validate_taxonomy": self.validate_taxonomy,
            "require_taxonomy": self.require_taxonomy,
            "validate_taxonomy_path": self.validate_taxonomy_path,
            "use_taxonomy_labels": self.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
            "include_taxonomy_payload": self.include_taxonomy_payload,
            "force_taxonomy_reload": self.force_taxonomy_reload,
            "include_legacy_source_layout": self.include_legacy_source_layout,
            "require_canonical_source_path": self.require_canonical_source_path,
            "require_classification_document": self.require_classification_document,
            "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
            "legacy_source_depth": LEGACY_SOURCE_DEPTH,
            "canonical_source_path_pattern": CANONICAL_SOURCE_PATH_PATTERN,
            "legacy_source_path_pattern": LEGACY_SOURCE_PATH_PATTERN,
        }


@dataclass(frozen=True)
class LibraryScanOptions:
    """Steuerung für das dateibasierte Scannen von `src/library/source`."""

    recursive: bool
    max_depth: int
    follow_symlinks: bool
    include_invalid_in_scan: bool
    auto_scan_on_request: bool
    fail_on_duplicate_ids: bool
    treat_missing_source_root_as_empty: bool
    allowed_manifest_filenames: tuple[str, ...]
    required_package_files: tuple[str, ...]
    optional_summary_files: tuple[str, ...]
    ignored_directory_names: tuple[str, ...]
    ignored_file_suffixes: tuple[str, ...]

    include_legacy_source_layout: bool
    validate_taxonomy_path: bool
    read_minimal_metadata: bool

    read_all_json_documents: bool
    include_optional_summary_files: bool
    fail_on_json_error: bool
    fail_on_missing_required: bool
    max_json_file_size_bytes: int
    text_encoding: str
    preserve_discovery_metadata: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "recursive": self.recursive,
            "max_depth": self.max_depth,
            "follow_symlinks": self.follow_symlinks,
            "include_invalid_in_scan": self.include_invalid_in_scan,
            "auto_scan_on_request": self.auto_scan_on_request,
            "fail_on_duplicate_ids": self.fail_on_duplicate_ids,
            "treat_missing_source_root_as_empty": self.treat_missing_source_root_as_empty,
            "allowed_manifest_filenames": list(self.allowed_manifest_filenames),
            "required_package_files": list(self.required_package_files),
            "optional_summary_files": list(self.optional_summary_files),
            "ignored_directory_names": list(self.ignored_directory_names),
            "ignored_file_suffixes": list(self.ignored_file_suffixes),
            "include_legacy_source_layout": self.include_legacy_source_layout,
            "validate_taxonomy_path": self.validate_taxonomy_path,
            "read_minimal_metadata": self.read_minimal_metadata,
            "read_all_json_documents": self.read_all_json_documents,
            "include_optional_summary_files": self.include_optional_summary_files,
            "fail_on_json_error": self.fail_on_json_error,
            "fail_on_missing_required": self.fail_on_missing_required,
            "max_json_file_size_bytes": self.max_json_file_size_bytes,
            "text_encoding": self.text_encoding,
            "preserve_discovery_metadata": self.preserve_discovery_metadata,
        }


@dataclass(frozen=True)
class LibraryReadOptions:
    """Steuerung für API-Read-Modelle."""

    list_include_invalid: bool
    detail_include_raw_documents: bool
    detail_include_validation_report: bool

    validate_taxonomy: bool
    require_taxonomy: bool
    use_taxonomy_labels: bool
    include_empty_taxonomy_nodes: bool
    include_inactive_taxonomy_nodes: bool
    include_taxonomy_payload: bool
    force_taxonomy_reload: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "list_include_invalid": self.list_include_invalid,
            "detail_include_raw_documents": self.detail_include_raw_documents,
            "detail_include_validation_report": self.detail_include_validation_report,
            "validate_taxonomy": self.validate_taxonomy,
            "require_taxonomy": self.require_taxonomy,
            "use_taxonomy_labels": self.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
            "include_taxonomy_payload": self.include_taxonomy_payload,
            "force_taxonomy_reload": self.force_taxonomy_reload,
        }


@dataclass(frozen=True)
class LibraryCacheOptions:
    """Vorbereitung für spätere In-Memory- oder File-Cache-Nutzung."""

    enabled: bool
    ttl_seconds: int
    include_taxonomy_version_in_cache_key: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ttl_seconds": self.ttl_seconds,
            "include_taxonomy_version_in_cache_key": self.include_taxonomy_version_in_cache_key,
        }


@dataclass(frozen=True)
class LibrarySettings:
    """Gesamtsettings der neuen Library-Schicht."""

    settings_version: str
    component: str
    generated_at: str
    run_mode: str
    directory_plan: LibraryDirectoryPlan
    route_plan: LibraryRoutePlan
    taxonomy_options: LibraryTaxonomyOptions
    scan_options: LibraryScanOptions
    read_options: LibraryReadOptions
    cache_options: LibraryCacheOptions
    env_used: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings_version": self.settings_version,
            "component": self.component,
            "generated_at": self.generated_at,
            "run_mode": self.run_mode,
            "directory_plan": self.directory_plan.to_dict(),
            "route_plan": self.route_plan.to_dict(),
            "taxonomy_options": self.taxonomy_options.to_dict(),
            "scan_options": self.scan_options.to_dict(),
            "read_options": self.read_options.to_dict(),
            "cache_options": self.cache_options.to_dict(),
            "env_used": dict(self.env_used),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class DirectoryStatus:
    """JSON-kompatibler Status eines Verzeichnisses."""

    key: str
    path: str
    exists: bool
    is_directory: bool
    created: bool
    required: bool
    status: str
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "exists": self.exists,
            "is_directory": self.is_directory,
            "created": self.created,
            "required": self.required,
            "status": self.status,
            "error": json_safe(self.error),
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions JSON-kompatibel."""
    if exc is None:
        return None

    try:
        data: dict[str, Any] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

        if include_traceback:
            data["traceback"] = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )

        return data

    except Exception as serialization_exc:
        return {
            "type": "ExceptionSerializationError",
            "message": str(serialization_exc),
            "original_type": str(type(exc)),
        }


def json_safe(value: Any) -> Any:
    """Defensiver JSON-Safe-Konverter."""
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, Path):
            return str(value)

        if is_dataclass(value):
            return json_safe(asdict(value))

        if isinstance(value, Mapping):
            return {
                str(key): json_safe(item)
                for key, item in value.items()
            }

        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe(to_dict())
            except TypeError:
                return json_safe(to_dict(flat=True))

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def _clean_env_value(value: str | None) -> str | None:
    """Normalisiert ENV-Werte. Leere Strings gelten als nicht gesetzt."""
    if value is None:
        return None

    cleaned = value.strip()

    if not cleaned:
        return None

    return cleaned


def get_env_first(
    aliases: Iterable[str],
    *,
    default: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """
    Liest den ersten gesetzten ENV-Wert aus mehreren Alias-Namen.

    Rückgabe:
      (value, used_key)
    """

    source = env if env is not None else os.environ

    for key in aliases:
        try:
            value = _clean_env_value(source.get(key))
        except Exception:
            value = None

        if value is not None:
            return value, key

    return default, None


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Konvertierung für ENV-Werte."""
    try:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "enable", "active"}:
            return True

        if text in {"0", "false", "no", "n", "nein", "off", "disabled", "disable", "inactive"}:
            return False

        return default

    except Exception:
        return default


def parse_int(
    value: Any,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Robuste Integer-Konvertierung mit optionalen Grenzen."""
    try:
        if value is None:
            number = int(default)
        else:
            text = str(value).strip()
            number = int(text) if text else int(default)
    except Exception:
        number = int(default)

    try:
        if minimum is not None:
            number = max(int(minimum), number)

        if maximum is not None:
            number = min(int(maximum), number)

        return int(number)
    except Exception:
        return int(default)


def parse_csv_tuple(
    value: Any,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    """Wandelt kommagetrennte ENV-Werte in ein Tuple um."""
    if value is None:
        return default

    try:
        parts = [
            part.strip()
            for part in str(value).split(",")
            if part.strip()
        ]
    except Exception:
        return default

    if not parts:
        return default

    return tuple(parts)


def safe_resolve_path(path: Path) -> Path:
    """Best-effort-Resolve."""
    try:
        return path.expanduser().resolve()
    except Exception:
        try:
            return path.expanduser().absolute()
        except Exception:
            return path


def path_from_env_or_default(
    aliases: Iterable[str],
    *,
    default: Path,
    base: Path,
    env: Mapping[str, str] | None,
    env_used: dict[str, str],
) -> Path:
    """Liest einen Pfad aus ENV oder nutzt einen Default."""
    value, used_key = get_env_first(aliases, env=env)

    if value is None:
        return safe_resolve_path(default)

    try:
        raw_path = Path(value).expanduser()
        path = raw_path if raw_path.is_absolute() else base / raw_path

        if used_key:
            env_used[used_key] = value

        return safe_resolve_path(path)

    except Exception:
        return safe_resolve_path(default)


def normalize_route_path(value: str | None, *, default: str = "/") -> str:
    """Normalisiert einen einzelnen Route-Pfad."""
    text = _clean_env_value(value) or default
    text = text.strip()

    if not text.startswith("/"):
        text = f"/{text}"

    if len(text) > 1:
        text = text.rstrip("/")

    return text


def normalize_route_prefix(value: str | None) -> str:
    """Normalisiert den Blueprint-Route-Prefix."""
    return normalize_route_path(value, default=DEFAULT_LIBRARY_ROUTE_PREFIX)


def join_route_path(prefix: str, path: str) -> str:
    """Fügt Prefix und Route-Pfad robust zusammen."""
    normalized_prefix = normalize_route_prefix(prefix)
    normalized_path = normalize_route_path(path)

    if normalized_path == "/":
        return normalized_prefix

    return f"{normalized_prefix}{normalized_path}"


def get_default_service_root() -> Path:
    """
    Ermittelt den Service-Root ausgehend von dieser Datei.

    Erwarteter Pfad:
      services/vectoplan-library/src/config/library_settings.py

    Daraus:
      service_root = services/vectoplan-library
    """
    try:
        return safe_resolve_path(Path(__file__).resolve().parents[2])
    except Exception:
        return safe_resolve_path(Path.cwd())


def get_default_src_root(service_root: Path | None = None) -> Path:
    """Ermittelt den `src`-Root."""
    if service_root is None:
        service_root = get_default_service_root()

    try:
        current = Path(__file__).resolve()
        return safe_resolve_path(current.parents[1])
    except Exception:
        return safe_resolve_path(service_root / "src")


def env_bool(
    aliases: Iterable[str],
    *,
    default: bool,
    env: Mapping[str, str],
    env_used: dict[str, str],
) -> bool:
    value, used_key = get_env_first(aliases, env=env)
    if used_key and value is not None:
        env_used[used_key] = value
    return parse_bool(value, default=default)


def env_int(
    aliases: Iterable[str],
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
    env: Mapping[str, str],
    env_used: dict[str, str],
) -> int:
    value, used_key = get_env_first(aliases, env=env)
    if used_key and value is not None:
        env_used[used_key] = value
    return parse_int(value, default=default, minimum=minimum, maximum=maximum)


def env_csv(
    aliases: Iterable[str],
    *,
    default: tuple[str, ...],
    env: Mapping[str, str],
    env_used: dict[str, str],
) -> tuple[str, ...]:
    value, used_key = get_env_first(aliases, env=env)
    if used_key and value is not None:
        env_used[used_key] = value
    return parse_csv_tuple(value, default=default)


# ---------------------------------------------------------------------------
# Settings builder
# ---------------------------------------------------------------------------

def build_library_settings(
    *,
    env: Mapping[str, str] | None = None,
) -> LibrarySettings:
    """
    Baut LibrarySettings aus ENV und Defaults.

    Diese Funktion ist side-effect-arm:
    - keine Ordneranlage
    - kein Scan
    - keine Imports aus `library.scanner` oder `vplib`
    """

    env_source = env if env is not None else os.environ
    env_used: dict[str, str] = {}
    warnings: list[str] = []

    default_service_root = get_default_service_root()

    service_root_value, service_root_key = get_env_first(
        ENV_SERVICE_ROOT_ALIASES,
        env=env_source,
    )

    if service_root_value:
        try:
            service_root_raw = Path(service_root_value).expanduser()
            service_root = (
                service_root_raw
                if service_root_raw.is_absolute()
                else default_service_root / service_root_raw
            )
            service_root = safe_resolve_path(service_root)

            if service_root_key:
                env_used[service_root_key] = service_root_value

        except Exception as exc:
            service_root = default_service_root
            message = exception_to_dict(exc)
            warnings.append(
                f"invalid service root env value ignored: {message.get('message') if message else exc}"
            )
    else:
        service_root = default_service_root

    default_src_root = get_default_src_root(service_root)

    src_root = path_from_env_or_default(
        ENV_SRC_ROOT_ALIASES,
        default=default_src_root,
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    library_package_root = path_from_env_or_default(
        ENV_LIBRARY_PACKAGE_ROOT_ALIASES,
        default=service_root / DEFAULT_LIBRARY_PACKAGE_DIRECTORY_RELATIVE,
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    source_root = path_from_env_or_default(
        ENV_SOURCE_ROOT_ALIASES,
        default=service_root / DEFAULT_SOURCE_DIRECTORY_RELATIVE,
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    creative_library_root = path_from_env_or_default(
        ENV_CREATIVE_LIBRARY_ROOT_ALIASES,
        default=service_root / DEFAULT_CREATIVE_LIBRARY_DIRECTORY_RELATIVE,
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    generated_library_root = path_from_env_or_default(
        ENV_GENERATED_LIBRARY_ROOT_ALIASES,
        default=service_root / DEFAULT_GENERATED_LIBRARY_DIRECTORY_RELATIVE,
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    library_cache_root = path_from_env_or_default(
        ENV_LIBRARY_CACHE_ROOT_ALIASES,
        default=service_root / DEFAULT_LIBRARY_CACHE_DIRECTORY_RELATIVE,
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    taxonomy_root = path_from_env_or_default(
        ENV_LIBRARY_TAXONOMY_ROOT_ALIASES,
        default=library_package_root / "taxonomy",
        base=service_root,
        env=env_source,
        env_used=env_used,
    )

    route_prefix_value, route_prefix_key = get_env_first(
        ENV_ROUTE_PREFIX_ALIASES,
        default=DEFAULT_LIBRARY_ROUTE_PREFIX,
        env=env_source,
    )
    if route_prefix_key and route_prefix_value is not None:
        env_used[route_prefix_key] = route_prefix_value

    run_mode_value, run_mode_key = get_env_first(
        ENV_RUN_MODE_ALIASES,
        default="development",
        env=env_source,
    )
    if run_mode_key and run_mode_value is not None:
        env_used[run_mode_key] = run_mode_value

    taxonomy_options = LibraryTaxonomyOptions(
        validate_taxonomy=env_bool(
            (
                "VECTOPLAN_LIBRARY_VALIDATE_TAXONOMY",
                "VPLIB_LIBRARY_VALIDATE_TAXONOMY",
                "LIBRARY_VALIDATE_TAXONOMY",
            ),
            default=DEFAULT_VALIDATE_TAXONOMY,
            env=env_source,
            env_used=env_used,
        ),
        require_taxonomy=env_bool(
            (
                "VECTOPLAN_LIBRARY_REQUIRE_TAXONOMY",
                "VPLIB_LIBRARY_REQUIRE_TAXONOMY",
                "LIBRARY_REQUIRE_TAXONOMY",
            ),
            default=DEFAULT_REQUIRE_TAXONOMY,
            env=env_source,
            env_used=env_used,
        ),
        validate_taxonomy_path=env_bool(
            (
                "VECTOPLAN_LIBRARY_VALIDATE_TAXONOMY_PATH",
                "VPLIB_LIBRARY_VALIDATE_TAXONOMY_PATH",
                "LIBRARY_VALIDATE_TAXONOMY_PATH",
            ),
            default=DEFAULT_VALIDATE_TAXONOMY_PATH,
            env=env_source,
            env_used=env_used,
        ),
        use_taxonomy_labels=env_bool(
            (
                "VECTOPLAN_LIBRARY_USE_TAXONOMY_LABELS",
                "VPLIB_LIBRARY_USE_TAXONOMY_LABELS",
                "LIBRARY_USE_TAXONOMY_LABELS",
            ),
            default=DEFAULT_USE_TAXONOMY_LABELS,
            env=env_source,
            env_used=env_used,
        ),
        include_empty_taxonomy_nodes=env_bool(
            (
                "VECTOPLAN_LIBRARY_INCLUDE_EMPTY_TAXONOMY_NODES",
                "VPLIB_LIBRARY_INCLUDE_EMPTY_TAXONOMY_NODES",
                "LIBRARY_INCLUDE_EMPTY_TAXONOMY_NODES",
            ),
            default=DEFAULT_INCLUDE_EMPTY_TAXONOMY_NODES,
            env=env_source,
            env_used=env_used,
        ),
        include_inactive_taxonomy_nodes=env_bool(
            (
                "VECTOPLAN_LIBRARY_INCLUDE_INACTIVE_TAXONOMY_NODES",
                "VPLIB_LIBRARY_INCLUDE_INACTIVE_TAXONOMY_NODES",
                "LIBRARY_INCLUDE_INACTIVE_TAXONOMY_NODES",
            ),
            default=DEFAULT_INCLUDE_INACTIVE_TAXONOMY_NODES,
            env=env_source,
            env_used=env_used,
        ),
        include_taxonomy_payload=env_bool(
            (
                "VECTOPLAN_LIBRARY_INCLUDE_TAXONOMY_PAYLOAD",
                "VPLIB_LIBRARY_INCLUDE_TAXONOMY_PAYLOAD",
                "LIBRARY_INCLUDE_TAXONOMY_PAYLOAD",
            ),
            default=DEFAULT_INCLUDE_TAXONOMY_PAYLOAD,
            env=env_source,
            env_used=env_used,
        ),
        force_taxonomy_reload=env_bool(
            (
                "VECTOPLAN_LIBRARY_FORCE_TAXONOMY_RELOAD",
                "VPLIB_LIBRARY_FORCE_TAXONOMY_RELOAD",
                "LIBRARY_FORCE_TAXONOMY_RELOAD",
            ),
            default=DEFAULT_FORCE_TAXONOMY_RELOAD,
            env=env_source,
            env_used=env_used,
        ),
        include_legacy_source_layout=env_bool(
            (
                "VECTOPLAN_LIBRARY_INCLUDE_LEGACY_SOURCE_LAYOUT",
                "VPLIB_LIBRARY_INCLUDE_LEGACY_SOURCE_LAYOUT",
                "LIBRARY_INCLUDE_LEGACY_SOURCE_LAYOUT",
            ),
            default=DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT,
            env=env_source,
            env_used=env_used,
        ),
        require_canonical_source_path=env_bool(
            (
                "VECTOPLAN_LIBRARY_REQUIRE_CANONICAL_SOURCE_PATH",
                "VPLIB_LIBRARY_REQUIRE_CANONICAL_SOURCE_PATH",
                "LIBRARY_REQUIRE_CANONICAL_SOURCE_PATH",
            ),
            default=False,
            env=env_source,
            env_used=env_used,
        ),
        require_classification_document=env_bool(
            (
                "VECTOPLAN_LIBRARY_REQUIRE_CLASSIFICATION_DOCUMENT",
                "VPLIB_LIBRARY_REQUIRE_CLASSIFICATION_DOCUMENT",
                "LIBRARY_REQUIRE_CLASSIFICATION_DOCUMENT",
            ),
            default=True,
            env=env_source,
            env_used=env_used,
        ),
    )

    scan_options = LibraryScanOptions(
        recursive=env_bool(
            (
                "VECTOPLAN_LIBRARY_SCAN_RECURSIVE",
                "VPLIB_LIBRARY_SCAN_RECURSIVE",
                "LIBRARY_SCAN_RECURSIVE",
            ),
            default=DEFAULT_SCAN_RECURSIVE,
            env=env_source,
            env_used=env_used,
        ),
        max_depth=env_int(
            (
                "VECTOPLAN_LIBRARY_SCAN_MAX_DEPTH",
                "VPLIB_LIBRARY_SCAN_MAX_DEPTH",
                "LIBRARY_SCAN_MAX_DEPTH",
            ),
            default=DEFAULT_SCAN_MAX_DEPTH,
            minimum=1,
            maximum=100,
            env=env_source,
            env_used=env_used,
        ),
        follow_symlinks=env_bool(
            (
                "VECTOPLAN_LIBRARY_SCAN_FOLLOW_SYMLINKS",
                "VPLIB_LIBRARY_SCAN_FOLLOW_SYMLINKS",
                "LIBRARY_SCAN_FOLLOW_SYMLINKS",
            ),
            default=DEFAULT_SCAN_FOLLOW_SYMLINKS,
            env=env_source,
            env_used=env_used,
        ),
        include_invalid_in_scan=env_bool(
            (
                "VECTOPLAN_LIBRARY_INCLUDE_INVALID_IN_SCAN",
                "VPLIB_LIBRARY_INCLUDE_INVALID_IN_SCAN",
                "LIBRARY_INCLUDE_INVALID_IN_SCAN",
            ),
            default=DEFAULT_INCLUDE_INVALID_IN_SCAN,
            env=env_source,
            env_used=env_used,
        ),
        auto_scan_on_request=env_bool(
            (
                "VECTOPLAN_LIBRARY_AUTO_SCAN_ON_REQUEST",
                "VPLIB_LIBRARY_AUTO_SCAN_ON_REQUEST",
                "LIBRARY_AUTO_SCAN_ON_REQUEST",
            ),
            default=DEFAULT_AUTO_SCAN_ON_REQUEST,
            env=env_source,
            env_used=env_used,
        ),
        fail_on_duplicate_ids=env_bool(
            (
                "VECTOPLAN_LIBRARY_FAIL_ON_DUPLICATE_IDS",
                "VPLIB_LIBRARY_FAIL_ON_DUPLICATE_IDS",
                "LIBRARY_FAIL_ON_DUPLICATE_IDS",
            ),
            default=DEFAULT_FAIL_ON_DUPLICATE_IDS,
            env=env_source,
            env_used=env_used,
        ),
        treat_missing_source_root_as_empty=env_bool(
            (
                "VECTOPLAN_LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY",
                "VPLIB_LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY",
                "LIBRARY_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY",
            ),
            default=DEFAULT_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY,
            env=env_source,
            env_used=env_used,
        ),
        allowed_manifest_filenames=env_csv(
            (
                "VECTOPLAN_LIBRARY_ALLOWED_MANIFEST_FILENAMES",
                "VPLIB_LIBRARY_ALLOWED_MANIFEST_FILENAMES",
                "LIBRARY_ALLOWED_MANIFEST_FILENAMES",
            ),
            default=DEFAULT_ALLOWED_MANIFEST_FILENAMES,
            env=env_source,
            env_used=env_used,
        ),
        required_package_files=env_csv(
            (
                "VECTOPLAN_LIBRARY_REQUIRED_PACKAGE_FILES",
                "VPLIB_LIBRARY_REQUIRED_PACKAGE_FILES",
                "LIBRARY_REQUIRED_PACKAGE_FILES",
            ),
            default=DEFAULT_REQUIRED_PACKAGE_FILES,
            env=env_source,
            env_used=env_used,
        ),
        optional_summary_files=env_csv(
            (
                "VECTOPLAN_LIBRARY_OPTIONAL_SUMMARY_FILES",
                "VPLIB_LIBRARY_OPTIONAL_SUMMARY_FILES",
                "LIBRARY_OPTIONAL_SUMMARY_FILES",
            ),
            default=DEFAULT_OPTIONAL_SUMMARY_FILES,
            env=env_source,
            env_used=env_used,
        ),
        ignored_directory_names=env_csv(
            (
                "VECTOPLAN_LIBRARY_IGNORED_DIRECTORY_NAMES",
                "VPLIB_LIBRARY_IGNORED_DIRECTORY_NAMES",
                "LIBRARY_IGNORED_DIRECTORY_NAMES",
            ),
            default=DEFAULT_IGNORED_DIRECTORY_NAMES,
            env=env_source,
            env_used=env_used,
        ),
        ignored_file_suffixes=env_csv(
            (
                "VECTOPLAN_LIBRARY_IGNORED_FILE_SUFFIXES",
                "VPLIB_LIBRARY_IGNORED_FILE_SUFFIXES",
                "LIBRARY_IGNORED_FILE_SUFFIXES",
            ),
            default=DEFAULT_IGNORED_FILE_SUFFIXES,
            env=env_source,
            env_used=env_used,
        ),
        include_legacy_source_layout=taxonomy_options.include_legacy_source_layout,
        validate_taxonomy_path=taxonomy_options.validate_taxonomy_path,
        read_minimal_metadata=env_bool(
            (
                "VECTOPLAN_LIBRARY_READ_MINIMAL_METADATA",
                "VPLIB_LIBRARY_READ_MINIMAL_METADATA",
                "LIBRARY_READ_MINIMAL_METADATA",
            ),
            default=DEFAULT_READ_MINIMAL_METADATA,
            env=env_source,
            env_used=env_used,
        ),
        read_all_json_documents=env_bool(
            (
                "VECTOPLAN_LIBRARY_READ_ALL_JSON_DOCUMENTS",
                "VPLIB_LIBRARY_READ_ALL_JSON_DOCUMENTS",
                "LIBRARY_READ_ALL_JSON_DOCUMENTS",
            ),
            default=DEFAULT_READ_ALL_JSON_DOCUMENTS,
            env=env_source,
            env_used=env_used,
        ),
        include_optional_summary_files=env_bool(
            (
                "VECTOPLAN_LIBRARY_INCLUDE_OPTIONAL_SUMMARY_FILES",
                "VPLIB_LIBRARY_INCLUDE_OPTIONAL_SUMMARY_FILES",
                "LIBRARY_INCLUDE_OPTIONAL_SUMMARY_FILES",
            ),
            default=DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES,
            env=env_source,
            env_used=env_used,
        ),
        fail_on_json_error=env_bool(
            (
                "VECTOPLAN_LIBRARY_FAIL_ON_JSON_ERROR",
                "VPLIB_LIBRARY_FAIL_ON_JSON_ERROR",
                "LIBRARY_FAIL_ON_JSON_ERROR",
            ),
            default=DEFAULT_FAIL_ON_JSON_ERROR,
            env=env_source,
            env_used=env_used,
        ),
        fail_on_missing_required=env_bool(
            (
                "VECTOPLAN_LIBRARY_FAIL_ON_MISSING_REQUIRED",
                "VPLIB_LIBRARY_FAIL_ON_MISSING_REQUIRED",
                "LIBRARY_FAIL_ON_MISSING_REQUIRED",
            ),
            default=DEFAULT_FAIL_ON_MISSING_REQUIRED,
            env=env_source,
            env_used=env_used,
        ),
        max_json_file_size_bytes=env_int(
            (
                "VECTOPLAN_LIBRARY_MAX_JSON_FILE_SIZE_BYTES",
                "VPLIB_LIBRARY_MAX_JSON_FILE_SIZE_BYTES",
                "LIBRARY_MAX_JSON_FILE_SIZE_BYTES",
            ),
            default=DEFAULT_MAX_JSON_FILE_SIZE_BYTES,
            minimum=1024,
            maximum=MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT,
            env=env_source,
            env_used=env_used,
        ),
        text_encoding=get_env_first(
            (
                "VECTOPLAN_LIBRARY_TEXT_ENCODING",
                "VPLIB_LIBRARY_TEXT_ENCODING",
                "LIBRARY_TEXT_ENCODING",
            ),
            default=DEFAULT_TEXT_ENCODING,
            env=env_source,
        )[0] or DEFAULT_TEXT_ENCODING,
        preserve_discovery_metadata=env_bool(
            (
                "VECTOPLAN_LIBRARY_PRESERVE_DISCOVERY_METADATA",
                "VPLIB_LIBRARY_PRESERVE_DISCOVERY_METADATA",
                "LIBRARY_PRESERVE_DISCOVERY_METADATA",
            ),
            default=DEFAULT_PRESERVE_DISCOVERY_METADATA,
            env=env_source,
            env_used=env_used,
        ),
    )

    read_options = LibraryReadOptions(
        list_include_invalid=env_bool(
            (
                "VECTOPLAN_LIBRARY_LIST_INCLUDE_INVALID",
                "VPLIB_LIBRARY_LIST_INCLUDE_INVALID",
                "LIBRARY_LIST_INCLUDE_INVALID",
            ),
            default=DEFAULT_LIST_INCLUDE_INVALID,
            env=env_source,
            env_used=env_used,
        ),
        detail_include_raw_documents=env_bool(
            (
                "VECTOPLAN_LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS",
                "VPLIB_LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS",
                "LIBRARY_DETAIL_INCLUDE_RAW_DOCUMENTS",
            ),
            default=DEFAULT_DETAIL_INCLUDE_RAW_DOCUMENTS,
            env=env_source,
            env_used=env_used,
        ),
        detail_include_validation_report=env_bool(
            (
                "VECTOPLAN_LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT",
                "VPLIB_LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT",
                "LIBRARY_DETAIL_INCLUDE_VALIDATION_REPORT",
            ),
            default=DEFAULT_DETAIL_INCLUDE_VALIDATION_REPORT,
            env=env_source,
            env_used=env_used,
        ),
        validate_taxonomy=taxonomy_options.validate_taxonomy,
        require_taxonomy=taxonomy_options.require_taxonomy,
        use_taxonomy_labels=taxonomy_options.use_taxonomy_labels,
        include_empty_taxonomy_nodes=taxonomy_options.include_empty_taxonomy_nodes,
        include_inactive_taxonomy_nodes=taxonomy_options.include_inactive_taxonomy_nodes,
        include_taxonomy_payload=taxonomy_options.include_taxonomy_payload,
        force_taxonomy_reload=taxonomy_options.force_taxonomy_reload,
    )

    cache_options = LibraryCacheOptions(
        enabled=env_bool(
            (
                "VECTOPLAN_LIBRARY_CACHE_ENABLED",
                "VPLIB_LIBRARY_CACHE_ENABLED",
                "LIBRARY_CACHE_ENABLED",
            ),
            default=DEFAULT_CACHE_ENABLED,
            env=env_source,
            env_used=env_used,
        ),
        ttl_seconds=env_int(
            (
                "VECTOPLAN_LIBRARY_CACHE_TTL_SECONDS",
                "VPLIB_LIBRARY_CACHE_TTL_SECONDS",
                "LIBRARY_CACHE_TTL_SECONDS",
            ),
            default=DEFAULT_CACHE_TTL_SECONDS,
            minimum=0,
            maximum=MAX_CACHE_TTL_SECONDS,
            env=env_source,
            env_used=env_used,
        ),
        include_taxonomy_version_in_cache_key=env_bool(
            (
                "VECTOPLAN_LIBRARY_CACHE_INCLUDE_TAXONOMY_VERSION",
                "VPLIB_LIBRARY_CACHE_INCLUDE_TAXONOMY_VERSION",
                "LIBRARY_CACHE_INCLUDE_TAXONOMY_VERSION",
            ),
            default=True,
            env=env_source,
            env_used=env_used,
        ),
    )

    directory_plan = LibraryDirectoryPlan(
        service_root=service_root,
        src_root=src_root,
        library_package_root=library_package_root,
        source_root=source_root,
        creative_library_root=creative_library_root,
        generated_library_root=generated_library_root,
        library_cache_root=library_cache_root,
        taxonomy_root=taxonomy_root,
    )

    route_plan = LibraryRoutePlan(
        route_prefix=normalize_route_prefix(route_prefix_value),
        health_route_path=DEFAULT_HEALTH_ROUTE_PATH,
        scan_route_path=DEFAULT_SCAN_ROUTE_PATH,
        blocks_route_path=DEFAULT_BLOCKS_ROUTE_PATH,
        tree_route_path=DEFAULT_TREE_ROUTE_PATH,
        cache_clear_route_path=DEFAULT_CACHE_CLEAR_ROUTE_PATH,
        block_detail_route_template=DEFAULT_BLOCK_DETAIL_ROUTE_TEMPLATE,
        block_variants_route_template=DEFAULT_BLOCK_VARIANTS_ROUTE_TEMPLATE,
    )

    text_encoding_value, text_encoding_key = get_env_first(
        (
            "VECTOPLAN_LIBRARY_TEXT_ENCODING",
            "VPLIB_LIBRARY_TEXT_ENCODING",
            "LIBRARY_TEXT_ENCODING",
        ),
        default=DEFAULT_TEXT_ENCODING,
        env=env_source,
    )
    if text_encoding_key and text_encoding_value:
        env_used[text_encoding_key] = text_encoding_value

    return LibrarySettings(
        settings_version=LIBRARY_SETTINGS_VERSION,
        component=LIBRARY_SETTINGS_COMPONENT,
        generated_at=utc_now_iso(),
        run_mode=run_mode_value or "development",
        directory_plan=directory_plan,
        route_plan=route_plan,
        taxonomy_options=taxonomy_options,
        scan_options=scan_options,
        read_options=read_options,
        cache_options=cache_options,
        env_used=env_used,
        warnings=tuple(warnings),
    )


@lru_cache(maxsize=1)
def _cached_library_settings() -> LibrarySettings:
    """Interner Settings-Cache."""
    return build_library_settings()


def get_library_settings(*, refresh: bool = False) -> LibrarySettings:
    """Gibt die aktuellen LibrarySettings zurück."""
    if refresh:
        reset_library_settings_cache()

    return _cached_library_settings()


def reset_library_settings_cache() -> None:
    """Leert den Settings-Cache."""
    try:
        _cached_library_settings.cache_clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public convenience accessors
# ---------------------------------------------------------------------------

def get_library_directory_plan(*, refresh: bool = False) -> LibraryDirectoryPlan:
    return get_library_settings(refresh=refresh).directory_plan


def get_library_route_plan(*, refresh: bool = False) -> LibraryRoutePlan:
    return get_library_settings(refresh=refresh).route_plan


def get_library_taxonomy_options(*, refresh: bool = False) -> LibraryTaxonomyOptions:
    return get_library_settings(refresh=refresh).taxonomy_options


def get_library_scan_options(*, refresh: bool = False) -> LibraryScanOptions:
    return get_library_settings(refresh=refresh).scan_options


def get_library_read_options(*, refresh: bool = False) -> LibraryReadOptions:
    return get_library_settings(refresh=refresh).read_options


def get_library_cache_options(*, refresh: bool = False) -> LibraryCacheOptions:
    return get_library_settings(refresh=refresh).cache_options


def get_source_root(*, refresh: bool = False) -> Path:
    return get_library_settings(refresh=refresh).directory_plan.source_root


def get_creative_library_root(*, refresh: bool = False) -> Path:
    return get_library_settings(refresh=refresh).directory_plan.creative_library_root


def get_taxonomy_root(*, refresh: bool = False) -> Path:
    return get_library_settings(refresh=refresh).directory_plan.taxonomy_root


def get_library_route_prefix(*, refresh: bool = False) -> str:
    return get_library_settings(refresh=refresh).route_plan.route_prefix


def get_library_route_prefix_safe() -> str:
    """Safe Helper für Blueprint-Erzeugung."""
    try:
        return get_library_route_prefix()
    except Exception:
        return DEFAULT_LIBRARY_ROUTE_PREFIX


def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
    """JSON-kompatible Settings-Zusammenfassung."""
    try:
        return get_library_settings(refresh=refresh).to_dict()
    except Exception as exc:
        return {
            "settings_version": LIBRARY_SETTINGS_VERSION,
            "component": LIBRARY_SETTINGS_COMPONENT,
            "ok": False,
            "error": exception_to_dict(exc),
            "fallback_route_prefix": DEFAULT_LIBRARY_ROUTE_PREFIX,
        }


# ---------------------------------------------------------------------------
# Directory checks
# ---------------------------------------------------------------------------

def _check_directory(
    *,
    key: str,
    path: Path,
    required: bool,
    create: bool,
) -> DirectoryStatus:
    """
    Prüft optional ein Verzeichnis und erzeugt es bei Bedarf.

    `create=False` ist der sichere Standard.
    """

    created = False

    try:
        exists_before = path.exists()

        if not exists_before and create:
            path.mkdir(parents=True, exist_ok=True)
            created = True

        exists = path.exists()
        is_directory = path.is_dir()

        if exists and is_directory:
            status = "ok"
        elif exists and not is_directory:
            status = "invalid"
        elif required:
            status = "missing"
        else:
            status = "missing_optional"

        return DirectoryStatus(
            key=key,
            path=str(path),
            exists=exists,
            is_directory=is_directory,
            created=created,
            required=required,
            status=status,
            error=None,
        )

    except Exception as exc:
        return DirectoryStatus(
            key=key,
            path=str(path),
            exists=False,
            is_directory=False,
            created=created,
            required=required,
            status="error",
            error=exception_to_dict(exc),
        )


def check_library_directories(
    *,
    create: bool = False,
    include_optional: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Prüft die zentralen Library-Verzeichnisse.

    Standard:
      create=False
    """

    settings = get_library_settings(refresh=refresh)
    plan = settings.directory_plan

    checks: list[tuple[str, Path, bool]] = [
        ("service_root", plan.service_root, True),
        ("src_root", plan.src_root, True),
        ("library_package_root", plan.library_package_root, True),
        ("source_root", plan.source_root, not settings.scan_options.treat_missing_source_root_as_empty),
        ("taxonomy_root", plan.taxonomy_root, settings.taxonomy_options.require_taxonomy),
    ]

    if include_optional:
        checks.extend(
            [
                ("creative_library_root", plan.creative_library_root, False),
                ("generated_library_root", plan.generated_library_root, False),
                ("library_cache_root", plan.library_cache_root, False),
            ]
        )

    statuses: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for key, path, required in checks:
        status = _check_directory(
            key=key,
            path=path,
            required=required,
            create=create,
        )
        statuses[key] = status.to_dict()

        if status.status in {"invalid", "error"}:
            errors.append(f"{key}: {status.status}")

        elif status.status == "missing" and required:
            errors.append(f"{key}: missing")

        elif status.status in {"missing", "missing_optional"}:
            warnings.append(f"{key}: {status.status}")

    ok = len(errors) == 0

    return {
        "ok": ok,
        "create": create,
        "include_optional": include_optional,
        "checked_at": utc_now_iso(),
        "directories": statuses,
        "warnings": warnings,
        "errors": errors,
    }


def ensure_library_directories(
    *,
    include_optional: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """
    Erzeugt zentrale Library-Verzeichnisse, falls sie fehlen.

    Diese Funktion ist für kontrollierte Startup-/Dev-/Test-Situationen gedacht.
    Sie sollte nicht implizit beim Import laufen.
    """

    return check_library_directories(
        create=True,
        include_optional=include_optional,
        refresh=refresh,
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_library_settings_health(*, refresh: bool = False) -> dict[str, Any]:
    """
    Health-Status der Library-Settings.

    Prüft:
    - Settings können geladen werden
    - Route-Prefix ist vorhanden
    - zentrale Pfade sind berechenbar
    - Verzeichnisstatus ohne Schreibwirkung
    """

    try:
        settings = get_library_settings(refresh=refresh)
        directory_check = check_library_directories(
            create=False,
            include_optional=True,
            refresh=False,
        )

        errors: list[str] = []
        warnings: list[str] = list(settings.warnings)

        if not settings.route_plan.route_prefix:
            errors.append("library route prefix is empty")

        if not settings.scan_options.required_package_files:
            errors.append("required package files list is empty")

        if "family/classification.json" not in settings.scan_options.required_package_files:
            errors.append("family/classification.json is missing from required package files")

        if directory_check.get("errors"):
            errors.extend(str(item) for item in directory_check.get("errors", []))

        if directory_check.get("warnings"):
            warnings.extend(str(item) for item in directory_check.get("warnings", []))

        ok = len(errors) == 0

        return {
            "ok": ok,
            "healthy": ok,
            "settings_version": settings.settings_version,
            "component": settings.component,
            "generated_at": utc_now_iso(),
            "settings": settings.to_dict(),
            "directory_check": directory_check,
            "taxonomy": {
                "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
                "legacy_source_depth": LEGACY_SOURCE_DEPTH,
                "canonical_source_path_pattern": CANONICAL_SOURCE_PATH_PATTERN,
                "legacy_source_path_pattern": LEGACY_SOURCE_PATH_PATTERN,
                "options": settings.taxonomy_options.to_dict(),
                "taxonomy_root": str(settings.directory_plan.taxonomy_root),
            },
            "warnings": warnings,
            "errors": errors,
        }

    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "settings_version": LIBRARY_SETTINGS_VERSION,
            "component": LIBRARY_SETTINGS_COMPONENT,
            "generated_at": utc_now_iso(),
            "error": exception_to_dict(exc, include_traceback=False),
        }


def assert_library_settings_ready(*, refresh: bool = False) -> None:
    """Wirft RuntimeError, wenn die Settings nicht bereit sind."""
    health = get_library_settings_health(refresh=refresh)

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library settings are not ready: "
        f"errors={health.get('errors') or health.get('error')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_SETTINGS_VERSION",
    "LIBRARY_SETTINGS_COMPONENT",
    "DEFAULT_LIBRARY_ROUTE_PREFIX",
    "DEFAULT_HEALTH_ROUTE_PATH",
    "DEFAULT_SCAN_ROUTE_PATH",
    "DEFAULT_BLOCKS_ROUTE_PATH",
    "DEFAULT_TREE_ROUTE_PATH",
    "DEFAULT_CACHE_CLEAR_ROUTE_PATH",
    "DEFAULT_BLOCK_DETAIL_ROUTE_TEMPLATE",
    "DEFAULT_BLOCK_VARIANTS_ROUTE_TEMPLATE",
    "DEFAULT_SOURCE_DIRECTORY_RELATIVE",
    "DEFAULT_LIBRARY_PACKAGE_DIRECTORY_RELATIVE",
    "DEFAULT_CREATIVE_LIBRARY_DIRECTORY_RELATIVE",
    "DEFAULT_GENERATED_LIBRARY_DIRECTORY_RELATIVE",
    "DEFAULT_LIBRARY_CACHE_DIRECTORY_RELATIVE",
    "CANONICAL_SOURCE_DEPTH",
    "LEGACY_SOURCE_DEPTH",
    "CANONICAL_SOURCE_PATH_PATTERN",
    "LEGACY_SOURCE_PATH_PATTERN",
    "DEFAULT_SCAN_RECURSIVE",
    "DEFAULT_SCAN_MAX_DEPTH",
    "DEFAULT_SCAN_FOLLOW_SYMLINKS",
    "DEFAULT_INCLUDE_INVALID_IN_SCAN",
    "DEFAULT_AUTO_SCAN_ON_REQUEST",
    "DEFAULT_FAIL_ON_DUPLICATE_IDS",
    "DEFAULT_TREAT_MISSING_SOURCE_ROOT_AS_EMPTY",
    "DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT",
    "DEFAULT_VALIDATE_TAXONOMY_PATH",
    "DEFAULT_READ_MINIMAL_METADATA",
    "DEFAULT_READ_ALL_JSON_DOCUMENTS",
    "DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES",
    "DEFAULT_FAIL_ON_JSON_ERROR",
    "DEFAULT_FAIL_ON_MISSING_REQUIRED",
    "DEFAULT_MAX_JSON_FILE_SIZE_BYTES",
    "MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT",
    "DEFAULT_TEXT_ENCODING",
    "DEFAULT_PRESERVE_DISCOVERY_METADATA",
    "DEFAULT_LIST_INCLUDE_INVALID",
    "DEFAULT_DETAIL_INCLUDE_RAW_DOCUMENTS",
    "DEFAULT_DETAIL_INCLUDE_VALIDATION_REPORT",
    "DEFAULT_USE_TAXONOMY_LABELS",
    "DEFAULT_INCLUDE_EMPTY_TAXONOMY_NODES",
    "DEFAULT_INCLUDE_INACTIVE_TAXONOMY_NODES",
    "DEFAULT_INCLUDE_TAXONOMY_PAYLOAD",
    "DEFAULT_FORCE_TAXONOMY_RELOAD",
    "DEFAULT_VALIDATE_TAXONOMY",
    "DEFAULT_REQUIRE_TAXONOMY",
    "DEFAULT_CACHE_ENABLED",
    "DEFAULT_CACHE_TTL_SECONDS",
    "MAX_CACHE_TTL_SECONDS",
    "DEFAULT_ALLOWED_MANIFEST_FILENAMES",
    "DEFAULT_REQUIRED_PACKAGE_FILES",
    "DEFAULT_OPTIONAL_SUMMARY_FILES",
    "DEFAULT_IGNORED_DIRECTORY_NAMES",
    "DEFAULT_IGNORED_FILE_SUFFIXES",
    "ENV_SERVICE_ROOT_ALIASES",
    "ENV_SRC_ROOT_ALIASES",
    "ENV_LIBRARY_PACKAGE_ROOT_ALIASES",
    "ENV_SOURCE_ROOT_ALIASES",
    "ENV_CREATIVE_LIBRARY_ROOT_ALIASES",
    "ENV_GENERATED_LIBRARY_ROOT_ALIASES",
    "ENV_LIBRARY_CACHE_ROOT_ALIASES",
    "ENV_ROUTE_PREFIX_ALIASES",
    "ENV_RUN_MODE_ALIASES",
    "ENV_LIBRARY_TAXONOMY_ROOT_ALIASES",
    "LibraryDirectoryPlan",
    "LibraryRoutePlan",
    "LibraryTaxonomyOptions",
    "LibraryScanOptions",
    "LibraryReadOptions",
    "LibraryCacheOptions",
    "LibrarySettings",
    "DirectoryStatus",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "get_env_first",
    "parse_bool",
    "parse_int",
    "parse_csv_tuple",
    "safe_resolve_path",
    "path_from_env_or_default",
    "normalize_route_path",
    "normalize_route_prefix",
    "join_route_path",
    "get_default_service_root",
    "get_default_src_root",
    "env_bool",
    "env_int",
    "env_csv",
    "build_library_settings",
    "get_library_settings",
    "reset_library_settings_cache",
    "get_library_directory_plan",
    "get_library_route_plan",
    "get_library_taxonomy_options",
    "get_library_scan_options",
    "get_library_read_options",
    "get_library_cache_options",
    "get_source_root",
    "get_creative_library_root",
    "get_taxonomy_root",
    "get_library_route_prefix",
    "get_library_route_prefix_safe",
    "get_settings_summary",
    "check_library_directories",
    "ensure_library_directories",
    "get_library_settings_health",
    "assert_library_settings_ready",
)