# services/vectoplan-library/routes/api.py
"""
API-Routen für die VECTOPLAN Library.

Diese Datei bündelt die JSON/API-Routen für die fachliche Creative-Library-
Schicht.

Ziel:

- dateibasierte Diagnose- und Debug-Routen bereitstellen
- neuen DB-Sync-Pfad bereitstellen
- produktive Read-Routen standardmäßig aus der DB bedienen
- alten filesystem-basierten Read-Pfad als Debug-Fallback erhalten
- keine Scans oder DB-Zugriffe beim Import ausführen
- robuste Fehlerantworten liefern
- unabhängig von konkreten Service-Implementierungsdetails bleiben
- Sync-Ergebnisse kompakt serialisieren, ohne rohe Domain-/ORM-Objekte durch jsonify zu schicken

Wichtige Trennung:

GET /api/v1/vplib/library/scan
    liest/scant dateibasiert und schreibt nicht in die DB.

POST /api/v1/vplib/library/sync
    scannt und synchronisiert gültige Ergebnisse in die DB.

GET /api/v1/vplib/library/blocks
GET /api/v1/vplib/library/blocks/<block_id>
GET /api/v1/vplib/library/blocks/<block_id>/variants
GET /api/v1/vplib/library/tree
GET /api/v1/vplib/library/inventory
    lesen standardmäßig aus der DB.
    Mit ?source=filesystem kann der alte dateibasierte Debug-Pfad genutzt werden.

Blueprint:

    api_bp

Empfohlene Registrierung in app.py oder routes/__init__.py:

    from routes.api import api_bp
    app.register_blueprint(api_bp)

Die Routen enthalten bereits den vollständigen Prefix:

    /api/v1/vplib/library/...

Falls ihr zentral mit url_prefix registrieren wollt, nutzt:

    register_api_routes(app, url_prefix=None)

und passt den Prefix nur an einer Stelle an.
"""

from __future__ import annotations

import importlib
import inspect
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Flask import
# ---------------------------------------------------------------------------

try:
    from flask import Blueprint, jsonify, request
except Exception as flask_import_error:  # pragma: no cover - defensive fallback
    Blueprint = None  # type: ignore
    jsonify = None  # type: ignore
    request = None  # type: ignore
    _FLASK_IMPORT_ERROR = flask_import_error
else:
    _FLASK_IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

API_ROUTES_NAME = "vplib_library_api"
API_ROUTES_COMPONENT = "creative_library_api_routes"
API_ROUTES_VERSION = "0.1.1"
API_ROUTES_STAGE = "db-sync-and-published-read-routes"

LIBRARY_API_PREFIX = "/api/v1/vplib/library"

DEFAULT_READ_SOURCE = "db"
FILESYSTEM_READ_SOURCE = "filesystem"
DB_READ_SOURCE = "db"

SUPPORTED_READ_SOURCES = (
    DB_READ_SOURCE,
    FILESYSTEM_READ_SOURCE,
)

DEFAULT_JSON_MIMETYPE = "application/json"


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

if Blueprint is not None:
    api_bp = Blueprint(API_ROUTES_NAME, __name__)
else:  # pragma: no cover - only relevant if Flask is unavailable
    api_bp = None


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    """Timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def iso_now() -> str:
    """UTC timestamp for responses."""

    return utcnow().isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """Serialisiert Exceptions sicher in JSON-kompatible Form."""

    if exc is None:
        return None

    payload: dict[str, Any] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
    }

    if include_traceback:
        payload["traceback"] = traceback.format_exception(
            type(exc),
            exc,
            exc.__traceback__,
        )

    return payload


def dataclass_shallow_dict(value: Any) -> dict[str, Any]:
    """
    Serialisiert Dataclasses flach.

    Absichtlich kein dataclasses.asdict(...), weil asdict rekursiv kopiert und
    bei großen Domain-Objekten oder ORM-nahen Objekten sehr teuer werden kann.
    """

    if not is_dataclass(value):
        return {}

    result: dict[str, Any] = {}

    for field_name in getattr(value, "__dataclass_fields__", {}).keys():
        try:
            result[str(field_name)] = getattr(value, field_name)
        except Exception:
            continue

    return result


def get_attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    """Liest ein Feld robust aus Mapping oder Objekt."""

    if value is None:
        return default

    if isinstance(value, Mapping):
        return value.get(key, default)

    try:
        return getattr(value, key)
    except Exception:
        return default


def object_columns_to_mapping(value: Any) -> dict[str, Any]:
    """
    Serialisiert SQLAlchemy-Objekte nur über echte Tabellen-Spalten.

    Dadurch werden Lazy-Relationships nicht versehentlich geladen.
    """

    if value is None:
        return {}

    table = getattr(value.__class__, "__table__", None)
    columns = getattr(table, "columns", None)

    if columns is None:
        return {}

    result: dict[str, Any] = {}

    try:
        for column in columns:
            name = str(column.name)
            try:
                result[name] = getattr(value, name)
            except Exception:
                continue
    except Exception:
        return {}

    return result


def json_safe(value: Any) -> Any:
    """
    Defensiver JSON-Safe-Konverter.

    Reihenfolge ist wichtig:
    - einfache Typen zuerst
    - Path/Datetime/Module
    - to_dict vor Dataclass
    - Dataclass nur shallow
    - Mapping/List rekursiv
    - Fallback str(...)

    Nie rohe Domain-/ORM-Objekte rekursiv per asdict(...) kopieren.
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, ModuleType):
        return {
            "module": value.__name__,
            "file": getattr(value, "__file__", None),
        }

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        for kwargs in (
            {},
            {"include_raw_documents": False},
            {"include_metadata": False},
            {"flat": True},
        ):
            try:
                return json_safe(to_dict(**kwargs))
            except TypeError:
                continue
            except Exception:
                break

    if is_dataclass(value):
        return {
            str(key): json_safe(item)
            for key, item in dataclass_shallow_dict(value).items()
        }

    column_mapping = object_columns_to_mapping(value)
    if column_mapping:
        return {
            str(key): json_safe(item)
            for key, item in column_mapping.items()
        }

    if isinstance(value, Mapping):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    return str(value)


