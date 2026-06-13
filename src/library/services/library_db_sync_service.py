# services/vectoplan-library/src/library/services/library_db_sync_service.py
"""
DB-Sync-Service für die VECTOPLAN Creative Library.

Diese Datei schließt die persistente Schleife:

    src/library/source
        → Scanner
        → Reader
        → Validation
        → Fingerprint
        → Read-/Scan-Result
        → library_db_sync_service
        → creative_library Tabellen
        → DB-basierte Read-Services / API

Aufgaben:

- dateibasierten Library-Scan auslösen
- vorhandene Scan-/Pipeline-Ergebnisse in DB schreiben
- ScanRun in der Datenbank anlegen und abschließen
- gültige Packages anhand vplib_uid upserten
- Revisionen anhand revision_hash erzeugen
- Varianten, Assets und Dokumente revisionsbezogen speichern
- Issues speichern
- ungültige Packages als Issues protokollieren
- optional fehlende Packages als deleted/inactive markieren
- robust mit unterschiedlichen ScanResult-/Pipeline-Strukturen umgehen
- Manifest-/Dokumentdaten notfalls direkt aus dem Package-Verzeichnis laden

Wichtige Architekturregeln:

- Dieser Service erzeugt keine vplib_uid.
- Fehlende oder ungültige vplib_uid wird nicht repariert.
- Die DB übernimmt vplib_uid aus vplib.manifest.json.
- Scanner/Reader/Validator/Fingerprint schreiben weiterhin nicht direkt in die DB.
- Repository-Details liegen in repositories/sql/creative_library_repository.py.
- API-Routen sollen diesen Service für POST /api/v1/vplib/library/sync nutzen.

Warum Dateisystem-Fallback nötig ist:

Einige Scan-/Summary-Objekte enthalten zwar family_id, package_id, source_path
und revision_hash, aber nicht die vollständigen geladenen Dokumente. Für den
DB-Sync ist `vplib_uid` jedoch Pflicht und steht im Manifest. Deshalb liest diese
Datei bei fehlenden Dokumenten defensiv aus:

    <package_root>/vplib.manifest.json
    <package_root>/family/identity.json
    <package_root>/family/classification.json
    <package_root>/editor/inventory.json
    <package_root>/variants/*.json
    ...

Der Fallback erzeugt keine IDs und schreibt keine Source-Dateien. Er liest nur.
"""

from __future__ import annotations

import importlib
import json
import os
import threading
import time
import traceback as traceback_module
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Domain imports
# ---------------------------------------------------------------------------

from ..domain.sync_result import (
    DEFAULT_SYNC_MODE,
    DEFAULT_SYNC_SOURCE,
    DEFAULT_SYNC_TARGET,
    LibrarySyncCandidateResult,
    LibrarySyncCandidateStatus,
    LibrarySyncIssue,
    LibrarySyncIssueSeverity,
    LibrarySyncOperation,
    LibrarySyncOperationResult,
    LibrarySyncResult,
    LibrarySyncRunInfo,
    LibrarySyncStats,
    LibrarySyncStatus,
    build_empty_sync_result,
    build_error_sync_result,
    build_sync_response,
)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

LIBRARY_DB_SYNC_SERVICE_NAME = "library_db_sync_service"
LIBRARY_DB_SYNC_COMPONENT_NAME = "creative_library_db_sync"
LIBRARY_DB_SYNC_API_VERSION = "v1"
LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE = "db-sync-service"

__version__ = "0.1.2"


# ---------------------------------------------------------------------------
# Environment / defaults
# ---------------------------------------------------------------------------

ENV_SYNC_ENABLED = "VPLIB_LIBRARY_SYNC_ENABLED"
ENV_SYNC_STRICT = "VPLIB_LIBRARY_SYNC_STRICT"
ENV_SYNC_AUTOCOMMIT = "VPLIB_LIBRARY_SYNC_AUTOCOMMIT"
ENV_SYNC_MARK_MISSING_DELETED = "VPLIB_LIBRARY_SYNC_MARK_MISSING_DELETED"
ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR = "VPLIB_LIBRARY_SYNC_CONTINUE_ON_CANDIDATE_ERROR"
ENV_SYNC_INCLUDE_RAW_DOCUMENTS = "VPLIB_LIBRARY_SYNC_INCLUDE_RAW_DOCUMENTS"

DEFAULT_SYNC_ENABLED = True
DEFAULT_SYNC_STRICT = False
DEFAULT_SYNC_AUTOCOMMIT = True
DEFAULT_SYNC_MARK_MISSING_DELETED = False
DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR = True
DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS = True

DEFAULT_REPOSITORY_FACTORY_IMPORT = "library.repositories.sql"
DEFAULT_SCAN_SERVICE_IMPORT = "library.services.library_scan_service"

DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD = 10_000
DEFAULT_ISSUE_LIMIT_PER_CANDIDATE = 2_000

MANIFEST_DOCUMENT_KEYS: Tuple[str, ...] = (
    "vplib.manifest.json",
    "manifest.json",
    "package.manifest.json",
)

IDENTITY_DOCUMENT_KEYS: Tuple[str, ...] = (
    "family/identity.json",
    "identity.json",
)

CLASSIFICATION_DOCUMENT_KEYS: Tuple[str, ...] = (
    "family/classification.json",
    "classification.json",
)

INVENTORY_DOCUMENT_KEYS: Tuple[str, ...] = (
    "editor/inventory.json",
    "inventory.json",
)

DOCUMENT_WRAPPER_KEYS: Tuple[str, ...] = (
    "payload",
    "document",
    "content",
    "data",
    "json",
    "value",
)

DOCUMENT_PATH_KEYS: Tuple[str, ...] = (
    "relative_path",
    "document_path",
    "path",
    "name",
)


# ---------------------------------------------------------------------------
# Internal import caches
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.RLock()
_IMPORT_CACHE: Dict[str, ModuleType] = {}
_IMPORT_ERROR_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_SERVICE: Optional["LibraryDbSyncService"] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LibraryDbSyncServiceError(RuntimeError):
    """Basisklasse für DB-Sync-Service-Fehler."""


class LibraryDbSyncDisabledError(LibraryDbSyncServiceError):
    """DB-Sync ist per Konfiguration deaktiviert."""


class LibraryDbSyncImportError(LibraryDbSyncServiceError):
    """Benötigtes Modul konnte nicht importiert werden."""


class LibraryDbSyncValidationError(LibraryDbSyncServiceError):
    """Ungültiger Sync-Payload oder ungültiger Kandidat."""


class LibraryDbSyncCandidateError(LibraryDbSyncServiceError):
    """Fehler beim Synchronisieren eines einzelnen Kandidaten."""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LibraryDbSyncServiceConfig:
    """
    Konfiguration für LibraryDbSyncService.

    repository:
        Optional injiziertes Repository.

    repository_factory:
        Optional Callable, das ein Repository liefert.

    scan_service:
        Optional injiziertes Scan-Service-Modul oder Objekt.

    enabled:
        Wenn False, verweigert der Service Schreiboperationen.

    strict:
        Wenn True, werden fehlende optionale Strukturen härter behandelt.

    autocommit:
        Wenn True, committet der Service am Ende eines Sync-Laufs.

    mark_missing_deleted:
        Wenn True, werden in DB vorhandene Families, die nicht mehr im Scan
        vorkommen, als deleted/inactive markiert.

    continue_on_candidate_error:
        Wenn True, wird ein Kandidatenfehler protokolliert und der Sync läuft
        weiter.

    include_raw_documents:
        Wenn True, werden Dokumentpayloads für Revisionsspeicherung extrahiert.

    publish_valid_only:
        Wenn True, werden invalid Packages nicht veröffentlicht, sondern nur
        als Issues protokolliert.
    """

    repository: Any = None
    repository_factory: Any = None
    scan_service: Any = None

    enabled: bool = DEFAULT_SYNC_ENABLED
    strict: bool = DEFAULT_SYNC_STRICT
    autocommit: bool = DEFAULT_SYNC_AUTOCOMMIT
    mark_missing_deleted: bool = DEFAULT_SYNC_MARK_MISSING_DELETED
    continue_on_candidate_error: bool = DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR
    include_raw_documents: bool = DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS
    publish_valid_only: bool = True

    repository_import_path: str = DEFAULT_REPOSITORY_FACTORY_IMPORT
    scan_service_import_path: str = DEFAULT_SCAN_SERVICE_IMPORT

    document_limit_for_detail_payload: int = DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD
    issue_limit_per_candidate: int = DEFAULT_ISSUE_LIMIT_PER_CANDIDATE


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def monotonic_ms() -> int:
    """Monotonic timestamp in Millisekunden."""

    return int(time.monotonic() * 1000)


def duration_ms(start_ms: Optional[int], end_ms: Optional[int] = None) -> Optional[int]:
    if start_ms is None:
        return None

    return max(0, (end_ms or monotonic_ms()) - start_ms)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def normalize_vplib_uid(value: Any) -> Optional[str]:
    text = normalize_string(value)
    return text.lower() if text else None


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

    if text in {"1", "true", "yes", "y", "on", "active", "enabled", "valid"}:
        return True

    if text in {"0", "false", "no", "n", "off", "inactive", "disabled", "invalid"}:
        return False

    return default


def dataclass_shallow_dict(value: Any) -> Dict[str, Any]:
    """
    Wandelt Dataclasses ohne rekursives `asdict(...)` in ein Dict.

    Grund:
        Scan-/Sync-Pipeline-Objekte können große verschachtelte Payloads
        enthalten. `dataclasses.asdict(...)` kopiert rekursiv alles und kann
        den HTTP-Sync massiv verlangsamen oder scheinbar hängen lassen.
    """

    if not is_dataclass(value):
        return {}

    result: Dict[str, Any] = {}

    try:
        for field_info in fields(value):
            try:
                result[field_info.name] = getattr(value, field_info.name)
            except Exception:
                continue
    except Exception:
        return {}

    return result


