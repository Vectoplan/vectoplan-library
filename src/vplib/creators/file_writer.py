# services/vectoplan-library/src/vplib/creators/file_writer.py
"""
File writer for the VPLIB package engine.

Diese Datei ist der zentrale sichere Schreibbaustein der Creator-Schicht.

Rolle dieser Datei:

    DocumentBundle / documents mapping / PackagePlan / asset copy plans
    -> safe filesystem writes
    -> FileWriteBatchResult

Diese Datei kann:
- Verzeichnisse sicher anlegen
- JSON-Dateien schreiben
- Text-Dateien schreiben
- Binary-Dateien schreiben
- lokale Asset-Dateien ins Package kopieren
- dry-run ausführen
- atomic writes verwenden
- overwrite/skip/fail-Strategien anwenden
- package-relative Pfade absichern

Wichtig:
Alle Zielpfade werden gegen package_root geprüft. Parent-Traversal und absolute
package-relative Pfade sind nicht erlaubt.

Sonderfall:
- "." ist als Datei-Ziel weiterhin verboten.
- "." ist als Directory-Ziel erlaubt und bedeutet package_root selbst.
- FileWriteResult normalisiert relative_path abhängig von operation.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping


FILE_WRITER_SCHEMA_VERSION: Final[str] = "vplib.file_writer.v1"
DEFAULT_ENCODING: Final[str] = "utf-8"
DEFAULT_JSON_INDENT: Final[int] = 2
DEFAULT_TEMP_PREFIX: Final[str] = ".vplib-write-"
DEFAULT_BACKUP_SUFFIX: Final[str] = ".bak"


class FileWriterError(OSError):
    """Wird ausgelöst, wenn ein sicherer Schreibvorgang fehlschlägt."""


class WriteMode(str, Enum):
    """Verhalten bei bestehenden Dateien."""

    FAIL = "fail"
    SKIP = "skip"
    OVERWRITE = "overwrite"

    @property
    def key(self) -> str:
        return str(self.value)


class WriteStatus(str, Enum):
    """Status eines Schreibvorgangs."""

    WRITTEN = "written"
    CREATED = "created"
    SKIPPED = "skipped"
    DRY_RUN = "dry_run"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


class WriteOperation(str, Enum):
    """Art eines Schreibvorgangs."""

    CREATE_DIRECTORY = "create_directory"
    WRITE_JSON = "write_json"
    WRITE_TEXT = "write_text"
    WRITE_BINARY = "write_binary"
    COPY_FILE = "copy_file"

    @property
    def key(self) -> str:
        return str(self.value)


class FileContentKind(str, Enum):
    """Content-Art."""

    JSON = "json"
    TEXT = "text"
    BINARY = "binary"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class FileWriteOptions:
    """Optionen für sichere Dateischreibvorgänge."""

    write_mode: str = WriteMode.FAIL.value
    dry_run: bool = False
    atomic: bool = True
    create_parent_directories: bool = True
    create_package_root: bool = True
    backup_existing: bool = False
    sort_json_keys: bool = False
    ensure_ascii: bool = False
    json_indent: int = DEFAULT_JSON_INDENT
    encoding: str = DEFAULT_ENCODING
    newline_at_end: bool = True
    preserve_copy_metadata: bool = True
    strict: bool = True

    def normalized(self) -> "FileWriteOptions":
        return FileWriteOptions(
            write_mode=parse_write_mode_value(self.write_mode),
            dry_run=bool(self.dry_run),
            atomic=bool(self.atomic),
            create_parent_directories=bool(self.create_parent_directories),
            create_package_root=bool(self.create_package_root),
            backup_existing=bool(self.backup_existing),
            sort_json_keys=bool(self.sort_json_keys),
            ensure_ascii=bool(self.ensure_ascii),
            json_indent=normalize_non_negative_int(self.json_indent, "json_indent"),
            encoding=clean_required_string(self.encoding or DEFAULT_ENCODING, "encoding"),
            newline_at_end=bool(self.newline_at_end),
            preserve_copy_metadata=bool(self.preserve_copy_metadata),
            strict=bool(self.strict),
        )

    @property
    def may_overwrite(self) -> bool:
        return self.normalized().write_mode == WriteMode.OVERWRITE.value

    @property
    def may_skip(self) -> bool:
        return self.normalized().write_mode == WriteMode.SKIP.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "write_mode": normalized.write_mode,
            "dry_run": normalized.dry_run,
            "atomic": normalized.atomic,
            "create_parent_directories": normalized.create_parent_directories,
            "create_package_root": normalized.create_package_root,
            "backup_existing": normalized.backup_existing,
            "sort_json_keys": normalized.sort_json_keys,
            "ensure_ascii": normalized.ensure_ascii,
            "json_indent": normalized.json_indent,
            "encoding": normalized.encoding,
            "newline_at_end": normalized.newline_at_end,
            "preserve_copy_metadata": normalized.preserve_copy_metadata,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class FileWriteRequest:
    """Ein einzelner Schreibauftrag."""

    relative_path: str
    content: Any
    content_kind: str = FileContentKind.JSON.value
    write_mode: str | None = None
    encoding: str | None = None
    required: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FileWriteRequest":
        content_kind = parse_content_kind_value(self.content_kind)
        relative_path = normalize_relative_package_path(self.relative_path)
        write_mode = parse_optional_write_mode_value(self.write_mode)
        encoding = clean_optional_string(self.encoding)
        metadata = normalize_metadata(self.metadata)

        if content_kind == FileContentKind.JSON.value:
            normalize_json_value(self.content)
        elif content_kind == FileContentKind.TEXT.value:
            if not isinstance(self.content, str):
                raise FileWriterError(f"Text content for {relative_path!r} must be a string.")
        elif content_kind == FileContentKind.BINARY.value:
            if not isinstance(self.content, (bytes, bytearray, memoryview)):
                raise FileWriterError(f"Binary content for {relative_path!r} must be bytes-like.")

        return FileWriteRequest(
            relative_path=relative_path,
            content=self.content,
            content_kind=content_kind,
            write_mode=write_mode,
            encoding=encoding,
            required=bool(self.required),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "content_kind": normalized.content_kind,
            "write_mode": normalized.write_mode,
            "encoding": normalized.encoding,
            "required": normalized.required,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class FileCopyRequest:
    """Ein einzelner Copy-Auftrag."""

    source_path: str | Path
    relative_path: str
    write_mode: str | None = None
    required: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FileCopyRequest":
        source_path = normalize_local_source_path(self.source_path)
        relative_path = normalize_relative_package_path(self.relative_path)
        write_mode = parse_optional_write_mode_value(self.write_mode)
        metadata = normalize_metadata(self.metadata)

        return FileCopyRequest(
            source_path=source_path,
            relative_path=relative_path,
            write_mode=write_mode,
            required=bool(self.required),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "source_path": str(normalized.source_path),
            "relative_path": normalized.relative_path,
            "write_mode": normalized.write_mode,
            "required": normalized.required,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class FileWriteResult:
    """Ergebnis eines einzelnen Schreibvorgangs."""

    relative_path: str
    absolute_path: Path
    operation: str
    status: str
    bytes_written: int = 0
    existed_before: bool = False
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FileWriteResult":
        operation = parse_write_operation_value(self.operation)
        relative_path = normalize_result_relative_path(self.relative_path, operation)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        status = parse_write_status_value(self.status)
        bytes_written = normalize_non_negative_int(self.bytes_written, "bytes_written")
        error = clean_optional_string(self.error)
        metadata = normalize_metadata(self.metadata)

        if status == WriteStatus.FAILED.value and not error:
            error = "Write operation failed."

        return FileWriteResult(
            relative_path=relative_path,
            absolute_path=absolute_path,
            operation=operation,
            status=status,
            bytes_written=bytes_written,
            existed_before=bool(self.existed_before),
            error=error,
            metadata=metadata,
        )

    @property
    def ok(self) -> bool:
        return self.normalized().status in {
            WriteStatus.WRITTEN.value,
            WriteStatus.CREATED.value,
            WriteStatus.SKIPPED.value,
            WriteStatus.DRY_RUN.value,
        }

    @property
    def failed(self) -> bool:
        return self.normalized().status == WriteStatus.FAILED.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "operation": normalized.operation,
            "status": normalized.status,
            "ok": normalized.ok,
            "bytes_written": normalized.bytes_written,
            "existed_before": normalized.existed_before,
            "error": normalized.error,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class FileWriteBatchResult:
    """Ergebnis mehrerer Schreibvorgänge."""

    package_root: Path
    results: tuple[FileWriteResult, ...] = field(default_factory=tuple)
    options: FileWriteOptions = field(default_factory=FileWriteOptions)
    schema_version: str = FILE_WRITER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FileWriteBatchResult":
        package_root = normalize_absolute_path(self.package_root, "package_root")
        results = tuple(result.normalized() for result in self.results or ())
        options = self.options.normalized()
        metadata = normalize_metadata(self.metadata)

        return FileWriteBatchResult(
            package_root=package_root,
            results=tuple(sorted(results, key=lambda item: result_sort_key(item))),
            options=options,
            schema_version=self.schema_version or FILE_WRITER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.normalized().results)

    @property
    def failed(self) -> bool:
        return any(result.failed for result in self.normalized().results)

    @property
    def written_results(self) -> tuple[FileWriteResult, ...]:
        return tuple(
            result
            for result in self.normalized().results
            if result.status in {WriteStatus.WRITTEN.value, WriteStatus.CREATED.value}
        )

    @property
    def skipped_results(self) -> tuple[FileWriteResult, ...]:
        return tuple(
            result
            for result in self.normalized().results
            if result.status == WriteStatus.SKIPPED.value
        )

    @property
    def failed_results(self) -> tuple[FileWriteResult, ...]:
        return tuple(result for result in self.normalized().results if result.failed)

    @property
    def dry_run_results(self) -> tuple[FileWriteResult, ...]:
        return tuple(
            result
            for result in self.normalized().results
            if result.status == WriteStatus.DRY_RUN.value
        )

    @property
    def total_bytes_written(self) -> int:
        return sum(result.bytes_written for result in self.normalized().results)

    def raise_for_errors(self) -> None:
        normalized = self.normalized()

        if normalized.failed:
            messages = "; ".join(
                f"{result.relative_path}: {result.error}"
                for result in normalized.failed_results
            )
            raise FileWriterError(messages or "File write batch failed.")

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "package_root": str(normalized.package_root),
            "ok": normalized.ok,
            "failed": normalized.failed,
            "result_count": len(normalized.results),
            "written_count": len(normalized.written_results),
            "skipped_count": len(normalized.skipped_results),
            "dry_run_count": len(normalized.dry_run_results),
            "failed_count": len(normalized.failed_results),
            "total_bytes_written": normalized.total_bytes_written,
            "options": normalized.options.to_dict(),
            "results": [result.to_dict() for result in normalized.results],
            "metadata": dict(normalized.metadata),
        }


def write_documents_to_package(
    *,
    package_root: str | Path,
    documents: Mapping[str, Mapping[str, Any]],
    options: FileWriteOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteBatchResult:
    """Schreibt ein path -> JSON-document Mapping ins Package."""
    normalized_documents = normalize_documents_mapping(documents)
    requests = tuple(
        FileWriteRequest(
            relative_path=relative_path,
            content=document,
            content_kind=FileContentKind.JSON.value,
            required=True,
            metadata={
                "source": "documents",
            },
        ).normalized()
        for relative_path, document in normalized_documents.items()
    )

    return write_file_requests(
        package_root=package_root,
        requests=requests,
        options=options,
        metadata={
            "source": "documents",
            "document_count": len(normalized_documents),
            **dict(metadata or {}),
        },
    )


def write_document_bundle_to_package(
    *,
    package_root: str | Path,
    bundle: Any,
    options: FileWriteOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteBatchResult:
    """Schreibt ein DocumentBundle-ähnliches Objekt ins Package."""
    normalized_bundle = normalize_document_bundle(bundle)
    documents = (
        normalized_bundle.to_documents()
        if hasattr(normalized_bundle, "to_documents")
        else normalized_bundle.documents
    )

    return write_documents_to_package(
        package_root=package_root,
        documents=documents,
        options=options,
        metadata={
            "source": "document_bundle",
            "bundle_schema_version": getattr(normalized_bundle, "schema_version", None),
            **dict(metadata or {}),
        },
    )


def write_file_requests(
    *,
    package_root: str | Path,
    requests: Iterable[FileWriteRequest],
    options: FileWriteOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteBatchResult:
    """Schreibt mehrere FileWriteRequest-Aufträge."""
    normalized_options = normalize_options(options)
    root = normalize_absolute_path(package_root, "package_root")
    results: list[FileWriteResult] = []

    try:
        if normalized_options.create_package_root:
            results.append(ensure_package_directory(root, ".", options=normalized_options))
    except Exception as exc:
        if normalized_options.strict:
            raise
        results.append(
            failed_result(
                package_root=root,
                relative_path=".",
                operation=WriteOperation.CREATE_DIRECTORY.value,
                error=str(exc),
            )
        )

    for request in requests or ():
        try:
            results.append(
                write_file_request(
                    package_root=root,
                    request=request,
                    options=normalized_options,
                )
            )
        except Exception as exc:
            normalized_request = request.normalized()
            if normalized_options.strict and normalized_request.required:
                raise
            results.append(
                failed_result(
                    package_root=root,
                    relative_path=normalized_request.relative_path,
                    operation=operation_for_content_kind(normalized_request.content_kind),
                    error=str(exc),
                )
            )

    return FileWriteBatchResult(
        package_root=root,
        results=tuple(results),
        options=normalized_options,
        metadata={
            "source": "file_requests",
            **dict(metadata or {}),
        },
    ).normalized()


def write_copy_requests(
    *,
    package_root: str | Path,
    requests: Iterable[FileCopyRequest],
    options: FileWriteOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteBatchResult:
    """Kopiert mehrere lokale Dateien ins Package."""
    normalized_options = normalize_options(options)
    root = normalize_absolute_path(package_root, "package_root")
    results: list[FileWriteResult] = []

    try:
        if normalized_options.create_package_root:
            results.append(ensure_package_directory(root, ".", options=normalized_options))
    except Exception as exc:
        if normalized_options.strict:
            raise
        results.append(
            failed_result(
                package_root=root,
                relative_path=".",
                operation=WriteOperation.CREATE_DIRECTORY.value,
                error=str(exc),
            )
        )

    for request in requests or ():
        try:
            results.append(
                copy_file_request(
                    package_root=root,
                    request=request,
                    options=normalized_options,
                )
            )
        except Exception as exc:
            normalized_request = request.normalized()
            if normalized_options.strict and normalized_request.required:
                raise
            results.append(
                failed_result(
                    package_root=root,
                    relative_path=normalized_request.relative_path,
                    operation=WriteOperation.COPY_FILE.value,
                    error=str(exc),
                )
            )

    return FileWriteBatchResult(
        package_root=root,
        results=tuple(results),
        options=normalized_options,
        metadata={
            "source": "copy_requests",
            **dict(metadata or {}),
        },
    ).normalized()


def write_package_plan_directories(
    *,
    package_root: str | Path,
    package_plan: Any,
    options: FileWriteOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteBatchResult:
    """Legt geplante PackagePlan-Verzeichnisse an."""
    normalized_options = normalize_options(options)
    root = normalize_absolute_path(package_root, "package_root")
    directories = extract_directory_paths_from_package_plan(package_plan)

    results = [
        ensure_package_directory(root, relative_path, options=normalized_options)
        for relative_path in directories
    ]

    return FileWriteBatchResult(
        package_root=root,
        results=tuple(results),
        options=normalized_options,
        metadata={
            "source": "package_plan_directories",
            "directory_count": len(directories),
            **dict(metadata or {}),
        },
    ).normalized()


def copy_package_plan_assets(
    *,
    package_root: str | Path,
    package_plan: Any,
    options: FileWriteOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteBatchResult:
    """Kopiert geplante PackagePlan-Assets ins Package."""
    copy_requests = tuple(
        file_copy_request_from_planned_asset_copy(item)
        for item in extract_asset_copies_from_package_plan(package_plan)
    )

    return write_copy_requests(
        package_root=package_root,
        requests=copy_requests,
        options=options,
        metadata={
            "source": "package_plan_assets",
            "asset_copy_count": len(copy_requests),
            **dict(metadata or {}),
        },
    )


def write_file_request(
    *,
    package_root: str | Path,
    request: FileWriteRequest,
    options: FileWriteOptions,
) -> FileWriteResult:
    """Schreibt einen einzelnen FileWriteRequest."""
    root = normalize_absolute_path(package_root, "package_root")
    normalized_options = options.normalized()
    normalized_request = request.normalized()

    target_path = resolve_package_target_path(root, normalized_request.relative_path)
    existed_before = target_path.exists()
    write_mode = normalized_request.write_mode or normalized_options.write_mode
    operation = operation_for_content_kind(normalized_request.content_kind)

    action = evaluate_existing_target(
        target_path=target_path,
        write_mode=write_mode,
        operation=operation,
    )

    if action == WriteStatus.SKIPPED.value:
        return FileWriteResult(
            relative_path=normalized_request.relative_path,
            absolute_path=target_path,
            operation=operation,
            status=WriteStatus.SKIPPED.value,
            bytes_written=0,
            existed_before=existed_before,
            metadata={"reason": "target_exists"},
        ).normalized()

    payload = serialize_file_content(
        content=normalized_request.content,
        content_kind=normalized_request.content_kind,
        options=normalized_options,
        encoding=normalized_request.encoding,
    )

    if normalized_options.dry_run:
        return FileWriteResult(
            relative_path=normalized_request.relative_path,
            absolute_path=target_path,
            operation=operation,
            status=WriteStatus.DRY_RUN.value,
            bytes_written=len(payload),
            existed_before=existed_before,
            metadata={
                "would_write": True,
                "content_kind": normalized_request.content_kind,
            },
        ).normalized()

    if normalized_options.create_parent_directories:
        target_path.parent.mkdir(parents=True, exist_ok=True)

    if normalized_options.backup_existing and existed_before and write_mode == WriteMode.OVERWRITE.value:
        create_backup_file(target_path)

    if normalized_options.atomic:
        atomic_write_bytes(target_path, payload)
    else:
        target_path.write_bytes(payload)

    return FileWriteResult(
        relative_path=normalized_request.relative_path,
        absolute_path=target_path,
        operation=operation,
        status=WriteStatus.WRITTEN.value if existed_before else WriteStatus.CREATED.value,
        bytes_written=len(payload),
        existed_before=existed_before,
        metadata={
            "content_kind": normalized_request.content_kind,
        },
    ).normalized()


def copy_file_request(
    *,
    package_root: str | Path,
    request: FileCopyRequest,
    options: FileWriteOptions,
) -> FileWriteResult:
    """Kopiert eine lokale Datei sicher ins Package."""
    root = normalize_absolute_path(package_root, "package_root")
    normalized_options = options.normalized()
    normalized_request = request.normalized()

    source_path = normalize_local_source_path(normalized_request.source_path)
    target_path = resolve_package_target_path(root, normalized_request.relative_path)
    existed_before = target_path.exists()
    write_mode = normalized_request.write_mode or normalized_options.write_mode

    if not source_path.exists():
        raise FileWriterError(f"Source file does not exist: {source_path}")

    if not source_path.is_file():
        raise FileWriterError(f"Source path is not a file: {source_path}")

    action = evaluate_existing_target(
        target_path=target_path,
        write_mode=write_mode,
        operation=WriteOperation.COPY_FILE.value,
    )

    if action == WriteStatus.SKIPPED.value:
        return FileWriteResult(
            relative_path=normalized_request.relative_path,
            absolute_path=target_path,
            operation=WriteOperation.COPY_FILE.value,
            status=WriteStatus.SKIPPED.value,
            bytes_written=0,
            existed_before=existed_before,
            metadata={
                "source_path": str(source_path),
                "reason": "target_exists",
            },
        ).normalized()

    source_size = source_path.stat().st_size

    if normalized_options.dry_run:
        return FileWriteResult(
            relative_path=normalized_request.relative_path,
            absolute_path=target_path,
            operation=WriteOperation.COPY_FILE.value,
            status=WriteStatus.DRY_RUN.value,
            bytes_written=source_size,
            existed_before=existed_before,
            metadata={
                "source_path": str(source_path),
                "would_copy": True,
            },
        ).normalized()

    if normalized_options.create_parent_directories:
        target_path.parent.mkdir(parents=True, exist_ok=True)

    if normalized_options.backup_existing and existed_before and write_mode == WriteMode.OVERWRITE.value:
        create_backup_file(target_path)

    if normalized_options.atomic:
        atomic_copy_file(
            source_path=source_path,
            target_path=target_path,
            preserve_metadata=normalized_options.preserve_copy_metadata,
        )
    else:
        if normalized_options.preserve_copy_metadata:
            shutil.copy2(source_path, target_path)
        else:
            shutil.copyfile(source_path, target_path)

    return FileWriteResult(
        relative_path=normalized_request.relative_path,
        absolute_path=target_path,
        operation=WriteOperation.COPY_FILE.value,
        status=WriteStatus.WRITTEN.value if existed_before else WriteStatus.CREATED.value,
        bytes_written=source_size,
        existed_before=existed_before,
        metadata={
            "source_path": str(source_path),
        },
    ).normalized()


def ensure_package_directory(
    package_root: Path,
    relative_path: str,
    *,
    options: FileWriteOptions,
) -> FileWriteResult:
    """Legt ein Package-Verzeichnis sicher an."""
    root = normalize_absolute_path(package_root, "package_root")
    normalized_options = options.normalized()

    relative = normalize_relative_directory_path(relative_path)
    target_path = root if relative == "." else resolve_package_target_path(root, relative)
    existed_before = target_path.exists()

    if existed_before and not target_path.is_dir():
        raise FileWriterError(f"Directory target exists but is not a directory: {target_path}")

    if normalized_options.dry_run:
        return FileWriteResult(
            relative_path=relative,
            absolute_path=target_path,
            operation=WriteOperation.CREATE_DIRECTORY.value,
            status=WriteStatus.DRY_RUN.value,
            bytes_written=0,
            existed_before=existed_before,
            metadata={"would_create_directory": not existed_before},
        ).normalized()

    target_path.mkdir(parents=True, exist_ok=True)

    return FileWriteResult(
        relative_path=relative,
        absolute_path=target_path,
        operation=WriteOperation.CREATE_DIRECTORY.value,
        status=WriteStatus.SKIPPED.value if existed_before else WriteStatus.CREATED.value,
        bytes_written=0,
        existed_before=existed_before,
        metadata={"directory": True},
    ).normalized()


def serialize_file_content(
    *,
    content: Any,
    content_kind: str,
    options: FileWriteOptions,
    encoding: str | None = None,
) -> bytes:
    """Serialisiert Content zu Bytes."""
    normalized_options = options.normalized()
    kind = parse_content_kind_value(content_kind)
    resolved_encoding = clean_optional_string(encoding) or normalized_options.encoding

    if kind == FileContentKind.JSON.value:
        text = json.dumps(
            normalize_json_value(content),
            ensure_ascii=normalized_options.ensure_ascii,
            indent=normalized_options.json_indent,
            sort_keys=normalized_options.sort_json_keys,
        )
        if normalized_options.newline_at_end and not text.endswith("\n"):
            text += "\n"
        return text.encode(resolved_encoding)

    if kind == FileContentKind.TEXT.value:
        text = str(content)
        if normalized_options.newline_at_end and not text.endswith("\n"):
            text += "\n"
        return text.encode(resolved_encoding)

    if kind == FileContentKind.BINARY.value:
        if isinstance(content, memoryview):
            return content.tobytes()
        if isinstance(content, bytearray):
            return bytes(content)
        if isinstance(content, bytes):
            return content
        raise FileWriterError("Binary content must be bytes-like.")

    raise FileWriterError(f"Unsupported content kind {content_kind!r}.")


def atomic_write_bytes(target_path: Path, payload: bytes) -> None:
    """Schreibt Bytes atomar über temporäre Datei im Zielordner."""
    target_path = normalize_absolute_path(target_path, "target_path")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(target_path.parent),
            prefix=DEFAULT_TEMP_PREFIX,
        ) as temp_file:
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)

        os.replace(temp_path, target_path)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


def atomic_copy_file(
    *,
    source_path: Path,
    target_path: Path,
    preserve_metadata: bool = True,
) -> None:
    """Kopiert eine Datei atomar über temporären Zielpfad."""
    source_path = normalize_local_source_path(source_path)
    target_path = normalize_absolute_path(target_path, "target_path")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=str(target_path.parent),
            prefix=DEFAULT_TEMP_PREFIX,
        ) as temp_file:
            temp_path = Path(temp_file.name)

        if preserve_metadata:
            shutil.copy2(source_path, temp_path)
        else:
            shutil.copyfile(source_path, temp_path)

        os.replace(temp_path, target_path)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


def create_backup_file(target_path: Path) -> Path:
    """Erzeugt ein einfaches Backup für eine bestehende Datei."""
    target_path = normalize_absolute_path(target_path, "target_path")

    if not target_path.exists():
        raise FileWriterError(f"Cannot backup missing file: {target_path}")

    backup_path = target_path.with_name(f"{target_path.name}{DEFAULT_BACKUP_SUFFIX}")
    counter = 1

    while backup_path.exists():
        backup_path = target_path.with_name(f"{target_path.name}{DEFAULT_BACKUP_SUFFIX}.{counter}")
        counter += 1

    shutil.copy2(target_path, backup_path)
    return backup_path


def evaluate_existing_target(
    *,
    target_path: Path,
    write_mode: str,
    operation: str,
) -> str:
    """Bewertet, ob ein bestehendes Ziel überschrieben, übersprungen oder blockiert wird."""
    mode = parse_write_mode_value(write_mode)

    if not target_path.exists():
        return WriteStatus.WRITTEN.value

    if target_path.is_dir() and operation != WriteOperation.CREATE_DIRECTORY.value:
        raise FileWriterError(f"Target exists as directory: {target_path}")

    if mode == WriteMode.SKIP.value:
        return WriteStatus.SKIPPED.value

    if mode == WriteMode.OVERWRITE.value:
        return WriteStatus.WRITTEN.value

    raise FileWriterError(f"Target already exists and write_mode='fail': {target_path}")


def resolve_package_target_path(package_root: Path, relative_path: str) -> Path:
    """Löst package-relativen Datei- oder Unterordner-Pfad sicher unter package_root auf."""
    root = normalize_absolute_path(package_root, "package_root")
    relative = normalize_relative_package_path(relative_path)
    target = root / relative

    if not is_path_inside_root(target, root):
        raise FileWriterError(f"Resolved target path escapes package_root: {relative_path!r}")

    return target


def is_path_inside_root(path: Path, root: Path) -> bool:
    """Prüft, ob path innerhalb root liegt."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


