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

Version 0.2.1:

- Scan-Service-Optionen werden jetzt auch aus dict/Mapping/Dataclass robust normalisiert.
- Fix für AttributeError: dict object has no attribute require_taxonomy.
- HTTP-Routen und DB-Sync dürfen options als Mapping übergeben, ohne die Scan-Pipeline zu brechen.

Version 0.2.0:

- Pipeline propagiert Taxonomie-Optionen in Discovery, Reader, Validator,
  Summary Builder und Index Builder.
- Health enthält Taxonomie-Health.
- Scan-Metadata enthält Taxonomie-Version und Taxonomie-Status.
- Blocks-Response unterstützt Filter:
    domain, category, subcategory, object_kind, q
- Tree kann optional leere Backend-Taxonomie-Knoten enthalten.
- Cache-Key berücksichtigt Taxonomie-Version, damit geänderte Taxonomie nicht
  versehentlich alte Tree-/Options-Daten ausliefert.
- Bestehende Public-APIs bleiben rückwärtskompatibel.
"""

from __future__ import annotations

import os
import time
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_SCAN_SERVICE_VERSION: Final[str] = "0.2.1"
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
)

DEFAULT_CACHE_KEY: Final[str] = "default"
DEFAULT_CACHE_TTL_SECONDS: Final[int] = 5
MAX_CACHE_TTL_SECONDS: Final[int] = 86400

SOURCE_ROOT_ENV_NAMES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SOURCE_ROOT",
    "VPLIB_CREATE_SOURCE_ROOT",
    "LIBRARY_SOURCE_ROOT",
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
            text = value.decode("utf-8", errors="replace").strip()
        else:
            text = str(value).strip()

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


def get_item_id(item: Any) -> str | None:
    """Extrahiert stabile Item-ID."""
    try:
        value = (
            get_item_attr(item, "id")
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


def calculate_duration_ms(started_monotonic_ms: int | None) -> int:
    """Berechnet Dauer in Millisekunden."""
    try:
        if started_monotonic_ms is None:
            return 0

        current = monotonic_ms()

        return max(0, current - int(started_monotonic_ms))

    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_SETTINGS_IMPORT_ERROR: BaseException | None = None
_SCANNER_IMPORT_ERROR: BaseException | None = None
_VALIDATION_IMPORT_ERROR: BaseException | None = None
_READ_MODELS_IMPORT_ERROR: BaseException | None = None
_DOMAIN_IMPORT_ERROR: BaseException | None = None
_TAXONOMY_IMPORT_ERROR: BaseException | None = None

try:
    from config.library_settings import (
        LibrarySettings,
        get_library_cache_options,
        get_library_read_options,
        get_library_scan_options,
        get_library_settings,
        get_settings_summary,
        get_source_root,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SETTINGS_IMPORT_ERROR = import_exc

    LibrarySettings = Any  # type: ignore[assignment]

    def get_default_source_root() -> Path:
        """
        Ermittelt den Standard-Source-Root ohne config.library_settings.

        Erwarteter Pfad:
            services/vectoplan-library/src/library/source
        """
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
        return get_default_source_root()

    def get_library_settings(*, refresh: bool = False) -> Any:
        return None

    def get_library_scan_options(*, refresh: bool = False) -> Any:
        return None

    def get_library_read_options(*, refresh: bool = False) -> Any:
        return None

    def get_library_cache_options(*, refresh: bool = False) -> Any:
        return None

    def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
        source_root = get_default_source_root()

        return {
            "ok": False,
            "fallback_active": True,
            "source_root": str(source_root),
            "error": exception_to_dict(_SETTINGS_IMPORT_ERROR) if _SETTINGS_IMPORT_ERROR else None,
        }


try:
    from library.scanner.package_discovery import (
        PackageDiscoveryOptions,
        PackageDiscoveryResult,
        discover_library_packages,
    )
    from library.scanner.package_reader import (
        PackageReaderOptions,
        PackageReadResult,
        read_package_candidates,
    )
    from library.scanner.package_fingerprint import (
        PackageFingerprintOptions,
        PackageFingerprintResult,
        fingerprint_read_result,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SCANNER_IMPORT_ERROR = import_exc

    PackageDiscoveryOptions = Any  # type: ignore[assignment]
    PackageDiscoveryResult = Any  # type: ignore[assignment]
    PackageReaderOptions = Any  # type: ignore[assignment]
    PackageReadResult = Any  # type: ignore[assignment]
    PackageFingerprintOptions = Any  # type: ignore[assignment]
    PackageFingerprintResult = Any  # type: ignore[assignment]

    def discover_library_packages(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"package discovery is unavailable: {_SCANNER_IMPORT_ERROR}")

    def read_package_candidates(*args: Any, **kwargs: Any) -> list[Any]:
        raise RuntimeError(f"package reader is unavailable: {_SCANNER_IMPORT_ERROR}")

    def fingerprint_read_result(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"package fingerprint is unavailable: {_SCANNER_IMPORT_ERROR}")


try:
    from library.validation.library_package_validator import (
        LibraryPackageValidatorOptions,
        LibraryPackageValidationResult,
        validate_read_results,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _VALIDATION_IMPORT_ERROR = import_exc

    LibraryPackageValidatorOptions = Any  # type: ignore[assignment]
    LibraryPackageValidationResult = Any  # type: ignore[assignment]

    def validate_read_results(
        read_results: Iterable[Any],
        *,
        options: Any = None,
    ) -> list[Any]:
        result: list[dict[str, Any]] = []

        for read_result in read_results:
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
                    "errors": [] if ok else ["validation layer unavailable"],
                    "metadata": {
                        "taxonomy": get_item_attr(read_result, "metadata", default={}).get("taxonomy")
                        if isinstance(get_item_attr(read_result, "metadata", default={}), Mapping)
                        else {},
                    },
                }
            )

        return result


try:
    from library.read_models.block_summary_builder import (
        BlockSummaryBuilderOptions,
        build_library_items_from_results,
        clear_taxonomy_cache as clear_summary_taxonomy_cache,
    )
    from library.read_models.library_index_builder import (
        LibraryIndex,
        LibraryIndexBuilderOptions,
        build_blocks_response_from_index,
        build_index_response,
        build_library_index_from_items,
        build_tree_response_from_index,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _READ_MODELS_IMPORT_ERROR = import_exc

    BlockSummaryBuilderOptions = Any  # type: ignore[assignment]
    LibraryIndex = Any  # type: ignore[assignment]
    LibraryIndexBuilderOptions = Any  # type: ignore[assignment]

    def clear_summary_taxonomy_cache() -> None:
        return None

    def build_library_items_from_results(
        *,
        read_results: Iterable[Any],
        validation_results: Iterable[Any] | None = None,
        fingerprint_results: Iterable[Any] | None = None,
        options: Any = None,
    ) -> list[Any]:
        items: list[dict[str, Any]] = []

        for read_result in read_results:
            taxonomy = {}
            metadata = ensure_mapping(get_item_attr(read_result, "metadata"))
            if isinstance(metadata.get("taxonomy"), Mapping):
                taxonomy = dict(metadata.get("taxonomy"))

            family_id = (
                get_item_attr(read_result, "family_id")
                or get_item_attr(read_result, "package_id")
                or get_item_attr(read_result, "relative_package_root")
                or "unknown.library_item"
            )
            valid = bool(get_item_attr(read_result, "ok", default=False))
            normalized_id = normalize_stable_id(family_id, fallback="unknown.library_item")

            items.append(
                {
                    "id": normalized_id,
                    "family_id": normalized_id,
                    "package_id": get_item_attr(read_result, "package_id"),
                    "label": humanize_identifier(family_id),
                    "status": "valid" if valid else "invalid",
                    "enabled": True,
                    "domain": taxonomy.get("domain") or get_item_attr(read_result, "domain"),
                    "category": taxonomy.get("category") or get_item_attr(read_result, "category"),
                    "subcategory": taxonomy.get("subcategory") or get_item_attr(read_result, "subcategory"),
                    "source_path": get_item_attr(read_result, "package_root"),
                    "taxonomy": taxonomy,
                    "metadata": {
                        "taxonomy": taxonomy,
                    },
                    "validation": {
                        "valid": valid,
                        "warning_count": 0,
                        "error_count": 0 if valid else 1,
                        "fatal_count": 0,
                    },
                }
            )

        return items

    def build_library_index_from_items(
        items: Iterable[Any] | None,
        *,
        source_root: Any = None,
        options: Any = None,
    ) -> dict[str, Any]:
        item_list = list(items or ())
        include_invalid = safe_bool(get_item_attr(options, "include_invalid"), default=False)
        enabled_only = safe_bool(get_item_attr(options, "enabled_only"), default=False)

        visible_items: list[Any] = []
        invalid_items: list[Any] = []

        for item in item_list:
            if enabled_only and not safe_bool(get_item_attr(item, "enabled"), default=True):
                continue

            if get_item_status(item) == "valid":
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
            "count": len(visible_items),
            "invalid_count": len(invalid_items),
        }

    def build_blocks_response_from_index(index: Any, **kwargs: Any) -> dict[str, Any]:
        items = get_item_attr(index, "items", default=[])

        if isinstance(index, Mapping):
            items = index.get("items", [])

        item_list = list(items or ())

        return {
            "ok": True,
            "status": "ok" if item_list else "empty",
            "count": len(item_list),
            "items": [json_safe(item) for item in item_list],
        }

    def build_tree_response_from_index(index: Any) -> dict[str, Any]:
        items = get_item_attr(index, "items", default=[])

        if isinstance(index, Mapping):
            items = index.get("items", [])

        tree: dict[str, Any] = {}

        for item in items or ():
            item_payload = json_safe(item)
            if not isinstance(item_payload, Mapping):
                continue

            domain = safe_str(item_payload.get("domain"), default="unknown")
            category = safe_str(item_payload.get("category"), default="unknown")
            subcategory = safe_str(item_payload.get("subcategory"), default="unknown")

            tree.setdefault(domain, {})
            tree[domain].setdefault(category, {})
            tree[domain][category].setdefault(subcategory, [])
            tree[domain][category][subcategory].append(dict(item_payload))

        return {
            "ok": True,
            "status": "ok" if tree else "empty",
            "tree": tree,
            "stats": {
                "domain_count": len(tree),
            },
        }

    def build_index_response(index: Any) -> dict[str, Any]:
        return json_safe(index)


try:
    from library.domain.scan_result import (
        LibraryScanResult,
        build_error_scan_result,
        build_scan_result_from_items,
        monotonic_ms,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DOMAIN_IMPORT_ERROR = import_exc

    LibraryScanResult = Any  # type: ignore[assignment]

    def monotonic_ms() -> int:
        return monotonic_ms_safe()

    def build_error_scan_result(
        exc: BaseException,
        *,
        source_root: Any = None,
        started_at: Any = None,
        started_monotonic_ms: int | None = None,
        include_traceback: bool = False,
        settings: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
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
        }

    def build_scan_result_from_items(
        *,
        source_root: Any = None,
        items: Iterable[Any] | None = None,
        warnings: Iterable[Any] | None = None,
        errors: Iterable[Any] | None = None,
        started_at: Any = None,
        started_monotonic_ms: int | None = None,
        settings: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        item_list = list(items or ())
        valid_items = [
            item
            for item in item_list
            if get_item_status(item) == "valid"
        ]

        return {
            "ok": True,
            "status": "ok" if valid_items else "empty",
            "source_root": safe_path_str(source_root),
            "started_at": safe_str(started_at, default="") or utc_now_iso(),
            "finished_at": utc_now_iso(),
            "duration_ms": calculate_duration_ms(started_monotonic_ms),
            "candidate_count": len(item_list),
            "valid_count": len(valid_items),
            "invalid_count": len(item_list) - len(valid_items),
            "items": [json_safe(item) for item in item_list],
            "warnings": list(warnings or ()),
            "errors": list(errors or ()),
            "settings": dict(settings or {}),
            "metadata": dict(metadata or {}),
        }


try:
    from library.taxonomy import get_default_taxonomy_service
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _TAXONOMY_IMPORT_ERROR = import_exc
    get_default_taxonomy_service = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Taxonomy helpers
# ---------------------------------------------------------------------------

def taxonomy_available() -> bool:
    return get_default_taxonomy_service is not None and _TAXONOMY_IMPORT_ERROR is None


def get_taxonomy_service_safe() -> Any | None:
    if not taxonomy_available():
        return None

    try:
        return get_default_taxonomy_service()  # type: ignore[misc]
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
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        }

    try:
        return ensure_mapping(
            service.get_taxonomy_payload(
                include_inactive=include_inactive,
                include_tree=True,
                include_options=True,
                include_lookup=True,
                force_reload=force_reload,
            )
        )
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
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        }

    try:
        return ensure_mapping(
            service.health(
                force_reload=force_reload,
                include_registry_state=include_registry_state,
            )
        )
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

    text = safe_str(value, default="")
    return text or None


# ---------------------------------------------------------------------------
# Options / cache
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryScanServiceOptions:
    """
    Optionen für den Library Scan Service.
    """

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
) -> "LibraryScanServiceOptions":
    """
    Normalisiert Scan-Service-Optionen.

    Der Scan-Service wird aus mehreren Pfaden aufgerufen:
    - HTTP-Routen
    - DB-Sync-Service
    - CLI-/Debug-Code
    - Tests

    Einige dieser Pfade übergeben echte LibraryScanServiceOptions, andere
    übergeben dict/Mapping-Payloads. Ohne diese Normalisierung landet ein dict
    in der Pipeline und spätere Zugriffe wie `options.require_taxonomy` brechen
    mit:

        AttributeError: 'dict' object has no attribute 'require_taxonomy'

    Diese Funktion ist deshalb der zentrale Eingangsschutz für alle
    scan_library_source*-Funktionen.
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
            # Best-effort Objektadapter: nur bekannte Optionsfelder lesen.
            for field_name in LibraryScanServiceOptions.__dataclass_fields__:
                if hasattr(value, field_name):
                    data[field_name] = getattr(value, field_name)

    except Exception:
        return base

    if not data:
        return base

    # Aliase aus Routen-/Sync-Payloads auf die echten Scan-Service-Felder mappen.
    alias_map = {
        "require_taxonomy_validation": "validate_taxonomy",
        "require_taxonomy_service": "require_taxonomy",
        "validate_taxonomy_path": "validate_taxonomy",
        "use_taxonomy": "validate_taxonomy",
        "taxonomy_required": "require_taxonomy",
        "include_read_artifacts": "include_read_results",
        "include_raw_documents": "include_read_results",
    }

    for source_key, target_key in alias_map.items():
        if source_key in data and target_key not in data:
            data[target_key] = data[source_key]

    # include_read_artifacts soll bei Debug-/Sync-Tests optional auch die
    # Pipeline-Zwischenergebnisse freischalten, ohne Standardantworten zu blähen.
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
    """
    Interner Cache-Eintrag.

    Der Cache ist absichtlich simpel und optional. Standardmäßig ist er aus.
    """

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
        clear_summary_taxonomy_cache()
    except Exception:
        pass

    taxonomy_service = get_taxonomy_service_safe()
    if taxonomy_service is not None:
        try:
            taxonomy_service.clear_cache()
        except Exception:
            pass