def json_safe(value: Any) -> Any:
    """Defensiv JSON-kompatible Struktur bauen."""

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return json_safe(to_dict())
        except TypeError:
            try:
                return json_safe(to_dict(include_raw_documents=False))
            except TypeError:
                try:
                    return json_safe(to_dict(flat=True))
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    if is_dataclass(value):
        return json_safe(dataclass_shallow_dict(value))

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def to_mapping(value: Any) -> Dict[str, Any]:
    """
    Konvertiert Mapping, Dataclass oder Fremdobjekt defensiv in Dict.

    Wichtig:
        Diese Funktion nutzt absichtlich kein rekursives `asdict(...)`, weil
        LibraryScanPipelineResult große Read-/Validation-Rohdaten enthalten kann.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            result = value.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
        except TypeError:
            try:
                result = value.to_dict(include_raw_documents=False)
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
        except Exception:
            pass

    if is_dataclass(value):
        return dataclass_shallow_dict(value)

    result: Dict[str, Any] = {}

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


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None

def get_direct_value(value: Any, key: str, default: Any = None) -> Any:
    """Liest einen direkten Mapping-Key oder ein Attribut ohne Vollserialisierung."""

    try:
        if value is None:
            return default

        if isinstance(value, Mapping):
            return value.get(key, default)

        return getattr(value, key, default)

    except Exception:
        return default


def deep_get(data: Any, *paths: str, default: Any = None) -> Any:
    """
    Liest verschachtelte Dict-/Objektwerte.

    Pfadsyntax:
        "summary.vplib_uid"

    Für Dokumentkeys mit Punkten, z. B. `vplib.manifest.json`, nicht diese
    Funktion verwenden, sondern `get_document(...)`.
    """

    for path in paths:
        current = data
        found = True

        for part in str(path).split("."):
            if current is None:
                found = False
                break

            if isinstance(current, Mapping):
                if part in current:
                    current = current.get(part)
                else:
                    found = False
                    break
            else:
                try:
                    current = getattr(current, part)
                except Exception:
                    found = False
                    break

        if found and current is not None:
            return current

    return default


def mapping_get_any(data: Mapping[str, Any], keys: Sequence[str], default: Any = None) -> Any:
    for key in keys:
        if key in data and data.get(key) is not None:
            return data.get(key)

    return default


def exception_to_issue(
    exc: BaseException,
    *,
    code: str,
    scope: Optional[str] = None,
    path: Optional[str] = None,
    vplib_uid: Optional[str] = None,
    family_id: Optional[str] = None,
    package_id: Optional[str] = None,
    operation: str = LibrarySyncOperation.NONE.value,
) -> LibrarySyncIssue:
    return LibrarySyncIssue(
        severity=LibrarySyncIssueSeverity.ERROR.value,
        code=code,
        message=str(exc),
        scope=scope,
        path=path,
        vplib_uid=vplib_uid,
        family_id=family_id,
        package_id=package_id,
        operation=operation,
        metadata={
            "exception_type": exc.__class__.__name__,
            "traceback": traceback_module.format_exc(),
        },
    )


# ---------------------------------------------------------------------------
# Safe imports
# ---------------------------------------------------------------------------


def safe_import_module(
    module_path: str,
    *,
    required: bool = False,
    force_reload: bool = False,
) -> Optional[ModuleType]:
    """Importiert ein Modul robust und cached Modul oder Fehler."""

    normalized_path = str(module_path or "").strip()

    if not normalized_path:
        if required:
            raise LibraryDbSyncImportError("Empty import path.")
        return None

    with _CACHE_LOCK:
        if not force_reload and normalized_path in _IMPORT_CACHE:
            return _IMPORT_CACHE[normalized_path]

    try:
        with _CACHE_LOCK:
            if force_reload and normalized_path in _IMPORT_CACHE:
                module = importlib.reload(_IMPORT_CACHE[normalized_path])
            else:
                module = importlib.import_module(normalized_path)

            _IMPORT_CACHE[normalized_path] = module
            _IMPORT_ERROR_CACHE.pop(normalized_path, None)
            return module

    except Exception as exc:
        payload = {
            "module_path": normalized_path,
            "error_type": exc.__class__.__name__,
            "error": str(exc),
            "traceback": traceback_module.format_exc(),
        }

        with _CACHE_LOCK:
            _IMPORT_CACHE.pop(normalized_path, None)
            _IMPORT_ERROR_CACHE[normalized_path] = payload

        if required:
            raise LibraryDbSyncImportError(
                f"Unable to import {normalized_path}: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc

        return None


def clear_library_db_sync_import_cache() -> Dict[str, Any]:
    """Leert nur Import-Caches dieses Moduls."""

    with _CACHE_LOCK:
        modules = sorted(_IMPORT_CACHE.keys())
        errors = sorted(_IMPORT_ERROR_CACHE.keys())
        _IMPORT_CACHE.clear()
        _IMPORT_ERROR_CACHE.clear()

    return {
        "ok": True,
        "cleared_modules": modules,
        "cleared_import_errors": errors,
    }


# ---------------------------------------------------------------------------
# Document / filesystem extraction helpers
# ---------------------------------------------------------------------------


def normalize_document_path(value: Any) -> Optional[str]:
    """Normalisiert Dokumentpfade für interne Mapping-Keys."""

    text = normalize_string(value)

    if not text:
        return None

    normalized = text.replace("\\", "/").lstrip("./")

    while "//" in normalized:
        normalized = normalized.replace("//", "/")

    return normalized or None


def unwrap_document_payload(value: Any) -> Any:
    """
    Entpackt häufige Dokument-Wrapper.

    Unterstützte Formen:
        {"relative_path": "...", "payload": {...}}
        {"path": "...", "document": {...}}
        {"content": {...}}
        {"data": {...}}

    Wenn kein Wrapper erkannt wird, wird der Wert selbst als Payload verwendet.
    """

    if value is None:
        return {}

    if is_dataclass(value):
        value = dataclass_shallow_dict(value)

    if not isinstance(value, Mapping):
        data = to_mapping(value)
        if data:
            value = data
        else:
            return value

    mapping = dict(value)

    # Typischer Row-/Wrapper-Fall mit Pfad + Payload.
    has_path_hint = any(key in mapping for key in DOCUMENT_PATH_KEYS)

    for wrapper_key in DOCUMENT_WRAPPER_KEYS:
        if wrapper_key not in mapping:
            continue

        payload = mapping.get(wrapper_key)

        if isinstance(payload, Mapping):
            if has_path_hint:
                return dict(payload)

            non_wrapper_keys = {
                key
                for key in mapping.keys()
                if key not in DOCUMENT_WRAPPER_KEYS
                and key not in DOCUMENT_PATH_KEYS
                and key not in {"metadata", "meta", "checksum", "type", "document_type", "module"}
            }

            if not non_wrapper_keys:
                return dict(payload)

        if isinstance(payload, (list, tuple)):
            if has_path_hint:
                return list(payload)

    return mapping


def document_mapping_from_value(value: Any) -> Dict[str, Any]:
    """
    Baut ein Dokumentmapping aus Mapping/List/Row-Strukturen.

    Rückgabe:
        {
            "vplib.manifest.json": {...},
            "family/identity.json": {...},
            ...
        }
    """

    if value is None:
        return {}

    if is_dataclass(value):
        value = dataclass_shallow_dict(value)

    if isinstance(value, (list, tuple, set)):
        result: Dict[str, Any] = {}

        for item in value:
            item_data = to_mapping(item)
            path = normalize_document_path(first_non_empty(*(item_data.get(key) for key in DOCUMENT_PATH_KEYS)))

            if not path:
                continue

            result[path] = unwrap_document_payload(item_data)

        return result

    if not isinstance(value, Mapping):
        data = to_mapping(value)

        if not data:
            return {}

        value = data

    mapping = dict(value)

    # Einzelner Dokument-Row statt Mapping von Dokumenten.
    single_path = normalize_document_path(first_non_empty(*(mapping.get(key) for key in DOCUMENT_PATH_KEYS)))

    if single_path and any(key in mapping for key in DOCUMENT_WRAPPER_KEYS):
        return {
            single_path: unwrap_document_payload(mapping),
        }

    result = {}

    for raw_key, raw_value in mapping.items():
        normalized_key = normalize_document_path(raw_key)

        if not normalized_key:
            continue

        raw_value_data = to_mapping(raw_value)

        internal_path = normalize_document_path(
            first_non_empty(*(raw_value_data.get(key) for key in DOCUMENT_PATH_KEYS))
        )

        key = internal_path or normalized_key
        result[key] = unwrap_document_payload(raw_value)

    return result


def get_candidate_path_candidates(value: Any) -> List[Path]:
    """
    Ermittelt mögliche Package-Pfade aus Candidate/Summary/ReadResult.

    Diese Funktion verwendet bewusst nicht `extract_documents_from_any`, damit
    keine Rekursion entsteht.
    """

    data = to_mapping(value)
    summary = extract_summary_payload(value)

    read_result = first_non_empty(
        data.get("read_result"),
        data.get("read"),
        data.get("package_read_result"),
    )
    read_data = to_mapping(read_result)

    raw_values = [
        data.get("package_root"),
        data.get("source_path"),
        data.get("root"),
        data.get("path"),
        data.get("relative_package_root"),
        data.get("relative_path"),
        summary.get("package_root"),
        summary.get("source_path"),
        summary.get("root"),
        summary.get("path"),
        summary.get("relative_package_root"),
        summary.get("relative_path"),
        read_data.get("package_root"),
        read_data.get("source_path"),
        read_data.get("root"),
        read_data.get("path"),
        read_data.get("relative_package_root"),
        read_data.get("relative_path"),
    ]

    result: List[Path] = []

    for raw in raw_values:
        text = normalize_string(raw)

        if not text:
            continue

        path = Path(text)

        if not path.is_absolute():
            path = Path.cwd() / path

        candidates = [path]

        if path.suffix:
            candidates.append(path.parent)

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate

            if resolved not in result:
                result.append(resolved)

    return result


def find_existing_package_root(value: Any) -> Optional[Path]:
    """Findet einen existierenden Package-Root-Pfad."""

    for candidate in get_candidate_path_candidates(value):
        try:
            if candidate.is_file():
                candidate = candidate.parent

            if not candidate.exists() or not candidate.is_dir():
                continue

            if (candidate / "vplib.manifest.json").is_file():
                return candidate

            if (candidate / "manifest.json").is_file():
                return candidate

        except Exception:
            continue

    return None


def read_json_file(path: Path) -> Dict[str, Any]:
    """Liest JSON-Datei defensiv als Dict."""

    try:
        if not path.is_file():
            return {}

        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, Mapping):
            return dict(data)

        return {"value": data}

    except Exception:
        return {}


def load_documents_from_package_root(
    package_root: Path,
    *,
    limit: int = DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD,
) -> Dict[str, Any]:
    """
    Lädt JSON-Dokumente direkt aus einem Package-Root.

    Es werden nur JSON-Dateien unterhalb des Package-Roots geladen.
    Pfade werden relativ zum Package-Root gespeichert.
    """

    result: Dict[str, Any] = {}

    try:
        root = package_root.resolve()
    except Exception:
        root = package_root

    if not root.exists() or not root.is_dir():
        return result

    preferred_files = [
        "vplib.manifest.json",
        "manifest.json",
        "family/identity.json",
        "family/classification.json",
        "editor/inventory.json",
        "variants/index.json",
        "variants/default.json",
    ]

    for relative_name in preferred_files:
        if len(result) >= limit:
            break

        path = root / relative_name
        payload = read_json_file(path)

        if payload:
            result[normalize_document_path(relative_name) or relative_name] = payload

    if len(result) >= limit:
        return result

    try:
        json_files = sorted(root.rglob("*.json"))
    except Exception:
        json_files = []

    for path in json_files:
        if len(result) >= limit:
            break

        try:
            relative_path = normalize_document_path(path.relative_to(root))
        except Exception:
            relative_path = normalize_document_path(path.name)

        if not relative_path or relative_path in result:
            continue

        payload = read_json_file(path)

        if payload:
            result[relative_path] = payload

    return result


def augment_documents_from_filesystem(
    value: Any,
    documents: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Ergänzt Dokumente aus dem Dateisystem, falls der Scanner keine oder nur
    unvollständige Dokumente geliefert hat.
    """

    current = document_mapping_from_value(documents or {})

    has_manifest = bool(get_document(current, *MANIFEST_DOCUMENT_KEYS))
    package_root = find_existing_package_root(value)

    if package_root is None:
        return current

    filesystem_documents = load_documents_from_package_root(package_root)

    if not filesystem_documents:
        return current

    # Bestehende Scanner-Dokumente haben Vorrang. Dateisystem-Fallback ergänzt.
    merged = dict(filesystem_documents)
    merged.update(current)

    if not has_manifest:
        manifest = get_document(filesystem_documents, *MANIFEST_DOCUMENT_KEYS)
        if manifest:
            merged["vplib.manifest.json"] = manifest

    return merged


