# services/vectoplan-library/src/library/scanner/package_discovery.py
"""
Package Discovery für die VECTOPLAN Creative-Library-Schicht.

Diese Datei ist die erste Stufe des Backend-Scanners.

Aufgabe:

- `src/library/source` durchsuchen
- mögliche VPLIB-Package-Roots erkennen
- Kandidatenordner melden
- neue kanonische Taxonomie-Pfade erkennen:
    {domain}/{category}/{subcategory}/{family_slug}
- alte Legacy-Pfade kontrolliert erkennen:
    {domain}/{category}/{family_slug}
- nur minimale optionale Metadaten lesen
- keine vollständige fachliche Package-Validierung ausführen
- keine Dateien schreiben
- keine Pakete nach `creative_library` kopieren

Ein Ordner gilt als VPLIB-Kandidat, wenn er mindestens eine erlaubte
Manifest-Datei enthält, standardmäßig:

    vplib.manifest.json

Kanonisches Beispiel:

    src/library/source/hochbau/waende/aussenwaende/ziegelwand/
      vplib.manifest.json
      vplib.modules.json
      family/
      variants/
      editor/
      render/
      physical/
      manufacturer/

Legacy-Beispiel:

    src/library/source/hochbau/bloecke/basic_stone_block/
      vplib.manifest.json

Diese Datei ist bewusst robust und isoliert:

- keine Flask-Abhängigkeit
- keine Datenbank-Abhängigkeit
- kein Import aus Reader
- kein Import aus Validator
- keine Seiteneffekte beim Import
- defensive Settings-Integration
- sichere Rekursion mit max_depth
- Symlink-Schutz
- Ignorierlisten
- JSON-kompatible Resultate
- Taxonomie-Import ist optional, aber bei Verfügbarkeit wird der Pfad geprüft

Version 0.2.0:

- Unterstützt kanonische Taxonomie-Pfade mit Tiefe 4.
- Unterstützt Legacy-Pfade mit Tiefe 3 als Warnung.
- Kandidaten enthalten Taxonomie-Metadaten:
    layout, domain, category, subcategory, family_slug, source_path.
- Discovery bleibt Kandidatenfindung; finale Gültigkeit bleibt Aufgabe des
  `library_package_validator`.
"""

from __future__ import annotations

import json
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

PACKAGE_DISCOVERY_VERSION: Final[str] = "0.2.0"
PACKAGE_DISCOVERY_COMPONENT: Final[str] = "library-package-discovery"

DEFAULT_DISCOVERY_MODE: Final[str] = "filesystem"
DEFAULT_DISCOVERY_STATUS: Final[str] = "unknown"

PACKAGE_MARKER_REASON_MANIFEST: Final[str] = "manifest_found"
PACKAGE_MARKER_REASON_SKIPPED_IGNORED_DIR: Final[str] = "ignored_directory"
PACKAGE_MARKER_REASON_SKIPPED_MAX_DEPTH: Final[str] = "max_depth_reached"
PACKAGE_MARKER_REASON_SKIPPED_SYMLINK: Final[str] = "symlink_skipped"
PACKAGE_MARKER_REASON_SKIPPED_NOT_DIRECTORY: Final[str] = "not_directory"
PACKAGE_MARKER_REASON_SKIPPED_OUTSIDE_SOURCE_ROOT: Final[str] = "outside_source_root"
PACKAGE_MARKER_REASON_SKIPPED_SYMLINK_LOOP: Final[str] = "symlink_loop_skipped"
PACKAGE_MARKER_REASON_SKIPPED_LEGACY: Final[str] = "legacy_source_layout_skipped"

VALID_DISCOVERY_STATUSES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "empty",
    "partial",
    "error",
)

VALID_DISCOVERY_CANDIDATE_STATUSES: Final[tuple[str, ...]] = (
    "candidate",
    "skipped",
    "error",
)

DEFAULT_ALLOWED_MANIFEST_FILENAMES_FALLBACK: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
)

DEFAULT_IGNORED_DIRECTORY_NAMES_FALLBACK: Final[tuple[str, ...]] = (
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
)

DEFAULT_SCAN_FOLLOW_SYMLINKS_FALLBACK: Final[bool] = False
DEFAULT_SCAN_MAX_DEPTH_FALLBACK: Final[int] = 12
DEFAULT_SCAN_RECURSIVE_FALLBACK: Final[bool] = True
DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT_FALLBACK: Final[bool] = True
DEFAULT_VALIDATE_TAXONOMY_PATH_FALLBACK: Final[bool] = True
DEFAULT_READ_MINIMAL_METADATA_FALLBACK: Final[bool] = True

MAX_SCAN_DEPTH_HARD_LIMIT: Final[int] = 200

CANONICAL_SOURCE_DEPTH: Final[int] = 4
LEGACY_SOURCE_DEPTH: Final[int] = 3

SOURCE_LAYOUT_CANONICAL: Final[str] = "canonical"
SOURCE_LAYOUT_LEGACY: Final[str] = "legacy"
SOURCE_LAYOUT_UNKNOWN: Final[str] = "unknown"

SOURCE_ROOT_ENV_NAMES: Final[tuple[str, ...]] = (
    "VECTOPLAN_LIBRARY_SOURCE_ROOT",
    "VPLIB_CREATE_SOURCE_ROOT",
    "LIBRARY_SOURCE_ROOT",
)


# ---------------------------------------------------------------------------
# Generic helpers used before optional imports
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def monotonic_ms_safe() -> int:
    """Monotonic-Zeit in Millisekunden."""
    try:
        return int(time.monotonic() * 1000)
    except Exception:
        return 0


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

        text = str(value).strip().lower()

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

        text = str(value).strip()

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


def ensure_dict(value: Any) -> dict[str, Any]:
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


def normalize_path_for_id(path: Any) -> str:
    """Erzeugt eine stabile Kandidaten-ID aus einem Pfad."""
    text = safe_str(path, default="unknown.candidate").replace("\\", "/")
    text = text.strip("/").lower()

    result: list[str] = []

    for char in text:
        if char.isalnum() or char in "._:-":
            result.append(char)
        elif char in {"/", " ", "-"}:
            result.append(".")
        else:
            result.append("_")

    candidate_id = "".join(result)

    while ".." in candidate_id:
        candidate_id = candidate_id.replace("..", ".")

    candidate_id = candidate_id.strip("._:-")

    return candidate_id or "unknown.candidate"


def tuple_of_strings(value: Any) -> tuple[str, ...]:
    """Normalisiert Werte zu tuple[str, ...]."""
    try:
        if value is None:
            return ()

        if isinstance(value, str):
            text = value.strip()
            return (text,) if text else ()

        if isinstance(value, Mapping):
            return tuple(
                safe_str(key, default="")
                for key in value.keys()
                if safe_str(key, default="")
            )

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


def path_is_relative_to(path: Path, parent: Path) -> bool:
    """Kompatibler `is_relative_to`-Check."""
    try:
        path.relative_to(parent)
        return True
    except Exception:
        return False


def make_relative_path(path: Path, root: Path) -> str:
    """Berechnet einen relativen Pfad robust."""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def calculate_depth(path: Path, root: Path) -> int:
    """
    Berechnet die Tiefe eines Pfads relativ zum Source-Root.

    Source-Root selbst hat Tiefe 0.
    """
    try:
        relative = path.relative_to(root)

        if str(relative) == ".":
            return 0

        return len(relative.parts)

    except Exception:
        return 0


def get_attr_or_key(value: Any, key: str, *, default: Any = None) -> Any:
    """Liest Mapping-Key oder Attribut."""
    try:
        if value is None:
            return default

        if isinstance(value, Mapping):
            return value.get(key, default)

        return getattr(value, key, default)

    except Exception:
        return default


