# services/vectoplan-library/src/library/services/library_scan_service.py
"""
Library Scan Service für die VECTOPLAN Creative-Library-Schicht.

Diese Datei orchestriert den vollständigen Backend-Scan der dateibasierten
Creative Library.

Ziel:

    src/library/source/
      -> Package Discovery
      -> Package Reader
      -> Library Validation
      -> Fingerprint
      -> LibraryItem Read-Models
      -> LibraryIndex
      -> API-taugliches Scan-Ergebnis
      -> optional Sync-Payload-Preview ohne DB-Schreibzugriff

Diese Datei ist die zentrale Backend-Service-Schicht für:

    GET /api/v1/vplib/library/scan
    GET /api/v1/vplib/library/blocks
    GET /api/v1/vplib/library/tree

Wichtige Grenzen:

- keine Flask-Abhängigkeit
- keine Datenbank
- kein Kopieren nach `creative_library`
- kein Schreiben ins Dateisystem
- kein UI
- kein automatischer Scan beim Import

Diese Datei liest nur, validiert, baut Read-Models und gibt strukturierte
Ergebnisse zurück.

Taxonomie-Regel:

    Backend-Taxonomie ist kanonisch für:
    - Source-Pfad-Tiefe
    - Domain/Reiter
    - Kategorie
    - Subkategorie
    - Labels
    - Tree-Sortierung
    - Create-/Library-Konsistenz

Version 1.0.0:

- Alle optionalen Backend-Module werden lazy geladen.
- Optionen werden aus Mapping/Dataclass/Object robust normalisiert.
- Keine DB-Abhängigkeit.
- Keine Schreiboperation.
- Cache-Key berücksichtigt Source-Root, Taxonomie-Version und relevante Optionen.
- Blocks-/Tree-Responses bleiben rückwärtskompatibel.
- Sync-Payload-Preview kann aus Scan-Ergebnissen erzeugt werden, schreibt aber nicht.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import time
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Final, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_SCAN_SERVICE_VERSION: Final[str] = "1.0.0"
LIBRARY_SCAN_SERVICE_COMPONENT: Final[str] = "library-scan-service"

DEFAULT_SCAN_SERVICE_STATUS: Final[str] = "unknown"

SCAN_SERVICE_STATUS_VALUES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "healthy",
    "empty",
    "partial",
    "invalid",
    "error",
    "unavailable",
)

DEFAULT_CACHE_KEY: Final[str] = "default"
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 5
MAX_CACHE_TTL_SECONDS: Final[int] = 86400

DEFAULT_LIMIT: Final[int] = 500
MAX_LIMIT: Final[int] = 5000

SOURCE_ROOT_ENV_NAMES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SOURCE_ROOT",
    "VPLIB_CREATE_SOURCE_ROOT",
    "LIBRARY_SOURCE_ROOT",
)

VPLIB_UID_KEYS: Final[tuple[str, ...]] = (
    "vplib_uid",
    "vplibUid",
    "vplib_uid_v1",
)

SETTINGS_MODULE_NAMES: Final[tuple[str, ...]] = (
    "config.library_settings",
    "src.config.library_settings",
    "vectoplan_library.config.library_settings",
    "vectoplan_library.src.config.library_settings",
)

DISCOVERY_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.scanner.package_discovery",
    "src.library.scanner.package_discovery",
    "vectoplan_library.library.scanner.package_discovery",
    "vectoplan_library.src.library.scanner.package_discovery",
)

READER_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.scanner.package_reader",
    "src.library.scanner.package_reader",
    "vectoplan_library.library.scanner.package_reader",
    "vectoplan_library.src.library.scanner.package_reader",
)

FINGERPRINT_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.scanner.package_fingerprint",
    "src.library.scanner.package_fingerprint",
    "vectoplan_library.library.scanner.package_fingerprint",
    "vectoplan_library.src.library.scanner.package_fingerprint",
)

VALIDATOR_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.validation.library_package_validator",
    "src.library.validation.library_package_validator",
    "vectoplan_library.library.validation.library_package_validator",
    "vectoplan_library.src.library.validation.library_package_validator",
)

SUMMARY_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.read_models.block_summary_builder",
    "src.library.read_models.block_summary_builder",
    "vectoplan_library.library.read_models.block_summary_builder",
    "vectoplan_library.src.library.read_models.block_summary_builder",
)

INDEX_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.read_models.library_index_builder",
    "src.library.read_models.library_index_builder",
    "vectoplan_library.library.read_models.library_index_builder",
    "vectoplan_library.src.library.read_models.library_index_builder",
)

DOMAIN_SCAN_RESULT_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.domain.scan_result",
    "src.library.domain.scan_result",
    "vectoplan_library.library.domain.scan_result",
    "vectoplan_library.src.library.domain.scan_result",
)

TAXONOMY_MODULE_NAMES: Final[tuple[str, ...]] = (
    "library.taxonomy",
    "src.library.taxonomy",
    "vectoplan_library.library.taxonomy",
    "vectoplan_library.src.library.taxonomy",
)


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

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")

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

        to_summary_dict = getattr(value, "to_summary_dict", None)
        if callable(to_summary_dict):
            return json_safe(to_summary_dict())

        if hasattr(value, "isoformat") and callable(value.isoformat):
            try:
                return value.isoformat()
            except Exception:
                return str(value)

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def safe_str(value: Any, *, default: str = "") -> str:
    """Robuste String-Konvertierung."""
    try:
        if value is None:
            return default

        if isinstance(value, bytes):
            text = value.decode("utf-8", errors="replace").replace("\x00", "").strip()
        else:
            text = str(value).replace("\x00", "").strip()

        return text if text else default

    except Exception:
        return default


def safe_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Konvertierung."""
    try:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

        text = safe_str(value, default="").lower()

        if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "enable", "active"}:
            return True

        if text in {"0", "false", "no", "n", "nein", "off", "disabled", "disable", "inactive"}:
            return False

        return default

    except Exception:
        return default


def safe_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Robuste Integer-Konvertierung mit optionaler Unter- und Obergrenze."""
    try:
        if value is None:
            number = int(default)
        elif isinstance(value, bool):
            number = int(value)
        elif isinstance(value, int):
            number = value
        elif isinstance(value, float):
            number = int(value)
        else:
            text = str(value).strip()

            if not text:
                number = int(default)
            else:
                try:
                    number = int(text)
                except Exception:
                    number = int(float(text))
    except Exception:
        try:
            number = int(default)
        except Exception:
            number = 0

    try:
        min_value = int(minimum) if minimum is not None else None
        max_value = int(maximum) if maximum is not None else None

        if min_value is not None and max_value is not None and min_value > max_value:
            min_value, max_value = max_value, min_value

        if min_value is not None:
            number = max(min_value, number)

        if max_value is not None:
            number = min(max_value, number)

        return int(number)

    except Exception:
        try:
            return int(default)
        except Exception:
            return 0


def safe_path(value: Any) -> Path | None:
    """Wandelt einen Wert defensiv in Path um."""
    try:
        if value is None:
            return None

        if isinstance(value, Path):
            return value.expanduser()

        text = safe_str(value, default="")

        if not text:
            return None

        return Path(text).expanduser()

    except Exception:
        return None


def safe_path_str(value: Any) -> str | None:
    """Wandelt Pfade defensiv in Strings."""
    try:
        path = safe_path(value)

        if path is not None:
            return str(path)

        text = safe_str(value, default="")
        return text or None

    except Exception:
        return None


def safe_resolve(path: Path) -> Path:
    """Best-effort Path.resolve()."""
    try:
        return path.resolve()
    except Exception:
        try:
            return path.absolute()
        except Exception:
            return path


def ensure_mapping(value: Any) -> dict[str, Any]:
    """Normalisiert Mapping-artige Werte zu dict."""
    try:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if is_dataclass(value):
            return asdict(value)

        to_dict = getattr(value, "to_dict", None)

        if callable(to_dict):
            try:
                raw = to_dict()
            except TypeError:
                raw = to_dict(flat=True)

            return dict(raw) if isinstance(raw, Mapping) else {}

        return {}

    except Exception:
        return {}


def tuple_of_strings(value: Any) -> tuple[str, ...]:
    """Normalisiert Werte zu tuple[str, ...]."""
    try:
        if value is None:
            return ()

        if isinstance(value, str):
            text = value.strip()
            return (text,) if text else ()

        if isinstance(value, Mapping):
            result_from_mapping: list[str] = []
            for key, item in value.items():
                if key in {"message", "error", "detail"}:
                    text = safe_str(item, default="")
                    if text:
                        result_from_mapping.append(text)
            return tuple(result_from_mapping)

        if isinstance(value, Iterable):
            result: list[str] = []

            for item in value:
                text = safe_str(item, default="")
                if text:
                    result.append(text)

            return tuple(result)

        text = safe_str(value, default="")
        return (text,) if text else ()

    except Exception:
        return ()


def normalize_service_status(value: Any) -> str:
    """Normalisiert Service-Status."""
    try:
        text = safe_str(value, default=DEFAULT_SCAN_SERVICE_STATUS).lower()

        if text in SCAN_SERVICE_STATUS_VALUES:
            return text

        return DEFAULT_SCAN_SERVICE_STATUS

    except Exception:
        return DEFAULT_SCAN_SERVICE_STATUS


def normalize_stable_id(value: Any, *, fallback: str | None = None) -> str:
    """Lokale stabile ID-Normalisierung für Fallbacks."""
    try:
        text = safe_str(value, default="").lower()
        text = text.replace("/", ".").replace("\\", ".").replace(" ", "_")
        text = "".join(ch for ch in text if ch.isalnum() or ch in "._:-")
        text = text.strip("._:-")

        if text:
            return text

        if fallback is not None:
            fallback_text = safe_str(fallback, default="").lower()
            fallback_text = fallback_text.replace("/", ".").replace("\\", ".").replace(" ", "_")
            fallback_text = "".join(ch for ch in fallback_text if ch.isalnum() or ch in "._:-")
            return fallback_text.strip("._:-")

        return ""

    except Exception:
        return ""


def humanize_identifier(value: Any, *, fallback: str = "Unnamed Library Item") -> str:
    """Erzeugt lesbares Label aus ID."""
    try:
        text = safe_str(value, default="")

        if not text:
            return fallback

        last = text.replace(":", ".").replace("/", ".").replace("\\", ".").split(".")[-1]
        last = last.replace("_", " ").replace("-", " ").strip()

        return " ".join(part.capitalize() for part in last.split()) if last else fallback

    except Exception:
        return fallback


def get_item_attr(item: Any, key: str, *, default: Any = None) -> Any:
    """Liest Mapping-Key oder Attribut."""
    try:
        if item is None:
            return default

        if isinstance(item, Mapping):
            return item.get(key, default)

        return getattr(item, key, default)

    except Exception:
        return default


def nested_mapping_value(mapping: Any, *keys: str, default: Any = None) -> Any:
    current = mapping

    for key in keys:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
        if current is None:
            return default

    return current


def get_item_id(item: Any) -> str | None:
    """Extrahiert stabile Item-ID."""
    try:
        value = (
            get_item_attr(item, "id")
            or get_item_attr(item, "vplib_uid")
            or get_item_attr(item, "family_id")
            or get_item_attr(item, "package_id")
            or get_item_attr(item, "slug")
        )
        normalized = normalize_stable_id(value)

        return normalized or None

    except Exception:
        return None


def get_item_status(item: Any) -> str:
    """Extrahiert Item-Status."""
    return safe_str(get_item_attr(item, "status"), default="unknown").lower()


def get_result_status(result: Any) -> str:
    """Extrahiert Status aus Result-Objekt oder Mapping."""
    return safe_str(
        get_item_attr(result, "status"),
        default="unknown",
    ).lower()


def result_is_ok(result: Any) -> bool:
    """Extrahiert ok-Flag."""
    return safe_bool(
        get_item_attr(result, "ok"),
        default=False,
    )


def result_is_valid(result: Any) -> bool:
    """Extrahiert valid-Flag."""
    return safe_bool(
        get_item_attr(result, "valid"),
        default=result_is_ok(result),
    )


def monotonic_ms_safe() -> int:
    """Monotonic-Zeit in Millisekunden."""
    try:
        return int(time.monotonic() * 1000)
    except Exception:
        return 0


def monotonic_ms() -> int:
    """Alias für Domain-Fallback-Kompatibilität."""
    return monotonic_ms_safe()


def calculate_duration_ms(started_monotonic_ms: int | None) -> int:
    """Berechnet Dauer in Millisekunden."""
    try:
        if started_monotonic_ms is None:
            return 0

        current = monotonic_ms_safe()

        return max(0, current - int(started_monotonic_ms))

    except Exception:
        return 0


def hash_json_safe(value: Any) -> str:
    """Hash für Cache-Key/Debug."""
    try:
        data = json.dumps(json_safe(value), sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return "unhashable"


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=128)
def _load_first_module(module_names: tuple[str, ...]) -> ModuleType:
    errors: list[str] = []

    for module_name in module_names:
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError("Could not import any module. " + " | ".join(errors))


def _try_load_first_module(module_names: Sequence[str]) -> tuple[ModuleType | None, BaseException | None]:
    try:
        return _load_first_module(tuple(module_names)), None
    except Exception as exc:
        return None, exc


def _try_get_optional_attr(module_names: Sequence[str], attr_name: str) -> tuple[Any | None, BaseException | None]:
    module, exc = _try_load_first_module(module_names)

    if module is None:
        return None, exc

    try:
        return getattr(module, attr_name), None
    except Exception as attr_exc:
        return None, attr_exc


def _call_function_flexible(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Ruft Funktion mit Signatur-Fallback auf."""
    try:
        signature = inspect.signature(func)
        supports_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if supports_kwargs:
            return func(*args, **kwargs)

        supported = set(signature.parameters.keys())
        filtered = {key: value for key, value in kwargs.items() if key in supported}
        return func(*args, **filtered)
    except TypeError:
        if kwargs:
            try:
                return func(*args)
            except TypeError:
                pass
        return func(*args)
    except Exception:
        raise