def make_cache_key(
    source_root: Any = None,
    *,
    taxonomy_version: Any = None,
) -> str:
    """Baut Cache-Key aus Source-Root und Taxonomie-Version."""
    root_text = safe_path_str(source_root) or DEFAULT_CACHE_KEY
    version_text = safe_str(taxonomy_version, default="noversion")
    return f"{root_text}|taxonomy:{version_text}"


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

        object.__setattr__(self, "ok", bool(self.ok and status not in {"error", "invalid"}))
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
                if get_item_status(item) == "valid"
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
        """
        Antwort für:
            GET /api/v1/vplib/library/scan
        """
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
        """
        Antwort für:
            GET /api/v1/vplib/library/blocks
        """
        response = build_blocks_response_from_index(
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
        """
        Antwort für:
            GET /api/v1/vplib/library/tree
        """
        response = build_tree_response_from_index(self.index)

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
        return cls(**dict(data))
    except Exception:
        try:
            return cls()
        except Exception:
            return dict(data)


def make_discovery_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Discovery-Optionen defensiv und propagiert Taxonomieoptionen."""
    resolved_options = service_options or LibraryScanServiceOptions()

    try:
        if hasattr(PackageDiscoveryOptions, "from_settings"):
            try:
                base = PackageDiscoveryOptions.from_settings(get_library_scan_options())
            except TypeError:
                base = PackageDiscoveryOptions.from_settings()
        else:
            base = PackageDiscoveryOptions()

        data = object_to_options_dict(base)
        data["validate_taxonomy_path"] = resolved_options.validate_taxonomy
        data.setdefault("include_legacy_source_layout", True)
        data.setdefault("read_minimal_metadata", True)

        return rebuild_options_object(PackageDiscoveryOptions, data)

    except Exception:
        try:
            return PackageDiscoveryOptions()
        except Exception:
            return None


def make_reader_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Reader-Optionen defensiv."""
    try:
        if hasattr(PackageReaderOptions, "from_settings"):
            try:
                return PackageReaderOptions.from_settings(get_library_scan_options())
            except TypeError:
                return PackageReaderOptions.from_settings()

        return PackageReaderOptions()

    except Exception:
        try:
            return PackageReaderOptions()
        except Exception:
            return None


def make_fingerprint_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Fingerprint-Optionen defensiv."""
    try:
        return PackageFingerprintOptions()
    except Exception:
        return None


def make_validation_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Validation-Optionen defensiv und propagiert Taxonomiepflicht."""
    resolved_options = service_options or LibraryScanServiceOptions()

    try:
        base = LibraryPackageValidatorOptions()
        data = object_to_options_dict(base)

        # Namen verwenden, die LibraryPackageValidatorOptions direkt versteht.
        # Ältere Alias-Namen bleiben zusätzlich enthalten, falls ein älterer
        # Validator sie erwartet.
        data["require_taxonomy"] = resolved_options.require_taxonomy
        data["require_classification"] = resolved_options.validate_taxonomy
        data["strict_taxonomy"] = resolved_options.require_taxonomy
        data["allow_legacy_source_depth"] = True
        data["require_taxonomy_validation"] = resolved_options.validate_taxonomy
        data["require_taxonomy_service"] = resolved_options.require_taxonomy
        data.setdefault("allow_legacy_source_path", True)
        data.setdefault("require_manifest_taxonomy_match", True)
        data.setdefault("require_canonical_family_id", True)

        return rebuild_options_object(LibraryPackageValidatorOptions, data)

    except Exception:
        try:
            return LibraryPackageValidatorOptions()
        except Exception:
            return None


def make_summary_options(service_options: LibraryScanServiceOptions | None = None) -> Any:
    """Baut Summary-Builder-Optionen defensiv und propagiert Taxonomie-Labeling."""
    resolved_options = service_options or LibraryScanServiceOptions()

    try:
        return BlockSummaryBuilderOptions(
            include_invalid=True,
            enabled_only=False,
            sort=True,
            sort_by="classification",
            include_metadata=True,
            include_validation_details=False,
            include_taxonomy_labels=resolved_options.use_taxonomy_labels,
            force_taxonomy_reload=resolved_options.force_taxonomy_reload,
        )
    except TypeError:
        try:
            return BlockSummaryBuilderOptions(
                include_invalid=True,
                enabled_only=False,
                sort=True,
                sort_by="classification",
                include_metadata=True,
                include_validation_details=False,
            )
        except Exception:
            return None
    except Exception:
        try:
            return BlockSummaryBuilderOptions()
        except Exception:
            return None


def make_index_options(options: LibraryScanServiceOptions) -> Any:
    """Baut Index-Optionen aus Service-Optionen."""
    try:
        return LibraryIndexBuilderOptions(
            include_invalid=options.include_invalid,
            enabled_only=options.enabled_only,
            fail_on_duplicates=False,
            sort=True,
            sort_by="classification",
            include_tree=True,
            include_items_by_id=True,
            include_metadata=True,
            use_taxonomy_labels=options.use_taxonomy_labels,
            include_empty_taxonomy_nodes=options.include_empty_taxonomy_nodes,
            include_inactive_taxonomy_nodes=options.include_inactive_taxonomy_nodes,
            force_taxonomy_reload=options.force_taxonomy_reload,
        )
    except TypeError:
        try:
            return LibraryIndexBuilderOptions(
                include_invalid=options.include_invalid,
                enabled_only=options.enabled_only,
                fail_on_duplicates=False,
                sort=True,
                sort_by="classification",
                include_tree=True,
                include_items_by_id=True,
                include_metadata=True,
            )
        except Exception:
            return None
    except Exception:
        try:
            return LibraryIndexBuilderOptions()
        except Exception:
            return None


def discover_library_packages_safe(
    *,
    source_root: Path,
    options: Any = None,
    refresh_settings: bool = False,
) -> Any:
    """Führt Package Discovery mit Signatur-Fallbacks aus."""
    try:
        return discover_library_packages(
            source_root=source_root,
            options=options,
            refresh_settings=refresh_settings,
        )
    except TypeError:
        try:
            return discover_library_packages(
                source_root=source_root,
                options=options,
            )
        except TypeError:
            return discover_library_packages(source_root)
    except Exception:
        raise


def read_package_candidates_safe(
    candidates: Iterable[Any],
    *,
    options: Any = None,
) -> tuple[Any, ...]:
    """Liest Package Candidates mit Signatur-Fallbacks."""
    candidate_tuple = tuple(candidates or ())

    try:
        return tuple(read_package_candidates(candidate_tuple, options=options))
    except TypeError:
        try:
            return tuple(read_package_candidates(candidates=candidate_tuple, options=options))
        except TypeError:
            return tuple(read_package_candidates(candidate_tuple))
    except Exception:
        raise


def validate_read_results_safe(
    read_results: Iterable[Any],
    *,
    options: Any = None,
) -> tuple[Any, ...]:
    """Validiert ReadResults mit Signatur-Fallbacks."""
    read_result_tuple = tuple(read_results or ())

    try:
        return tuple(validate_read_results(read_result_tuple, options=options))
    except TypeError:
        try:
            return tuple(validate_read_results(read_results=read_result_tuple, options=options))
        except TypeError:
            return tuple(validate_read_results(read_result_tuple))
    except Exception:
        raise


def fingerprint_read_results_safe(
    read_results: Iterable[Any],
    *,
    options: Any = None,
) -> tuple[Any, ...]:
    """
    Erzeugt Fingerprints für ReadResults.
    Einzelne Fingerprint-Fehler zerstören nicht die gesamte Pipeline.
    """
    fingerprint_results: list[Any] = []

    for read_result in read_results or ():
        try:
            try:
                fingerprint_results.append(
                    fingerprint_read_result(
                        read_result,
                        options=options,
                    )
                )
            except TypeError:
                try:
                    fingerprint_results.append(
                        fingerprint_read_result(
                            read_result=read_result,
                            options=options,
                        )
                    )
                except TypeError:
                    fingerprint_results.append(
                        fingerprint_read_result(read_result)
                    )

        except Exception as fingerprint_exc:
            fingerprint_results.append(
                {
                    "ok": False,
                    "status": "error",
                    "revision_hash": None,
                    "package_id": get_item_attr(read_result, "package_id"),
                    "family_id": get_item_attr(read_result, "family_id"),
                    "errors": [str(fingerprint_exc)],
                    "error": exception_to_dict(fingerprint_exc),
                }
            )

    return tuple(fingerprint_results)


def build_library_items_from_results_safe(
    *,
    read_results: Iterable[Any],
    validation_results: Iterable[Any],
    fingerprint_results: Iterable[Any],
    options: Any = None,
) -> tuple[Any, ...]:
    """Baut LibraryItems mit Signatur-Fallbacks."""
    try:
        return tuple(
            build_library_items_from_results(
                read_results=tuple(read_results or ()),
                validation_results=tuple(validation_results or ()),
                fingerprint_results=tuple(fingerprint_results or ()),
                options=options,
            )
        )
    except TypeError:
        try:
            return tuple(
                build_library_items_from_results(
                    read_results=tuple(read_results or ()),
                    validation_results=tuple(validation_results or ()),
                    fingerprint_results=tuple(fingerprint_results or ()),
                )
            )
        except TypeError:
            return tuple(
                build_library_items_from_results(
                    tuple(read_results or ()),
                    tuple(validation_results or ()),
                    tuple(fingerprint_results or ()),
                )
            )
    except Exception:
        raise


def build_library_index_from_items_safe(
    items: Iterable[Any],
    *,
    source_root: Any = None,
    options: Any = None,
) -> Any:
    """Baut LibraryIndex mit Signatur-Fallbacks."""
    item_tuple = tuple(items or ())

    try:
        return build_library_index_from_items(
            item_tuple,
            source_root=source_root,
            options=options,
        )
    except TypeError:
        try:
            return build_library_index_from_items(
                items=item_tuple,
                source_root=source_root,
                options=options,
            )
        except TypeError:
            return build_library_index_from_items(item_tuple)
    except Exception:
        raise


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
    item_tuple = tuple(items or ())
    warning_tuple = tuple_of_strings(warnings)
    error_tuple = tuple_of_strings(errors)

    try:
        return build_scan_result_from_items(
            source_root=source_root,
            items=item_tuple,
            warnings=warning_tuple,
            errors=error_tuple,
            started_at=started_at,
            started_monotonic_ms=started_monotonic_ms,
            settings=settings or {},
            metadata=metadata or {},
        )
    except TypeError:
        try:
            return build_scan_result_from_items(
                source_root=source_root,
                items=item_tuple,
                warnings=warning_tuple,
                errors=error_tuple,
                settings=settings or {},
                metadata=metadata or {},
            )
        except TypeError:
            return {
                "ok": True,
                "status": "ok" if item_tuple else "empty",
                "source_root": safe_path_str(source_root),
                "started_at": safe_str(started_at, default="") or utc_now_iso(),
                "finished_at": utc_now_iso(),
                "duration_ms": calculate_duration_ms(started_monotonic_ms),
                "items": [json_safe(item) for item in item_tuple],
                "warnings": list(warning_tuple),
                "errors": list(error_tuple),
                "settings": dict(settings or {}),
                "metadata": dict(metadata or {}),
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
    try:
        return build_error_scan_result(
            exc,
            source_root=source_root,
            started_at=started_at,
            started_monotonic_ms=started_monotonic_ms,
            include_traceback=include_traceback,
            settings=settings or {},
        )
    except TypeError:
        try:
            return build_error_scan_result(
                exc,
                source_root=source_root,
                started_at=started_at,
                settings=settings or {},
            )
        except TypeError:
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

    deduped: list[str] = []

    for warning in warnings:
        if warning not in deduped:
            deduped.append(warning)

    return deduped


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

    deduped: list[str] = []

    for error in errors:
        if error not in deduped:
            deduped.append(error)

    return deduped


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
        if get_item_status(item) == "valid"
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
    options: LibraryScanServiceOptions | None = None,
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
            include_invalid=service_options.include_invalid,
            enabled_only=service_options.enabled_only,
            use_cache=service_options.use_cache,
            cache_ttl_seconds=service_options.cache_ttl_seconds,
            refresh_settings=bool(refresh_settings),
            include_raw_pipeline=service_options.include_raw_pipeline,
            include_index=service_options.include_index,
            include_scan_result=service_options.include_scan_result,
            include_discovery_result=service_options.include_discovery_result,
            include_read_results=service_options.include_read_results,
            include_validation_results=service_options.include_validation_results,
            include_fingerprint_results=service_options.include_fingerprint_results,
            strict_errors=service_options.strict_errors,
            validate_taxonomy=service_options.validate_taxonomy,
            require_taxonomy=service_options.require_taxonomy,
            use_taxonomy_labels=service_options.use_taxonomy_labels,
            include_empty_taxonomy_nodes=service_options.include_empty_taxonomy_nodes,
            include_inactive_taxonomy_nodes=service_options.include_inactive_taxonomy_nodes,
            include_taxonomy_payload=service_options.include_taxonomy_payload,
            force_taxonomy_reload=service_options.force_taxonomy_reload,
        )

    started_at = utc_now_iso()
    started_monotonic = monotonic_ms()

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
            ok=status not in {"error", "invalid"},
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
        )