def extract_documents_from_any(value: Any) -> Dict[str, Any]:
    """
    Extrahiert Package-Dokumente aus verschiedenen möglichen Pipeline-Formen.

    Unterstützte Quellen:
        - value["documents"]
        - value["raw_documents"]
        - value["document_mapping"]
        - value["loaded_documents"]
        - value["read_result"]["documents"]
        - value["read_result"]["loaded_documents"]
        - value.documents
        - value.read_result.documents
        - fallback: <package_root>/**/*.json
    """

    data = to_mapping(value)

    direct = first_non_empty(
        data.get("documents"),
        data.get("raw_documents"),
        data.get("document_mapping"),
        data.get("loaded_documents"),
    )

    direct_documents = document_mapping_from_value(direct)

    if direct_documents:
        return augment_documents_from_filesystem(value, direct_documents)

    read_result = first_non_empty(
        data.get("read_result"),
        data.get("read"),
        data.get("package_read_result"),
    )

    read_data = to_mapping(read_result)

    nested = first_non_empty(
        read_data.get("documents"),
        read_data.get("raw_documents"),
        read_data.get("loaded_documents"),
        read_data.get("document_mapping"),
    )

    nested_documents = document_mapping_from_value(nested)

    if nested_documents:
        return augment_documents_from_filesystem(value, nested_documents)

    item = first_non_empty(data.get("item"), data.get("summary"), data.get("library_item"))
    item_data = to_mapping(item)

    item_documents = first_non_empty(
        item_data.get("documents"),
        item_data.get("raw_documents"),
        item_data.get("document_mapping"),
        item_data.get("loaded_documents"),
    )

    item_document_mapping = document_mapping_from_value(item_documents)

    if item_document_mapping:
        return augment_documents_from_filesystem(value, item_document_mapping)

    return augment_documents_from_filesystem(value, {})


def get_document(documents: Mapping[str, Any], *keys: str) -> Dict[str, Any]:
    """
    Liest ein Dokument aus einem Mapping.

    Unterstützt:
        - exakte Keys
        - normalisierte Pfade
        - Suffix-Matches wie ".../vplib.manifest.json"
        - Wrapper-Payloads
    """

    normalized_documents = document_mapping_from_value(documents)

    for key in keys:
        normalized_key = normalize_document_path(key)

        if not normalized_key:
            continue

        value = normalized_documents.get(normalized_key)

        if isinstance(value, Mapping):
            return dict(unwrap_document_payload(value))

    for key in keys:
        normalized_key = normalize_document_path(key)

        if not normalized_key:
            continue

        suffix = f"/{normalized_key}"

        for document_key, value in normalized_documents.items():
            candidate_key = normalize_document_path(document_key)

            if not candidate_key:
                continue

            if candidate_key == normalized_key or candidate_key.endswith(suffix):
                payload = unwrap_document_payload(value)
                if isinstance(payload, Mapping):
                    return dict(payload)

    return {}


def extract_manifest(documents: Mapping[str, Any]) -> Dict[str, Any]:
    return get_document(documents, *MANIFEST_DOCUMENT_KEYS)


def extract_identity(documents: Mapping[str, Any]) -> Dict[str, Any]:
    return get_document(documents, *IDENTITY_DOCUMENT_KEYS)


def extract_classification(documents: Mapping[str, Any]) -> Dict[str, Any]:
    return get_document(documents, *CLASSIFICATION_DOCUMENT_KEYS)


def extract_inventory(documents: Mapping[str, Any]) -> Dict[str, Any]:
    return get_document(documents, *INVENTORY_DOCUMENT_KEYS)


def extract_validation_payload(value: Any) -> Dict[str, Any]:
    data = to_mapping(value)

    validation = first_non_empty(
        data.get("validation"),
        data.get("validation_result"),
        data.get("validation_summary"),
    )

    validation_data = to_mapping(validation)

    if validation_data:
        return validation_data

    item = first_non_empty(data.get("item"), data.get("summary"), data.get("library_item"))
    item_data = to_mapping(item)

    return to_mapping(item_data.get("validation"))


def extract_fingerprint_payload(value: Any) -> Dict[str, Any]:
    data = to_mapping(value)

    fingerprint = first_non_empty(
        data.get("fingerprint"),
        data.get("fingerprint_result"),
        data.get("package_fingerprint"),
    )

    return to_mapping(fingerprint)


def extract_summary_payload(value: Any) -> Dict[str, Any]:
    data = to_mapping(value)

    summary = first_non_empty(
        data.get("summary"),
        data.get("item"),
        data.get("library_item"),
        data.get("block"),
    )

    summary_data = to_mapping(summary)

    if summary_data:
        return summary_data

    return data


def extract_source_path(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)
    package_root = find_existing_package_root(value)

    return normalize_string(
        first_non_empty(
            data.get("source_path"),
            data.get("relative_package_root"),
            data.get("relative_path"),
            summary.get("source_path"),
            summary.get("relative_package_root"),
            manifest.get("source_path"),
            str(package_root) if package_root else None,
        )
    )


def extract_package_root(value: Any) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    package_root = find_existing_package_root(value)

    return normalize_string(
        first_non_empty(
            data.get("package_root"),
            data.get("root"),
            data.get("path"),
            summary.get("package_root"),
            summary.get("root"),
            summary.get("path"),
            str(package_root) if package_root else None,
        )
    )


def extract_revision_hash(value: Any) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    fingerprint = extract_fingerprint_payload(value)

    return normalize_string(
        first_non_empty(
            data.get("revision_hash"),
            data.get("hash"),
            data.get("content_hash"),
            summary.get("revision_hash"),
            fingerprint.get("revision_hash"),
            fingerprint.get("hash"),
            fingerprint.get("content_hash"),
        )
    )


def extract_vplib_uid(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)
    identity = extract_identity(docs)

    return normalize_vplib_uid(
        first_non_empty(
            data.get("vplib_uid"),
            data.get("vplibUid"),
            data.get("vplib_uid_v1"),
            data.get("uid"),
            summary.get("vplib_uid"),
            summary.get("vplibUid"),
            summary.get("vplib_uid_v1"),
            summary.get("uid"),
            manifest.get("vplib_uid"),
            manifest.get("vplibUid"),
            manifest.get("vplib_uid_v1"),
            manifest.get("uid"),
            identity.get("vplib_uid"),
            identity.get("vplibUid"),
            identity.get("uid"),
        )
    )


def extract_family_id(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)
    identity = extract_identity(docs)

    return normalize_string(
        first_non_empty(
            data.get("family_id"),
            summary.get("family_id"),
            manifest.get("family_id"),
            identity.get("family_id"),
            identity.get("id"),
        )
    )


def extract_package_id(value: Any, documents: Optional[Mapping[str, Any]] = None) -> Optional[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    docs = documents or extract_documents_from_any(value)
    manifest = extract_manifest(docs)

    return normalize_string(
        first_non_empty(
            data.get("package_id"),
            summary.get("package_id"),
            manifest.get("package_id"),
            manifest.get("id"),
        )
    )


def extract_variant_ids(value: Any, documents: Optional[Mapping[str, Any]] = None) -> List[str]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)

    raw = first_non_empty(
        data.get("variant_ids"),
        summary.get("variant_ids"),
        summary.get("variants"),
    )

    if isinstance(raw, Mapping):
        variants = raw.get("items") or raw.get("variants") or raw.get("ids") or raw.keys()
    else:
        variants = raw or []

    result: List[str] = []

    for item in variants:
        if isinstance(item, Mapping):
            variant_id = first_non_empty(item.get("variant_id"), item.get("id"))
        else:
            variant_id = item

        text = normalize_string(variant_id)
        if text and text not in result:
            result.append(text)

    docs = documents or extract_documents_from_any(value)
    index_doc = get_document(docs, "variants/index.json")

    index_variants = first_non_empty(
        index_doc.get("variants"),
        index_doc.get("items"),
        index_doc.get("variant_ids"),
    )

    if isinstance(index_variants, Mapping):
        index_variants = index_variants.keys()

    for item in index_variants or []:
        if isinstance(item, Mapping):
            variant_id = first_non_empty(item.get("variant_id"), item.get("id"))
        else:
            variant_id = item

        text = normalize_string(variant_id)
        if text and text not in result:
            result.append(text)

    if not result:
        default_doc = get_document(docs, "variants/default.json")
        default_id = normalize_string(
            first_non_empty(
                default_doc.get("variant_id"),
                default_doc.get("id"),
                "default" if default_doc else None,
            )
        )
        if default_id:
            result.append(default_id)

    return result


def candidate_is_valid(value: Any) -> bool:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    validation = extract_validation_payload(value)

    explicit = first_non_empty(
        data.get("valid"),
        data.get("is_valid"),
        summary.get("valid"),
        summary.get("is_valid"),
        validation.get("valid"),
        validation.get("ok"),
    )

    if explicit is not None:
        return safe_bool(explicit, False)

    status = str(
        first_non_empty(
            data.get("status"),
            summary.get("status"),
            validation.get("status"),
            validation.get("validation_status"),
        )
        or ""
    ).strip().lower()

    if status in {"valid", "ok", "published", "active", "success"}:
        return True

    if status in {"invalid", "error", "fatal", "failed", "duplicate"}:
        return False

    error_count = safe_int(
        first_non_empty(
            data.get("error_count"),
            summary.get("error_count"),
            validation.get("error_count"),
            validation.get("errors_count"),
            validation.get("fatal_count"),
        ),
        0,
    )

    fatal_count = safe_int(validation.get("fatal_count"), 0)

    return error_count == 0 and fatal_count == 0


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------


