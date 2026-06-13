# services/vectoplan-library/src/library/repositories/sql/creative_library_repository.py
"""
SQL-Repository für die persistente Creative-Library-Schicht von VECTOPLAN.

Diese Datei ist die zentrale DB-Zugriffsschicht zwischen:

    library_db_sync_service / library_published_service
        und
    models/creative_library.py / SQLAlchemy / PostgreSQL

Aufgaben:

- ScanRuns speichern
- ScanIssues speichern
- Families anhand stabiler vplib_uid upserten
- Family-Revisions anhand revision_hash erzeugen
- Varianten, Assets und Dokumente revisionsbezogen speichern
- veröffentlichte Families für API-Read-Services lesen
- Detail-, Varianten-, Tree- und Inventar-Grunddaten aus der DB laden
- Family-Aggregate wie current_revision_id, revision_count, variant_count, asset_count und document_count aktuell halten
- Asset-Payloads ohne echten Pfad robust behandeln, ohne dict/list-Werte in Textfelder zu schreiben
- robust mit unterschiedlichen Model-Klassennamen umgehen
- keine Tabellen beim Import erzeugen
- keine DB-Verbindung beim Import öffnen
- keine Migrationen ausführen

Wichtige Architekturregel:

    Die DB erzeugt keine vplib_uid.
    Die DB übernimmt vplib_uid aus vplib.manifest.json.
    Scanner, Validatoren, Repository und DB-Sync reparieren keine fehlende UID.

Diese Repository-Datei ist bewusst modellnamen-tolerant, weil der konkrete
Stand von models/creative_library.py in der laufenden Migration variieren kann.
Sobald models/creative_library.py final ist, kann die Candidate-Liste reduziert
werden. Bis dahin bleibt diese Datei vorwärtskompatibel.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import threading
import traceback as traceback_module
from dataclasses import asdict, dataclass, field as dataclass_field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Type, Union


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_REPOSITORY_NAME = "creative_library_repository"
CREATIVE_LIBRARY_REPOSITORY_COMPONENT = "creative_library_sql_repository"
CREATIVE_LIBRARY_REPOSITORY_API_VERSION = "v1"
CREATIVE_LIBRARY_REPOSITORY_IMPLEMENTATION_STAGE = "sql-repository"

__version__ = "0.1.2"


# ---------------------------------------------------------------------------
# Environment / defaults
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_MODEL_MODULE_ENV = "VPLIB_CREATIVE_LIBRARY_MODEL_MODULE"
SQLALCHEMY_EXTENSION_MODULE_ENV = "VPLIB_SQLALCHEMY_EXTENSION_MODULE"
CREATIVE_LIBRARY_REPOSITORY_STRICT_ENV = "VPLIB_CREATIVE_LIBRARY_REPOSITORY_STRICT"

DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE = "models.creative_library"
DEFAULT_SQLALCHEMY_EXTENSION_MODULE = "extensions"

DEFAULT_PUBLICATION_STATUS = "published"
DEFAULT_DRAFT_STATUS = "draft"
DEFAULT_DELETED_STATUS = "deleted"
DEFAULT_SCAN_STATUS_RUNNING = "running"
DEFAULT_SCAN_STATUS_FINISHED = "finished"
DEFAULT_SCAN_STATUS_FAILED = "failed"

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


# ---------------------------------------------------------------------------
# Model candidate registry
# ---------------------------------------------------------------------------

MODEL_CANDIDATES: Mapping[str, Tuple[str, ...]] = {
    "scan_run": (
        "CreativeLibraryScanRun",
        "CreativeLibraryScanRunModel",
        "LibraryScanRun",
        "LibraryScanRunModel",
        "ScanRun",
    ),
    "scan_issue": (
        "CreativeLibraryScanIssue",
        "CreativeLibraryScanIssueModel",
        "LibraryScanIssue",
        "LibraryScanIssueModel",
        "ScanIssue",
    ),
    "family": (
        "CreativeLibraryFamily",
        "CreativeLibraryFamilyModel",
        "LibraryFamily",
        "LibraryFamilyModel",
        "LibraryItem",
        "CreativeLibraryItem",
    ),
    "family_revision": (
        "CreativeLibraryFamilyRevision",
        "CreativeLibraryRevision",
        "CreativeLibraryFamilyRevisionModel",
        "LibraryFamilyRevision",
        "LibraryRevision",
        "FamilyRevision",
    ),
    "variant": (
        "CreativeLibraryVariant",
        "CreativeLibraryVariantModel",
        "LibraryVariant",
        "LibraryVariantModel",
        "FamilyVariant",
    ),
    "resolved_variant": (
        "CreativeLibraryResolvedVariant",
        "CreativeLibraryResolvedVariantModel",
        "LibraryResolvedVariant",
        "ResolvedVariant",
    ),
    "asset": (
        "CreativeLibraryAsset",
        "CreativeLibraryAssetModel",
        "LibraryAsset",
        "LibraryAssetModel",
        "FamilyAsset",
    ),
    "document": (
        "CreativeLibraryDocument",
        "CreativeLibraryDocumentModel",
        "LibraryDocument",
        "LibraryDocumentModel",
        "FamilyDocument",
    ),
    "inventory_slot": (
        "CreativeLibraryInventorySlot",
        "CreativeLibraryInventorySlotModel",
        "LibraryInventorySlot",
        "InventorySlot",
    ),
    "publication_status": (
        "CreativeLibraryPublicationStatus",
        "LibraryPublicationStatus",
        "PublicationStatus",
    ),
    "manufacturer_overlay": (
        "CreativeLibraryManufacturerOverlay",
        "CreativeLibraryManufacturerOverlayModel",
        "ManufacturerOverlay",
    ),
    "product_overlay": (
        "CreativeLibraryProductOverlay",
        "CreativeLibraryProductOverlayModel",
        "ProductOverlay",
    ),
}


CORE_MODEL_KEYS: Tuple[str, ...] = (
    "family",
    "family_revision",
)

RECOMMENDED_MODEL_KEYS: Tuple[str, ...] = (
    "scan_run",
    "scan_issue",
    "variant",
    "asset",
    "document",
    "inventory_slot",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CreativeLibraryRepositoryError(RuntimeError):
    """Basisklasse für Creative-Library-Repository-Fehler."""


class CreativeLibraryRepositoryUnavailable(CreativeLibraryRepositoryError):
    """DB-Session, Model-Modul oder benötigtes Model ist nicht verfügbar."""


class CreativeLibraryRepositoryConflict(CreativeLibraryRepositoryError):
    """Konflikt beim Schreiben, z. B. doppelte UID oder Revisionskollision."""


class CreativeLibraryRepositoryNotFound(CreativeLibraryRepositoryError):
    """Gesuchte DB-Entität wurde nicht gefunden."""


class CreativeLibraryRepositoryValidationError(CreativeLibraryRepositoryError):
    """Ungültiger Payload für eine Repository-Operation."""


# ---------------------------------------------------------------------------
# Payload models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreativeLibraryRepositoryConfig:
    """
    Konfiguration für CreativeLibraryRepository.

    db:
        Optionales Flask-SQLAlchemy-Objekt.

    session:
        Optionale SQLAlchemy-Session. Wenn nicht gesetzt, wird db.session oder
        das Objekt aus extensions.py verwendet.

    model_module:
        Optional bereits importiertes models.creative_library-Modul.

    model_module_path:
        Optionaler Modulpfad. Überschreibt Environment und Default.

    autocommit:
        Wenn True, committen Schreibmethoden selbst.

    autoflush:
        Wenn True, wird nach Schreiboperationen flush() ausgeführt.

    strict_models:
        Wenn True, schlagen fehlende empfohlene Models früher fehl.
        Core-Models werden bei nutzenden Methoden immer verlangt.

    json_safe_payloads:
        Wenn True, werden JSON-Payloads defensiv serialisierbar gemacht.

    permissive_model_fields:
        Wenn True, dürfen Attribute auch gesetzt werden, wenn sie nicht in
        __table__.columns oder __annotations__ erkennbar sind.
    """

    db: Any = None
    session: Any = None
    model_module: Optional[ModuleType] = None
    model_module_path: Optional[str] = None
    autocommit: bool = False
    autoflush: bool = True
    strict_models: bool = False
    json_safe_payloads: bool = True
    permissive_model_fields: bool = False


@dataclass(frozen=True)
class CreativeLibraryScanRunPayload:
    source_root: Optional[str] = None
    mode: str = "filesystem_sync"
    triggered_by: Optional[str] = None
    status: str = DEFAULT_SCAN_STATUS_RUNNING
    started_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryScanRunSummary:
    id: Any = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    source_root: Optional[str] = None
    mode: Optional[str] = None
    total_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    published_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryFamilyUpsertPayload:
    vplib_uid: str
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    family_slug: Optional[str] = None
    slug: Optional[str] = None
    label: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    object_kind: Optional[str] = None
    domain: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    source_path: Optional[str] = None
    package_root: Optional[str] = None
    classification_path: Optional[str] = None
    enabled: bool = True
    visible: bool = True
    publication_status: str = DEFAULT_PUBLICATION_STATUS
    status: Optional[str] = None
    default_variant_id: Optional[str] = None
    variant_count: Optional[int] = None
    revision_hash: Optional[str] = None
    scanned_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)
    summary_payload: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryRevisionUpsertPayload:
    vplib_uid: str
    revision_hash: str
    family_id: Optional[str] = None
    package_id: Optional[str] = None
    package_version: Optional[str] = None
    schema_version: Optional[str] = None
    validation_status: Optional[str] = None
    publication_status: str = DEFAULT_PUBLICATION_STATUS
    scan_run_id: Any = None
    source_path: Optional[str] = None
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    summary_payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    detail_payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    raw_documents: Mapping[str, Any] = dataclass_field(default_factory=dict)
    documents: Mapping[str, Any] = dataclass_field(default_factory=dict)
    validation_payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryVariantPayload:
    vplib_uid: str
    variant_id: str
    label: Optional[str] = None
    description: Optional[str] = None
    is_default: bool = False
    enabled: bool = True
    visible: bool = True
    sort_order: int = 0
    revision_hash: Optional[str] = None
    payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    resolved_payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryAssetPayload:
    vplib_uid: str
    role: Optional[str] = None
    asset_type: Optional[str] = None
    path: Optional[str] = None
    relative_path: Optional[str] = None
    uri: Optional[str] = None
    label: Optional[str] = None
    mime_type: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    revision_hash: Optional[str] = None
    payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryDocumentPayload:
    vplib_uid: str
    relative_path: str
    document_type: Optional[str] = None
    module: Optional[str] = None
    checksum: Optional[str] = None
    revision_hash: Optional[str] = None
    payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class CreativeLibraryIssuePayload:
    vplib_uid: Optional[str] = None
    severity: str = "warning"
    code: Optional[str] = None
    message: Optional[str] = None
    path: Optional[str] = None
    field: Optional[str] = None
    scope: Optional[str] = None
    source_path: Optional[str] = None
    revision_hash: Optional[str] = None
    scan_run_id: Any = None
    payload: Mapping[str, Any] = dataclass_field(default_factory=dict)
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal caches / singleton handling
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.RLock()
_DEFAULT_REPOSITORY: Optional["CreativeLibraryRepository"] = None
_MODEL_MODULE_CACHE: Dict[str, ModuleType] = {}
_IMPORT_ERROR_CACHE: Dict[str, BaseException] = {}
_IMPORT_TRACEBACK_CACHE: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def _normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _normalize_vplib_uid(value: Any) -> str:
    text = _normalize_string(value)

    if not text:
        raise CreativeLibraryRepositoryValidationError("vplib_uid is required.")

    return text.lower()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_env_candidates(value: Optional[str]) -> Tuple[str, ...]:
    if not value:
        return ()

    raw = str(value).replace(";", ",").replace(" ", ",")
    parts = [part.strip() for part in raw.split(",")]
    return tuple(part for part in parts if part)


def _dedupe(values: Iterable[str]) -> Tuple[str, ...]:
    seen: set[str] = set()
    result: List[str] = []

    for value in values:
        normalized = str(value or "").strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)
        result.append(normalized)

    return tuple(result)


def _json_safe(value: Any) -> Any:
    """
    Macht Payloads defensiv JSON-kompatibel.

    SQLAlchemy-JSON-Spalten akzeptieren meist Dict/List/Scalar. Datetime,
    Path, Dataclasses oder fremde Objekte werden hier in einfache Strukturen
    überführt.
    """

    if value is None:
        return None

    if is_dataclass(value):
        value = asdict(value)

    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _to_mapping(value: Any) -> Dict[str, Any]:
    """Konvertiert Dataclass, Mapping oder Objekt defensiv in ein Dict."""

    if value is None:
        return {}

    if is_dataclass(value):
        return dict(asdict(value))

    if isinstance(value, Mapping):
        return dict(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return dict(result)

    result: Dict[str, Any] = {}

    for name in dir(value):
        if name.startswith("_"):
            continue

        try:
            attr = getattr(value, name)
        except Exception:
            continue

        if callable(attr):
            continue

        result[name] = attr

    return result


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _bounded_limit(value: Any, default: int = DEFAULT_LIMIT) -> int:
    limit = _safe_int(value, default)

    if limit <= 0:
        return default

    return min(limit, MAX_LIMIT)


def _safe_offset(value: Any) -> int:
    offset = _safe_int(value, 0)
    return max(0, offset)


def _module_exists(module_path: str) -> Tuple[bool, Optional[BaseException]]:
    try:
        return importlib.util.find_spec(module_path) is not None, None
    except Exception as exc:
        return False, exc


def _store_import_error(module_path: str, exc: BaseException) -> None:
    with _CACHE_LOCK:
        _IMPORT_ERROR_CACHE[module_path] = exc
        _IMPORT_TRACEBACK_CACHE[module_path] = traceback_module.format_exc()
        _MODEL_MODULE_CACHE.pop(module_path, None)


def _clear_import_error(module_path: str) -> None:
    with _CACHE_LOCK:
        _IMPORT_ERROR_CACHE.pop(module_path, None)
        _IMPORT_TRACEBACK_CACHE.pop(module_path, None)


def _get_cached_import_error(module_path: str) -> Optional[BaseException]:
    with _CACHE_LOCK:
        return _IMPORT_ERROR_CACHE.get(module_path)


def _get_cached_traceback(module_path: str) -> Optional[str]:
    with _CACHE_LOCK:
        return _IMPORT_TRACEBACK_CACHE.get(module_path)


def _safe_import_module(
    module_path: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    normalized_path = str(module_path or "").strip()

    if not normalized_path:
        exc = CreativeLibraryRepositoryValidationError("Empty module path.")
        if required:
            raise exc
        return None

    with _CACHE_LOCK:
        if not force_reload and normalized_path in _MODEL_MODULE_CACHE:
            return _MODEL_MODULE_CACHE[normalized_path]

    try:
        with _CACHE_LOCK:
            if force_reload and normalized_path in _MODEL_MODULE_CACHE:
                module = importlib.reload(_MODEL_MODULE_CACHE[normalized_path])
            else:
                module = importlib.import_module(normalized_path)

            _MODEL_MODULE_CACHE[normalized_path] = module
            _clear_import_error(normalized_path)
            return module

    except Exception as exc:
        _store_import_error(normalized_path, exc)

        if required:
            raise CreativeLibraryRepositoryUnavailable(
                f"Unable to import module {normalized_path}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        return None


def _safe_import_first_available(
    candidates: Sequence[str],
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    last_error: Optional[BaseException] = None

    for module_path in candidates:
        module = _safe_import_module(
            module_path,
            required=False,
            force_reload=force_reload,
        )

        if module is not None:
            return module

        last_error = _get_cached_import_error(module_path)

    if required:
        joined = ", ".join(candidates)

        if last_error is not None:
            raise CreativeLibraryRepositoryUnavailable(
                f"No candidate module could be imported: {joined} "
                f"({last_error.__class__.__name__}: {last_error})"
            ) from last_error

        raise CreativeLibraryRepositoryUnavailable(
            f"No candidate module could be imported: {joined}"
        )

    return None


def get_model_module_candidates(configured: Optional[str] = None) -> Tuple[str, ...]:
    env_candidates = _split_env_candidates(os.getenv(CREATIVE_LIBRARY_MODEL_MODULE_ENV))

    configured_candidates = _split_env_candidates(configured) if configured else ()

    return _dedupe(
        (
            *configured_candidates,
            *env_candidates,
            DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE,
        )
    )


def get_extension_module_candidates() -> Tuple[str, ...]:
    env_candidates = _split_env_candidates(os.getenv(SQLALCHEMY_EXTENSION_MODULE_ENV))

    return _dedupe(
        (
            *env_candidates,
            DEFAULT_SQLALCHEMY_EXTENSION_MODULE,
        )
    )


def import_creative_library_model_module(
    *,
    configured: Optional[str] = None,
    required: bool = True,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    return _safe_import_first_available(
        get_model_module_candidates(configured),
        required=required,
        force_reload=force_reload,
    )


def import_sqlalchemy_extension_module(
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    return _safe_import_first_available(
        get_extension_module_candidates(),
        required=required,
        force_reload=force_reload,
    )


# ---------------------------------------------------------------------------
# SQLAlchemy model introspection helpers
# ---------------------------------------------------------------------------


def _model_columns(model_cls: Type[Any]) -> Dict[str, Any]:
    table = getattr(model_cls, "__table__", None)
    columns = getattr(table, "columns", None)

    if columns is None:
        return {}

    result: Dict[str, Any] = {}

    try:
        for column in columns:
            result[column.name] = column
    except Exception:
        return {}

    return result


def _model_column_names(model_cls: Type[Any]) -> set[str]:
    columns = _model_columns(model_cls)

    if columns:
        return set(columns.keys())

    annotations = getattr(model_cls, "__annotations__", None)

    if isinstance(annotations, Mapping):
        return set(str(key) for key in annotations.keys())

    return set()


def _model_has_field(model_cls: Type[Any], field_name: str, *, permissive: bool = False) -> bool:
    if permissive:
        return True

    if field_name in _model_column_names(model_cls):
        return True

    if hasattr(model_cls, field_name):
        return True

    return False


def _column_has_foreign_key(model_cls: Type[Any], field_name: str) -> bool:
    column = _model_columns(model_cls).get(field_name)

    if column is None:
        return False

    try:
        return bool(column.foreign_keys)
    except Exception:
        return False


def _model_primary_key_names(model_cls: Type[Any]) -> Tuple[str, ...]:
    table = getattr(model_cls, "__table__", None)
    primary_key = getattr(table, "primary_key", None)

    if primary_key is not None:
        try:
            return tuple(column.name for column in primary_key.columns)
        except Exception:
            pass

    if _model_has_field(model_cls, "id"):
        return ("id",)

    return ()


def _get_object_pk(obj: Any) -> Any:
    if obj is None:
        return None

    for name in ("id", "pk", "uuid"):
        if hasattr(obj, name):
            value = getattr(obj, name, None)
            if value is not None:
                return value

    model_cls = obj.__class__
    pk_names = _model_primary_key_names(model_cls)

    for name in pk_names:
        value = getattr(obj, name, None)
        if value is not None:
            return value

    return None


def _object_to_dict(obj: Any, *, include_private: bool = False) -> Dict[str, Any]:
    if obj is None:
        return {}

    if isinstance(obj, Mapping):
        return dict(obj)

    if is_dataclass(obj):
        return asdict(obj)

    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            result = obj.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
        except TypeError:
            pass

    model_cls = obj.__class__
    field_names = _model_column_names(model_cls)

    result: Dict[str, Any] = {}

    if field_names:
        for name in sorted(field_names):
            try:
                result[name] = getattr(obj, name)
            except Exception:
                continue

        return result

    for name in dir(obj):
        if name.startswith("_") and not include_private:
            continue

        try:
            value = getattr(obj, name)
        except Exception:
            continue

        if callable(value):
            continue

        result[name] = value

    return result


def _filter_model_data(
    model_cls: Type[Any],
    data: Mapping[str, Any],
    *,
    permissive: bool = False,
    json_safe_payloads: bool = True,
) -> Dict[str, Any]:
    filtered: Dict[str, Any] = {}

    for key, value in data.items():
        if value is None:
            continue

        if not _model_has_field(model_cls, key, permissive=permissive):
            continue

        if json_safe_payloads and isinstance(value, (Mapping, list, tuple, set)):
            filtered[key] = _json_safe(value)
        else:
            filtered[key] = value

    return filtered


def _make_instance(
    model_cls: Type[Any],
    data: Mapping[str, Any],
    *,
    permissive: bool = False,
    json_safe_payloads: bool = True,
) -> Any:
    filtered = _filter_model_data(
        model_cls,
        data,
        permissive=permissive,
        json_safe_payloads=json_safe_payloads,
    )

    try:
        return model_cls(**filtered)
    except TypeError:
        obj = model_cls()
        _update_instance(
            obj,
            filtered,
            permissive=True,
            json_safe_payloads=json_safe_payloads,
        )
        return obj


def _update_instance(
    obj: Any,
    data: Mapping[str, Any],
    *,
    permissive: bool = False,
    json_safe_payloads: bool = True,
) -> Any:
    model_cls = obj.__class__

    filtered = _filter_model_data(
        model_cls,
        data,
        permissive=permissive,
        json_safe_payloads=json_safe_payloads,
    )

    for key, value in filtered.items():
        try:
            setattr(obj, key, value)
        except Exception:
            continue

    return obj


def _get_attr(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if obj is None:
            continue

        try:
            value = getattr(obj, name)
        except Exception:
            continue

        if value is not None:
            return value

    return default


def _build_foreign_link_payload(
    model_cls: Type[Any],
    *,
    family: Any = None,
    revision: Any = None,
    scan_run: Any = None,
    vplib_uid: Optional[str] = None,
    family_id: Optional[str] = None,
    revision_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Baut robuste Foreign-Key-/Referenzfelder.

    Weil die konkreten Model-Felder variieren können, werden mehrere übliche
    Feldnamen unterstützt. Bei mehrdeutigen Feldern wird anhand von Foreign-Key-
    Markern entschieden, ob technischer PK oder semantischer Wert gesetzt wird.
    """

    data: Dict[str, Any] = {}

    family_pk = _get_object_pk(family)
    revision_pk = _get_object_pk(revision)
    scan_run_pk = _get_object_pk(scan_run)

    if vplib_uid:
        data["vplib_uid"] = vplib_uid

    if revision_hash:
        data["revision_hash"] = revision_hash

    # Family FK candidates.
    for field_name in (
        "creative_library_family_id",
        "library_family_id",
        "family_db_id",
        "family_pk",
        "family_ref_id",
    ):
        if family_pk is not None:
            data[field_name] = family_pk

    if family is not None:
        semantic_family_id = _get_attr(family, "family_id", "semantic_family_id", default=family_id)

        if _column_has_foreign_key(model_cls, "family_id") and family_pk is not None:
            data["family_id"] = family_pk
        elif semantic_family_id is not None:
            data["family_id"] = semantic_family_id

    elif family_id is not None:
        data["family_id"] = family_id

    # Revision FK candidates.
    for field_name in (
        "creative_library_family_revision_id",
        "family_revision_id",
        "revision_db_id",
        "revision_pk",
        "revision_ref_id",
    ):
        if revision_pk is not None:
            data[field_name] = revision_pk

    if revision is not None:
        if _column_has_foreign_key(model_cls, "revision_id") and revision_pk is not None:
            data["revision_id"] = revision_pk
        else:
            semantic_revision_id = _get_attr(revision, "revision_id", default=None)
            if semantic_revision_id is not None:
                data["revision_id"] = semantic_revision_id

    # ScanRun FK candidates.
    for field_name in (
        "creative_library_scan_run_id",
        "library_scan_run_id",
        "scan_run_db_id",
        "scan_run_pk",
    ):
        if scan_run_pk is not None:
            data[field_name] = scan_run_pk

    if scan_run is not None:
        if _column_has_foreign_key(model_cls, "scan_run_id") and scan_run_pk is not None:
            data["scan_run_id"] = scan_run_pk
        else:
            semantic_scan_run_id = _get_attr(scan_run, "scan_run_id", default=None)
            if semantic_scan_run_id is not None:
                data["scan_run_id"] = semantic_scan_run_id

    return data