def file_write_request_from_document(
    relative_path: str,
    document: Mapping[str, Any],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> FileWriteRequest:
    """Baut FileWriteRequest aus Dokument."""
    return FileWriteRequest(
        relative_path=relative_path,
        content=document,
        content_kind=FileContentKind.JSON.value,
        required=True,
        metadata=dict(metadata or {}),
    ).normalized()


def file_copy_request_from_planned_asset_copy(value: Any) -> FileCopyRequest:
    """Baut FileCopyRequest aus PlannedAssetCopy-ähnlichem Objekt."""
    if isinstance(value, Mapping):
        source_path = value.get("source_path")
        relative_path = value.get("target_relative_path") or value.get("target_package_path") or value.get("package_path")
        required = bool(value.get("required", False))
        metadata = dict(value.get("metadata", {}) or {})
    else:
        source_path = getattr(value, "source_path", None)
        relative_path = (
            getattr(value, "target_relative_path", None)
            or getattr(value, "target_package_path", None)
            or getattr(value, "package_path", None)
        )
        required = bool(getattr(value, "required", False))
        metadata = dict(getattr(value, "metadata", {}) or {})

    return FileCopyRequest(
        source_path=source_path,
        relative_path=relative_path,
        required=required,
        metadata=metadata,
    ).normalized()


def extract_directory_paths_from_package_plan(package_plan: Any) -> tuple[str, ...]:
    """Extrahiert Directory-Pfade aus PackagePlan-ähnlichem Objekt."""
    normalized_plan = package_plan.normalized() if hasattr(package_plan, "normalized") else package_plan
    paths: list[str] = []

    for value in getattr(normalized_plan, "directories", ()) or ():
        path = extract_relative_path(value)
        if path:
            paths.append(path)

    for value in getattr(normalized_plan, "planned_directories", ()) or ():
        path = extract_relative_path(value)
        if path:
            paths.append(path)

    return dedupe_paths(paths)


def extract_asset_copies_from_package_plan(package_plan: Any) -> tuple[Any, ...]:
    """Extrahiert AssetCopy-Einträge aus PackagePlan-ähnlichem Objekt."""
    normalized_plan = package_plan.normalized() if hasattr(package_plan, "normalized") else package_plan
    return tuple(getattr(normalized_plan, "asset_copies", ()) or ())


def extract_relative_path(value: Any) -> str | None:
    """Extrahiert relative_path aus verschiedenen PlanItem-Formen."""
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, Mapping):
        return (
            clean_optional_string(value.get("relative_path"))
            or clean_optional_string(value.get("path"))
            or clean_optional_string(value.get("target_relative_path"))
        )

    return (
        clean_optional_string(getattr(value, "relative_path", None))
        or clean_optional_string(getattr(value, "path", None))
        or clean_optional_string(getattr(value, "target_relative_path", None))
    )


