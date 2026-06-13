# services/vectoplan-library/src/library/scanner/package_fingerprint.py
"""
Package Fingerprint für die VECTOPLAN Creative-Library-Schicht.

Diese Datei erzeugt stabile Inhaltsfingerprints für VPLIB-Pakete.

Zweck:

- Änderungen an JSON-Dokumenten erkennen
- Änderungen an relevanten Asset-Dateien erkennen
- später DB-Upserts vorbereiten
- `family_id` stabil halten
- `revision_hash` ändern, wenn sich Inhalt ändert

Wichtig:

- Diese Datei schreibt nichts.
- Diese Datei validiert keine Fachlogik.
- Diese Datei liest nur Dateien für Hashing.
- Der Hash ist kein Security-/Auth-Mechanismus.
- Der Hash dient als technischer Änderungsfingerprint.

Späterer DB-Flow:

    family_id existiert nicht
      -> insert

    family_id existiert
      -> revision_hash vergleichen

    revision_hash gleich
      -> keine Änderung

    revision_hash anders
      -> update oder neue Revision schreiben

Version 0.1.2:

- Fallback-`safe_int` unterstützt `maximum`.
- Optionen können aus Mapping, Dataclass oder Defaults gebaut werden.
- JSON-Dokumenthash wird kanonisch aus geladenen Dokumenten gebildet, wenn
  diese verfügbar sind.
- Asset-Hash bleibt dateibasiert.
- Revision-Hash ist stabil und vermeidet JSON-Formatierungsrauschen, sobald
  geladene Dokumente vorliegen.
- Health prüft Hashing und safe_int(maximum).
"""

from __future__ import annotations

import hashlib
import json
import os
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACKAGE_FINGERPRINT_VERSION: Final[str] = "0.1.2"
PACKAGE_FINGERPRINT_COMPONENT: Final[str] = "library-package-fingerprint"

DEFAULT_HASH_ALGORITHM: Final[str] = "sha256"
DEFAULT_READ_CHUNK_SIZE_BYTES: Final[int] = 1024 * 1024
DEFAULT_MAX_HASH_FILE_SIZE_BYTES: Final[int] = 256 * 1024 * 1024
MAX_HASH_FILE_SIZE_BYTES_HARD_LIMIT: Final[int] = 2 * 1024 * 1024 * 1024

DEFAULT_INCLUDE_JSON_DOCUMENTS: Final[bool] = True
DEFAULT_INCLUDE_ASSET_FILES: Final[bool] = True
DEFAULT_INCLUDE_FILE_METADATA: Final[bool] = False
DEFAULT_INCLUDE_PACKAGE_PATH: Final[bool] = False

FINGERPRINT_SCHEMA_VERSION: Final[str] = "vplib.library.fingerprint.v1"

DEFAULT_HASHABLE_SUFFIXES: Final[tuple[str, ...]] = (
    ".json",
    ".svg",
    ".webp",
    ".png",
    ".jpg",
    ".jpeg",
    ".glb",
    ".gltf",
    ".bin",
    ".mtl",
    ".obj",
    ".txt",
    ".md",
)

DEFAULT_ASSET_SUFFIXES: Final[tuple[str, ...]] = (
    ".svg",
    ".webp",
    ".png",
    ".jpg",
    ".jpeg",
    ".glb",
    ".gltf",
    ".bin",
    ".mtl",
    ".obj",
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

HASH_STATUS_VALUES: Final[tuple[str, ...]] = (
    "unknown",
    "ok",
    "partial",
    "empty",
    "error",
)


# ---------------------------------------------------------------------------
# Generic helpers used before optional imports
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """
    UTC-Zeit im ISO-Format.
    """

    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any] | None:
    """
    Serialisiert Exceptions JSON-kompatibel.
    """

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
    """
    Defensiver JSON-Safe-Konverter.
    """

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
    """
    Robuste String-Konvertierung.
    """

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
    """
    Robuste Bool-Konvertierung.
    """

    try:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
            return True

        if text in {"0", "false", "no", "n", "off", "disabled", "disable"}:
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
    """
    Robuste Integer-Konvertierung mit optionaler Unter- und Obergrenze.
    """

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
    """
    Wandelt einen Wert defensiv in Path um.
    """

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
    """
    Wandelt Pfade defensiv in Strings.
    """

    try:
        path = safe_path(value)

        if path is not None:
            return str(path)

        text = safe_str(value, default="")
        return text or None

    except Exception:
        return None


def safe_resolve(path: Path) -> Path:
    """
    Best-effort Path.resolve().
    """

    try:
        return path.resolve()
    except Exception:
        try:
            return path.absolute()
        except Exception:
            return path


def path_is_relative_to(path: Path, parent: Path) -> bool:
    """
    Kompatibler `is_relative_to`-Check.
    """

    try:
        path.relative_to(parent)
        return True
    except Exception:
        return False


def make_relative_path(path: Path, root: Path) -> str:
    """
    Berechnet einen relativen Pfad robust.
    """

    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def ensure_dict(value: Any) -> dict[str, Any]:
    """
    Normalisiert Mapping-artige Werte zu dict.
    """

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
    """
    Normalisiert Werte zu tuple[str, ...].
    """

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