def build_family_upsert_payload(value: Any) -> Dict[str, Any]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    documents = extract_documents_from_any(value)

    manifest = extract_manifest(documents)
    identity = extract_identity(documents)
    classification = extract_classification(documents)
    inventory = extract_inventory(documents)
    package_root = extract_package_root(value)

    uid = extract_vplib_uid(value, documents)
    family_id = extract_family_id(value, documents)
    package_id = extract_package_id(value, documents)

    family_slug = first_non_empty(
        data.get("family_slug"),
        data.get("slug"),
        summary.get("family_slug"),
        summary.get("slug"),
        manifest.get("family_slug"),
        manifest.get("slug"),
        identity.get("family_slug"),
        identity.get("slug"),
        Path(package_root).name if package_root else None,
    )

    label = first_non_empty(
        data.get("label"),
        data.get("family_name"),
        summary.get("label"),
        summary.get("family_name"),
        manifest.get("label"),
        manifest.get("family_name"),
        manifest.get("name"),
        inventory.get("label"),
        inventory.get("name"),
        identity.get("label"),
        identity.get("name"),
        family_slug,
        family_id,
    )

    manifest_classification = to_mapping(manifest.get("classification"))

    classification_payload = first_non_empty(
        summary.get("classification"),
        data.get("classification"),
        classification,
        manifest_classification,
        {},
    )

    classification_data = to_mapping(classification_payload)

    domain = first_non_empty(
        data.get("domain"),
        summary.get("domain"),
        classification_data.get("domain"),
        classification_data.get("domain_id"),
        manifest_classification.get("domain"),
    )

    category = first_non_empty(
        data.get("category"),
        summary.get("category"),
        classification_data.get("category"),
        classification_data.get("category_id"),
        manifest_classification.get("category"),
    )

    subcategory = first_non_empty(
        data.get("subcategory"),
        summary.get("subcategory"),
        classification_data.get("subcategory"),
        classification_data.get("subcategory_id"),
        manifest_classification.get("subcategory"),
    )

    variant_ids = extract_variant_ids(value, documents)
    default_variant_id = first_non_empty(
        summary.get("default_variant_id"),
        data.get("default_variant_id"),
        inventory.get("default_variant_id"),
        variant_ids[0] if variant_ids else None,
    )

    return {
        "vplib_uid": uid,
        "family_id": family_id,
        "package_id": package_id,
        "family_slug": family_slug,
        "slug": family_slug,
        "label": label,
        "name": label,
        "description": first_non_empty(
            data.get("description"),
            summary.get("description"),
            manifest.get("description"),
            inventory.get("description"),
            identity.get("description"),
        ),
        "object_kind": first_non_empty(
            data.get("object_kind"),
            summary.get("object_kind"),
            manifest.get("object_kind"),
            identity.get("object_kind"),
            inventory.get("object_kind"),
        ),
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "source_path": extract_source_path(value, documents),
        "package_root": package_root,
        "classification_path": first_non_empty(
            summary.get("classification_path"),
            data.get("classification_path"),
            classification_data.get("classification_path"),
            classification_data.get("path"),
            manifest_classification.get("path"),
        ),
        "enabled": safe_bool(
            first_non_empty(
                data.get("enabled"),
                summary.get("enabled"),
                manifest.get("enabled"),
                inventory.get("enabled"),
            ),
            True,
        ),
        "visible": safe_bool(
            first_non_empty(
                data.get("visible"),
                summary.get("visible"),
                manifest.get("visible"),
                inventory.get("visible"),
            ),
            True,
        ),
        "publication_status": "published",
        "status": "published",
        "default_variant_id": default_variant_id,
        "variant_count": len(variant_ids),
        "revision_hash": extract_revision_hash(value),
        "scanned_at": utcnow(),
        "published_at": utcnow(),
        "metadata": {
            "classification": classification_data or manifest_classification,
            "inventory": inventory,
            "manifest": manifest,
            "source": "library_db_sync_service",
        },
        "summary_payload": json_safe(
            {
                **summary,
                "vplib_uid": uid,
                "family_id": family_id,
                "package_id": package_id,
                "family_slug": family_slug,
                "label": label,
                "object_kind": first_non_empty(
                    data.get("object_kind"),
                    summary.get("object_kind"),
                    manifest.get("object_kind"),
                    identity.get("object_kind"),
                    inventory.get("object_kind"),
                ),
                "domain": domain,
                "category": category,
                "subcategory": subcategory,
            }
        ),
    }


def build_revision_upsert_payload(value: Any, *, scan_run_id: Any = None) -> Dict[str, Any]:
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    documents = extract_documents_from_any(value)
    manifest = extract_manifest(documents)
    validation = extract_validation_payload(value)

    revision_hash = extract_revision_hash(value)

    detail_payload = first_non_empty(
        data.get("detail"),
        data.get("detail_payload"),
        data.get("raw_detail"),
        {},
    )

    return {
        "vplib_uid": extract_vplib_uid(value, documents),
        "family_id": extract_family_id(value, documents),
        "package_id": extract_package_id(value, documents),
        "revision_hash": revision_hash,
        "package_version": first_non_empty(
            data.get("package_version"),
            summary.get("package_version"),
            manifest.get("package_version"),
            manifest.get("version"),
        ),
        "schema_version": first_non_empty(
            data.get("schema_version"),
            summary.get("schema_version"),
            manifest.get("schema_version"),
        ),
        "validation_status": first_non_empty(
            validation.get("status"),
            validation.get("validation_status"),
            "valid" if candidate_is_valid(value) else "invalid",
        ),
        "publication_status": "published",
        "scan_run_id": scan_run_id,
        "source_path": extract_source_path(value, documents),
        "created_at": utcnow(),
        "published_at": utcnow(),
        "summary_payload": json_safe(summary),
        "detail_payload": json_safe(detail_payload),
        "raw_documents": json_safe(documents),
        "documents": json_safe(documents),
        "validation_payload": json_safe(validation),
        "metadata": {
            "source": "library_db_sync_service",
            "document_count": len(documents),
            "manifest": manifest,
        },
    }


def extract_variant_payloads(value: Any) -> List[Dict[str, Any]]:
    documents = extract_documents_from_any(value)
    uid = extract_vplib_uid(value, documents)
    revision_hash = extract_revision_hash(value)

    variants: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Explizite Varianten aus Candidate/Summary.
    data = to_mapping(value)
    summary = extract_summary_payload(value)

    raw_variants = first_non_empty(
        data.get("variants"),
        summary.get("variants"),
    )

    if isinstance(raw_variants, Mapping):
        raw_variants = raw_variants.get("items") or raw_variants.get("variants") or raw_variants.values()

    for index, raw_variant in enumerate(raw_variants or []):
        variant_data = to_mapping(raw_variant)
        variant_id = normalize_string(first_non_empty(variant_data.get("variant_id"), variant_data.get("id")))

        if not variant_id or variant_id in seen:
            continue

        seen.add(variant_id)
        variants.append(
            {
                "vplib_uid": uid,
                "variant_id": variant_id,
                "label": first_non_empty(variant_data.get("label"), variant_data.get("name"), variant_id),
                "description": variant_data.get("description"),
                "is_default": safe_bool(variant_data.get("is_default"), index == 0),
                "enabled": safe_bool(variant_data.get("enabled"), True),
                "visible": safe_bool(variant_data.get("visible"), True),
                "sort_order": safe_int(variant_data.get("sort_order"), index),
                "revision_hash": revision_hash,
                "payload": json_safe(variant_data),
                "resolved_payload": json_safe(variant_data.get("resolved_payload") or variant_data.get("resolved") or {}),
                "metadata": {},
            }
        )

    # 2. Varianten aus variants/*.json.
    index_doc = get_document(documents, "variants/index.json")
    default_doc = get_document(documents, "variants/default.json")

    default_variant_id = normalize_string(
        first_non_empty(
            index_doc.get("default_variant_id"),
            default_doc.get("variant_id"),
            default_doc.get("id"),
            "default" if default_doc else None,
        )
    )

    for path, document in documents.items():
        normalized_path = str(path).replace("\\", "/")

        if not normalized_path.startswith("variants/") or not normalized_path.endswith(".json"):
            continue

        if normalized_path == "variants/index.json":
            continue

        document_data = to_mapping(document)
        variant_id = normalize_string(
            first_non_empty(
                document_data.get("variant_id"),
                document_data.get("id"),
                normalized_path.removeprefix("variants/").removesuffix(".json"),
            )
        )

        if not variant_id or variant_id in seen:
            continue

        seen.add(variant_id)
        variants.append(
            {
                "vplib_uid": uid,
                "variant_id": variant_id,
                "label": first_non_empty(document_data.get("label"), document_data.get("name"), variant_id),
                "description": document_data.get("description"),
                "is_default": variant_id == default_variant_id or normalized_path == "variants/default.json",
                "enabled": safe_bool(document_data.get("enabled"), True),
                "visible": safe_bool(document_data.get("visible"), True),
                "sort_order": len(variants),
                "revision_hash": revision_hash,
                "payload": json_safe(document_data),
                "resolved_payload": json_safe(document_data.get("resolved_payload") or {}),
                "metadata": {
                    "document_path": normalized_path,
                },
            }
        )

    # 3. Falls nur variant_ids bekannt sind.
    for variant_id in extract_variant_ids(value, documents):
        if variant_id in seen:
            continue

        seen.add(variant_id)
        variants.append(
            {
                "vplib_uid": uid,
                "variant_id": variant_id,
                "label": variant_id,
                "description": None,
                "is_default": variant_id == default_variant_id or not variants,
                "enabled": True,
                "visible": True,
                "sort_order": len(variants),
                "revision_hash": revision_hash,
                "payload": {},
                "resolved_payload": {},
                "metadata": {
                    "source": "variant_ids",
                },
            }
        )

    return variants