def scan_library_source_no_cache(
    *,
    source_root: Any = None,
    options: LibraryScanServiceOptions | None = None,
) -> LibraryScanPipelineResult:
    """Führt Scan ohne Cache aus."""
    service_options = coerce_scan_service_options(options)

    service_options = LibraryScanServiceOptions(
        include_invalid=service_options.include_invalid,
        enabled_only=service_options.enabled_only,
        use_cache=False,
        cache_ttl_seconds=service_options.cache_ttl_seconds,
        refresh_settings=service_options.refresh_settings,
        include_raw_pipeline=service_options.include_raw_pipeline,
        include_index=service_options.include_index,
        include_scan_result=service_options.include_scan_result,
        include_discovery_result=service_options.include_discovery_result,
        include_read_results=service_options.include_read_results,
        include_validation_results=service_options.include_validation_results,
        include_fingerprint_results=service_options.include_fingerprint_results,
        strict_errors=service_options.strict_errors,
        validate_taxonomy=service_options.validate_taxonomy,
        require_taxonomy=service_options.require_taxonomy,
        use_taxonomy_labels=service_options.use_taxonomy_labels,
        include_empty_taxonomy_nodes=service_options.include_empty_taxonomy_nodes,
        include_inactive_taxonomy_nodes=service_options.include_inactive_taxonomy_nodes,
        include_taxonomy_payload=service_options.include_taxonomy_payload,
        force_taxonomy_reload=service_options.force_taxonomy_reload,
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
    options: LibraryScanServiceOptions | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Baut Antwort für:
        GET /api/v1/vplib/library/scan
    """
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
    options: LibraryScanServiceOptions | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Baut Antwort für:
        GET /api/v1/vplib/library/blocks
    """
    service_options = coerce_scan_service_options(options)

    service_options = LibraryScanServiceOptions(
        include_invalid=service_options.include_invalid,
        enabled_only=service_options.enabled_only,
        use_cache=service_options.use_cache,
        cache_ttl_seconds=service_options.cache_ttl_seconds,
        refresh_settings=service_options.refresh_settings,
        include_raw_pipeline=False,
        include_index=True,
        include_scan_result=False,
        include_discovery_result=False,
        include_read_results=False,
        include_validation_results=False,
        include_fingerprint_results=False,
        strict_errors=service_options.strict_errors,
        validate_taxonomy=service_options.validate_taxonomy,
        require_taxonomy=service_options.require_taxonomy,
        use_taxonomy_labels=service_options.use_taxonomy_labels,
        include_empty_taxonomy_nodes=service_options.include_empty_taxonomy_nodes,
        include_inactive_taxonomy_nodes=service_options.include_inactive_taxonomy_nodes,
        include_taxonomy_payload=False,
        force_taxonomy_reload=service_options.force_taxonomy_reload,
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
        },
    )

    return response


