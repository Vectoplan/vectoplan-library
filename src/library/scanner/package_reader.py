# services/vectoplan-library/src/library/scanner/package_reader.py
"""
Package Reader für die VECTOPLAN Creative-Library-Schicht.

Diese Datei ist die zweite Stufe des Backend-Scanners.

Aufgabe:

- einen gefundenen VPLIB-Package-Root einlesen
- JSON-Dokumente robust laden
- Pflichtdateien prüfen
- optionale Dokumente erfassen
- alle weiteren JSON-Dokumente im Paket optional mitlesen
- kaputte JSON-Dateien als Fehler melden
- Discovery-Metadaten und Taxonomiepfad-Metadaten weiterreichen
- keine fachliche Validierung ausführen
- keine Dateien schreiben
- keine Pakete kopieren
- kein Datenbankzugriff

Input kommt typischerweise aus:

    src/library/scanner/package_discovery.py

Output geht später an:

    src/library/validation/library_package_validator.py
    src/library/read_models/*
    src/library/services/library_scan_service.py

Diese Datei trennt bewusst "Lesen" von "Validieren". Ein gelesenes Paket kann
also technisch lesbar, aber fachlich ungültig sein.

Taxonomie-Integration:

- Reader validiert Taxonomie nicht abschließend.
- Reader bewahrt aber die Taxonomie-Kontextdaten aus Discovery und Dokumenten:
    source_layout
    domain
    category
    subcategory
    family_slug
    source_path
    classification_path
    taxonomy_version
- Der Validator entscheidet später, ob diese Daten fachlich gültig sind.

Canonical source path:

    {domain}/{category}/{subcategory}/{family_slug}

Legacy source path:

    {domain}/{category}/{family_slug}

Version 0.2.0:

- `family/classification.json` ist jetzt Reader-Pflichtdatei.
- `PackageReadResult` enthält Taxonomie- und Source-Pfad-Metadaten.
- `read_discovery_candidate()` übernimmt Discovery-Metadaten vollständig.
- `to_scan_candidate()` reicht Reader- und Taxonomie-Metadaten weiter.
- `read_result_to_document_mapping()` bleibt rückwärtskompatibel.
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

PACKAGE_READER_VERSION: Final[str] = "0.2.0"
PACKAGE_READER_COMPONENT: Final[str] = "library-package-reader"

DEFAULT_READER_STATUS: Final[str] = "unknown"
DEFAULT_TEXT_ENCODING: Final[str] = "utf-8-sig"
DEFAULT_MAX_JSON_FILE_SIZE_BYTES: Final[int] = 5 * 1024 * 1024
MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT: Final[int] = 100 * 1024 * 1024

DEFAULT_READ_ALL_JSON_DOCUMENTS: Final[bool] = True
DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES: Final[bool] = True
DEFAULT_FAIL_ON_JSON_ERROR: Final[bool] = False
DEFAULT_FAIL_ON_MISSING_REQUIRED: Final[bool] = False

JSON_SUFFIX: Final[str] = ".json"

CANONICAL_SOURCE_DEPTH: Final[int] = 4
LEGACY_SOURCE_DEPTH: Final[int] = 3

SOURCE_LAYOUT_CANONICAL: Final[str] = "canonical"
SOURCE_LAYOUT_LEGACY: Final[str] = "legacy"
SOURCE_LAYOUT_UNKNOWN: Final[str] = "unknown"

VALID_READER_STATUSES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "partial",
    "invalid",
    "error",
)

READ_ERROR_CODES: Final[tuple[str, ...]] = (
    "missing_required_file",
    "missing_document",
    "not_a_directory",
    "not_a_file",
    "path_outside_package",
    "file_too_large",
    "json_decode_error",
    "read_error",
    "invalid_document_key",
)

DEFAULT_ALLOWED_MANIFEST_FILENAMES_FALLBACK: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
)

DEFAULT_REQUIRED_PACKAGE_FILES_FALLBACK: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
    "vplib.modules.json",
    "family/identity.json",
    "family/classification.json",
    "variants/index.json",
    "variants/default.json",
)

TAXONOMY_REQUIRED_READER_FILES: Final[tuple[str, ...]] = (
    "family/classification.json",
)

DEFAULT_OPTIONAL_SUMMARY_FILES_FALLBACK: Final[tuple[str, ...]] = (
    "editor/inventory.json",
    "editor/placement.json",
    "render/render_variants.json",
    "physical/base.json",
    "physical/dimensions.json",
    "physical/collision.json",
    "manufacturer/contract.json",
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

DEFAULT_IGNORED_FILE_SUFFIXES_FALLBACK: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
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
    """Wandelt Werte defensiv in JSON-kompatible Strukturen um."""
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


def normalize_document_key(document_key: Any) -> str:
    """Normalisiert Dokumentkeys."""
    text = safe_str(document_key, default="")
    text = text.replace("\\", "/").strip("/")

    while "//" in text:
        text = text.replace("//", "/")

    return text


def normalize_documents(documents: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert ein Dokumentmapping auf paketrelative Keys."""
    if not isinstance(documents, Mapping):
        return {}

    result: dict[str, Any] = {}

    for key, value in documents.items():
        normalized_key = normalize_document_key(key)

        if normalized_key:
            result[normalized_key] = value

    return result


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


def deep_get(
    data: Mapping[str, Any] | None,
    path: str,
    *,
    default: Any = None,
) -> Any:
    """Liest defensiv einen verschachtelten Wert aus einem Dict."""
    if not isinstance(data, Mapping):
        return default

    try:
        current: Any = data

        for part in str(path).split("."):
            if not isinstance(current, Mapping):
                return default

            if part not in current:
                return default

            current = current[part]

        return current

    except Exception:
        return default


def first_non_empty(*values: Any, default: Any = None) -> Any:
    """Gibt den ersten nicht-leeren Wert zurück."""
    try:
        for value in values:
            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            if isinstance(value, (list, tuple, set, dict)) and not value:
                continue

            return value

        return default

    except Exception:
        return default


def normalize_reader_status(value: Any) -> str:
    """Normalisiert Reader-Status."""
    text = safe_str(value, default=DEFAULT_READER_STATUS).lower()

    if text in VALID_READER_STATUSES:
        return text

    return DEFAULT_READER_STATUS


def normalize_candidate_id(value: Any) -> str:
    """Baut eine stabile Kandidaten-ID aus Pfad oder String."""
    text = safe_str(value, default="unknown.candidate").replace("\\", "/").lower()
    text = text.strip("/")

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


def fallback_normalize_slug(value: Any, *, default: str = "") -> str:
    """Fallback-Slugnormalisierung."""
    text = safe_str(value, default="").lower()

    if not text:
        return default

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

    result = "".join(chars).strip("_-")
    return result or default


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_SETTINGS_IMPORT_ERROR: BaseException | None = None
_DISCOVERY_IMPORT_ERROR: BaseException | None = None
_DETAIL_IMPORT_ERROR: BaseException | None = None
_SCAN_RESULT_IMPORT_ERROR: BaseException | None = None
_TAXONOMY_IMPORT_ERROR: BaseException | None = None

