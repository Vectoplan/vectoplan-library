# services/vectoplan-library/src/vplib/creators/archive_creator.py
"""
Archive creator for the VPLIB package engine.

Diese Datei erstellt ein .vplib-Archiv aus einem bereits geschriebenen
Package-Verzeichnis.

Rolle dieser Datei:

    package_root
    -> scan package files
    -> validate archive entries
    -> create .vplib zip archive
    -> ArchiveCreationResult

Ein .vplib ist technisch ein ZIP-kompatibles Archiv mit stabilen,
package-relativen POSIX-Pfaden.

Diese Datei:
- liest Package-Dateien vom Dateisystem
- schreibt optional ein .vplib-Archiv
- nutzt sichere relative Archive-Namen
- verhindert Parent-Traversal im Archiv
- unterstützt dry-run
- unterstützt atomic archive creation
- unterstützt overwrite/fail/skip-Verhalten

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping


ARCHIVE_CREATOR_SCHEMA_VERSION: Final[str] = "vplib.archive_creator.v1"
PACKAGE_ARCHIVE_EXTENSION: Final[str] = ".vplib"
DEFAULT_COMPRESSION_LEVEL: Final[int] = 6
DEFAULT_TEMP_PREFIX: Final[str] = ".vplib-archive-"

DEFAULT_EXCLUDED_NAMES: Final[tuple[str, ...]] = (
    ".DS_Store",
    "Thumbs.db",
)

DEFAULT_EXCLUDED_SUFFIXES: Final[tuple[str, ...]] = (
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
)

DEFAULT_EXCLUDED_PREFIXES: Final[tuple[str, ...]] = (
    ".vplib-write-",
    ".vplib-archive-",
)


class ArchiveCreatorError(RuntimeError):
    """Wird ausgelöst, wenn ein .vplib-Archiv nicht erstellt werden kann."""


class ArchiveCreationStatus(str, Enum):
    """Status der Archive-Erstellung."""

    CREATED = "created"
    DRY_RUN = "dry_run"
    SKIPPED = "skipped"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


class ArchiveEntryKind(str, Enum):
    """Art eines Archiveintrags."""

    FILE = "file"
    DIRECTORY = "directory"

    @property
    def key(self) -> str:
        return str(self.value)


class ArchiveCompression(str, Enum):
    """Kompressionsmodus."""

    DEFLATED = "deflated"
    STORED = "stored"

    @property
    def key(self) -> str:
        return str(self.value)


class ArchiveWriteMode(str, Enum):
    """Verhalten bei bestehendem Archiv."""

    FAIL = "fail"
    SKIP = "skip"
    OVERWRITE = "overwrite"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ArchiveCreationOptions:
    """Optionen für die .vplib-Archive-Erstellung."""

    write_mode: str = ArchiveWriteMode.FAIL.value
    dry_run: bool = False
    atomic: bool = True
    compression: str = ArchiveCompression.DEFLATED.value
    compression_level: int = DEFAULT_COMPRESSION_LEVEL
    include_directories: bool = True
    include_empty_directories: bool = True
    include_hidden_files: bool = False
    include_archive_if_inside_package: bool = False
    require_manifest: bool = True
    require_modules: bool = True
    strict: bool = True

    def normalized(self) -> "ArchiveCreationOptions":
        return ArchiveCreationOptions(
            write_mode=parse_write_mode_value(self.write_mode),
            dry_run=bool(self.dry_run),
            atomic=bool(self.atomic),
            compression=parse_compression_value(self.compression),
            compression_level=normalize_compression_level(self.compression_level),
            include_directories=bool(self.include_directories),
            include_empty_directories=bool(self.include_empty_directories),
            include_hidden_files=bool(self.include_hidden_files),
            include_archive_if_inside_package=bool(self.include_archive_if_inside_package),
            require_manifest=bool(self.require_manifest),
            require_modules=bool(self.require_modules),
            strict=bool(self.strict),
        )

    @property
    def zip_compression(self) -> int:
        normalized = self.normalized()

        if normalized.compression == ArchiveCompression.STORED.value:
            return zipfile.ZIP_STORED

        return zipfile.ZIP_DEFLATED

    @property
    def may_overwrite(self) -> bool:
        return self.normalized().write_mode == ArchiveWriteMode.OVERWRITE.value

    @property
    def may_skip(self) -> bool:
        return self.normalized().write_mode == ArchiveWriteMode.SKIP.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "write_mode": normalized.write_mode,
            "dry_run": normalized.dry_run,
            "atomic": normalized.atomic,
            "compression": normalized.compression,
            "compression_level": normalized.compression_level,
            "include_directories": normalized.include_directories,
            "include_empty_directories": normalized.include_empty_directories,
            "include_hidden_files": normalized.include_hidden_files,
            "include_archive_if_inside_package": normalized.include_archive_if_inside_package,
            "require_manifest": normalized.require_manifest,
            "require_modules": normalized.require_modules,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """Ein geplanter Archiveintrag."""

    relative_path: str
    absolute_path: Path
    entry_kind: str = ArchiveEntryKind.FILE.value
    size_bytes: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ArchiveEntry":
        relative_path = normalize_archive_relative_path(self.relative_path)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        entry_kind = parse_entry_kind_value(self.entry_kind)
        size_bytes = normalize_non_negative_int(self.size_bytes, "size_bytes")
        metadata = normalize_metadata(self.metadata)

        if entry_kind == ArchiveEntryKind.DIRECTORY.value and not relative_path.endswith("/"):
            relative_path = f"{relative_path}/"

        if entry_kind == ArchiveEntryKind.FILE.value and relative_path.endswith("/"):
            raise ArchiveCreatorError(f"File archive entry must not end with '/': {relative_path!r}.")

        return ArchiveEntry(
            relative_path=relative_path,
            absolute_path=absolute_path,
            entry_kind=entry_kind,
            size_bytes=size_bytes,
            metadata=metadata,
        )

    @property
    def is_file(self) -> bool:
        return self.normalized().entry_kind == ArchiveEntryKind.FILE.value

    @property
    def is_directory(self) -> bool:
        return self.normalized().entry_kind == ArchiveEntryKind.DIRECTORY.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "entry_kind": normalized.entry_kind,
            "size_bytes": normalized.size_bytes,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ArchiveCreationResult:
    """Ergebnis der .vplib-Archive-Erstellung."""

    package_root: Path
    archive_path: Path
    entries: tuple[ArchiveEntry, ...] = field(default_factory=tuple)
    status: str = ArchiveCreationStatus.CREATED.value
    bytes_written: int = 0
    existed_before: bool = False
    dry_run: bool = False
    error: str | None = None
    schema_version: str = ARCHIVE_CREATOR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ArchiveCreationResult":
        package_root = normalize_absolute_path(self.package_root, "package_root")
        archive_path = normalize_archive_path(self.archive_path)
        entries = tuple(entry.normalized() for entry in self.entries or ())
        status = parse_creation_status_value(self.status)
        bytes_written = normalize_non_negative_int(self.bytes_written, "bytes_written")
        error = clean_optional_string(self.error)
        metadata = normalize_metadata(self.metadata)

        if error:
            status = ArchiveCreationStatus.FAILED.value

        return ArchiveCreationResult(
            package_root=package_root,
            archive_path=archive_path,
            entries=sort_archive_entries(dedupe_archive_entries(entries)),
            status=status,
            bytes_written=bytes_written,
            existed_before=bool(self.existed_before),
            dry_run=bool(self.dry_run),
            error=error,
            schema_version=self.schema_version or ARCHIVE_CREATOR_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def ok(self) -> bool:
        return self.normalized().status in {
            ArchiveCreationStatus.CREATED.value,
            ArchiveCreationStatus.DRY_RUN.value,
            ArchiveCreationStatus.SKIPPED.value,
        }

    @property
    def failed(self) -> bool:
        return self.normalized().status == ArchiveCreationStatus.FAILED.value

    @property
    def entry_count(self) -> int:
        return len(self.normalized().entries)

    @property
    def file_count(self) -> int:
        return sum(1 for entry in self.normalized().entries if entry.is_file)

    @property
    def directory_count(self) -> int:
        return sum(1 for entry in self.normalized().entries if entry.is_directory)

    @property
    def total_uncompressed_bytes(self) -> int:
        return sum(entry.size_bytes for entry in self.normalized().entries)

    def raise_for_error(self) -> None:
        normalized = self.normalized()

        if normalized.failed:
            raise ArchiveCreatorError(normalized.error or "Archive creation failed.")

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "status": normalized.status,
            "ok": normalized.ok,
            "failed": normalized.failed,
            "dry_run": normalized.dry_run,
            "package_root": str(normalized.package_root),
            "archive_path": str(normalized.archive_path),
            "bytes_written": normalized.bytes_written,
            "existed_before": normalized.existed_before,
            "entry_count": normalized.entry_count,
            "file_count": normalized.file_count,
            "directory_count": normalized.directory_count,
            "total_uncompressed_bytes": normalized.total_uncompressed_bytes,
            "error": normalized.error,
            "entries": [entry.to_dict() for entry in normalized.entries],
            "metadata": dict(normalized.metadata),
        }


def create_vplib_archive_from_package(
    *,
    package_root: str | Path,
    archive_path: str | Path | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
    options: ArchiveCreationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ArchiveCreationResult:
    """
    Erstellt ein .vplib-Archiv aus einem Package-Verzeichnis.

    Diese Signatur ist bewusst kompatibel mit package_creator.py.
    """
    try:
        base_options = normalize_options(options)
        effective_options = ArchiveCreationOptions(
            write_mode=ArchiveWriteMode.OVERWRITE.value if overwrite else base_options.write_mode,
            dry_run=bool(dry_run) or base_options.dry_run,
            atomic=base_options.atomic,
            compression=base_options.compression,
            compression_level=base_options.compression_level,
            include_directories=base_options.include_directories,
            include_empty_directories=base_options.include_empty_directories,
            include_hidden_files=base_options.include_hidden_files,
            include_archive_if_inside_package=base_options.include_archive_if_inside_package,
            require_manifest=base_options.require_manifest,
            require_modules=base_options.require_modules,
            strict=base_options.strict,
        ).normalized()

        root = normalize_package_root(package_root)
        target_archive = resolve_archive_path(
            package_root=root,
            archive_path=archive_path,
        )
        existed_before = target_archive.exists()

        validate_package_root_for_archive(root, options=effective_options)

        if existed_before and effective_options.write_mode == ArchiveWriteMode.SKIP.value:
            return ArchiveCreationResult(
                package_root=root,
                archive_path=target_archive,
                entries=tuple(),
                status=ArchiveCreationStatus.SKIPPED.value,
                bytes_written=target_archive.stat().st_size if target_archive.is_file() else 0,
                existed_before=True,
                dry_run=effective_options.dry_run,
                metadata={
                    "reason": "archive_exists",
                    **dict(metadata or {}),
                },
            ).normalized()

        if existed_before and effective_options.write_mode == ArchiveWriteMode.FAIL.value:
            raise ArchiveCreatorError(f"Archive already exists: {target_archive}")

        entries = scan_package_entries(
            package_root=root,
            archive_path=target_archive,
            options=effective_options,
        )

        valid, messages = validate_archive_entries(
            entries=entries,
            package_root=root,
            options=effective_options,
        )
        if not valid:
            raise ArchiveCreatorError(" ".join(messages))

        if effective_options.dry_run:
            return ArchiveCreationResult(
                package_root=root,
                archive_path=target_archive,
                entries=entries,
                status=ArchiveCreationStatus.DRY_RUN.value,
                bytes_written=0,
                existed_before=existed_before,
                dry_run=True,
                metadata={
                    "would_create_archive": True,
                    **dict(metadata or {}),
                },
            ).normalized()

        target_archive.parent.mkdir(parents=True, exist_ok=True)

        if effective_options.atomic:
            write_archive_atomic(
                package_root=root,
                archive_path=target_archive,
                entries=entries,
                options=effective_options,
            )
        else:
            write_archive_file(
                package_root=root,
                archive_path=target_archive,
                entries=entries,
                options=effective_options,
            )

        return ArchiveCreationResult(
            package_root=root,
            archive_path=target_archive,
            entries=entries,
            status=ArchiveCreationStatus.CREATED.value,
            bytes_written=target_archive.stat().st_size if target_archive.exists() else 0,
            existed_before=existed_before,
            dry_run=False,
            metadata={
                "compression": effective_options.compression,
                "compression_level": effective_options.compression_level,
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        if isinstance(exc, ArchiveCreatorError):
            error_message = str(exc)
        else:
            error_message = f"Could not create VPLIB archive: {exc}"

        safe_root = Path(package_root).expanduser() if package_root is not None else Path(".")
        safe_archive = Path(archive_path).expanduser() if archive_path is not None else derive_archive_path(safe_root)

        return ArchiveCreationResult(
            package_root=safe_root,
            archive_path=safe_archive,
            entries=tuple(),
            status=ArchiveCreationStatus.FAILED.value,
            bytes_written=0,
            existed_before=safe_archive.exists(),
            dry_run=bool(dry_run),
            error=error_message,
            metadata=dict(metadata or {}),
        ).normalized()


def scan_package_entries(
    *,
    package_root: Path,
    archive_path: Path | None,
    options: ArchiveCreationOptions,
) -> tuple[ArchiveEntry, ...]:
    """Scannt Package-Dateien und erzeugt ArchiveEntry-Werte."""
    root = normalize_package_root(package_root)
    normalized_options = options.normalized()
    entries: list[ArchiveEntry] = []

    for current_root, directory_names, file_names in os.walk(root):
        current_path = Path(current_root)

        directory_names[:] = sorted(
            directory_name
            for directory_name in directory_names
            if should_include_name(directory_name, options=normalized_options)
        )

        relative_directory = normalize_path_relative_to_root(current_path, root)

        if (
            normalized_options.include_directories
            and relative_directory != "."
            and (
                normalized_options.include_empty_directories
                or not directory_names and not file_names
            )
        ):
            entries.append(
                ArchiveEntry(
                    relative_path=f"{relative_directory}/",
                    absolute_path=current_path,
                    entry_kind=ArchiveEntryKind.DIRECTORY.value,
                    size_bytes=0,
                ).normalized()
            )

        for file_name in sorted(file_names):
            if not should_include_name(file_name, options=normalized_options):
                continue

            file_path = current_path / file_name

            if archive_path is not None and not normalized_options.include_archive_if_inside_package:
                try:
                    if file_path.resolve() == archive_path.resolve():
                        continue
                except Exception:
                    pass

            if not file_path.is_file():
                continue

            relative_file_path = normalize_path_relative_to_root(file_path, root)

            entries.append(
                ArchiveEntry(
                    relative_path=relative_file_path,
                    absolute_path=file_path,
                    entry_kind=ArchiveEntryKind.FILE.value,
                    size_bytes=file_path.stat().st_size,
                ).normalized()
            )

    return sort_archive_entries(dedupe_archive_entries(entries))


def write_archive_file(
    *,
    package_root: Path,
    archive_path: Path,
    entries: Iterable[ArchiveEntry],
    options: ArchiveCreationOptions,
) -> None:
    """Schreibt ZIP-kompatibles .vplib-Archiv."""
    root = normalize_package_root(package_root)
    target = normalize_archive_path(archive_path)
    normalized_options = options.normalized()
    normalized_entries = tuple(entry.normalized() for entry in entries or ())

    compression = normalized_options.zip_compression
    compresslevel = (
        None
        if compression == zipfile.ZIP_STORED
        else normalized_options.compression_level
    )

    with zipfile.ZipFile(
        target,
        mode="w",
        compression=compression,
        compresslevel=compresslevel,
    ) as archive:
        for entry in normalized_entries:
            if entry.is_directory:
                archive.writestr(entry.relative_path, b"")
                continue

            if not entry.absolute_path.is_file():
                raise ArchiveCreatorError(f"Archive entry source is not a file: {entry.absolute_path}")

            if not is_path_inside_root(entry.absolute_path, root):
                raise ArchiveCreatorError(f"Archive entry escapes package_root: {entry.absolute_path}")

            archive.write(
                entry.absolute_path,
                arcname=entry.relative_path,
            )


def write_archive_atomic(
    *,
    package_root: Path,
    archive_path: Path,
    entries: Iterable[ArchiveEntry],
    options: ArchiveCreationOptions,
) -> None:
    """Schreibt Archiv atomar über temporären Pfad im Zielordner."""
    target = normalize_archive_path(archive_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(target.parent),
            prefix=DEFAULT_TEMP_PREFIX,
            suffix=PACKAGE_ARCHIVE_EXTENSION,
        ) as temp_file:
            temp_path = Path(temp_file.name)

        write_archive_file(
            package_root=package_root,
            archive_path=temp_path,
            entries=entries,
            options=options,
        )

        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


def validate_package_root_for_archive(
    package_root: Path,
    *,
    options: ArchiveCreationOptions,
) -> None:
    """Validiert Package-Root vor Archive-Erstellung."""
    root = normalize_package_root(package_root)
    normalized_options = options.normalized()

    if normalized_options.require_manifest and not (root / "vplib.manifest.json").is_file():
        raise ArchiveCreatorError("Package root is missing required vplib.manifest.json.")

    if normalized_options.require_modules and not (root / "vplib.modules.json").is_file():
        raise ArchiveCreatorError("Package root is missing required vplib.modules.json.")


def validate_archive_entries(
    *,
    entries: Iterable[ArchiveEntry],
    package_root: Path,
    options: ArchiveCreationOptions,
) -> tuple[bool, tuple[str, ...]]:
    """Validiert ArchiveEntries."""
    messages: list[str] = []
    root = normalize_package_root(package_root)
    seen: set[str] = set()

    try:
        for entry in entries or ():
            normalized = entry.normalized()

            if normalized.relative_path in seen:
                messages.append(f"Duplicate archive entry {normalized.relative_path!r}.")
            seen.add(normalized.relative_path)

            if normalized.is_file:
                if not normalized.absolute_path.is_file():
                    messages.append(f"Archive file entry source is missing: {normalized.absolute_path}.")
                elif not is_path_inside_root(normalized.absolute_path, root):
                    messages.append(f"Archive file entry escapes package_root: {normalized.absolute_path}.")

            if normalized.is_directory:
                if not normalized.absolute_path.is_dir():
                    messages.append(f"Archive directory entry source is missing: {normalized.absolute_path}.")
                elif not is_path_inside_root(normalized.absolute_path, root):
                    messages.append(f"Archive directory entry escapes package_root: {normalized.absolute_path}.")

            try:
                normalize_archive_relative_path(normalized.relative_path)
            except Exception as exc:
                messages.append(str(exc))

        if options.normalized().require_manifest and "vplib.manifest.json" not in seen:
            messages.append("Archive entries are missing vplib.manifest.json.")

        if options.normalized().require_modules and "vplib.modules.json" not in seen:
            messages.append("Archive entries are missing vplib.modules.json.")

    except Exception as exc:
        messages.append(f"Could not validate archive entries: {exc}")

    return len(messages) == 0, tuple(messages)


def resolve_archive_path(
    *,
    package_root: Path,
    archive_path: str | Path | None,
) -> Path:
    """Ermittelt finalen Archivpfad."""
    if archive_path is None:
        return derive_archive_path(package_root)

    return normalize_archive_path(archive_path)


def derive_archive_path(package_root: str | Path) -> Path:
    """Leitet Archivpfad aus package_root ab."""
    root = Path(package_root).expanduser()
    archive_name = f"{root.name}{PACKAGE_ARCHIVE_EXTENSION}"

    if root.parent:
        return root.parent / archive_name

    return Path(archive_name)


def should_include_name(name: str, *, options: ArchiveCreationOptions) -> bool:
    """Prüft, ob Datei-/Ordnername ins Archiv aufgenommen werden soll."""
    normalized_options = options.normalized()
    cleaned = clean_required_string(name, "name")

    if cleaned in DEFAULT_EXCLUDED_NAMES:
        return False

    if any(cleaned.startswith(prefix) for prefix in DEFAULT_EXCLUDED_PREFIXES):
        return False

    if any(cleaned.endswith(suffix) for suffix in DEFAULT_EXCLUDED_SUFFIXES):
        return False

    if not normalized_options.include_hidden_files and cleaned.startswith("."):
        return False

    return True


def normalize_path_relative_to_root(path: Path, root: Path) -> str:
    """Erzeugt sicheren POSIX-Pfad relativ zum Package-Root."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except Exception as exc:
        raise ArchiveCreatorError(f"Path {path} is outside package_root {root}.") from exc

    if not relative.parts:
        return "."

    return normalize_archive_relative_path(PurePosixPath(*relative.parts).as_posix())