def _instantiate_flexible(class_or_factory: Any, *args: Any, **kwargs: Any) -> Any:
    """Instanziiert Optionsklassen mit Signatur-Fallback."""
    if class_or_factory is None:
        return None

    try:
        return _call_function_flexible(class_or_factory, *args, **kwargs)
    except Exception:
        try:
            return class_or_factory()
        except Exception:
            return None


def get_optional_import_status() -> dict[str, Any]:
    """Status aller optionalen Lazy-Import-Gruppen."""
    return {
        "settings": _module_status(SETTINGS_MODULE_NAMES),
        "discovery": _module_status(DISCOVERY_MODULE_NAMES),
        "reader": _module_status(READER_MODULE_NAMES),
        "fingerprint": _module_status(FINGERPRINT_MODULE_NAMES),
        "validation": _module_status(VALIDATOR_MODULE_NAMES),
        "summary": _module_status(SUMMARY_MODULE_NAMES),
        "index": _module_status(INDEX_MODULE_NAMES),
        "domain_scan_result": _module_status(DOMAIN_SCAN_RESULT_MODULE_NAMES),
        "taxonomy": _module_status(TAXONOMY_MODULE_NAMES),
    }


def _module_status(module_names: Sequence[str]) -> dict[str, Any]:
    module, exc = _try_load_first_module(module_names)
    if module is not None:
        return {
            "ok": True,
            "module": getattr(module, "__name__", ""),
        }

    return {
        "ok": False,
        "error": exception_to_dict(exc),
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_default_source_root() -> Path:
    """Ermittelt den Standard-Source-Root ohne config.library_settings."""
    for env_name in SOURCE_ROOT_ENV_NAMES:
        env_value = safe_str(os.getenv(env_name), default="")
        if env_value:
            env_path = safe_path(env_value)
            if env_path is not None:
                return safe_resolve(env_path)

    try:
        return safe_resolve(Path(__file__).resolve().parents[1] / "source")
    except Exception:
        return safe_resolve(Path.cwd() / "src" / "library" / "source")


def get_source_root(*, refresh: bool = False) -> Path:
    func, _exc = _try_get_optional_attr(SETTINGS_MODULE_NAMES, "get_source_root")
    if callable(func):
        try:
            return safe_resolve(Path(func(refresh=refresh)))
        except TypeError:
            try:
                return safe_resolve(Path(func()))
            except Exception:
                pass
        except Exception:
            pass

    return get_default_source_root()


def get_library_settings(*, refresh: bool = False) -> Any:
    func, _exc = _try_get_optional_attr(SETTINGS_MODULE_NAMES, "get_library_settings")
    if callable(func):
        try:
            return func(refresh=refresh)
        except TypeError:
            try:
                return func()
            except Exception:
                pass
    return None


def get_library_scan_options(*, refresh: bool = False) -> Any:
    func, _exc = _try_get_optional_attr(SETTINGS_MODULE_NAMES, "get_library_scan_options")
    if callable(func):
        try:
            return func(refresh=refresh)
        except TypeError:
            try:
                return func()
            except Exception:
                pass
    return None


def get_library_read_options(*, refresh: bool = False) -> Any:
    func, _exc = _try_get_optional_attr(SETTINGS_MODULE_NAMES, "get_library_read_options")
    if callable(func):
        try:
            return func(refresh=refresh)
        except TypeError:
            try:
                return func()
            except Exception:
                pass
    return None


def get_library_cache_options(*, refresh: bool = False) -> Any:
    func, _exc = _try_get_optional_attr(SETTINGS_MODULE_NAMES, "get_library_cache_options")
    if callable(func):
        try:
            return func(refresh=refresh)
        except TypeError:
            try:
                return func()
            except Exception:
                pass
    return None


def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
    func, _exc = _try_get_optional_attr(SETTINGS_MODULE_NAMES, "get_settings_summary")
    if callable(func):
        try:
            result = func(refresh=refresh)
            if isinstance(result, Mapping):
                return dict(result)
        except TypeError:
            try:
                result = func()
                if isinstance(result, Mapping):
                    return dict(result)
            except Exception:
                pass
        except Exception:
            pass

    source_root = get_default_source_root()

    return {
        "ok": False,
        "fallback_active": True,
        "source_root": str(source_root),
        "refresh_requested": bool(refresh),
    }


# ---------------------------------------------------------------------------
# Taxonomy helpers
# ---------------------------------------------------------------------------

def taxonomy_available() -> bool:
    factory, _exc = _try_get_optional_attr(TAXONOMY_MODULE_NAMES, "get_default_taxonomy_service")
    return callable(factory)


def get_taxonomy_service_safe() -> Any | None:
    factory, _exc = _try_get_optional_attr(TAXONOMY_MODULE_NAMES, "get_default_taxonomy_service")
    if not callable(factory):
        return None

    try:
        return factory()
    except Exception:
        return None


def get_taxonomy_payload_safe(
    *,
    force_reload: bool = False,
    include_inactive: bool = False,
) -> dict[str, Any]:
    service = get_taxonomy_service_safe()

    if service is None:
        return {
            "ok": False,
            "healthy": False,
            "available": False,
            "taxonomy_version": None,
        }

    try:
        method = getattr(service, "get_taxonomy_payload", None)
        if callable(method):
            return ensure_mapping(
                _call_function_flexible(
                    method,
                    include_inactive=include_inactive,
                    include_tree=True,
                    include_options=True,
                    include_lookup=True,
                    force_reload=force_reload,
                )
            )

        method = getattr(service, "get_create_options_payload", None)
        if callable(method):
            return ensure_mapping(method())

        return {
            "ok": True,
            "healthy": True,
            "available": True,
            "taxonomy_version": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "available": True,
            "taxonomy_version": None,
            "error": exception_to_dict(exc),
        }


def get_taxonomy_health_safe(
    *,
    force_reload: bool = False,
    include_registry_state: bool = False,
) -> dict[str, Any]:
    service = get_taxonomy_service_safe()

    if service is None:
        return {
            "ok": False,
            "healthy": False,
            "available": False,
        }

    try:
        method = getattr(service, "health", None)
        if callable(method):
            return ensure_mapping(
                _call_function_flexible(
                    method,
                    force_reload=force_reload,
                    include_registry_state=include_registry_state,
                )
            )

        method = getattr(service, "get_health", None)
        if callable(method):
            return ensure_mapping(method())

        return {
            "ok": True,
            "healthy": True,
            "available": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "available": True,
            "error": exception_to_dict(exc),
        }


def extract_taxonomy_version(payload: Mapping[str, Any] | None) -> str | None:
    data = ensure_mapping(payload)
    value = data.get("taxonomy_version")

    if not value:
        value = get_item_attr(get_item_attr(data, "tree", default={}), "taxonomy_version")

    if not value:
        value = nested_mapping_value(data, "payload", "taxonomy_version")

    text = safe_str(value, default="")
    return text or None


# ---------------------------------------------------------------------------
# Options / cache
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryScanServiceOptions:
    """Optionen für den Library Scan Service."""

    include_invalid: bool = True
    enabled_only: bool = False
    use_cache: bool = False
    cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS
    refresh_settings: bool = False
    include_raw_pipeline: bool = False
    include_index: bool = True
    include_scan_result: bool = True
    include_discovery_result: bool = True
    include_read_results: bool = False
    include_validation_results: bool = False
    include_fingerprint_results: bool = False
    strict_errors: bool = False

    validate_taxonomy: bool = True
    require_taxonomy: bool = True
    use_taxonomy_labels: bool = True
    include_empty_taxonomy_nodes: bool = False
    include_inactive_taxonomy_nodes: bool = False
    include_taxonomy_payload: bool = False
    force_taxonomy_reload: bool = False

    limit: int = DEFAULT_LIMIT
    offset: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "include_invalid", safe_bool(self.include_invalid, default=True))
        object.__setattr__(self, "enabled_only", safe_bool(self.enabled_only, default=False))
        object.__setattr__(self, "use_cache", safe_bool(self.use_cache, default=False))
        object.__setattr__(
            self,
            "cache_ttl_seconds",
            safe_int(
                self.cache_ttl_seconds,
                default=DEFAULT_CACHE_TTL_SECONDS,
                minimum=0,
                maximum=MAX_CACHE_TTL_SECONDS,
            ),
        )
        object.__setattr__(self, "refresh_settings", safe_bool(self.refresh_settings, default=False))
        object.__setattr__(self, "include_raw_pipeline", safe_bool(self.include_raw_pipeline, default=False))
        object.__setattr__(self, "include_index", safe_bool(self.include_index, default=True))
        object.__setattr__(self, "include_scan_result", safe_bool(self.include_scan_result, default=True))
        object.__setattr__(self, "include_discovery_result", safe_bool(self.include_discovery_result, default=True))
        object.__setattr__(self, "include_read_results", safe_bool(self.include_read_results, default=False))
        object.__setattr__(self, "include_validation_results", safe_bool(self.include_validation_results, default=False))
        object.__setattr__(self, "include_fingerprint_results", safe_bool(self.include_fingerprint_results, default=False))
        object.__setattr__(self, "strict_errors", safe_bool(self.strict_errors, default=False))
        object.__setattr__(self, "validate_taxonomy", safe_bool(self.validate_taxonomy, default=True))
        object.__setattr__(self, "require_taxonomy", safe_bool(self.require_taxonomy, default=True))
        object.__setattr__(self, "use_taxonomy_labels", safe_bool(self.use_taxonomy_labels, default=True))
        object.__setattr__(self, "include_empty_taxonomy_nodes", safe_bool(self.include_empty_taxonomy_nodes, default=False))
        object.__setattr__(self, "include_inactive_taxonomy_nodes", safe_bool(self.include_inactive_taxonomy_nodes, default=False))
        object.__setattr__(self, "include_taxonomy_payload", safe_bool(self.include_taxonomy_payload, default=False))
        object.__setattr__(self, "force_taxonomy_reload", safe_bool(self.force_taxonomy_reload, default=False))
        object.__setattr__(self, "limit", safe_int(self.limit, default=DEFAULT_LIMIT, minimum=1, maximum=MAX_LIMIT))
        object.__setattr__(self, "offset", safe_int(self.offset, default=0, minimum=0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_invalid": self.include_invalid,
            "enabled_only": self.enabled_only,
            "use_cache": self.use_cache,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "refresh_settings": self.refresh_settings,
            "include_raw_pipeline": self.include_raw_pipeline,
            "include_index": self.include_index,
            "include_scan_result": self.include_scan_result,
            "include_discovery_result": self.include_discovery_result,
            "include_read_results": self.include_read_results,
            "include_validation_results": self.include_validation_results,
            "include_fingerprint_results": self.include_fingerprint_results,
            "strict_errors": self.strict_errors,
            "validate_taxonomy": self.validate_taxonomy,
            "require_taxonomy": self.require_taxonomy,
            "use_taxonomy_labels": self.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": self.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": self.include_inactive_taxonomy_nodes,
            "include_taxonomy_payload": self.include_taxonomy_payload,
            "force_taxonomy_reload": self.force_taxonomy_reload,
            "limit": self.limit,
            "offset": self.offset,
        }

    @classmethod
    def from_settings(cls, *, refresh: bool = False) -> "LibraryScanServiceOptions":
        """Baut Service-Optionen aus Settings, wenn verfügbar."""
        try:
            cache_options = get_library_cache_options(refresh=refresh)
            read_options = get_library_read_options(refresh=refresh)

            return cls(
                include_invalid=safe_bool(
                    get_item_attr(read_options, "list_include_invalid"),
                    default=False,
                ),
                enabled_only=False,
                use_cache=safe_bool(
                    get_item_attr(cache_options, "enabled"),
                    default=False,
                ),
                cache_ttl_seconds=safe_int(
                    get_item_attr(cache_options, "ttl_seconds"),
                    default=DEFAULT_CACHE_TTL_SECONDS,
                    minimum=0,
                    maximum=MAX_CACHE_TTL_SECONDS,
                ),
                refresh_settings=refresh,
                validate_taxonomy=safe_bool(
                    get_item_attr(read_options, "validate_taxonomy"),
                    default=True,
                ),
                require_taxonomy=safe_bool(
                    get_item_attr(read_options, "require_taxonomy"),
                    default=True,
                ),
                use_taxonomy_labels=safe_bool(
                    get_item_attr(read_options, "use_taxonomy_labels"),
                    default=True,
                ),
                include_empty_taxonomy_nodes=safe_bool(
                    get_item_attr(read_options, "include_empty_taxonomy_nodes"),
                    default=False,
                ),
                include_inactive_taxonomy_nodes=safe_bool(
                    get_item_attr(read_options, "include_inactive_taxonomy_nodes"),
                    default=False,
                ),
            )

        except Exception:
            return cls(refresh_settings=refresh)


def coerce_scan_service_options(
    value: Any = None,
    *,
    refresh: bool = False,
) -> LibraryScanServiceOptions:
    """
    Normalisiert Scan-Service-Optionen.

    Der Scan-Service wird aus mehreren Pfaden aufgerufen:
    - HTTP-Routen
    - DB-Sync-Service
    - CLI-/Debug-Code
    - Tests

    Einige dieser Pfade übergeben echte LibraryScanServiceOptions, andere
    dict/Mapping-Payloads. Diese Funktion ist der zentrale Eingangsschutz.
    """
    if isinstance(value, LibraryScanServiceOptions):
        return value

    try:
        base = LibraryScanServiceOptions.from_settings(refresh=refresh)
    except Exception:
        base = LibraryScanServiceOptions(refresh_settings=refresh)

    data: dict[str, Any] = {}

    try:
        if value is None:
            return base

        if isinstance(value, Mapping):
            data = dict(value)
        elif is_dataclass(value):
            data = dict(asdict(value))
        elif hasattr(value, "to_dict") and callable(value.to_dict):
            raw = value.to_dict()
            data = dict(raw) if isinstance(raw, Mapping) else {}
        else:
            for field_name in LibraryScanServiceOptions.__dataclass_fields__:
                if hasattr(value, field_name):
                    data[field_name] = getattr(value, field_name)

    except Exception:
        return base

    if not data:
        return base

    alias_map = {
        "require_taxonomy_validation": "validate_taxonomy",
        "require_taxonomy_service": "require_taxonomy",
        "validate_taxonomy_path": "validate_taxonomy",
        "use_taxonomy": "validate_taxonomy",
        "taxonomy_required": "require_taxonomy",
        "include_read_artifacts": "include_read_results",
        "include_raw_documents": "include_read_results",
        "force_refresh": "refresh_settings",
    }

    for source_key, target_key in alias_map.items():
        if source_key in data and target_key not in data:
            data[target_key] = data[source_key]

    if safe_bool(data.get("include_read_artifacts"), default=False):
        data.setdefault("include_read_results", True)
        data.setdefault("include_validation_results", True)
        data.setdefault("include_fingerprint_results", True)

    allowed = set(LibraryScanServiceOptions.__dataclass_fields__.keys())

    try:
        merged = base.to_dict()
    except Exception:
        merged = {}

    for key, item in data.items():
        if key in allowed:
            merged[key] = item

    merged["refresh_settings"] = safe_bool(
        merged.get("refresh_settings"),
        default=refresh,
    ) or bool(refresh)

    try:
        return LibraryScanServiceOptions(**merged)
    except Exception:
        return base


@dataclass
class _CacheEntry:
    """Interner Cache-Eintrag."""

    created_at_monotonic: float
    result: "LibraryScanPipelineResult"

    def is_fresh(self, ttl_seconds: int) -> bool:
        try:
            if ttl_seconds <= 0:
                return False

            return (time.monotonic() - self.created_at_monotonic) <= ttl_seconds

        except Exception:
            return False


_SCAN_CACHE: dict[str, _CacheEntry] = {}


def clear_library_scan_cache() -> None:
    """Leert den in-memory Scan-Cache."""
    try:
        _SCAN_CACHE.clear()
    except Exception:
        pass

    try:
        clear_func, _exc = _try_get_optional_attr(SUMMARY_MODULE_NAMES, "clear_taxonomy_cache")
        if callable(clear_func):
            clear_func()
    except Exception:
        pass

    taxonomy_service = get_taxonomy_service_safe()
    if taxonomy_service is not None:
        try:
            clear_func = getattr(taxonomy_service, "clear_cache", None)
            if callable(clear_func):
                clear_func()
        except Exception:
            pass


def make_cache_key(
    source_root: Any = None,
    *,
    taxonomy_version: Any = None,
    options: LibraryScanServiceOptions | Mapping[str, Any] | None = None,
) -> str:
    """Baut Cache-Key aus Source-Root, Taxonomie-Version und relevanten Optionen."""
    root_text = safe_path_str(source_root) or DEFAULT_CACHE_KEY
    version_text = safe_str(taxonomy_version, default="noversion")
    options_payload = coerce_scan_service_options(options).to_dict() if options is not None else {}
    options_hash = hash_json_safe(
        {
            "include_invalid": options_payload.get("include_invalid"),
            "enabled_only": options_payload.get("enabled_only"),
            "validate_taxonomy": options_payload.get("validate_taxonomy"),
            "require_taxonomy": options_payload.get("require_taxonomy"),
            "use_taxonomy_labels": options_payload.get("use_taxonomy_labels"),
            "include_empty_taxonomy_nodes": options_payload.get("include_empty_taxonomy_nodes"),
            "include_inactive_taxonomy_nodes": options_payload.get("include_inactive_taxonomy_nodes"),
        }
    )[:16]
    return f"{root_text}|taxonomy:{version_text}|options:{options_hash}"


def get_cached_scan_result(
    *,
    cache_key: str,
    ttl_seconds: int,
) -> "LibraryScanPipelineResult | None":
    """Holt frischen Cache-Eintrag, falls vorhanden."""
    try:
        entry = _SCAN_CACHE.get(cache_key)

        if entry is None:
            return None

        if entry.is_fresh(ttl_seconds):
            return entry.result

        _SCAN_CACHE.pop(cache_key, None)

    except Exception:
        return None

    return None


def set_cached_scan_result(
    *,
    cache_key: str,
    result: "LibraryScanPipelineResult",
) -> None:
    """Speichert Scan-Ergebnis im in-memory Cache."""
    try:
        _SCAN_CACHE[cache_key] = _CacheEntry(
            created_at_monotonic=time.monotonic(),
            result=result,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryScanPipelineResult:
    """Vollständiges Ergebnis der Scan-Service-Pipeline."""

    ok: bool
    status: str
    source_root: str | None = None
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = field(default_factory=utc_now_iso)
    duration_ms: int = 0

    discovery_result: Any = None
    read_results: tuple[Any, ...] = field(default_factory=tuple)
    validation_results: tuple[Any, ...] = field(default_factory=tuple)
    fingerprint_results: tuple[Any, ...] = field(default_factory=tuple)
    items: tuple[Any, ...] = field(default_factory=tuple)
    index: Any = None
    scan_result: Any = None

    taxonomy_payload: dict[str, Any] = field(default_factory=dict)
    taxonomy_health: dict[str, Any] = field(default_factory=dict)

    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    options: LibraryScanServiceOptions = field(default_factory=LibraryScanServiceOptions)
    settings_summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = LIBRARY_SCAN_SERVICE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.options, LibraryScanServiceOptions):
            object.__setattr__(
                self,
                "options",
                coerce_scan_service_options(self.options),
            )

        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)
        status = normalize_service_status(self.status)

        if status == "unknown":
            if errors:
                status = "error"
            elif self.index is not None:
                index_status = get_result_status(self.index)
                if index_status in SCAN_SERVICE_STATUS_VALUES:
                    status = index_status
                else:
                    status = "ok"
            elif self.items:
                status = "ok"
            else:
                status = "empty"

        object.__setattr__(self, "ok", bool(self.ok and status not in {"error", "invalid", "unavailable"}))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "duration_ms", safe_int(self.duration_ms, default=0, minimum=0))
        object.__setattr__(self, "read_results", tuple(self.read_results or ()))
        object.__setattr__(self, "validation_results", tuple(self.validation_results or ()))
        object.__setattr__(self, "fingerprint_results", tuple(self.fingerprint_results or ()))
        object.__setattr__(self, "items", tuple(self.items or ()))
        object.__setattr__(self, "taxonomy_payload", dict(self.taxonomy_payload or {}))
        object.__setattr__(self, "taxonomy_health", dict(self.taxonomy_health or {}))
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "settings_summary", dict(self.settings_summary or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "version", safe_str(self.version, default=LIBRARY_SCAN_SERVICE_VERSION))

    @property
    def taxonomy_version(self) -> str | None:
        return extract_taxonomy_version(self.taxonomy_payload) or safe_str(
            self.taxonomy_health.get("taxonomy_version"),
            default="",
        ) or None

    @property
    def candidate_count(self) -> int:
        try:
            direct_count = get_item_attr(self.discovery_result, "candidate_count", default=None)
            if direct_count is not None:
                return safe_int(direct_count, default=0, minimum=0)

            candidates = get_item_attr(self.discovery_result, "candidates", default=())
            return len(tuple(candidates or ()))
        except Exception:
            return 0

    @property
    def canonical_candidate_count(self) -> int:
        try:
            return safe_int(get_item_attr(self.discovery_result, "canonical_count"), default=0, minimum=0)
        except Exception:
            return 0

    @property
    def legacy_candidate_count(self) -> int:
        try:
            return safe_int(get_item_attr(self.discovery_result, "legacy_count"), default=0, minimum=0)
        except Exception:
            return 0

    @property
    def read_count(self) -> int:
        return len(self.read_results)

    @property
    def validation_count(self) -> int:
        return len(self.validation_results)

    @property
    def fingerprint_count(self) -> int:
        return len(self.fingerprint_results)

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def valid_item_count(self) -> int:
        try:
            if self.index is not None:
                count = get_item_attr(self.index, "count", default=None)
                if count is not None:
                    return safe_int(count, default=0, minimum=0)

            return sum(
                1
                for item in self.items
                if get_item_status(item) in {"valid", "ok", "active"}
                or safe_bool(get_item_attr(item, "is_valid"), default=False)
            )

        except Exception:
            return 0

    @property
    def invalid_item_count(self) -> int:
        return max(0, self.item_count - self.valid_item_count)

    def to_dict(
        self,
        *,
        include_raw_pipeline: bool | None = None,
    ) -> dict[str, Any]:
        """Serialisiert das Pipeline-Ergebnis."""
        include_raw = self.options.include_raw_pipeline if include_raw_pipeline is None else include_raw_pipeline

        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "candidate_count": self.candidate_count,
            "canonical_candidate_count": self.canonical_candidate_count,
            "legacy_candidate_count": self.legacy_candidate_count,
            "read_count": self.read_count,
            "validation_count": self.validation_count,
            "fingerprint_count": self.fingerprint_count,
            "item_count": self.item_count,
            "valid_item_count": self.valid_item_count,
            "invalid_item_count": self.invalid_item_count,
            "taxonomy": {
                "available": bool(self.taxonomy_health.get("available", self.taxonomy_health.get("healthy", False))),
                "healthy": bool(self.taxonomy_health.get("healthy", self.taxonomy_payload.get("ok", False))),
                "taxonomy_version": self.taxonomy_version,
                "required": self.options.require_taxonomy,
                "validate_taxonomy": self.options.validate_taxonomy,
                "use_taxonomy_labels": self.options.use_taxonomy_labels,
                "include_empty_taxonomy_nodes": self.options.include_empty_taxonomy_nodes,
                "include_inactive_taxonomy_nodes": self.options.include_inactive_taxonomy_nodes,
                "health": json_safe(self.taxonomy_health),
            },
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "options": self.options.to_dict(),
            "settings_summary": json_safe(self.settings_summary),
            "metadata": json_safe(self.metadata),
            "version": self.version,
            "component": LIBRARY_SCAN_SERVICE_COMPONENT,
            "writes_database": False,
        }

        if self.options.include_taxonomy_payload or include_raw:
            result["taxonomy"]["payload"] = json_safe(self.taxonomy_payload)

        if self.options.include_discovery_result or include_raw:
            result["discovery_result"] = json_safe(self.discovery_result)

        if self.options.include_scan_result or include_raw:
            result["scan_result"] = json_safe(self.scan_result)

        if self.options.include_index or include_raw:
            result["index"] = json_safe(self.index)

        if self.options.include_read_results or include_raw:
            result["read_results"] = json_safe(self.read_results)

        if self.options.include_validation_results or include_raw:
            result["validation_results"] = json_safe(self.validation_results)

        if self.options.include_fingerprint_results or include_raw:
            result["fingerprint_results"] = json_safe(self.fingerprint_results)

        if include_raw:
            result["items"] = json_safe(self.items)

        return result

    def to_scan_response_dict(self) -> dict[str, Any]:
        """Antwort für GET /api/v1/vplib/library/scan."""
        result = self.to_dict(include_raw_pipeline=False)

        result["items"] = [
            item.to_summary_dict()
            if hasattr(item, "to_summary_dict") and callable(item.to_summary_dict)
            else json_safe(item)
            for item in self.items
        ]

        return result

    def to_blocks_response_dict(
        self,
        *,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        object_kind: Any = None,
        q: Any = None,
    ) -> dict[str, Any]:
        """Antwort für GET /api/v1/vplib/library/blocks."""
        response = build_blocks_response_from_index_safe(
            self.index,
            domain=domain,
            category=category,
            subcategory=subcategory,
            object_kind=object_kind,
            q=q,
        )

        if isinstance(response, Mapping):
            payload = dict(response)
            payload.setdefault("taxonomy_version", self.taxonomy_version)
            payload.setdefault(
                "taxonomy",
                {
                    "taxonomy_version": self.taxonomy_version,
                    "healthy": bool(self.taxonomy_health.get("healthy", self.taxonomy_payload.get("ok", False))),
                    "required": self.options.require_taxonomy,
                },
            )
            return payload

        return {
            "ok": False,
            "status": "error",
            "items": [],
            "count": 0,
            "errors": ["invalid blocks response from index builder"],
        }

    def to_tree_response_dict(self) -> dict[str, Any]:
        """Antwort für GET /api/v1/vplib/library/tree."""
        response = build_tree_response_from_index_safe(self.index)

        if isinstance(response, Mapping):
            payload = dict(response)
            payload.setdefault("taxonomy_version", self.taxonomy_version)
            payload.setdefault(
                "taxonomy",
                {
                    "taxonomy_version": self.taxonomy_version,
                    "healthy": bool(self.taxonomy_health.get("healthy", self.taxonomy_payload.get("ok", False))),
                    "include_empty_taxonomy_nodes": self.options.include_empty_taxonomy_nodes,
                    "include_inactive_taxonomy_nodes": self.options.include_inactive_taxonomy_nodes,
                },
            )
            return payload

        return {
            "ok": False,
            "status": "error",
            "tree": {},
            "errors": ["invalid tree response from index builder"],
        }

    def to_sync_preview_dict(self) -> dict[str, Any]:
        """Erzeugt DB-Sync-kompatible Publish-Payloads ohne zu schreiben."""
        payloads = build_sync_payloads_from_scan_result(self)

        return {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "item_count": len(payloads),
            "publish_payloads": payloads,
            "writes_database": False,
            "target_write_route": "/api/v1/vplib/library/sync",
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        source_root: Any = None,
        started_at: Any = None,
        started_monotonic_ms: int | None = None,
        options: LibraryScanServiceOptions | None = None,
        settings_summary: Mapping[str, Any] | None = None,
        taxonomy_payload: Mapping[str, Any] | None = None,
        taxonomy_health: Mapping[str, Any] | None = None,
        include_traceback: bool = False,
    ) -> "LibraryScanPipelineResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        message = safe_str(error_data.get("message") if error_data else None, default="library scan service failed")

        return cls(
            ok=False,
            status="error",
            source_root=safe_path_str(source_root),
            started_at=safe_str(started_at, default="") or utc_now_iso(),
            finished_at=utc_now_iso(),
            duration_ms=calculate_duration_ms(started_monotonic_ms),
            discovery_result=None,
            read_results=(),
            validation_results=(),
            fingerprint_results=(),
            items=(),
            index=None,
            scan_result=build_error_scan_result_safe(
                exc,
                source_root=source_root,
                started_at=started_at,
                started_monotonic_ms=started_monotonic_ms,
                include_traceback=include_traceback,
                settings=settings_summary or {},
            ),
            taxonomy_payload=dict(taxonomy_payload or {}),
            taxonomy_health=dict(taxonomy_health or {}),
            warnings=(),
            errors=(message,),
            options=options or LibraryScanServiceOptions(),
            settings_summary=dict(settings_summary or {}),
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# Internal pipeline helpers
# ---------------------------------------------------------------------------

def resolve_scan_source_root(
    source_root: Any = None,
    *,
    refresh_settings: bool = False,
) -> Path:
    """Ermittelt den Source-Root für den Scan."""
    if source_root is not None:
        path = safe_path(source_root)

        if path is None:
            raise ValueError("source_root could not be resolved")

        return safe_resolve(path)

    for env_name in SOURCE_ROOT_ENV_NAMES:
        env_value = safe_str(os.getenv(env_name), default="")
        if env_value:
            env_path = safe_path(env_value)
            if env_path is not None:
                return safe_resolve(env_path)

    return safe_resolve(get_source_root(refresh=refresh_settings))


def object_to_options_dict(value: Any) -> dict[str, Any]:
    """Options-Objekte robust in dict wandeln."""
    if value is None:
        return {}

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            data = value.to_dict()
            return dict(data) if isinstance(data, Mapping) else {}
        except Exception:
            return {}

    if isinstance(value, Mapping):
        return dict(value)

    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:
            return {}

    return {}


def rebuild_options_object(cls: Any, data: Mapping[str, Any]) -> Any:
    """Baut Options-Objekte defensiv aus dict."""
    try:
        if cls is None:
            return dict(data)
        return cls(**dict(data))
    except Exception:
        try:
            return cls()
        except Exception:
            return dict(data)


def make_discovery_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Discovery-Optionen defensiv und propagiert Taxonomieoptionen."""
    resolved_options = service_options or LibraryScanServiceOptions()
    cls, _exc = _try_get_optional_attr(DISCOVERY_MODULE_NAMES, "PackageDiscoveryOptions")

    try:
        if cls is not None and hasattr(cls, "from_settings"):
            try:
                base = cls.from_settings(get_library_scan_options())
            except TypeError:
                base = cls.from_settings()
        elif cls is not None:
            base = cls()
        else:
            base = {}

        data = object_to_options_dict(base)
        data["validate_taxonomy_path"] = resolved_options.validate_taxonomy
        data.setdefault("include_legacy_source_layout", True)
        data.setdefault("read_minimal_metadata", True)

        return rebuild_options_object(cls, data)

    except Exception:
        return _instantiate_flexible(cls) if cls is not None else None


def make_reader_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Reader-Optionen defensiv."""
    cls, _exc = _try_get_optional_attr(READER_MODULE_NAMES, "PackageReaderOptions")

    try:
        if cls is not None and hasattr(cls, "from_settings"):
            try:
                return cls.from_settings(get_library_scan_options())
            except TypeError:
                return cls.from_settings()

        return cls() if cls is not None else None

    except Exception:
        return _instantiate_flexible(cls) if cls is not None else None


def make_fingerprint_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Fingerprint-Optionen defensiv."""
    cls, _exc = _try_get_optional_attr(FINGERPRINT_MODULE_NAMES, "PackageFingerprintOptions")
    return _instantiate_flexible(cls) if cls is not None else None


def make_validation_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Validation-Optionen defensiv und propagiert Taxonomiepflicht."""
    resolved_options = service_options or LibraryScanServiceOptions()
    cls, _exc = _try_get_optional_attr(VALIDATOR_MODULE_NAMES, "LibraryPackageValidatorOptions")

    try:
        base = cls() if cls is not None else {}
        data = object_to_options_dict(base)

        data["require_taxonomy"] = resolved_options.require_taxonomy
        data["require_classification"] = resolved_options.validate_taxonomy
        data["strict_taxonomy"] = resolved_options.require_taxonomy
        data["allow_legacy_source_depth"] = True
        data["require_taxonomy_validation"] = resolved_options.validate_taxonomy
        data["require_taxonomy_service"] = resolved_options.require_taxonomy
        data.setdefault("allow_legacy_source_path", True)
        data.setdefault("require_manifest_taxonomy_match", True)
        data.setdefault("require_canonical_family_id", True)

        return rebuild_options_object(cls, data)

    except Exception:
        return _instantiate_flexible(cls) if cls is not None else None


def make_summary_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Summary-Builder-Optionen defensiv und propagiert Taxonomie-Labeling."""
    resolved_options = service_options or LibraryScanServiceOptions()
    cls, _exc = _try_get_optional_attr(SUMMARY_MODULE_NAMES, "BlockSummaryBuilderOptions")

    if cls is None:
        return {
            "include_invalid": True,
            "enabled_only": False,
            "sort": True,
            "sort_by": "classification",
            "include_metadata": True,
            "include_validation_details": False,
            "include_taxonomy_labels": resolved_options.use_taxonomy_labels,
            "force_taxonomy_reload": resolved_options.force_taxonomy_reload,
        }

    attempts = (
        {
            "include_invalid": True,
            "enabled_only": False,
            "sort": True,
            "sort_by": "classification",
            "include_metadata": True,
            "include_validation_details": False,
            "include_taxonomy_labels": resolved_options.use_taxonomy_labels,
            "force_taxonomy_reload": resolved_options.force_taxonomy_reload,
        },
        {
            "include_invalid": True,
            "enabled_only": False,
            "sort": True,
            "sort_by": "classification",
            "include_metadata": True,
            "include_validation_details": False,
        },
        {},
    )

    for kwargs in attempts:
        try:
            return cls(**kwargs)
        except Exception:
            continue

    return None


def make_index_options(options: LibraryScanServiceOptions) -> Any:
    """Baut Index-Optionen aus Service-Optionen."""
    cls, _exc = _try_get_optional_attr(INDEX_MODULE_NAMES, "LibraryIndexBuilderOptions")

    if cls is None:
        return {
            "include_invalid": options.include_invalid,
            "enabled_only": options.enabled_only,
            "fail_on_duplicates": False,
            "sort": True,
            "sort_by": "classification",
            "include_tree": True,
            "include_items_by_id": True,
            "include_metadata": True,
            "use_taxonomy_labels": options.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": options.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": options.include_inactive_taxonomy_nodes,
            "force_taxonomy_reload": options.force_taxonomy_reload,
        }

    attempts = (
        {
            "include_invalid": options.include_invalid,
            "enabled_only": options.enabled_only,
            "fail_on_duplicates": False,
            "sort": True,
            "sort_by": "classification",
            "include_tree": True,
            "include_items_by_id": True,
            "include_metadata": True,
            "use_taxonomy_labels": options.use_taxonomy_labels,
            "include_empty_taxonomy_nodes": options.include_empty_taxonomy_nodes,
            "include_inactive_taxonomy_nodes": options.include_inactive_taxonomy_nodes,
            "force_taxonomy_reload": options.force_taxonomy_reload,
        },
        {
            "include_invalid": options.include_invalid,
            "enabled_only": options.enabled_only,
            "fail_on_duplicates": False,
            "sort": True,
            "sort_by": "classification",
            "include_tree": True,
            "include_items_by_id": True,
            "include_metadata": True,
        },
        {},
    )

    for kwargs in attempts:
        try:
            return cls(**kwargs)
        except Exception:
            continue

    return None


def discover_library_packages_safe(
    *,
    source_root: Path,
    options: Any = None,
    refresh_settings: bool = False,
) -> Any:
    """Führt Package Discovery mit Signatur-Fallbacks aus."""
    func, exc = _try_get_optional_attr(DISCOVERY_MODULE_NAMES, "discover_library_packages")
    if not callable(func):
        raise RuntimeError(f"package discovery is unavailable: {exc}")

    return _call_function_flexible(
        func,
        source_root=source_root,
        options=options,
        refresh_settings=refresh_settings,
    )


def read_package_candidates_safe(
    candidates: Iterable[Any],
    *,
    options: Any = None,
) -> tuple[Any, ...]:
    """Liest Package Candidates mit Signatur-Fallbacks."""
    func, exc = _try_get_optional_attr(READER_MODULE_NAMES, "read_package_candidates")
    if not callable(func):
        raise RuntimeError(f"package reader is unavailable: {exc}")

    candidate_tuple = tuple(candidates or ())

    try:
        return tuple(func(candidate_tuple, options=options))
    except TypeError:
        try:
            return tuple(func(candidates=candidate_tuple, options=options))
        except TypeError:
            return tuple(func(candidate_tuple))


def validate_read_results_safe(
    read_results: Iterable[Any],
    *,
    options: Any = None,
) -> tuple[Any, ...]:
    """Validiert ReadResults mit Signatur-Fallbacks."""
    func, exc = _try_get_optional_attr(VALIDATOR_MODULE_NAMES, "validate_read_results")
    read_result_tuple = tuple(read_results or ())

    if not callable(func):
        result: list[dict[str, Any]] = []
        for read_result in read_result_tuple:
            ok = bool(get_item_attr(read_result, "ok", default=False))
            result.append(
                {
                    "ok": ok,
                    "valid": ok,
                    "status": "valid" if ok else "invalid",
                    "package_id": get_item_attr(read_result, "package_id"),
                    "family_id": get_item_attr(read_result, "family_id"),
                    "item_id": get_item_attr(read_result, "item_id"),
                    "warnings": [],
                    "errors": [] if ok else [f"validation layer unavailable: {exc}"],
                }
            )
        return tuple(result)

    try:
        return tuple(func(read_result_tuple, options=options))
    except TypeError:
        try:
            return tuple(func(read_results=read_result_tuple, options=options))
        except TypeError:
            return tuple(func(read_result_tuple))


def fingerprint_read_results_safe(
    read_results: Iterable[Any],
    *,
    options: Any = None,
) -> tuple[Any, ...]:
    """
    Erzeugt Fingerprints für ReadResults.
    Einzelne Fingerprint-Fehler zerstören nicht die gesamte Pipeline.
    """
    func, exc = _try_get_optional_attr(FINGERPRINT_MODULE_NAMES, "fingerprint_read_result")
    fingerprint_results: list[Any] = []

    for read_result in read_results or ():
        if not callable(func):
            fingerprint_results.append(build_fallback_fingerprint(read_result, error=exc))
            continue

        try:
            try:
                fingerprint_results.append(
                    func(
                        read_result,
                        options=options,
                    )
                )
            except TypeError:
                try:
                    fingerprint_results.append(
                        func(
                            read_result=read_result,
                            options=options,
                        )
                    )
                except TypeError:
                    fingerprint_results.append(func(read_result))

        except Exception as fingerprint_exc:
            fingerprint_results.append(build_fallback_fingerprint(read_result, error=fingerprint_exc))

    return tuple(fingerprint_results)


def build_fallback_fingerprint(read_result: Any, *, error: BaseException | None = None) -> dict[str, Any]:
    payload = json_safe(read_result)
    fingerprint_source = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    return {
        "ok": error is None,
        "status": "ok" if error is None else "error",
        "revision_hash": hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest(),
        "package_id": get_item_attr(read_result, "package_id"),
        "family_id": get_item_attr(read_result, "family_id"),
        "errors": [] if error is None else [str(error)],
        "error": exception_to_dict(error),
        "fallback": True,
    }


def build_library_items_from_results_safe(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any],
    fingerprint_results: Iterable[Any],
    options: Any = None,
) -> tuple[Any, ...]:
    """Baut LibraryItems mit Signatur-Fallbacks."""
    func, _exc = _try_get_optional_attr(SUMMARY_MODULE_NAMES, "build_library_items_from_results")
    read_tuple = tuple(read_results or ())
    validation_tuple = tuple(validation_results or ())
    fingerprint_tuple = tuple(fingerprint_results or ())

    if callable(func):
        try:
            return tuple(
                func(
                    read_results=read_tuple,
                    validation_results=validation_tuple,
                    fingerprint_results=fingerprint_tuple,
                    options=options,
                )
            )
        except TypeError:
            try:
                return tuple(
                    func(
                        read_results=read_tuple,
                        validation_results=validation_tuple,
                        fingerprint_results=fingerprint_tuple,
                    )
                )
            except TypeError:
                return tuple(func(read_tuple, validation_tuple, fingerprint_tuple))

    return build_library_items_from_results_fallback(
        read_results=read_tuple,
        validation_results=validation_tuple,
        fingerprint_results=fingerprint_tuple,
    )


def build_library_items_from_results_fallback(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any],
    fingerprint_results: Iterable[Any],
) -> tuple[dict[str, Any], ...]:
    """Fallback Read-Model-Builder."""
    read_tuple = tuple(read_results or ())
    validation_tuple = tuple(validation_results or ())
    fingerprint_tuple = tuple(fingerprint_results or ())

    items: list[dict[str, Any]] = []

    for index, read_result in enumerate(read_tuple):
        read_payload = json_safe(read_result)
        if not isinstance(read_payload, Mapping):
            read_payload = {"value": read_payload}

        validation = validation_tuple[index] if index < len(validation_tuple) else {}
        fingerprint = fingerprint_tuple[index] if index < len(fingerprint_tuple) else {}

        validation_payload = ensure_mapping(validation)
        fingerprint_payload = ensure_mapping(fingerprint)

        documents = ensure_mapping(read_payload.get("documents"))
        manifest = ensure_mapping(
            read_payload.get("manifest")
            or read_payload.get("manifest_payload")
            or documents.get("vplib.manifest.json")
        )
        family = ensure_mapping(
            read_payload.get("family")
            or read_payload.get("family_payload")
            or documents.get("family/identity.json")
        )
        classification = ensure_mapping(
            read_payload.get("classification")
            or read_payload.get("classification_payload")
            or documents.get("family/classification.json")
        )

        metadata = ensure_mapping(read_payload.get("metadata"))
        taxonomy = ensure_mapping(metadata.get("taxonomy"))
        if classification:
            taxonomy.update(
                {
                    "domain": classification.get("domain") or taxonomy.get("domain"),
                    "category": classification.get("category") or taxonomy.get("category"),
                    "subcategory": classification.get("subcategory") or taxonomy.get("subcategory"),
                    "classification_path": classification.get("classification_path") or taxonomy.get("classification_path"),
                    "object_kind": classification.get("object_kind") or taxonomy.get("object_kind"),
                }
            )

        vplib_uid = (
            extract_vplib_uid_from_mapping(read_payload)
            or extract_vplib_uid_from_mapping(manifest)
        )
        family_id = (
            read_payload.get("family_id")
            or manifest.get("family_id")
            or family.get("family_id")
            or read_payload.get("package_id")
            or read_payload.get("relative_package_root")
            or "unknown.library_item"
        )
        package_id = (
            read_payload.get("package_id")
            or manifest.get("package_id")
            or f"vplib.{family_id}"
        )

        valid = result_is_valid(validation_payload) or result_is_ok(read_payload)
        stable_id = normalize_stable_id(vplib_uid or family_id or package_id, fallback="unknown.library_item")

        items.append(
            {
                "id": stable_id,
                "vplib_uid": vplib_uid,
                "family_id": safe_str(family_id),
                "package_id": safe_str(package_id),
                "label": (
                    family.get("label")
                    or family.get("name")
                    or manifest.get("family_name")
                    or humanize_identifier(family_id)
                ),
                "description": family.get("description") or manifest.get("description") or read_payload.get("description"),
                "status": "valid" if valid else "invalid",
                "enabled": True,
                "is_valid": bool(valid),
                "domain": taxonomy.get("domain"),
                "category": taxonomy.get("category"),
                "subcategory": taxonomy.get("subcategory"),
                "object_kind": taxonomy.get("object_kind") or manifest.get("object_kind"),
                "classification_path": taxonomy.get("classification_path") or manifest.get("classification_path"),
                "source_path": read_payload.get("package_root") or read_payload.get("source_path") or manifest.get("source_path"),
                "taxonomy": taxonomy,
                "manifest": manifest,
                "family": family,
                "classification": classification,
                "validation": {
                    "valid": bool(valid),
                    "status": validation_payload.get("status"),
                    "warnings": validation_payload.get("warnings", []),
                    "errors": validation_payload.get("errors", []),
                    "warning_count": len(tuple_of_strings(validation_payload.get("warnings"))),
                    "error_count": len(tuple_of_strings(validation_payload.get("errors"))),
                    "fatal_count": 0,
                },
                "fingerprint": fingerprint_payload,
                "revision_hash": fingerprint_payload.get("revision_hash"),
                "documents": documents,
                "metadata": {
                    "taxonomy": taxonomy,
                    "read_result": read_payload,
                    "fallback_builder": True,
                },
            }
        )

    return tuple(items)


def build_library_index_from_items_safe(
    items: Iterable[Any],
    *,
    source_root: Any = None,
    options: Any = None,
) -> Any:
    """Baut LibraryIndex mit Signatur-Fallbacks."""
    func, _exc = _try_get_optional_attr(INDEX_MODULE_NAMES, "build_library_index_from_items")
    item_tuple = tuple(items or ())

    if callable(func):
        try:
            return func(
                item_tuple,
                source_root=source_root,
                options=options,
            )
        except TypeError:
            try:
                return func(
                    items=item_tuple,
                    source_root=source_root,
                    options=options,
                )
            except TypeError:
                return func(item_tuple)

    return build_library_index_from_items_fallback(item_tuple, source_root=source_root, options=options)


def build_library_index_from_items_fallback(
    items: Iterable[Any],
    *,
    source_root: Any = None,
    options: Any = None,
) -> dict[str, Any]:
    """Fallback LibraryIndex."""
    item_list = list(items or ())
    options_payload = object_to_options_dict(options)
    include_invalid = safe_bool(options_payload.get("include_invalid"), default=False)
    enabled_only = safe_bool(options_payload.get("enabled_only"), default=False)

    visible_items: list[Any] = []
    invalid_items: list[Any] = []

    for item in item_list:
        if enabled_only and not safe_bool(get_item_attr(item, "enabled"), default=True):
            continue

        item_status = get_item_status(item)
        is_valid = item_status in {"valid", "ok", "active"} or safe_bool(get_item_attr(item, "is_valid"), default=False)

        if is_valid:
            visible_items.append(item)
        else:
            invalid_items.append(item)
            if include_invalid:
                visible_items.append(item)

    return {
        "ok": True,
        "status": "ok" if visible_items else "empty",
        "source_root": safe_path_str(source_root),
        "items": visible_items,
        "invalid_items": invalid_items,
        "items_by_id": {
            get_item_id(item): item
            for item in visible_items
            if get_item_id(item)
        },
        "tree": build_tree_from_items(visible_items),
        "count": len(visible_items),
        "invalid_count": len(invalid_items),
        "fallback_builder": True,
    }


def build_blocks_response_from_index_safe(index: Any, **filters: Any) -> dict[str, Any]:
    func, _exc = _try_get_optional_attr(INDEX_MODULE_NAMES, "build_blocks_response_from_index")
    if callable(func):
        try:
            response = _call_function_flexible(func, index, **filters)
            if isinstance(response, Mapping):
                return dict(response)
        except Exception:
            pass

    items = extract_index_items(index)
    filtered = filter_items(items, **filters)

    return {
        "ok": True,
        "status": "ok" if filtered else "empty",
        "count": len(filtered),
        "items": [json_safe(item) for item in filtered],
        "filters": {
            key: value
            for key, value in filters.items()
            if value not in {None, ""}
        },
        "fallback_builder": True,
    }


def build_tree_response_from_index_safe(index: Any) -> dict[str, Any]:
    func, _exc = _try_get_optional_attr(INDEX_MODULE_NAMES, "build_tree_response_from_index")
    if callable(func):
        try:
            response = func(index)
            if isinstance(response, Mapping):
                return dict(response)
        except Exception:
            pass

    items = extract_index_items(index)
    tree = build_tree_from_items(items)

    return {
        "ok": True,
        "status": "ok" if tree.get("domains") else "empty",
        "tree": tree,
        "stats": {
            "domain_count": len(tree.get("domains", [])),
        },
        "fallback_builder": True,
    }


def build_index_response_safe(index: Any) -> dict[str, Any]:
    func, _exc = _try_get_optional_attr(INDEX_MODULE_NAMES, "build_index_response")
    if callable(func):
        try:
            response = func(index)
            if isinstance(response, Mapping):
                return dict(response)
        except Exception:
            pass

    return json_safe(index) if isinstance(json_safe(index), Mapping) else {"index": json_safe(index)}


def extract_index_items(index: Any) -> list[Any]:
    if isinstance(index, Mapping):
        items = index.get("items")
        if isinstance(items, list):
            return items
        if isinstance(items, tuple):
            return list(items)

    items = get_item_attr(index, "items", default=[])
    if isinstance(items, tuple):
        return list(items)
    if isinstance(items, list):
        return items

    return []


def filter_items(items: Iterable[Any], **filters: Any) -> list[Any]:
    domain = normalize_query_value(filters.get("domain"))
    category = normalize_query_value(filters.get("category"))
    subcategory = normalize_query_value(filters.get("subcategory"))
    object_kind = normalize_query_value(filters.get("object_kind"))
    q = normalize_query_value(filters.get("q"))

    result: list[Any] = []

    for item in items or ():
        item_payload = json_safe(item)
        if not isinstance(item_payload, Mapping):
            continue

        taxonomy = ensure_mapping(item_payload.get("taxonomy"))
        item_domain = safe_str(item_payload.get("domain") or taxonomy.get("domain"), default="")
        item_category = safe_str(item_payload.get("category") or taxonomy.get("category"), default="")
        item_subcategory = safe_str(item_payload.get("subcategory") or taxonomy.get("subcategory"), default="")
        item_object_kind = safe_str(item_payload.get("object_kind") or taxonomy.get("object_kind") or item_payload.get("kind"), default="")

        if domain and item_domain != domain:
            continue
        if category and item_category != category:
            continue
        if subcategory and item_subcategory != subcategory:
            continue
        if object_kind and item_object_kind != object_kind:
            continue

        if q:
            haystack = " ".join(
                [
                    safe_str(item_payload.get("id")),
                    safe_str(item_payload.get("vplib_uid")),
                    safe_str(item_payload.get("family_id")),
                    safe_str(item_payload.get("package_id")),
                    safe_str(item_payload.get("label")),
                    safe_str(item_payload.get("name")),
                    safe_str(item_payload.get("title")),
                    safe_str(item_payload.get("description")),
                    item_domain,
                    item_category,
                    item_subcategory,
                    item_object_kind,
                ]
            ).lower()
            if q.lower() not in haystack:
                continue

        result.append(item)

    return result


def normalize_query_value(value: Any) -> str | None:
    text = safe_str(value, default="")
    return text or None


def build_tree_from_items(items: Iterable[Any]) -> dict[str, Any]:
    by_domain: dict[str, dict[str, Any]] = {}

    for item in items or ():
        payload = json_safe(item)
        if not isinstance(payload, Mapping):
            continue

        taxonomy = ensure_mapping(payload.get("taxonomy"))
        domain = safe_str(payload.get("domain") or taxonomy.get("domain"), default="unknown")
        category = safe_str(payload.get("category") or taxonomy.get("category"), default="unknown")
        subcategory = safe_str(payload.get("subcategory") or taxonomy.get("subcategory"), default="unknown")

        domain_node = by_domain.setdefault(
            domain,
            {
                "id": domain,
                "label": domain,
                "item_count": 0,
                "by_category": {},
                "categories": [],
            },
        )
        domain_node["item_count"] += 1

        by_category = domain_node["by_category"]
        category_node = by_category.setdefault(
            category,
            {
                "id": category,
                "label": category,
                "item_count": 0,
                "by_subcategory": {},
                "subcategories": [],
            },
        )
        category_node["item_count"] += 1

        by_subcategory = category_node["by_subcategory"]
        subcategory_node = by_subcategory.setdefault(
            subcategory,
            {
                "id": subcategory,
                "label": subcategory,
                "item_count": 0,
                "items": [],
            },
        )
        subcategory_node["item_count"] += 1
        subcategory_node["items"].append(payload)

    domains: list[dict[str, Any]] = []

    for domain_key in sorted(by_domain.keys()):
        domain_node = by_domain[domain_key]
        category_nodes = []

        for category_key in sorted(domain_node["by_category"].keys()):
            category_node = domain_node["by_category"][category_key]
            subcategory_nodes = []

            for subcategory_key in sorted(category_node["by_subcategory"].keys()):
                subcategory_nodes.append(category_node["by_subcategory"][subcategory_key])

            category_node["subcategories"] = subcategory_nodes
            category_node.pop("by_subcategory", None)
            category_nodes.append(category_node)

        domain_node["categories"] = category_nodes
        domain_node.pop("by_category", None)
        domains.append(domain_node)

    return {
        "domains": domains,
        "by_domain": by_domain,
    }


def build_scan_result_from_items_safe(
    *,
    source_root: Any = None,
    items: Iterable[Any] | None = None,
    warnings: Iterable[Any] | None = None,
    errors: Iterable[Any] | None = None,
    started_at: Any = None,
    started_monotonic_ms: int | None = None,
    settings: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Baut ScanResult mit defensiven Signatur-Fallbacks."""
    func, _exc = _try_get_optional_attr(DOMAIN_SCAN_RESULT_MODULE_NAMES, "build_scan_result_from_items")

    item_tuple = tuple(items or ())
    warning_tuple = tuple_of_strings(warnings)
    error_tuple = tuple_of_strings(errors)

    if callable(func):
        try:
            return _call_function_flexible(
                func,
                source_root=source_root,
                items=item_tuple,
                warnings=warning_tuple,
                errors=error_tuple,
                started_at=started_at,
                started_monotonic_ms=started_monotonic_ms,
                settings=settings or {},
                metadata=metadata or {},
            )
        except Exception:
            pass

    return {
        "ok": not bool(error_tuple),
        "status": "ok" if item_tuple and not error_tuple else ("empty" if not item_tuple else "partial"),
        "source_root": safe_path_str(source_root),
        "started_at": safe_str(started_at, default="") or utc_now_iso(),
        "finished_at": utc_now_iso(),
        "duration_ms": calculate_duration_ms(started_monotonic_ms),
        "items": [json_safe(item) for item in item_tuple],
        "warnings": list(warning_tuple),
        "errors": list(error_tuple),
        "settings": dict(settings or {}),
        "metadata": dict(metadata or {}),
        "fallback_builder": True,
    }


def build_error_scan_result_safe(
    exc: BaseException,
    *,
    source_root: Any = None,
    started_at: Any = None,
    started_monotonic_ms: int | None = None,
    include_traceback: bool = False,
    settings: Mapping[str, Any] | None = None,
) -> Any:
    """Baut Error-ScanResult mit defensiven Signatur-Fallbacks."""
    func, _load_exc = _try_get_optional_attr(DOMAIN_SCAN_RESULT_MODULE_NAMES, "build_error_scan_result")

    if callable(func):
        try:
            return _call_function_flexible(
                func,
                exc,
                source_root=source_root,
                started_at=started_at,
                started_monotonic_ms=started_monotonic_ms,
                include_traceback=include_traceback,
                settings=settings or {},
            )
        except Exception:
            pass

    return {
        "ok": False,
        "status": "error",
        "source_root": safe_path_str(source_root),
        "started_at": safe_str(started_at, default="") or utc_now_iso(),
        "finished_at": utc_now_iso(),
        "duration_ms": calculate_duration_ms(started_monotonic_ms),
        "errors": [str(exc)],
        "error": exception_to_dict(exc, include_traceback=include_traceback),
        "settings": dict(settings or {}),
        "fallback_builder": True,
    }


def collect_pipeline_warnings(
    *,
    discovery_result: Any,
    read_results: Iterable[Any],
    validation_results: Iterable[Any],
    fingerprint_results: Iterable[Any],
    index: Any,
    taxonomy_health: Mapping[str, Any] | None = None,
) -> list[str]:
    """Sammelt Warnungen aus Pipeline-Ergebnissen."""
    warnings: list[str] = []

    for source in (discovery_result, index):
        try:
            warnings.extend(tuple_of_strings(get_item_attr(source, "warnings")))
        except Exception:
            continue

    for result_group in (read_results, validation_results, fingerprint_results):
        for result in result_group:
            try:
                warnings.extend(tuple_of_strings(get_item_attr(result, "warnings")))
            except Exception:
                continue

    if taxonomy_health and not safe_bool(taxonomy_health.get("healthy"), default=False):
        warnings.append("taxonomy service is not healthy")

    return dedupe_strings(warnings)


def collect_pipeline_errors(
    *,
    discovery_result: Any,
    read_results: Iterable[Any],
    validation_results: Iterable[Any],
    fingerprint_results: Iterable[Any],
    index: Any,
    taxonomy_health: Mapping[str, Any] | None = None,
    require_taxonomy: bool = True,
) -> list[str]:
    """Sammelt Fehler aus Pipeline-Ergebnissen."""
    errors: list[str] = []

    for source in (discovery_result, index):
        try:
            errors.extend(tuple_of_strings(get_item_attr(source, "errors")))
        except Exception:
            continue

    for result_group in (read_results, validation_results, fingerprint_results):
        for result in result_group:
            try:
                errors.extend(tuple_of_strings(get_item_attr(result, "errors")))
            except Exception:
                continue

    if require_taxonomy and taxonomy_health and not safe_bool(taxonomy_health.get("healthy"), default=False):
        errors.append("taxonomy service is required but not healthy")

    return dedupe_strings(errors)


def dedupe_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        text = safe_str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)

    return result