# ---------------------------------------------------------------------------
# Aggregate / payload normalization helpers
# ---------------------------------------------------------------------------


def _is_empty_mapping(value: Any) -> bool:
    """True, wenn value ein leeres Mapping ist."""

    return isinstance(value, Mapping) and not bool(value)


def _is_empty_sequence(value: Any) -> bool:
    """True, wenn value eine leere nicht-string Sequenz ist."""

    return isinstance(value, (list, tuple, set)) and not bool(value)


def _coerce_optional_text(value: Any) -> Optional[str]:
    """
    Normalisiert optionale Textfelder.

    Mapping-/Listenwerte werden nicht als Text gespeichert. Dadurch landen
    versehentliche `{}`-Payloads nicht in Textspalten wie `path`.
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return _normalize_string(value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Mapping):
        for key in ("path", "relative_path", "uri", "url", "href", "src"):
            nested = value.get(key)
            text = _coerce_optional_text(nested)
            if text:
                return text
        return None

    if isinstance(value, (list, tuple, set)):
        for item in value:
            text = _coerce_optional_text(item)
            if text:
                return text
        return None

    return _normalize_string(value)


def _mapping_has_content(value: Any) -> bool:
    """Prüft, ob ein Payload inhaltlich relevant ist."""

    if value is None:
        return False

    if isinstance(value, Mapping):
        return any(_mapping_has_content(item) for item in value.values())

    if isinstance(value, (list, tuple, set)):
        return any(_mapping_has_content(item) for item in value)

    if isinstance(value, str):
        return bool(value.strip())

    return True


def _safe_count_query(query: Any) -> int:
    """Zählt Query-Ergebnisse defensiv."""

    try:
        return int(query.count())
    except Exception:
        try:
            return len(list(query.all()))
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------


class CreativeLibraryModelRegistry:
    """
    Lazy Registry für models.creative_library.

    Die Registry löst abstrakte Keys wie "family" oder "variant" auf konkrete
    SQLAlchemy-Modelklassen auf. Dadurch bleibt das Repository robust, solange
    die Model-Datei während der Migration noch wächst.
    """

    def __init__(
        self,
        *,
        model_module: Optional[ModuleType] = None,
        model_module_path: Optional[str] = None,
        force_reload: bool = False,
    ) -> None:
        self.model_module = model_module
        self.model_module_path = model_module_path
        self.force_reload = force_reload
        self._resolved: Dict[str, Optional[Type[Any]]] = {}
        self._errors: Dict[str, str] = {}

    def load_module(self, *, required: bool = True) -> Optional[ModuleType]:
        if self.model_module is not None:
            return self.model_module

        module = import_creative_library_model_module(
            configured=self.model_module_path,
            required=required,
            force_reload=self.force_reload,
        )

        self.model_module = module
        return module

    def resolve(self, key: str, *, required: bool = False) -> Optional[Type[Any]]:
        normalized_key = str(key or "").strip()

        if not normalized_key:
            if required:
                raise CreativeLibraryRepositoryValidationError("Empty model key.")
            return None

        if normalized_key in self._resolved:
            model_cls = self._resolved[normalized_key]
            if model_cls is None and required:
                raise CreativeLibraryRepositoryUnavailable(
                    f"Required creative library model is missing: {normalized_key}"
                )
            return model_cls

        module = self.load_module(required=required)

        if module is None:
            self._resolved[normalized_key] = None
            return None

        candidates = MODEL_CANDIDATES.get(normalized_key, (normalized_key,))

        for class_name in candidates:
            model_cls = getattr(module, class_name, None)

            if model_cls is not None:
                self._resolved[normalized_key] = model_cls
                return model_cls

        self._resolved[normalized_key] = None
        self._errors[normalized_key] = (
            f"No model class found for key '{normalized_key}'. "
            f"Tried: {', '.join(candidates)}"
        )

        if required:
            raise CreativeLibraryRepositoryUnavailable(self._errors[normalized_key])

        return None

    def require(self, key: str) -> Type[Any]:
        model_cls = self.resolve(key, required=True)
        assert model_cls is not None
        return model_cls

    def status(self, *, include_traceback: bool = False) -> Dict[str, Any]:
        module_candidates = get_model_module_candidates(self.model_module_path)

        module_status: Dict[str, Any] = {
            "candidates": list(module_candidates),
            "loaded": self.model_module is not None,
            "module": getattr(self.model_module, "__name__", None) if self.model_module else None,
        }

        if self.model_module is None:
            existing_candidates: List[str] = []

            for module_path in module_candidates:
                exists, spec_error = _module_exists(module_path)
                if exists:
                    existing_candidates.append(module_path)

                if spec_error is not None:
                    module_status.setdefault("spec_errors", []).append(
                        {
                            "module_path": module_path,
                            "error_type": spec_error.__class__.__name__,
                            "error": str(spec_error),
                            "traceback": _get_cached_traceback(module_path)
                            if include_traceback
                            else None,
                        }
                    )

            module_status["existing_candidates"] = existing_candidates

        models: Dict[str, Any] = {}

        for key, candidates in MODEL_CANDIDATES.items():
            try:
                model_cls = self.resolve(key, required=False)
            except Exception as exc:
                model_cls = None
                self._errors[key] = f"{exc.__class__.__name__}: {exc}"

            models[key] = {
                "available": model_cls is not None,
                "class_name": getattr(model_cls, "__name__", None) if model_cls else None,
                "candidates": list(candidates),
                "required_core": key in CORE_MODEL_KEYS,
                "recommended": key in RECOMMENDED_MODEL_KEYS,
                "error": self._errors.get(key),
            }

        return {
            "module": module_status,
            "models": models,
        }


# ---------------------------------------------------------------------------
# Repository implementation
# ---------------------------------------------------------------------------


class CreativeLibraryRepository:
    """
    SQL-Repository für Creative-Library-DB-Operationen.

    Diese Klasse soll von DB-Sync- und DB-Read-Services verwendet werden.
    Sie enthält bewusst keine Scanner- oder Validatorlogik.
    """

    def __init__(
        self,
        *,
        db: Any = None,
        session: Any = None,
        model_module: Optional[ModuleType] = None,
        model_module_path: Optional[str] = None,
        config: Optional[CreativeLibraryRepositoryConfig] = None,
    ) -> None:
        if config is None:
            config = CreativeLibraryRepositoryConfig(
                db=db,
                session=session,
                model_module=model_module,
                model_module_path=model_module_path,
                strict_models=_env_bool(CREATIVE_LIBRARY_REPOSITORY_STRICT_ENV, False),
            )
        else:
            db = db if db is not None else config.db
            session = session if session is not None else config.session
            model_module = model_module if model_module is not None else config.model_module
            model_module_path = model_module_path or config.model_module_path

        self.config = config
        self.db = db
        self._session = session
        self.model_registry = CreativeLibraryModelRegistry(
            model_module=model_module,
            model_module_path=model_module_path,
        )

    # ------------------------------------------------------------------
    # Session handling
    # ------------------------------------------------------------------

    def get_session(self, *, required: bool = True) -> Any:
        if self._session is not None:
            return self._session

        if self.db is not None:
            session = getattr(self.db, "session", None)
            if session is not None:
                return session

        extension_module = import_sqlalchemy_extension_module(required=False)

        if extension_module is not None:
            for attr_name in ("db", "database", "sqlalchemy_db"):
                db_object = getattr(extension_module, attr_name, None)

                if db_object is None:
                    continue

                session = getattr(db_object, "session", None)

                if session is not None:
                    self.db = db_object
                    return session

        if required:
            raise CreativeLibraryRepositoryUnavailable(
                "No SQLAlchemy session available. Provide session=..., db=..., "
                "or expose db.session in extensions.py."
            )

        return None

    def query(self, model_cls: Type[Any]) -> Any:
        session = self.get_session(required=True)
        return session.query(model_cls)

    def add(self, obj: Any) -> Any:
        session = self.get_session(required=True)
        session.add(obj)
        return obj

    def flush(self) -> None:
        if not self.config.autoflush:
            return

        session = self.get_session(required=False)

        if session is not None:
            session.flush()

    def commit(self) -> None:
        session = self.get_session(required=False)

        if session is not None:
            session.commit()

    def rollback(self) -> None:
        session = self.get_session(required=False)

        if session is not None:
            session.rollback()

    def _finalize_write(self, *, commit: Optional[bool] = None) -> None:
        should_commit = self.config.autocommit if commit is None else bool(commit)

        self.flush()

        if should_commit:
            self.commit()

    # ------------------------------------------------------------------
    # Aggregate / pointer helpers
    # ------------------------------------------------------------------

    def _set_family_fields(
        self,
        family: Any,
        data: Mapping[str, Any],
        *,
        commit: Optional[bool] = None,
    ) -> Any:
        """
        Aktualisiert Family-Felder ohne zusätzliche Read-/Count-Queries.

        Diese Methode ist der konservative Schreibpfad für den normalen Sync.
        Sie setzt nur Werte, die der Aufrufer bereits kennt.
        """

        if family is None:
            return family

        write_data = dict(data or {})
        write_data.setdefault("updated_at", utcnow())

        _update_instance(
            family,
            write_data,
            permissive=self.config.permissive_model_fields,
            json_safe_payloads=self.config.json_safe_payloads,
        )

        self._finalize_write(commit=commit)
        return family

    def _set_family_revision_pointer(
        self,
        family: Any,
        revision: Any,
        *,
        commit: Optional[bool] = None,
    ) -> Any:
        """
        Setzt den aktuellen Revisionszeiger direkt nach Erzeugen einer Revision.

        Wichtig: Diese Methode zählt keine Child-Tabellen. Sie wird nur im
        New-Revision-Pfad verwendet und bleibt dadurch idempotenzsicher.
        """

        if family is None or revision is None:
            return family

        now = utcnow()
        revision_pk = _get_object_pk(revision)
        revision_hash = _get_attr(revision, "revision_hash", "hash", "content_hash")
        publication_status = _get_attr(
            revision,
            "publication_status",
            "status",
            default=DEFAULT_PUBLICATION_STATUS,
        ) or DEFAULT_PUBLICATION_STATUS

        published_at = _get_attr(revision, "published_at", default=None) or now
        current_revision_count = _safe_int(_get_attr(family, "revision_count"), 0)

        data: Dict[str, Any] = {
            "current_revision_id": revision_pk,
            "current_revision_hash": revision_hash,
            "latest_revision_hash": revision_hash,
            "published_revision_hash": revision_hash,
            "revision_hash": revision_hash,
            "publication_status": publication_status,
            "status": publication_status,
            "published_at": published_at,
            "revision_count": max(current_revision_count + 1, 1),
            "updated_at": now,
        }

        return self._set_family_fields(family, data, commit=commit)

    def _set_family_variant_summary(
        self,
        family: Any,
        *,
        count: int,
        default_variant_id: Optional[str] = None,
        commit: Optional[bool] = None,
    ) -> Any:
        """Setzt Variant-Aggregate direkt aus dem Replace-Ergebnis."""

        data: Dict[str, Any] = {
            "variant_count": max(0, int(count or 0)),
            "updated_at": utcnow(),
        }

        if default_variant_id:
            data["default_variant_id"] = default_variant_id

        return self._set_family_fields(family, data, commit=commit)

    def _set_family_asset_count(
        self,
        family: Any,
        *,
        count: int,
        commit: Optional[bool] = None,
    ) -> Any:
        """Setzt Asset-Aggregate direkt aus dem Replace-Ergebnis."""

        return self._set_family_fields(
            family,
            {
                "asset_count": max(0, int(count or 0)),
                "updated_at": utcnow(),
            },
            commit=commit,
        )

    def _set_family_document_count(
        self,
        family: Any,
        *,
        count: int,
        commit: Optional[bool] = None,
    ) -> Any:
        """Setzt Document-Aggregate direkt aus dem Replace-Ergebnis."""

        return self._set_family_fields(
            family,
            {
                "document_count": max(0, int(count or 0)),
                "updated_at": utcnow(),
            },
            commit=commit,
        )

    def count_family_revisions(self, family: Any) -> int:
        """Zählt alle Revisions einer Family. Nur für explizite Repair-Läufe."""

        revision_model = self.model("family_revision", required=False)

        if revision_model is None:
            return 0

        uid = _normalize_string(_get_attr(family, "vplib_uid"))
        query = self.query(revision_model)
        query = self._filter_query_for_family_or_uid(
            query,
            revision_model,
            family=family,
            vplib_uid=uid,
        )
        return _safe_count_query(query)

    def _count_child_rows(
        self,
        model_key: str,
        *,
        family: Any,
        revision: Any = None,
    ) -> int:
        """
        Zählt Child-Rows robust. Nur für explizite Repair-Läufe.

        Der normale Sync verwendet diese Methode bewusst nicht.
        """

        model_cls = self.model(model_key, required=False)

        if model_cls is None:
            return 0

        query = self.query(model_cls)

        if revision is not None:
            revision_query = self._filter_query_for_revision(
                query,
                model_cls,
                revision=revision,
            )

            if revision_query is not query:
                return _safe_count_query(revision_query)

        uid = _normalize_string(_get_attr(family, "vplib_uid"))

        family_query = self._filter_query_for_family_or_uid(
            query,
            model_cls,
            family=family,
            vplib_uid=uid,
        )

        return _safe_count_query(family_query)

    def _get_default_variant_id(
        self,
        *,
        family: Any,
        revision: Any = None,
    ) -> Optional[str]:
        """Ermittelt die Default-Variant einer Family/Revision. Nur für Repair."""

        variant_model = self.model("variant", required=False)

        if variant_model is None:
            return None

        query = self.query(variant_model)

        if revision is not None:
            revision_query = self._filter_query_for_revision(
                query,
                variant_model,
                revision=revision,
            )
            if revision_query is not query:
                query = revision_query
            else:
                query = self._filter_query_for_family_or_uid(
                    query,
                    variant_model,
                    family=family,
                    vplib_uid=_normalize_string(_get_attr(family, "vplib_uid")),
                )
        else:
            query = self._filter_query_for_family_or_uid(
                query,
                variant_model,
                family=family,
                vplib_uid=_normalize_string(_get_attr(family, "vplib_uid")),
            )

        try:
            if _model_has_field(variant_model, "is_default"):
                default_variant = query.filter(getattr(variant_model, "is_default") == True).first()  # noqa: E712
                variant_id = _get_attr(default_variant, "variant_id", "id_in_family", "slug")
                if variant_id:
                    return str(variant_id)

            if _model_has_field(variant_model, "sort_order"):
                query = query.order_by(getattr(variant_model, "sort_order").asc())

            first_variant = query.first()
            variant_id = _get_attr(first_variant, "variant_id", "id_in_family", "slug")
            return str(variant_id) if variant_id else None
        except Exception:
            return None

    def repair_family_aggregate_fields(
        self,
        family: Any,
        revision: Any = None,
        *,
        update_revision_pointer: bool = True,
        update_variant_count: bool = True,
        update_asset_count: bool = True,
        update_document_count: bool = True,
        commit: Optional[bool] = None,
    ) -> Any:
        """
        Repariert Family-Aggregate explizit durch DB-Reads/Counts.

        Diese Methode ist absichtlich vom normalen Sync getrennt. Sie darf für
        Wartungs-/Backfill-Fälle genutzt werden, wird aber nicht automatisch im
        idempotenten Sync-Pfad ausgeführt.
        """

        if family is None:
            return family

        now = utcnow()

        if revision is None and update_revision_pointer:
            try:
                revision = self.get_latest_revision(family)
            except Exception:
                revision = None

        data: Dict[str, Any] = {
            "updated_at": now,
        }

        if update_revision_pointer and revision is not None:
            revision_pk = _get_object_pk(revision)
            revision_hash = _get_attr(revision, "revision_hash", "hash", "content_hash")
            publication_status = _get_attr(
                revision,
                "publication_status",
                "status",
                default=DEFAULT_PUBLICATION_STATUS,
            ) or DEFAULT_PUBLICATION_STATUS

            data.update(
                {
                    "current_revision_id": revision_pk,
                    "current_revision_hash": revision_hash,
                    "latest_revision_hash": revision_hash,
                    "published_revision_hash": revision_hash,
                    "revision_hash": revision_hash,
                    "publication_status": publication_status,
                    "status": publication_status,
                    "published_at": _get_attr(revision, "published_at", default=now),
                }
            )

        if update_revision_pointer:
            data["revision_count"] = self.count_family_revisions(family)

        if update_variant_count:
            variant_count = self._count_child_rows(
                "variant",
                family=family,
                revision=revision,
            )
            data["variant_count"] = variant_count

            default_variant_id = self._get_default_variant_id(
                family=family,
                revision=revision,
            )
            if default_variant_id:
                data["default_variant_id"] = default_variant_id

        if update_asset_count:
            data["asset_count"] = self._count_child_rows(
                "asset",
                family=family,
                revision=revision,
            )

        if update_document_count:
            data["document_count"] = self._count_child_rows(
                "document",
                family=family,
                revision=revision,
            )

        return self._set_family_fields(family, data, commit=commit)

    def sync_family_aggregate_fields(
        self,
        family: Any,
        revision: Any = None,
        *,
        update_revision_pointer: bool = True,
        update_variant_count: bool = True,
        update_asset_count: bool = True,
        update_document_count: bool = True,
        commit: Optional[bool] = None,
    ) -> Any:
        """
        Backwards-kompatibler Alias für explizite Aggregate-Reparatur.

        Der normale Sync-Pfad ruft diese Methode nicht mehr auf.
        """

        return self.repair_family_aggregate_fields(
            family,
            revision,
            update_revision_pointer=update_revision_pointer,
            update_variant_count=update_variant_count,
            update_asset_count=update_asset_count,
            update_document_count=update_document_count,
            commit=commit,
        )

    def _sync_family_revision_pointer(
        self,
        family: Any,
        revision: Any,
        *,
        commit: Optional[bool] = None,
    ) -> Any:
        """Aktualisiert nur den aktuellen Revisionszeiger ohne Count-Queries."""

        return self._set_family_revision_pointer(
            family,
            revision,
            commit=commit,
        )

    def _sync_family_variant_count(
        self,
        family: Any,
        revision: Any,
        *,
        count: int = 0,
        default_variant_id: Optional[str] = None,
        commit: Optional[bool] = None,
    ) -> Any:
        """Kompatibilitätswrapper: setzt Variant-Count direkt."""

        return self._set_family_variant_summary(
            family,
            count=count,
            default_variant_id=default_variant_id,
            commit=commit,
        )

    def _sync_family_asset_count(
        self,
        family: Any,
        revision: Any,
        *,
        count: int = 0,
        commit: Optional[bool] = None,
    ) -> Any:
        """Kompatibilitätswrapper: setzt Asset-Count direkt."""

        return self._set_family_asset_count(
            family,
            count=count,
            commit=commit,
        )

    def _sync_family_document_count(
        self,
        family: Any,
        revision: Any,
        *,
        count: int = 0,
        commit: Optional[bool] = None,
    ) -> Any:
        """Kompatibilitätswrapper: setzt Document-Count direkt."""

        return self._set_family_document_count(
            family,
            count=count,
            commit=commit,
        )

    # ------------------------------------------------------------------
    # Model helpers
    # ------------------------------------------------------------------

    def model(self, key: str, *, required: bool = True) -> Optional[Type[Any]]:
        return self.model_registry.resolve(key, required=required)

    def require_model(self, key: str) -> Type[Any]:
        return self.model_registry.require(key)

    # ------------------------------------------------------------------
    # Scan runs
    # ------------------------------------------------------------------

    def create_scan_run(
        self,
        payload: Union[CreativeLibraryScanRunPayload, Mapping[str, Any], None] = None,
        *,
        commit: Optional[bool] = None,
    ) -> Any:
        scan_run_model = self.require_model("scan_run")

        data = _to_mapping(payload or {})
        now = utcnow()

        insert_data = {
            "status": data.get("status") or DEFAULT_SCAN_STATUS_RUNNING,
            "source_root": data.get("source_root"),
            "mode": data.get("mode") or "filesystem_sync",
            "triggered_by": data.get("triggered_by"),
            "started_at": data.get("started_at") or now,
            "created_at": data.get("created_at") or now,
            "updated_at": data.get("updated_at") or now,
            "metadata": data.get("metadata") or {},
            "meta": data.get("metadata") or {},
            "details": data.get("metadata") or {},
            "total_count": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "published_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "warning_count": 0,
        }

        obj = _make_instance(
            scan_run_model,
            insert_data,
            permissive=self.config.permissive_model_fields,
            json_safe_payloads=self.config.json_safe_payloads,
        )

        self.add(obj)
        self._finalize_write(commit=commit)
        return obj

    def finish_scan_run(
        self,
        scan_run: Any,
        *,
        stats: Optional[Mapping[str, Any]] = None,
        status: str = DEFAULT_SCAN_STATUS_FINISHED,
        commit: Optional[bool] = None,
    ) -> Any:
        if scan_run is None:
            raise CreativeLibraryRepositoryValidationError("scan_run is required.")

        now = utcnow()
        stats = dict(stats or {})

        data = {
            "status": status,
            "finished_at": now,
            "updated_at": now,
            "total_count": stats.get("total_count", stats.get("total", None)),
            "valid_count": stats.get("valid_count", stats.get("valid", None)),
            "invalid_count": stats.get("invalid_count", stats.get("invalid", None)),
            "published_count": stats.get("published_count", stats.get("published", None)),
            "skipped_count": stats.get("skipped_count", stats.get("skipped", None)),
            "error_count": stats.get("error_count", stats.get("errors", None)),
            "warning_count": stats.get("warning_count", stats.get("warnings", None)),
            "metadata": stats.get("metadata"),
            "meta": stats.get("metadata"),
        }

        _update_instance(
            scan_run,
            data,
            permissive=self.config.permissive_model_fields,
            json_safe_payloads=self.config.json_safe_payloads,
        )

        self._finalize_write(commit=commit)
        return scan_run

    def fail_scan_run(
        self,
        scan_run: Any,
        *,
        error: Optional[BaseException] = None,
        message: Optional[str] = None,
        commit: Optional[bool] = None,
    ) -> Any:
        if scan_run is None:
            raise CreativeLibraryRepositoryValidationError("scan_run is required.")

        now = utcnow()

        error_payload: Dict[str, Any] = {}

        if error is not None:
            error_payload = {
                "error_type": error.__class__.__name__,
                "error": str(error),
                "traceback": traceback_module.format_exc(),
            }
        elif message:
            error_payload = {
                "error": message,
            }

        data = {
            "status": DEFAULT_SCAN_STATUS_FAILED,
            "finished_at": now,
            "updated_at": now,
            "error": message or (str(error) if error is not None else None),
            "error_message": message or (str(error) if error is not None else None),
            "metadata": error_payload,
            "meta": error_payload,
        }

        _update_instance(
            scan_run,
            data,
            permissive=self.config.permissive_model_fields,
            json_safe_payloads=self.config.json_safe_payloads,
        )

        self._finalize_write(commit=commit)
        return scan_run

    def list_scan_runs(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[Any]:
        scan_run_model = self.require_model("scan_run")
        query = self.query(scan_run_model)

        if status and _model_has_field(scan_run_model, "status"):
            query = query.filter(getattr(scan_run_model, "status") == status)

        if _model_has_field(scan_run_model, "started_at"):
            query = query.order_by(getattr(scan_run_model, "started_at").desc())
        elif _model_has_field(scan_run_model, "created_at"):
            query = query.order_by(getattr(scan_run_model, "created_at").desc())

        return query.offset(_safe_offset(offset)).limit(_bounded_limit(limit)).all()

    def get_scan_run(self, scan_run_id: Any) -> Any:
        scan_run_model = self.require_model("scan_run")

        if scan_run_id is None:
            raise CreativeLibraryRepositoryValidationError("scan_run_id is required.")

        query = self.query(scan_run_model)

        if _model_has_field(scan_run_model, "id"):
            obj = query.filter(getattr(scan_run_model, "id") == scan_run_id).first()
            if obj is not None:
                return obj

        if _model_has_field(scan_run_model, "scan_run_id"):
            obj = query.filter(getattr(scan_run_model, "scan_run_id") == scan_run_id).first()
            if obj is not None:
                return obj

        raise CreativeLibraryRepositoryNotFound(f"ScanRun not found: {scan_run_id}")

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def add_issue(
        self,
        payload: Union[CreativeLibraryIssuePayload, Mapping[str, Any]],
        *,
        scan_run: Any = None,
        family: Any = None,
        revision: Any = None,
        commit: Optional[bool] = None,
    ) -> Optional[Any]:
        issue_model = self.model("scan_issue", required=False)

        if issue_model is None:
            return None

        data = _to_mapping(payload)
        now = utcnow()

        if data.get("vplib_uid"):
            data["vplib_uid"] = _normalize_vplib_uid(data["vplib_uid"])

        link_data = _build_foreign_link_payload(
            issue_model,
            family=family,
            revision=revision,
            scan_run=scan_run,
            vplib_uid=data.get("vplib_uid"),
            revision_hash=data.get("revision_hash"),
        )

        insert_data = {
            **link_data,
            "severity": data.get("severity") or "warning",
            "level": data.get("severity") or "warning",
            "code": data.get("code"),
            "message": data.get("message") or data.get("error"),
            "path": data.get("path"),
            "field": data.get("field"),
            "scope": data.get("scope"),
            "source_path": data.get("source_path"),
            "payload": data.get("payload") or {},
            "metadata": data.get("metadata") or {},
            "meta": data.get("metadata") or {},
            "created_at": data.get("created_at") or now,
            "updated_at": data.get("updated_at") or now,
        }

        obj = _make_instance(
            issue_model,
            insert_data,
            permissive=self.config.permissive_model_fields,
            json_safe_payloads=self.config.json_safe_payloads,
        )

        self.add(obj)
        self._finalize_write(commit=commit)
        return obj

    def add_issues(
        self,
        issues: Iterable[Union[CreativeLibraryIssuePayload, Mapping[str, Any]]],
        *,
        scan_run: Any = None,
        family: Any = None,
        revision: Any = None,
        commit: Optional[bool] = None,
    ) -> List[Any]:
        created: List[Any] = []

        for issue in issues:
            obj = self.add_issue(
                issue,
                scan_run=scan_run,
                family=family,
                revision=revision,
                commit=False,
            )

            if obj is not None:
                created.append(obj)

        self._finalize_write(commit=commit)
        return created

    # ------------------------------------------------------------------
    # Families
    # ------------------------------------------------------------------

    def get_family_by_vplib_uid(self, vplib_uid: str) -> Optional[Any]:
        family_model = self.require_model("family")
        uid = _normalize_vplib_uid(vplib_uid)

        if not _model_has_field(family_model, "vplib_uid"):
            raise CreativeLibraryRepositoryUnavailable(
                "Family model does not expose required field: vplib_uid"
            )

        return self.query(family_model).filter(
            getattr(family_model, "vplib_uid") == uid
        ).first()

    def get_family_by_family_id(self, family_id: str) -> Optional[Any]:
        family_model = self.require_model("family")
        value = _normalize_string(family_id)

        if not value:
            return None

        if not _model_has_field(family_model, "family_id"):
            return None

        return self.query(family_model).filter(
            getattr(family_model, "family_id") == value
        ).first()

    def get_family_by_identifier(self, identifier: str) -> Optional[Any]:
        family_model = self.require_model("family")
        value = _normalize_string(identifier)

        if not value:
            return None

        filters = []

        for field_name in ("vplib_uid", "family_id", "package_id", "slug", "family_slug"):
            if _model_has_field(family_model, field_name):
                filters.append(getattr(family_model, field_name) == value)

        # WICHTIG:
        # id ist in PostgreSQL bigint. Nur numerische Identifier gegen id prüfen.
        if _model_has_field(family_model, "id"):
            try:
                numeric_id = int(value)
            except Exception:
                numeric_id = None

            if numeric_id is not None:
                filters.append(getattr(family_model, "id") == numeric_id)

        if not filters:
            return None

        try:
            from sqlalchemy import or_  # type: ignore

            return self.query(family_model).filter(or_(*filters)).first()

        except Exception:
            # Nach einem PostgreSQL-/SQLAlchemy-Fehler ist die Transaction aborted.
            # Vor Fallback-Queries muss zwingend rollback() laufen.
            self.rollback()

            for expression in filters:
                try:
                    obj = self.query(family_model).filter(expression).first()
                    if obj is not None:
                        return obj
                except Exception:
                    self.rollback()
                    continue

        return None

    def upsert_family(
        self,
        payload: Union[CreativeLibraryFamilyUpsertPayload, Mapping[str, Any]],
        *,
        commit: Optional[bool] = None,
    ) -> Any:
        family_model = self.require_model("family")
        data = _to_mapping(payload)
        uid = _normalize_vplib_uid(data.get("vplib_uid"))
        now = utcnow()

        existing = self.get_family_by_vplib_uid(uid)

        family_slug = _first_non_empty(data.get("family_slug"), data.get("slug"))
        label = _first_non_empty(data.get("label"), data.get("name"), family_slug, data.get("family_id"))
        status = _first_non_empty(data.get("publication_status"), data.get("status"), DEFAULT_PUBLICATION_STATUS)

        write_data = {
            "vplib_uid": uid,
            "family_id": data.get("family_id"),
            "package_id": data.get("package_id"),
            "family_slug": family_slug,
            "slug": family_slug,
            "label": label,
            "name": label,
            "description": data.get("description"),
            "object_kind": data.get("object_kind"),
            "domain": data.get("domain"),
            "category": data.get("category"),
            "subcategory": data.get("subcategory"),
            "source_path": data.get("source_path"),
            "package_root": data.get("package_root"),
            "classification_path": data.get("classification_path"),
            "enabled": bool(data.get("enabled", True)),
            "visible": bool(data.get("visible", True)),
            "publication_status": status,
            "status": status,
            "default_variant_id": data.get("default_variant_id"),
            "variant_count": data.get("variant_count"),
            "revision_hash": data.get("revision_hash"),
            "latest_revision_hash": data.get("revision_hash"),
            "scanned_at": data.get("scanned_at") or now,
            "published_at": data.get("published_at") or (now if status == DEFAULT_PUBLICATION_STATUS else None),
            "updated_at": now,
            "metadata": data.get("metadata") or {},
            "meta": data.get("metadata") or {},
            "summary_payload": data.get("summary_payload") or {},
            "payload": data.get("summary_payload") or {},
        }

        if existing is None:
            write_data["created_at"] = now
            obj = _make_instance(
                family_model,
                write_data,
                permissive=self.config.permissive_model_fields,
                json_safe_payloads=self.config.json_safe_payloads,
            )
            self.add(obj)
        else:
            obj = _update_instance(
                existing,
                write_data,
                permissive=self.config.permissive_model_fields,
                json_safe_payloads=self.config.json_safe_payloads,
            )

        self._finalize_write(commit=commit)
        return obj

    def mark_missing_families_deleted(
        self,
        active_vplib_uids: Iterable[str],
        *,
        commit: Optional[bool] = None,
    ) -> int:
        family_model = self.require_model("family")

        if not _model_has_field(family_model, "vplib_uid"):
            return 0

        active = {_normalize_vplib_uid(uid) for uid in active_vplib_uids if uid}
        query = self.query(family_model)

        if active:
            query = query.filter(~getattr(family_model, "vplib_uid").in_(active))

        changed = 0
        now = utcnow()

        for family in query.all():
            current_status = _get_attr(family, "publication_status", "status")

            if current_status == DEFAULT_DELETED_STATUS:
                continue

            _update_instance(
                family,
                {
                    "publication_status": DEFAULT_DELETED_STATUS,
                    "status": DEFAULT_DELETED_STATUS,
                    "enabled": False,
                    "visible": False,
                    "deleted_at": now,
                    "updated_at": now,
                },
                permissive=self.config.permissive_model_fields,
                json_safe_payloads=self.config.json_safe_payloads,
            )
            changed += 1

        self._finalize_write(commit=commit)
        return changed

    # ------------------------------------------------------------------
    # Revisions
    # ------------------------------------------------------------------

    def get_latest_revision(self, family_or_uid: Union[str, Any]) -> Optional[Any]:
        revision_model = self.require_model("family_revision")

        if isinstance(family_or_uid, str):
            family = self.get_family_by_vplib_uid(family_or_uid)
            uid = _normalize_vplib_uid(family_or_uid)
        else:
            family = family_or_uid
            uid = _normalize_string(_get_attr(family, "vplib_uid"))

        query = self.query(revision_model)

        query = self._filter_query_for_family_or_uid(query, revision_model, family=family, vplib_uid=uid)

        if _model_has_field(revision_model, "created_at"):
            query = query.order_by(getattr(revision_model, "created_at").desc())
        elif _model_has_field(revision_model, "published_at"):
            query = query.order_by(getattr(revision_model, "published_at").desc())
        elif _model_has_field(revision_model, "id"):
            query = query.order_by(getattr(revision_model, "id").desc())

        return query.first()

    def get_latest_revision_hash(self, vplib_uid: str) -> Optional[str]:
        latest = self.get_latest_revision(vplib_uid)

        if latest is None:
            return None

        return _get_attr(latest, "revision_hash", "hash", "content_hash")

    def create_revision(
        self,
        family: Any,
        payload: Union[CreativeLibraryRevisionUpsertPayload, Mapping[str, Any]],
        *,
        scan_run: Any = None,
        commit: Optional[bool] = None,
    ) -> Any:
        revision_model = self.require_model("family_revision")
        data = _to_mapping(payload)

        uid = _normalize_vplib_uid(data.get("vplib_uid") or _get_attr(family, "vplib_uid"))
        revision_hash = _normalize_string(data.get("revision_hash"))

        if not revision_hash:
            raise CreativeLibraryRepositoryValidationError("revision_hash is required.")

        now = utcnow()

        link_data = _build_foreign_link_payload(
            revision_model,
            family=family,
            scan_run=scan_run,
            vplib_uid=uid,
            family_id=data.get("family_id") or _get_attr(family, "family_id"),
            revision_hash=revision_hash,
        )

        write_data = {
            **link_data,
            "package_id": data.get("package_id") or _get_attr(family, "package_id"),
            "package_version": data.get("package_version"),
            "schema_version": data.get("schema_version"),
            "validation_status": data.get("validation_status"),
            "publication_status": data.get("publication_status") or DEFAULT_PUBLICATION_STATUS,
            "status": data.get("publication_status") or DEFAULT_PUBLICATION_STATUS,
            "source_path": data.get("source_path") or _get_attr(family, "source_path"),
            "summary_payload": data.get("summary_payload") or {},
            "detail_payload": data.get("detail_payload") or {},
            "raw_documents": data.get("raw_documents") or data.get("documents") or {},
            "documents": data.get("documents") or data.get("raw_documents") or {},
            "validation_payload": data.get("validation_payload") or {},
            "payload": data.get("detail_payload") or data.get("summary_payload") or {},
            "metadata": data.get("metadata") or {},
            "meta": data.get("metadata") or {},
            "created_at": data.get("created_at") or now,
            "published_at": data.get("published_at") or now,
            "updated_at": now,
        }

        obj = _make_instance(
            revision_model,
            write_data,
            permissive=self.config.permissive_model_fields,
            json_safe_payloads=self.config.json_safe_payloads,
        )

        self.add(obj)
        self.flush()

        self._sync_family_revision_pointer(
            family,
            obj,
            commit=False,
        )

        self._finalize_write(commit=commit)
        return obj

    def upsert_revision_if_changed(
        self,
        family: Any,
        payload: Union[CreativeLibraryRevisionUpsertPayload, Mapping[str, Any]],
        *,
        scan_run: Any = None,
        commit: Optional[bool] = None,
    ) -> Tuple[Any, bool]:
        data = _to_mapping(payload)
        revision_hash = _normalize_string(data.get("revision_hash"))

        if not revision_hash:
            raise CreativeLibraryRepositoryValidationError("revision_hash is required.")

        latest = self.get_latest_revision(family)

        if latest is not None:
            latest_hash = _get_attr(latest, "revision_hash", "hash", "content_hash")

            if latest_hash == revision_hash:
                # Idempotenter Pfad: keine Aggregate-/Pointer-Reparatur und
                # keine Child-Count-Queries. Bestehende Altstände werden über
                # repair_family_aggregate_fields(...) gezielt repariert.
                return latest, False

        revision = self.create_revision(
            family,
            data,
            scan_run=scan_run,
            commit=commit,
        )

        return revision, True

    # ------------------------------------------------------------------
    # Replace child collections
    # ------------------------------------------------------------------

    def replace_variants(
        self,
        family: Any,
        revision: Any,
        variants: Iterable[Union[CreativeLibraryVariantPayload, Mapping[str, Any]]],
        *,
        commit: Optional[bool] = None,
    ) -> List[Any]:
        variant_model = self.model("variant", required=False)

        if variant_model is None:
            return []

        self._delete_child_rows(
            variant_model,
            family=family,
            revision=revision,
            vplib_uid=_get_attr(family, "vplib_uid"),
        )

        created: List[Any] = []
        now = utcnow()

        for index, variant in enumerate(variants):
            data = _to_mapping(variant)
            uid = _normalize_vplib_uid(data.get("vplib_uid") or _get_attr(family, "vplib_uid"))
            variant_id = _normalize_string(data.get("variant_id") or data.get("id"))

            if not variant_id:
                continue

            link_data = _build_foreign_link_payload(
                variant_model,
                family=family,
                revision=revision,
                vplib_uid=uid,
                family_id=_get_attr(family, "family_id"),
                revision_hash=data.get("revision_hash") or _get_attr(revision, "revision_hash"),
            )

            write_data = {
                **link_data,
                "variant_id": variant_id,
                "id_in_family": variant_id,
                "label": data.get("label") or variant_id,
                "name": data.get("label") or variant_id,
                "description": data.get("description"),
                "is_default": bool(data.get("is_default", False)),
                "default": bool(data.get("is_default", False)),
                "enabled": bool(data.get("enabled", True)),
                "visible": bool(data.get("visible", True)),
                "sort_order": data.get("sort_order", index),
                "payload": data.get("payload") or {},
                "resolved_payload": data.get("resolved_payload") or {},
                "metadata": data.get("metadata") or {},
                "meta": data.get("metadata") or {},
                "created_at": now,
                "updated_at": now,
            }

            obj = _make_instance(
                variant_model,
                write_data,
                permissive=self.config.permissive_model_fields,
                json_safe_payloads=self.config.json_safe_payloads,
            )

            self.add(obj)
            created.append(obj)

        self.flush()

        default_variant_id = None
        for obj in created:
            if bool(_get_attr(obj, "is_default", "default", default=False)):
                default_variant_id = _get_attr(obj, "variant_id", "id_in_family", "slug")
                break

        if default_variant_id is None and created:
            default_variant_id = _get_attr(created[0], "variant_id", "id_in_family", "slug")

        self._sync_family_variant_count(
            family,
            revision,
            count=len(created),
            default_variant_id=str(default_variant_id) if default_variant_id else None,
            commit=False,
        )

        self._finalize_write(commit=commit)
        return created

    def replace_assets(
        self,
        family: Any,
        revision: Any,
        assets: Iterable[Union[CreativeLibraryAssetPayload, Mapping[str, Any]]],
        *,
        commit: Optional[bool] = None,
    ) -> List[Any]:
        asset_model = self.model("asset", required=False)

        if asset_model is None:
            return []

        self._delete_child_rows(
            asset_model,
            family=family,
            revision=revision,
            vplib_uid=_get_attr(family, "vplib_uid"),
        )

        created: List[Any] = []
        now = utcnow()

        for asset in assets:
            data = _to_mapping(asset)
            uid = _normalize_vplib_uid(data.get("vplib_uid") or _get_attr(family, "vplib_uid"))

            link_data = _build_foreign_link_payload(
                asset_model,
                family=family,
                revision=revision,
                vplib_uid=uid,
                family_id=_get_attr(family, "family_id"),
                revision_hash=data.get("revision_hash") or _get_attr(revision, "revision_hash"),
            )

            path = _coerce_optional_text(
                _first_non_empty(
                    data.get("path"),
                    data.get("relative_path"),
                    data.get("uri"),
                    data.get("url"),
                )
            )
            relative_path = _coerce_optional_text(data.get("relative_path") or data.get("path"))
            uri = _coerce_optional_text(data.get("uri") or data.get("url"))
            payload = data.get("payload") or {}

            role = _normalize_string(data.get("role"))
            asset_type = _normalize_string(data.get("asset_type") or data.get("type"))
            label = _normalize_string(data.get("label") or data.get("name"))

            # Keine leeren Mapping-/Listenwerte in Textfelder schreiben.
            # Gleichzeitig strukturierte Payloads behalten, falls sie fachlich
            # relevant sind.
            if (
                not path
                and not relative_path
                and not uri
                and not _mapping_has_content(payload)
            ):
                continue

            write_data = {
                **link_data,
                "role": role,
                "asset_kind": role,
                "asset_type": asset_type,
                "type": asset_type,
                "path": path,
                "asset_path": path,
                "relative_path": relative_path,
                "uri": uri,
                "label": label or role,
                "mime_type": _normalize_string(data.get("mime_type") or data.get("mimeType")),
                "checksum": _normalize_string(data.get("checksum") or data.get("sha256")),
                "asset_hash": _normalize_string(data.get("asset_hash") or data.get("hash")),
                "size_bytes": data.get("size_bytes"),
                "exists": True,
                "payload": payload,
                "metadata": data.get("metadata") or {},
                "meta": data.get("metadata") or {},
                "created_at": now,
                "updated_at": now,
            }

            obj = _make_instance(
                asset_model,
                write_data,
                permissive=self.config.permissive_model_fields,
                json_safe_payloads=self.config.json_safe_payloads,
            )

            self.add(obj)
            created.append(obj)

        self.flush()
        self._sync_family_asset_count(
            family,
            revision,
            count=len(created),
            commit=False,
        )

        self._finalize_write(commit=commit)
        return created

    def replace_documents(
        self,
        family: Any,
        revision: Any,
        documents: Iterable[Union[CreativeLibraryDocumentPayload, Mapping[str, Any]]],
        *,
        commit: Optional[bool] = None,
    ) -> List[Any]:
        document_model = self.model("document", required=False)

        if document_model is None:
            return []

        self._delete_child_rows(
            document_model,
            family=family,
            revision=revision,
            vplib_uid=_get_attr(family, "vplib_uid"),
        )

        created: List[Any] = []
        now = utcnow()

        for document in documents:
            data = _to_mapping(document)
            uid = _normalize_vplib_uid(data.get("vplib_uid") or _get_attr(family, "vplib_uid"))
            relative_path = _normalize_string(data.get("relative_path") or data.get("path"))

            if not relative_path:
                continue

            link_data = _build_foreign_link_payload(
                document_model,
                family=family,
                revision=revision,
                vplib_uid=uid,
                family_id=_get_attr(family, "family_id"),
                revision_hash=data.get("revision_hash") or _get_attr(revision, "revision_hash"),
            )

            write_data = {
                **link_data,
                "relative_path": relative_path,
                "path": relative_path,
                "document_type": data.get("document_type") or data.get("type"),
                "type": data.get("document_type") or data.get("type"),
                "module": data.get("module"),
                "checksum": data.get("checksum"),
                "payload": data.get("payload") or data.get("document") or {},
                "document": data.get("payload") or data.get("document") or {},
                "metadata": data.get("metadata") or {},
                "meta": data.get("metadata") or {},
                "created_at": now,
                "updated_at": now,
            }

            obj = _make_instance(
                document_model,
                write_data,
                permissive=self.config.permissive_model_fields,
                json_safe_payloads=self.config.json_safe_payloads,
            )

            self.add(obj)
            created.append(obj)

        self.flush()
        self._sync_family_document_count(
            family,
            revision,
            count=len(created),
            commit=False,
        )

        self._finalize_write(commit=commit)
        return created

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def list_published_families(
        self,
        *,
        domain: Optional[str] = None,
        category: Optional[str] = None,
        subcategory: Optional[str] = None,
        object_kind: Optional[str] = None,
        q: Optional[str] = None,
        include_unpublished: bool = False,
        include_deleted: bool = False,
        enabled_only: bool = True,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
    ) -> List[Any]:
        family_model = self.require_model("family")
        query = self.query(family_model)

        if not include_unpublished:
            query = self._filter_publication_status(query, family_model)

        if not include_deleted:
            query = self._filter_not_deleted(query, family_model)

        if enabled_only:
            query = self._filter_enabled(query, family_model)

        for field_name, value in (
            ("domain", domain),
            ("category", category),
            ("subcategory", subcategory),
            ("object_kind", object_kind),
        ):
            normalized = _normalize_string(value)

            if normalized and _model_has_field(family_model, field_name):
                query = query.filter(getattr(family_model, field_name) == normalized)

        search = _normalize_string(q)
        if search:
            query = self._apply_search(query, family_model, search)

        if _model_has_field(family_model, "domain"):
            query = query.order_by(getattr(family_model, "domain").asc())

        if _model_has_field(family_model, "category"):
            query = query.order_by(getattr(family_model, "category").asc())

        if _model_has_field(family_model, "subcategory"):
            query = query.order_by(getattr(family_model, "subcategory").asc())

        if _model_has_field(family_model, "label"):
            query = query.order_by(getattr(family_model, "label").asc())
        elif _model_has_field(family_model, "family_id"):
            query = query.order_by(getattr(family_model, "family_id").asc())

        return query.offset(_safe_offset(offset)).limit(_bounded_limit(limit)).all()

    def count_published_families(
        self,
        *,
        include_unpublished: bool = False,
        include_deleted: bool = False,
    ) -> int:
        family_model = self.require_model("family")
        query = self.query(family_model)

        if not include_unpublished:
            query = self._filter_publication_status(query, family_model)

        if not include_deleted:
            query = self._filter_not_deleted(query, family_model)

        return int(query.count())

    def get_published_family_detail(
        self,
        identifier: str,
        *,
        include_unpublished: bool = False,
    ) -> Dict[str, Any]:
        family = self.get_family_by_identifier(identifier)

        if family is None:
            raise CreativeLibraryRepositoryNotFound(f"Family not found: {identifier}")

        if not include_unpublished and not self._is_published_family(family):
            raise CreativeLibraryRepositoryNotFound(f"Published family not found: {identifier}")

        revision = self.get_latest_revision(family)
        variants = self.get_family_variants(_get_attr(family, "vplib_uid"), include_unpublished=include_unpublished)
        assets = self.get_family_assets(_get_attr(family, "vplib_uid"))
        documents = self.get_family_documents(_get_attr(family, "vplib_uid"))

        return {
            "family": family,
            "revision": revision,
            "variants": variants,
            "assets": assets,
            "documents": documents,
        }

    def get_family_variants(
        self,
        identifier: str,
        *,
        include_unpublished: bool = False,
    ) -> List[Any]:
        variant_model = self.model("variant", required=False)

        if variant_model is None:
            return []

        family = self.get_family_by_identifier(identifier)
        uid = _normalize_string(_get_attr(family, "vplib_uid")) if family is not None else _normalize_string(identifier)

        query = self.query(variant_model)
        query = self._filter_query_for_family_or_uid(query, variant_model, family=family, vplib_uid=uid)

        if not include_unpublished:
            query = self._filter_not_deleted(query, variant_model)

        if _model_has_field(variant_model, "sort_order"):
            query = query.order_by(getattr(variant_model, "sort_order").asc())

        if _model_has_field(variant_model, "variant_id"):
            query = query.order_by(getattr(variant_model, "variant_id").asc())

        return query.all()

    def get_family_assets(self, identifier: str) -> List[Any]:
        asset_model = self.model("asset", required=False)

        if asset_model is None:
            return []

        family = self.get_family_by_identifier(identifier)
        uid = _normalize_string(_get_attr(family, "vplib_uid")) if family is not None else _normalize_string(identifier)

        query = self.query(asset_model)
        query = self._filter_query_for_family_or_uid(query, asset_model, family=family, vplib_uid=uid)

        return query.all()

    def get_family_documents(self, identifier: str) -> List[Any]:
        document_model = self.model("document", required=False)

        if document_model is None:
            return []

        family = self.get_family_by_identifier(identifier)
        uid = _normalize_string(_get_attr(family, "vplib_uid")) if family is not None else _normalize_string(identifier)

        query = self.query(document_model)
        query = self._filter_query_for_family_or_uid(query, document_model, family=family, vplib_uid=uid)

        if _model_has_field(document_model, "relative_path"):
            query = query.order_by(getattr(document_model, "relative_path").asc())
        elif _model_has_field(document_model, "path"):
            query = query.order_by(getattr(document_model, "path").asc())

        return query.all()

    def list_inventory_slots(
        self,
        *,
        include_inactive: bool = False,
    ) -> List[Any]:
        slot_model = self.model("inventory_slot", required=False)

        if slot_model is None:
            return []

        query = self.query(slot_model)

        if not include_inactive:
            if _model_has_field(slot_model, "active"):
                query = query.filter(getattr(slot_model, "active") == True)  # noqa: E712
            elif _model_has_field(slot_model, "enabled"):
                query = query.filter(getattr(slot_model, "enabled") == True)  # noqa: E712

        if _model_has_field(slot_model, "slot_index"):
            query = query.order_by(getattr(slot_model, "slot_index").asc())
        elif _model_has_field(slot_model, "index"):
            query = query.order_by(getattr(slot_model, "index").asc())

        return query.all()

    # ------------------------------------------------------------------
    # Utility read serialization
    # ------------------------------------------------------------------

    def family_to_dict(self, family: Any) -> Dict[str, Any]:
        return _object_to_dict(family)

    def revision_to_dict(self, revision: Any) -> Dict[str, Any]:
        return _object_to_dict(revision)

    def variant_to_dict(self, variant: Any) -> Dict[str, Any]:
        return _object_to_dict(variant)

    def asset_to_dict(self, asset: Any) -> Dict[str, Any]:
        return _object_to_dict(asset)

    def document_to_dict(self, document: Any) -> Dict[str, Any]:
        return _object_to_dict(document)

    def issue_to_dict(self, issue: Any) -> Dict[str, Any]:
        return _object_to_dict(issue)

    # ------------------------------------------------------------------
    # Query helper internals
    # ------------------------------------------------------------------

    def _filter_query_for_family_or_uid(
        self,
        query: Any,
        model_cls: Type[Any],
        *,
        family: Any = None,
        vplib_uid: Optional[str] = None,
    ) -> Any:
        uid = _normalize_string(vplib_uid or _get_attr(family, "vplib_uid"))
        family_pk = _get_object_pk(family)
        semantic_family_id = _normalize_string(_get_attr(family, "family_id"))

        filters = []

        if uid and _model_has_field(model_cls, "vplib_uid"):
            filters.append(getattr(model_cls, "vplib_uid") == uid)

        for field_name in (
            "creative_library_family_id",
            "library_family_id",
            "family_db_id",
            "family_pk",
            "family_ref_id",
        ):
            if family_pk is not None and _model_has_field(model_cls, field_name):
                filters.append(getattr(model_cls, field_name) == family_pk)

        if _model_has_field(model_cls, "family_id"):
            if _column_has_foreign_key(model_cls, "family_id") and family_pk is not None:
                filters.append(getattr(model_cls, "family_id") == family_pk)
            elif semantic_family_id:
                filters.append(getattr(model_cls, "family_id") == semantic_family_id)

        if not filters:
            return query

        try:
            from sqlalchemy import or_  # type: ignore

            return query.filter(or_(*filters))
        except Exception:
            return query.filter(filters[0])

    def _filter_query_for_revision(
        self,
        query: Any,
        model_cls: Type[Any],
        *,
        revision: Any = None,
        revision_hash: Optional[str] = None,
    ) -> Any:
        revision_pk = _get_object_pk(revision)
        revision_hash_value = _normalize_string(revision_hash or _get_attr(revision, "revision_hash"))

        filters = []

        for field_name in (
            "creative_library_family_revision_id",
            "family_revision_id",
            "revision_db_id",
            "revision_pk",
            "revision_ref_id",
        ):
            if revision_pk is not None and _model_has_field(model_cls, field_name):
                filters.append(getattr(model_cls, field_name) == revision_pk)

        if revision_hash_value and _model_has_field(model_cls, "revision_hash"):
            filters.append(getattr(model_cls, "revision_hash") == revision_hash_value)

        if not filters:
            return query

        try:
            from sqlalchemy import or_  # type: ignore

            return query.filter(or_(*filters))
        except Exception:
            return query.filter(filters[0])

    def _delete_child_rows(
        self,
        model_cls: Type[Any],
        *,
        family: Any,
        revision: Any,
        vplib_uid: Optional[str],
    ) -> int:
        query = self.query(model_cls)

        filtered_query = self._filter_query_for_revision(query, model_cls, revision=revision)

        # Wenn keine Revisionsfelder vorhanden sind, auf Family/UID fallbacken.
        if filtered_query is query:
            filtered_query = self._filter_query_for_family_or_uid(
                query,
                model_cls,
                family=family,
                vplib_uid=vplib_uid,
            )

        try:
            count = int(filtered_query.delete(synchronize_session=False))
            return count
        except Exception:
            count = 0

            for obj in filtered_query.all():
                self.get_session(required=True).delete(obj)
                count += 1

            return count

    def _filter_publication_status(self, query: Any, model_cls: Type[Any]) -> Any:
        if _model_has_field(model_cls, "publication_status"):
            return query.filter(
                getattr(model_cls, "publication_status").in_(
                    [DEFAULT_PUBLICATION_STATUS, "active", "published"]
                )
            )

        if _model_has_field(model_cls, "status"):
            return query.filter(
                getattr(model_cls, "status").in_(
                    [DEFAULT_PUBLICATION_STATUS, "active", "published"]
                )
            )

        return query

    def _filter_not_deleted(self, query: Any, model_cls: Type[Any]) -> Any:
        if _model_has_field(model_cls, "publication_status"):
            query = query.filter(getattr(model_cls, "publication_status") != DEFAULT_DELETED_STATUS)

        if _model_has_field(model_cls, "status"):
            query = query.filter(getattr(model_cls, "status") != DEFAULT_DELETED_STATUS)

        if _model_has_field(model_cls, "deleted_at"):
            query = query.filter(getattr(model_cls, "deleted_at").is_(None))

        return query

    def _filter_enabled(self, query: Any, model_cls: Type[Any]) -> Any:
        if _model_has_field(model_cls, "enabled"):
            query = query.filter(getattr(model_cls, "enabled") == True)  # noqa: E712

        return query

    def _apply_search(self, query: Any, model_cls: Type[Any], search: str) -> Any:
        fields = [
            field_name
            for field_name in ("label", "name", "family_id", "package_id", "vplib_uid", "description")
            if _model_has_field(model_cls, field_name)
        ]

        if not fields:
            return query

        pattern = f"%{search}%"

        try:
            from sqlalchemy import or_  # type: ignore

            return query.filter(or_(*(getattr(model_cls, field).ilike(pattern) for field in fields)))
        except Exception:
            return query.filter(getattr(model_cls, fields[0]).like(pattern))

    def _is_published_family(self, family: Any) -> bool:
        status = _get_attr(family, "publication_status", "status", default=DEFAULT_PUBLICATION_STATUS)

        if status in {DEFAULT_DELETED_STATUS, DEFAULT_DRAFT_STATUS, "unpublished", "inactive"}:
            return False

        enabled = _get_attr(family, "enabled", default=True)

        if enabled is False:
            return False

        return True

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(
        self,
        *,
        strict: bool = False,
        check_session: bool = False,
        include_traceback: bool = False,
    ) -> Dict[str, Any]:
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        registry_status = self.model_registry.status(include_traceback=include_traceback)

        for key in CORE_MODEL_KEYS:
            model_status = registry_status.get("models", {}).get(key, {})

            if not model_status.get("available"):
                payload = {
                    "scope": "model",
                    "key": key,
                    "required": True,
                    "error": model_status.get("error") or f"Required model missing: {key}",
                }

                if strict:
                    errors.append(payload)
                else:
                    warnings.append(payload)

        for key in RECOMMENDED_MODEL_KEYS:
            model_status = registry_status.get("models", {}).get(key, {})

            if not model_status.get("available"):
                warnings.append(
                    {
                        "scope": "model",
                        "key": key,
                        "required": False,
                        "error": model_status.get("error") or f"Recommended model missing: {key}",
                    }
                )

        session_status = {
            "checked": check_session,
            "available": None,
            "error": None,
        }

        if check_session:
            try:
                session = self.get_session(required=True)
                session_status["available"] = session is not None
            except Exception as exc:
                session_status["available"] = False
                session_status["error"] = f"{exc.__class__.__name__}: {exc}"
                errors.append(
                    {
                        "scope": "session",
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    }
                )

        ok = not errors

        if not ok:
            status_text = "error"
        elif warnings:
            status_text = "partial"
        else:
            status_text = "ok"

        return {
            "ok": ok,
            "status": status_text,
            "strict": strict,
            "component": CREATIVE_LIBRARY_REPOSITORY_COMPONENT,
            "name": CREATIVE_LIBRARY_REPOSITORY_NAME,
            "version": __version__,
            "api_version": CREATIVE_LIBRARY_REPOSITORY_API_VERSION,
            "implementation_stage": CREATIVE_LIBRARY_REPOSITORY_IMPLEMENTATION_STAGE,
            "model_registry": registry_status,
            "session": session_status,
            "config": {
                "autocommit": self.config.autocommit,
                "autoflush": self.config.autoflush,
                "strict_models": self.config.strict_models,
                "json_safe_payloads": self.config.json_safe_payloads,
                "permissive_model_fields": self.config.permissive_model_fields,
                "model_module_path": self.config.model_module_path,
            },
            "errors": errors,
            "warnings": warnings,
        }


# ---------------------------------------------------------------------------
# Factory / default singleton
# ---------------------------------------------------------------------------


def create_creative_library_repository(
    *,
    db: Any = None,
    session: Any = None,
    model_module: Optional[ModuleType] = None,
    model_module_path: Optional[str] = None,
    config: Optional[CreativeLibraryRepositoryConfig] = None,
) -> CreativeLibraryRepository:
    """Erstellt eine neue Repository-Instanz ohne globalen Cache."""

    return CreativeLibraryRepository(
        db=db,
        session=session,
        model_module=model_module,
        model_module_path=model_module_path,
        config=config,
    )


def get_creative_library_repository(
    *,
    db: Any = None,
    session: Any = None,
    model_module: Optional[ModuleType] = None,
    model_module_path: Optional[str] = None,
    config: Optional[CreativeLibraryRepositoryConfig] = None,
    use_cache: bool = False,
    force_new: bool = False,
) -> CreativeLibraryRepository:
    """
    Liefert eine Repository-Instanz.

    use_cache=False:
        Standardmäßig wird eine neue Instanz erzeugt. Das ist für Tests und
        request-lokale Sessions sicherer.

    use_cache=True:
        Nutzt einen einfachen Prozesscache für das Default-Repository.
    """

    if force_new or not use_cache:
        return create_creative_library_repository(
            db=db,
            session=session,
            model_module=model_module,
            model_module_path=model_module_path,
            config=config,
        )

    return get_default_creative_library_repository(
        db=db,
        session=session,
        model_module=model_module,
        model_module_path=model_module_path,
        config=config,
    )


def get_default_creative_library_repository(
    *,
    db: Any = None,
    session: Any = None,
    model_module: Optional[ModuleType] = None,
    model_module_path: Optional[str] = None,
    config: Optional[CreativeLibraryRepositoryConfig] = None,
) -> CreativeLibraryRepository:
    """Liefert ein gecachtes Default-Repository."""

    global _DEFAULT_REPOSITORY

    with _CACHE_LOCK:
        if _DEFAULT_REPOSITORY is None:
            _DEFAULT_REPOSITORY = create_creative_library_repository(
                db=db,
                session=session,
                model_module=model_module,
                model_module_path=model_module_path,
                config=config,
            )

        return _DEFAULT_REPOSITORY


# ---------------------------------------------------------------------------
# Module-level health / cache
# ---------------------------------------------------------------------------


def get_creative_library_repository_health(
    *,
    strict: bool = False,
    check_session: bool = False,
    include_traceback: bool = False,
) -> Dict[str, Any]:
    repository = get_creative_library_repository(use_cache=True)

    return repository.health(
        strict=strict,
        check_session=check_session,
        include_traceback=include_traceback,
    )


def assert_creative_library_repository_ready(
    *,
    strict: bool = True,
    check_session: bool = True,
) -> Dict[str, Any]:
    health = get_creative_library_repository_health(
        strict=strict,
        check_session=check_session,
    )

    if not health.get("ok"):
        raise CreativeLibraryRepositoryUnavailable(
            "CreativeLibraryRepository is not ready "
            f"(status={health.get('status')}, "
            f"errors={len(health.get('errors') or [])}, "
            f"warnings={len(health.get('warnings') or [])})."
        )

    return health


def clear_creative_library_repository_cache() -> Dict[str, Any]:
    """Leert Modul-/Import-/Default-Repository-Caches."""

    global _DEFAULT_REPOSITORY

    with _CACHE_LOCK:
        cached_modules = sorted(_MODEL_MODULE_CACHE.keys())
        cached_errors = sorted(_IMPORT_ERROR_CACHE.keys())

        _DEFAULT_REPOSITORY = None
        _MODEL_MODULE_CACHE.clear()
        _IMPORT_ERROR_CACHE.clear()
        _IMPORT_TRACEBACK_CACHE.clear()

    return {
        "ok": True,
        "cleared_default_repository": True,
        "cleared_module_cache": cached_modules,
        "cleared_import_error_cache": cached_errors,
    }


clear_creative_library_repository_caches = clear_creative_library_repository_cache
clear_repository_cache = clear_creative_library_repository_cache
clear_repository_caches = clear_creative_library_repository_cache


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "CREATIVE_LIBRARY_REPOSITORY_NAME",
    "CREATIVE_LIBRARY_REPOSITORY_COMPONENT",
    "CREATIVE_LIBRARY_REPOSITORY_API_VERSION",
    "CREATIVE_LIBRARY_REPOSITORY_IMPLEMENTATION_STAGE",
    "CREATIVE_LIBRARY_MODEL_MODULE_ENV",
    "SQLALCHEMY_EXTENSION_MODULE_ENV",
    "CREATIVE_LIBRARY_REPOSITORY_STRICT_ENV",
    "DEFAULT_CREATIVE_LIBRARY_MODEL_MODULE",
    "DEFAULT_SQLALCHEMY_EXTENSION_MODULE",
    "MODEL_CANDIDATES",
    "CORE_MODEL_KEYS",
    "RECOMMENDED_MODEL_KEYS",

    # Exceptions
    "CreativeLibraryRepositoryError",
    "CreativeLibraryRepositoryUnavailable",
    "CreativeLibraryRepositoryConflict",
    "CreativeLibraryRepositoryNotFound",
    "CreativeLibraryRepositoryValidationError",

    # Payloads / config
    "CreativeLibraryRepositoryConfig",
    "CreativeLibraryScanRunPayload",
    "CreativeLibraryScanRunSummary",
    "CreativeLibraryFamilyUpsertPayload",
    "CreativeLibraryRevisionUpsertPayload",
    "CreativeLibraryVariantPayload",
    "CreativeLibraryAssetPayload",
    "CreativeLibraryDocumentPayload",
    "CreativeLibraryIssuePayload",

    # Registry / repository
    "CreativeLibraryModelRegistry",
    "CreativeLibraryRepository",

    # Import helpers
    "get_model_module_candidates",
    "get_extension_module_candidates",
    "import_creative_library_model_module",
    "import_sqlalchemy_extension_module",

    # Factories
    "create_creative_library_repository",
    "get_creative_library_repository",
    "get_default_creative_library_repository",

    # Health / cache
    "get_creative_library_repository_health",
    "assert_creative_library_repository_ready",
    "clear_creative_library_repository_cache",
    "clear_creative_library_repository_caches",
    "clear_repository_cache",
    "clear_repository_caches",
]