def normalize_archive_relative_path(value: Any) -> str:
    """Normalisiert sicheren Archivpfad."""
    raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

    is_directory = raw.endswith("/")
    raw = raw.strip("/")

    if not raw or raw == ".":
        if is_directory:
            raise ArchiveCreatorError("Archive directory entry must not be root.")
        return "."

    path = PurePosixPath(raw)

    if path.is_absolute():
        raise ArchiveCreatorError(f"Archive entry path must not be absolute: {value!r}")

    parts = tuple(part for part in path.parts if part not in {"", "."})

    if not parts:
        raise ArchiveCreatorError("Archive entry path is empty.")

    if any(part == ".." for part in parts):
        raise ArchiveCreatorError(f"Archive entry path must not contain parent traversal: {value!r}")

    normalized = PurePosixPath(*parts).as_posix()

    return f"{normalized}/" if is_directory else normalized


def normalize_package_root(value: Any) -> Path:
    """Normalisiert und validiert Package-Root."""
    root = normalize_absolute_path(value, "package_root")

    if not root.exists():
        raise ArchiveCreatorError(f"Package root does not exist: {root}")

    if not root.is_dir():
        raise ArchiveCreatorError(f"Package root is not a directory: {root}")

    return root


def normalize_archive_path(value: Any) -> Path:
    """Normalisiert Archivpfad und erzwingt .vplib-Endung."""
    path = normalize_absolute_path(value, "archive_path")

    if path.suffix != PACKAGE_ARCHIVE_EXTENSION:
        path = path.with_suffix(PACKAGE_ARCHIVE_EXTENSION)

    if path.name in {"", ".", ".."}:
        raise ArchiveCreatorError(f"Invalid archive file name: {value!r}")

    return path