def derive_pipeline_status(
    *,
    discovery_result: Any,
    read_results: Iterable[Any],
    validation_results: Iterable[Any],
    items: Iterable[Any],
    index: Any,
    errors: Iterable[str],
    strict_errors: bool,
) -> str:
    """Leitet Gesamtstatus der Pipeline ab."""
    error_list = list(errors or ())
    item_list = list(items or ())
    read_result_list = list(read_results or ())

    valid_count = sum(
        1
        for item in item_list
        if get_item_status(item) in {"valid", "ok", "active"}
        or safe_bool(get_item_attr(item, "is_valid"), default=False)
    )

    if strict_errors and error_list:
        return "error"

    index_status = get_result_status(index)
    if index_status in {"error", "invalid"}:
        return index_status

    if error_list and valid_count == 0:
        return "error"

    if error_list and valid_count > 0:
        return "partial"

    if not item_list:
        discovery_status = get_result_status(discovery_result)

        if discovery_status == "empty":
            return "empty"

        if not read_result_list:
            return "empty"

        return "invalid"

    if valid_count == 0:
        return "invalid"

    if valid_count < len(item_list):
        return "partial"

    return "ok"


# ---------------------------------------------------------------------------
# Main service functions
# ---------------------------------------------------------------------------

def scan_library_source(
    *,
    source_root: Any = None,
    options: Any = None,
    refresh_settings: bool | None = None,
    force_refresh: bool = False,
) -> LibraryScanPipelineResult:
    """
    Führt den vollständigen Library-Scan aus.

    Pipeline:

        1. Settings laden
        2. Source-Root ermitteln
        3. Taxonomie laden/health prüfen
        4. Discovery
        5. Reader
        6. Validation
        7. Fingerprint
        8. LibraryItems bauen
        9. Index bauen
        10. ScanResult bauen
        11. PipelineResult zurückgeben

    Kein Schreiben. Keine Datenbank.
    """
    service_options = coerce_scan_service_options(
        options,
        refresh=bool(refresh_settings),
    )

    if refresh_settings is not None:
        service_options = LibraryScanServiceOptions(
            **{
                **service_options.to_dict(),
                "refresh_settings": bool(refresh_settings),
            }
        )

    started_at = utc_now_iso()
    started_monotonic = monotonic_ms_safe()

    taxonomy_payload: dict[str, Any] = {}
    taxonomy_health: dict[str, Any] = {}

    try:
        settings_summary = get_settings_summary(refresh=service_options.refresh_settings)
        resolved_source_root = resolve_scan_source_root(
            source_root,
            refresh_settings=service_options.refresh_settings,
        )

        taxonomy_health = get_taxonomy_health_safe(
            force_reload=service_options.force_taxonomy_reload,
            include_registry_state=False,
        )
        taxonomy_payload = get_taxonomy_payload_safe(
            force_reload=service_options.force_taxonomy_reload,
            include_inactive=service_options.include_inactive_taxonomy_nodes,
        )
        taxonomy_version = extract_taxonomy_version(taxonomy_payload) or safe_str(
            taxonomy_health.get("taxonomy_version"),
            default="",
        )

        cache_key = make_cache_key(
            resolved_source_root,
            taxonomy_version=taxonomy_version or "noversion",
            options=service_options,
        )

        if service_options.use_cache and not force_refresh:
            cached = get_cached_scan_result(
                cache_key=cache_key,
                ttl_seconds=service_options.cache_ttl_seconds,
            )

            if cached is not None:
                cached_metadata = dict(cached.metadata)
                cached_metadata["cache_used"] = True

                return LibraryScanPipelineResult(
                    ok=cached.ok,
                    status=cached.status,
                    source_root=cached.source_root,
                    started_at=cached.started_at,
                    finished_at=cached.finished_at,
                    duration_ms=cached.duration_ms,
                    discovery_result=cached.discovery_result,
                    read_results=cached.read_results,
                    validation_results=cached.validation_results,
                    fingerprint_results=cached.fingerprint_results,
                    items=cached.items,
                    index=cached.index,
                    scan_result=cached.scan_result,
                    taxonomy_payload=cached.taxonomy_payload,
                    taxonomy_health=cached.taxonomy_health,
                    warnings=cached.warnings,
                    errors=cached.errors,
                    options=cached.options,
                    settings_summary=cached.settings_summary,
                    metadata=cached_metadata,
                    version=cached.version,
                )

        discovery_options = make_discovery_options(service_options)
        reader_options = make_reader_options(service_options)
        validation_options = make_validation_options(service_options)
        fingerprint_options = make_fingerprint_options(service_options)
        summary_options = make_summary_options(service_options)
        index_options = make_index_options(service_options)

        discovery_result = discover_library_packages_safe(
            source_root=resolved_source_root,
            options=discovery_options,
            refresh_settings=service_options.refresh_settings,
        )

        candidates = tuple(get_item_attr(discovery_result, "candidates", default=()) or ())

        read_results = read_package_candidates_safe(
            candidates,
            options=reader_options,
        )

        validation_results = validate_read_results_safe(
            read_results,
            options=validation_options,
        )

        fingerprint_results = fingerprint_read_results_safe(
            read_results,
            options=fingerprint_options,
        )

        items = build_library_items_from_results_safe(
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            options=summary_options,
        )

        index = build_library_index_from_items_safe(
            items,
            source_root=resolved_source_root,
            options=index_options,
        )

        warnings = collect_pipeline_warnings(
            discovery_result=discovery_result,
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            index=index,
            taxonomy_health=taxonomy_health,
        )

        errors = collect_pipeline_errors(
            discovery_result=discovery_result,
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            index=index,
            taxonomy_health=taxonomy_health,
            require_taxonomy=service_options.require_taxonomy,
        )

        scan_result = build_scan_result_from_items_safe(
            source_root=resolved_source_root,
            items=items,
            warnings=warnings,
            errors=errors if service_options.strict_errors else (),
            started_at=started_at,
            started_monotonic_ms=started_monotonic,
            settings=settings_summary,
            metadata={
                "discovery_status": get_result_status(discovery_result),
                "read_count": len(read_results),
                "validation_count": len(validation_results),
                "fingerprint_count": len(fingerprint_results),
                "index_status": get_result_status(index),
                "taxonomy_version": taxonomy_version,
                "taxonomy_healthy": bool(taxonomy_health.get("healthy", taxonomy_payload.get("ok", False))),
            },
        )

        status = derive_pipeline_status(
            discovery_result=discovery_result,
            read_results=read_results,
            validation_results=validation_results,
            items=items,
            index=index,
            errors=errors,
            strict_errors=service_options.strict_errors,
        )

        result = LibraryScanPipelineResult(
            ok=status not in {"error", "invalid", "unavailable"},
            status=status,
            source_root=str(resolved_source_root),
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_ms=calculate_duration_ms(started_monotonic),
            discovery_result=discovery_result,
            read_results=read_results,
            validation_results=validation_results,
            fingerprint_results=fingerprint_results,
            items=items,
            index=index,
            scan_result=scan_result,
            taxonomy_payload=taxonomy_payload,
            taxonomy_health=taxonomy_health,
            warnings=tuple(warnings),
            errors=tuple(errors if service_options.strict_errors else ()),
            options=service_options,
            settings_summary=settings_summary if isinstance(settings_summary, Mapping) else {},
            metadata={
                "cache_key": cache_key,
                "cache_used": False,
                "taxonomy_version": taxonomy_version,
                "taxonomy_healthy": bool(taxonomy_health.get("healthy", taxonomy_payload.get("ok", False))),
                "imports": get_import_status(),
                "writes_database": False,
            },
        )

        if service_options.use_cache:
            set_cached_scan_result(
                cache_key=cache_key,
                result=result,
            )

        return result

    except Exception as exc:
        settings_summary = {}

        try:
            settings_summary = get_settings_summary(refresh=service_options.refresh_settings)
        except Exception:
            settings_summary = {}

        return LibraryScanPipelineResult.error(
            exc,
            source_root=source_root,
            started_at=started_at,
            started_monotonic_ms=started_monotonic,
            options=service_options,
            settings_summary=settings_summary if isinstance(settings_summary, Mapping) else {},
            taxonomy_payload=taxonomy_payload,
            taxonomy_health=taxonomy_health,
            include_traceback=service_options.include_raw_pipeline,
        )