try:
    from config.library_settings import (
        DEFAULT_ALLOWED_MANIFEST_FILENAMES,
        DEFAULT_IGNORED_DIRECTORY_NAMES,
        DEFAULT_IGNORED_FILE_SUFFIXES,
        DEFAULT_OPTIONAL_SUMMARY_FILES,
        DEFAULT_REQUIRED_PACKAGE_FILES,
        LibraryScanOptions,
        get_library_scan_options,
        get_settings_summary,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SETTINGS_IMPORT_ERROR = import_exc

    DEFAULT_ALLOWED_MANIFEST_FILENAMES = DEFAULT_ALLOWED_MANIFEST_FILENAMES_FALLBACK
    DEFAULT_REQUIRED_PACKAGE_FILES = DEFAULT_REQUIRED_PACKAGE_FILES_FALLBACK
    DEFAULT_OPTIONAL_SUMMARY_FILES = DEFAULT_OPTIONAL_SUMMARY_FILES_FALLBACK
    DEFAULT_IGNORED_DIRECTORY_NAMES = DEFAULT_IGNORED_DIRECTORY_NAMES_FALLBACK
    DEFAULT_IGNORED_FILE_SUFFIXES = DEFAULT_IGNORED_FILE_SUFFIXES_FALLBACK
    LibraryScanOptions = Any  # type: ignore[assignment]

    def get_library_scan_options(*, refresh: bool = False) -> Any:
        return None

    def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
        return {
            "ok": False,
            "fallback_active": True,
            "error": exception_to_dict(_SETTINGS_IMPORT_ERROR) if _SETTINGS_IMPORT_ERROR else None,
        }


try:
    from library.scanner import package_discovery as _package_discovery

    PackageDiscoveryCandidate = getattr(_package_discovery, "PackageDiscoveryCandidate", Any)
    PackageDiscoveryResult = getattr(_package_discovery, "PackageDiscoveryResult", Any)
    discovery_safe_resolve = getattr(_package_discovery, "safe_resolve", safe_resolve)
    discovery_taxonomy_from_relative_path = getattr(_package_discovery, "taxonomy_from_relative_path", None)
    discovery_normalize_source_path_string = getattr(_package_discovery, "normalize_source_path_string", None)
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DISCOVERY_IMPORT_ERROR = import_exc

    PackageDiscoveryCandidate = Any  # type: ignore[assignment]
    PackageDiscoveryResult = Any  # type: ignore[assignment]

    def discovery_safe_resolve(path: Path) -> Path:
        return safe_resolve(path)

    discovery_taxonomy_from_relative_path = None
    discovery_normalize_source_path_string = None


try:
    from library.domain.library_detail import (
        MANIFEST_DOCUMENT_KEY,
        MODULES_DOCUMENT_KEY,
        extract_family_id_from_documents,
        extract_package_id_from_documents,
        normalize_document_key as detail_normalize_document_key,
        normalize_documents as detail_normalize_documents,
    )

    normalize_document_key = detail_normalize_document_key
    normalize_documents = detail_normalize_documents

except Exception as import_exc:  # pragma: no cover - defensive fallback
    _DETAIL_IMPORT_ERROR = import_exc

    MANIFEST_DOCUMENT_KEY = "vplib.manifest.json"
    MODULES_DOCUMENT_KEY = "vplib.modules.json"

    def extract_package_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
        docs = normalize_documents(documents)
        manifest = ensure_dict(docs.get(MANIFEST_DOCUMENT_KEY))
        value = manifest.get("package_id") or manifest.get("id")
        text = safe_str(value, default="")
        return text or None

    def extract_family_id_from_documents(documents: Mapping[str, Any] | None) -> str | None:
        docs = normalize_documents(documents)
        manifest = ensure_dict(docs.get(MANIFEST_DOCUMENT_KEY))
        identity = ensure_dict(docs.get("family/identity.json"))
        value = (
            manifest.get("family_id")
            or identity.get("family_id")
            or identity.get("id")
            or manifest.get("id")
            or manifest.get("package_id")
        )
        text = safe_str(value, default="")
        return text or None


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
        INVALID = type("StatusValue", (), {"value": "invalid"})()
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
        package_id: str | None = None
        family_id: str | None = None
        item_id: str | None = None
        label: str | None = None
        object_kind: str | None = None
        source_path: str | None = None
        package_root: str | None = None
        relative_package_root: str | None = None
        manifest_path: str | None = None
        document_count: int = 0
        loaded_document_keys: tuple[str, ...] = field(default_factory=tuple)
        missing_required_files: tuple[str, ...] = field(default_factory=tuple)
        warnings: tuple[str, ...] = field(default_factory=tuple)
        errors: tuple[str, ...] = field(default_factory=tuple)
        messages: tuple[Any, ...] = field(default_factory=tuple)
        metadata: dict[str, Any] = field(default_factory=dict)

        @classmethod
        def from_raw(cls, **kwargs: Any) -> "LibraryScanCandidate":
            return cls(
                candidate_id=safe_str(kwargs.get("candidate_id"), default="unknown.candidate"),
                status=safe_str(kwargs.get("status"), default="candidate"),
                valid=bool(kwargs.get("valid", False)),
                package_id=safe_str(kwargs.get("package_id"), default="") or None,
                family_id=safe_str(kwargs.get("family_id"), default="") or None,
                item_id=safe_str(kwargs.get("item_id"), default="") or None,
                label=safe_str(kwargs.get("label"), default="") or None,
                object_kind=safe_str(kwargs.get("object_kind"), default="") or None,
                source_path=safe_path_str(kwargs.get("source_path")),
                package_root=safe_path_str(kwargs.get("package_root")),
                relative_package_root=safe_path_str(kwargs.get("relative_package_root")),
                manifest_path=safe_path_str(kwargs.get("manifest_path")),
                document_count=safe_int(kwargs.get("document_count"), default=0, minimum=0),
                loaded_document_keys=tuple_of_strings(kwargs.get("loaded_document_keys")),
                missing_required_files=tuple_of_strings(kwargs.get("missing_required_files")),
                warnings=tuple_of_strings(kwargs.get("warnings")),
                errors=tuple_of_strings(kwargs.get("errors")),
                messages=tuple(kwargs.get("messages") or ()),
                metadata=ensure_dict(kwargs.get("metadata")),
            )

        def to_dict(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return asdict(self)

    def monotonic_ms() -> int:
        return monotonic_ms_safe()


try:
    from library.taxonomy import normalize_slug as taxonomy_normalize_slug
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _TAXONOMY_IMPORT_ERROR = import_exc
    taxonomy_normalize_slug = fallback_normalize_slug  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Taxonomy helpers
# ---------------------------------------------------------------------------

def normalize_taxonomy_slug(value: Any) -> str:
    """Normalisiert Taxonomie-Slugs."""
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

        slug = normalize_taxonomy_slug(text)
        if slug:
            result.append(slug)

    return tuple(result)


def normalize_source_path_string(value: Any) -> str:
    """Normalisiert Source-Pfad auf Slash-Syntax."""
    if callable(discovery_normalize_source_path_string):
        try:
            return discovery_normalize_source_path_string(value)  # type: ignore[misc]
        except Exception:
            pass

    return "/".join(normalize_source_path_parts(value))


def infer_source_layout(parts: Iterable[Any]) -> str:
    """Leitet Source-Layout aus relativer Pfadtiefe ab."""
    normalized = tuple(normalize_source_path_parts(parts))

    if len(normalized) == CANONICAL_SOURCE_DEPTH:
        return SOURCE_LAYOUT_CANONICAL

    if len(normalized) == LEGACY_SOURCE_DEPTH:
        return SOURCE_LAYOUT_LEGACY

    return SOURCE_LAYOUT_UNKNOWN


def taxonomy_from_relative_path(relative_package_root: Any) -> dict[str, Any]:
    """Extrahiert Taxonomiepfad-Information aus relative_package_root."""
    if callable(discovery_taxonomy_from_relative_path):
        try:
            result = discovery_taxonomy_from_relative_path(relative_package_root)
            if isinstance(result, Mapping):
                return dict(result)
        except Exception:
            pass

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


def extract_classification_from_documents(documents: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extrahiert Taxonomie-Klassifikation aus gelesenen Dokumenten."""
    docs = normalize_documents(documents)
    manifest = ensure_dict(docs.get(MANIFEST_DOCUMENT_KEY))
    classification = ensure_dict(docs.get("family/classification.json"))
    inventory = ensure_dict(docs.get("editor/inventory.json"))

    domain = first_non_empty(
        deep_get(manifest, "domain"),
        deep_get(manifest, "classification.domain"),
        deep_get(classification, "domain"),
        deep_get(classification, "classification.domain"),
        deep_get(inventory, "domain"),
    )
    category = first_non_empty(
        deep_get(manifest, "category"),
        deep_get(manifest, "classification.category"),
        deep_get(classification, "category"),
        deep_get(classification, "classification.category"),
        deep_get(inventory, "category"),
    )
    subcategory = first_non_empty(
        deep_get(manifest, "subcategory"),
        deep_get(manifest, "classification.subcategory"),
        deep_get(classification, "subcategory"),
        deep_get(classification, "classification.subcategory"),
        deep_get(inventory, "subcategory"),
    )
    taxonomy_version = first_non_empty(
        deep_get(manifest, "taxonomy_version"),
        deep_get(manifest, "classification.taxonomy_version"),
        deep_get(classification, "taxonomy_version"),
        deep_get(classification, "classification.taxonomy_version"),
        deep_get(inventory, "taxonomy_version"),
    )
    source_path = first_non_empty(
        deep_get(manifest, "source_path"),
        deep_get(classification, "source_path"),
        deep_get(inventory, "source_path"),
    )
    classification_path = first_non_empty(
        deep_get(manifest, "classification_path"),
        deep_get(manifest, "classification.path"),
        deep_get(classification, "classification_path"),
        deep_get(classification, "classification.path"),
        deep_get(inventory, "classification_path"),
    )

    return {
        "domain": normalize_taxonomy_slug(domain) or None,
        "category": normalize_taxonomy_slug(category) or None,
        "subcategory": normalize_taxonomy_slug(subcategory) or None,
        "taxonomy_version": safe_str(taxonomy_version, default="") or None,
        "source_path": normalize_source_path_string(source_path) or None,
        "classification_path": normalize_source_path_string(classification_path) or None,
    }


def extract_family_slug_from_documents(documents: Mapping[str, Any] | None) -> str | None:
    """Extrahiert Family-Slug aus Dokumenten."""
    docs = normalize_documents(documents)
    manifest = ensure_dict(docs.get(MANIFEST_DOCUMENT_KEY))
    identity = ensure_dict(docs.get("family/identity.json"))
    classification = ensure_dict(docs.get("family/classification.json"))

    value = first_non_empty(
        deep_get(identity, "slug"),
        deep_get(identity, "family_slug"),
        deep_get(manifest, "family_slug"),
    )
    slug = normalize_taxonomy_slug(value)
    if slug:
        return slug

    source_path = first_non_empty(
        deep_get(manifest, "source_path"),
        deep_get(classification, "source_path"),
    )
    parts = normalize_source_path_parts(source_path)
    if len(parts) >= 4:
        return parts[-1]

    family_id = extract_family_id_from_documents(documents)
    if family_id:
        candidate = safe_str(family_id, default="").split(".")[-1]
        slug = normalize_taxonomy_slug(candidate)
        if slug:
            return slug

    return None


def build_reader_taxonomy_metadata(
    *,
    package_root: Any,
    source_root: Any,
    relative_package_root: Any,
    documents: Mapping[str, Any],
    discovery_metadata: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """
    Baut Taxonomie-Metadaten für PackageReadResult.

    Rückgabe:
        metadata, warnings
    """
    warnings: list[str] = []
    discovery_data = ensure_dict(discovery_metadata)
    discovery_taxonomy = ensure_dict(discovery_data.get("taxonomy"))

    resolved_relative = safe_str(relative_package_root, default="")
    if not resolved_relative and package_root and source_root:
        root_path = safe_path(package_root)
        source_path = safe_path(source_root)
        if root_path is not None and source_path is not None:
            resolved_relative = make_relative_path(safe_resolve(root_path), safe_resolve(source_path))

    path_taxonomy = taxonomy_from_relative_path(resolved_relative)
    document_taxonomy = extract_classification_from_documents(documents)
    family_slug_from_docs = extract_family_slug_from_documents(documents)

    layout = (
        safe_str(discovery_taxonomy.get("layout"), default="")
        or safe_str(path_taxonomy.get("layout"), default="")
        or SOURCE_LAYOUT_UNKNOWN
    )

    domain = first_non_empty(
        path_taxonomy.get("domain"),
        discovery_taxonomy.get("domain"),
        document_taxonomy.get("domain"),
        default="",
    )
    category = first_non_empty(
        path_taxonomy.get("category"),
        discovery_taxonomy.get("category"),
        document_taxonomy.get("category"),
        default="",
    )
    subcategory = first_non_empty(
        path_taxonomy.get("subcategory"),
        discovery_taxonomy.get("subcategory"),
        document_taxonomy.get("subcategory"),
        default="",
    )
    family_slug = first_non_empty(
        path_taxonomy.get("family_slug"),
        discovery_taxonomy.get("family_slug"),
        family_slug_from_docs,
        default="",
    )

    source_path = first_non_empty(
        path_taxonomy.get("source_path"),
        discovery_taxonomy.get("source_path"),
        document_taxonomy.get("source_path"),
        default="",
    )
    classification_path = first_non_empty(
        path_taxonomy.get("classification_path"),
        discovery_taxonomy.get("classification_path"),
        document_taxonomy.get("classification_path"),
        default="",
    )

    doc_domain = safe_str(document_taxonomy.get("domain"), default="")
    doc_category = safe_str(document_taxonomy.get("category"), default="")
    doc_subcategory = safe_str(document_taxonomy.get("subcategory"), default="")
    doc_source_path = safe_str(document_taxonomy.get("source_path"), default="")
    doc_classification_path = safe_str(document_taxonomy.get("classification_path"), default="")

    if doc_domain and domain and doc_domain != domain:
        warnings.append(f"Document domain '{doc_domain}' differs from path domain '{domain}'.")

    if doc_category and category and doc_category != category:
        warnings.append(f"Document category '{doc_category}' differs from path category '{category}'.")

    if layout == SOURCE_LAYOUT_CANONICAL and doc_subcategory and subcategory and doc_subcategory != subcategory:
        warnings.append(f"Document subcategory '{doc_subcategory}' differs from path subcategory '{subcategory}'.")

    if doc_source_path and source_path and doc_source_path != source_path:
        warnings.append(f"Document source_path '{doc_source_path}' differs from path source_path '{source_path}'.")

    if doc_classification_path and classification_path and doc_classification_path != classification_path:
        warnings.append(
            f"Document classification_path '{doc_classification_path}' differs from path classification_path '{classification_path}'."
        )

    return {
        "layout": layout,
        "canonical": layout == SOURCE_LAYOUT_CANONICAL,
        "legacy": layout == SOURCE_LAYOUT_LEGACY,
        "unknown_layout": layout == SOURCE_LAYOUT_UNKNOWN,
        "domain": normalize_taxonomy_slug(domain) or None,
        "category": normalize_taxonomy_slug(category) or None,
        "subcategory": normalize_taxonomy_slug(subcategory) or None,
        "family_slug": normalize_taxonomy_slug(family_slug) or None,
        "source_path": normalize_source_path_string(source_path) or None,
        "classification_path": normalize_source_path_string(classification_path) or None,
        "taxonomy_version": safe_str(document_taxonomy.get("taxonomy_version"), default="") or None,
        "path": json_safe(path_taxonomy),
        "document": json_safe(document_taxonomy),
        "discovery": json_safe(discovery_taxonomy),
    }, tuple(warnings)


# ---------------------------------------------------------------------------
# Path / document normalization helpers
# ---------------------------------------------------------------------------

def normalize_required_files(value: Any) -> tuple[str, ...]:
    """Normalisiert Pflichtdateien auf paketrelative Dokumentkeys."""
    files = tuple_of_strings(value)

    if not files:
        files = tuple(DEFAULT_REQUIRED_PACKAGE_FILES)

    result: list[str] = []

    for file in files:
        key = normalize_document_key(file)

        if key and key not in result:
            result.append(key)

    for key in TAXONOMY_REQUIRED_READER_FILES:
        normalized_key = normalize_document_key(key)
        if normalized_key and normalized_key not in result:
            result.append(normalized_key)

    return tuple(result)


def normalize_optional_files(value: Any) -> tuple[str, ...]:
    """Normalisiert optionale Summary-Dateien."""
    files = tuple_of_strings(value)

    if not files:
        files = tuple(DEFAULT_OPTIONAL_SUMMARY_FILES)

    result: list[str] = []

    for file in files:
        key = normalize_document_key(file)

        if key and key not in result and key not in TAXONOMY_REQUIRED_READER_FILES:
            result.append(key)

    return tuple(result)


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


def normalize_ignored_file_suffixes(value: Any) -> tuple[str, ...]:
    """Normalisiert ignorierte Dateisuffixe."""
    suffixes = tuple_of_strings(value)

    if not suffixes:
        suffixes = tuple(DEFAULT_IGNORED_FILE_SUFFIXES)

    result: list[str] = []

    for suffix in suffixes:
        clean = safe_str(suffix, default="").lower()

        if clean and not clean.startswith("."):
            clean = f".{clean}"

        if clean and clean not in result:
            result.append(clean)

    return tuple(result)


def document_key_to_path(package_root: Path, document_key: Any) -> Path:
    """Wandelt einen paketrelativen Dokumentkey in einen Pfad um."""
    key = normalize_document_key(document_key)

    if not key:
        raise ValueError("document key is empty")

    if key.startswith("../") or "/../" in key or key == "..":
        raise ValueError(f"document key may not traverse outside package: {key}")

    return package_root / Path(key)


def path_to_document_key(package_root: Path, path: Path) -> str:
    """Wandelt einen absoluten Pfad in einen paketrelativen Dokumentkey um."""
    resolved_package_root = safe_resolve(package_root)
    resolved_path = safe_resolve(path)

    if not path_is_relative_to(resolved_path, resolved_package_root):
        raise ValueError(f"path is outside package root: {resolved_path}")

    return normalize_document_key(make_relative_path(resolved_path, resolved_package_root))


def is_ignored_file(path: Path, ignored_file_suffixes: Iterable[str]) -> bool:
    """Prüft, ob eine Datei wegen Suffix ignoriert werden soll."""
    try:
        suffix = path.suffix.lower()
        return suffix in set(ignored_file_suffixes)
    except Exception:
        return False


def is_ignored_directory(path: Path, ignored_directory_names: Iterable[str]) -> bool:
    """Prüft, ob ein Verzeichnisname ignoriert werden soll."""
    try:
        return path.name in set(ignored_directory_names)
    except Exception:
        return False


def extract_label_from_documents(documents: Mapping[str, Any] | None) -> str | None:
    """Extrahiert ein Label aus gelesenen Dokumenten."""
    docs = normalize_documents(documents)
    manifest = ensure_dict(docs.get(MANIFEST_DOCUMENT_KEY))
    identity = ensure_dict(docs.get("family/identity.json"))
    inventory = ensure_dict(docs.get("editor/inventory.json"))

    value = first_non_empty(
        deep_get(identity, "label"),
        deep_get(identity, "name"),
        deep_get(identity, "family_name"),
        deep_get(manifest, "family_name"),
        deep_get(inventory, "label"),
    )

    text = safe_str(value, default="")
    return text or None


def extract_object_kind_from_documents(documents: Mapping[str, Any] | None) -> str | None:
    """Extrahiert object_kind aus gelesenen Dokumenten."""
    docs = normalize_documents(documents)
    manifest = ensure_dict(docs.get(MANIFEST_DOCUMENT_KEY))
    identity = ensure_dict(docs.get("family/identity.json"))
    classification = ensure_dict(docs.get("family/classification.json"))
    physical_base = ensure_dict(docs.get("physical/base.json"))

    value = first_non_empty(
        deep_get(manifest, "object_kind"),
        deep_get(identity, "object_kind"),
        deep_get(classification, "object_kind"),
        deep_get(physical_base, "object_kind"),
    )

    text = safe_str(value, default="")
    return text or None


# ---------------------------------------------------------------------------
# Reader options
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackageReaderOptions:
    """Konfiguration für das Lesen eines VPLIB-Package-Ordners."""

    required_package_files: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_REQUIRED_PACKAGE_FILES)
    )
    optional_summary_files: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_OPTIONAL_SUMMARY_FILES)
    )
    ignored_directory_names: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_IGNORED_DIRECTORY_NAMES)
    )
    ignored_file_suffixes: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_IGNORED_FILE_SUFFIXES)
    )
    read_all_json_documents: bool = DEFAULT_READ_ALL_JSON_DOCUMENTS
    include_optional_summary_files: bool = DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES
    fail_on_json_error: bool = DEFAULT_FAIL_ON_JSON_ERROR
    fail_on_missing_required: bool = DEFAULT_FAIL_ON_MISSING_REQUIRED
    max_json_file_size_bytes: int = DEFAULT_MAX_JSON_FILE_SIZE_BYTES
    text_encoding: str = DEFAULT_TEXT_ENCODING
    preserve_discovery_metadata: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_package_files", normalize_required_files(self.required_package_files))
        object.__setattr__(self, "optional_summary_files", normalize_optional_files(self.optional_summary_files))
        object.__setattr__(self, "ignored_directory_names", normalize_ignored_directory_names(self.ignored_directory_names))
        object.__setattr__(self, "ignored_file_suffixes", normalize_ignored_file_suffixes(self.ignored_file_suffixes))
        object.__setattr__(self, "read_all_json_documents", safe_bool(self.read_all_json_documents, default=DEFAULT_READ_ALL_JSON_DOCUMENTS))
        object.__setattr__(self, "include_optional_summary_files", safe_bool(self.include_optional_summary_files, default=DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES))
        object.__setattr__(self, "fail_on_json_error", safe_bool(self.fail_on_json_error, default=DEFAULT_FAIL_ON_JSON_ERROR))
        object.__setattr__(self, "fail_on_missing_required", safe_bool(self.fail_on_missing_required, default=DEFAULT_FAIL_ON_MISSING_REQUIRED))
        object.__setattr__(
            self,
            "max_json_file_size_bytes",
            safe_int(
                self.max_json_file_size_bytes,
                default=DEFAULT_MAX_JSON_FILE_SIZE_BYTES,
                minimum=1024,
                maximum=MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT,
            ),
        )
        object.__setattr__(self, "text_encoding", safe_str(self.text_encoding, default=DEFAULT_TEXT_ENCODING))
        object.__setattr__(self, "preserve_discovery_metadata", safe_bool(self.preserve_discovery_metadata, default=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_package_files": list(self.required_package_files),
            "optional_summary_files": list(self.optional_summary_files),
            "ignored_directory_names": list(self.ignored_directory_names),
            "ignored_file_suffixes": list(self.ignored_file_suffixes),
            "read_all_json_documents": self.read_all_json_documents,
            "include_optional_summary_files": self.include_optional_summary_files,
            "fail_on_json_error": self.fail_on_json_error,
            "fail_on_missing_required": self.fail_on_missing_required,
            "max_json_file_size_bytes": self.max_json_file_size_bytes,
            "text_encoding": self.text_encoding,
            "preserve_discovery_metadata": self.preserve_discovery_metadata,
        }

    @classmethod
    def from_settings(cls, settings_options: Any = None) -> "PackageReaderOptions":
        """Baut Reader-Optionen aus `LibraryScanOptions`, wenn verfügbar."""
        try:
            options = settings_options if settings_options is not None else get_library_scan_options()

            if options is None:
                return cls()

            return cls(
                required_package_files=get_attr_or_key(
                    options,
                    "required_package_files",
                    default=DEFAULT_REQUIRED_PACKAGE_FILES,
                ),
                optional_summary_files=get_attr_or_key(
                    options,
                    "optional_summary_files",
                    default=DEFAULT_OPTIONAL_SUMMARY_FILES,
                ),
                ignored_directory_names=get_attr_or_key(
                    options,
                    "ignored_directory_names",
                    default=DEFAULT_IGNORED_DIRECTORY_NAMES,
                ),
                ignored_file_suffixes=get_attr_or_key(
                    options,
                    "ignored_file_suffixes",
                    default=DEFAULT_IGNORED_FILE_SUFFIXES,
                ),
                read_all_json_documents=safe_bool(
                    get_attr_or_key(options, "read_all_json_documents", default=True),
                    default=True,
                ),
                include_optional_summary_files=safe_bool(
                    get_attr_or_key(options, "include_optional_summary_files", default=True),
                    default=True,
                ),
                fail_on_json_error=safe_bool(
                    get_attr_or_key(options, "fail_on_json_error", default=False),
                    default=False,
                ),
                fail_on_missing_required=safe_bool(
                    get_attr_or_key(options, "fail_on_missing_required", default=False),
                    default=False,
                ),
                max_json_file_size_bytes=safe_int(
                    get_attr_or_key(options, "max_json_file_size_bytes", default=DEFAULT_MAX_JSON_FILE_SIZE_BYTES),
                    default=DEFAULT_MAX_JSON_FILE_SIZE_BYTES,
                    minimum=1024,
                    maximum=MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT,
                ),
                text_encoding=safe_str(
                    get_attr_or_key(options, "text_encoding", default=DEFAULT_TEXT_ENCODING),
                    default=DEFAULT_TEXT_ENCODING,
                ),
                preserve_discovery_metadata=safe_bool(
                    get_attr_or_key(options, "preserve_discovery_metadata", default=True),
                    default=True,
                ),
            )

        except Exception:
            return cls()


def coerce_reader_options(value: PackageReaderOptions | Mapping[str, Any] | None = None) -> PackageReaderOptions:
    """Normalisiert optionale Reader-Options."""
    if isinstance(value, PackageReaderOptions):
        return value

    if value is None:
        return PackageReaderOptions()

    try:
        data = ensure_dict(value)

        if not data:
            return PackageReaderOptions()

        allowed = {
            "required_package_files",
            "optional_summary_files",
            "ignored_directory_names",
            "ignored_file_suffixes",
            "read_all_json_documents",
            "include_optional_summary_files",
            "fail_on_json_error",
            "fail_on_missing_required",
            "max_json_file_size_bytes",
            "text_encoding",
            "preserve_discovery_metadata",
        }

        return PackageReaderOptions(
            **{key: item for key, item in data.items() if key in allowed}
        )

    except Exception:
        return PackageReaderOptions()


# ---------------------------------------------------------------------------
# Reader domain models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackageReadMessage:
    """Einzelne Reader-Meldung."""

    level: str
    message: str
    code: str | None = None
    path: str | None = None
    document_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        level = safe_str(self.level, default="info").lower()

        if level not in {"debug", "info", "warning", "error", "fatal"}:
            level = "info"

        object.__setattr__(self, "level", level)
        object.__setattr__(self, "message", safe_str(self.message, default=""))
        object.__setattr__(self, "code", safe_str(self.code, default="") or None)
        object.__setattr__(self, "path", safe_path_str(self.path))
        object.__setattr__(self, "document_key", normalize_document_key(self.document_key) if self.document_key else None)
        object.__setattr__(self, "data", ensure_dict(self.data))

    @classmethod
    def error(
        cls,
        message: str,
        *,
        code: str | None = None,
        path: Any = None,
        document_key: Any = None,
        exc: BaseException | None = None,
    ) -> "PackageReadMessage":
        data: dict[str, Any] = {}

        if exc is not None:
            data["exception"] = exception_to_dict(exc)

        return cls(
            level="error",
            message=message,
            code=code,
            path=safe_path_str(path),
            document_key=normalize_document_key(document_key) if document_key else None,
            data=data,
        )

    @classmethod
    def warning(
        cls,
        message: str,
        *,
        code: str | None = None,
        path: Any = None,
        document_key: Any = None,
        data: Mapping[str, Any] | None = None,
    ) -> "PackageReadMessage":
        return cls(
            level="warning",
            message=message,
            code=code,
            path=safe_path_str(path),
            document_key=normalize_document_key(document_key) if document_key else None,
            data=ensure_dict(data),
        )

    def to_scan_message(self) -> LibraryScanMessage:
        """Wandelt Reader-Meldung in allgemeine Scan-Meldung."""
        try:
            return LibraryScanMessage(
                level=self.level,
                message=self.message,
                code=self.code,
                path=self.path,
                document_key=self.document_key,
                data=self.data,
            )
        except TypeError:
            try:
                return LibraryScanMessage(
                    level=self.level,
                    message=self.message,
                    code=self.code,
                    path=self.path,
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
            "document_key": self.document_key,
            "data": json_safe(self.data),
        }


@dataclass(frozen=True)
class PackageDocument:
    """Ein gelesenes Dokument innerhalb eines VPLIB-Pakets."""

    key: str
    path: str
    data: Any
    size_bytes: int = 0
    loaded: bool = True
    error: dict[str, Any] | None = None
    read_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", normalize_document_key(self.key))
        object.__setattr__(self, "path", safe_path_str(self.path) or "")
        object.__setattr__(self, "size_bytes", safe_int(self.size_bytes, default=0, minimum=0))
        object.__setattr__(self, "loaded", safe_bool(self.loaded, default=True))
        object.__setattr__(self, "error", ensure_dict(self.error) if self.error else None)
        object.__setattr__(self, "read_at", safe_str(self.read_at, default=utc_now_iso()))

    @property
    def filename(self) -> str:
        try:
            return self.key.split("/")[-1]
        except Exception:
            return self.key

    @property
    def group(self) -> str:
        try:
            if "/" not in self.key:
                return "root"
            return self.key.split("/", 1)[0]
        except Exception:
            return "unknown"

    def to_dict(self, *, include_data: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "key": self.key,
            "path": self.path,
            "filename": self.filename,
            "group": self.group,
            "size_bytes": self.size_bytes,
            "loaded": self.loaded,
            "error": json_safe(self.error),
            "read_at": self.read_at,
        }

        if include_data:
            result["data"] = json_safe(self.data)

        return result


@dataclass(frozen=True)
class PackageReadResult:
    """Ergebnis des Lesens eines VPLIB-Package-Ordners."""

    ok: bool
    status: str
    package_root: str | None
    manifest_path: str | None = None
    source_root: str | None = None
    relative_package_root: str | None = None

    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = field(default_factory=utc_now_iso)
    duration_ms: int = 0

    package_id: str | None = None
    family_id: str | None = None
    item_id: str | None = None
    label: str | None = None
    object_kind: str | None = None

    source_layout: str | None = None
    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    family_slug: str | None = None
    source_path: str | None = None
    classification_path: str | None = None
    taxonomy_version: str | None = None

    documents: dict[str, Any] = field(default_factory=dict)
    document_entries: tuple[PackageDocument, ...] = field(default_factory=tuple)

    loaded_document_keys: tuple[str, ...] = field(default_factory=tuple)
    missing_required_files: tuple[str, ...] = field(default_factory=tuple)
    unreadable_files: tuple[str, ...] = field(default_factory=tuple)

    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    messages: tuple[PackageReadMessage, ...] = field(default_factory=tuple)

    options: PackageReaderOptions = field(default_factory=PackageReaderOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = PACKAGE_READER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.options, PackageReaderOptions):
            object.__setattr__(self, "options", coerce_reader_options(self.options))

        normalized_documents = normalize_documents(self.documents)
        loaded_keys = tuple(
            sorted(
                set(
                    tuple_of_strings(self.loaded_document_keys)
                    or tuple(normalized_documents.keys())
                )
            )
        )
        missing_required = tuple(sorted(set(tuple_of_strings(self.missing_required_files))))
        unreadable = tuple(sorted(set(tuple_of_strings(self.unreadable_files))))

        warning_tuple = tuple_of_strings(self.warnings)
        error_tuple = tuple_of_strings(self.errors)

        status = normalize_reader_status(self.status)

        if status == "unknown":
            if error_tuple and not normalized_documents:
                status = "error"
            elif missing_required or unreadable or error_tuple:
                status = "partial"
            elif normalized_documents:
                status = "ok"
            else:
                status = "invalid"

        effective_ok = bool(self.ok and status in {"ok", "partial"})

        object.__setattr__(self, "ok", effective_ok)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "package_root", safe_path_str(self.package_root))
        object.__setattr__(self, "manifest_path", safe_path_str(self.manifest_path))
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "relative_package_root", safe_path_str(self.relative_package_root))
        object.__setattr__(self, "duration_ms", safe_int(self.duration_ms, default=0, minimum=0))
        object.__setattr__(self, "package_id", safe_str(self.package_id, default="") or None)
        object.__setattr__(self, "family_id", safe_str(self.family_id, default="") or None)
        object.__setattr__(self, "item_id", safe_str(self.item_id, default="") or None)
        object.__setattr__(self, "label", safe_str(self.label, default="") or None)
        object.__setattr__(self, "object_kind", safe_str(self.object_kind, default="") or None)
        object.__setattr__(self, "source_layout", safe_str(self.source_layout, default=SOURCE_LAYOUT_UNKNOWN) or SOURCE_LAYOUT_UNKNOWN)
        object.__setattr__(self, "domain", normalize_taxonomy_slug(self.domain) or None)
        object.__setattr__(self, "category", normalize_taxonomy_slug(self.category) or None)
        object.__setattr__(self, "subcategory", normalize_taxonomy_slug(self.subcategory) or None)
        object.__setattr__(self, "family_slug", normalize_taxonomy_slug(self.family_slug) or None)
        object.__setattr__(self, "source_path", normalize_source_path_string(self.source_path) or None)
        object.__setattr__(self, "classification_path", normalize_source_path_string(self.classification_path) or None)
        object.__setattr__(self, "taxonomy_version", safe_str(self.taxonomy_version, default="") or None)
        object.__setattr__(self, "documents", normalized_documents)
        object.__setattr__(self, "document_entries", tuple(self.document_entries or ()))
        object.__setattr__(self, "loaded_document_keys", loaded_keys)
        object.__setattr__(self, "missing_required_files", missing_required)
        object.__setattr__(self, "unreadable_files", unreadable)
        object.__setattr__(self, "warnings", warning_tuple)
        object.__setattr__(self, "errors", error_tuple)
        object.__setattr__(self, "messages", tuple(self.messages or ()))
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "version", safe_str(self.version, default=PACKAGE_READER_VERSION))

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def error_count(self) -> int:
        return len(self.errors) + sum(1 for message in self.messages if message.level in {"error", "fatal"})

    @property
    def warning_count(self) -> int:
        return len(self.warnings) + sum(1 for message in self.messages if message.level == "warning")

    @property
    def has_missing_required_files(self) -> bool:
        return bool(self.missing_required_files)

    @property
    def has_unreadable_files(self) -> bool:
        return bool(self.unreadable_files)

    @property
    def is_complete_minimal_package(self) -> bool:
        return not self.has_missing_required_files and self.document_count > 0

    def get_document(self, key: Any, *, default: Any = None) -> Any:
        """Liest ein Dokument aus dem Ergebnis."""
        return self.documents.get(normalize_document_key(key), default)

    def to_scan_candidate(self) -> LibraryScanCandidate:
        """
        Wandelt das Leseergebnis in einen allgemeinen ScanCandidate um.

        Noch keine fachliche Validierung: valid=False.
        """
        if self.status == "error":
            candidate_status = LibraryScanCandidateStatus.ERROR.value
        elif self.status in {"partial", "invalid"}:
            candidate_status = LibraryScanCandidateStatus.INVALID.value
        else:
            candidate_status = LibraryScanCandidateStatus.CANDIDATE.value

        payload = {
            "candidate_id": self.item_id or self.family_id or self.package_id or self.relative_package_root or self.package_root or "unknown.candidate",
            "status": candidate_status,
            "valid": False,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "item_id": self.item_id or self.family_id,
            "label": self.label,
            "object_kind": self.object_kind,
            "source_path": self.package_root,
            "package_root": self.package_root,
            "relative_package_root": self.relative_package_root,
            "manifest_path": self.manifest_path,
            "document_count": self.document_count,
            "loaded_document_keys": self.loaded_document_keys,
            "missing_required_files": self.missing_required_files,
            "warnings": self.warnings,
            "errors": self.errors,
            "messages": [message.to_scan_message() for message in self.messages],
            "metadata": {
                "reader": self.to_dict(include_documents=False, include_document_entries=False),
                "taxonomy": {
                    "source_layout": self.source_layout,
                    "domain": self.domain,
                    "category": self.category,
                    "subcategory": self.subcategory,
                    "family_slug": self.family_slug,
                    "source_path": self.source_path,
                    "classification_path": self.classification_path,
                    "taxonomy_version": self.taxonomy_version,
                },
            },
        }

        return make_scan_candidate(payload)

    def to_dict(
        self,
        *,
        include_documents: bool = True,
        include_document_entries: bool = True,
        include_document_data: bool = False,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "package_root": self.package_root,
            "manifest_path": self.manifest_path,
            "source_root": self.source_root,
            "relative_package_root": self.relative_package_root,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "item_id": self.item_id,
            "label": self.label,
            "object_kind": self.object_kind,
            "taxonomy": {
                "source_layout": self.source_layout,
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "family_slug": self.family_slug,
                "source_path": self.source_path,
                "classification_path": self.classification_path,
                "taxonomy_version": self.taxonomy_version,
            },
            "document_count": self.document_count,
            "loaded_document_keys": list(self.loaded_document_keys),
            "missing_required_files": list(self.missing_required_files),
            "unreadable_files": list(self.unreadable_files),
            "is_complete_minimal_package": self.is_complete_minimal_package,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
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

        if include_documents:
            result["documents"] = json_safe(self.documents)

        if include_document_entries:
            result["document_entries"] = [
                entry.to_dict(include_data=include_document_data)
                for entry in self.document_entries
            ]

        return result

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        package_root: Any = None,
        manifest_path: Any = None,
        source_root: Any = None,
        relative_package_root: Any = None,
        started_at: Any = None,
        duration_ms: int = 0,
        options: PackageReaderOptions | None = None,
        include_traceback: bool = False,
        discovery_metadata: Mapping[str, Any] | None = None,
    ) -> "PackageReadResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        error_message = safe_str(error_data.get("message") if error_data else None, default="package read failed")
        taxonomy_metadata, taxonomy_warnings = build_reader_taxonomy_metadata(
            package_root=package_root,
            source_root=source_root,
            relative_package_root=relative_package_root,
            documents={},
            discovery_metadata=discovery_metadata,
        )

        return cls(
            ok=False,
            status="error",
            package_root=safe_path_str(package_root),
            manifest_path=safe_path_str(manifest_path),
            source_root=safe_path_str(source_root),
            relative_package_root=safe_path_str(relative_package_root),
            started_at=safe_str(started_at, default="") or utc_now_iso(),
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            source_layout=taxonomy_metadata.get("layout"),
            domain=taxonomy_metadata.get("domain"),
            category=taxonomy_metadata.get("category"),
            subcategory=taxonomy_metadata.get("subcategory"),
            family_slug=taxonomy_metadata.get("family_slug"),
            source_path=taxonomy_metadata.get("source_path"),
            classification_path=taxonomy_metadata.get("classification_path"),
            taxonomy_version=taxonomy_metadata.get("taxonomy_version"),
            documents={},
            document_entries=(),
            loaded_document_keys=(),
            missing_required_files=(),
            unreadable_files=(),
            warnings=taxonomy_warnings,
            errors=(error_message,),
            messages=(
                PackageReadMessage(
                    level="error",
                    message=error_message,
                    code=safe_str(error_data.get("type") if error_data else None, default="Exception"),
                    path=safe_path_str(package_root),
                    data={"exception": error_data},
                ),
            ),
            options=options or PackageReaderOptions(),
            metadata={
                "exception": error_data,
                "taxonomy": taxonomy_metadata,
                "discovery": json_safe(discovery_metadata or {}),
            },
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

    minimal_keys = {
        "candidate_id",
        "status",
        "valid",
        "package_id",
        "family_id",
        "item_id",
        "source_path",
        "package_root",
        "relative_package_root",
        "manifest_path",
        "document_count",
        "loaded_document_keys",
        "missing_required_files",
        "warnings",
        "errors",
        "metadata",
    }

    try:
        return LibraryScanCandidate(
            **{key: value for key, value in data.items() if key in minimal_keys}
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
# Reader implementation
# ---------------------------------------------------------------------------

def iter_json_files(
    package_root: Path,
    *,
    options: PackageReaderOptions,
) -> list[Path]:
    """Listet alle JSON-Dateien eines Package-Roots robust auf."""
    resolved_root = safe_resolve(package_root)
    result: list[Path] = []

    try:
        for current_root, dirnames, filenames in os.walk(resolved_root):
            current_path = Path(current_root)

            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname not in set(options.ignored_directory_names)
            ]

            for filename in filenames:
                try:
                    file_path = current_path / filename

                    if not file_path.is_file():
                        continue

                    if is_ignored_file(file_path, options.ignored_file_suffixes):
                        continue

                    if file_path.suffix.lower() != JSON_SUFFIX:
                        continue

                    resolved_file = safe_resolve(file_path)

                    if not path_is_relative_to(resolved_file, resolved_root):
                        continue

                    result.append(resolved_file)

                except Exception:
                    continue

        return sorted(
            result,
            key=lambda path: path_to_document_key(resolved_root, path),
        )

    except Exception:
        return []


def collect_document_keys_to_read(
    package_root: Path,
    *,
    options: PackageReaderOptions,
) -> tuple[str, ...]:
    """Ermittelt alle Dokumentkeys, die gelesen werden sollen."""
    keys: list[str] = []

    for key in options.required_package_files:
        normalized = normalize_document_key(key)

        if normalized and normalized not in keys:
            keys.append(normalized)

    if options.include_optional_summary_files:
        for key in options.optional_summary_files:
            normalized = normalize_document_key(key)

            if normalized and normalized not in keys:
                keys.append(normalized)

    if options.read_all_json_documents:
        for file_path in iter_json_files(package_root, options=options):
            try:
                key = path_to_document_key(package_root, file_path)

                if key and key not in keys:
                    keys.append(key)

            except Exception:
                continue

    return tuple(keys)


def read_json_document(
    package_root: Path,
    document_key: Any,
    *,
    options: PackageReaderOptions,
) -> tuple[PackageDocument | None, PackageReadMessage | None]:
    """Liest ein einzelnes JSON-Dokument robust."""
    key = normalize_document_key(document_key)

    try:
        if not key:
            return None, PackageReadMessage.error(
                "document key is empty",
                code="invalid_document_key",
                document_key=document_key,
            )

        resolved_package_root = safe_resolve(package_root)
        document_path = safe_resolve(document_key_to_path(resolved_package_root, key))

        if not path_is_relative_to(document_path, resolved_package_root):
            return None, PackageReadMessage.error(
                f"document path is outside package root: {key}",
                code="path_outside_package",
                path=document_path,
                document_key=key,
            )

        if not document_path.exists():
            return None, PackageReadMessage.warning(
                f"document does not exist: {key}",
                code="missing_document",
                path=document_path,
                document_key=key,
            )

        if not document_path.is_file():
            return None, PackageReadMessage.error(
                f"document path is not a file: {key}",
                code="not_a_file",
                path=document_path,
                document_key=key,
            )

        size_bytes = document_path.stat().st_size

        if size_bytes > options.max_json_file_size_bytes:
            return None, PackageReadMessage.error(
                f"json document is too large: {key}",
                code="file_too_large",
                path=document_path,
                document_key=key,
            )

        try:
            raw_text = document_path.read_text(encoding=options.text_encoding)
        except UnicodeDecodeError:
            raw_text = document_path.read_text(encoding="utf-8")

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            return None, PackageReadMessage.error(
                f"json decode error in {key}: {exc.msg}",
                code="json_decode_error",
                path=document_path,
                document_key=key,
                exc=exc,
            )

        return PackageDocument(
            key=key,
            path=str(document_path),
            data=data,
            size_bytes=size_bytes,
            loaded=True,
            error=None,
            read_at=utc_now_iso(),
        ), None

    except Exception as exc:
        return None, PackageReadMessage.error(
            f"could not read document: {key}",
            code="read_error",
            path=None,
            document_key=key,
            exc=exc,
        )


def read_package_root(
    package_root: Path,
    *,
    source_root: Path | None = None,
    manifest_path: Path | None = None,
    relative_package_root: str | None = None,
    options: PackageReaderOptions | Mapping[str, Any] | None = None,
    discovery_metadata: Mapping[str, Any] | None = None,
) -> PackageReadResult:
    """
    Liest einen VPLIB-Package-Root.

    Diese Funktion liest nur Dokumente und prüft minimale Dateipräsenz.
    Fachliche Validierung passiert später separat.
    """
    started_at = utc_now_iso()
    started_monotonic = monotonic_ms()
    reader_options = coerce_reader_options(options)

    documents: dict[str, Any] = {}
    document_entries: list[PackageDocument] = []
    messages: list[PackageReadMessage] = []
    warnings: list[str] = []
    errors: list[str] = []
    unreadable_files: list[str] = []

    try:
        resolved_package_root = safe_resolve(package_root)

        if not resolved_package_root.exists():
            raise FileNotFoundError(f"package root does not exist: {resolved_package_root}")

        if not resolved_package_root.is_dir():
            raise NotADirectoryError(f"package root is not a directory: {resolved_package_root}")

        resolved_source_root = safe_resolve(source_root) if source_root is not None else None

        if resolved_source_root is not None and not path_is_relative_to(resolved_package_root, resolved_source_root):
            warnings.append(
                f"package root is not below source root: {resolved_package_root}"
            )

        if manifest_path is None:
            for manifest_filename in DEFAULT_ALLOWED_MANIFEST_FILENAMES:
                possible_manifest = resolved_package_root / manifest_filename

                if possible_manifest.is_file():
                    manifest_path = possible_manifest
                    break

        resolved_manifest_path = safe_resolve(manifest_path) if manifest_path is not None else None

        if relative_package_root is None and resolved_source_root is not None:
            relative_package_root = make_relative_path(resolved_package_root, resolved_source_root)

        document_keys = collect_document_keys_to_read(
            resolved_package_root,
            options=reader_options,
        )

        required_key_set = set(reader_options.required_package_files)
        seen_keys: set[str] = set()

        for key in document_keys:
            normalized_key = normalize_document_key(key)

            if not normalized_key or normalized_key in seen_keys:
                continue

            seen_keys.add(normalized_key)

            document, message = read_json_document(
                resolved_package_root,
                normalized_key,
                options=reader_options,
            )

            if document is not None:
                documents[document.key] = document.data
                document_entries.append(document)

            if message is not None:
                messages.append(message)

                is_missing_optional = (
                    message.code == "missing_document"
                    and normalized_key not in required_key_set
                )

                if is_missing_optional:
                    continue

                if message.level in {"error", "fatal"}:
                    unreadable_files.append(normalized_key)
                    errors.append(message.message)

                    if reader_options.fail_on_json_error:
                        break

                elif message.level == "warning":
                    warnings.append(message.message)

        loaded_keys = tuple(sorted(documents.keys()))
        missing_required_files = tuple(
            key
            for key in reader_options.required_package_files
            if key not in documents
        )

        for missing_key in missing_required_files:
            message = f"required document is missing: {missing_key}"

            if message not in warnings:
                warnings.append(message)

            messages.append(
                PackageReadMessage.warning(
                    message,
                    code="missing_required_file",
                    path=str(resolved_package_root / missing_key),
                    document_key=missing_key,
                )
            )

        if missing_required_files and reader_options.fail_on_missing_required:
            errors.append("one or more required package documents are missing")

        package_id = extract_package_id_from_documents(documents)
        family_id = extract_family_id_from_documents(documents)
        item_id = family_id or package_id or normalize_candidate_id(relative_package_root or resolved_package_root)
        label = extract_label_from_documents(documents)
        object_kind = extract_object_kind_from_documents(documents)

        taxonomy_metadata, taxonomy_warnings = build_reader_taxonomy_metadata(
            package_root=resolved_package_root,
            source_root=resolved_source_root,
            relative_package_root=relative_package_root,
            documents=documents,
            discovery_metadata=discovery_metadata if reader_options.preserve_discovery_metadata else {},
        )

        for warning in taxonomy_warnings:
            if warning not in warnings:
                warnings.append(warning)
                messages.append(
                    PackageReadMessage.warning(
                        warning,
                        code="taxonomy_metadata_warning",
                        path=str(resolved_package_root),
                        data={"taxonomy": taxonomy_metadata},
                    )
                )

        duration_ms = max(0, monotonic_ms() - started_monotonic)

        if errors and not documents:
            status = "error"
        elif errors or unreadable_files or missing_required_files:
            status = "partial"
        elif documents:
            status = "ok"
        else:
            status = "invalid"

        return PackageReadResult(
            ok=status in {"ok", "partial"},
            status=status,
            package_root=str(resolved_package_root),
            manifest_path=str(resolved_manifest_path) if resolved_manifest_path is not None else None,
            source_root=str(resolved_source_root) if resolved_source_root is not None else None,
            relative_package_root=relative_package_root,
            started_at=started_at,
            finished_at=utc_now_iso(),
            duration_ms=duration_ms,
            package_id=package_id,
            family_id=family_id,
            item_id=item_id,
            label=label,
            object_kind=object_kind,
            source_layout=taxonomy_metadata.get("layout"),
            domain=taxonomy_metadata.get("domain"),
            category=taxonomy_metadata.get("category"),
            subcategory=taxonomy_metadata.get("subcategory"),
            family_slug=taxonomy_metadata.get("family_slug"),
            source_path=taxonomy_metadata.get("source_path"),
            classification_path=taxonomy_metadata.get("classification_path"),
            taxonomy_version=taxonomy_metadata.get("taxonomy_version"),
            documents=documents,
            document_entries=tuple(document_entries),
            loaded_document_keys=loaded_keys,
            missing_required_files=missing_required_files,
            unreadable_files=tuple(sorted(set(unreadable_files))),
            warnings=tuple(warnings),
            errors=tuple(errors),
            messages=tuple(messages),
            options=reader_options,
            metadata={
                "settings_import_error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
                "discovery_import_error": exception_to_dict(_DISCOVERY_IMPORT_ERROR),
                "detail_import_error": exception_to_dict(_DETAIL_IMPORT_ERROR),
                "scan_result_import_error": exception_to_dict(_SCAN_RESULT_IMPORT_ERROR),
                "taxonomy_import_error": exception_to_dict(_TAXONOMY_IMPORT_ERROR),
                "taxonomy": taxonomy_metadata,
                "discovery": json_safe(discovery_metadata or {}),
            },
        )

    except Exception as exc:
        duration_ms = max(0, monotonic_ms() - started_monotonic)

        return PackageReadResult.error(
            exc,
            package_root=package_root,
            manifest_path=manifest_path,
            source_root=source_root,
            relative_package_root=relative_package_root,
            started_at=started_at,
            duration_ms=duration_ms,
            options=reader_options,
            discovery_metadata=discovery_metadata,
        )


def discovery_candidate_to_metadata(candidate: Any) -> dict[str, Any]:
    """Extrahiert Discovery-Metadaten aus Candidate-Objekt oder Mapping."""
    try:
        if candidate is None:
            return {}

        if isinstance(candidate, Mapping):
            metadata = ensure_dict(candidate.get("metadata"))
            if "discovery" not in metadata:
                metadata["discovery"] = json_safe(candidate)
            return metadata

        if hasattr(candidate, "to_dict") and callable(candidate.to_dict):
            payload = candidate.to_dict()
            if isinstance(payload, Mapping):
                metadata = ensure_dict(payload.get("metadata"))
                if "discovery" not in metadata:
                    metadata["discovery"] = json_safe(payload)
                return metadata

        metadata = ensure_dict(getattr(candidate, "metadata", None))
        if "discovery" not in metadata:
            metadata["discovery"] = {
                "package_root": safe_path_str(getattr(candidate, "package_root", None)),
                "relative_package_root": safe_path_str(getattr(candidate, "relative_package_root", None)),
                "source_root": safe_path_str(getattr(candidate, "source_root", None)),
                "manifest_path": safe_path_str(getattr(candidate, "manifest_path", None)),
            }
        return metadata
    except Exception:
        return {}


def read_discovery_candidate(
    candidate: Any,
    *,
    options: PackageReaderOptions | Mapping[str, Any] | None = None,
) -> PackageReadResult:
    """Liest einen PackageDiscoveryCandidate oder ein kompatibles Mapping."""
    reader_options = coerce_reader_options(options)

    try:
        if isinstance(candidate, Mapping):
            package_root = safe_path(candidate.get("package_root") or candidate.get("source_path"))
            manifest_path = safe_path(candidate.get("manifest_path"))
            source_root = safe_path(candidate.get("source_root"))
            relative_package_root = safe_str(candidate.get("relative_package_root"), default="") or None
        else:
            package_root = safe_path(getattr(candidate, "package_root", None) or getattr(candidate, "source_path", None))
            manifest_path = safe_path(getattr(candidate, "manifest_path", None))
            source_root = safe_path(getattr(candidate, "source_root", None))
            relative_package_root = safe_str(getattr(candidate, "relative_package_root", None), default="") or None

        if package_root is None:
            raise ValueError("candidate package_root is missing")

        return read_package_root(
            package_root,
            source_root=source_root,
            manifest_path=manifest_path,
            relative_package_root=relative_package_root,
            options=reader_options,
            discovery_metadata=discovery_candidate_to_metadata(candidate),
        )

    except Exception as exc:
        if isinstance(candidate, Mapping):
            package_root_value = candidate.get("package_root")
            manifest_path_value = candidate.get("manifest_path")
            source_root_value = candidate.get("source_root")
            relative_value = candidate.get("relative_package_root")
        else:
            package_root_value = getattr(candidate, "package_root", None) if candidate is not None else None
            manifest_path_value = getattr(candidate, "manifest_path", None) if candidate is not None else None
            source_root_value = getattr(candidate, "source_root", None) if candidate is not None else None
            relative_value = getattr(candidate, "relative_package_root", None) if candidate is not None else None

        return PackageReadResult.error(
            exc,
            package_root=package_root_value,
            manifest_path=manifest_path_value,
            source_root=source_root_value,
            relative_package_root=relative_value,
            options=reader_options,
            discovery_metadata=discovery_candidate_to_metadata(candidate),
        )


def read_package_candidates(
    candidates: Iterable[Any],
    *,
    options: PackageReaderOptions | Mapping[str, Any] | None = None,
) -> list[PackageReadResult]:
    """Liest mehrere Discovery-Kandidaten."""
    reader_options = coerce_reader_options(options)
    results: list[PackageReadResult] = []

    for candidate in candidates or ():
        try:
            results.append(
                read_discovery_candidate(
                    candidate,
                    options=reader_options,
                )
            )
        except Exception as exc:
            results.append(
                PackageReadResult.error(
                    exc,
                    package_root=get_attr_or_key(candidate, "package_root"),
                    manifest_path=get_attr_or_key(candidate, "manifest_path"),
                    source_root=get_attr_or_key(candidate, "source_root"),
                    relative_package_root=get_attr_or_key(candidate, "relative_package_root"),
                    options=reader_options,
                    discovery_metadata=discovery_candidate_to_metadata(candidate),
                )
            )

    return results


def read_package_path(
    package_root: Any,
    *,
    source_root: Any = None,
    options: PackageReaderOptions | Mapping[str, Any] | None = None,
) -> PackageReadResult:
    """Convenience-Funktion zum direkten Lesen eines Package-Pfads."""
    root = safe_path(package_root)

    if root is None:
        return PackageReadResult.error(
            ValueError("package_root could not be resolved"),
            package_root=package_root,
            source_root=source_root,
            options=coerce_reader_options(options),
        )

    source = safe_path(source_root) if source_root is not None else None

    return read_package_root(
        root,
        source_root=source,
        options=options,
    )


def read_result_to_document_mapping(result: PackageReadResult | Mapping[str, Any] | None) -> dict[str, Any]:
    """Extrahiert ein reines Dokument-Mapping aus einem ReadResult."""
    try:
        if isinstance(result, PackageReadResult):
            return normalize_documents(result.documents)

        if isinstance(result, Mapping):
            documents = result.get("documents")

            if documents is not None:
                return normalize_documents(documents)

            if any(str(key).endswith(".json") or "/" in str(key) for key in result.keys()):
                return normalize_documents(result)

        documents = getattr(result, "documents", None)
        return normalize_documents(documents)

    except Exception:
        return {}


def read_results_to_scan_candidates(results: Iterable[PackageReadResult]) -> list[LibraryScanCandidate]:
    """Wandelt mehrere ReadResults in ScanCandidates."""
    candidates: list[LibraryScanCandidate] = []

    for result in results or ():
        try:
            candidates.append(result.to_scan_candidate())
        except Exception:
            continue

    return candidates


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def build_read_response(
    result: PackageReadResult | Mapping[str, Any] | None,
    *,
    include_documents: bool = True,
    include_document_entries: bool = True,
) -> dict[str, Any]:
    """Baut eine JSON-kompatible Reader-Antwort."""
    try:
        if isinstance(result, PackageReadResult):
            return result.to_dict(
                include_documents=include_documents,
                include_document_entries=include_document_entries,
                include_document_data=False,
            )

        if isinstance(result, Mapping):
            return json_safe(result)

        return {
            "ok": False,
            "status": "error",
            "errors": ["read result is empty"],
        }

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "errors": ["could not serialize read result"],
            "error": exception_to_dict(exc),
        }


def build_read_many_response(
    results: Iterable[PackageReadResult],
    *,
    include_documents: bool = False,
) -> dict[str, Any]:
    """Baut eine JSON-kompatible Antwort für mehrere gelesene Pakete."""
    result_list = list(results or ())

    ok_count = sum(1 for result in result_list if result.ok)
    error_count = sum(1 for result in result_list if result.status == "error")
    partial_count = sum(1 for result in result_list if result.status == "partial")

    return {
        "ok": error_count == 0,
        "status": "ok" if error_count == 0 else "partial" if ok_count > 0 else "error",
        "count": len(result_list),
        "ok_count": ok_count,
        "partial_count": partial_count,
        "error_count": error_count,
        "results": [
            result.to_dict(
                include_documents=include_documents,
                include_document_entries=True,
                include_document_data=False,
            )
            for result in result_list
        ],
    }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_package_reader_health(
    *,
    refresh_settings: bool = False,
) -> dict[str, Any]:
    """Health-Status der Package-Reader-Schicht. Führt keinen Package-Read aus."""
    warnings: list[str] = []
    errors: list[str] = []

    if _SETTINGS_IMPORT_ERROR is not None:
        warnings.append("config.library_settings import failed; fallback reader settings are active")

    if _DISCOVERY_IMPORT_ERROR is not None:
        warnings.append("package_discovery import failed; direct path reading still works")

    if _DETAIL_IMPORT_ERROR is not None:
        warnings.append("library_detail import failed; fallback document helpers are active")

    if _SCAN_RESULT_IMPORT_ERROR is not None:
        warnings.append("scan_result import failed; fallback scan candidate model is active")

    if _TAXONOMY_IMPORT_ERROR is not None:
        warnings.append("taxonomy import failed; slug normalization fallback is active")

    try:
        options = PackageReaderOptions.from_settings(
            get_library_scan_options(refresh=refresh_settings)
        )
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build reader options: {exc}")

    try:
        safe_int_self_test = safe_int("999999", default=500, minimum=1, maximum=5000)
        if safe_int_self_test != 5000:
            errors.append(f"safe_int maximum self-test failed: expected 5000, got {safe_int_self_test}")
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

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": PACKAGE_READER_COMPONENT,
        "version": PACKAGE_READER_VERSION,
        "generated_at": utc_now_iso(),
        "options": options_dict,
        "canonical_source_depth": CANONICAL_SOURCE_DEPTH,
        "legacy_source_depth": LEGACY_SOURCE_DEPTH,
        "taxonomy_required_reader_files": list(TAXONOMY_REQUIRED_READER_FILES),
        "imports": {
            "settings": {
                "ok": _SETTINGS_IMPORT_ERROR is None,
                "error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
            },
            "discovery": {
                "ok": _DISCOVERY_IMPORT_ERROR is None,
                "error": exception_to_dict(_DISCOVERY_IMPORT_ERROR),
            },
            "detail": {
                "ok": _DETAIL_IMPORT_ERROR is None,
                "error": exception_to_dict(_DETAIL_IMPORT_ERROR),
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
        "settings_summary": json_safe(settings_summary),
        "warnings": warnings,
        "errors": errors,
    }


def assert_package_reader_ready() -> None:
    """Wirft RuntimeError, wenn Package Reader nicht bereit ist."""
    health = get_package_reader_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"package reader is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "PACKAGE_READER_VERSION",
    "PACKAGE_READER_COMPONENT",
    "DEFAULT_READER_STATUS",
    "DEFAULT_TEXT_ENCODING",
    "DEFAULT_MAX_JSON_FILE_SIZE_BYTES",
    "MAX_JSON_FILE_SIZE_BYTES_HARD_LIMIT",
    "DEFAULT_READ_ALL_JSON_DOCUMENTS",
    "DEFAULT_INCLUDE_OPTIONAL_SUMMARY_FILES",
    "DEFAULT_FAIL_ON_JSON_ERROR",
    "DEFAULT_FAIL_ON_MISSING_REQUIRED",
    "JSON_SUFFIX",
    "CANONICAL_SOURCE_DEPTH",
    "LEGACY_SOURCE_DEPTH",
    "SOURCE_LAYOUT_CANONICAL",
    "SOURCE_LAYOUT_LEGACY",
    "SOURCE_LAYOUT_UNKNOWN",
    "VALID_READER_STATUSES",
    "READ_ERROR_CODES",
    "TAXONOMY_REQUIRED_READER_FILES",
    "PackageReaderOptions",
    "PackageReadMessage",
    "PackageDocument",
    "PackageReadResult",
    "utc_now_iso",
    "monotonic_ms_safe",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_int",
    "ensure_dict",
    "tuple_of_strings",
    "safe_path",
    "safe_path_str",
    "safe_resolve",
    "path_is_relative_to",
    "make_relative_path",
    "normalize_document_key",
    "normalize_documents",
    "get_attr_or_key",
    "deep_get",
    "first_non_empty",
    "normalize_reader_status",
    "normalize_candidate_id",
    "fallback_normalize_slug",
    "normalize_taxonomy_slug",
    "normalize_source_path_parts",
    "normalize_source_path_string",
    "infer_source_layout",
    "taxonomy_from_relative_path",
    "extract_classification_from_documents",
    "extract_family_slug_from_documents",
    "build_reader_taxonomy_metadata",
    "normalize_required_files",
    "normalize_optional_files",
    "normalize_ignored_directory_names",
    "normalize_ignored_file_suffixes",
    "document_key_to_path",
    "path_to_document_key",
    "is_ignored_file",
    "is_ignored_directory",
    "extract_label_from_documents",
    "extract_object_kind_from_documents",
    "coerce_reader_options",
    "make_scan_candidate",
    "iter_json_files",
    "collect_document_keys_to_read",
    "read_json_document",
    "read_package_root",
    "discovery_candidate_to_metadata",
    "read_discovery_candidate",
    "read_package_candidates",
    "read_package_path",
    "read_result_to_document_mapping",
    "read_results_to_scan_candidates",
    "build_read_response",
    "build_read_many_response",
    "get_package_reader_health",
    "assert_package_reader_ready",
)