def extract_asset_payloads(value: Any) -> List[Dict[str, Any]]:
    documents = extract_documents_from_any(value)
    data = to_mapping(value)
    summary = extract_summary_payload(value)
    uid = extract_vplib_uid(value, documents)
    revision_hash = extract_revision_hash(value)

    raw_assets = first_non_empty(
        data.get("assets"),
        summary.get("assets"),
        data.get("asset_refs"),
        summary.get("asset_refs"),
        {},
    )

    assets: List[Dict[str, Any]] = []

    if isinstance(raw_assets, Mapping):
        for role, asset_value in raw_assets.items():
            if asset_value is None:
                continue

            if isinstance(asset_value, Mapping):
                asset_data = dict(asset_value)
            else:
                asset_data = {
                    "path": asset_value,
                }

            assets.append(
                {
                    "vplib_uid": uid,
                    "role": asset_data.get("role") or role,
                    "asset_type": asset_data.get("asset_type") or asset_data.get("type"),
                    "path": first_non_empty(asset_data.get("path"), asset_data.get("relative_path"), asset_data.get("uri")),
                    "relative_path": asset_data.get("relative_path") or asset_data.get("path"),
                    "uri": asset_data.get("uri") or asset_data.get("url"),
                    "label": asset_data.get("label") or role,
                    "mime_type": asset_data.get("mime_type"),
                    "checksum": asset_data.get("checksum") or asset_data.get("sha256"),
                    "size_bytes": asset_data.get("size_bytes"),
                    "revision_hash": revision_hash,
                    "payload": json_safe(asset_data),
                    "metadata": {},
                }
            )

    elif isinstance(raw_assets, list):
        for asset_value in raw_assets:
            asset_data = to_mapping(asset_value)

            assets.append(
                {
                    "vplib_uid": uid,
                    "role": asset_data.get("role"),
                    "asset_type": asset_data.get("asset_type") or asset_data.get("type"),
                    "path": first_non_empty(asset_data.get("path"), asset_data.get("relative_path"), asset_data.get("uri")),
                    "relative_path": asset_data.get("relative_path") or asset_data.get("path"),
                    "uri": asset_data.get("uri") or asset_data.get("url"),
                    "label": asset_data.get("label") or asset_data.get("name"),
                    "mime_type": asset_data.get("mime_type"),
                    "checksum": asset_data.get("checksum") or asset_data.get("sha256"),
                    "size_bytes": asset_data.get("size_bytes"),
                    "revision_hash": revision_hash,
                    "payload": json_safe(asset_data),
                    "metadata": {},
                }
            )

    return assets


def extract_document_payloads(value: Any) -> List[Dict[str, Any]]:
    documents = extract_documents_from_any(value)
    uid = extract_vplib_uid(value, documents)
    revision_hash = extract_revision_hash(value)

    payloads: List[Dict[str, Any]] = []

    for path, document in documents.items():
        relative_path = str(path).replace("\\", "/").strip()

        if not relative_path:
            continue

        module = relative_path.split("/", 1)[0] if "/" in relative_path else "root"

        payloads.append(
            {
                "vplib_uid": uid,
                "relative_path": relative_path,
                "document_type": "json" if relative_path.endswith(".json") else None,
                "module": module,
                "revision_hash": revision_hash,
                "payload": json_safe(document),
                "metadata": {},
            }
        )

    return payloads


def extract_issue_payloads(value: Any) -> List[Dict[str, Any]]:
    data = to_mapping(value)
    validation = extract_validation_payload(value)
    documents = extract_documents_from_any(value)

    uid = extract_vplib_uid(value, documents)
    family_id = extract_family_id(value, documents)
    package_id = extract_package_id(value, documents)
    revision_hash = extract_revision_hash(value)

    raw_issues = first_non_empty(
        data.get("issues"),
        data.get("messages"),
        validation.get("issues"),
        validation.get("messages"),
        validation.get("errors"),
        [],
    )

    if isinstance(raw_issues, Mapping):
        raw_issues = raw_issues.values()

    issues: List[Dict[str, Any]] = []

    for raw_issue in raw_issues or []:
        issue_data = to_mapping(raw_issue)

        if not issue_data:
            issue_data = {
                "message": str(raw_issue),
            }

        severity = first_non_empty(
            issue_data.get("severity"),
            issue_data.get("level"),
            "error" if issue_data.get("error") else "warning",
        )

        issues.append(
            {
                "vplib_uid": uid,
                "family_id": family_id,
                "package_id": package_id,
                "revision_hash": revision_hash,
                "severity": severity,
                "code": issue_data.get("code"),
                "message": first_non_empty(issue_data.get("message"), issue_data.get("error"), str(raw_issue)),
                "path": issue_data.get("path"),
                "field": issue_data.get("field"),
                "scope": issue_data.get("scope"),
                "source_path": extract_source_path(value, documents),
                "payload": json_safe(issue_data),
                "metadata": {},
            }
        )

    return issues


def extract_pipeline_candidates(scan_result: Any) -> List[Any]:
    """
    Extrahiert Sync-Kandidaten ohne das gesamte PipelineResult tief zu kopieren.

    Der frühere Weg über `to_mapping(scan_result)` konnte bei
    LibraryScanPipelineResult rekursiv große Read-/Validation-/Index-Payloads
    serialisieren und dadurch den DB-Sync stark verlangsamen.
    """

    if scan_result is None:
        return []

    if isinstance(scan_result, (list, tuple)):
        return list(scan_result)

    for key in (
        "pipeline_entries",
        "entries",
        "candidates",
        "items",
        "valid_items",
        "blocks",
        "results",
    ):
        value = get_direct_value(scan_result, key)

        if isinstance(value, (list, tuple)):
            return list(value)

    combined: List[Any] = []

    for key in ("valid_items", "invalid_items", "skipped_items"):
        value = get_direct_value(scan_result, key)
        if isinstance(value, (list, tuple)):
            combined.extend(value)

    if combined:
        return combined

    for key in ("scan_result", "result", "library_scan_result"):
        nested = get_direct_value(scan_result, key)
        if nested is not None and nested is not scan_result:
            nested_candidates = extract_pipeline_candidates(nested)
            if nested_candidates:
                return nested_candidates

    data = to_mapping(scan_result)

    for key in (
        "pipeline_entries",
        "entries",
        "candidates",
        "items",
        "valid_items",
        "blocks",
        "results",
    ):
        value = data.get(key)
        if isinstance(value, (list, tuple)):
            return list(value)

    return []


# ---------------------------------------------------------------------------
# Service implementation
# ---------------------------------------------------------------------------