def scan_library_source_no_cache(
    *,
    source_root: Any = None,
    options: Any = None,
) -> LibraryScanPipelineResult:
    """Führt Scan ohne Cache aus."""
    service_options = coerce_scan_service_options(options)

    service_options = LibraryScanServiceOptions(
        **{
            **service_options.to_dict(),
            "use_cache": False,
        }
    )

    return scan_library_source(
        source_root=source_root,
        options=service_options,
        force_refresh=True,
    )


# ---------------------------------------------------------------------------
# API response helpers for routes/services
# ---------------------------------------------------------------------------

def get_library_scan_response(
    *,
    source_root: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Baut Antwort für GET /api/v1/vplib/library/scan."""
    result = scan_library_source(
        source_root=source_root,
        options=options,
        force_refresh=force_refresh,
    )

    return result.to_scan_response_dict()


def get_library_blocks_response(
    *,
    source_root: Any = None,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
    object_kind: Any = None,
    q: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Baut Antwort für GET /api/v1/vplib/library/blocks."""
    service_options = coerce_scan_service_options(options)

    service_options = LibraryScanServiceOptions(
        **{
            **service_options.to_dict(),
            "include_raw_pipeline": False,
            "include_index": True,
            "include_scan_result": False,
            "include_discovery_result": False,
            "include_read_results": False,
            "include_validation_results": False,
            "include_fingerprint_results": False,
            "include_taxonomy_payload": False,
        }
    )

    result = scan_library_source(
        source_root=source_root,
        options=service_options,
        force_refresh=force_refresh,
    )

    response = result.to_blocks_response_dict(
        domain=domain,
        category=category,
        subcategory=subcategory,
        object_kind=object_kind,
        q=q,
    )

    response.setdefault(
        "scan",
        {
            "status": result.status,
            "source_root": result.source_root,
            "candidate_count": result.candidate_count,
            "canonical_candidate_count": result.canonical_candidate_count,
            "legacy_candidate_count": result.legacy_candidate_count,
            "read_count": result.read_count,
            "validation_count": result.validation_count,
            "fingerprint_count": result.fingerprint_count,
            "item_count": result.item_count,
            "valid_item_count": result.valid_item_count,
            "invalid_item_count": result.invalid_item_count,
            "duration_ms": result.duration_ms,
            "generated_at": result.finished_at,
            "taxonomy_version": result.taxonomy_version,
            "writes_database": False,
        },
    )

    return response


def get_library_tree_response(
    *,
    source_root: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Baut Antwort für GET /api/v1/vplib/library/tree."""
    service_options = coerce_scan_service_options(options)

    service_options = LibraryScanServiceOptions(
        **{
            **service_options.to_dict(),
            "include_raw_pipeline": False,
            "include_index": True,
            "include_scan_result": False,
            "include_discovery_result": False,
            "include_read_results": False,
            "include_validation_results": False,
            "include_fingerprint_results": False,
            "include_taxonomy_payload": False,
        }
    )

    result = scan_library_source(
        source_root=source_root,
        options=service_options,
        force_refresh=force_refresh,
    )

    response = result.to_tree_response_dict()

    response.setdefault(
        "scan",
        {
            "status": result.status,
            "source_root": result.source_root,
            "candidate_count": result.candidate_count,
            "canonical_candidate_count": result.canonical_candidate_count,
            "legacy_candidate_count": result.legacy_candidate_count,
            "read_count": result.read_count,
            "validation_count": result.validation_count,
            "fingerprint_count": result.fingerprint_count,
            "item_count": result.item_count,
            "valid_item_count": result.valid_item_count,
            "invalid_item_count": result.invalid_item_count,
            "duration_ms": result.duration_ms,
            "generated_at": result.finished_at,
            "taxonomy_version": result.taxonomy_version,
            "writes_database": False,
        },
    )

    return response


def get_library_index(
    *,
    source_root: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> Any:
    """Gibt nur den LibraryIndex zurück."""
    result = scan_library_source(
        source_root=source_root,
        options=options,
        force_refresh=force_refresh,
    )

    return result.index


def get_library_sync_preview_response(
    *,
    source_root: Any = None,
    options: Any = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Baut Sync-Payload-Preview ohne zu schreiben.

    Diese Antwort kann später an POST /api/v1/vplib/library/sync gegeben werden.
    """
    result = scan_library_source(
        source_root=source_root,
        options=options,
        force_refresh=force_refresh,
    )
    return result.to_sync_preview_dict()


# ---------------------------------------------------------------------------
# Sync payload preview helpers
# ---------------------------------------------------------------------------

def build_sync_payloads_from_scan_result(result: LibraryScanPipelineResult | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Erzeugt CreativeLibraryService.publish_bundle-kompatible Payloads aus Scan-Items."""
    if isinstance(result, LibraryScanPipelineResult):
        items = list(result.items)
        source_root = result.source_root
        taxonomy_version = result.taxonomy_version
    else:
        items = result.get("items", []) if isinstance(result.get("items"), list) else []
        source_root = result.get("source_root")
        taxonomy_version = nested_mapping_value(result, "taxonomy", "taxonomy_version")

    payloads: list[dict[str, Any]] = []

    for item in items:
        item_payload = json_safe(item)
        if not isinstance(item_payload, Mapping):
            continue

        publish_payload = build_publish_payload_from_scan_item(
            item_payload,
            source_root=source_root,
            taxonomy_version=taxonomy_version,
        )
        if publish_payload:
            payloads.append(publish_payload)

    return payloads


def build_publish_payload_from_scan_item(
    item: Mapping[str, Any],
    *,
    source_root: Any = None,
    taxonomy_version: Any = None,
) -> dict[str, Any]:
    """Baut Publish-Bundle-Payload aus einem Scan-Item."""
    payload = ensure_mapping(item)
    manifest = ensure_mapping(payload.get("manifest") or payload.get("manifest_payload"))
    family = ensure_mapping(payload.get("family") or payload.get("family_payload"))
    classification = ensure_mapping(payload.get("classification") or payload.get("classification_payload"))
    documents = ensure_mapping(payload.get("documents"))
    taxonomy = ensure_mapping(payload.get("taxonomy"))

    if not manifest and isinstance(documents.get("vplib.manifest.json"), Mapping):
        manifest = ensure_mapping(documents.get("vplib.manifest.json"))

    if not family and isinstance(documents.get("family/identity.json"), Mapping):
        family = ensure_mapping(documents.get("family/identity.json"))

    if not classification and isinstance(documents.get("family/classification.json"), Mapping):
        classification = ensure_mapping(documents.get("family/classification.json"))

    uid = (
        extract_vplib_uid_from_mapping(payload)
        or extract_vplib_uid_from_mapping(manifest)
    )

    family_id = (
        payload.get("family_id")
        or manifest.get("family_id")
        or family.get("family_id")
    )
    package_id = (
        payload.get("package_id")
        or manifest.get("package_id")
    )

    if not family_id and not package_id and not uid:
        return {}

    document_rows = []

    for path, content in documents.items():
        document_rows.append(
            {
                "document_kind": "source_document",
                "document_type": "json" if str(path).endswith(".json") else "text",
                "field_key": path,
                "title": path,
                "payload": {
                    "path": path,
                    "content": json_safe(content),
                    "source": "library_scan_service",
                },
            }
        )

    variants = payload.get("variants")
    if not isinstance(variants, list):
        variants = []

    return {
        "schema_version": LIBRARY_SCAN_SERVICE_VERSION,
        "source": LIBRARY_SCAN_SERVICE_COMPONENT,
        "vplib_uid": uid,
        "family_id": family_id,
        "package_id": package_id,
        "title": payload.get("label") or payload.get("title") or family.get("label") or manifest.get("family_name"),
        "description": payload.get("description") or family.get("description"),
        "source_path": payload.get("source_path") or manifest.get("source_path"),
        "source_root": safe_path_str(source_root),
        "taxonomy_version": taxonomy_version,
        "domain": payload.get("domain") or classification.get("domain") or taxonomy.get("domain"),
        "category": payload.get("category") or classification.get("category") or taxonomy.get("category"),
        "subcategory": payload.get("subcategory") or classification.get("subcategory") or taxonomy.get("subcategory"),
        "object_kind": payload.get("object_kind") or classification.get("object_kind") or taxonomy.get("object_kind") or manifest.get("object_kind"),
        "classification_path": payload.get("classification_path") or classification.get("classification_path") or taxonomy.get("classification_path"),
        "manifest_payload": manifest,
        "family_payload": family,
        "classification_payload": classification,
        "modules_payload": ensure_mapping(documents.get("vplib.modules.json")),
        "generator_payload": {
            "component": LIBRARY_SCAN_SERVICE_COMPONENT,
            "version": LIBRARY_SCAN_SERVICE_VERSION,
            "source_item": payload,
        },
        "variants": variants,
        "assets": payload.get("assets") if isinstance(payload.get("assets"), list) else [],
        "documents": document_rows,
        "document_bundle": {
            "manifest": manifest,
            "family": family,
            "classification": classification,
            "documents": documents,
            "variants": variants,
            "assets": payload.get("assets") if isinstance(payload.get("assets"), list) else [],
        },
    }


def extract_vplib_uid_from_mapping(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, Mapping):
        for key in VPLIB_UID_KEYS:
            uid = safe_str(value.get(key), default="")
            if uid:
                return uid

        for nested_key in ("manifest", "manifest_payload", "vplib_manifest", "payload", "data", "metadata"):
            nested = value.get(nested_key)
            uid = extract_vplib_uid_from_mapping(nested)
            if uid:
                return uid

        if "vplib.manifest.json" in value:
            uid = extract_vplib_uid_from_mapping(value.get("vplib.manifest.json"))
            if uid:
                return uid

    return None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """Liefert Importstatus optionaler Abhängigkeiten."""
    return get_optional_import_status()


def get_library_scan_service_health(
    *,
    refresh_settings: bool = False,
) -> dict[str, Any]:
    """
    Health-Status des Library Scan Service.

    Führt keinen Scan aus.
    """
    warnings: list[str] = []
    errors: list[str] = []

    imports = get_import_status()

    for name, status in imports.items():
        if not status.get("ok"):
            if name in {"discovery", "reader", "validation", "summary", "index", "taxonomy"}:
                errors.append(f"{name} import failed")
            else:
                warnings.append(f"{name} import failed; fallback may be active")

    try:
        source_root = resolve_scan_source_root(
            None,
            refresh_settings=refresh_settings,
        )
        source_root_value = str(source_root)
        source_root_exists = source_root.exists()
        source_root_is_directory = source_root.is_dir()
    except Exception as exc:
        source_root_value = None
        source_root_exists = False
        source_root_is_directory = False
        errors.append(f"could not resolve library source root: {exc}")

    try:
        options = LibraryScanServiceOptions.from_settings(refresh=refresh_settings)
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build scan service options: {exc}")

    try:
        settings_summary = get_settings_summary(refresh=refresh_settings)
    except Exception as exc:
        settings_summary = {}
        warnings.append(f"could not build settings summary: {exc}")

    try:
        taxonomy_health = get_taxonomy_health_safe(
            force_reload=False,
            include_registry_state=False,
        )
        if not taxonomy_health.get("healthy"):
            errors.append("taxonomy service is not healthy")
    except Exception as exc:
        taxonomy_health = {
            "ok": False,
            "healthy": False,
            "error": exception_to_dict(exc),
        }
        errors.append(f"taxonomy health check failed: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=5, minimum=0, maximum=MAX_CACHE_TTL_SECONDS)
        if safe_int_self_test != MAX_CACHE_TTL_SECONDS:
            errors.append(
                f"safe_int maximum self-test failed: expected {MAX_CACHE_TTL_SECONDS}, got {safe_int_self_test}"
            )
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": LIBRARY_SCAN_SERVICE_COMPONENT,
        "version": LIBRARY_SCAN_SERVICE_VERSION,
        "generated_at": utc_now_iso(),
        "source_root": source_root_value,
        "source_root_exists": source_root_exists,
        "source_root_is_directory": source_root_is_directory,
        "taxonomy": json_safe(taxonomy_health),
        "options": options_dict,
        "cache": {
            "entry_count": len(_SCAN_CACHE),
            "keys": sorted(_SCAN_CACHE.keys()),
        },
        "imports": imports,
        "settings_summary": json_safe(settings_summary),
        "supports_scan": True,
        "supports_blocks": True,
        "supports_tree": True,
        "supports_sync_preview": True,
        "writes_database": False,
        "writes_filesystem": False,
        "warnings": warnings,
        "errors": errors,
    }


def assert_library_scan_service_ready() -> None:
    """Wirft RuntimeError, wenn der Scan Service nicht bereit ist."""
    health = get_library_scan_service_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"library scan service is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_SCAN_SERVICE_VERSION",
    "LIBRARY_SCAN_SERVICE_COMPONENT",
    "DEFAULT_SCAN_SERVICE_STATUS",
    "SCAN_SERVICE_STATUS_VALUES",
    "DEFAULT_CACHE_KEY",
    "DEFAULT_CACHE_TTL_SECONDS",
    "MAX_CACHE_TTL_SECONDS",
    "SOURCE_ROOT_ENV_NAMES",
    "LibraryScanServiceOptions",
    "LibraryScanPipelineResult",
    "coerce_scan_service_options",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_int",
    "safe_path",
    "safe_path_str",
    "safe_resolve",
    "ensure_mapping",
    "tuple_of_strings",
    "normalize_service_status",
    "normalize_stable_id",
    "humanize_identifier",
    "get_item_attr",
    "nested_mapping_value",
    "get_item_id",
    "get_item_status",
    "get_result_status",
    "result_is_ok",
    "result_is_valid",
    "monotonic_ms_safe",
    "monotonic_ms",
    "calculate_duration_ms",
    "hash_json_safe",
    "taxonomy_available",
    "get_taxonomy_service_safe",
    "get_taxonomy_payload_safe",
    "get_taxonomy_health_safe",
    "extract_taxonomy_version",
    "clear_library_scan_cache",
    "make_cache_key",
    "get_cached_scan_result",
    "set_cached_scan_result",
    "resolve_scan_source_root",
    "object_to_options_dict",
    "rebuild_options_object",
    "make_discovery_options",
    "make_reader_options",
    "make_fingerprint_options",
    "make_validation_options",
    "make_summary_options",
    "make_index_options",
    "discover_library_packages_safe",
    "read_package_candidates_safe",
    "validate_read_results_safe",
    "fingerprint_read_results_safe",
    "build_fallback_fingerprint",
    "build_library_items_from_results_safe",
    "build_library_items_from_results_fallback",
    "build_library_index_from_items_safe",
    "build_library_index_from_items_fallback",
    "build_blocks_response_from_index_safe",
    "build_tree_response_from_index_safe",
    "build_index_response_safe",
    "extract_index_items",
    "filter_items",
    "normalize_query_value",
    "build_tree_from_items",
    "build_scan_result_from_items_safe",
    "build_error_scan_result_safe",
    "collect_pipeline_warnings",
    "collect_pipeline_errors",
    "dedupe_strings",
    "derive_pipeline_status",
    "scan_library_source",
    "scan_library_source_no_cache",
    "get_library_scan_response",
    "get_library_blocks_response",
    "get_library_tree_response",
    "get_library_index",
    "get_library_sync_preview_response",
    "build_sync_payloads_from_scan_result",
    "build_publish_payload_from_scan_item",
    "extract_vplib_uid_from_mapping",
    "get_import_status",
    "get_library_scan_service_health",
    "assert_library_scan_service_ready",
)