def get_attr_or_key(value: Any, key: str, *, default: Any = None) -> Any:
    """
    Liest Mapping-Key oder Attribut.
    """

    try:
        if value is None:
            return default

        if isinstance(value, Mapping):
            return value.get(key, default)

        return getattr(value, key, default)

    except Exception:
        return default


def normalize_document_key(document_key: Any) -> str:
    """
    Normalisiert Dokumentkeys.
    """

    text = safe_str(document_key, default="")
    text = text.replace("\\", "/").strip("/")

    while "//" in text:
        text = text.replace("//", "/")

    return text


def normalize_documents(documents: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Normalisiert ein Dokumentmapping auf paketrelative Keys.
    """

    if not isinstance(documents, Mapping):
        return {}

    result: dict[str, Any] = {}

    for key, value in documents.items():
        normalized_key = normalize_document_key(key)

        if normalized_key:
            result[normalized_key] = value

    return result


# ---------------------------------------------------------------------------
# Optional imports
# ---------------------------------------------------------------------------

_SETTINGS_IMPORT_ERROR: BaseException | None = None
_READER_IMPORT_ERROR: BaseException | None = None

try:
    from config.library_settings import (
        DEFAULT_IGNORED_DIRECTORY_NAMES,
        DEFAULT_IGNORED_FILE_SUFFIXES,
        get_settings_summary,
    )
except Exception as import_exc:  # pragma: no cover - defensive fallback
    _SETTINGS_IMPORT_ERROR = import_exc

    DEFAULT_IGNORED_DIRECTORY_NAMES = DEFAULT_IGNORED_DIRECTORY_NAMES_FALLBACK
    DEFAULT_IGNORED_FILE_SUFFIXES = DEFAULT_IGNORED_FILE_SUFFIXES_FALLBACK

    def get_settings_summary(*, refresh: bool = False) -> dict[str, Any]:
        return {
            "ok": False,
            "fallback_active": True,
            "error": exception_to_dict(_SETTINGS_IMPORT_ERROR) if _SETTINGS_IMPORT_ERROR else None,
        }


try:
    from library.scanner.package_reader import (
        PackageReadResult,
        normalize_document_key as reader_normalize_document_key,
        normalize_documents as reader_normalize_documents,
    )

    normalize_document_key = reader_normalize_document_key
    normalize_documents = reader_normalize_documents

except Exception as import_exc:  # pragma: no cover - defensive fallback
    _READER_IMPORT_ERROR = import_exc
    PackageReadResult = Any  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Normalizers / hash helpers
# ---------------------------------------------------------------------------

def normalize_suffixes(value: Any, *, default: tuple[str, ...]) -> tuple[str, ...]:
    """
    Normalisiert Dateisuffixe.
    """

    suffixes = tuple_of_strings(value)

    if not suffixes:
        suffixes = default

    result: list[str] = []

    for suffix in suffixes:
        clean = safe_str(suffix, default="").lower()

        if clean and not clean.startswith("."):
            clean = f".{clean}"

        if clean and clean not in result:
            result.append(clean)

    return tuple(result)


def normalize_ignored_directory_names(value: Any) -> tuple[str, ...]:
    """
    Normalisiert ignorierte Verzeichnisnamen.
    """

    names = tuple_of_strings(value)

    if not names:
        names = DEFAULT_IGNORED_DIRECTORY_NAMES

    result: list[str] = []

    for name in names:
        clean = safe_str(name, default="")

        if clean and clean not in result:
            result.append(clean)

    return tuple(result)


def normalize_ignored_file_suffixes(value: Any) -> tuple[str, ...]:
    """
    Normalisiert ignorierte Dateisuffixe.
    """

    return normalize_suffixes(
        value,
        default=DEFAULT_IGNORED_FILE_SUFFIXES,
    )


def normalize_hash_algorithm(value: Any) -> str:
    """
    Normalisiert den Hashalgorithmus.

    Aktuell wird primär sha256 verwendet.
    """

    text = safe_str(value, default=DEFAULT_HASH_ALGORITHM).lower().replace("-", "")

    allowed = {
        "sha256": "sha256",
        "sha512": "sha512",
        "blake2b": "blake2b",
    }

    return allowed.get(text, DEFAULT_HASH_ALGORITHM)


def new_hash(algorithm: str = DEFAULT_HASH_ALGORITHM) -> Any:
    """
    Erstellt ein Hashobjekt.
    """

    normalized = normalize_hash_algorithm(algorithm)

    if normalized == "sha512":
        return hashlib.sha512()

    if normalized == "blake2b":
        return hashlib.blake2b()

    return hashlib.sha256()


def stable_json_dumps(value: Any) -> str:
    """
    Erzeugt eine stabile JSON-Serialisierung.

    Wichtig für reproduzierbare Hashes aus bereits geladenen Dokumenten.
    """

    return json.dumps(
        json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def hash_bytes(data: bytes, *, algorithm: str = DEFAULT_HASH_ALGORITHM) -> str:
    """
    Hasht Bytes.
    """

    hasher = new_hash(algorithm)
    hasher.update(data)
    return hasher.hexdigest()


def hash_text(text: str, *, algorithm: str = DEFAULT_HASH_ALGORITHM) -> str:
    """
    Hasht Text als UTF-8.
    """

    return hash_bytes(text.encode("utf-8"), algorithm=algorithm)


def normalize_hash_status(value: Any) -> str:
    """
    Normalisiert Hash-Status.
    """

    text = safe_str(value, default="unknown").lower()

    if text in HASH_STATUS_VALUES:
        return text

    return "unknown"


def is_ignored_directory(path: Path, ignored_directory_names: Iterable[str]) -> bool:
    """
    Prüft ignorierte Verzeichnisse.
    """

    try:
        return path.name in set(ignored_directory_names)
    except Exception:
        return False


def is_ignored_file(path: Path, ignored_file_suffixes: Iterable[str]) -> bool:
    """
    Prüft ignorierte Dateisuffixe.
    """

    try:
        return path.suffix.lower() in set(ignored_file_suffixes)
    except Exception:
        return False


def should_hash_file(path: Path, *, options: "PackageFingerprintOptions") -> bool:
    """
    Entscheidet, ob eine Datei in den Fingerprint einfließt.
    """

    try:
        if not path.is_file():
            return False

        if is_ignored_file(path, options.ignored_file_suffixes):
            return False

        suffix = path.suffix.lower()

        if suffix not in set(options.hashable_suffixes):
            return False

        if suffix == ".json" and not options.include_json_documents:
            return False

        if suffix in set(options.asset_suffixes) and not options.include_asset_files:
            return False

        return True

    except Exception:
        return False


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PackageFingerprintOptions:
    """
    Konfiguration für Package-Fingerprints.
    """

    algorithm: str = DEFAULT_HASH_ALGORITHM
    include_json_documents: bool = DEFAULT_INCLUDE_JSON_DOCUMENTS
    include_asset_files: bool = DEFAULT_INCLUDE_ASSET_FILES
    include_file_metadata: bool = DEFAULT_INCLUDE_FILE_METADATA
    include_package_path: bool = DEFAULT_INCLUDE_PACKAGE_PATH
    read_chunk_size_bytes: int = DEFAULT_READ_CHUNK_SIZE_BYTES
    max_hash_file_size_bytes: int = DEFAULT_MAX_HASH_FILE_SIZE_BYTES
    hashable_suffixes: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_HASHABLE_SUFFIXES)
    )
    asset_suffixes: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_ASSET_SUFFIXES)
    )
    ignored_directory_names: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_IGNORED_DIRECTORY_NAMES)
    )
    ignored_file_suffixes: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_IGNORED_FILE_SUFFIXES)
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "algorithm", normalize_hash_algorithm(self.algorithm))
        object.__setattr__(
            self,
            "include_json_documents",
            safe_bool(self.include_json_documents, default=DEFAULT_INCLUDE_JSON_DOCUMENTS),
        )
        object.__setattr__(
            self,
            "include_asset_files",
            safe_bool(self.include_asset_files, default=DEFAULT_INCLUDE_ASSET_FILES),
        )
        object.__setattr__(
            self,
            "include_file_metadata",
            safe_bool(self.include_file_metadata, default=DEFAULT_INCLUDE_FILE_METADATA),
        )
        object.__setattr__(
            self,
            "include_package_path",
            safe_bool(self.include_package_path, default=DEFAULT_INCLUDE_PACKAGE_PATH),
        )
        object.__setattr__(
            self,
            "read_chunk_size_bytes",
            safe_int(
                self.read_chunk_size_bytes,
                default=DEFAULT_READ_CHUNK_SIZE_BYTES,
                minimum=4096,
                maximum=64 * 1024 * 1024,
            ),
        )
        object.__setattr__(
            self,
            "max_hash_file_size_bytes",
            safe_int(
                self.max_hash_file_size_bytes,
                default=DEFAULT_MAX_HASH_FILE_SIZE_BYTES,
                minimum=1024,
                maximum=MAX_HASH_FILE_SIZE_BYTES_HARD_LIMIT,
            ),
        )
        object.__setattr__(
            self,
            "hashable_suffixes",
            normalize_suffixes(
                self.hashable_suffixes,
                default=DEFAULT_HASHABLE_SUFFIXES,
            ),
        )
        object.__setattr__(
            self,
            "asset_suffixes",
            normalize_suffixes(
                self.asset_suffixes,
                default=DEFAULT_ASSET_SUFFIXES,
            ),
        )
        object.__setattr__(
            self,
            "ignored_directory_names",
            normalize_ignored_directory_names(self.ignored_directory_names),
        )
        object.__setattr__(
            self,
            "ignored_file_suffixes",
            normalize_ignored_file_suffixes(self.ignored_file_suffixes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "include_json_documents": self.include_json_documents,
            "include_asset_files": self.include_asset_files,
            "include_file_metadata": self.include_file_metadata,
            "include_package_path": self.include_package_path,
            "read_chunk_size_bytes": self.read_chunk_size_bytes,
            "max_hash_file_size_bytes": self.max_hash_file_size_bytes,
            "hashable_suffixes": list(self.hashable_suffixes),
            "asset_suffixes": list(self.asset_suffixes),
            "ignored_directory_names": list(self.ignored_directory_names),
            "ignored_file_suffixes": list(self.ignored_file_suffixes),
        }


def coerce_fingerprint_options(
    value: PackageFingerprintOptions | Mapping[str, Any] | None = None,
) -> PackageFingerprintOptions:
    """
    Normalisiert optionale Fingerprint-Options.
    """

    if isinstance(value, PackageFingerprintOptions):
        return value

    if value is None:
        return PackageFingerprintOptions()

    try:
        data = ensure_dict(value)

        if not data:
            return PackageFingerprintOptions()

        allowed = {
            "algorithm",
            "include_json_documents",
            "include_asset_files",
            "include_file_metadata",
            "include_package_path",
            "read_chunk_size_bytes",
            "max_hash_file_size_bytes",
            "hashable_suffixes",
            "asset_suffixes",
            "ignored_directory_names",
            "ignored_file_suffixes",
        }

        return PackageFingerprintOptions(
            **{key: item for key, item in data.items() if key in allowed}
        )

    except Exception:
        return PackageFingerprintOptions()


# ---------------------------------------------------------------------------
# Fingerprint models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FingerprintedFile:
    """
    Eine Datei, die in den Package-Fingerprint eingeflossen ist.
    """

    key: str
    path: str
    size_bytes: int
    sha256: str | None = None
    digest: str | None = None
    algorithm: str = DEFAULT_HASH_ALGORITHM
    suffix: str | None = None
    group: str | None = None
    included: bool = True
    error: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", normalize_document_key(self.key))
        object.__setattr__(self, "path", safe_path_str(self.path) or "")
        object.__setattr__(self, "size_bytes", safe_int(self.size_bytes, default=0, minimum=0))
        object.__setattr__(self, "algorithm", normalize_hash_algorithm(self.algorithm))
        object.__setattr__(self, "suffix", safe_str(self.suffix, default="") or None)
        object.__setattr__(self, "group", safe_str(self.group, default="") or None)
        object.__setattr__(self, "included", safe_bool(self.included, default=True))
        object.__setattr__(self, "error", ensure_dict(self.error) if self.error else None)

        if self.digest is None and self.sha256 is not None:
            object.__setattr__(self, "digest", self.sha256)

        if self.sha256 is None and self.algorithm == "sha256" and self.digest is not None:
            object.__setattr__(self, "sha256", self.digest)

    @property
    def filename(self) -> str:
        try:
            return self.key.split("/")[-1]
        except Exception:
            return self.key

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "path": self.path,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "digest": self.digest,
            "algorithm": self.algorithm,
            "suffix": self.suffix,
            "group": self.group,
            "included": self.included,
            "error": json_safe(self.error),
        }


@dataclass(frozen=True)
class PackageFingerprintResult:
    """
    Ergebnis eines Package-Fingerprints.
    """

    ok: bool
    status: str
    revision_hash: str | None
    algorithm: str
    package_root: str | None = None
    source_root: str | None = None
    relative_package_root: str | None = None
    schema_version: str = FINGERPRINT_SCHEMA_VERSION
    generated_at: str = field(default_factory=utc_now_iso)

    file_count: int = 0
    included_file_count: int = 0
    skipped_file_count: int = 0
    error_count: int = 0
    total_size_bytes: int = 0

    files: tuple[FingerprintedFile, ...] = field(default_factory=tuple)
    document_hash: str | None = None
    asset_hash: str | None = None
    metadata_hash: str | None = None

    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    options: PackageFingerprintOptions = field(default_factory=PackageFingerprintOptions)
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = PACKAGE_FINGERPRINT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.options, PackageFingerprintOptions):
            object.__setattr__(self, "options", coerce_fingerprint_options(self.options))

        files = tuple(self.files or ())
        warnings = tuple_of_strings(self.warnings)
        errors = tuple_of_strings(self.errors)

        status = normalize_hash_status(self.status)

        if status == "unknown":
            if errors:
                status = "error" if not self.revision_hash else "partial"
            elif self.revision_hash:
                status = "ok"
            elif not files:
                status = "empty"
            else:
                status = "partial"

        effective_ok = bool(self.ok and status in {"ok", "partial", "empty"})

        object.__setattr__(self, "ok", effective_ok)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "revision_hash", safe_str(self.revision_hash, default="") or None)
        object.__setattr__(self, "algorithm", normalize_hash_algorithm(self.algorithm))
        object.__setattr__(self, "package_root", safe_path_str(self.package_root))
        object.__setattr__(self, "source_root", safe_path_str(self.source_root))
        object.__setattr__(self, "relative_package_root", safe_path_str(self.relative_package_root))
        object.__setattr__(self, "file_count", safe_int(self.file_count or len(files), default=len(files), minimum=0))
        object.__setattr__(
            self,
            "included_file_count",
            safe_int(
                self.included_file_count or sum(1 for file in files if file.included),
                default=0,
                minimum=0,
            ),
        )
        object.__setattr__(self, "skipped_file_count", safe_int(self.skipped_file_count, default=0, minimum=0))
        object.__setattr__(
            self,
            "error_count",
            safe_int(
                self.error_count or len(errors) or sum(1 for file in files if file.error),
                default=0,
                minimum=0,
            ),
        )
        object.__setattr__(
            self,
            "total_size_bytes",
            safe_int(
                self.total_size_bytes or sum(file.size_bytes for file in files),
                default=0,
                minimum=0,
            ),
        )
        object.__setattr__(self, "files", files)
        object.__setattr__(self, "document_hash", safe_str(self.document_hash, default="") or None)
        object.__setattr__(self, "asset_hash", safe_str(self.asset_hash, default="") or None)
        object.__setattr__(self, "metadata_hash", safe_str(self.metadata_hash, default="") or None)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "errors", errors)
        object.__setattr__(self, "metadata", ensure_dict(self.metadata))
        object.__setattr__(self, "version", safe_str(self.version, default=PACKAGE_FINGERPRINT_VERSION))

    def to_dict(
        self,
        *,
        include_files: bool = True,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "revision_hash": self.revision_hash,
            "algorithm": self.algorithm,
            "package_root": self.package_root,
            "source_root": self.source_root,
            "relative_package_root": self.relative_package_root,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "file_count": self.file_count,
            "included_file_count": self.included_file_count,
            "skipped_file_count": self.skipped_file_count,
            "error_count": self.error_count,
            "total_size_bytes": self.total_size_bytes,
            "document_hash": self.document_hash,
            "asset_hash": self.asset_hash,
            "metadata_hash": self.metadata_hash,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "options": self.options.to_dict(),
            "metadata": json_safe(self.metadata),
            "version": self.version,
        }

        if include_files:
            result["files"] = [
                file.to_dict()
                for file in self.files
            ]

        return result

    @classmethod
    def error(
        cls,
        exc: BaseException,
        *,
        package_root: Any = None,
        source_root: Any = None,
        relative_package_root: Any = None,
        options: PackageFingerprintOptions | Mapping[str, Any] | None = None,
        include_traceback: bool = False,
    ) -> "PackageFingerprintResult":
        error_data = exception_to_dict(exc, include_traceback=include_traceback)
        error_message = safe_str(error_data.get("message") if error_data else None, default="fingerprint failed")
        fingerprint_options = coerce_fingerprint_options(options)

        return cls(
            ok=False,
            status="error",
            revision_hash=None,
            algorithm=fingerprint_options.algorithm,
            package_root=safe_path_str(package_root),
            source_root=safe_path_str(source_root),
            relative_package_root=safe_path_str(relative_package_root),
            generated_at=utc_now_iso(),
            file_count=0,
            included_file_count=0,
            skipped_file_count=0,
            error_count=1,
            total_size_bytes=0,
            files=(),
            warnings=(),
            errors=(error_message,),
            options=fingerprint_options,
            metadata={"exception": error_data},
        )


# ---------------------------------------------------------------------------
# File collection and hashing
# ---------------------------------------------------------------------------

def path_to_package_key(package_root: Path, path: Path) -> str:
    """
    Wandelt einen Pfad in einen paketrelativen Key um.
    """

    resolved_root = safe_resolve(package_root)
    resolved_path = safe_resolve(path)

    if not path_is_relative_to(resolved_path, resolved_root):
        raise ValueError(f"path is outside package root: {resolved_path}")

    return normalize_document_key(make_relative_path(resolved_path, resolved_root))


def package_key_group(key: str) -> str:
    """
    Liefert grobe Gruppe eines Paketkeys.
    """

    normalized = normalize_document_key(key)

    if not normalized:
        return "unknown"

    if "/" not in normalized:
        return "root"

    return normalized.split("/", 1)[0]


def iter_hashable_files(
    package_root: Path,
    *,
    options: PackageFingerprintOptions,
) -> list[Path]:
    """
    Listet hashbare Dateien eines Package-Roots.
    """

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

                    if not should_hash_file(file_path, options=options):
                        continue

                    resolved_file = safe_resolve(file_path)

                    if not path_is_relative_to(resolved_file, resolved_root):
                        continue

                    result.append(resolved_file)

                except Exception:
                    continue

        return sorted(
            result,
            key=lambda path: path_to_package_key(resolved_root, path),
        )

    except Exception:
        return []


def hash_file(
    file_path: Path,
    *,
    package_root: Path,
    options: PackageFingerprintOptions,
) -> FingerprintedFile:
    """
    Hasht eine einzelne Datei robust.
    """

    resolved_root = safe_resolve(package_root)
    resolved_file = safe_resolve(file_path)

    try:
        key = path_to_package_key(resolved_root, resolved_file)

        if not resolved_file.is_file():
            raise FileNotFoundError(f"hash target is not a file: {resolved_file}")

        size_bytes = resolved_file.stat().st_size

        if size_bytes > options.max_hash_file_size_bytes:
            raise ValueError(
                f"file exceeds max hash size: {key} ({size_bytes} bytes)"
            )

        hasher = new_hash(options.algorithm)

        with resolved_file.open("rb") as file_handle:
            while True:
                chunk = file_handle.read(options.read_chunk_size_bytes)

                if not chunk:
                    break

                hasher.update(chunk)

        digest = hasher.hexdigest()
        sha256 = digest if options.algorithm == "sha256" else None

        return FingerprintedFile(
            key=key,
            path=str(resolved_file),
            size_bytes=size_bytes,
            sha256=sha256,
            digest=digest,
            algorithm=options.algorithm,
            suffix=resolved_file.suffix.lower(),
            group=package_key_group(key),
            included=True,
            error=None,
        )

    except Exception as exc:
        key = normalize_document_key(make_relative_path(resolved_file, resolved_root))

        return FingerprintedFile(
            key=key,
            path=str(resolved_file),
            size_bytes=0,
            sha256=None,
            digest=None,
            algorithm=options.algorithm,
            suffix=resolved_file.suffix.lower(),
            group=package_key_group(key),
            included=False,
            error=exception_to_dict(exc),
        )


def hash_loaded_documents(
    documents: Mapping[str, Any] | None,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
) -> str | None:
    """
    Erzeugt einen stabilen Hash aus bereits geladenen Dokumenten.

    Das ist nützlich, wenn PackageReader bereits JSON-Daten geladen hat.
    """

    normalized = normalize_documents(documents)

    if not normalized:
        return None

    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "documents": {
            key: normalized[key]
            for key in sorted(normalized.keys())
        },
    }

    return hash_text(
        stable_json_dumps(payload),
        algorithm=algorithm,
    )


def split_file_hashes(
    files: Iterable[FingerprintedFile],
    *,
    algorithm: str,
) -> tuple[str | None, str | None]:
    """
    Erzeugt getrennte Hashes für JSON-Dokumente und Asset-Dateien.
    """

    document_entries: list[dict[str, Any]] = []
    asset_entries: list[dict[str, Any]] = []

    for file in sorted(files, key=lambda item: item.key):
        if not file.included or file.error:
            continue

        entry = {
            "key": file.key,
            "digest": file.digest,
            "size_bytes": file.size_bytes,
        }

        if file.suffix == ".json":
            document_entries.append(entry)
        else:
            asset_entries.append(entry)

    document_hash = None
    asset_hash = None

    if document_entries:
        document_hash = hash_text(
            stable_json_dumps(document_entries),
            algorithm=algorithm,
        )

    if asset_entries:
        asset_hash = hash_text(
            stable_json_dumps(asset_entries),
            algorithm=algorithm,
        )

    return document_hash, asset_hash


def build_revision_payload(
    *,
    files: Iterable[FingerprintedFile],
    options: PackageFingerprintOptions,
    package_root: Path | None = None,
    source_root: Path | None = None,
    relative_package_root: str | None = None,
    document_hash: str | None = None,
    asset_hash: str | None = None,
    metadata_hash: str | None = None,
) -> dict[str, Any]:
    """
    Baut die kanonische Payload für den finalen revision_hash.

    Wenn `document_hash` vorhanden ist, werden JSON-Dateibyte-Digests nicht noch
    einmal in `files` aufgenommen. Dadurch ändert sich der Revision-Hash nicht
    nur wegen JSON-Formatierung, Whitespace oder Key-Reihenfolge, solange die
    geladenen Dokumentdaten semantisch gleich bleiben.
    """

    file_payload: list[dict[str, Any]] = []
    canonical_document_hash_available = bool(document_hash)

    for file in sorted(files, key=lambda item: item.key):
        if not file.included or file.error:
            continue

        if canonical_document_hash_available and file.suffix == ".json":
            continue

        entry: dict[str, Any] = {
            "key": file.key,
            "digest": file.digest,
            "algorithm": file.algorithm,
            "size_bytes": file.size_bytes,
        }

        if options.include_file_metadata:
            entry["suffix"] = file.suffix
            entry["group"] = file.group

        file_payload.append(entry)

    payload: dict[str, Any] = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "algorithm": options.algorithm,
        "files": file_payload,
        "document_hash": document_hash,
        "asset_hash": asset_hash,
        "metadata_hash": metadata_hash,
    }

    if options.include_package_path:
        payload["package_root"] = str(package_root) if package_root is not None else None
        payload["source_root"] = str(source_root) if source_root is not None else None
        payload["relative_package_root"] = relative_package_root

    return payload


# ---------------------------------------------------------------------------
# Main fingerprint functions
# ---------------------------------------------------------------------------

def fingerprint_package_root(
    package_root: Path,
    *,
    source_root: Path | None = None,
    relative_package_root: str | None = None,
    documents: Mapping[str, Any] | None = None,
    options: PackageFingerprintOptions | Mapping[str, Any] | None = None,
) -> PackageFingerprintResult:
    """
    Erzeugt einen Fingerprint für ein Package-Verzeichnis.

    Wenn `documents` übergeben werden, wird zusätzlich ein stabiler
    Dokumenthash aus den bereits geladenen JSON-Daten erzeugt.
    """

    fingerprint_options = coerce_fingerprint_options(options)

    try:
        resolved_package_root = safe_resolve(package_root)

        if not resolved_package_root.exists():
            raise FileNotFoundError(f"package root does not exist: {resolved_package_root}")

        if not resolved_package_root.is_dir():
            raise NotADirectoryError(f"package root is not a directory: {resolved_package_root}")

        resolved_source_root = safe_resolve(source_root) if source_root is not None else None

        if relative_package_root is None and resolved_source_root is not None:
            relative_package_root = make_relative_path(resolved_package_root, resolved_source_root)

        normalized_documents = normalize_documents(documents)

        file_paths = iter_hashable_files(
            resolved_package_root,
            options=fingerprint_options,
        )

        files: list[FingerprintedFile] = []

        for file_path in file_paths:
            files.append(
                hash_file(
                    file_path,
                    package_root=resolved_package_root,
                    options=fingerprint_options,
                )
            )

        file_errors = [
            file
            for file in files
            if file.error
        ]

        document_hash_from_files, asset_hash = split_file_hashes(
            files,
            algorithm=fingerprint_options.algorithm,
        )

        loaded_document_hash = hash_loaded_documents(
            normalized_documents,
            algorithm=fingerprint_options.algorithm,
        )

        # Wenn geladene Dokumente vorhanden sind, sind sie kanonischer als rohe
        # Dateibytes, weil JSON-Key-Reihenfolge und Formatierung normalisiert
        # werden. Asset-Hash bleibt dateibasiert.
        document_hash = loaded_document_hash or document_hash_from_files

        metadata_payload = {
            "schema_version": FINGERPRINT_SCHEMA_VERSION,
            "file_count": len(files),
            "included_file_count": sum(1 for file in files if file.included and not file.error),
            "document_keys": sorted(normalized_documents.keys()),
            "canonical_documents_used": bool(loaded_document_hash),
        }
        metadata_hash = hash_text(
            stable_json_dumps(metadata_payload),
            algorithm=fingerprint_options.algorithm,
        )

        revision_payload = build_revision_payload(
            files=files,
            options=fingerprint_options,
            package_root=resolved_package_root,
            source_root=resolved_source_root,
            relative_package_root=relative_package_root,
            document_hash=document_hash,
            asset_hash=asset_hash,
            metadata_hash=metadata_hash,
        )

        revision_hash = hash_text(
            stable_json_dumps(revision_payload),
            algorithm=fingerprint_options.algorithm,
        )

        warnings: list[str] = []
        errors: list[str] = []

        if file_errors:
            warnings.append(f"{len(file_errors)} files could not be fingerprinted")

        status = "ok"

        if file_errors:
            status = "partial"

        if not files and not normalized_documents:
            status = "empty"

        return PackageFingerprintResult(
            ok=status in {"ok", "partial", "empty"},
            status=status,
            revision_hash=revision_hash,
            algorithm=fingerprint_options.algorithm,
            package_root=str(resolved_package_root),
            source_root=str(resolved_source_root) if resolved_source_root is not None else None,
            relative_package_root=relative_package_root,
            schema_version=FINGERPRINT_SCHEMA_VERSION,
            generated_at=utc_now_iso(),
            file_count=len(files),
            included_file_count=sum(1 for file in files if file.included and not file.error),
            skipped_file_count=0,
            error_count=len(file_errors),
            total_size_bytes=sum(file.size_bytes for file in files),
            files=tuple(files),
            document_hash=document_hash,
            asset_hash=asset_hash,
            metadata_hash=metadata_hash,
            warnings=tuple(warnings),
            errors=tuple(errors),
            options=fingerprint_options,
            metadata={
                "revision_payload": revision_payload,
                "canonical_documents_used": bool(loaded_document_hash),
                "settings_import_error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
                "reader_import_error": exception_to_dict(_READER_IMPORT_ERROR),
            },
        )

    except Exception as exc:
        return PackageFingerprintResult.error(
            exc,
            package_root=package_root,
            source_root=source_root,
            relative_package_root=relative_package_root,
            options=fingerprint_options,
        )


def fingerprint_read_result(
    read_result: Any,
    *,
    options: PackageFingerprintOptions | Mapping[str, Any] | None = None,
) -> PackageFingerprintResult:
    """
    Erzeugt einen Fingerprint aus einem PackageReadResult oder kompatiblen Mapping.
    """

    fingerprint_options = coerce_fingerprint_options(options)

    try:
        if isinstance(read_result, Mapping):
            package_root = safe_path(read_result.get("package_root"))
            source_root = safe_path(read_result.get("source_root"))
            relative_package_root = safe_str(read_result.get("relative_package_root"), default="") or None
            documents = normalize_documents(read_result.get("documents"))
        else:
            package_root = safe_path(getattr(read_result, "package_root", None))
            source_root = safe_path(getattr(read_result, "source_root", None))
            relative_package_root = safe_str(getattr(read_result, "relative_package_root", None), default="") or None
            documents = normalize_documents(getattr(read_result, "documents", None))

        if package_root is None:
            raise ValueError("read_result package_root is missing")

        return fingerprint_package_root(
            package_root,
            source_root=source_root,
            relative_package_root=relative_package_root,
            documents=documents,
            options=fingerprint_options,
        )

    except Exception as exc:
        if isinstance(read_result, Mapping):
            package_root_value = read_result.get("package_root")
            source_root_value = read_result.get("source_root")
            relative_value = read_result.get("relative_package_root")
        else:
            package_root_value = getattr(read_result, "package_root", None) if read_result is not None else None
            source_root_value = getattr(read_result, "source_root", None) if read_result is not None else None
            relative_value = getattr(read_result, "relative_package_root", None) if read_result is not None else None

        return PackageFingerprintResult.error(
            exc,
            package_root=package_root_value,
            source_root=source_root_value,
            relative_package_root=relative_value,
            options=fingerprint_options,
        )


def fingerprint_documents_only(
    documents: Mapping[str, Any] | None,
    *,
    algorithm: str = DEFAULT_HASH_ALGORITHM,
) -> str | None:
    """
    Convenience-Funktion für reine Dokumenthashes.
    """

    return hash_loaded_documents(
        documents,
        algorithm=algorithm,
    )


def attach_fingerprint_to_read_result_dict(
    read_result: Any,
    fingerprint: PackageFingerprintResult,
) -> dict[str, Any]:
    """
    Baut ein Dict aus ReadResult plus Fingerprint.

    Diese Funktion verändert keine Objekte.
    """

    try:
        if hasattr(read_result, "to_dict") and callable(read_result.to_dict):
            try:
                data = read_result.to_dict(
                    include_documents=True,
                    include_document_entries=True,
                    include_document_data=False,
                )
            except TypeError:
                data = read_result.to_dict()
        elif isinstance(read_result, Mapping):
            data = dict(read_result)
        else:
            data = {"read_result": str(read_result)}

        data["fingerprint"] = fingerprint.to_dict(include_files=True)
        data["revision_hash"] = fingerprint.revision_hash

        return data

    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": exception_to_dict(exc),
            "fingerprint": fingerprint.to_dict(include_files=False),
        }


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def get_package_fingerprint_health(
    *,
    refresh_settings: bool = False,
) -> dict[str, Any]:
    """
    Health-Status der Fingerprint-Schicht.

    Führt kein Package-Hashing aus.
    """

    warnings: list[str] = []
    errors: list[str] = []

    if _SETTINGS_IMPORT_ERROR is not None:
        warnings.append("config.library_settings import failed; fallback fingerprint settings are active")

    if _READER_IMPORT_ERROR is not None:
        warnings.append("package_reader import failed; direct path fingerprinting still works")

    try:
        options = PackageFingerprintOptions()
        options_dict = options.to_dict()
    except Exception as exc:
        options_dict = {}
        errors.append(f"could not build fingerprint options: {exc}")

    try:
        test_hash = hash_text("vectoplan-library-fingerprint-health")
    except Exception as exc:
        test_hash = None
        errors.append(f"hash self-test failed: {exc}")

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
        "component": PACKAGE_FINGERPRINT_COMPONENT,
        "version": PACKAGE_FINGERPRINT_VERSION,
        "generated_at": utc_now_iso(),
        "algorithm": DEFAULT_HASH_ALGORITHM,
        "hash_self_test": {
            "ok": test_hash is not None,
            "digest": test_hash,
        },
        "options": options_dict,
        "imports": {
            "settings": {
                "ok": _SETTINGS_IMPORT_ERROR is None,
                "error": exception_to_dict(_SETTINGS_IMPORT_ERROR),
            },
            "reader": {
                "ok": _READER_IMPORT_ERROR is None,
                "error": exception_to_dict(_READER_IMPORT_ERROR),
            },
        },
        "settings_summary": json_safe(settings_summary),
        "warnings": warnings,
        "errors": errors,
    }


def assert_package_fingerprint_ready() -> None:
    """
    Wirft RuntimeError, wenn Fingerprint-Schicht nicht bereit ist.
    """

    health = get_package_fingerprint_health()

    if health.get("healthy"):
        return

    raise RuntimeError(
        f"package fingerprint is not ready: errors={health.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "PACKAGE_FINGERPRINT_VERSION",
    "PACKAGE_FINGERPRINT_COMPONENT",
    "DEFAULT_HASH_ALGORITHM",
    "DEFAULT_READ_CHUNK_SIZE_BYTES",
    "DEFAULT_MAX_HASH_FILE_SIZE_BYTES",
    "MAX_HASH_FILE_SIZE_BYTES_HARD_LIMIT",
    "DEFAULT_INCLUDE_JSON_DOCUMENTS",
    "DEFAULT_INCLUDE_ASSET_FILES",
    "DEFAULT_INCLUDE_FILE_METADATA",
    "DEFAULT_INCLUDE_PACKAGE_PATH",
    "FINGERPRINT_SCHEMA_VERSION",
    "DEFAULT_HASHABLE_SUFFIXES",
    "DEFAULT_ASSET_SUFFIXES",
    "HASH_STATUS_VALUES",
    "PackageFingerprintOptions",
    "FingerprintedFile",
    "PackageFingerprintResult",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_bool",
    "safe_int",
    "safe_path",
    "safe_path_str",
    "safe_resolve",
    "path_is_relative_to",
    "make_relative_path",
    "ensure_dict",
    "tuple_of_strings",
    "get_attr_or_key",
    "normalize_document_key",
    "normalize_documents",
    "normalize_suffixes",
    "normalize_ignored_directory_names",
    "normalize_ignored_file_suffixes",
    "normalize_hash_algorithm",
    "new_hash",
    "stable_json_dumps",
    "hash_bytes",
    "hash_text",
    "normalize_hash_status",
    "is_ignored_directory",
    "is_ignored_file",
    "should_hash_file",
    "coerce_fingerprint_options",
    "path_to_package_key",
    "package_key_group",
    "iter_hashable_files",
    "hash_file",
    "hash_loaded_documents",
    "build_revision_payload",
    "split_file_hashes",
    "fingerprint_package_root",
    "fingerprint_read_result",
    "fingerprint_documents_only",
    "attach_fingerprint_to_read_result_dict",
    "get_package_fingerprint_health",
    "assert_package_fingerprint_ready",
)