def first_non_empty(*values: Any, default: Any = None) -> Any:
    """Liefert den ersten nicht-leeren Wert."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, (list, tuple, set, dict)) and not value:
            continue

        return value

    return default


def deep_get(data: Mapping[str, Any] | None, path: str, *, default: Any = None) -> Any:
    """Liest einen Dotted Path aus einem Mapping."""
    if not isinstance(data, Mapping):
        return default

    current: Any = data

    try:
        for part in path.split("."):
            if not isinstance(current, Mapping):
                return default
            if part not in current:
                return default
            current = current[part]

        return current
    except Exception:
        return default


def fallback_normalize_slug(value: Any, *, default: str = "") -> str:
    """Fallback-Slug-Normalisierung."""
    try:
        text = safe_str(value, default="").lower()
        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

        chars: list[str] = []
        previous_sep = False

        for char in text:
            if char.isalnum():
                chars.append(char)
                previous_sep = False
            else:
                if not previous_sep:
                    chars.append("_")
                    previous_sep = True

        normalized = "".join(chars).strip("_-")
        return normalized or default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_SETTINGS_IMPORT_ERROR: BaseException | None = None
_SCAN_RESULT_IMPORT_ERROR: BaseException | None = None
_TAXONOMY_IMPORT_ERROR: BaseException | None = None

try:
    from config.library_settings import (
        DEFAULT_ALLOWED_MANIFEST_FILENAMES,
        DEFAULT_IGNORED_DIRECTORY_NAMES,
        DEFAULT_SCAN_FOLLOW_SYMLINKS,
        DEFAULT_SCAN_MAX_DEPTH,
        DEFAULT_SCAN_RECURSIVE,
        LibraryScanOptions,
        get_library_scan_options,
        get_settings_summary,
        get_source_root,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SETTINGS_IMPORT_ERROR = import_exc

    DEFAULT_ALLOWED_MANIFEST_FILENAMES = DEFAULT_ALLOWED_MANIFEST_FILENAMES_FALLBACK
    DEFAULT_IGNORED_DIRECTORY_NAMES = DEFAULT_IGNORED_DIRECTORY_NAMES_FALLBACK
    DEFAULT_SCAN_FOLLOW_SYMLINKS = DEFAULT_SCAN_FOLLOW_SYMLINKS_FALLBACK
    DEFAULT_SCAN_MAX_DEPTH = DEFAULT_SCAN_MAX_DEPTH_FALLBACK
    DEFAULT_SCAN_RECURSIVE = DEFAULT_SCAN_RECURSIVE_FALLBACK
    LibraryScanOptions = Any  # type: ignore[assignment]

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
        return get_default_source_root()

    def get_library_scan_options(*, refresh: bool = False) -> Any:
        return None

    def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
        return {
            "ok": False,
            "fallback_active": True,
            "source_root": str(get_default_source_root()),
            "error": exception_to_dict(_SETTINGS_IMPORT_ERROR) if _SETTINGS_IMPORT_ERROR else None,
        }


try:
    from library.domain.scan_result import (
        LibraryScanCandidate,
        LibraryScanCandidateStatus,
        LibraryScanMessage,
        monotonic_ms,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SCAN_RESULT_IMPORT_ERROR = import_exc

    class LibraryScanCandidateStatus:  # type: ignore[no-redef]
        CANDIDATE = type("StatusValue", (), {"value": "candidate"})()
        SKIPPED = type("StatusValue", (), {"value": "skipped"})()
        ERROR = type("StatusValue", (), {"value": "error"})()

    @dataclass(frozen=True)
    class LibraryScanMessage:  # type: ignore[no-redef]
        level: str
        message: str
        code: str | None = None
        path: str | None = None
        document_key: str | None = None
        data: dict[str, Any] = field(default_factory=dict)

        def to_dict(self) -> dict[str, Any]:
            return {
                "level": self.level,
                "message": self.message,
                "code": self.code,
                "path": self.path,
                "document_key": self.document_key,
                "data": self.data,
            }

    @dataclass(frozen=True)
    class LibraryScanCandidate:  # type: ignore[no-redef]
        candidate_id: str
        status: str = "candidate"
        valid: bool = False
        source_path: str | None = None
        package_root: str | None = None
        relative_package_root: str | None = None
        manifest_path: str | None = None
        discovered_at: str | None = None
        warnings: tuple[str, ...] = field(default_factory=tuple)
        errors: tuple[str, ...] = field(default_factory=tuple)
        metadata: dict[str, Any] = field(default_factory=dict)

        @classmethod
        def from_raw(cls, **kwargs: Any) -> "LibraryScanCandidate":
            return cls(
                candidate_id=str(kwargs.get("candidate_id") or "unknown.candidate"),
                status=str(kwargs.get("status") or "candidate"),
                valid=bool(kwargs.get("valid", False)),
                source_path=safe_path_str(kwargs.get("source_path")),
                package_root=safe_path_str(kwargs.get("package_root")),
                relative_package_root=safe_path_str(kwargs.get("relative_package_root")),
                manifest_path=safe_path_str(kwargs.get("manifest_path")),
                discovered_at=safe_str(kwargs.get("discovered_at"), default="") or None,
                warnings=tuple_of_strings(kwargs.get("warnings")),
                errors=tuple_of_strings(kwargs.get("errors")),
                metadata=dict(kwargs.get("metadata") or {}),
            )

        def to_dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return asdict(self)

    def monotonic_ms() -> int:
        return monotonic_ms_safe()


try:
    from library.taxonomy import (
        get_default_taxonomy_service,
        normalize_slug as taxonomy_normalize_slug,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _TAXONOMY_IMPORT_ERROR = import_exc
    get_default_taxonomy_service = None  # type: ignore[assignment]
    taxonomy_normalize_slug = fallback_normalize_slug  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Taxonomy helpers
# ---------------------------------------------------------------------------

def taxonomy_available() -> bool:
    """Prüft, ob der Taxonomie-Service importierbar ist."""
    return get_default_taxonomy_service is not None and _TAXONOMY_IMPORT_ERROR is None


def normalize_taxonomy_part(value: Any) -> str:
    """Normalisiert ein Taxonomie-Segment."""
    return taxonomy_normalize_slug(value, default="")


def normalize_source_path_parts(value: Any) -> tuple[str, ...]:
    """Normalisiert einen Source-Pfad in Slug-Segmente."""
    if value is None:
        return tuple()

    if isinstance(value, Path):
        raw_parts = value.parts
    elif isinstance(value, str):
        raw_parts = value.replace("\\", "/").split("/")
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        raw_parts = list(value)
    else:
        raw_parts = str(value).replace("\\", "/").split("/")

    result: list[str] = []

    for part in raw_parts:
        text = safe_str(part, default="")

        if not text or text in {".", ".."}:
            continue

        if text.endswith(":"):
            continue

        slug = normalize_taxonomy_part(text)
        if slug:
            result.append(slug)

    return tuple(result)


def normalize_source_path_string(value: Any) -> str:
    """Normalisiert Source-Pfad auf Slash-Syntax."""
    return "/".join(normalize_source_path_parts(value))


def infer_source_layout(parts: Sequence[str]) -> str:
    """Leitet Layout aus relativer Pfadtiefe ab."""
    normalized_parts = tuple(normalize_source_path_parts(parts))

    if len(normalized_parts) == CANONICAL_SOURCE_DEPTH:
        return SOURCE_LAYOUT_CANONICAL

    if len(normalized_parts) == LEGACY_SOURCE_DEPTH:
        return SOURCE_LAYOUT_LEGACY

    return SOURCE_LAYOUT_UNKNOWN


def taxonomy_from_relative_path(relative_package_root: Any) -> dict[str, Any]:
    """Extrahiert Taxonomie-Segmente aus dem relativen Package-Pfad."""
    parts = normalize_source_path_parts(relative_package_root)
    layout = infer_source_layout(parts)

    if layout == SOURCE_LAYOUT_CANONICAL:
        return {
            "layout": SOURCE_LAYOUT_CANONICAL,
            "parts": parts,
            "domain": parts[0],
            "category": parts[1],
            "subcategory": parts[2],
            "family_slug": parts[3],
            "source_path": "/".join(parts),
            "classification_path": "/".join(parts[:3]),
        }

    if layout == SOURCE_LAYOUT_LEGACY:
        return {
            "layout": SOURCE_LAYOUT_LEGACY,
            "parts": parts,
            "domain": parts[0],
            "category": parts[1],
            "subcategory": "",
            "family_slug": parts[2],
            "source_path": "/".join(parts),
            "classification_path": "/".join(parts[:2]),
        }

    return {
        "layout": SOURCE_LAYOUT_UNKNOWN,
        "parts": parts,
        "domain": parts[0] if len(parts) >= 1 else "",
        "category": parts[1] if len(parts) >= 2 else "",
        "subcategory": parts[2] if len(parts) >= 3 else "",
        "family_slug": parts[-1] if parts else "",
        "source_path": "/".join(parts),
        "classification_path": "/".join(parts[:3]) if len(parts) >= 3 else "/".join(parts),
    }


def read_json_object(path: Path) -> dict[str, Any]:
    """Liest ein JSON-Objekt defensiv."""
    try:
        if not path.exists() or not path.is_file():
            return {}

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, Mapping):
            return dict(data)

        return {}
    except Exception:
        return {}


def read_minimal_package_metadata(package_root: Path, *, manifest_path: Path) -> dict[str, Any]:
    """
    Liest nur minimale Metadaten aus bekannten JSON-Dateien.

    Keine vollständige Validierung. Keine Dokumentnormalisierung. Keine Reader-
    Abhängigkeit.
    """
    manifest = read_json_object(manifest_path)
    classification = read_json_object(package_root / "family" / "classification.json")
    identity = read_json_object(package_root / "family" / "identity.json")

    domain = first_non_empty(
        manifest.get("domain"),
        deep_get(manifest, "classification.domain"),
        classification.get("domain"),
        deep_get(classification, "classification.domain"),
    )
    category = first_non_empty(
        manifest.get("category"),
        deep_get(manifest, "classification.category"),
        classification.get("category"),
        deep_get(classification, "classification.category"),
    )
    subcategory = first_non_empty(
        manifest.get("subcategory"),
        deep_get(manifest, "classification.subcategory"),
        classification.get("subcategory"),
        deep_get(classification, "classification.subcategory"),
    )

    source_path = first_non_empty(
        manifest.get("source_path"),
        classification.get("source_path"),
        deep_get(classification, "classification.source_path"),
    )
    classification_path = first_non_empty(
        manifest.get("classification_path"),
        deep_get(manifest, "classification.path"),
        classification.get("classification_path"),
        deep_get(classification, "classification.path"),
    )
    taxonomy_version = first_non_empty(
        manifest.get("taxonomy_version"),
        deep_get(manifest, "classification.taxonomy_version"),
        classification.get("taxonomy_version"),
        deep_get(classification, "classification.taxonomy_version"),
    )

    package_id = first_non_empty(
        manifest.get("package_id"),
        manifest.get("id"),
    )
    family_id = first_non_empty(
        manifest.get("family_id"),
        identity.get("family_id"),
        identity.get("id"),
    )
    object_kind = first_non_empty(
        manifest.get("object_kind"),
        classification.get("object_kind"),
        identity.get("object_kind"),
    )
    family_slug = first_non_empty(
        identity.get("slug"),
        identity.get("family_slug"),
        manifest.get("family_slug"),
    )
    label = first_non_empty(
        identity.get("label"),
        identity.get("name"),
        manifest.get("family_name"),
        manifest.get("label"),
    )

    return {
        "package_id": safe_str(package_id, default="") or None,
        "family_id": safe_str(family_id, default="") or None,
        "object_kind": normalize_taxonomy_part(object_kind) or None,
        "taxonomy_version": safe_str(taxonomy_version, default="") or None,
        "domain": normalize_taxonomy_part(domain) or None,
        "category": normalize_taxonomy_part(category) or None,
        "subcategory": normalize_taxonomy_part(subcategory) or None,
        "source_path": normalize_source_path_string(source_path) or None,
        "classification_path": normalize_source_path_string(classification_path) or None,
        "family_slug": normalize_taxonomy_part(family_slug) or None,
        "label": safe_str(label, default="") or None,
    }


def build_taxonomy_discovery_metadata(
    *,
    source_root: Path,
    package_root: Path,
    manifest_path: Path,
    read_metadata: bool,
    validate_taxonomy_path: bool,
) -> tuple[dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    """
    Baut Taxonomie-Metadaten für einen Package-Kandidaten.

    Rückgabe:
        metadata, warnings, errors
    """
    warnings: list[str] = []
    errors: list[str] = []

    relative_package_root = make_relative_path(
        safe_resolve(package_root),
        safe_resolve(source_root),
    )
    path_taxonomy = taxonomy_from_relative_path(relative_package_root)
    document_metadata = (
        read_minimal_package_metadata(package_root, manifest_path=manifest_path)
        if read_metadata
        else {}
    )

    layout = path_taxonomy["layout"]
    domain = path_taxonomy["domain"]
    category = path_taxonomy["category"]
    subcategory = path_taxonomy["subcategory"]
    family_slug = path_taxonomy["family_slug"]

    if layout == SOURCE_LAYOUT_LEGACY:
        warnings.append(
            "Legacy source layout detected. New packages should use domain/category/subcategory/family_slug."
        )
    elif layout == SOURCE_LAYOUT_UNKNOWN:
        warnings.append(
            "Unknown source layout detected. Expected canonical domain/category/subcategory/family_slug."
        )

    doc_domain = safe_str(document_metadata.get("domain"), default="")
    doc_category = safe_str(document_metadata.get("category"), default="")
    doc_subcategory = safe_str(document_metadata.get("subcategory"), default="")
    doc_source_path = safe_str(document_metadata.get("source_path"), default="")
    doc_family_slug = safe_str(document_metadata.get("family_slug"), default="")

    if doc_domain and domain and doc_domain != domain:
        errors.append(f"Document domain '{doc_domain}' does not match path domain '{domain}'.")

    if doc_category and category and doc_category != category:
        errors.append(f"Document category '{doc_category}' does not match path category '{category}'.")

    if layout == SOURCE_LAYOUT_CANONICAL and doc_subcategory and subcategory and doc_subcategory != subcategory:
        errors.append(
            f"Document subcategory '{doc_subcategory}' does not match path subcategory '{subcategory}'."
        )

    if doc_family_slug and family_slug and doc_family_slug != family_slug:
        warnings.append(
            f"Document family_slug '{doc_family_slug}' does not match path family_slug '{family_slug}'."
        )

    expected_source_path = path_taxonomy["source_path"]
    if layout == SOURCE_LAYOUT_CANONICAL and doc_source_path and doc_source_path != expected_source_path:
        warnings.append(
            f"Document source_path '{doc_source_path}' does not match path '{expected_source_path}'."
        )

    taxonomy_validation: dict[str, Any] = {
        "attempted": False,
        "available": taxonomy_available(),
        "valid": None,
        "issues": [],
    }

    if validate_taxonomy_path and layout == SOURCE_LAYOUT_CANONICAL:
        if taxonomy_available():
            try:
                taxonomy_service = get_default_taxonomy_service()  # type: ignore[misc]
                validation = taxonomy_service.validate_selection(
                    domain,
                    category,
                    subcategory,
                    object_kind=document_metadata.get("object_kind") or "",
                )
                validation_payload = validation.to_dict() if hasattr(validation, "to_dict") else {}

                taxonomy_validation = {
                    "attempted": True,
                    "available": True,
                    "valid": bool(getattr(validation, "valid", False)),
                    "issues": validation_payload.get("issues", []),
                }

                for issue in getattr(validation, "issues", []) or []:
                    issue_payload = issue.to_dict() if hasattr(issue, "to_dict") else {}
                    severity = safe_str(issue_payload.get("severity"), default="error")
                    message = safe_str(issue_payload.get("message"), default="taxonomy issue")

                    if severity == "error":
                        errors.append(message)
                    elif severity == "warning":
                        warnings.append(message)
            except Exception as exc:
                warnings.append(f"Taxonomy validation failed during discovery: {exc}")
                taxonomy_validation = {
                    "attempted": True,
                    "available": True,
                    "valid": None,
                    "error": exception_to_dict(exc),
                    "issues": [],
                }
        else:
            warnings.append("Taxonomy service unavailable; path validation skipped.")
            taxonomy_validation = {
                "attempted": False,
                "available": False,
                "valid": None,
                "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
                "issues": [],
            }

    metadata = {
        "taxonomy": {
            "layout": layout,
            "canonical": layout == SOURCE_LAYOUT_CANONICAL,
            "legacy": layout == SOURCE_LAYOUT_LEGACY,
            "path_parts": list(path_taxonomy["parts"]),
            "domain": domain,
            "category": category,
            "subcategory": subcategory,
            "family_slug": family_slug,
            "source_path": path_taxonomy["source_path"],
            "classification_path": path_taxonomy["classification_path"],
            "document": document_metadata,
            "validation": taxonomy_validation,
        }
    }

    return metadata, tuple(warnings), tuple(errors)


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def normalize_manifest_filenames(value: Any) -> tuple[str, ...]:
    """Normalisiert erlaubte Manifest-Dateinamen."""
    filenames = tuple_of_strings(value)

    if not filenames:
        filenames = tuple(DEFAULT_ALLOWED_MANIFEST_FILENAMES)

    normalized: list[str] = []

    for filename in filenames:
        clean = filename.replace("\\", "/").split("/")[-1].strip()

        if clean and clean not in normalized:
            normalized.append(clean)

    return tuple(normalized) or tuple(DEFAULT_ALLOWED_MANIFEST_FILENAMES)


def normalize_ignored_directory_names(value: Any) -> tuple[str, ...]:
    """Normalisiert Ignorierverzeichnisse."""
    names = tuple_of_strings(value)

    if not names:
        names = tuple(DEFAULT_IGNORED_DIRECTORY_NAMES)

    result: list[str] = []

    for name in names:
        clean = safe_str(name, default="")

        if clean and clean not in result:
            result.append(clean)

    return tuple(result)


def normalize_discovery_status(value: Any) -> str:
    """Normalisiert Discovery-Status."""
    text = safe_str(value, default=DEFAULT_DISCOVERY_STATUS).lower()

    if text in VALID_DISCOVERY_STATUSES:
        return text

    return DEFAULT_DISCOVERY_STATUS


def normalize_candidate_status(value: Any) -> str:
    """Normalisiert Discovery-Kandidatenstatus."""
    text = safe_str(value, default="candidate").lower()

    if text in VALID_DISCOVERY_CANDIDATE_STATUSES:
        return text

    return "candidate"


def normalize_source_layout(value: Any) -> str:
    """Normalisiert Source-Layout."""
    text = safe_str(value, default=SOURCE_LAYOUT_UNKNOWN).lower()

    if text in {SOURCE_LAYOUT_CANONICAL, SOURCE_LAYOUT_LEGACY, SOURCE_LAYOUT_UNKNOWN}:
        return text

    return SOURCE_LAYOUT_UNKNOWN


def directory_name_is_ignored(path: Path, ignored_directory_names: Iterable[str]) -> bool:
    """Prüft, ob ein Verzeichnisname ignoriert werden soll."""
    try:
        return path.name in set(ignored_directory_names)
    except Exception:
        return False


def find_manifest_file(
    package_root: Path,
    *,
    allowed_manifest_filenames: Iterable[str],
) -> Path | None:
    """Prüft, ob ein Ordner eine erlaubte Manifest-Datei enthält."""
    try:
        for filename in allowed_manifest_filenames:
            candidate = package_root / filename

            if candidate.is_file():
                return candidate

    except Exception:
        return None

    return None


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackageDiscoveryOptions:
    """Konfiguration für Package Discovery."""

    recursive: bool = DEFAULT_SCAN_RECURSIVE
    max_depth: int = DEFAULT_SCAN_MAX_DEPTH
    follow_symlinks: bool = DEFAULT_SCAN_FOLLOW_SYMLINKS
    allowed_manifest_filenames: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_ALLOWED_MANIFEST_FILENAMES)
    )
    ignored_directory_names: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_IGNORED_DIRECTORY_NAMES)
    )
    treat_missing_source_root_as_empty: bool = True
    include_skipped: bool = False

    include_legacy_source_layout: bool = DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT_FALLBACK
    validate_taxonomy_path: bool = DEFAULT_VALIDATE_TAXONOMY_PATH_FALLBACK
    read_minimal_metadata: bool = DEFAULT_READ_MINIMAL_METADATA_FALLBACK

    def __post_init__(self) -> None:
        object.__setattr__(self, "recursive", safe_bool(self.recursive, default=DEFAULT_SCAN_RECURSIVE))
        object.__setattr__(
            self,
            "max_depth",
            safe_int(
                self.max_depth,
                default=DEFAULT_SCAN_MAX_DEPTH,
                minimum=0,
                maximum=MAX_SCAN_DEPTH_HARD_LIMIT,
            ),
        )
        object.__setattr__(self, "follow_symlinks", safe_bool(self.follow_symlinks, default=DEFAULT_SCAN_FOLLOW_SYMLINKS))
        object.__setattr__(
            self,
            "allowed_manifest_filenames",
            normalize_manifest_filenames(self.allowed_manifest_filenames),
        )
        object.__setattr__(
            self,
            "ignored_directory_names",
            normalize_ignored_directory_names(self.ignored_directory_names),
        )
        object.__setattr__(
            self,
            "treat_missing_source_root_as_empty",
            safe_bool(self.treat_missing_source_root_as_empty, default=True),
        )
        object.__setattr__(
            self,
            "include_skipped",
            safe_bool(self.include_skipped, default=False),
        )
        object.__setattr__(
            self,
            "include_legacy_source_layout",
            safe_bool(
                self.include_legacy_source_layout,
                default=DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT_FALLBACK,
            ),
        )
        object.__setattr__(
            self,
            "validate_taxonomy_path",
            safe_bool(
                self.validate_taxonomy_path,
                default=DEFAULT_VALIDATE_TAXONOMY_PATH_FALLBACK,
            ),
        )
        object.__setattr__(
            self,
            "read_minimal_metadata",
            safe_bool(
                self.read_minimal_metadata,
                default=DEFAULT_READ_MINIMAL_METADATA_FALLBACK,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "recursive": self.recursive,
            "max_depth": self.max_depth,
            "follow_symlinks": self.follow_symlinks,
            "allowed_manifest_filenames": list(self.allowed_manifest_filenames),
            "ignored_directory_names": list(self.ignored_directory_names),
            "treat_missing_source_root_as_empty": self.treat_missing_source_root_as_empty,
            "include_skipped": self.include_skipped,
            "include_legacy_source_layout": self.include_legacy_source_layout,
            "validate_taxonomy_path": self.validate_taxonomy_path,
            "read_minimal_metadata": self.read_minimal_metadata,
        }

    @classmethod
    def from_settings(cls, settings_options: Any = None) -> "PackageDiscoveryOptions":
        """Baut Discovery-Optionen aus `LibraryScanOptions`."""
        try:
            options = settings_options if settings_options is not None else get_library_scan_options()

            if options is None:
                return cls()

            return cls(
                recursive=get_attr_or_key(options, "recursive", default=DEFAULT_SCAN_RECURSIVE),
                max_depth=get_attr_or_key(options, "max_depth", default=DEFAULT_SCAN_MAX_DEPTH),
                follow_symlinks=get_attr_or_key(options, "follow_symlinks", default=DEFAULT_SCAN_FOLLOW_SYMLINKS),
                allowed_manifest_filenames=get_attr_or_key(
                    options,
                    "allowed_manifest_filenames",
                    default=DEFAULT_ALLOWED_MANIFEST_FILENAMES,
                ),
                ignored_directory_names=get_attr_or_key(
                    options,
                    "ignored_directory_names",
                    default=DEFAULT_IGNORED_DIRECTORY_NAMES,
                ),
                treat_missing_source_root_as_empty=get_attr_or_key(
                    options,
                    "treat_missing_source_root_as_empty",
                    default=True,
                ),
                include_skipped=False,
                include_legacy_source_layout=get_attr_or_key(
                    options,
                    "include_legacy_source_layout",
                    default=DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT_FALLBACK,
                ),
                validate_taxonomy_path=get_attr_or_key(
                    options,
                    "validate_taxonomy_path",
                    default=DEFAULT_VALIDATE_TAXONOMY_PATH_FALLBACK,
                ),
                read_minimal_metadata=get_attr_or_key(
                    options,
                    "read_minimal_metadata",
                    default=DEFAULT_READ_MINIMAL_METADATA_FALLBACK,
                ),
            )

        except Exception:
            return cls()


def coerce_discovery_options(
    value: PackageDiscoveryOptions | Mapping[str, Any] | None = None,
) -> PackageDiscoveryOptions:
    """Normalisiert optionale Discovery-Options."""
    if isinstance(value, PackageDiscoveryOptions):
        return value

    if value is None:
        return PackageDiscoveryOptions()

    try:
        data = ensure_dict(value)

        if not data:
            return PackageDiscoveryOptions()

        allowed = {
            "recursive",
            "max_depth",
            "follow_symlinks",
            "allowed_manifest_filenames",
            "ignored_directory_names",
            "treat_missing_source_root_as_empty",
            "include_skipped",
            "include_legacy_source_layout",
            "validate_taxonomy_path",
            "read_minimal_metadata",
        }

        return PackageDiscoveryOptions(
            **{key: item for key, item in data.items() if key in allowed}
        )

    except Exception:
        return PackageDiscoveryOptions()


# ---------------------------------------------------------------------------
# Discovery domain models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackageDiscoveryMessage:
    """Meldung der Discovery-Schicht."""

    level: str
    message: str
    code: str | None = None
    path: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        level = safe_str(self.level, default="info").lower()

        if level not in {"debug", "info", "warning", "error", "fatal"}:
            level = "info"

        object.__setattr__(self, "level", level)
        object.__setattr__(self, "message", safe_str(self.message, default=""))
        object.__setattr__(self, "code", safe_str(self.code, default="") or None)
        object.__setattr__(self, "path", safe_path_str(self.path))
        object.__setattr__(self, "data", ensure_dict(self.data))

    def to_scan_message(self) -> LibraryScanMessage:
        """Wandelt Discovery-Meldung in allgemeine Scan-Meldung."""
        try:
            return LibraryScanMessage(
                level=self.level,
                message=self.message,
                code=self.code,
                path=self.path,
                data=self.data,
            )
        except TypeError:
            try:
                return LibraryScanMessage(
                    level=self.level,
                    message=self.message,
                    code=self.code,
                    path=self.path,
                    document_key=None,
                    data=self.data,
                )
            except Exception:
                return self  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "message": self.message,
            "code": self.code,
            "path": self.path,
            "data": json_safe(self.data),
        }


@dataclass(frozen=True)
class PackageDiscoveryCandidate:
    """Ein gefundener möglicher VPLIB-Package-Root."""

    candidate_id: str
    package_root: str
    manifest_path: str
    source_root: str | None = None
    relative_package_root: str | None = None
    depth: int = 0
    status: str = "candidate"
    reason: str = PACKAGE_MARKER_REASON_MANIFEST
    discovered_at: str = field(default_factory=utc_now_iso)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    source_layout: str = SOURCE_LAYOUT_UNKNOWN
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    family_slug: str | None = None
    source_path: str | None = None
    classification_path: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", normalize_path_for_id(self.candidate_id))
        object.__setattr__(self, "package_root", safe_path_str(self.package_root) or "")
        object.__setattr__(self, "manifest_path", safe_path_str(self.manifest_path) or "")
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "relative_package_root", safe_path_str(self.relative_package_root))
        object.__setattr__(self, "depth", safe_int(self.depth, default=0, minimum=0))
        object.__setattr__(self, "status", normalize_candidate_status(self.status))
        object.__setattr__(self, "reason", safe_str(self.reason, default=PACKAGE_MARKER_REASON_MANIFEST))
        object.__setattr__(self, "discovered_at", safe_str(self.discovered_at, default=utc_now_iso()))
        object.__setattr__(self, "warnings", tuple_of_strings(self.warnings))
        object.__setattr__(self, "errors", tuple_of_strings(self.errors))
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "source_layout", normalize_source_layout(self.source_layout))
        object.__setattr__(self, "domain", normalize_taxonomy_part(self.domain) or None)
        object.__setattr__(self, "category", normalize_taxonomy_part(self.category) or None)
        object.__setattr__(self, "subcategory", normalize_taxonomy_part(self.subcategory) or None)
        object.__setattr__(self, "family_slug", normalize_taxonomy_part(self.family_slug) or None)
        object.__setattr__(self, "source_path", normalize_source_path_string(self.source_path) or None)
        object.__setattr__(self, "classification_path", normalize_source_path_string(self.classification_path) or None)

    @property
    def is_candidate(self) -> bool:
        return self.status == "candidate"

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    @property
    def is_canonical(self) -> bool:
        return self.source_layout == SOURCE_LAYOUT_CANONICAL

    @property
    def is_legacy(self) -> bool:
        return self.source_layout == SOURCE_LAYOUT_LEGACY

    @classmethod
    def from_paths(
        cls,
        *,
        source_root: Path,
        package_root: Path,
        manifest_path: Path,
        status: str = "candidate",
        reason: str = PACKAGE_MARKER_REASON_MANIFEST,
        warnings: Iterable[Any] | None = None,
        errors: Iterable[Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        options: PackageDiscoveryOptions | None = None,
    ) -> "PackageDiscoveryCandidate":
        resolved_source_root = safe_resolve(source_root)
        resolved_package_root = safe_resolve(package_root)
        resolved_manifest_path = safe_resolve(manifest_path)

        relative_package_root = make_relative_path(
            resolved_package_root,
            resolved_source_root,
        )

        candidate_id = normalize_path_for_id(relative_package_root)
        depth = calculate_depth(resolved_package_root, resolved_source_root)
        discovery_options = options or PackageDiscoveryOptions()

        base_metadata = ensure_dict(metadata)

        taxonomy_metadata, taxonomy_warnings, taxonomy_errors = build_taxonomy_discovery_metadata(
            source_root=resolved_source_root,
            package_root=resolved_package_root,
            manifest_path=resolved_manifest_path,
            read_metadata=discovery_options.read_minimal_metadata,
            validate_taxonomy_path=discovery_options.validate_taxonomy_path,
        )

        merged_metadata = {
            **base_metadata,
            **taxonomy_metadata,
        }
        taxonomy_info = ensure_dict(merged_metadata.get("taxonomy"))

        return cls(
            candidate_id=candidate_id,
            package_root=str(resolved_package_root),
            manifest_path=str(resolved_manifest_path),
            source_root=str(resolved_source_root),
            relative_package_root=relative_package_root,
            depth=depth,
            status=status,
            reason=reason,
            discovered_at=utc_now_iso(),
            warnings=tuple_of_strings(warnings) + tuple(taxonomy_warnings),
            errors=tuple_of_strings(errors) + tuple(taxonomy_errors),
            metadata=merged_metadata,
            source_layout=taxonomy_info.get("layout") or SOURCE_LAYOUT_UNKNOWN,
            domain=taxonomy_info.get("domain"),
            category=taxonomy_info.get("category"),
            subcategory=taxonomy_info.get("subcategory"),
            family_slug=taxonomy_info.get("family_slug"),
            source_path=taxonomy_info.get("source_path"),
            classification_path=taxonomy_info.get("classification_path"),
        )

    def to_scan_candidate(self) -> LibraryScanCandidate:
        """Wandelt Discovery-Kandidaten in das allgemeinere ScanCandidate-Modell."""
        payload = {
            "candidate_id": self.candidate_id,
            "status": (
                LibraryScanCandidateStatus.SKIPPED.value
                if self.status == "skipped" and hasattr(LibraryScanCandidateStatus, "SKIPPED")
                else LibraryScanCandidateStatus.CANDIDATE.value
            ),
            "valid": False,
            "source_path": self.package_root,
            "package_root": self.package_root,
            "relative_package_root": self.relative_package_root,
            "manifest_path": self.manifest_path,
            "discovered_at": self.discovered_at,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": {
                "discovery": self.to_dict(),
                "taxonomy": self.metadata.get("taxonomy", {}),
            },
        }

        return make_scan_candidate(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "package_root": self.package_root,
            "manifest_path": self.manifest_path,
            "source_root": self.source_root,
            "relative_package_root": self.relative_package_root,
            "depth": self.depth,
            "status": self.status,
            "reason": self.reason,
            "is_candidate": self.is_candidate,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "source_layout": self.source_layout,
            "is_canonical": self.is_canonical,
            "is_legacy": self.is_legacy,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "family_slug": self.family_slug,
            "source_path": self.source_path,
            "classification_path": self.classification_path,
            "discovered_at": self.discovered_at,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": json_safe(self.metadata),
        }


@dataclass(frozen=True)
class PackageDiscoveryResult:
    """Ergebnis eines Package-Discovery-Laufs."""

    ok: bool
    status: str
    source_root: str | None
    started_at: str
    finished_at: str
    duration_ms: int
    candidates: tuple[PackageDiscoveryCandidate, ...] = field(default_factory=tuple)
    skipped: tuple[PackageDiscoveryCandidate, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[PackageDiscoveryMessage, ...] = field(default_factory=tuple)
    options: PackageDiscoveryOptions = field(default_factory=PackageDiscoveryOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = PACKAGE_DISCOVERY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.options, PackageDiscoveryOptions):
            object.__setattr__(self, "options", coerce_discovery_options(self.options))

        normalized_status = normalize_discovery_status(self.status)

        candidate_tuple = tuple(self.candidates or ())
        skipped_tuple = tuple(self.skipped or ())
        warning_tuple = tuple_of_strings(self.warnings)
        error_tuple = tuple_of_strings(self.errors)

        candidate_has_errors = any(candidate.has_errors for candidate in candidate_tuple)

        if normalized_status == "unknown":
            if error_tuple:
                normalized_status = "error"
            elif candidate_has_errors and candidate_tuple:
                normalized_status = "partial"
            elif candidate_tuple:
                normalized_status = "ok"
            else:
                normalized_status = "empty"

        object.__setattr__(self, "ok", bool(self.ok and normalized_status in {"ok", "empty", "partial"}))
        object.__setattr__(self, "status", normalized_status)
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "duration_ms", safe_int(self.duration_ms, default=0, minimum=0))
        object.__setattr__(self, "candidates", candidate_tuple)
        object.__setattr__(self, "skipped", skipped_tuple)
        object.__setattr__(self, "warnings", warning_tuple)
        object.__setattr__(self, "errors", error_tuple)
        object.__setattr__(self, "messages", tuple(self.messages or ()))
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "version", safe_str(self.version, default=PACKAGE_DISCOVERY_VERSION))

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)

    @property
    def canonical_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.is_canonical)

    @property
    def legacy_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.is_legacy)

    @property
    def unknown_layout_count(self) -> int:
        return sum(1 for candidate in self.candidates if candidate.source_layout == SOURCE_LAYOUT_UNKNOWN)

    @property
    def error_count(self) -> int:
        return len(self.errors) + sum(1 for candidate in self.candidates if candidate.has_errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings) + sum(1 for candidate in self.candidates if candidate.has_warnings)

    @property
    def is_empty(self) -> bool:
        return self.candidate_count == 0

    def to_scan_candidates(self) -> list[LibraryScanCandidate]:
        """Wandelt alle Discovery-Kandidaten in allgemeine ScanCandidates um."""
        result: list[LibraryScanCandidate] = []

        for candidate in self.candidates:
            try:
                result.append(candidate.to_scan_candidate())
            except Exception:
                continue

        return result

    def to_dict(self, *, include_skipped: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "source_root": self.source_root,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "candidate_count": self.candidate_count,
            "skipped_count": self.skipped_count,
            "canonical_count": self.canonical_count,
            "legacy_count": self.legacy_count,
            "unknown_layout_count": self.unknown_layout_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "is_empty": self.is_empty,
            "candidates": [
                candidate.to_dict()
                for candidate in self.candidates
            ],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "messages": [
                message.to_dict()
                for message in self.messages
            ],
            "options": self.options.to_dict(),
            "metadata": json_safe(self.metadata),
            "version": self.version,
        }

        if include_skipped:
            result["skipped"] = [
                candidate.to_dict()
                for candidate in self.skipped
            ]

        return result

    @classmethod
    def empty(
        cls,
        *,
        source_root: Any,
        started_at: str | None = None,
        duration_ms: int = 0,
        options: PackageDiscoveryOptions | None = None,
        warning: str | None = None,
    ) -> "PackageDiscoveryResult":
        warnings = (warning,) if warning else ()

        return cls(
            ok=True,
            status="empty",
            source_root=safe_path_str(source_root),
            started_at=started_at or utc_now_iso(),
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            candidates=(),
            skipped=(),
            warnings=warnings,
            errors=(),
            messages=(),
            options=options or PackageDiscoveryOptions(),
            metadata={},
        )

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        source_root: Any = None,
        started_at: str | None = None,
        duration_ms: int = 0,
        options: PackageDiscoveryOptions | None = None,
        include_traceback: bool = False,
    ) -> "PackageDiscoveryResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        message = safe_str(
            error_data.get("message") if error_data else None,
            default="package discovery failed",
        )

        return cls(
            ok=False,
            status="error",
            source_root=safe_path_str(source_root),
            started_at=started_at or utc_now_iso(),
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            candidates=(),
            skipped=(),
            warnings=(),
            errors=(message,),
            messages=(
                PackageDiscoveryMessage(
                    level="error",
                    message=message,
                    code=safe_str(error_data.get("type") if error_data else None, default="Exception"),
                    data=error_data or {},
                ),
            ),
            options=options or PackageDiscoveryOptions(),
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# Scan candidate compatibility
# ---------------------------------------------------------------------------

def make_scan_candidate(payload: Mapping[str, Any]) -> LibraryScanCandidate:
    """Baut LibraryScanCandidate robust gegen unterschiedliche Signaturen."""
    data = dict(payload)

    try:
        if hasattr(LibraryScanCandidate, "from_raw") and callable(LibraryScanCandidate.from_raw):
            return LibraryScanCandidate.from_raw(**data)
    except TypeError:
        pass
    except Exception:
        pass

    allowed = {
        "candidate_id",
        "status",
        "valid",
        "source_path",
        "package_root",
        "relative_package_root",
        "manifest_path",
        "discovered_at",
        "warnings",
        "errors",
        "metadata",
    }

    try:
        return LibraryScanCandidate(
            **{key: value for key, value in data.items() if key in allowed}
        )
    except TypeError:
        try:
            return LibraryScanCandidate(
                candidate_id=safe_str(data.get("candidate_id"), default="unknown.candidate"),
                status=safe_str(data.get("status"), default="candidate"),
                valid=safe_bool(data.get("valid"), default=False),
            )
        except Exception:
            return LibraryScanCandidate.from_raw(
                candidate_id=safe_str(data.get("candidate_id"), default="unknown.candidate")
            )


# ---------------------------------------------------------------------------
# Discovery implementation
# ---------------------------------------------------------------------------

def should_skip_directory(
    directory: Path,
    *,
    source_root: Path,
    options: PackageDiscoveryOptions,
    depth: int,
) -> tuple[bool, str | None]:
    """Entscheidet, ob ein Verzeichnis übersprungen werden soll."""
    try:
        if not directory.is_dir():
            return True, PACKAGE_MARKER_REASON_SKIPPED_NOT_DIRECTORY

        if directory_name_is_ignored(directory, options.ignored_directory_names):
            return True, PACKAGE_MARKER_REASON_SKIPPED_IGNORED_DIR

        if directory.is_symlink() and not options.follow_symlinks:
            return True, PACKAGE_MARKER_REASON_SKIPPED_SYMLINK

        if depth > options.max_depth:
            return True, PACKAGE_MARKER_REASON_SKIPPED_MAX_DEPTH

        if not path_is_relative_to(safe_resolve(directory), safe_resolve(source_root)):
            return True, PACKAGE_MARKER_REASON_SKIPPED_OUTSIDE_SOURCE_ROOT

        return False, None

    except Exception as exc:
        return True, f"skip_check_error:{exc.__class__.__name__}"


def make_skipped_candidate(
    *,
    source_root: Path,
    directory: Path,
    reason: str,
    options: PackageDiscoveryOptions,
    metadata: Mapping[str, Any] | None = None,
) -> PackageDiscoveryCandidate:
    """Baut einen übersprungenen Kandidaten für Debug-Ausgaben."""
    resolved_source_root = safe_resolve(source_root)
    resolved_directory = safe_resolve(directory)
    relative = make_relative_path(resolved_directory, resolved_source_root)
    taxonomy_info = taxonomy_from_relative_path(relative)

    return PackageDiscoveryCandidate(
        candidate_id=normalize_path_for_id(relative),
        package_root=str(resolved_directory),
        manifest_path="",
        source_root=str(resolved_source_root),
        relative_package_root=relative,
        depth=calculate_depth(resolved_directory, resolved_source_root),
        status="skipped",
        reason=reason,
        discovered_at=utc_now_iso(),
        warnings=(),
        errors=(),
        metadata={
            "options": options.to_dict(),
            "taxonomy": taxonomy_info,
            **ensure_dict(metadata),
        },
        source_layout=taxonomy_info.get("layout"),
        domain=taxonomy_info.get("domain"),
        category=taxonomy_info.get("category"),
        subcategory=taxonomy_info.get("subcategory"),
        family_slug=taxonomy_info.get("family_slug"),
        source_path=taxonomy_info.get("source_path"),
        classification_path=taxonomy_info.get("classification_path"),
    )


def iter_child_directories(directory: Path) -> list[Path]:
    """Listet direkte Unterverzeichnisse robust und sortiert auf."""
    try:
        children: list[Path] = []

        for child in directory.iterdir():
            try:
                if child.is_dir():
                    children.append(child)
            except OSError:
                continue
            except Exception:
                continue

        return sorted(children, key=lambda path: str(path).lower())

    except Exception:
        return []


def discover_package_candidates(
    source_root: Path,
    *,
    options: PackageDiscoveryOptions | Mapping[str, Any] | None = None,
) -> PackageDiscoveryResult:
    """
    Sucht VPLIB-Package-Kandidaten unter einem Source-Root.

    Diese Funktion:
    - sucht Ordner mit `vplib.manifest.json`
    - liest nur minimale optionale Metadaten
    - validiert keine vollständige Package-Struktur
    - schreibt nichts ins Dateisystem
    """
    started_at = utc_now_iso()
    started_monotonic = monotonic_ms()
    discovery_options = coerce_discovery_options(options)

    candidates: list[PackageDiscoveryCandidate] = []
    skipped: list[PackageDiscoveryCandidate] = []
    warnings: list[str] = []
    errors: list[str] = []
    messages: list[PackageDiscoveryMessage] = []

    try:
        resolved_source_root = safe_resolve(source_root)

        if not resolved_source_root.exists():
            message = f"library source root does not exist: {resolved_source_root}"

            if discovery_options.treat_missing_source_root_as_empty:
                duration_ms = max(0, monotonic_ms() - started_monotonic)
                return PackageDiscoveryResult.empty(
                    source_root=resolved_source_root,
                    started_at=started_at,
                    duration_ms=duration_ms,
                    options=discovery_options,
                    warning=message,
                )

            raise FileNotFoundError(message)

        if not resolved_source_root.is_dir():
            raise NotADirectoryError(f"library source root is not a directory: {resolved_source_root}")

        visited_real_paths: set[str] = set()
        candidate_roots: set[str] = set()

        def walk(directory: Path, depth: int) -> None:
            """
            Interner rekursiver Walker.

            Sobald ein Package-Root erkannt wird, wird darunter nicht weiter
            gesucht. Dadurch werden Assets/Unterordner eines Pakets nicht
            versehentlich als eigene Pakete interpretiert.
            """
            try:
                resolved_directory = safe_resolve(directory)

                skip, reason = should_skip_directory(
                    resolved_directory,
                    source_root=resolved_source_root,
                    options=discovery_options,
                    depth=depth,
                )

                if skip:
                    if discovery_options.include_skipped:
                        skipped.append(
                            make_skipped_candidate(
                                source_root=resolved_source_root,
                                directory=resolved_directory,
                                reason=reason or "skipped",
                                options=discovery_options,
                            )
                        )
                    return

                if resolved_directory.is_symlink() and discovery_options.follow_symlinks:
                    try:
                        real_path_key = str(os.path.realpath(str(resolved_directory)))

                        if real_path_key in visited_real_paths:
                            if discovery_options.include_skipped:
                                skipped.append(
                                    make_skipped_candidate(
                                        source_root=resolved_source_root,
                                        directory=resolved_directory,
                                        reason=PACKAGE_MARKER_REASON_SKIPPED_SYMLINK_LOOP,
                                        options=discovery_options,
                                    )
                                )
                            return

                        visited_real_paths.add(real_path_key)

                    except Exception:
                        pass

                manifest_path = find_manifest_file(
                    resolved_directory,
                    allowed_manifest_filenames=discovery_options.allowed_manifest_filenames,
                )

                if manifest_path is not None:
                    root_key = str(resolved_directory)

                    if root_key not in candidate_roots:
                        candidate_roots.add(root_key)

                        candidate = PackageDiscoveryCandidate.from_paths(
                            source_root=resolved_source_root,
                            package_root=resolved_directory,
                            manifest_path=manifest_path,
                            status="candidate",
                            reason=PACKAGE_MARKER_REASON_MANIFEST,
                            metadata={
                                "discovery_mode": DEFAULT_DISCOVERY_MODE,
                                "manifest_filename": manifest_path.name,
                            },
                            options=discovery_options,
                        )

                        if candidate.is_legacy and not discovery_options.include_legacy_source_layout:
                            if discovery_options.include_skipped:
                                skipped.append(
                                    make_skipped_candidate(
                                        source_root=resolved_source_root,
                                        directory=resolved_directory,
                                        reason=PACKAGE_MARKER_REASON_SKIPPED_LEGACY,
                                        options=discovery_options,
                                        metadata={"candidate": candidate.to_dict()},
                                    )
                                )
                        else:
                            candidates.append(candidate)

                    # Package gefunden: nicht tiefer in dieses Package laufen.
                    return

                if not discovery_options.recursive:
                    return

                if depth >= discovery_options.max_depth:
                    if discovery_options.include_skipped:
                        skipped.append(
                            make_skipped_candidate(
                                source_root=resolved_source_root,
                                directory=resolved_directory,
                                reason=PACKAGE_MARKER_REASON_SKIPPED_MAX_DEPTH,
                                options=discovery_options,
                            )
                        )
                    return

                for child in iter_child_directories(resolved_directory):
                    walk(child, depth + 1)

            except Exception as walk_exc:
                error_message = f"could not inspect directory {directory}: {walk_exc}"
                errors.append(error_message)
                messages.append(
                    PackageDiscoveryMessage(
                        level="error",
                        message=f"could not inspect directory: {directory}",
                        code=walk_exc.__class__.__name__,
                        path=str(directory),
                        data={"exception": exception_to_dict(walk_exc)},
                    )
                )

        walk(resolved_source_root, 0)

        duration_ms = max(0, monotonic_ms() - started_monotonic)

        candidate_has_errors = any(candidate.has_errors for candidate in candidates)

        status = "ok"
        if errors and candidates:
            status = "partial"
        elif errors and not candidates:
            status = "error"
        elif candidate_has_errors and candidates:
            status = "partial"
        elif not candidates:
            status = "empty"

        return PackageDiscoveryResult(
            ok=status in {"ok", "partial", "empty"},
            status=status,
            source_root=str(resolved_source_root),
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            candidates=tuple(candidates),
            skipped=tuple(skipped),
            warnings=tuple(warnings),
            errors=tuple(errors),
            messages=tuple(messages),
            options=discovery_options,
            metadata={
                "settings_import_error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
                "scan_result_import_error": exception_to_dict(_SCAN_RESULT_IMPORT_ERROR),
                "taxonomy_import_error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
                "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
                "legacy_source_depth": LEGACY_SOURCE_DEPTH,
            },
        )

    except Exception as exc:
        duration_ms = max(0, monotonic_ms() - started_monotonic)

        return PackageDiscoveryResult.error(
            exc,
            source_root=source_root,
            started_at=started_at,
            duration_ms=duration_ms,
            options=discovery_options,
        )


def discover_library_packages(
    *,
    source_root: Any = None,
    options: PackageDiscoveryOptions | Mapping[str, Any] | None = None,
    refresh_settings: bool = False,
) -> PackageDiscoveryResult:
    """
    Hauptfunktion für spätere Services und Routen.

    Wenn `source_root` nicht gesetzt ist, wird der Pfad aus
    `config.library_settings.get_source_root()` verwendet.
    """
    try:
        discovery_options = coerce_discovery_options(
            options or PackageDiscoveryOptions.from_settings(
                get_library_scan_options(refresh=refresh_settings)
            )
        )

        if source_root is None:
            root = get_source_root(refresh=refresh_settings)
        else:
            root = safe_path(source_root)

        if root is None:
            raise ValueError("source_root could not be resolved")

        return discover_package_candidates(
            root,
            options=discovery_options,
        )

    except Exception as exc:
        return PackageDiscoveryResult.error(
            exc,
            source_root=source_root,
            options=coerce_discovery_options(options),
        )


def discover_package_roots(
    source_root: Any = None,
    *,
    options: PackageDiscoveryOptions | Mapping[str, Any] | None = None,
) -> list[Path]:
    """Convenience-Funktion: gibt nur gefundene Package-Root-Pfade zurück."""
    result = discover_library_packages(
        source_root=source_root,
        options=options,
    )

    roots: list[Path] = []

    for candidate in result.candidates:
        try:
            root = safe_path(candidate.package_root)

            if root is not None:
                roots.append(root)

        except Exception:
            continue

    return roots


def discover_manifest_paths(
    source_root: Any = None,
    *,
    options: PackageDiscoveryOptions | Mapping[str, Any] | None = None,
) -> list[Path]:
    """Convenience-Funktion: gibt nur gefundene Manifest-Pfade zurück."""
    result = discover_library_packages(
        source_root=source_root,
        options=options,
    )

    manifests: list[Path] = []

    for candidate in result.candidates:
        try:
            manifest_path = safe_path(candidate.manifest_path)

            if manifest_path is not None:
                manifests.append(manifest_path)

        except Exception:
            continue

    return manifests


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_package_discovery_health(
    *,
    refresh_settings: bool = False,
) -> dict[str, Any]:
    """
    Health-Status der Package-Discovery-Schicht.

    Führt keinen Scan aus. Prüft nur:
    - Settings-Zugriff
    - Source-Root-Berechnung
    - Importstatus optionaler Abhängigkeiten
    """
    warnings: list[str] = []
    errors: list[str] = []

    try:
        source_root = get_source_root(refresh=refresh_settings)
        source_root_value = str(source_root)
        source_root_exists = source_root.exists()
        source_root_is_directory = source_root.is_dir()
    except Exception as exc:
        source_root = None
        source_root_value = None
        source_root_exists = False
        source_root_is_directory = False
        errors.append(f"could not resolve source root: {exc}")

    if _SETTINGS_IMPORT_ERROR is not None:
        warnings.append("config.library_settings import failed; fallback settings are active")

    if _SCAN_RESULT_IMPORT_ERROR is not None:
        warnings.append("library.domain.scan_result import failed; fallback scan models are active")

    if _TAXONOMY_IMPORT_ERROR is not None:
        warnings.append("library.taxonomy import failed; taxonomy path checks are degraded")

    try:
        options = PackageDiscoveryOptions.from_settings()
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build discovery options: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=12, minimum=0, maximum=MAX_SCAN_DEPTH_HARD_LIMIT)
        if safe_int_self_test != MAX_SCAN_DEPTH_HARD_LIMIT:
            errors.append(
                f"safe_int maximum self-test failed: expected {MAX_SCAN_DEPTH_HARD_LIMIT}, got {safe_int_self_test}"
            )
    except Exception as exc:
        errors.append(f"safe_int maximum self-test failed: {exc}")

    try:
        settings_summary = get_settings_summary(refresh=refresh_settings)
    except Exception as exc:
        settings_summary = {
            "ok": False,
            "error": exception_to_dict(exc),
        }
        warnings.append("settings summary fallback failed")

    taxonomy_health: dict[str, Any] = {
        "available": taxonomy_available(),
        "import_error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
    }
    if taxonomy_available():
        try:
            taxonomy_health = get_default_taxonomy_service().health(  # type: ignore[misc]
                force_reload=False,
                include_registry_state=False,
            )
        except Exception as exc:
            taxonomy_health = {
                "available": True,
                "healthy": False,
                "error": exception_to_dict(exc),
            }
            warnings.append("taxonomy health check failed")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": PACKAGE_DISCOVERY_COMPONENT,
        "version": PACKAGE_DISCOVERY_VERSION,
        "generated_at": utc_now_iso(),
        "source_root": source_root_value,
        "source_root_exists": source_root_exists,
        "source_root_is_directory": source_root_is_directory,
        "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
        "legacy_source_depth": LEGACY_SOURCE_DEPTH,
        "options": options_dict,
        "imports": {
            "settings": {
                "ok": _SETTINGS_IMPORT_ERROR is None,
                "error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
            },
            "scan_result": {
                "ok": _SCAN_RESULT_IMPORT_ERROR is None,
                "error": exception_to_dict(_SCAN_RESULT_IMPORT_ERROR),
            },
            "taxonomy": {
                "ok": _TAXONOMY_IMPORT_ERROR is None,
                "error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
            },
        },
        "taxonomy": json_safe(taxonomy_health),
        "settings_summary": json_safe(settings_summary),
        "warnings": warnings,
        "errors": errors,
    }


def assert_package_discovery_ready() -> None:
    """Wirft RuntimeError, wenn Package Discovery nicht bereit ist."""
    health = get_package_discovery_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"package discovery is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "PACKAGE_DISCOVERY_VERSION",
    "PACKAGE_DISCOVERY_COMPONENT",
    "DEFAULT_DISCOVERY_MODE",
    "DEFAULT_DISCOVERY_STATUS",
    "PACKAGE_MARKER_REASON_MANIFEST",
    "PACKAGE_MARKER_REASON_SKIPPED_IGNORED_DIR",
    "PACKAGE_MARKER_REASON_SKIPPED_MAX_DEPTH",
    "PACKAGE_MARKER_REASON_SKIPPED_SYMLINK",
    "PACKAGE_MARKER_REASON_SKIPPED_NOT_DIRECTORY",
    "PACKAGE_MARKER_REASON_SKIPPED_OUTSIDE_SOURCE_ROOT",
    "PACKAGE_MARKER_REASON_SKIPPED_SYMLINK_LOOP",
    "PACKAGE_MARKER_REASON_SKIPPED_LEGACY",
    "VALID_DISCOVERY_STATUSES",
    "VALID_DISCOVERY_CANDIDATE_STATUSES",
    "DEFAULT_ALLOWED_MANIFEST_FILENAMES_FALLBACK",
    "DEFAULT_IGNORED_DIRECTORY_NAMES_FALLBACK",
    "DEFAULT_SCAN_FOLLOW_SYMLINKS_FALLBACK",
    "DEFAULT_SCAN_MAX_DEPTH_FALLBACK",
    "DEFAULT_SCAN_RECURSIVE_FALLBACK",
    "DEFAULT_INCLUDE_LEGACY_SOURCE_LAYOUT_FALLBACK",
    "DEFAULT_VALIDATE_TAXONOMY_PATH_FALLBACK",
    "DEFAULT_READ_MINIMAL_METADATA_FALLBACK",
    "MAX_SCAN_DEPTH_HARD_LIMIT",
    "CANONICAL_SOURCE_DEPTH",
    "LEGACY_SOURCE_DEPTH",
    "SOURCE_LAYOUT_CANONICAL",
    "SOURCE_LAYOUT_LEGACY",
    "SOURCE_LAYOUT_UNKNOWN",
    "SOURCE_ROOT_ENV_NAMES",
    "PackageDiscoveryOptions",
    "PackageDiscoveryMessage",
    "PackageDiscoveryCandidate",
    "PackageDiscoveryResult",
    "utc_now_iso",
    "monotonic_ms_safe",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_int",
    "safe_path",
    "safe_path_str",
    "safe_resolve",
    "ensure_dict",
    "normalize_path_for_id",
    "tuple_of_strings",
    "path_is_relative_to",
    "make_relative_path",
    "calculate_depth",
    "get_attr_or_key",
    "first_non_empty",
    "deep_get",
    "fallback_normalize_slug",
    "taxonomy_available",
    "normalize_taxonomy_part",
    "normalize_source_path_parts",
    "normalize_source_path_string",
    "infer_source_layout",
    "taxonomy_from_relative_path",
    "read_json_object",
    "read_minimal_package_metadata",
    "build_taxonomy_discovery_metadata",
    "normalize_manifest_filenames",
    "normalize_ignored_directory_names",
    "normalize_discovery_status",
    "normalize_candidate_status",
    "normalize_source_layout",
    "directory_name_is_ignored",
    "find_manifest_file",
    "coerce_discovery_options",
    "make_scan_candidate",
    "should_skip_directory",
    "make_skipped_candidate",
    "iter_child_directories",
    "discover_package_candidates",
    "discover_library_packages",
    "discover_package_roots",
    "discover_manifest_paths",
    "get_package_discovery_health",
    "assert_package_discovery_ready",
)