class LibraryDbSyncService:
    """Orchestriert ScanResult/PipelineResult → creative_library DB."""

    def __init__(
        self,
        *,
        repository: Any = None,
        repository_factory: Any = None,
        scan_service: Any = None,
        config: Optional[LibraryDbSyncServiceConfig] = None,
    ) -> None:
        if config is None:
            config = LibraryDbSyncServiceConfig(
                repository=repository,
                repository_factory=repository_factory,
                scan_service=scan_service,
                enabled=env_bool(ENV_SYNC_ENABLED, DEFAULT_SYNC_ENABLED),
                strict=env_bool(ENV_SYNC_STRICT, DEFAULT_SYNC_STRICT),
                autocommit=env_bool(ENV_SYNC_AUTOCOMMIT, DEFAULT_SYNC_AUTOCOMMIT),
                mark_missing_deleted=env_bool(
                    ENV_SYNC_MARK_MISSING_DELETED,
                    DEFAULT_SYNC_MARK_MISSING_DELETED,
                ),
                continue_on_candidate_error=env_bool(
                    ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR,
                    DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR,
                ),
                include_raw_documents=env_bool(
                    ENV_SYNC_INCLUDE_RAW_DOCUMENTS,
                    DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS,
                ),
            )

        self.config = config
        self._repository = repository if repository is not None else config.repository
        self._repository_factory = (
            repository_factory
            if repository_factory is not None
            else config.repository_factory
        )
        self._scan_service = scan_service if scan_service is not None else config.scan_service

    # ------------------------------------------------------------------
    # Dependency loading
    # ------------------------------------------------------------------

    def get_repository(self) -> Any:
        """Liefert das Repository für creative_library DB-Zugriffe."""

        if self._repository is not None:
            return self._repository

        if callable(self._repository_factory):
            self._repository = self._repository_factory()
            return self._repository

        module = safe_import_module(self.config.repository_import_path, required=True)

        factory = getattr(module, "get_creative_library_repository", None)
        if callable(factory):
            self._repository = factory()
            return self._repository

        factory = getattr(module, "get_default_creative_library_repository", None)
        if callable(factory):
            self._repository = factory()
            return self._repository

        factory = getattr(module, "create_creative_library_repository", None)
        if callable(factory):
            self._repository = factory()
            return self._repository

        raise LibraryDbSyncImportError(
            "No repository factory found. Expected one of: "
            "get_creative_library_repository, "
            "get_default_creative_library_repository, "
            "create_creative_library_repository."
        )

    def get_scan_service(self) -> Any:
        """Liefert das dateibasierte Library-Scan-Service-Modul oder Objekt."""

        if self._scan_service is not None:
            return self._scan_service

        module = safe_import_module(self.config.scan_service_import_path, required=True)
        self._scan_service = module
        return module

    # ------------------------------------------------------------------
    # Public sync entrypoints
    # ------------------------------------------------------------------

    def sync_library_source(
        self,
        *,
        source_root: Optional[str] = None,
        force_refresh: bool = True,
        triggered_by: Optional[str] = None,
        publish_valid_only: Optional[bool] = None,
        mark_missing_deleted: Optional[bool] = None,
        include_raw_documents: Optional[bool] = None,
        scan_options: Optional[Mapping[str, Any]] = None,
    ) -> LibrarySyncResult:
        """
        Führt einen dateibasierten Scan aus und synchronisiert das Ergebnis in DB.

        Diese Methode ist der fachliche Hauptentrypoint für:

            POST /api/v1/vplib/library/sync
        """

        self._assert_enabled()

        started_ms = monotonic_ms()

        run_info = LibrarySyncRunInfo(
            mode=DEFAULT_SYNC_MODE,
            source=DEFAULT_SYNC_SOURCE,
            target=DEFAULT_SYNC_TARGET,
            source_root=source_root,
            triggered_by=triggered_by,
            force_refresh=force_refresh,
            publish_valid_only=self.config.publish_valid_only
            if publish_valid_only is None
            else bool(publish_valid_only),
            mark_missing_deleted=self.config.mark_missing_deleted
            if mark_missing_deleted is None
            else bool(mark_missing_deleted),
            started_at=utcnow(),
            metadata={
                "scan_options": dict(scan_options or {}),
            },
        )

        repository = self.get_repository()
        scan_run = None

        try:
            scan_run = self._create_scan_run(repository, run_info)
            run_info.scan_run_id = self._get_object_id(scan_run)

            scan_result = self._run_scan(
                source_root=source_root,
                force_refresh=force_refresh,
                include_raw_documents=self.config.include_raw_documents
                if include_raw_documents is None
                else bool(include_raw_documents),
                scan_options=scan_options or {},
            )

            result = self.sync_scan_result_to_db(
                scan_result,
                scan_run=scan_run,
                run_info=run_info,
                publish_valid_only=publish_valid_only,
                mark_missing_deleted=mark_missing_deleted,
                repository=repository,
            )

            result.run.duration_ms = duration_ms(started_ms)
            result.finish()

            self._finish_scan_run(repository, scan_run, result)

            if self.config.autocommit:
                self._commit(repository)

            return result

        except Exception as exc:
            self._rollback(repository)

            if scan_run is not None:
                try:
                    self._fail_scan_run(repository, scan_run, exc)
                    if self.config.autocommit:
                        self._commit(repository)
                except Exception:
                    self._rollback(repository)

            return build_error_sync_result(
                exc,
                message="Library DB sync failed.",
                run=run_info,
                include_traceback=True,
            )

    def sync_scan_result_to_db(
        self,
        scan_result: Any,
        *,
        scan_run: Any = None,
        run_info: Optional[LibrarySyncRunInfo] = None,
        publish_valid_only: Optional[bool] = None,
        mark_missing_deleted: Optional[bool] = None,
        repository: Any = None,
    ) -> LibrarySyncResult:
        """
        Synchronisiert ein vorhandenes Scan-/Pipeline-Ergebnis in die Datenbank.

        Diese Methode schreibt selbst keinen Scan neu an. Sie verarbeitet das
        übergebene Ergebnis und ist damit gut testbar.
        """

        self._assert_enabled()

        repository = repository or self.get_repository()

        run_info = run_info or LibrarySyncRunInfo(
            mode=DEFAULT_SYNC_MODE,
            source=DEFAULT_SYNC_SOURCE,
            target=DEFAULT_SYNC_TARGET,
            started_at=utcnow(),
        )

        if scan_run is not None:
            run_info.scan_run_id = run_info.scan_run_id or self._get_object_id(scan_run)

        candidates = extract_pipeline_candidates(scan_result)

        if not candidates:
            return build_empty_sync_result(
                message="No scan candidates found for DB sync.",
                run=run_info,
            ).finish()

        result = LibrarySyncResult(
            ok=False,
            status=LibrarySyncStatus.RUNNING.value,
            message="Library DB sync running.",
            run=run_info,
            stats=LibrarySyncStats(total_count=0),
            candidates=[],
            metadata={
                "candidate_count": len(candidates),
            },
        )

        active_vplib_uids: List[str] = []

        publish_valid_only_effective = (
            self.config.publish_valid_only
            if publish_valid_only is None
            else bool(publish_valid_only)
        )

        for raw_candidate in candidates:
            try:
                candidate_result = self.sync_candidate_to_db(
                    raw_candidate,
                    scan_run=scan_run,
                    repository=repository,
                    publish_valid_only=publish_valid_only_effective,
                )

                if candidate_result.vplib_uid:
                    active_vplib_uids.append(candidate_result.vplib_uid)

                result.add_candidate(candidate_result)

            except Exception as exc:
                issue = exception_to_issue(
                    exc,
                    code="sync.candidate_failed",
                    scope="candidate",
                    operation=LibrarySyncOperation.UPSERT_FAMILY.value,
                )

                failed_candidate = LibrarySyncCandidateResult(
                    status=LibrarySyncCandidateStatus.ERROR.value,
                    valid=False,
                    issues=[issue],
                    error_count=1,
                    issue_count=1,
                    metadata={
                        "raw_candidate_type": raw_candidate.__class__.__name__,
                    },
                )

                result.add_candidate(failed_candidate)
                result.add_issue(issue)

                if not self.config.continue_on_candidate_error:
                    raise LibraryDbSyncCandidateError(str(exc)) from exc

        mark_missing_deleted_effective = (
            self.config.mark_missing_deleted
            if mark_missing_deleted is None
            else bool(mark_missing_deleted)
        )

        if mark_missing_deleted_effective:
            deleted_count = self._mark_missing_deleted(repository, active_vplib_uids)
            result.stats.marked_missing_deleted_count = deleted_count
            if deleted_count:
                result.add_issue(
                    LibrarySyncIssue(
                        severity=LibrarySyncIssueSeverity.INFO.value,
                        code="sync.missing_marked_deleted",
                        message=f"Marked {deleted_count} missing families as deleted.",
                        operation=LibrarySyncOperation.MARK_MISSING_DELETED.value,
                    )
                )

        result.finish(message="Library DB sync finished.")
        return result

    def sync_candidate_to_db(
        self,
        candidate: Any,
        *,
        scan_run: Any = None,
        repository: Any = None,
        publish_valid_only: bool = True,
    ) -> LibrarySyncCandidateResult:
        """
        Synchronisiert einen einzelnen Kandidaten in die DB.

        Ablauf:
            1. IDs und Validität extrahieren
            2. invalid Kandidaten nur als Issues speichern
            3. Family upserten
            4. Revision anhand revision_hash erzeugen oder überspringen
            5. Varianten/Assets/Dokumente bei neuer Revision ersetzen
            6. Issues speichern
        """

        started_ms = monotonic_ms()
        repository = repository or self.get_repository()

        documents = extract_documents_from_any(candidate)
        uid = extract_vplib_uid(candidate, documents)
        family_id = extract_family_id(candidate, documents)
        package_id = extract_package_id(candidate, documents)
        revision_hash = extract_revision_hash(candidate)
        source_path = extract_source_path(candidate, documents)
        package_root = extract_package_root(candidate)
        is_valid = candidate_is_valid(candidate)

        family_payload = build_family_upsert_payload(candidate)

        candidate_result = LibrarySyncCandidateResult(
            status=LibrarySyncCandidateStatus.SCANNED.value,
            vplib_uid=uid,
            family_id=family_id,
            package_id=package_id,
            family_slug=family_payload.get("family_slug"),
            label=family_payload.get("label"),
            object_kind=family_payload.get("object_kind"),
            domain=family_payload.get("domain"),
            category=family_payload.get("category"),
            subcategory=family_payload.get("subcategory"),
            source_path=source_path,
            package_root=package_root,
            revision_hash=revision_hash,
            valid=is_valid,
            validation_status="valid" if is_valid else "invalid",
            started_at=utcnow(),
            scan_run_id=self._get_object_id(scan_run),
            metadata={
                "document_count": len(documents),
                "manifest_loaded": bool(extract_manifest(documents)),
            },
        )

        issue_payloads = extract_issue_payloads(candidate)

        if not uid:
            issue = LibrarySyncIssue(
                severity=LibrarySyncIssueSeverity.ERROR.value,
                code="sync.missing_vplib_uid",
                message="Candidate has no vplib_uid. It cannot be synchronized.",
                scope="candidate",
                source_path=source_path,
                family_id=family_id,
                package_id=package_id,
                revision_hash=revision_hash,
                metadata={
                    "document_count": len(documents),
                    "manifest_loaded": bool(extract_manifest(documents)),
                    "package_root": package_root,
                },
            )
            candidate_result.add_issue(issue)
            self._save_issue(repository, issue, scan_run=scan_run)
            candidate_result.status = LibrarySyncCandidateStatus.INVALID.value
            candidate_result.finished_at = utcnow()
            candidate_result.duration_ms = duration_ms(started_ms)
            return candidate_result

        if not revision_hash and is_valid:
            issue = LibrarySyncIssue(
                severity=LibrarySyncIssueSeverity.ERROR.value,
                code="sync.missing_revision_hash",
                message="Candidate has no revision_hash. It cannot be published.",
                scope="candidate",
                source_path=source_path,
                vplib_uid=uid,
                family_id=family_id,
                package_id=package_id,
            )
            candidate_result.add_issue(issue)
            self._save_issue(repository, issue, scan_run=scan_run)
            candidate_result.status = LibrarySyncCandidateStatus.INVALID.value
            candidate_result.finished_at = utcnow()
            candidate_result.duration_ms = duration_ms(started_ms)
            return candidate_result

        if not is_valid and publish_valid_only:
            for issue_payload in issue_payloads:
                issue = LibrarySyncIssue.from_mapping(issue_payload)
                candidate_result.add_issue(issue)
                self._save_issue(repository, issue, scan_run=scan_run)

            if not issue_payloads:
                issue = LibrarySyncIssue(
                    severity=LibrarySyncIssueSeverity.WARNING.value,
                    code="sync.invalid_skipped",
                    message="Candidate is invalid and was skipped.",
                    scope="candidate",
                    source_path=source_path,
                    vplib_uid=uid,
                    family_id=family_id,
                    package_id=package_id,
                    revision_hash=revision_hash,
                )
                candidate_result.add_issue(issue)
                self._save_issue(repository, issue, scan_run=scan_run)

            candidate_result.status = LibrarySyncCandidateStatus.SKIPPED.value
            candidate_result.skipped = True
            candidate_result.finished_at = utcnow()
            candidate_result.duration_ms = duration_ms(started_ms)
            return candidate_result

        # Family upsert.
        existing_family = self._get_family_by_uid(repository, uid)

        family = self._upsert_family(repository, family_payload)
        family_db_id = self._get_object_id(family)

        candidate_result.family_db_id = family_db_id
        candidate_result.family_created = existing_family is None
        candidate_result.family_updated = existing_family is not None
        candidate_result.label = family_payload.get("label")
        candidate_result.family_slug = family_payload.get("family_slug")
        candidate_result.object_kind = family_payload.get("object_kind")
        candidate_result.domain = family_payload.get("domain")
        candidate_result.category = family_payload.get("category")
        candidate_result.subcategory = family_payload.get("subcategory")

        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.UPSERT_FAMILY.value,
                status=LibrarySyncCandidateStatus.INSERTED.value
                if candidate_result.family_created
                else LibrarySyncCandidateStatus.UPDATED.value,
                affected_count=1,
                created_count=1 if candidate_result.family_created else 0,
                updated_count=1 if candidate_result.family_updated else 0,
            )
        )

        previous_revision_hash = self._get_latest_revision_hash(repository, uid)
        candidate_result.previous_revision_hash = previous_revision_hash

        revision_payload = build_revision_upsert_payload(
            candidate,
            scan_run_id=self._get_object_id(scan_run),
        )

        revision, revision_created = self._upsert_revision_if_changed(
            repository,
            family,
            revision_payload,
            scan_run=scan_run,
        )

        candidate_result.revision_db_id = self._get_object_id(revision)
        candidate_result.revision_created = bool(revision_created)

        candidate_result.add_operation(
            LibrarySyncOperationResult(
                operation=LibrarySyncOperation.CREATE_REVISION.value
                if revision_created
                else LibrarySyncOperation.SKIP_REVISION.value,
                status=LibrarySyncCandidateStatus.REVISION_CREATED.value
                if revision_created
                else LibrarySyncCandidateStatus.UNCHANGED.value,
                affected_count=1,
                created_count=1 if revision_created else 0,
                skipped_count=0 if revision_created else 1,
                message="Revision created." if revision_created else "Revision unchanged.",
            )
        )

        if revision_created:
            variant_payloads = extract_variant_payloads(candidate)
            asset_payloads = extract_asset_payloads(candidate)
            document_payloads = extract_document_payloads(candidate)

            variants = self._replace_variants(repository, family, revision, variant_payloads)
            assets = self._replace_assets(repository, family, revision, asset_payloads)
            documents_created = self._replace_documents(repository, family, revision, document_payloads)

            candidate_result.variant_count = len(variants)
            candidate_result.asset_count = len(assets)
            candidate_result.document_count = len(documents_created)

            candidate_result.add_operation(
                LibrarySyncOperationResult(
                    operation=LibrarySyncOperation.REPLACE_VARIANTS.value,
                    status=LibrarySyncCandidateStatus.UPDATED.value,
                    affected_count=len(variants),
                    created_count=len(variants),
                )
            )
            candidate_result.add_operation(
                LibrarySyncOperationResult(
                    operation=LibrarySyncOperation.REPLACE_ASSETS.value,
                    status=LibrarySyncCandidateStatus.UPDATED.value,
                    affected_count=len(assets),
                    created_count=len(assets),
                )
            )
            candidate_result.add_operation(
                LibrarySyncOperationResult(
                    operation=LibrarySyncOperation.REPLACE_DOCUMENTS.value,
                    status=LibrarySyncCandidateStatus.UPDATED.value,
                    affected_count=len(documents_created),
                    created_count=len(documents_created),
                )
            )

        for issue_payload in issue_payloads[: self.config.issue_limit_per_candidate]:
            issue = LibrarySyncIssue.from_mapping(issue_payload)
            candidate_result.add_issue(issue)
            self._save_issue(
                repository,
                issue,
                scan_run=scan_run,
                family=family,
                revision=revision,
            )

        if candidate_result.revision_created:
            candidate_result.status = LibrarySyncCandidateStatus.REVISION_CREATED.value
        elif candidate_result.family_created:
            candidate_result.status = LibrarySyncCandidateStatus.INSERTED.value
        elif candidate_result.family_updated:
            candidate_result.status = LibrarySyncCandidateStatus.UPDATED.value
        else:
            candidate_result.status = LibrarySyncCandidateStatus.UNCHANGED.value

        candidate_result.published = True
        candidate_result.finished_at = utcnow()
        candidate_result.duration_ms = duration_ms(started_ms)
        return candidate_result

    # ------------------------------------------------------------------
    # Internals: scan
    # ------------------------------------------------------------------

    def _run_scan(
        self,
        *,
        source_root: Optional[str],
        force_refresh: bool,
        include_raw_documents: bool,
        scan_options: Mapping[str, Any],
    ) -> Any:
        scan_service = self.get_scan_service()

        raw_options = dict(scan_options or {})
        raw_options.setdefault("include_invalid", True)

        # Für den DB-Sync brauchen wir ein kompaktes PipelineResult. Große
        # Rohdaten werden bei Bedarf später gezielt aus dem Package-Root gelesen.
        raw_options.setdefault("include_raw_pipeline", False)
        raw_options.setdefault("include_index", False)
        raw_options.setdefault("include_scan_result", False)
        raw_options.setdefault("include_discovery_result", False)
        raw_options.setdefault("include_read_results", False)
        raw_options.setdefault("include_validation_results", False)
        raw_options.setdefault("include_fingerprint_results", False)
        raw_options.setdefault("include_taxonomy_payload", False)

        options_object = None
        options_cls = getattr(scan_service, "LibraryScanServiceOptions", None)

        if callable(options_cls):
            allowed_option_keys = {
                "include_invalid",
                "enabled_only",
                "use_cache",
                "cache_ttl_seconds",
                "refresh_settings",
                "include_raw_pipeline",
                "include_index",
                "include_scan_result",
                "include_discovery_result",
                "include_read_results",
                "include_validation_results",
                "include_fingerprint_results",
                "strict_errors",
                "validate_taxonomy",
                "require_taxonomy",
                "use_taxonomy_labels",
                "include_empty_taxonomy_nodes",
                "include_inactive_taxonomy_nodes",
                "include_taxonomy_payload",
                "force_taxonomy_reload",
            }

            try:
                options_object = options_cls(
                    **{
                        key: value
                        for key, value in raw_options.items()
                        if key in allowed_option_keys
                    }
                )
            except Exception:
                options_object = None

        for function_name in (
            "scan_library_source",
            "scan_library_source_no_cache",
            "scan_library_for_blocks",
        ):
            scan_function = getattr(scan_service, function_name, None)

            if callable(scan_function):
                try:
                    return scan_function(
                        source_root=source_root,
                        force_refresh=force_refresh,
                        options=options_object,
                    )
                except TypeError:
                    try:
                        return scan_function(
                            source_root=source_root,
                            force_refresh=force_refresh,
                        )
                    except TypeError:
                        if source_root:
                            return scan_function(source_root=source_root)
                        return scan_function()

        raise LibraryDbSyncImportError(
            "Scan service does not expose a supported scan function. "
            "Expected one of: scan_library_source, scan_library_source_no_cache, "
            "scan_library_for_blocks."
        )

    # ------------------------------------------------------------------
    # Internals: repository delegation
    # ------------------------------------------------------------------

    def _create_scan_run(self, repository: Any, run_info: LibrarySyncRunInfo) -> Any:
        create_scan_run = getattr(repository, "create_scan_run", None)

        if not callable(create_scan_run):
            return None

        return create_scan_run(
            {
                "source_root": run_info.source_root,
                "mode": run_info.mode,
                "triggered_by": run_info.triggered_by,
                "status": "running",
                "started_at": run_info.started_at,
                "metadata": run_info.metadata,
            },
            commit=False,
        )

    def _finish_scan_run(self, repository: Any, scan_run: Any, result: LibrarySyncResult) -> None:
        if scan_run is None:
            return

        finish_scan_run = getattr(repository, "finish_scan_run", None)

        if callable(finish_scan_run):
            finish_scan_run(
                scan_run,
                stats=result.stats.to_dict(),
                status="finished" if result.ok else "failed",
                commit=False,
            )

    def _fail_scan_run(self, repository: Any, scan_run: Any, exc: BaseException) -> None:
        if scan_run is None:
            return

        fail_scan_run = getattr(repository, "fail_scan_run", None)

        if callable(fail_scan_run):
            fail_scan_run(
                scan_run,
                error=exc,
                commit=False,
            )

    def _get_family_by_uid(self, repository: Any, uid: str) -> Any:
        function = getattr(repository, "get_family_by_vplib_uid", None)

        if callable(function):
            return function(uid)

        return None

    def _upsert_family(self, repository: Any, payload: Mapping[str, Any]) -> Any:
        function = getattr(repository, "upsert_family", None)

        if not callable(function):
            raise LibraryDbSyncImportError("Repository does not expose upsert_family(...).")

        return function(payload, commit=False)

    def _get_latest_revision_hash(self, repository: Any, uid: str) -> Optional[str]:
        function = getattr(repository, "get_latest_revision_hash", None)

        if callable(function):
            return function(uid)

        return None

    def _upsert_revision_if_changed(
        self,
        repository: Any,
        family: Any,
        payload: Mapping[str, Any],
        *,
        scan_run: Any = None,
    ) -> Tuple[Any, bool]:
        function = getattr(repository, "upsert_revision_if_changed", None)

        if not callable(function):
            raise LibraryDbSyncImportError(
                "Repository does not expose upsert_revision_if_changed(...)."
            )

        return function(
            family,
            payload,
            scan_run=scan_run,
            commit=False,
        )

    def _replace_variants(
        self,
        repository: Any,
        family: Any,
        revision: Any,
        variants: Iterable[Mapping[str, Any]],
    ) -> List[Any]:
        function = getattr(repository, "replace_variants", None)

        if not callable(function):
            return []

        return list(function(family, revision, variants, commit=False) or [])

    def _replace_assets(
        self,
        repository: Any,
        family: Any,
        revision: Any,
        assets: Iterable[Mapping[str, Any]],
    ) -> List[Any]:
        function = getattr(repository, "replace_assets", None)

        if not callable(function):
            return []

        return list(function(family, revision, assets, commit=False) or [])

    def _replace_documents(
        self,
        repository: Any,
        family: Any,
        revision: Any,
        documents: Iterable[Mapping[str, Any]],
    ) -> List[Any]:
        function = getattr(repository, "replace_documents", None)

        if not callable(function):
            return []

        return list(function(family, revision, documents, commit=False) or [])

    def _save_issue(
        self,
        repository: Any,
        issue: LibrarySyncIssue,
        *,
        scan_run: Any = None,
        family: Any = None,
        revision: Any = None,
    ) -> Any:
        function = getattr(repository, "add_issue", None)

        if not callable(function):
            return None

        return function(
            issue.to_dict(),
            scan_run=scan_run,
            family=family,
            revision=revision,
            commit=False,
        )

    def _mark_missing_deleted(self, repository: Any, active_vplib_uids: Iterable[str]) -> int:
        function = getattr(repository, "mark_missing_families_deleted", None)

        if not callable(function):
            return 0

        return safe_int(
            function(active_vplib_uids, commit=False),
            0,
        )

    def _commit(self, repository: Any) -> None:
        commit = getattr(repository, "commit", None)

        if callable(commit):
            commit()

    def _rollback(self, repository: Any) -> None:
        rollback = getattr(repository, "rollback", None)

        if callable(rollback):
            rollback()

    def _get_object_id(self, obj: Any) -> Any:
        if obj is None:
            return None

        for name in ("id", "pk", "uuid", "scan_run_id"):
            try:
                value = getattr(obj, name)
            except Exception:
                continue

            if value is not None:
                return value

        data = to_mapping(obj)

        return first_non_empty(
            data.get("id"),
            data.get("pk"),
            data.get("uuid"),
            data.get("scan_run_id"),
        )

    def _assert_enabled(self) -> None:
        if not self.config.enabled:
            raise LibraryDbSyncDisabledError(
                f"Library DB sync is disabled. Enable {ENV_SYNC_ENABLED}=true."
            )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(
        self,
        *,
        check_repository: bool = False,
        check_scan_service: bool = False,
        include_traceback: bool = False,
    ) -> Dict[str, Any]:
        errors: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []

        repository_health: Dict[str, Any] = {
            "checked": check_repository,
            "available": None,
        }

        scan_service_health: Dict[str, Any] = {
            "checked": check_scan_service,
            "available": None,
        }

        if check_repository:
            try:
                repository = self.get_repository()
                health_function = getattr(repository, "health", None)

                if callable(health_function):
                    repository_health = health_function(
                        strict=self.config.strict,
                        check_session=True,
                        include_traceback=include_traceback,
                    )
                else:
                    repository_health = {
                        "checked": True,
                        "available": repository is not None,
                        "status": "loaded_no_health_function",
                    }

                if not repository_health.get("ok", repository_health.get("available", False)):
                    errors.append(
                        {
                            "scope": "repository",
                            "error": "Repository health is not ok.",
                            "health": repository_health,
                        }
                    )

            except Exception as exc:
                payload = {
                    "scope": "repository",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }

                if include_traceback:
                    payload["traceback"] = traceback_module.format_exc()

                errors.append(payload)
                repository_health = {
                    "checked": True,
                    "available": False,
                    "error": payload,
                }

        if check_scan_service:
            try:
                scan_service = self.get_scan_service()
                scan_service_health = {
                    "checked": True,
                    "available": scan_service is not None,
                    "module": getattr(scan_service, "__name__", None),
                }
            except Exception as exc:
                payload = {
                    "scope": "scan_service",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                }

                if include_traceback:
                    payload["traceback"] = traceback_module.format_exc()

                errors.append(payload)
                scan_service_health = {
                    "checked": True,
                    "available": False,
                    "error": payload,
                }

        if not self.config.enabled:
            warnings.append(
                {
                    "scope": "config",
                    "warning": "DB sync is disabled.",
                    "env": ENV_SYNC_ENABLED,
                }
            )

        ok = not errors

        if not ok:
            status = "error"
        elif warnings:
            status = "partial"
        else:
            status = "ok"

        return {
            "ok": ok,
            "status": status,
            "component": LIBRARY_DB_SYNC_COMPONENT_NAME,
            "service": LIBRARY_DB_SYNC_SERVICE_NAME,
            "api_version": LIBRARY_DB_SYNC_API_VERSION,
            "implementation_stage": LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE,
            "version": __version__,
            "config": {
                "enabled": self.config.enabled,
                "strict": self.config.strict,
                "autocommit": self.config.autocommit,
                "mark_missing_deleted": self.config.mark_missing_deleted,
                "continue_on_candidate_error": self.config.continue_on_candidate_error,
                "include_raw_documents": self.config.include_raw_documents,
                "publish_valid_only": self.config.publish_valid_only,
                "repository_import_path": self.config.repository_import_path,
                "scan_service_import_path": self.config.scan_service_import_path,
            },
            "repository": repository_health,
            "scan_service": scan_service_health,
            "imports": {
                "cached_modules": sorted(_IMPORT_CACHE.keys()),
                "cached_errors": _IMPORT_ERROR_CACHE,
            },
            "warnings": warnings,
            "errors": errors,
        }