def to_mapping(value: Any) -> dict[str, Any]:
    """
    Konvertiert Mapping, Dataclass, Domainobjekt oder ORM-Objekt defensiv in Dict.

    Wichtig: Auch hier kein rekursives asdict(...) für Dataclasses.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        for kwargs in (
            {},
            {"include_raw_documents": False},
            {"include_metadata": False},
            {"flat": True},
        ):
            try:
                result = to_dict(**kwargs)
                if isinstance(result, Mapping):
                    return dict(result)
            except TypeError:
                continue
            except Exception:
                break

    if is_dataclass(value):
        return dataclass_shallow_dict(value)

    column_mapping = object_columns_to_mapping(value)
    if column_mapping:
        return column_mapping

    result: dict[str, Any] = {}

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


def first_non_empty(*values: Any) -> Any:
    """Liefert den ersten nicht-leeren Wert."""

    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def normalize_string(value: Any) -> Optional[str]:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def normalize_read_source(value: Any) -> str:
    """Normalisiert ?source=... für Read-Routen."""

    text = str(value or DEFAULT_READ_SOURCE).strip().lower().replace("-", "_")

    aliases = {
        "database": DB_READ_SOURCE,
        "db": DB_READ_SOURCE,
        "sql": DB_READ_SOURCE,
        "postgres": DB_READ_SOURCE,
        "postgresql": DB_READ_SOURCE,
        "published": DB_READ_SOURCE,
        "fs": FILESYSTEM_READ_SOURCE,
        "file": FILESYSTEM_READ_SOURCE,
        "files": FILESYSTEM_READ_SOURCE,
        "source": FILESYSTEM_READ_SOURCE,
        "scan": FILESYSTEM_READ_SOURCE,
    }

    return aliases.get(text, text if text in SUPPORTED_READ_SOURCES else DEFAULT_READ_SOURCE)


def parse_bool(value: Any, default: bool = False) -> bool:
    """Robuster bool parser für Query-/JSON-Werte."""

    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = str(value).strip().lower()

    if text in {"1", "true", "yes", "y", "on", "active", "enabled"}:
        return True

    if text in {"0", "false", "no", "n", "off", "inactive", "disabled"}:
        return False

    return default


def parse_int(
    value: Any,
    default: int = 0,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    """Robuster int parser."""

    try:
        number = int(value)
    except Exception:
        number = default

    if minimum is not None:
        number = max(minimum, number)

    if maximum is not None:
        number = min(maximum, number)

    return number


def request_args() -> dict[str, Any]:
    """Liest Query-Parameter als Dict."""

    if request is None:
        return {}

    try:
        return dict(request.args.items())
    except Exception:
        return {}


def request_json() -> dict[str, Any]:
    """Liest JSON-Body defensiv."""

    if request is None:
        return {}

    try:
        data = request.get_json(silent=True)
    except Exception:
        return {}

    return dict(data or {}) if isinstance(data, Mapping) else {}


def merged_request_data() -> dict[str, Any]:
    """Kombiniert JSON-Body und Query-Parameter. Query überschreibt Body."""

    data = request_json()
    data.update(request_args())
    return data


def get_client_identifier() -> Optional[str]:
    """Best-effort Identifikation für triggered_by."""

    if request is None:
        return None

    try:
        header_user = (
            request.headers.get("X-User")
            or request.headers.get("X-User-Id")
            or request.headers.get("X-Actor")
        )
        if header_user:
            return str(header_user)

        remote = request.remote_addr
        if remote:
            return f"remote:{remote}"
    except Exception:
        return None

    return None


def response_status_from_payload(payload: Mapping[str, Any], *, default: int = 200) -> int:
    """Leitet HTTP-Status aus Payload ab."""

    status = str(payload.get("status") or "").lower()

    if payload.get("ok") is False:
        if status in {"not_found", "missing"}:
            return 404

        if status in {"disabled", "unavailable"}:
            return 503

        if status in {"invalid", "validation_error", "bad_request"}:
            return 400

        return 500

    return default


def json_response(payload: Any, status_code: Optional[int] = None):
    """Gibt Flask-JSON-Response zurück."""

    safe_payload = json_safe(payload)

    if isinstance(safe_payload, Mapping):
        safe_payload.setdefault("generated_at", iso_now())

    if status_code is None and isinstance(safe_payload, Mapping):
        status_code = response_status_from_payload(safe_payload)

    if status_code is None:
        status_code = 200

    if jsonify is None:  # pragma: no cover
        return safe_payload

    return jsonify(safe_payload), status_code


def ok_response(
    payload: Optional[Mapping[str, Any]] = None,
    *,
    status_code: int = 200,
):
    """Standard-Erfolgsantwort."""

    data = dict(payload or {})
    data.setdefault("ok", True)
    data.setdefault("status", "ok")
    return json_response(data, status_code=status_code)


def error_response(
    error: Any,
    *,
    message: Optional[str] = None,
    status: str = "error",
    status_code: int = 500,
    include_traceback: bool = False,
):
    """Standard-Fehlerantwort."""

    if isinstance(error, BaseException):
        error_payload = exception_to_dict(error, include_traceback=include_traceback)
        error_type = error.__class__.__name__
        error_message = str(error)
    else:
        error_payload = json_safe(error)
        error_type = type(error).__name__ if error is not None else None
        error_message = str(error) if error is not None else None

    return json_response(
        {
            "ok": False,
            "status": status,
            "message": message or error_message,
            "error_type": error_type,
            "error": error_payload,
        },
        status_code=status_code,
    )


def not_found_response(identifier: Any, *, message: Optional[str] = None):
    """Standard-404-Antwort."""

    return json_response(
        {
            "ok": False,
            "status": "not_found",
            "identifier": str(identifier) if identifier is not None else None,
            "message": message or f"Resource not found: {identifier}",
        },
        status_code=404,
    )


def route_disabled_response(route_name: str):
    """Antwort bei fehlender Flask-/Route-Verfügbarkeit."""

    return json_response(
        {
            "ok": False,
            "status": "disabled",
            "route": route_name,
            "message": "Route is unavailable because Flask could not be imported.",
            "error": exception_to_dict(_FLASK_IMPORT_ERROR),
        },
        status_code=503,
    )


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

_MODULE_IMPORT_CACHE: dict[str, ModuleType] = {}
_MODULE_IMPORT_ERRORS: dict[str, dict[str, Any]] = {}


def safe_import_first(
    candidates: Sequence[str],
    *,
    required: bool = False,
) -> Optional[ModuleType]:
    """Importiert den ersten verfügbaren Modulpfad."""

    last_error: Optional[BaseException] = None

    for module_path in candidates:
        normalized = str(module_path or "").strip()

        if not normalized:
            continue

        if normalized in _MODULE_IMPORT_CACHE:
            return _MODULE_IMPORT_CACHE[normalized]

        try:
            module = importlib.import_module(normalized)
            _MODULE_IMPORT_CACHE[normalized] = module
            _MODULE_IMPORT_ERRORS.pop(normalized, None)
            return module

        except Exception as exc:
            last_error = exc
            _MODULE_IMPORT_ERRORS[normalized] = exception_to_dict(exc, include_traceback=True)

    if required:
        raise ImportError(
            f"Could not import any candidate module: {', '.join(candidates)}"
        ) from last_error

    return None


def import_library_package(required: bool = True) -> Optional[ModuleType]:
    return safe_import_first(
        (
            "library",
            "src.library",
        ),
        required=required,
    )


def import_library_services(required: bool = True) -> Optional[ModuleType]:
    return safe_import_first(
        (
            "library.services",
            "src.library.services",
        ),
        required=required,
    )


def import_library_repositories(required: bool = True) -> Optional[ModuleType]:
    return safe_import_first(
        (
            "library.repositories",
            "src.library.repositories",
        ),
        required=required,
    )


def import_sql_repositories(required: bool = True) -> Optional[ModuleType]:
    return safe_import_first(
        (
            "library.repositories.sql",
            "src.library.repositories.sql",
        ),
        required=required,
    )


def call_flexible(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """
    Ruft eine Funktion mit passender Teilmenge der kwargs auf.

    Damit bleiben Routes kompatibel mit leicht unterschiedlichen Service-
    Signaturen während der Migration.
    """

    try:
        return fn(**kwargs)
    except TypeError:
        pass

    try:
        signature = inspect.signature(fn)
        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )

        if accepts_var_kwargs:
            return fn(**kwargs)

        filtered = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters
        }

        return fn(**filtered)
    except TypeError:
        raise
    except Exception:
        raise


def module_function(module: ModuleType, *names: str) -> Optional[Callable[..., Any]]:
    """Liefert erste vorhandene Callable aus Modul."""

    for name in names:
        value = getattr(module, name, None)
        if callable(value):
            return value

    return None


def call_block_identifier_function(
    fn: Callable[..., Any],
    block_id: str,
    **kwargs: Any,
) -> Any:
    """
    Ruft Detail-/Variants-Funktionen robust auf.

    Es gibt aktuell zwei kompatible Service-Ebenen:

    - Wrapper in library.services:
        published_block_detail_db_response(block_id, ...)
        published_block_variants_db_response(block_id, ...)

    - direkte Published-Service-Funktionen:
        get_published_block_detail_response(identifier, ...)
        get_published_block_variants_response(identifier, ...)

    Diese Helper-Funktion verhindert beide Fehlerbilder:

    - got multiple values for argument 'identifier'
    - missing required positional argument: 'block_id'
    """

    try:
        signature = inspect.signature(fn)
        parameters = signature.parameters

        if "block_id" in parameters:
            return call_flexible(fn, block_id=block_id, **kwargs)

        if "identifier" in parameters:
            return call_flexible(fn, identifier=block_id, **kwargs)

        accepts_var_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

        if accepts_var_kwargs:
            return call_flexible(fn, block_id=block_id, **kwargs)

        positional_parameters = [
            parameter
            for parameter in parameters.values()
            if parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        ]

        if positional_parameters:
            first_name = positional_parameters[0].name
            return call_flexible(fn, **{first_name: block_id}, **kwargs)

    except Exception:
        pass

    return call_flexible(fn, block_id=block_id, **kwargs)


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

def library_filter_kwargs() -> dict[str, Any]:
    """Standardfilter für Blocks/Tree/Inventory."""

    args = request_args()

    return {
        "domain": normalize_string(args.get("domain")),
        "category": normalize_string(args.get("category")),
        "subcategory": normalize_string(args.get("subcategory")),
        "object_kind": normalize_string(args.get("object_kind")),
        "q": normalize_string(first_non_empty(args.get("q"), args.get("search"))),
    }


def pagination_kwargs() -> dict[str, Any]:
    """Pagination-Parameter."""

    args = request_args()

    return {
        "limit": parse_int(args.get("limit"), 100, minimum=1, maximum=1000),
        "offset": parse_int(args.get("offset"), 0, minimum=0),
    }


def include_kwargs() -> dict[str, Any]:
    """Include-/Debug-Parameter."""

    args = request_args()

    return {
        "include_payload": parse_bool(args.get("include_payload"), False),
        "include_metadata": parse_bool(args.get("include_metadata"), False),
        "include_raw_documents": parse_bool(args.get("include_raw_documents"), False),
        "include_unpublished": parse_bool(args.get("include_unpublished"), False),
        "include_deleted": parse_bool(args.get("include_deleted"), False),
        "enabled_only": parse_bool(args.get("enabled_only"), True),
        "force_refresh": parse_bool(args.get("force_refresh"), False),
    }


def current_read_source() -> str:
    """Liest ?source=db|filesystem."""

    args = request_args()
    return normalize_read_source(args.get("source"))


def scan_options_from_request() -> dict[str, Any]:
    """Baut Scan-Options aus Query/Body."""

    data = merged_request_data()

    return {
        "include_invalid": parse_bool(data.get("include_invalid"), True),
        "include_raw_documents": parse_bool(data.get("include_raw_documents"), True),
        "include_read_artifacts": parse_bool(data.get("include_read_artifacts"), True),
        "force_taxonomy_reload": parse_bool(data.get("force_taxonomy_reload"), False),
    }


# ---------------------------------------------------------------------------
# Sync response compaction
# ---------------------------------------------------------------------------

SYNC_CANDIDATE_FIELDS = (
    "status",
    "vplib_uid",
    "family_id",
    "package_id",
    "family_slug",
    "label",
    "object_kind",
    "domain",
    "category",
    "subcategory",
    "source_path",
    "package_root",
    "revision_hash",
    "previous_revision_hash",
    "family_db_id",
    "revision_db_id",
    "valid",
    "validation_status",
    "published",
    "skipped",
    "family_created",
    "family_updated",
    "revision_created",
    "variant_count",
    "asset_count",
    "document_count",
    "issue_count",
    "warning_count",
    "error_count",
    "duration_ms",
)

SYNC_ISSUE_FIELDS = (
    "severity",
    "code",
    "message",
    "scope",
    "path",
    "field",
    "vplib_uid",
    "family_id",
    "package_id",
    "revision_hash",
    "operation",
)

SYNC_RUN_FIELDS = (
    "mode",
    "source",
    "target",
    "source_root",
    "triggered_by",
    "force_refresh",
    "publish_valid_only",
    "mark_missing_deleted",
    "scan_run_id",
    "started_at",
    "finished_at",
    "duration_ms",
)

SYNC_STATS_FIELDS = (
    "total_count",
    "processed_count",
    "published_count",
    "skipped_count",
    "failed_count",
    "inserted_count",
    "updated_count",
    "unchanged_count",
    "deleted_count",
    "marked_missing_deleted_count",
    "family_created_count",
    "family_updated_count",
    "revision_created_count",
    "revision_unchanged_count",
    "variant_count",
    "asset_count",
    "document_count",
    "issue_count",
    "warning_count",
    "error_count",
)


def compact_fields(value: Any, fields: Sequence[str]) -> dict[str, Any]:
    """Extrahiert nur explizit erlaubte Felder aus Mapping/Objekt."""

    result: dict[str, Any] = {}

    for field_name in fields:
        item = get_attr_or_key(value, field_name, None)
        if item is not None:
            result[field_name] = json_safe(item)

    return result


def compact_issue(value: Any) -> dict[str, Any]:
    """Kompakte Issue-Darstellung ohne rohe Metadata-Payloads."""

    return compact_fields(value, SYNC_ISSUE_FIELDS)


def compact_candidate(value: Any) -> dict[str, Any]:
    """Kompakte Candidate-Darstellung ohne rohe Dokumente/ORM-Objekte."""

    payload = compact_fields(value, SYNC_CANDIDATE_FIELDS)

    operations = get_attr_or_key(value, "operations", None)
    if operations:
        compact_operations = []

        for operation in list(operations)[:50]:
            compact_operations.append(
                compact_fields(
                    operation,
                    (
                        "operation",
                        "status",
                        "affected_count",
                        "created_count",
                        "updated_count",
                        "deleted_count",
                        "skipped_count",
                        "message",
                    ),
                )
            )

        payload["operations"] = compact_operations

    issues = get_attr_or_key(value, "issues", None)
    if issues:
        payload["issues"] = [compact_issue(issue) for issue in list(issues)[:50]]
        payload["issues_truncated"] = len(list(issues)) > 50 if hasattr(issues, "__len__") else False

    return payload


def compact_run(value: Any) -> dict[str, Any]:
    """Kompakte Run-Information."""

    return compact_fields(value, SYNC_RUN_FIELDS)


def compact_stats(value: Any) -> dict[str, Any]:
    """Kompakte Statistik-Information."""

    return compact_fields(value, SYNC_STATS_FIELDS)


def sync_response_payload(result: Any) -> dict[str, Any]:
    """
    Baut eine kompakte JSON-Antwort für Sync-Ergebnisse.

    Diese Funktion ist bewusst explizit und verwendet nicht blind result.to_dict(),
    weil ältere to_dict/asdict-Pfade große verschachtelte Payloads oder ORM-nahe
    Objekte rekursiv serialisieren können.
    """

    if isinstance(result, Mapping):
        raw = dict(result)

        candidates = raw.get("candidates") or []
        issues = raw.get("issues") or raw.get("errors") or []

        return {
            "ok": bool(raw.get("ok", False)),
            "status": raw.get("status") or "unknown",
            "message": raw.get("message"),
            "run": json_safe(raw.get("run") or {}),
            "stats": json_safe(raw.get("stats") or {}),
            "candidate_count": len(candidates) if isinstance(candidates, (list, tuple)) else raw.get("candidate_count", 0),
            "candidates": [compact_candidate(candidate) for candidate in list(candidates)[:100]]
            if isinstance(candidates, (list, tuple))
            else [],
            "candidates_truncated": len(candidates) > 100 if isinstance(candidates, (list, tuple)) else False,
            "issue_count": len(issues) if isinstance(issues, (list, tuple)) else raw.get("issue_count", 0),
            "issues": [compact_issue(issue) for issue in list(issues)[:100]]
            if isinstance(issues, (list, tuple))
            else [],
            "issues_truncated": len(issues) > 100 if isinstance(issues, (list, tuple)) else False,
            "source": "database_sync",
        }

    candidates = get_attr_or_key(result, "candidates", []) or []
    issues = get_attr_or_key(result, "issues", []) or []
    warnings = get_attr_or_key(result, "warnings", []) or []
    errors = get_attr_or_key(result, "errors", []) or []
    run = get_attr_or_key(result, "run", None)
    stats = get_attr_or_key(result, "stats", None)

    candidates_list = list(candidates) if isinstance(candidates, (list, tuple)) else []
    issues_list = list(issues) if isinstance(issues, (list, tuple)) else []
    warnings_list = list(warnings) if isinstance(warnings, (list, tuple)) else []
    errors_list = list(errors) if isinstance(errors, (list, tuple)) else []

    return {
        "ok": bool(get_attr_or_key(result, "ok", False)),
        "status": get_attr_or_key(result, "status", "unknown"),
        "message": get_attr_or_key(result, "message", None),
        "run": compact_run(run),
        "stats": compact_stats(stats),
        "candidate_count": len(candidates_list),
        "candidates": [compact_candidate(candidate) for candidate in candidates_list[:100]],
        "candidates_truncated": len(candidates_list) > 100,
        "issue_count": len(issues_list),
        "issues": [compact_issue(issue) for issue in issues_list[:100]],
        "issues_truncated": len(issues_list) > 100,
        "warning_count": len(warnings_list),
        "warnings": json_safe(warnings_list[:100]),
        "warnings_truncated": len(warnings_list) > 100,
        "error_count": len(errors_list),
        "errors": json_safe(errors_list[:100]),
        "errors_truncated": len(errors_list) > 100,
        "source": "database_sync",
    }


# ---------------------------------------------------------------------------
# API route helpers
# ---------------------------------------------------------------------------

def get_api_routes_health_payload() -> dict[str, Any]:
    """Health-Payload nur für diese Route-Datei."""

    return {
        "ok": _FLASK_IMPORT_ERROR is None,
        "status": "ok" if _FLASK_IMPORT_ERROR is None else "error",
        "component": API_ROUTES_COMPONENT,
        "name": API_ROUTES_NAME,
        "version": API_ROUTES_VERSION,
        "stage": API_ROUTES_STAGE,
        "prefix": LIBRARY_API_PREFIX,
        "flask_available": _FLASK_IMPORT_ERROR is None,
        "flask_error": exception_to_dict(_FLASK_IMPORT_ERROR),
        "supported_read_sources": list(SUPPORTED_READ_SOURCES),
        "default_read_source": DEFAULT_READ_SOURCE,
        "import_cache": {
            "cached_modules": sorted(_MODULE_IMPORT_CACHE.keys()),
            "import_errors": _MODULE_IMPORT_ERRORS,
        },
        "routes": {
            "health": f"{LIBRARY_API_PREFIX}/health",
            "db_health": f"{LIBRARY_API_PREFIX}/db/health",
            "scan": f"{LIBRARY_API_PREFIX}/scan",
            "sync": f"{LIBRARY_API_PREFIX}/sync",
            "sync_runs": f"{LIBRARY_API_PREFIX}/sync-runs",
            "publication_status": f"{LIBRARY_API_PREFIX}/publication-status",
            "blocks": f"{LIBRARY_API_PREFIX}/blocks",
            "block_detail": f"{LIBRARY_API_PREFIX}/blocks/<block_id>",
            "block_variants": f"{LIBRARY_API_PREFIX}/blocks/<block_id>/variants",
            "tree": f"{LIBRARY_API_PREFIX}/tree",
            "inventory": f"{LIBRARY_API_PREFIX}/inventory",
        },
    }


def get_services_or_error():
    try:
        return import_library_services(required=True), None
    except Exception as exc:
        return None, exc


def get_repositories_or_error():
    try:
        return import_library_repositories(required=True), None
    except Exception as exc:
        return None, exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

if api_bp is not None:

    @api_bp.get(f"{LIBRARY_API_PREFIX}/health")
    def library_health_route():
        """Library API Health."""

        args = request_args()
        strict = parse_bool(args.get("strict"), False)
        strict_db = parse_bool(args.get("strict_db"), False)
        include_traceback = parse_bool(args.get("traceback"), False)
        include_subhealth = parse_bool(args.get("subhealth"), True)

        payload = {
            "api": get_api_routes_health_payload(),
        }

        try:
            library_module = import_library_package(required=True)
            get_health = getattr(library_module, "get_library_health", None)

            if callable(get_health):
                library_health = call_flexible(
                    get_health,
                    strict=strict,
                    strict_db=strict_db,
                    include_traceback=include_traceback,
                    include_subhealth=include_subhealth,
                )
            else:
                library_health = {
                    "ok": True,
                    "status": "loaded_no_health_function",
                    "module": getattr(library_module, "__name__", None),
                }

            payload["library"] = library_health
            payload["ok"] = bool(library_health.get("ok", True)) and payload["api"]["ok"]
            payload["status"] = "ok" if payload["ok"] else "error"

            return json_response(payload)

        except Exception as exc:
            payload["ok"] = False
            payload["status"] = "error"
            payload["error"] = exception_to_dict(exc, include_traceback=include_traceback)
            return json_response(payload, status_code=500)


    @api_bp.get(f"{LIBRARY_API_PREFIX}/db/health")
    def library_db_health_route():
        """DB-/Repository-/Published Health."""

        args = request_args()
        strict = parse_bool(args.get("strict"), False)
        include_traceback = parse_bool(args.get("traceback"), False)

        payload: dict[str, Any] = {
            "ok": True,
            "status": "ok",
            "api": {
                "route": f"{LIBRARY_API_PREFIX}/db/health",
            },
        }

        try:
            repositories = import_library_repositories(required=False)
            if repositories is not None:
                health_fn = module_function(
                    repositories,
                    "get_repositories_health",
                    "get_repository_health",
                )
                if health_fn:
                    payload["repositories"] = call_flexible(
                        health_fn,
                        strict=strict,
                        attempt_import=True,
                        include_tracebacks=include_traceback,
                        include_traceback=include_traceback,
                        require_backend="sql",
                    )

            sql_repositories = import_sql_repositories(required=False)
            if sql_repositories is not None:
                health_fn = module_function(
                    sql_repositories,
                    "get_sql_repositories_health",
                    "get_sql_repository_health",
                )
                if health_fn:
                    payload["sql_repositories"] = call_flexible(
                        health_fn,
                        strict=strict,
                        attempt_import=True,
                        include_tracebacks=include_traceback,
                        include_traceback=include_traceback,
                        require_models=False,
                        require_sqlalchemy_extension=False,
                    )

            services = import_library_services(required=False)
            if services is not None:
                sync_health = getattr(services, "get_library_db_sync_service_health", None)
                published_health = getattr(services, "get_library_published_service_health", None)

                if callable(sync_health):
                    payload["db_sync_service"] = call_flexible(
                        sync_health,
                        check_repository=parse_bool(args.get("check_repository"), False),
                        check_scan_service=parse_bool(args.get("check_scan_service"), False),
                        include_traceback=include_traceback,
                    )

                if callable(published_health):
                    payload["published_service"] = call_flexible(
                        published_health,
                        check_repository=parse_bool(args.get("check_repository"), False),
                        include_traceback=include_traceback,
                    )

            health_values = [
                value
                for key, value in payload.items()
                if key not in {"api", "ok", "status"} and isinstance(value, Mapping)
            ]

            payload["ok"] = all(bool(value.get("ok", True)) for value in health_values)
            payload["status"] = "ok" if payload["ok"] else "partial"

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to build DB health response.",
                include_traceback=include_traceback,
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/scan")
    def library_scan_route():
        """
        Dateibasierter Scan.

        Diese Route schreibt nicht in die DB.
        """

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        args = request_args()

        try:
            scan_response_fn = module_function(
                services,
                "scan_source_response",
                "get_library_scan_response",
            )

            if not callable(scan_response_fn):
                raise RuntimeError("No scan response function available.")

            payload = call_flexible(
                scan_response_fn,
                source_root=normalize_string(args.get("source_root")),
                force_refresh=parse_bool(args.get("force_refresh"), False),
                options=scan_options_from_request(),
                include_invalid=parse_bool(args.get("include_invalid"), True),
                include_raw_documents=parse_bool(args.get("include_raw_documents"), True),
            )

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Library scan failed.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.post(f"{LIBRARY_API_PREFIX}/sync")
    def library_sync_route():
        """
        Filesystem → DB Sync.

        Diese Route ist die erste persistierende Library-Route.
        """

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        data = merged_request_data()
        include_traceback = parse_bool(data.get("traceback"), False)

        try:
            sync_fn = module_function(
                services,
                "sync_library_to_database_response",
                "sync_library_to_db",
                "sync_library_to_database",
            )

            if not callable(sync_fn):
                raise RuntimeError("No DB sync function available.")

            result = call_flexible(
                sync_fn,
                source_root=normalize_string(data.get("source_root")),
                force_refresh=parse_bool(data.get("force_refresh"), True),
                triggered_by=first_non_empty(data.get("triggered_by"), get_client_identifier()),
                publish_valid_only=parse_bool(data.get("publish_valid_only"), True),
                mark_missing_deleted=parse_bool(data.get("mark_missing_deleted"), False),
                include_raw_documents=parse_bool(data.get("include_raw_documents"), True),
                scan_options=scan_options_from_request(),
            )

            return json_response(sync_response_payload(result))

        except Exception as exc:
            return error_response(
                exc,
                message="Library DB sync failed.",
                include_traceback=include_traceback,
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/sync-runs")
    def library_sync_runs_route():
        """Liste bisheriger Sync-/ScanRuns aus der DB."""

        repositories, error = get_repositories_or_error()
        if error is not None:
            return error_response(error, message="Library repositories are unavailable.")

        args = request_args()

        try:
            repo_getter = module_function(
                repositories,
                "get_creative_library_repository",
                "get_default_creative_library_repository",
                "create_creative_library_repository",
            )

            if not callable(repo_getter):
                raise RuntimeError("No creative library repository factory available.")

            repository = repo_getter()
            list_fn = getattr(repository, "list_scan_runs", None)

            if not callable(list_fn):
                return json_response(
                    {
                        "ok": False,
                        "status": "not_implemented",
                        "message": "Repository does not expose list_scan_runs(...).",
                        "items": [],
                    },
                    status_code=501,
                )

            rows = call_flexible(
                list_fn,
                limit=parse_int(args.get("limit"), 50, minimum=1, maximum=500),
                offset=parse_int(args.get("offset"), 0, minimum=0),
                status=normalize_string(args.get("status")),
            )

            items = [to_mapping(row) for row in rows or []]

            return json_response(
                {
                    "ok": True,
                    "status": "ok",
                    "count": len(items),
                    "items": items,
                    "pagination": {
                        "limit": parse_int(args.get("limit"), 50, minimum=1, maximum=500),
                        "offset": parse_int(args.get("offset"), 0, minimum=0),
                    },
                }
            )

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to list sync runs.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/sync-runs/<path:run_id>")
    def library_sync_run_detail_route(run_id: str):
        """Detail eines Sync-/ScanRuns."""

        repositories, error = get_repositories_or_error()
        if error is not None:
            return error_response(error, message="Library repositories are unavailable.")

        args = request_args()

        try:
            repo_getter = module_function(
                repositories,
                "get_creative_library_repository",
                "get_default_creative_library_repository",
                "create_creative_library_repository",
            )

            if not callable(repo_getter):
                raise RuntimeError("No creative library repository factory available.")

            repository = repo_getter()
            get_fn = getattr(repository, "get_scan_run", None)

            if not callable(get_fn):
                return json_response(
                    {
                        "ok": False,
                        "status": "not_implemented",
                        "message": "Repository does not expose get_scan_run(...).",
                        "run_id": run_id,
                    },
                    status_code=501,
                )

            scan_run = get_fn(run_id)

            if scan_run is None:
                return not_found_response(run_id, message="Sync run not found.")

            return json_response(
                {
                    "ok": True,
                    "status": "ok",
                    "run_id": run_id,
                    "item": to_mapping(scan_run),
                }
            )

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to load sync run.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/publication-status")
    def library_publication_status_route():
        """Kompakter DB-Publication-Status."""

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        try:
            fn = module_function(
                services,
                "publication_status_response",
                "get_publication_status",
            )

            if not callable(fn):
                raise RuntimeError("No publication status function available.")

            return json_response(fn())

        except Exception as exc:
            return error_response(exc, message="Failed to load publication status.")


    @api_bp.get(f"{LIBRARY_API_PREFIX}/blocks")
    def library_blocks_route():
        """Blocks-Liste. Standard: DB. Debug: ?source=filesystem."""

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        args = request_args()
        source = current_read_source()

        try:
            filters = library_filter_kwargs()
            pagination = pagination_kwargs()
            includes = include_kwargs()

            if source == FILESYSTEM_READ_SOURCE:
                fn = module_function(
                    services,
                    "list_blocks_response",
                    "list_library_blocks_response",
                )

                if not callable(fn):
                    raise RuntimeError("No filesystem blocks response function available.")

                payload = call_flexible(
                    fn,
                    source_root=normalize_string(args.get("source_root")),
                    options=None,
                    **filters,
                    **pagination,
                    force_refresh=includes["force_refresh"],
                )

                return json_response(payload)

            fn = module_function(
                services,
                "list_published_blocks_db_response",
                "published_blocks_response",
                "list_published_blocks_response",
            )

            if not callable(fn):
                raise RuntimeError("No DB published blocks response function available.")

            payload = call_flexible(
                fn,
                **filters,
                **pagination,
                include_unpublished=includes["include_unpublished"],
                include_deleted=includes["include_deleted"],
                enabled_only=includes["enabled_only"],
                include_payload=includes["include_payload"],
                include_metadata=includes["include_metadata"],
            )

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to load library blocks.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/blocks/<path:block_id>/variants")
    def library_block_variants_route(block_id: str):
        """Varianten. Standard: DB. Debug: ?source=filesystem."""

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        args = request_args()
        source = current_read_source()

        try:
            if source == FILESYSTEM_READ_SOURCE:
                fn = module_function(
                    services,
                    "block_variants_response",
                    "get_library_block_variants_response",
                )

                if not callable(fn):
                    raise RuntimeError("No filesystem variants response function available.")

                payload = call_flexible(
                    fn,
                    block_id=block_id,
                    source_root=normalize_string(args.get("source_root")),
                    options=None,
                    force_refresh=parse_bool(args.get("force_refresh"), False),
                )

                return json_response(payload)

            fn = module_function(
                services,
                "published_block_variants_db_response",
                "published_block_variants_response",
                "get_published_block_variants_response",
            )

            if not callable(fn):
                raise RuntimeError("No DB published variants response function available.")

            payload = call_block_identifier_function(
                fn,
                block_id,
                include_unpublished=parse_bool(args.get("include_unpublished"), False),
            )

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to load library block variants.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/blocks/<path:block_id>")
    def library_block_detail_route(block_id: str):
        """Block-Detail. Standard: DB. Debug: ?source=filesystem."""

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        args = request_args()
        source = current_read_source()

        try:
            includes = include_kwargs()

            if source == FILESYSTEM_READ_SOURCE:
                fn = module_function(
                    services,
                    "block_detail_response",
                    "get_library_block_detail_response",
                )

                if not callable(fn):
                    raise RuntimeError("No filesystem detail response function available.")

                payload = call_flexible(
                    fn,
                    block_id=block_id,
                    source_root=normalize_string(args.get("source_root")),
                    options=None,
                    force_refresh=includes["force_refresh"],
                    include_raw_documents=includes["include_raw_documents"],
                )

                return json_response(payload)

            fn = module_function(
                services,
                "published_block_detail_db_response",
                "published_block_detail_response",
                "get_published_block_detail_response",
            )

            if not callable(fn):
                raise RuntimeError("No DB published detail response function available.")

            payload = call_block_identifier_function(
                fn,
                block_id,
                include_unpublished=includes["include_unpublished"],
                include_raw_documents=includes["include_raw_documents"],
                include_payload=includes["include_payload"],
                include_metadata=includes["include_metadata"],
            )

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to load library block detail.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/tree")
    def library_tree_route():
        """Creative-Library-Tree. Standard: DB. Debug: ?source=filesystem."""

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        args = request_args()
        source = current_read_source()

        try:
            filters = library_filter_kwargs()
            includes = include_kwargs()

            if source == FILESYSTEM_READ_SOURCE:
                fn = module_function(
                    services,
                    "tree_response",
                    "get_library_tree_response_from_block_service",
                    "get_library_tree_response",
                )

                if not callable(fn):
                    raise RuntimeError("No filesystem tree response function available.")

                payload = call_flexible(
                    fn,
                    source_root=normalize_string(args.get("source_root")),
                    options=None,
                    force_refresh=includes["force_refresh"],
                    **filters,
                )

                return json_response(payload)

            fn = module_function(
                services,
                "published_tree_db_response",
                "published_tree_response",
                "get_published_tree_response",
            )

            if not callable(fn):
                raise RuntimeError("No DB published tree response function available.")

            payload = call_flexible(
                fn,
                include_unpublished=includes["include_unpublished"],
                include_deleted=includes["include_deleted"],
                enabled_only=includes["enabled_only"],
            )

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to load library tree.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


    @api_bp.get(f"{LIBRARY_API_PREFIX}/inventory")
    def library_inventory_route():
        """Editor-/Creative-Library-Inventar. Standard: DB."""

        services, error = get_services_or_error()
        if error is not None:
            return error_response(error, message="Library services are unavailable.")

        args = request_args()

        try:
            fn = module_function(
                services,
                "published_inventory_db_response",
                "published_inventory_response",
                "get_inventory_response",
            )

            if not callable(fn):
                raise RuntimeError("No DB inventory response function available.")

            payload = call_flexible(
                fn,
                include_inactive=parse_bool(args.get("include_inactive"), False),
                fallback_from_published_families=parse_bool(args.get("fallback"), True),
                slot_limit=parse_int(
                    args.get("slot_limit"),
                    parse_int(args.get("limit"), 512),
                    minimum=0,
                    maximum=512,
                ),
                include_payload=parse_bool(args.get("include_payload"), False),
                include_metadata=parse_bool(args.get("include_metadata"), False),
                include_assets=parse_bool(args.get("include_assets"), True),
            )

            return json_response(payload)

        except Exception as exc:
            return error_response(
                exc,
                message="Failed to load library inventory.",
                include_traceback=parse_bool(args.get("traceback"), False),
            )


else:  # pragma: no cover - Flask not available
    api_bp = None


# ---------------------------------------------------------------------------
# Registration / Health helpers
# ---------------------------------------------------------------------------

def register_api_routes(app: Any, *, url_prefix: Optional[str] = None) -> bool:
    """
    Registriert den API-Blueprint an einer Flask-App.

    Standard:
        app.register_blueprint(api_bp)

    Da die Route-Pfade in diesem Modul bereits den vollständigen Prefix
    enthalten, sollte url_prefix normalerweise None bleiben.
    """

    if api_bp is None:
        return False

    if url_prefix:
        app.register_blueprint(api_bp, url_prefix=url_prefix)
    else:
        app.register_blueprint(api_bp)

    return True


def get_api_routes_health() -> dict[str, Any]:
    """Öffentlicher Health-Helper für routes/__init__.py oder Tests."""

    return get_api_routes_health_payload()


def clear_api_route_import_cache() -> dict[str, Any]:
    """Leert lokale Import-Caches der Route-Datei."""

    cached = sorted(_MODULE_IMPORT_CACHE.keys())
    errors = sorted(_MODULE_IMPORT_ERRORS.keys())

    _MODULE_IMPORT_CACHE.clear()
    _MODULE_IMPORT_ERRORS.clear()

    return {
        "ok": True,
        "cleared_modules": cached,
        "cleared_import_errors": errors,
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata
    "API_ROUTES_NAME",
    "API_ROUTES_COMPONENT",
    "API_ROUTES_VERSION",
    "API_ROUTES_STAGE",
    "LIBRARY_API_PREFIX",
    "DEFAULT_READ_SOURCE",
    "FILESYSTEM_READ_SOURCE",
    "DB_READ_SOURCE",
    "SUPPORTED_READ_SOURCES",

    # Blueprint
    "api_bp",
    "register_api_routes",

    # Generic helpers
    "utcnow",
    "iso_now",
    "exception_to_dict",
    "dataclass_shallow_dict",
    "get_attr_or_key",
    "object_columns_to_mapping",
    "json_safe",
    "to_mapping",
    "first_non_empty",
    "normalize_string",
    "normalize_read_source",
    "parse_bool",
    "parse_int",
    "request_args",
    "request_json",
    "merged_request_data",
    "get_client_identifier",
    "response_status_from_payload",
    "json_response",
    "ok_response",
    "error_response",
    "not_found_response",

    # Imports/helpers
    "safe_import_first",
    "import_library_package",
    "import_library_services",
    "import_library_repositories",
    "import_sql_repositories",
    "call_flexible",
    "call_block_identifier_function",
    "module_function",

    # Query builders
    "library_filter_kwargs",
    "pagination_kwargs",
    "include_kwargs",
    "current_read_source",
    "scan_options_from_request",

    # Sync response
    "sync_response_payload",
    "compact_candidate",
    "compact_issue",
    "compact_run",
    "compact_stats",

    # Health/cache
    "get_api_routes_health_payload",
    "get_api_routes_health",
    "clear_api_route_import_cache",
]