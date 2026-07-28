"""Portable import/export support for complete VECTOPLAN Creative Libraries.

The exchange format is a ZIP-compatible ``.vpcreative`` archive.  Every
archive contains one ``creative-library.manifest.json`` and zero or more files
below ``packages/``.  The manifest contains the size and SHA-256 digest of
every package file so an import can be validated fully before it writes.

This module deliberately has no Flask or database dependency.  The HTTP layer
is implemented in :mod:`routes.library_routes`; published database state can
be rebuilt through the existing explicit library sync route after import.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping


LIBRARY_ARCHIVE_COMPONENT: Final[str] = "library-archive-service"
LIBRARY_ARCHIVE_VERSION: Final[str] = "1.0.0"
LIBRARY_ARCHIVE_FORMAT: Final[str] = "vectoplan.creative-library"
LIBRARY_ARCHIVE_EXTENSION: Final[str] = ".vpcreative"
LIBRARY_ARCHIVE_MANIFEST: Final[str] = "creative-library.manifest.json"
LIBRARY_ARCHIVE_PACKAGES_PREFIX: Final[str] = "packages/"
DEFAULT_LIBRARY_ARCHIVE_NAME: Final[str] = "default.vpcreative"
DEFAULT_LIBRARY_ID: Final[str] = "default"

DEFAULT_MAX_ARCHIVE_BYTES: Final[int] = 1024 * 1024 * 1024
DEFAULT_MAX_UNCOMPRESSED_BYTES: Final[int] = 4 * 1024 * 1024 * 1024
DEFAULT_MAX_ENTRY_BYTES: Final[int] = 512 * 1024 * 1024
DEFAULT_MAX_ENTRIES: Final[int] = 100_000
DETERMINISTIC_ZIP_DATETIME: Final[tuple[int, int, int, int, int, int]] = (
    1980,
    1,
    1,
    0,
    0,
    0,
)

BLOCKED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".dylib",
        ".exe",
        ".jar",
        ".js",
        ".jsx",
        ".mjs",
        ".msi",
        ".ps1",
        ".py",
        ".pyc",
        ".pyo",
        ".scr",
        ".sh",
        ".so",
        ".ts",
        ".tsx",
    }
)


class LibraryArchiveError(RuntimeError):
    """Raised when a Creative Library archive is unsafe or invalid."""

    def __init__(self, message: str, *, code: str, http_status: int = 422) -> None:
        super().__init__(message)
        self.code = str(code)
        self.http_status = int(http_status)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_source_root() -> Path:
    """Resolve the canonical editable Creative Library source directory."""
    for key in (
        "VECTOPLAN_LIBRARY_SOURCE_ROOT",
        "VPLIB_CREATE_SOURCE_ROOT",
        "LIBRARY_SOURCE_ROOT",
    ):
        raw = str(os.getenv(key, "") or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "source").resolve()


def get_creative_library_root() -> Path:
    """Resolve the directory that stores named full-library archives."""
    for key in (
        "VECTOPLAN_LIBRARY_CREATIVE_ROOT",
        "VPLIB_LIBRARY_CATALOG_ROOT",
        "LIBRARY_CREATIVE_ROOT",
    ):
        raw = str(os.getenv(key, "") or "").strip()
        if raw:
            return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "creative_library").resolve()


def initialize_default_library(
    *,
    source_root: Path | str | None = None,
    creative_root: Path | str | None = None,
) -> dict[str, Any]:
    """Ensure an editable source root and one valid empty default library exist."""
    resolved_source = Path(source_root or get_source_root()).resolve()
    resolved_creative = Path(creative_root or get_creative_library_root()).resolve()
    resolved_source.mkdir(parents=True, exist_ok=True)
    resolved_creative.mkdir(parents=True, exist_ok=True)

    archives = sorted(resolved_creative.glob(f"*{LIBRARY_ARCHIVE_EXTENSION}"))
    if archives:
        return {
            "ok": True,
            "status": "existing",
            "component": LIBRARY_ARCHIVE_COMPONENT,
            "format": LIBRARY_ARCHIVE_FORMAT,
            "format_version": LIBRARY_ARCHIVE_VERSION,
            "source_root": str(resolved_source),
            "creative_root": str(resolved_creative),
            "default_archive": str(archives[0]),
            "archive_count": len(archives),
            "initialized": False,
        }

    filename, content, metadata = export_library_archive(
        source_root=resolved_source,
        library_id=DEFAULT_LIBRARY_ID,
        include_packages=False,
    )
    default_path = resolved_creative / DEFAULT_LIBRARY_ARCHIVE_NAME
    _write_bytes_atomic(default_path, content)
    return {
        "ok": True,
        "status": "initialized_empty",
        "component": LIBRARY_ARCHIVE_COMPONENT,
        "format": LIBRARY_ARCHIVE_FORMAT,
        "format_version": LIBRARY_ARCHIVE_VERSION,
        "source_root": str(resolved_source),
        "creative_root": str(resolved_creative),
        "default_archive": str(default_path),
        "filename": filename,
        "archive_count": 1,
        "initialized": True,
        "package_file_count": metadata["package_file_count"],
    }


def export_library_archive(
    *,
    source_root: Path | str | None = None,
    library_id: str = DEFAULT_LIBRARY_ID,
    include_packages: bool = True,
) -> tuple[str, bytes, dict[str, Any]]:
    """Build a complete checksummed ``.vpcreative`` archive in memory."""
    root = Path(source_root or get_source_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_library_id = _safe_identifier(library_id, fallback=DEFAULT_LIBRARY_ID)
    file_entries: list[tuple[str, bytes]] = []

    if include_packages:
        for file_path in _iter_source_files(root):
            relative = file_path.relative_to(root).as_posix()
            archive_path = f"{LIBRARY_ARCHIVE_PACKAGES_PREFIX}{relative}"
            _validate_archive_member(archive_path, require_packages_prefix=True)
            content = file_path.read_bytes()
            if len(content) > DEFAULT_MAX_ENTRY_BYTES:
                raise LibraryArchiveError(
                    f"Library file exceeds the per-entry limit: {relative}",
                    code="library_file_too_large",
                    http_status=413,
                )
            file_entries.append((archive_path, content))

    manifest_entries = [
        {
            "path": archive_path,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for archive_path, content in file_entries
    ]
    manifest = {
        "format": LIBRARY_ARCHIVE_FORMAT,
        "format_version": LIBRARY_ARCHIVE_VERSION,
        "library_id": safe_library_id,
        "created_at": utc_now_iso(),
        "package_root": LIBRARY_ARCHIVE_PACKAGES_PREFIX.rstrip("/"),
        "package_file_count": len(manifest_entries),
        "entries": manifest_entries,
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(
        archive_buffer,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        archive.comment = b"VECTOPLAN Creative Library"
        _write_zip_entry(archive, LIBRARY_ARCHIVE_MANIFEST, manifest_bytes)
        for archive_path, content in sorted(file_entries, key=lambda item: item[0]):
            _write_zip_entry(archive, archive_path, content)

    archive_bytes = archive_buffer.getvalue()
    validation = validate_library_archive(archive_bytes)
    filename = f"{safe_library_id}{LIBRARY_ARCHIVE_EXTENSION}"
    return filename, archive_bytes, {
        "ok": True,
        "status": "archive_ready",
        "component": LIBRARY_ARCHIVE_COMPONENT,
        "format": LIBRARY_ARCHIVE_FORMAT,
        "format_version": LIBRARY_ARCHIVE_VERSION,
        "library_id": safe_library_id,
        "filename": filename,
        "size_bytes": len(archive_bytes),
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "package_file_count": len(file_entries),
        "manifest": manifest,
        "validation": validation,
    }


def validate_library_archive(content: bytes | bytearray | memoryview) -> dict[str, Any]:
    """Validate structure, paths, limits, sizes and checksums without writing."""
    archive_bytes = bytes(content or b"")
    if not archive_bytes:
        raise LibraryArchiveError("Library archive is empty.", code="archive_empty")
    if len(archive_bytes) > DEFAULT_MAX_ARCHIVE_BYTES:
        raise LibraryArchiveError(
            "Library archive exceeds the configured size limit.",
            code="archive_too_large",
            http_status=413,
        )

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r")
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise LibraryArchiveError(
            "Library archive is not a valid ZIP-compatible archive.",
            code="archive_invalid",
        ) from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > DEFAULT_MAX_ENTRIES:
            raise LibraryArchiveError(
                "Library archive contains too many entries.",
                code="archive_entry_limit_exceeded",
                http_status=413,
            )

        seen: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            name = _validate_archive_member(info.filename)
            if name in seen:
                raise LibraryArchiveError(
                    f"Duplicate archive member: {name}",
                    code="archive_duplicate_member",
                )
            seen.add(name)
            if info.is_dir():
                continue
            if info.file_size > DEFAULT_MAX_ENTRY_BYTES:
                raise LibraryArchiveError(
                    f"Archive entry exceeds the per-entry limit: {name}",
                    code="archive_entry_too_large",
                    http_status=413,
                )
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > DEFAULT_MAX_UNCOMPRESSED_BYTES:
                raise LibraryArchiveError(
                    "Library archive exceeds the uncompressed size limit.",
                    code="archive_uncompressed_limit_exceeded",
                    http_status=413,
                )

        if LIBRARY_ARCHIVE_MANIFEST not in seen:
            raise LibraryArchiveError(
                "Creative Library manifest is missing.",
                code="archive_manifest_missing",
            )

        try:
            manifest = json.loads(archive.read(LIBRARY_ARCHIVE_MANIFEST).decode("utf-8"))
        except Exception as exc:
            raise LibraryArchiveError(
                "Creative Library manifest is not valid UTF-8 JSON.",
                code="archive_manifest_invalid",
            ) from exc

        if not isinstance(manifest, Mapping):
            raise LibraryArchiveError(
                "Creative Library manifest must be a JSON object.",
                code="archive_manifest_invalid",
            )
        if manifest.get("format") != LIBRARY_ARCHIVE_FORMAT:
            raise LibraryArchiveError(
                "Unsupported Creative Library archive format.",
                code="archive_format_unsupported",
            )
        if manifest.get("format_version") != LIBRARY_ARCHIVE_VERSION:
            raise LibraryArchiveError(
                "Unsupported Creative Library archive version.",
                code="archive_version_unsupported",
            )

        raw_entries = manifest.get("entries")
        if not isinstance(raw_entries, list):
            raise LibraryArchiveError(
                "Creative Library manifest entries must be an array.",
                code="archive_manifest_entries_invalid",
            )

        manifest_paths: set[str] = set()
        verified_entries: list[dict[str, Any]] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, Mapping):
                raise LibraryArchiveError(
                    "Creative Library manifest contains an invalid entry.",
                    code="archive_manifest_entry_invalid",
                )
            path = _validate_archive_member(
                raw_entry.get("path"),
                require_packages_prefix=True,
            )
            if path in manifest_paths:
                raise LibraryArchiveError(
                    f"Duplicate manifest path: {path}",
                    code="archive_manifest_duplicate_path",
                )
            if path not in seen:
                raise LibraryArchiveError(
                    f"Manifest entry is missing from the archive: {path}",
                    code="archive_manifest_file_missing",
                )
            data = archive.read(path)
            expected_size = _safe_int(raw_entry.get("size_bytes"), minimum=0)
            expected_sha256 = str(raw_entry.get("sha256") or "").strip().lower()
            actual_sha256 = hashlib.sha256(data).hexdigest()
            if len(data) != expected_size:
                raise LibraryArchiveError(
                    f"Size mismatch for archive entry: {path}",
                    code="archive_entry_size_mismatch",
                )
            if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or actual_sha256 != expected_sha256:
                raise LibraryArchiveError(
                    f"Checksum mismatch for archive entry: {path}",
                    code="archive_entry_checksum_mismatch",
                )
            manifest_paths.add(path)
            verified_entries.append(
                {
                    "path": path,
                    "size_bytes": len(data),
                    "sha256": actual_sha256,
                }
            )

        package_files = {
            name
            for name in seen
            if name.startswith(LIBRARY_ARCHIVE_PACKAGES_PREFIX) and not name.endswith("/")
        }
        if package_files != manifest_paths:
            unexpected = sorted(package_files - manifest_paths)
            raise LibraryArchiveError(
                f"Archive contains package files missing from its manifest: {unexpected[:5]}",
                code="archive_unlisted_package_file",
            )

        declared_count = _safe_int(manifest.get("package_file_count"), minimum=0)
        if declared_count != len(verified_entries):
            raise LibraryArchiveError(
                "Creative Library manifest file count does not match its entries.",
                code="archive_manifest_count_mismatch",
            )

    return {
        "ok": True,
        "status": "valid",
        "component": LIBRARY_ARCHIVE_COMPONENT,
        "format": LIBRARY_ARCHIVE_FORMAT,
        "format_version": LIBRARY_ARCHIVE_VERSION,
        "library_id": str(manifest.get("library_id") or DEFAULT_LIBRARY_ID),
        "archive_size_bytes": len(archive_bytes),
        "uncompressed_size_bytes": total_uncompressed,
        "package_file_count": len(verified_entries),
        "entries": verified_entries,
        "manifest": dict(manifest),
    }


def import_library_archive(
    content: bytes | bytearray | memoryview,
    *,
    source_root: Path | str | None = None,
    mode: str = "merge",
    overwrite: bool = False,
) -> dict[str, Any]:
    """Validate and import a library archive using merge or explicit replace."""
    archive_bytes = bytes(content or b"")
    validation = validate_library_archive(archive_bytes)
    resolved_root = Path(source_root or get_source_root()).resolve()
    resolved_root.parent.mkdir(parents=True, exist_ok=True)
    normalized_mode = str(mode or "merge").strip().lower()
    if normalized_mode not in {"merge", "replace"}:
        raise LibraryArchiveError(
            "Import mode must be 'merge' or 'replace'.",
            code="import_mode_invalid",
            http_status=400,
        )

    stage_root = Path(
        tempfile.mkdtemp(prefix=".vpcreative-import-", dir=str(resolved_root.parent))
    ).resolve()
    backup_root: Path | None = None
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), mode="r") as archive:
            for entry in validation["entries"]:
                archive_path = entry["path"]
                relative = archive_path[len(LIBRARY_ARCHIVE_PACKAGES_PREFIX) :]
                target = _safe_join(stage_root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_bytes_atomic(target, archive.read(archive_path))

        if normalized_mode == "merge":
            conflicts = [
                path.relative_to(stage_root).as_posix()
                for path in _iter_source_files(stage_root)
                if _safe_join(resolved_root, path.relative_to(stage_root).as_posix()).exists()
            ]
            if conflicts and not overwrite:
                raise LibraryArchiveError(
                    f"Import would overwrite existing files: {conflicts[:5]}",
                    code="import_conflict",
                    http_status=409,
                )
            resolved_root.mkdir(parents=True, exist_ok=True)
            imported_files: list[str] = []
            for staged_file in _iter_source_files(stage_root):
                relative = staged_file.relative_to(stage_root).as_posix()
                target = _safe_join(resolved_root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                _write_bytes_atomic(target, staged_file.read_bytes())
                imported_files.append(relative)
        else:
            imported_files = [
                path.relative_to(stage_root).as_posix()
                for path in _iter_source_files(stage_root)
            ]
            if resolved_root.exists():
                backup_root = resolved_root.with_name(
                    f".{resolved_root.name}.backup-{os.getpid()}-{int(datetime.now().timestamp())}"
                )
                resolved_root.replace(backup_root)
            stage_root.replace(resolved_root)
            stage_root = resolved_root
            if backup_root is not None and backup_root.exists():
                shutil.rmtree(backup_root)
                backup_root = None

        return {
            "ok": True,
            "status": "imported",
            "component": LIBRARY_ARCHIVE_COMPONENT,
            "format": LIBRARY_ARCHIVE_FORMAT,
            "format_version": LIBRARY_ARCHIVE_VERSION,
            "library_id": validation["library_id"],
            "mode": normalized_mode,
            "overwrite": bool(overwrite),
            "source_root": str(resolved_root),
            "imported_file_count": len(imported_files),
            "imported_files": sorted(imported_files),
            "validation": validation,
            "sync_required": True,
            "sync_route": "/api/v1/vplib/library/sync",
        }
    except Exception:
        if backup_root is not None and backup_root.exists() and not resolved_root.exists():
            backup_root.replace(resolved_root)
            backup_root = None
        raise
    finally:
        if stage_root.exists() and stage_root != resolved_root:
            shutil.rmtree(stage_root, ignore_errors=True)


def _iter_source_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise LibraryArchiveError(
                f"Symbolic links are not supported in Creative Libraries: {path}",
                code="library_symlink_unsupported",
            )
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            _validate_relative_package_path(relative)
            files.append(path)
    if len(files) > DEFAULT_MAX_ENTRIES:
        raise LibraryArchiveError(
            "Creative Library contains too many files.",
            code="library_entry_limit_exceeded",
            http_status=413,
        )
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def _validate_archive_member(
    value: Any,
    *,
    require_packages_prefix: bool = False,
) -> str:
    raw = str(value or "").replace("\\", "/").replace("\x00", "").strip()
    if not raw:
        raise LibraryArchiveError("Archive member path is empty.", code="archive_path_invalid")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or raw.startswith("/") or raw.startswith("\\"):
        raise LibraryArchiveError(
            f"Archive member path is absolute: {raw}",
            code="archive_path_unsafe",
        )
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise LibraryArchiveError(
            f"Archive member path is unsafe: {raw}",
            code="archive_path_unsafe",
        )
    normalized = pure.as_posix()
    if normalized != raw:
        raise LibraryArchiveError(
            f"Archive member path is not normalized: {raw}",
            code="archive_path_unsafe",
        )
    if ":" in pure.parts[0]:
        raise LibraryArchiveError(
            f"Archive member path contains a drive prefix: {raw}",
            code="archive_path_unsafe",
        )
    if require_packages_prefix and not normalized.startswith(LIBRARY_ARCHIVE_PACKAGES_PREFIX):
        raise LibraryArchiveError(
            f"Archive package path must start with '{LIBRARY_ARCHIVE_PACKAGES_PREFIX}': {raw}",
            code="archive_package_path_invalid",
        )
    if _is_blocked_path(normalized):
        raise LibraryArchiveError(
            f"Executable content is blocked in Creative Libraries: {raw}",
            code="archive_file_type_blocked",
        )
    return normalized


def _validate_relative_package_path(value: str) -> str:
    archive_path = f"{LIBRARY_ARCHIVE_PACKAGES_PREFIX}{value}"
    _validate_archive_member(archive_path, require_packages_prefix=True)
    return value


def _safe_join(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    target = (resolved_root / Path(*PurePosixPath(relative).parts)).resolve()
    try:
        target.relative_to(resolved_root)
    except ValueError as exc:
        raise LibraryArchiveError(
            f"Resolved path escapes the library root: {relative}",
            code="archive_path_unsafe",
        ) from exc
    return target


def _is_blocked_path(value: str) -> bool:
    return Path(value).suffix.lower() in BLOCKED_SUFFIXES


def _safe_identifier(value: Any, *, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("._-")
    return (text or fallback)[:96]


def _safe_int(value: Any, *, minimum: int = 0) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise LibraryArchiveError(
            "Archive manifest contains an invalid integer.",
            code="archive_manifest_integer_invalid",
        ) from exc
    return max(minimum, result)


def _write_zip_entry(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    _validate_archive_member(
        name,
        require_packages_prefix=name != LIBRARY_ARCHIVE_MANIFEST,
    )
    info = zipfile.ZipInfo(filename=name, date_time=DETERMINISTIC_ZIP_DATETIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.flag_bits |= 0x800
    archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _write_bytes_atomic(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temp.write_bytes(content)
        temp.replace(target)
    finally:
        if temp.exists():
            temp.unlink()


def get_library_archive_service_health() -> dict[str, Any]:
    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": LIBRARY_ARCHIVE_COMPONENT,
        "format": LIBRARY_ARCHIVE_FORMAT,
        "format_version": LIBRARY_ARCHIVE_VERSION,
        "extension": LIBRARY_ARCHIVE_EXTENSION,
        "source_root": str(get_source_root()),
        "creative_root": str(get_creative_library_root()),
        "supports_empty_default": True,
        "supports_export": True,
        "supports_import": True,
        "import_modes": ["merge", "replace"],
    }


__all__ = [
    "DEFAULT_LIBRARY_ARCHIVE_NAME",
    "DEFAULT_LIBRARY_ID",
    "LIBRARY_ARCHIVE_COMPONENT",
    "LIBRARY_ARCHIVE_EXTENSION",
    "LIBRARY_ARCHIVE_FORMAT",
    "LIBRARY_ARCHIVE_MANIFEST",
    "LIBRARY_ARCHIVE_VERSION",
    "LibraryArchiveError",
    "export_library_archive",
    "get_creative_library_root",
    "get_library_archive_service_health",
    "get_source_root",
    "import_library_archive",
    "initialize_default_library",
    "validate_library_archive",
]