# ---------------------------------------------------------------------------
# Module-level factory / API
# ---------------------------------------------------------------------------


def create_library_db_sync_service(
    *,
    repository: Any = None,
    repository_factory: Any = None,
    scan_service: Any = None,
    config: Optional[LibraryDbSyncServiceConfig] = None,
) -> LibraryDbSyncService:
    """Erstellt eine neue DB-Sync-Service-Instanz."""

    return LibraryDbSyncService(
        repository=repository,
        repository_factory=repository_factory,
        scan_service=scan_service,
        config=config,
    )


def get_library_db_sync_service(
    *,
    use_cache: bool = True,
    force_new: bool = False,
    repository: Any = None,
    repository_factory: Any = None,
    scan_service: Any = None,
    config: Optional[LibraryDbSyncServiceConfig] = None,
) -> LibraryDbSyncService:
    """Liefert den Default-DB-Sync-Service."""

    global _DEFAULT_SERVICE

    if force_new or not use_cache:
        return create_library_db_sync_service(
            repository=repository,
            repository_factory=repository_factory,
            scan_service=scan_service,
            config=config,
        )

    with _CACHE_LOCK:
        if _DEFAULT_SERVICE is None:
            _DEFAULT_SERVICE = create_library_db_sync_service(
                repository=repository,
                repository_factory=repository_factory,
                scan_service=scan_service,
                config=config,
            )

        return _DEFAULT_SERVICE