def operation_for_content_kind(content_kind: str) -> str:
    """Mappt ContentKind auf WriteOperation."""
    kind = parse_content_kind_value(content_kind)

    if kind == FileContentKind.JSON.value:
        return WriteOperation.WRITE_JSON.value

    if kind == FileContentKind.TEXT.value:
        return WriteOperation.WRITE_TEXT.value

    if kind == FileContentKind.BINARY.value:
        return WriteOperation.WRITE_BINARY.value

    raise FileWriterError(f"Unsupported content kind {content_kind!r}.")


def failed_result(
    *,
    package_root: Path,
    relative_path: str,
    operation: str,
    error: str,
) -> FileWriteResult:
    """Erzeugt ein fehlgeschlagenes FileWriteResult."""
    root = normalize_absolute_path(package_root, "package_root")
    parsed_operation = parse_write_operation_value(operation)
    relative = normalize_result_relative_path(relative_path, parsed_operation)
    absolute = root if relative == "." else root / relative

    return FileWriteResult(
        relative_path=relative,
        absolute_path=absolute,
        operation=parsed_operation,
        status=WriteStatus.FAILED.value,
        bytes_written=0,
        existed_before=absolute.exists(),
        error=error,
    ).normalized()


def normalize_options(options: FileWriteOptions | Mapping[str, Any] | None) -> FileWriteOptions:
    """Normalisiert FileWriteOptions."""
    if options is None:
        return FileWriteOptions().normalized()

    if isinstance(options, FileWriteOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return FileWriteOptions(
            write_mode=options.get("write_mode", WriteMode.FAIL.value),
            dry_run=bool(options.get("dry_run", False)),
            atomic=bool(options.get("atomic", True)),
            create_parent_directories=bool(options.get("create_parent_directories", True)),
            create_package_root=bool(options.get("create_package_root", True)),
            backup_existing=bool(options.get("backup_existing", False)),
            sort_json_keys=bool(options.get("sort_json_keys", False)),
            ensure_ascii=bool(options.get("ensure_ascii", False)),
            json_indent=options.get("json_indent", DEFAULT_JSON_INDENT),
            encoding=options.get("encoding", DEFAULT_ENCODING),
            newline_at_end=bool(options.get("newline_at_end", True)),
            preserve_copy_metadata=bool(options.get("preserve_copy_metadata", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise FileWriterError("options must be FileWriteOptions, mapping or None.")


def normalize_document_bundle(value: Any) -> Any:
    """Normalisiert DocumentBundle-ähnliche Werte."""
    try:
        from ..defaults.document_bundle import DocumentBundle, build_document_bundle_from_components

        if isinstance(value, DocumentBundle):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping):
            return build_document_bundle_from_components(documents=value).normalized()

        raise FileWriterError("DocumentBundle value is required.")
    except FileWriterError:
        raise
    except Exception as exc:
        raise FileWriterError(f"Invalid DocumentBundle: {exc}") from exc


def normalize_documents_mapping(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalisiert path -> document Mapping."""
    if not isinstance(documents, Mapping):
        raise FileWriterError("documents must be a mapping.")

    return {
        normalize_relative_package_path(path): normalize_document_mapping(document)
        for path, document in documents.items()
    }


def normalize_document_mapping(document: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert ein JSON-Dokument."""
    if not isinstance(document, Mapping):
        raise FileWriterError("document must be a mapping.")

    return {
        str(key): normalize_json_value(value)
        for key, value in document.items()
    }


def normalize_json_value(value: Any) -> Any:
    """Normalisiert JSON-kompatible Werte."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_value(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    return str(value)


def normalize_result_relative_path(value: Any, operation: str) -> str:
    """
    Normalisiert relative_path für FileWriteResult.

    CREATE_DIRECTORY darf "." verwenden, weil "." das Package-Root selbst meint.
    Alle Datei-/Copy-Operationen müssen echte package-relative Datei-Pfade sein.
    """
    parsed_operation = parse_write_operation_value(operation)

    if parsed_operation == WriteOperation.CREATE_DIRECTORY.value:
        return normalize_relative_directory_path(value)

    return normalize_relative_package_path(value)


def normalize_relative_package_path(value: Any) -> str:
    """Normalisiert package-relative Datei-Pfade."""
    raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

    if raw == ".":
        raise FileWriterError("relative file path must not be '.'.")

    if raw.startswith("/"):
        raise FileWriterError(f"relative_path must not be absolute: {value!r}")

    path = PurePosixPath(raw)

    if path.is_absolute():
        raise FileWriterError(f"relative_path must not be absolute: {value!r}")

    parts = tuple(part for part in path.parts if part not in {"", "."})

    if not parts:
        raise FileWriterError("relative_path is required.")

    if any(part == ".." for part in parts):
        raise FileWriterError(f"relative_path must not contain parent traversal: {value!r}")

    return str(PurePosixPath(*parts))


def normalize_relative_directory_path(value: Any) -> str:
    """Normalisiert package-relative Directory-Pfade."""
    raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

    if raw == ".":
        return "."

    if raw.startswith("/"):
        raise FileWriterError(f"relative directory path must not be absolute: {value!r}")

    path = PurePosixPath(raw)
    parts = tuple(part for part in path.parts if part not in {"", "."})

    if not parts:
        return "."

    if any(part == ".." for part in parts):
        raise FileWriterError(f"relative directory path must not contain parent traversal: {value!r}")

    return str(PurePosixPath(*parts))


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert lokalen absoluten/relativen Systempfad."""
    try:
        if value is None:
            raise FileWriterError(f"{field_name} is required.")

        return Path(value).expanduser()
    except FileWriterError:
        raise
    except Exception as exc:
        raise FileWriterError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_local_source_path(value: Any) -> Path:
    """Normalisiert lokalen Source-Pfad."""
    return normalize_absolute_path(value, "source_path")


@lru_cache(maxsize=128)
def parse_write_mode_value(value: Any) -> str:
    """Parst WriteMode."""
    try:
        if isinstance(value, WriteMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "fail": WriteMode.FAIL.value,
            "error": WriteMode.FAIL.value,
            "strict": WriteMode.FAIL.value,
            "skip": WriteMode.SKIP.value,
            "ignore": WriteMode.SKIP.value,
            "overwrite": WriteMode.OVERWRITE.value,
            "replace": WriteMode.OVERWRITE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return WriteMode(raw).value
    except Exception as exc:
        raise FileWriterError(f"Invalid write_mode {value!r}.") from exc


def parse_optional_write_mode_value(value: Any) -> str | None:
    """Parst optionalen WriteMode."""
    if value is None:
        return None

    return parse_write_mode_value(value)


@lru_cache(maxsize=128)
def parse_write_status_value(value: Any) -> str:
    """Parst WriteStatus."""
    try:
        if isinstance(value, WriteStatus):
            return value.value

        raw = normalize_enum_key(value)
        return WriteStatus(raw).value
    except Exception as exc:
        raise FileWriterError(f"Invalid write status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_write_operation_value(value: Any) -> str:
    """Parst WriteOperation."""
    try:
        if isinstance(value, WriteOperation):
            return value.value

        raw = normalize_enum_key(value)
        return WriteOperation(raw).value
    except Exception as exc:
        raise FileWriterError(f"Invalid write operation {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_content_kind_value(value: Any) -> str:
    """Parst FileContentKind."""
    try:
        if isinstance(value, FileContentKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "json": FileContentKind.JSON.value,
            "dict": FileContentKind.JSON.value,
            "mapping": FileContentKind.JSON.value,
            "text": FileContentKind.TEXT.value,
            "str": FileContentKind.TEXT.value,
            "string": FileContentKind.TEXT.value,
            "binary": FileContentKind.BINARY.value,
            "bytes": FileContentKind.BINARY.value,
        }

        if raw in aliases:
            return aliases[raw]

        return FileContentKind(raw).value
    except Exception as exc:
        raise FileWriterError(f"Invalid content kind {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise FileWriterError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except FileWriterError:
        raise
    except Exception as exc:
        raise FileWriterError(f"Invalid enum value {value!r}.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise FileWriterError(f"{field_name} must be an integer.")

        number = int(value)

        if number < 0:
            raise FileWriterError(f"{field_name} must be >= 0.")

        return number
    except FileWriterError:
        raise
    except Exception as exc:
        raise FileWriterError(f"{field_name} must be a non-negative integer.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise FileWriterError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def dedupe_paths(values: Iterable[Any]) -> tuple[str, ...]:
    """Dedupliziert relative Directory-Pfade."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned:
            continue

        normalized = normalize_relative_directory_path(cleaned)

        if normalized in seen:
            continue

        result.append(normalized)
        seen.add(normalized)

    return tuple(sorted(result, key=lambda item: (0 if item == "." else 1, item)))


def result_sort_key(result: FileWriteResult) -> tuple[int, str, str]:
    """Sortierschlüssel für FileWriteResult."""
    normalized = result.normalized()

    if normalized.relative_path == ".":
        return (0, normalized.operation, normalized.relative_path)

    if normalized.operation == WriteOperation.CREATE_DIRECTORY.value:
        return (1, normalized.operation, normalized.relative_path)

    return (2, normalized.operation, normalized.relative_path)


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise FileWriterError(f"{field_name} is required.")

        return cleaned
    except FileWriterError:
        raise
    except Exception as exc:
        raise FileWriterError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_file_writer_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_write_mode_value.cache_clear()
    parse_write_status_value.cache_clear()
    parse_write_operation_value.cache_clear()
    parse_content_kind_value.cache_clear()


__all__ = [
    "DEFAULT_BACKUP_SUFFIX",
    "DEFAULT_ENCODING",
    "DEFAULT_JSON_INDENT",
    "DEFAULT_TEMP_PREFIX",
    "FILE_WRITER_SCHEMA_VERSION",
    "FileContentKind",
    "FileCopyRequest",
    "FileWriteBatchResult",
    "FileWriteOptions",
    "FileWriteRequest",
    "FileWriteResult",
    "FileWriterError",
    "WriteMode",
    "WriteOperation",
    "WriteStatus",
    "atomic_copy_file",
    "atomic_write_bytes",
    "clean_optional_string",
    "clean_required_string",
    "clear_file_writer_caches",
    "copy_file_request",
    "copy_package_plan_assets",
    "create_backup_file",
    "dedupe_paths",
    "ensure_package_directory",
    "evaluate_existing_target",
    "extract_asset_copies_from_package_plan",
    "extract_directory_paths_from_package_plan",
    "extract_relative_path",
    "failed_result",
    "file_copy_request_from_planned_asset_copy",
    "file_write_request_from_document",
    "is_path_inside_root",
    "normalize_absolute_path",
    "normalize_document_bundle",
    "normalize_document_mapping",
    "normalize_documents_mapping",
    "normalize_enum_key",
    "normalize_json_value",
    "normalize_local_source_path",
    "normalize_metadata",
    "normalize_non_negative_int",
    "normalize_options",
    "normalize_relative_directory_path",
    "normalize_relative_package_path",
    "normalize_result_relative_path",
    "operation_for_content_kind",
    "parse_content_kind_value",
    "parse_optional_write_mode_value",
    "parse_write_mode_value",
    "parse_write_operation_value",
    "parse_write_status_value",
    "resolve_package_target_path",
    "result_sort_key",
    "serialize_file_content",
    "write_copy_requests",
    "write_document_bundle_to_package",
    "write_documents_to_package",
    "write_file_request",
    "write_file_requests",
    "write_package_plan_directories",
]