def get_library_tree_response(
    *,
    source_root: Any = None,
    options: LibraryScanServiceOptions | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Baut Antwort für:
        GET /api/v1/vplib/library/tree
    """
    service_options = coerce_scan_service_options(options)

    service_options = LibraryScanServiceOptions(
        include_invalid=service_options.include_invalid,
        enabled_only=service_options.enabled_only,
        use_cache=service_options.use_cache,
        cache_ttl_seconds=service_options.cache_ttl_seconds,
        refresh_settings=service_options.refresh_settings,
        include_raw_pipeline=False,
        include_index=True,
        include_scan_result=False,
        include_discovery_result=False,
        include_read_results=False,
        include_validation_results=False,
        include_fingerprint_results=False,
        strict_errors=service_options.strict_errors,
        validate_taxonomy=service_options.validate_taxonomy,
        require_taxonomy=service_options.require_taxonomy,
        use_taxonomy_labels=service_options.use_taxonomy_labels,
        include_empty_taxonomy_nodes=service_options.include_empty_taxonomy_nodes,
        include_inactive_taxonomy_nodes=service_options.include_inactive_taxonomy_nodes,
        include_taxonomy_payload=False,
        force_taxonomy_reload=service_options.force_taxonomy_reload,
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
        },
    )

    return response


def get_library_index(
    *,
    source_root: Any = None,
    options: LibraryScanServiceOptions | None = None,
    force_refresh: bool = False,
) -> Any:
    """Gibt nur den LibraryIndex zurück."""
    result = scan_library_source(
        source_root=source_root,
        options=options,
        force_refresh=force_refresh,
    )

    return result.index


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_import_status() -> dict[str, Any]:
    """Liefert Importstatus optionaler Abhängigkeiten."""
    return {
        "settings": {
            "ok": _SETTINGS_IMPORT_ERROR is None,
            "error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
        },
        "scanner": {
            "ok": _SCANNER_IMPORT_ERROR is None,
            "error": exception_to_dict(_SCANNER_IMPORT_ERROR),
        },
        "validation": {
            "ok": _VALIDATION_IMPORT_ERROR is None,
            "error": exception_to_dict(_VALIDATION_IMPORT_ERROR),
        },
        "read_models": {
            "ok": _READ_MODELS_IMPORT_ERROR is None,
            "error": exception_to_dict(_READ_MODELS_IMPORT_ERROR),
        },
        "domain": {
            "ok": _DOMAIN_IMPORT_ERROR is None,
            "error": exception_to_dict(_DOMAIN_IMPORT_ERROR),
        },
        "taxonomy": {
            "ok": _TAXONOMY_IMPORT_ERROR is None,
            "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
        },
    }


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
            if name in {"scanner", "validation", "read_models", "taxonomy"}:
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
    "get_item_id",
    "get_item_status",
    "get_result_status",
    "result_is_ok",
    "result_is_valid",
    "monotonic_ms_safe",
    "calculate_duration_ms",
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
    "build_library_items_from_results_safe",
    "build_library_index_from_items_safe",
    "build_scan_result_from_items_safe",
    "build_error_scan_result_safe",
    "collect_pipeline_warnings",
    "collect_pipeline_errors",
    "derive_pipeline_status",
    "scan_library_source",
    "scan_library_source_no_cache",
    "get_library_scan_response",
    "get_library_blocks_response",
    "get_library_tree_response",
    "get_library_index",
    "get_import_status",
    "get_library_scan_service_health",
    "assert_library_scan_service_ready",
)