def sync_library_to_db(
    *,
    source_root: Optional[str] = None,
    force_refresh: bool = True,
    triggered_by: Optional[str] = None,
    publish_valid_only: Optional[bool] = None,
    mark_missing_deleted: Optional[bool] = None,
    include_raw_documents: Optional[bool] = None,
    scan_options: Optional[Mapping[str, Any]] = None,
    service: Optional[LibraryDbSyncService] = None,
) -> LibrarySyncResult:
    """Top-Level Convenience-Funktion für Filesystem → DB Sync."""

    sync_service = service or get_library_db_sync_service()

    return sync_service.sync_library_source(
        source_root=source_root,
        force_refresh=force_refresh,
        triggered_by=triggered_by,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        include_raw_documents=include_raw_documents,
        scan_options=scan_options,
    )


def sync_library_to_database_response(
    *,
    source_root: Optional[str] = None,
    force_refresh: bool = True,
    triggered_by: Optional[str] = None,
    publish_valid_only: Optional[bool] = None,
    mark_missing_deleted: Optional[bool] = None,
    include_raw_documents: Optional[bool] = None,
    scan_options: Optional[Mapping[str, Any]] = None,
    service: Optional[LibraryDbSyncService] = None,
) -> Dict[str, Any]:
    """
    Kompakte JSON-kompatible Antwort für POST /library/sync.

    Die Route sollte nicht das rohe LibrarySyncResult serialisieren, sondern
    dieses kompakte Response-Payload verwenden.
    """

    result = sync_library_to_db(
        source_root=source_root,
        force_refresh=force_refresh,
        triggered_by=triggered_by,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        include_raw_documents=include_raw_documents,
        scan_options=scan_options,
        service=service,
    )

    try:
        payload = build_sync_response(result)
    except Exception:
        to_dict = getattr(result, "to_dict", None)
        if callable(to_dict):
            try:
                payload = to_dict()
            except TypeError:
                payload = to_dict(flat=True)
        else:
            payload = json_safe(result)

    return json_safe(payload)


def sync_scan_result_to_db(
    scan_result: Any,
    *,
    scan_run: Any = None,
    run_info: Optional[LibrarySyncRunInfo] = None,
    publish_valid_only: Optional[bool] = None,
    mark_missing_deleted: Optional[bool] = None,
    repository: Any = None,
    service: Optional[LibraryDbSyncService] = None,
) -> LibrarySyncResult:
    """Top-Level Convenience-Funktion für vorhandenes ScanResult → DB Sync."""

    sync_service = service or get_library_db_sync_service(repository=repository)

    return sync_service.sync_scan_result_to_db(
        scan_result,
        scan_run=scan_run,
        run_info=run_info,
        publish_valid_only=publish_valid_only,
        mark_missing_deleted=mark_missing_deleted,
        repository=repository,
    )


def get_library_db_sync_service_health(
    *,
    check_repository: bool = False,
    check_scan_service: bool = False,
    include_traceback: bool = False,
) -> Dict[str, Any]:
    """Health-Check für den DB-Sync-Service."""

    service = get_library_db_sync_service()

    return service.health(
        check_repository=check_repository,
        check_scan_service=check_scan_service,
        include_traceback=include_traceback,
    )


def assert_library_db_sync_service_ready(
    *,
    check_repository: bool = True,
    check_scan_service: bool = True,
) -> Dict[str, Any]:
    """Wirft RuntimeError, wenn der DB-Sync-Service nicht bereit ist."""

    health = get_library_db_sync_service_health(
        check_repository=check_repository,
        check_scan_service=check_scan_service,
    )

    if not health.get("ok"):
        raise LibraryDbSyncServiceError(
            "Library DB sync service is not ready "
            f"(status={health.get('status')}, errors={health.get('errors')})."
        )

    return health


def clear_library_db_sync_service_cache() -> Dict[str, Any]:
    """Leert Import- und Default-Service-Caches."""

    global _DEFAULT_SERVICE

    with _CACHE_LOCK:
        _DEFAULT_SERVICE = None

    import_result = clear_library_db_sync_import_cache()

    return {
        "ok": True,
        "default_service_cleared": True,
        "imports": import_result,
    }


clear_library_db_sync_service_caches = clear_library_db_sync_service_cache
clear_db_sync_cache = clear_library_db_sync_service_cache
clear_db_sync_caches = clear_library_db_sync_service_cache


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "LIBRARY_DB_SYNC_SERVICE_NAME",
    "LIBRARY_DB_SYNC_COMPONENT_NAME",
    "LIBRARY_DB_SYNC_API_VERSION",
    "LIBRARY_DB_SYNC_IMPLEMENTATION_STAGE",

    # Env / defaults
    "ENV_SYNC_ENABLED",
    "ENV_SYNC_STRICT",
    "ENV_SYNC_AUTOCOMMIT",
    "ENV_SYNC_MARK_MISSING_DELETED",
    "ENV_SYNC_CONTINUE_ON_CANDIDATE_ERROR",
    "ENV_SYNC_INCLUDE_RAW_DOCUMENTS",
    "DEFAULT_SYNC_ENABLED",
    "DEFAULT_SYNC_STRICT",
    "DEFAULT_SYNC_AUTOCOMMIT",
    "DEFAULT_SYNC_MARK_MISSING_DELETED",
    "DEFAULT_SYNC_CONTINUE_ON_CANDIDATE_ERROR",
    "DEFAULT_SYNC_INCLUDE_RAW_DOCUMENTS",
    "DEFAULT_REPOSITORY_FACTORY_IMPORT",
    "DEFAULT_SCAN_SERVICE_IMPORT",
    "DEFAULT_DOCUMENT_LIMIT_FOR_DETAIL_PAYLOAD",
    "DEFAULT_ISSUE_LIMIT_PER_CANDIDATE",

    # Exceptions
    "LibraryDbSyncServiceError",
    "LibraryDbSyncDisabledError",
    "LibraryDbSyncImportError",
    "LibraryDbSyncValidationError",
    "LibraryDbSyncCandidateError",

    # Config / service
    "LibraryDbSyncServiceConfig",
    "LibraryDbSyncService",

    # Generic helpers
    "utcnow",
    "monotonic_ms",
    "duration_ms",
    "env_bool",
    "normalize_string",
    "normalize_vplib_uid",
    "safe_int",
    "safe_bool",
    "json_safe",
    "to_mapping",
    "first_non_empty",
    "deep_get",
    "mapping_get_any",
    "exception_to_issue",

    # Import helpers
    "safe_import_module",
    "clear_library_db_sync_import_cache",

    # Document helpers
    "normalize_document_path",
    "unwrap_document_payload",
    "document_mapping_from_value",
    "get_candidate_path_candidates",
    "find_existing_package_root",
    "read_json_file",
    "load_documents_from_package_root",
    "augment_documents_from_filesystem",

    # Candidate extraction
    "extract_documents_from_any",
    "get_document",
    "extract_manifest",
    "extract_identity",
    "extract_classification",
    "extract_inventory",
    "extract_validation_payload",
    "extract_fingerprint_payload",
    "extract_summary_payload",
    "extract_source_path",
    "extract_package_root",
    "extract_revision_hash",
    "extract_vplib_uid",
    "extract_family_id",
    "extract_package_id",
    "extract_variant_ids",
    "candidate_is_valid",
    "extract_pipeline_candidates",

    # Payload builders
    "build_family_upsert_payload",
    "build_revision_upsert_payload",
    "extract_variant_payloads",
    "extract_asset_payloads",
    "extract_document_payloads",
    "extract_issue_payloads",

    # Top-level API
    "create_library_db_sync_service",
    "get_library_db_sync_service",
    "sync_library_to_db",
    "sync_library_to_database_response",
    "sync_scan_result_to_db",
    "get_library_db_sync_service_health",
    "assert_library_db_sync_service_ready",
    "clear_library_db_sync_service_cache",
    "clear_library_db_sync_service_caches",
    "clear_db_sync_cache",
    "clear_db_sync_caches",

    # Reexported domain helpers
    "build_sync_response",
]