def is_path_inside_root(path: Path, root: Path) -> bool:
    """Prüft, ob path innerhalb root liegt."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


def dedupe_archive_entries(entries: Iterable[ArchiveEntry]) -> tuple[ArchiveEntry, ...]:
    """Dedupliziert ArchiveEntries anhand relative_path."""
    by_path: dict[str, ArchiveEntry] = {}

    for entry in entries or ():
        normalized = entry.normalized()
        by_path[normalized.relative_path] = normalized

    return tuple(by_path.values())


def sort_archive_entries(entries: Iterable[ArchiveEntry]) -> tuple[ArchiveEntry, ...]:
    """Sortiert ArchiveEntries stabil."""
    return tuple(
        sorted(
            (entry.normalized() for entry in entries or ()),
            key=lambda entry: (
                0 if entry.is_directory else 1,
                entry.relative_path,
            ),
        )
    )


def normalize_options(
    options: ArchiveCreationOptions | Mapping[str, Any] | None,
) -> ArchiveCreationOptions:
    """Normalisiert ArchiveCreationOptions."""
    if options is None:
        return ArchiveCreationOptions().normalized()

    if isinstance(options, ArchiveCreationOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return ArchiveCreationOptions(
            write_mode=options.get("write_mode", ArchiveWriteMode.FAIL.value),
            dry_run=bool(options.get("dry_run", False)),
            atomic=bool(options.get("atomic", True)),
            compression=options.get("compression", ArchiveCompression.DEFLATED.value),
            compression_level=options.get("compression_level", DEFAULT_COMPRESSION_LEVEL),
            include_directories=bool(options.get("include_directories", True)),
            include_empty_directories=bool(options.get("include_empty_directories", True)),
            include_hidden_files=bool(options.get("include_hidden_files", False)),
            include_archive_if_inside_package=bool(options.get("include_archive_if_inside_package", False)),
            require_manifest=bool(options.get("require_manifest", True)),
            require_modules=bool(options.get("require_modules", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise ArchiveCreatorError("options must be ArchiveCreationOptions, mapping or None.")


@lru_cache(maxsize=128)
def parse_creation_status_value(value: Any) -> str:
    """Parst ArchiveCreationStatus."""
    try:
        if isinstance(value, ArchiveCreationStatus):
            return value.value

        raw = normalize_enum_key(value)
        return ArchiveCreationStatus(raw).value
    except Exception as exc:
        raise ArchiveCreatorError(f"Invalid archive creation status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_entry_kind_value(value: Any) -> str:
    """Parst ArchiveEntryKind."""
    try:
        if isinstance(value, ArchiveEntryKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "dir": ArchiveEntryKind.DIRECTORY.value,
            "directory": ArchiveEntryKind.DIRECTORY.value,
            "folder": ArchiveEntryKind.DIRECTORY.value,
            "file": ArchiveEntryKind.FILE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ArchiveEntryKind(raw).value
    except Exception as exc:
        raise ArchiveCreatorError(f"Invalid archive entry kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_compression_value(value: Any) -> str:
    """Parst ArchiveCompression."""
    try:
        if isinstance(value, ArchiveCompression):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "deflate": ArchiveCompression.DEFLATED.value,
            "deflated": ArchiveCompression.DEFLATED.value,
            "zip_deflated": ArchiveCompression.DEFLATED.value,
            "store": ArchiveCompression.STORED.value,
            "stored": ArchiveCompression.STORED.value,
            "none": ArchiveCompression.STORED.value,
            "zip_stored": ArchiveCompression.STORED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ArchiveCompression(raw).value
    except Exception as exc:
        raise ArchiveCreatorError(f"Invalid archive compression {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_write_mode_value(value: Any) -> str:
    """Parst ArchiveWriteMode."""
    try:
        if isinstance(value, ArchiveWriteMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "fail": ArchiveWriteMode.FAIL.value,
            "error": ArchiveWriteMode.FAIL.value,
            "strict": ArchiveWriteMode.FAIL.value,
            "skip": ArchiveWriteMode.SKIP.value,
            "ignore": ArchiveWriteMode.SKIP.value,
            "overwrite": ArchiveWriteMode.OVERWRITE.value,
            "replace": ArchiveWriteMode.OVERWRITE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ArchiveWriteMode(raw).value
    except Exception as exc:
        raise ArchiveCreatorError(f"Invalid archive write mode {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ArchiveCreatorError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ArchiveCreatorError:
        raise
    except Exception as exc:
        raise ArchiveCreatorError(f"Invalid enum value {value!r}.") from exc


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert lokalen Pfad."""
    try:
        if value is None:
            raise ArchiveCreatorError(f"{field_name} is required.")

        return Path(value).expanduser()
    except ArchiveCreatorError:
        raise
    except Exception as exc:
        raise ArchiveCreatorError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_compression_level(value: Any) -> int:
    """Normalisiert ZIP-Kompressionslevel."""
    try:
        if isinstance(value, bool):
            raise ArchiveCreatorError("compression_level must be an integer.")

        level = int(value)
        if level < 0 or level > 9:
            raise ArchiveCreatorError("compression_level must be in range 0..9.")

        return level
    except ArchiveCreatorError:
        raise
    except Exception as exc:
        raise ArchiveCreatorError("compression_level must be an integer.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise ArchiveCreatorError(f"{field_name} must be an integer.")

        number = int(value)

        if number < 0:
            raise ArchiveCreatorError(f"{field_name} must be >= 0.")

        return number
    except ArchiveCreatorError:
        raise
    except Exception as exc:
        raise ArchiveCreatorError(f"{field_name} must be a non-negative integer.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ArchiveCreatorError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ArchiveCreatorError(f"{field_name} is required.")

        return cleaned
    except ArchiveCreatorError:
        raise
    except Exception as exc:
        raise ArchiveCreatorError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_archive_creator_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_creation_status_value.cache_clear()
    parse_entry_kind_value.cache_clear()
    parse_compression_value.cache_clear()
    parse_write_mode_value.cache_clear()


__all__ = [
    "ARCHIVE_CREATOR_SCHEMA_VERSION",
    "DEFAULT_COMPRESSION_LEVEL",
    "DEFAULT_EXCLUDED_NAMES",
    "DEFAULT_EXCLUDED_PREFIXES",
    "DEFAULT_EXCLUDED_SUFFIXES",
    "DEFAULT_TEMP_PREFIX",
    "PACKAGE_ARCHIVE_EXTENSION",
    "ArchiveCompression",
    "ArchiveCreationOptions",
    "ArchiveCreationResult",
    "ArchiveCreationStatus",
    "ArchiveCreatorError",
    "ArchiveEntry",
    "ArchiveEntryKind",
    "ArchiveWriteMode",
    "clean_optional_string",
    "clean_required_string",
    "clear_archive_creator_caches",
    "create_vplib_archive_from_package",
    "dedupe_archive_entries",
    "derive_archive_path",
    "is_path_inside_root",
    "normalize_absolute_path",
    "normalize_archive_path",
    "normalize_archive_relative_path",
    "normalize_compression_level",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_int",
    "normalize_options",
    "normalize_package_root",
    "normalize_path_relative_to_root",
    "parse_compression_value",
    "parse_creation_status_value",
    "parse_entry_kind_value",
    "parse_write_mode_value",
    "resolve_archive_path",
    "scan_package_entries",
    "should_include_name",
    "sort_archive_entries",
    "validate_archive_entries",
    "validate_package_root_for_archive",
    "write_archive_atomic",
    "write_archive_file",
]