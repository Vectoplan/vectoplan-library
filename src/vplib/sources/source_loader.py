# services/vectoplan-library/src/vplib/sources/source_loader.py
"""
Source loader for the VPLIB package engine.

Diese Datei lädt gescannte Source-Packages in eine Creative-Library-Struktur.

Rolle dieser Datei:

    sources/
      object_a/
        vplib.manifest.json
        family/identity.json
        render/assets/model.glb
        ...

    -> SourceScanner
    -> SourcePackageCandidate
    -> DocumentBundle
    -> library_catalog_root/<package_dir>/
    -> optional .vplib archive

Diese Datei:
- nutzt source_scanner.py für Erkennung und Validierung
- übernimmt `vplib_uid` aus dem gescannten Manifest
- schreibt JSON-Dokumente über creators/file_writer.py
- kopiert Asset-/Neben-Dateien aus dem Source-Package
- kann bestehende Library-Einträge skippen, failen oder überschreiben
- unterstützt dry-run
- erzeugt ein strukturiertes SourceLoadResult
- liest Source-Dateien und schreibt in den Library-Katalog

Wichtig für die neue VPLIB-ID-/DB-Architektur:
- `vplib_uid` wird nicht hier erzeugt.
- `vplib_uid` kommt aus dem SourcePackageCandidate / `vplib.manifest.json`.
- Der Loader erhält und spiegelt diese ID in Target, ItemResult, LoadResult,
  Metadata, Write-Result, Asset-Copy und Archive-Erzeugung.
- Die spätere Datenbank übernimmt diese ID aus dem validierten Package.
- Falls ein Candidate keine gültige `vplib_uid` hat, sollte er bereits im
  Scanner/Validator invalid sein. Dieser Loader behandelt fehlende IDs
  zusätzlich defensiv.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping


SOURCE_LOADER_SCHEMA_VERSION: Final[str] = "vplib.source_loader.v1"

DEFAULT_PACKAGE_DIR_PATTERN: Final[str] = "{family_slug}"
DEFAULT_ENCODING: Final[str] = "utf-8"

MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"
MANIFEST_DOCUMENT_PATH: Final[str] = "vplib.manifest.json"

IGNORED_COPY_FILE_NAMES: Final[tuple[str, ...]] = (
    ".DS_Store",
    "Thumbs.db",
)

IGNORED_COPY_DIRECTORY_NAMES: Final[tuple[str, ...]] = (
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
)

IGNORED_COPY_SUFFIXES: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
    ".tmp",
    ".temp",
    ".bak",
    ".swp",
)

JSON_DOCUMENT_SUFFIX: Final[str] = ".json"


class SourceLoaderError(RuntimeError):
    """Wird ausgelöst, wenn der Source-Loader selbst fehlschlägt."""


class SourceLoadStatus(str, Enum):
    """Status eines Load-Ergebnisses."""

    LOADED = "loaded"
    DRY_RUN = "dry_run"
    SKIPPED = "skipped"
    PARTIAL = "partial"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


class SourceLoadAction(str, Enum):
    """Aktion beim Laden eines Kandidaten."""

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    FAIL = "fail"

    @property
    def key(self) -> str:
        return str(self.value)


class SourceLoadWriteMode(str, Enum):
    """Verhalten bei bestehenden Library-Zielen."""

    FAIL = "fail"
    SKIP = "skip"
    OVERWRITE = "overwrite"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SourceLoadOptions:
    """Optionen für das Laden von Source-Packages in die Creative Library."""

    write_mode: str = SourceLoadWriteMode.FAIL.value
    dry_run: bool = False
    scan_options: Mapping[str, Any] = field(default_factory=dict)
    validate_before_write: bool = True
    validate_after_write: bool = False
    skip_invalid_candidates: bool = True
    write_documents: bool = True
    copy_assets: bool = True
    create_archive: bool = False
    include_optional_documents: bool = True
    include_generated_documents: bool = True
    package_dir_pattern: str = DEFAULT_PACKAGE_DIR_PATTERN
    atomic_writes: bool = True
    backup_existing: bool = False
    fail_on_candidate_error: bool = False
    strict: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceLoadOptions":
        return SourceLoadOptions(
            write_mode=parse_write_mode_value(self.write_mode),
            dry_run=bool(self.dry_run),
            scan_options=normalize_metadata(self.scan_options),
            validate_before_write=bool(self.validate_before_write),
            validate_after_write=bool(self.validate_after_write),
            skip_invalid_candidates=bool(self.skip_invalid_candidates),
            write_documents=bool(self.write_documents),
            copy_assets=bool(self.copy_assets),
            create_archive=bool(self.create_archive),
            include_optional_documents=bool(self.include_optional_documents),
            include_generated_documents=bool(self.include_generated_documents),
            package_dir_pattern=clean_required_string(
                self.package_dir_pattern or DEFAULT_PACKAGE_DIR_PATTERN,
                "package_dir_pattern",
            ),
            atomic_writes=bool(self.atomic_writes),
            backup_existing=bool(self.backup_existing),
            fail_on_candidate_error=bool(self.fail_on_candidate_error),
            strict=bool(self.strict),
            metadata=normalize_metadata(self.metadata),
        )

    def to_file_write_options(self) -> Any:
        """Baut FileWriteOptions für creators/file_writer.py."""
        from ..creators.file_writer import FileWriteOptions

        normalized = self.normalized()

        return FileWriteOptions(
            write_mode=normalized.write_mode,
            dry_run=normalized.dry_run,
            atomic=normalized.atomic_writes,
            create_parent_directories=True,
            create_package_root=True,
            backup_existing=normalized.backup_existing,
            strict=normalized.strict,
        ).normalized()

    def to_package_creation_options(self) -> Any:
        """Baut PackageCreationOptions für creators/package_creator.py."""
        from ..creators.package_creator import PackageCreationOptions

        normalized = self.normalized()

        return PackageCreationOptions(
            write_mode=normalized.write_mode,
            dry_run=normalized.dry_run,
            validate_before_write=normalized.validate_before_write,
            validate_after_write=normalized.validate_after_write,
            write_documents=normalized.write_documents,
            copy_assets=False,
            create_directories=True,
            create_archive=normalized.create_archive,
            include_optional_documents=normalized.include_optional_documents,
            include_generated_documents=normalized.include_generated_documents,
            atomic_writes=normalized.atomic_writes,
            backup_existing=normalized.backup_existing,
            fail_on_validation_error=normalized.strict,
            fail_on_asset_copy_error=normalized.strict,
            strict=normalized.strict,
            metadata=normalized.metadata,
        ).normalized()

    def to_scan_options(self) -> Any:
        """Baut SourceScanOptions."""
        from .source_scanner import SourceScanOptions

        normalized = self.normalized()
        scan_options = dict(normalized.scan_options)

        return SourceScanOptions(
            scan_mode=scan_options.get("scan_mode", "direct_children"),
            max_depth=scan_options.get("max_depth", 12),
            encoding=scan_options.get("encoding", DEFAULT_ENCODING),
            include_hidden_directories=bool(scan_options.get("include_hidden_directories", False)),
            include_hidden_files=bool(scan_options.get("include_hidden_files", False)),
            follow_symlinks=bool(scan_options.get("follow_symlinks", False)),
            require_manifest=bool(scan_options.get("require_manifest", True)),
            require_modules=bool(scan_options.get("require_modules", True)),
            require_vplib_uid=bool(scan_options.get("require_vplib_uid", True)),
            require_core_documents=bool(scan_options.get("require_core_documents", False)),
            validate_schema=bool(scan_options.get("validate_schema", normalized.validate_before_write)),
            validate_semantics=bool(scan_options.get("validate_semantics", normalized.validate_before_write)),
            validate_assets=bool(scan_options.get("validate_assets", normalized.validate_before_write)),
            skip_invalid_candidates=bool(scan_options.get("skip_invalid_candidates", normalized.skip_invalid_candidates)),
            collect_all_errors=bool(scan_options.get("collect_all_errors", True)),
            strict=bool(scan_options.get("strict", normalized.strict)),
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "write_mode": normalized.write_mode,
            "dry_run": normalized.dry_run,
            "scan_options": dict(normalized.scan_options),
            "validate_before_write": normalized.validate_before_write,
            "validate_after_write": normalized.validate_after_write,
            "skip_invalid_candidates": normalized.skip_invalid_candidates,
            "write_documents": normalized.write_documents,
            "copy_assets": normalized.copy_assets,
            "create_archive": normalized.create_archive,
            "include_optional_documents": normalized.include_optional_documents,
            "include_generated_documents": normalized.include_generated_documents,
            "package_dir_pattern": normalized.package_dir_pattern,
            "atomic_writes": normalized.atomic_writes,
            "backup_existing": normalized.backup_existing,
            "fail_on_candidate_error": normalized.fail_on_candidate_error,
            "strict": normalized.strict,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SourceLoadTarget:
    """Ziel eines SourcePackageCandidate in der Creative Library."""

    library_catalog_root: Path
    package_dir_name: str
    package_root: Path
    vplib_uid: str | None = None
    package_id: str | None = None
    family_id: str | None = None
    family_slug: str | None = None
    object_kind: str | None = None
    archive_path: Path | None = None
    existed_before: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceLoadTarget":
        library_catalog_root = normalize_absolute_path(self.library_catalog_root, "library_catalog_root")
        package_dir_name = normalize_package_dir_name(self.package_dir_name)
        package_root = normalize_absolute_path(self.package_root, "package_root")
        archive_path = Path(self.archive_path).expanduser() if self.archive_path is not None else None
        vplib_uid = normalize_vplib_uid_safe(self.vplib_uid) or clean_optional_string(self.vplib_uid)
        metadata = normalize_metadata(self.metadata)

        if vplib_uid:
            metadata = {
                **metadata,
                MANIFEST_VPLIB_UID_FIELD: vplib_uid,
            }

        if not is_path_inside_root(package_root, library_catalog_root):
            raise SourceLoaderError("package_root must be inside library_catalog_root.")

        if archive_path is not None:
            if archive_path.suffix != ".vplib":
                archive_path = archive_path.with_suffix(".vplib")

        return SourceLoadTarget(
            library_catalog_root=library_catalog_root,
            package_dir_name=package_dir_name,
            package_root=package_root,
            vplib_uid=vplib_uid,
            package_id=clean_optional_string(self.package_id),
            family_id=clean_optional_string(self.family_id),
            family_slug=clean_optional_string(self.family_slug),
            object_kind=clean_optional_string(self.object_kind),
            archive_path=archive_path,
            existed_before=bool(self.existed_before),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "library_catalog_root": str(normalized.library_catalog_root),
            "package_dir_name": normalized.package_dir_name,
            "package_root": str(normalized.package_root),
            "vplib_uid": normalized.vplib_uid,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "family_slug": normalized.family_slug,
            "object_kind": normalized.object_kind,
            "archive_path": str(normalized.archive_path) if normalized.archive_path else None,
            "existed_before": normalized.existed_before,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SourceLoadItemResult:
    """Ergebnis eines geladenen SourcePackageCandidate."""

    source_dir: Path
    target: SourceLoadTarget | None = None
    candidate: Any | None = None
    document_bundle: Any | None = None
    validation_before_write: Any | None = None
    validation_after_write: Any | None = None
    document_write_result: Any | None = None
    asset_copy_result: Any | None = None
    archive_result: Any | None = None
    status: str = SourceLoadStatus.LOADED.value
    action: str = SourceLoadAction.CREATE.value
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceLoadItemResult":
        source_dir = normalize_absolute_path(self.source_dir, "source_dir")
        target = self.target.normalized() if self.target is not None else None
        status = parse_load_status_value(self.status)
        action = parse_load_action_value(self.action)
        error = clean_optional_string(self.error)
        metadata = normalize_metadata(self.metadata)
        uid = (
            get_source_candidate_vplib_uid(self.candidate)
            or get_bundle_vplib_uid(self.document_bundle)
            or (target.vplib_uid if target else None)
            or normalize_vplib_uid_safe(metadata.get(MANIFEST_VPLIB_UID_FIELD))
        )

        if uid:
            metadata = {
                **metadata,
                MANIFEST_VPLIB_UID_FIELD: uid,
            }

        if error:
            status = SourceLoadStatus.FAILED.value

        if action == SourceLoadAction.SKIP.value and status != SourceLoadStatus.FAILED.value:
            status = SourceLoadStatus.SKIPPED.value

        if any_result_failed(self.document_write_result, self.asset_copy_result, self.archive_result):
            status = SourceLoadStatus.FAILED.value

        if any_result_dry_run(self.document_write_result, self.asset_copy_result, self.archive_result) and status != SourceLoadStatus.FAILED.value:
            status = SourceLoadStatus.DRY_RUN.value

        return SourceLoadItemResult(
            source_dir=source_dir,
            target=target,
            candidate=self.candidate,
            document_bundle=self.document_bundle,
            validation_before_write=self.validation_before_write,
            validation_after_write=self.validation_after_write,
            document_write_result=self.document_write_result,
            asset_copy_result=self.asset_copy_result,
            archive_result=self.archive_result,
            status=status,
            action=action,
            error=error,
            metadata=metadata,
        )

    @property
    def ok(self) -> bool:
        return self.normalized().status in {
            SourceLoadStatus.LOADED.value,
            SourceLoadStatus.DRY_RUN.value,
            SourceLoadStatus.SKIPPED.value,
        }

    @property
    def failed(self) -> bool:
        return self.normalized().status == SourceLoadStatus.FAILED.value

    @property
    def vplib_uid(self) -> str | None:
        normalized = self.normalized()
        return normalize_vplib_uid_safe(normalized.metadata.get(MANIFEST_VPLIB_UID_FIELD))

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        uid = normalize_vplib_uid_safe(normalized.metadata.get(MANIFEST_VPLIB_UID_FIELD))

        return {
            "source_dir": str(normalized.source_dir),
            "status": normalized.status,
            "action": normalized.action,
            "ok": normalized.ok,
            "failed": normalized.failed,
            "vplib_uid": uid,
            "error": normalized.error,
            "target": normalized.target.to_dict() if normalized.target else None,
            "candidate": object_to_dict(normalized.candidate),
            "document_bundle": object_to_dict(normalized.document_bundle),
            "validation_before_write": object_to_dict(normalized.validation_before_write),
            "validation_after_write": object_to_dict(normalized.validation_after_write),
            "document_write_result": object_to_dict(normalized.document_write_result),
            "asset_copy_result": object_to_dict(normalized.asset_copy_result),
            "archive_result": object_to_dict(normalized.archive_result),
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SourceLoadResult:
    """Gesamtergebnis eines Source-Loads."""

    source_root: Path
    library_catalog_root: Path
    scan_result: Any | None = None
    item_results: tuple[SourceLoadItemResult, ...] = field(default_factory=tuple)
    options: SourceLoadOptions = field(default_factory=SourceLoadOptions)
    status: str = SourceLoadStatus.LOADED.value
    schema_version: str = SOURCE_LOADER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceLoadResult":
        source_root = normalize_absolute_path(self.source_root, "source_root")
        library_catalog_root = normalize_absolute_path(self.library_catalog_root, "library_catalog_root")
        item_results = sort_item_results(tuple(item.normalized() for item in self.item_results or ()))
        options = self.options.normalized()
        status = parse_load_status_value(self.status)
        metadata = normalize_metadata(self.metadata)
        uids = tuple(uid for uid in (item.vplib_uid for item in item_results) if uid)

        if uids:
            metadata = {
                **metadata,
                "vplib_uids": list(dict.fromkeys(uids)),
                "vplib_uid_count": len(set(uids)),
            }

        if not item_results:
            status = SourceLoadStatus.SKIPPED.value
        elif any(item.failed for item in item_results):
            status = SourceLoadStatus.PARTIAL.value
        elif all(item.status == SourceLoadStatus.SKIPPED.value for item in item_results):
            status = SourceLoadStatus.SKIPPED.value
        elif any(item.status == SourceLoadStatus.DRY_RUN.value for item in item_results):
            status = SourceLoadStatus.DRY_RUN.value
        else:
            status = SourceLoadStatus.LOADED.value

        return SourceLoadResult(
            source_root=source_root,
            library_catalog_root=library_catalog_root,
            scan_result=self.scan_result,
            item_results=item_results,
            options=options,
            status=status,
            schema_version=self.schema_version or SOURCE_LOADER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def ok(self) -> bool:
        return self.normalized().status in {
            SourceLoadStatus.LOADED.value,
            SourceLoadStatus.DRY_RUN.value,
            SourceLoadStatus.SKIPPED.value,
        }

    @property
    def failed(self) -> bool:
        return self.normalized().status == SourceLoadStatus.FAILED.value

    @property
    def item_count(self) -> int:
        return len(self.normalized().item_results)

    @property
    def loaded_count(self) -> int:
        return sum(1 for item in self.normalized().item_results if item.status == SourceLoadStatus.LOADED.value)

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.normalized().item_results if item.status == SourceLoadStatus.SKIPPED.value)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.normalized().item_results if item.failed)

    @property
    def vplib_uids(self) -> tuple[str, ...]:
        result: list[str] = []
        seen: set[str] = set()

        for item in self.normalized().item_results:
            uid = item.vplib_uid
            if not uid or uid in seen:
                continue
            result.append(uid)
            seen.add(uid)

        return tuple(result)

    def raise_for_errors(self) -> None:
        normalized = self.normalized()

        if normalized.failed_count:
            messages = [
                item.error or f"Failed to load {item.source_dir}"
                for item in normalized.item_results
                if item.failed
            ]
            raise SourceLoaderError("; ".join(messages) or "Source load failed.")

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "status": normalized.status,
            "ok": normalized.ok,
            "failed": normalized.failed,
            "source_root": str(normalized.source_root),
            "library_catalog_root": str(normalized.library_catalog_root),
            "vplib_uids": list(normalized.vplib_uids),
            "item_count": normalized.item_count,
            "loaded_count": normalized.loaded_count,
            "skipped_count": normalized.skipped_count,
            "failed_count": normalized.failed_count,
            "scan_result": object_to_dict(normalized.scan_result),
            "options": normalized.options.to_dict(),
            "item_results": [item.to_dict() for item in normalized.item_results],
            "metadata": dict(normalized.metadata),
        }


def load_source_root_to_library(
    *,
    source_root: str | Path,
    library_catalog_root: str | Path,
    options: SourceLoadOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SourceLoadResult:
    """Scannt einen Source-Root und lädt alle Kandidaten in die Creative Library."""
    normalized_options = normalize_options(options)
    root = normalize_absolute_path(source_root, "source_root")
    library_root = normalize_absolute_path(library_catalog_root, "library_catalog_root")

    try:
        from .source_scanner import scan_source_root

        scan_result = scan_source_root(
            root,
            options=normalized_options.to_scan_options(),
            metadata={
                "source": "source_loader",
                **dict(metadata or {}),
            },
        ).normalized()

        return load_scan_result_to_library(
            scan_result=scan_result,
            library_catalog_root=library_root,
            options=normalized_options,
            metadata=metadata,
        ).normalized()
    except Exception as exc:
        if normalized_options.strict:
            raise SourceLoaderError(f"Could not load source root to library: {exc}") from exc

        return SourceLoadResult(
            source_root=root,
            library_catalog_root=library_root,
            scan_result=None,
            item_results=(
                SourceLoadItemResult(
                    source_dir=root,
                    status=SourceLoadStatus.FAILED.value,
                    action=SourceLoadAction.FAIL.value,
                    error=str(exc),
                ),
            ),
            options=normalized_options,
            status=SourceLoadStatus.FAILED.value,
            metadata=dict(metadata or {}),
        ).normalized()


def load_scan_result_to_library(
    *,
    scan_result: Any,
    library_catalog_root: str | Path,
    options: SourceLoadOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SourceLoadResult:
    """Lädt alle Kandidaten aus einem SourceScanResult in die Creative Library."""
    normalized_options = normalize_options(options)
    normalized_scan = normalize_scan_result(scan_result)
    library_root = normalize_absolute_path(library_catalog_root, "library_catalog_root")
    item_results: list[SourceLoadItemResult] = []

    try:
        if not normalized_options.dry_run:
            library_root.mkdir(parents=True, exist_ok=True)

        for candidate in normalized_scan.candidates:
            normalized_candidate = normalize_source_candidate(candidate)
            uid = get_source_candidate_vplib_uid(normalized_candidate)

            try:
                result = load_source_candidate_to_library(
                    candidate=normalized_candidate,
                    library_catalog_root=library_root,
                    options=normalized_options,
                    metadata={
                        MANIFEST_VPLIB_UID_FIELD: uid,
                    } if uid else None,
                ).normalized()
                item_results.append(result)

                if result.failed and normalized_options.fail_on_candidate_error:
                    break
            except Exception as exc:
                if normalized_options.fail_on_candidate_error or normalized_options.strict:
                    raise

                item_results.append(
                    SourceLoadItemResult(
                        source_dir=getattr(normalized_candidate, "source_dir", library_root),
                        candidate=normalized_candidate,
                        status=SourceLoadStatus.FAILED.value,
                        action=SourceLoadAction.FAIL.value,
                        error=str(exc),
                        metadata={
                            MANIFEST_VPLIB_UID_FIELD: uid,
                        } if uid else {},
                    ).normalized()
                )

        return SourceLoadResult(
            source_root=normalized_scan.source_root,
            library_catalog_root=library_root,
            scan_result=normalized_scan,
            item_results=tuple(item_results),
            options=normalized_options,
            metadata={
                "source": "scan_result",
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        if normalized_options.strict:
            raise SourceLoaderError(f"Could not load scan result to library: {exc}") from exc

        return SourceLoadResult(
            source_root=normalized_scan.source_root,
            library_catalog_root=library_root,
            scan_result=normalized_scan,
            item_results=tuple(item_results),
            options=normalized_options,
            status=SourceLoadStatus.PARTIAL.value,
            metadata={
                "source": "scan_result",
                "error": str(exc),
                **dict(metadata or {}),
            },
        ).normalized()


def load_source_candidate_to_library(
    *,
    candidate: Any,
    library_catalog_root: str | Path,
    options: SourceLoadOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SourceLoadItemResult:
    """Lädt einen einzelnen SourcePackageCandidate in die Creative Library."""
    normalized_options = normalize_options(options)
    normalized_candidate = normalize_source_candidate(candidate)
    library_root = normalize_absolute_path(library_catalog_root, "library_catalog_root")
    uid = get_source_candidate_vplib_uid(normalized_candidate)
    item_metadata = {
        **dict(metadata or {}),
        **({MANIFEST_VPLIB_UID_FIELD: uid} if uid else {}),
    }

    try:
        target = build_load_target_for_candidate(
            candidate=normalized_candidate,
            library_catalog_root=library_root,
            options=normalized_options,
        ).normalized()

        action = determine_load_action(
            target=target,
            candidate=normalized_candidate,
            options=normalized_options,
        )

        if action == SourceLoadAction.SKIP.value:
            return SourceLoadItemResult(
                source_dir=normalized_candidate.source_dir,
                target=target,
                candidate=normalized_candidate,
                status=SourceLoadStatus.SKIPPED.value,
                action=SourceLoadAction.SKIP.value,
                metadata={
                    "reason": "target_exists",
                    **item_metadata,
                },
            ).normalized()

        if action == SourceLoadAction.FAIL.value:
            return SourceLoadItemResult(
                source_dir=normalized_candidate.source_dir,
                target=target,
                candidate=normalized_candidate,
                status=SourceLoadStatus.FAILED.value,
                action=SourceLoadAction.FAIL.value,
                error=f"Target already exists: {target.package_root}",
                metadata=item_metadata,
            ).normalized()

        if normalized_options.skip_invalid_candidates and not normalized_candidate.valid:
            return SourceLoadItemResult(
                source_dir=normalized_candidate.source_dir,
                target=target,
                candidate=normalized_candidate,
                status=SourceLoadStatus.SKIPPED.value,
                action=SourceLoadAction.SKIP.value,
                metadata={
                    "reason": "invalid_candidate",
                    **item_metadata,
                },
            ).normalized()

        document_bundle = normalized_candidate.to_document_bundle()
        bundle_uid = get_bundle_vplib_uid(document_bundle) or uid

        if bundle_uid:
            item_metadata[MANIFEST_VPLIB_UID_FIELD] = bundle_uid

        validation_before = None
        if normalized_options.validate_before_write:
            validation_before = validate_candidate_before_write(
                candidate=normalized_candidate,
                document_bundle=document_bundle,
                options=normalized_options,
            )

            if not validation_result_is_valid(validation_before) and normalized_options.strict:
                return SourceLoadItemResult(
                    source_dir=normalized_candidate.source_dir,
                    target=target,
                    candidate=normalized_candidate,
                    document_bundle=document_bundle,
                    validation_before_write=validation_before,
                    status=SourceLoadStatus.FAILED.value,
                    action=action,
                    error="Candidate failed validation before write.",
                    metadata=item_metadata,
                ).normalized()

        document_write_result = None
        if normalized_options.write_documents:
            document_write_result = write_candidate_documents(
                candidate=normalized_candidate,
                target=target,
                document_bundle=document_bundle,
                options=normalized_options,
            )

        asset_copy_result = None
        if normalized_options.copy_assets:
            asset_copy_result = copy_candidate_assets(
                candidate=normalized_candidate,
                target=target,
                options=normalized_options,
            )

        archive_result = None
        if normalized_options.create_archive:
            archive_result = create_candidate_archive(
                target=target,
                options=normalized_options,
            )

        validation_after = None
        if normalized_options.validate_after_write:
            validation_after = validate_candidate_after_write(
                candidate=normalized_candidate,
                document_bundle=document_bundle,
                options=normalized_options,
            )

        return SourceLoadItemResult(
            source_dir=normalized_candidate.source_dir,
            target=target,
            candidate=normalized_candidate,
            document_bundle=document_bundle,
            validation_before_write=validation_before,
            validation_after_write=validation_after,
            document_write_result=document_write_result,
            asset_copy_result=asset_copy_result,
            archive_result=archive_result,
            status=SourceLoadStatus.DRY_RUN.value if normalized_options.dry_run else SourceLoadStatus.LOADED.value,
            action=action,
            metadata={
                "source": "load_source_candidate_to_library",
                **item_metadata,
            },
        ).normalized()
    except Exception as exc:
        if normalized_options.strict:
            raise SourceLoaderError(f"Could not load source candidate: {exc}") from exc

        return SourceLoadItemResult(
            source_dir=normalized_candidate.source_dir,
            candidate=normalized_candidate,
            status=SourceLoadStatus.FAILED.value,
            action=SourceLoadAction.FAIL.value,
            error=str(exc),
            metadata=item_metadata,
        ).normalized()


def build_load_target_for_candidate(
    *,
    candidate: Any,
    library_catalog_root: str | Path,
    options: SourceLoadOptions | Mapping[str, Any] | None = None,
) -> SourceLoadTarget:
    """Baut das Zielverzeichnis für einen Candidate."""
    normalized_options = normalize_options(options)
    normalized_candidate = normalize_source_candidate(candidate)
    library_root = normalize_absolute_path(library_catalog_root, "library_catalog_root")

    package_dir_name = render_package_dir_name(
        candidate=normalized_candidate,
        pattern=normalized_options.package_dir_pattern,
    )
    package_root = library_root / package_dir_name
    archive_path = package_root.with_suffix(".vplib")
    uid = get_source_candidate_vplib_uid(normalized_candidate)

    return SourceLoadTarget(
        library_catalog_root=library_root,
        package_dir_name=package_dir_name,
        package_root=package_root,
        vplib_uid=uid,
        package_id=normalized_candidate.package_id,
        family_id=normalized_candidate.family_id,
        family_slug=normalized_candidate.family_slug,
        object_kind=normalized_candidate.object_kind,
        archive_path=archive_path,
        existed_before=package_root.exists(),
        metadata={
            "source_dir": str(normalized_candidate.source_dir),
            **({MANIFEST_VPLIB_UID_FIELD: uid} if uid else {}),
        },
    ).normalized()


def determine_load_action(
    *,
    target: SourceLoadTarget,
    candidate: Any,
    options: SourceLoadOptions,
) -> str:
    """Bestimmt create/update/skip/fail für einen Candidate."""
    normalized_target = target.normalized()
    normalized_options = options.normalized()

    if not normalized_target.existed_before:
        return SourceLoadAction.CREATE.value

    if normalized_options.write_mode == SourceLoadWriteMode.SKIP.value:
        return SourceLoadAction.SKIP.value

    if normalized_options.write_mode == SourceLoadWriteMode.OVERWRITE.value:
        return SourceLoadAction.UPDATE.value

    return SourceLoadAction.FAIL.value


def write_candidate_documents(
    *,
    candidate: Any,
    target: SourceLoadTarget,
    document_bundle: Any,
    options: SourceLoadOptions,
) -> Any:
    """Schreibt Candidate-Dokumente in den Library-Katalog."""
    from ..creators.file_writer import write_document_bundle_to_package

    normalized_candidate = normalize_source_candidate(candidate)
    normalized_target = target.normalized()
    uid = (
        get_bundle_vplib_uid(document_bundle)
        or normalized_target.vplib_uid
        or get_source_candidate_vplib_uid(normalized_candidate)
    )

    return write_document_bundle_to_package(
        package_root=normalized_target.package_root,
        bundle=document_bundle,
        options=options.to_file_write_options(),
        metadata={
            "source": "source_loader.documents",
            "source_dir": str(normalized_candidate.source_dir),
            "vplib_uid": uid,
            "package_id": normalized_target.package_id,
        },
    ).normalized()


def copy_candidate_assets(
    *,
    candidate: Any,
    target: SourceLoadTarget,
    options: SourceLoadOptions,
) -> Any:
    """Kopiert Nicht-JSON-Dateien aus Source-Package in das Library-Ziel."""
    from ..creators.file_writer import FileCopyRequest, write_copy_requests

    normalized_candidate = normalize_source_candidate(candidate)
    normalized_target = target.normalized()
    uid = normalized_target.vplib_uid or get_source_candidate_vplib_uid(normalized_candidate)
    copy_requests = tuple(
        FileCopyRequest(
            source_path=asset.source_path,
            relative_path=asset.relative_path,
            required=False,
            metadata={
                "source": "source_loader.assets",
                "vplib_uid": uid,
            },
        ).normalized()
        for asset in discover_candidate_asset_files(normalized_candidate)
    )

    return write_copy_requests(
        package_root=normalized_target.package_root,
        requests=copy_requests,
        options=options.to_file_write_options(),
        metadata={
            "source": "source_loader.assets",
            "vplib_uid": uid,
            "asset_count": len(copy_requests),
            "source_dir": str(normalized_candidate.source_dir),
        },
    ).normalized()


def create_candidate_archive(
    *,
    target: SourceLoadTarget,
    options: SourceLoadOptions,
) -> Any:
    """Erzeugt .vplib Archiv für einen geladenen Candidate."""
    from ..creators.archive_creator import create_vplib_archive_from_package

    normalized_target = target.normalized()

    return create_vplib_archive_from_package(
        package_root=normalized_target.package_root,
        archive_path=normalized_target.archive_path,
        dry_run=options.normalized().dry_run,
        overwrite=options.normalized().write_mode == SourceLoadWriteMode.OVERWRITE.value,
        metadata={
            "source": "source_loader.archive",
            "vplib_uid": normalized_target.vplib_uid,
            "package_id": normalized_target.package_id,
        },
    ).normalized()


def validate_candidate_before_write(
    *,
    candidate: Any,
    document_bundle: Any,
    options: SourceLoadOptions,
) -> Any:
    """Validiert Candidate-Bundle vor dem Schreiben."""
    from ..validators.package_validator import PackageValidationOptions, validate_package_document_bundle

    normalized_candidate = normalize_source_candidate(candidate)
    normalized_options = options.normalized()
    uid = get_bundle_vplib_uid(document_bundle) or get_source_candidate_vplib_uid(normalized_candidate)

    return validate_package_document_bundle(
        document_bundle,
        options=PackageValidationOptions(
            mode="strict" if normalized_options.strict else "normal",
            validate_schema=True,
            validate_semantics=True,
            validate_assets=True,
            validate_package_plan=False,
            validate_vplib_uid=True,
            strict=normalized_options.strict,
        ),
        metadata={
            "source": "source_loader.before_write",
            "source_dir": str(normalized_candidate.source_dir),
            "vplib_uid": uid,
        },
    ).normalized()


def validate_candidate_after_write(
    *,
    candidate: Any,
    document_bundle: Any,
    options: SourceLoadOptions,
) -> Any:
    """Validiert Candidate-Bundle nach dem Schreiben."""
    from ..validators.package_validator import PackageValidationOptions, validate_package_document_bundle

    normalized_candidate = normalize_source_candidate(candidate)
    normalized_options = options.normalized()
    uid = get_bundle_vplib_uid(document_bundle) or get_source_candidate_vplib_uid(normalized_candidate)

    return validate_package_document_bundle(
        document_bundle,
        options=PackageValidationOptions(
            mode="strict" if normalized_options.strict else "normal",
            validate_schema=True,
            validate_semantics=True,
            validate_assets=True,
            validate_package_plan=False,
            validate_vplib_uid=True,
            strict=normalized_options.strict,
        ),
        metadata={
            "source": "source_loader.after_write",
            "source_dir": str(normalized_candidate.source_dir),
            "vplib_uid": uid,
        },
    ).normalized()


@dataclass(frozen=True, slots=True)
class CandidateAssetFile:
    """Eine zu kopierende Nicht-JSON-Datei eines Source-Candidates."""

    source_path: Path
    relative_path: str
    size_bytes: int = 0

    def normalized(self) -> "CandidateAssetFile":
        source_path = normalize_absolute_path(self.source_path, "source_path")
        relative_path = normalize_package_relative_path(self.relative_path)
        size_bytes = normalize_non_negative_int(self.size_bytes, "size_bytes")

        return CandidateAssetFile(
            source_path=source_path,
            relative_path=relative_path,
            size_bytes=size_bytes,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "source_path": str(normalized.source_path),
            "relative_path": normalized.relative_path,
            "size_bytes": normalized.size_bytes,
        }


def discover_candidate_asset_files(candidate: Any) -> tuple[CandidateAssetFile, ...]:
    """Findet alle zu kopierenden Nicht-JSON-Dateien eines Candidates."""
    normalized_candidate = normalize_source_candidate(candidate)
    source_dir = normalized_candidate.source_dir

    files: list[CandidateAssetFile] = []

    for path in sorted(source_dir.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue

        if not should_copy_asset_file(path, source_dir=source_dir):
            continue

        relative_path = normalize_source_asset_relative_path(path, source_dir)

        files.append(
            CandidateAssetFile(
                source_path=path,
                relative_path=relative_path,
                size_bytes=path.stat().st_size,
            ).normalized()
        )

    return tuple(files)


def should_copy_asset_file(path: Path, *, source_dir: Path) -> bool:
    """Prüft, ob eine Datei als Asset/Neben-Datei kopiert werden soll."""
    if path.name in IGNORED_COPY_FILE_NAMES:
        return False

    if path.suffix.lower() == JSON_DOCUMENT_SUFFIX:
        return False

    if path.suffix.lower() in IGNORED_COPY_SUFFIXES:
        return False

    for part in path.relative_to(source_dir).parts:
        if part in IGNORED_COPY_DIRECTORY_NAMES:
            return False
        if part.startswith("."):
            return False

    return True


def normalize_source_asset_relative_path(path: Path, source_dir: Path) -> str:
    """Normalisiert Asset-Pfad relativ zum Source-Package."""
    try:
        relative = path.resolve().relative_to(source_dir.resolve())
    except Exception as exc:
        raise SourceLoaderError(f"Asset file {path} is outside source_dir {source_dir}.") from exc

    return normalize_package_relative_path(PurePosixPath(*relative.parts).as_posix())


def render_package_dir_name(*, candidate: Any, pattern: str) -> str:
    """Rendert package_dir_name aus Candidate-Metadaten."""
    normalized_candidate = normalize_source_candidate(candidate)

    values = {
        "vplib_uid": get_source_candidate_vplib_uid(normalized_candidate) or "",
        "package_id": normalized_candidate.package_id or normalized_candidate.family_id or normalized_candidate.source_dir.name,
        "family_id": normalized_candidate.family_id or normalized_candidate.package_id or normalized_candidate.source_dir.name,
        "family_slug": normalized_candidate.family_slug or normalized_candidate.family_id or normalized_candidate.package_id or normalized_candidate.source_dir.name,
        "family_name": normalized_candidate.family_name or normalized_candidate.family_slug or normalized_candidate.source_dir.name,
        "object_kind": normalized_candidate.object_kind or "unknown",
        "source_name": normalized_candidate.source_dir.name,
    }

    try:
        rendered = pattern.format(**values)
    except Exception as exc:
        raise SourceLoaderError(f"Could not render package_dir_pattern {pattern!r}: {exc}") from exc

    return normalize_package_dir_name(rendered)


def normalize_scan_result(value: Any) -> Any:
    """Normalisiert SourceScanResult-ähnliche Werte."""
    try:
        from .source_scanner import SourceScanResult

        if isinstance(value, SourceScanResult):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise SourceLoaderError("SourceScanResult value is required.")
    except SourceLoaderError:
        raise
    except Exception as exc:
        raise SourceLoaderError(f"Invalid SourceScanResult: {exc}") from exc


def normalize_source_candidate(value: Any) -> Any:
    """Normalisiert SourcePackageCandidate-ähnliche Werte."""
    try:
        from .source_scanner import SourcePackageCandidate

        if isinstance(value, SourcePackageCandidate):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise SourceLoaderError("SourcePackageCandidate value is required.")
    except SourceLoaderError:
        raise
    except Exception as exc:
        raise SourceLoaderError(f"Invalid SourcePackageCandidate: {exc}") from exc


def get_source_candidate_vplib_uid(candidate: Any | None) -> str | None:
    """Liest `vplib_uid` defensiv aus einem SourcePackageCandidate-artigen Objekt."""
    if candidate is None:
        return None

    try:
        normalized = candidate.normalized() if hasattr(candidate, "normalized") else candidate
        uid = normalize_vplib_uid_safe(getattr(normalized, MANIFEST_VPLIB_UID_FIELD, None))
        if uid:
            return uid

        metadata = getattr(normalized, "metadata", None)
        if isinstance(metadata, Mapping):
            uid = normalize_vplib_uid_safe(metadata.get(MANIFEST_VPLIB_UID_FIELD))
            if uid:
                return uid
    except Exception:
        pass

    if isinstance(candidate, Mapping):
        uid = normalize_vplib_uid_safe(candidate.get(MANIFEST_VPLIB_UID_FIELD))
        if uid:
            return uid

        metadata = candidate.get("metadata")
        if isinstance(metadata, Mapping):
            uid = normalize_vplib_uid_safe(metadata.get(MANIFEST_VPLIB_UID_FIELD))
            if uid:
                return uid

    return None


def get_bundle_vplib_uid(bundle: Any | None) -> str | None:
    """Liest `vplib_uid` defensiv aus einem DocumentBundle-artigen Objekt."""
    if bundle is None:
        return None

    try:
        normalized_bundle = bundle.normalized() if hasattr(bundle, "normalized") else bundle
        uid = normalize_vplib_uid_safe(getattr(normalized_bundle, MANIFEST_VPLIB_UID_FIELD, None))
        if uid:
            return uid

        if hasattr(normalized_bundle, "get_document"):
            manifest = normalized_bundle.get_document(MANIFEST_DOCUMENT_PATH)
            uid = get_manifest_vplib_uid(manifest)
            if uid:
                return uid

        if hasattr(normalized_bundle, "to_documents"):
            documents = normalized_bundle.to_documents()
            if isinstance(documents, Mapping):
                uid = get_manifest_vplib_uid(documents.get(MANIFEST_DOCUMENT_PATH))
                if uid:
                    return uid
    except Exception:
        pass

    if isinstance(bundle, Mapping):
        uid = normalize_vplib_uid_safe(bundle.get(MANIFEST_VPLIB_UID_FIELD))
        if uid:
            return uid

        uid = get_manifest_vplib_uid(bundle.get(MANIFEST_DOCUMENT_PATH))
        if uid:
            return uid

    return None


def get_manifest_vplib_uid(manifest: Any | None) -> str | None:
    """Liest `vplib_uid` defensiv aus einem Manifest-Mapping."""
    if not isinstance(manifest, Mapping):
        return None

    try:
        from ..vplib_id_service import get_vplib_uid_from_mapping

        return get_vplib_uid_from_mapping(manifest)
    except Exception:
        return normalize_vplib_uid_safe(manifest.get(MANIFEST_VPLIB_UID_FIELD))


def normalize_vplib_uid_safe(value: Any) -> str | None:
    """Normalisiert `vplib_uid` defensiv."""
    try:
        from ..vplib_id_service import normalize_vplib_uid

        return normalize_vplib_uid(value)
    except Exception:
        return None


def validation_result_is_valid(value: Any | None) -> bool:
    """Prüft, ob ein ValidationResult-artiges Objekt gültig ist."""
    if value is None:
        return True

    try:
        return bool(value.valid)
    except Exception:
        pass

    try:
        return bool(value.is_valid)
    except Exception:
        pass

    if isinstance(value, Mapping):
        return bool(value.get("valid", False))

    return False


def any_result_failed(*values: Any | None) -> bool:
    """Prüft, ob ein Result-Objekt fehlgeschlagen ist."""
    for value in values:
        if value is None:
            continue

        try:
            if bool(value.failed):
                return True
        except Exception:
            pass

        if isinstance(value, Mapping) and bool(value.get("failed", False)):
            return True

    return False


def any_result_dry_run(*values: Any | None) -> bool:
    """Prüft, ob ein Result-Objekt Dry-Run ist."""
    for value in values:
        if value is None:
            continue

        try:
            options = getattr(value, "options", None)
            if options is not None and bool(options.dry_run):
                return True
        except Exception:
            pass

        if isinstance(value, Mapping) and bool(value.get("dry_run", False)):
            return True

    return False


def object_to_dict(value: Any | None) -> Any:
    """Serialisiert bekannte Objekte robust."""
    if value is None:
        return None

    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            return str(value)

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    return str(value)


def is_path_inside_root(path: Path, root: Path) -> bool:
    """Prüft, ob path innerhalb root liegt."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


def normalize_options(options: SourceLoadOptions | Mapping[str, Any] | None) -> SourceLoadOptions:
    """Normalisiert SourceLoadOptions."""
    if options is None:
        return SourceLoadOptions().normalized()

    if isinstance(options, SourceLoadOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return SourceLoadOptions(
            write_mode=options.get("write_mode", SourceLoadWriteMode.FAIL.value),
            dry_run=bool(options.get("dry_run", False)),
            scan_options=dict(options.get("scan_options", {}) or {}),
            validate_before_write=bool(options.get("validate_before_write", True)),
            validate_after_write=bool(options.get("validate_after_write", False)),
            skip_invalid_candidates=bool(options.get("skip_invalid_candidates", True)),
            write_documents=bool(options.get("write_documents", True)),
            copy_assets=bool(options.get("copy_assets", True)),
            create_archive=bool(options.get("create_archive", False)),
            include_optional_documents=bool(options.get("include_optional_documents", True)),
            include_generated_documents=bool(options.get("include_generated_documents", True)),
            package_dir_pattern=options.get("package_dir_pattern", DEFAULT_PACKAGE_DIR_PATTERN),
            atomic_writes=bool(options.get("atomic_writes", True)),
            backup_existing=bool(options.get("backup_existing", False)),
            fail_on_candidate_error=bool(options.get("fail_on_candidate_error", False)),
            strict=bool(options.get("strict", True)),
            metadata=dict(options.get("metadata", {}) or {}),
        ).normalized()

    raise SourceLoaderError("options must be SourceLoadOptions, mapping or None.")


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert lokalen Pfad."""
    try:
        if value is None:
            raise SourceLoaderError(f"{field_name} is required.")

        return Path(value).expanduser()
    except SourceLoaderError:
        raise
    except Exception as exc:
        raise SourceLoaderError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_package_relative_path(value: Any) -> str:
    """Normalisiert package-relativen POSIX-Pfad."""
    raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

    if raw.startswith("/"):
        raise SourceLoaderError(f"relative_path must not be absolute: {value!r}")

    path = PurePosixPath(raw)
    parts = tuple(part for part in path.parts if part not in {"", "."})

    if not parts:
        raise SourceLoaderError("relative_path is required.")

    if any(part == ".." for part in parts):
        raise SourceLoaderError(f"relative_path must not contain parent traversal: {value!r}")

    return PurePosixPath(*parts).as_posix()


def normalize_package_dir_name(value: Any) -> str:
    """Normalisiert Directory-Name eines Library-Packages."""
    raw = clean_required_string(value, "package_dir_name")
    safe = (
        raw.strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )

    safe = "_".join(part for part in safe.split("_") if part)

    if not safe:
        raise SourceLoaderError("package_dir_name is required.")

    if safe in {".", ".."}:
        raise SourceLoaderError("package_dir_name must not be '.' or '..'.")

    return safe


@lru_cache(maxsize=128)
def parse_load_status_value(value: Any) -> str:
    """Parst SourceLoadStatus."""
    try:
        if isinstance(value, SourceLoadStatus):
            return value.value

        raw = normalize_enum_key(value)
        return SourceLoadStatus(raw).value
    except Exception as exc:
        raise SourceLoaderError(f"Invalid source load status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_load_action_value(value: Any) -> str:
    """Parst SourceLoadAction."""
    try:
        if isinstance(value, SourceLoadAction):
            return value.value

        raw = normalize_enum_key(value)
        return SourceLoadAction(raw).value
    except Exception as exc:
        raise SourceLoaderError(f"Invalid source load action {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_write_mode_value(value: Any) -> str:
    """Parst SourceLoadWriteMode."""
    try:
        if isinstance(value, SourceLoadWriteMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "fail": SourceLoadWriteMode.FAIL.value,
            "error": SourceLoadWriteMode.FAIL.value,
            "skip": SourceLoadWriteMode.SKIP.value,
            "ignore": SourceLoadWriteMode.SKIP.value,
            "overwrite": SourceLoadWriteMode.OVERWRITE.value,
            "replace": SourceLoadWriteMode.OVERWRITE.value,
            "update": SourceLoadWriteMode.OVERWRITE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return SourceLoadWriteMode(raw).value
    except Exception as exc:
        raise SourceLoaderError(f"Invalid source load write_mode {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise SourceLoaderError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except SourceLoaderError:
        raise
    except Exception as exc:
        raise SourceLoaderError(f"Invalid enum value {value!r}.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise SourceLoaderError(f"{field_name} must be an integer.")

        number = int(value)

        if number < 0:
            raise SourceLoaderError(f"{field_name} must be >= 0.")

        return number
    except SourceLoaderError:
        raise
    except Exception as exc:
        raise SourceLoaderError(f"{field_name} must be a non-negative integer.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise SourceLoaderError("metadata must be a mapping.")

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


def sort_item_results(values: Iterable[SourceLoadItemResult]) -> tuple[SourceLoadItemResult, ...]:
    """Sortiert ItemResults stabil."""
    return tuple(
        sorted(
            (value.normalized() for value in values or ()),
            key=lambda item: (
                item.vplib_uid or "",
                item.target.package_id if item.target else "",
                item.target.family_id if item.target else "",
                str(item.source_dir),
            ),
        )
    )


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise SourceLoaderError(f"{field_name} is required.")

        return cleaned
    except SourceLoaderError:
        raise
    except Exception as exc:
        raise SourceLoaderError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_source_loader_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_load_status_value.cache_clear()
    parse_load_action_value.cache_clear()
    parse_write_mode_value.cache_clear()


__all__ = [
    "DEFAULT_ENCODING",
    "DEFAULT_PACKAGE_DIR_PATTERN",
    "IGNORED_COPY_DIRECTORY_NAMES",
    "IGNORED_COPY_FILE_NAMES",
    "IGNORED_COPY_SUFFIXES",
    "JSON_DOCUMENT_SUFFIX",
    "MANIFEST_DOCUMENT_PATH",
    "MANIFEST_VPLIB_UID_FIELD",
    "SOURCE_LOADER_SCHEMA_VERSION",
    "CandidateAssetFile",
    "SourceLoadAction",
    "SourceLoadItemResult",
    "SourceLoadOptions",
    "SourceLoadResult",
    "SourceLoadStatus",
    "SourceLoadTarget",
    "SourceLoadWriteMode",
    "SourceLoaderError",
    "any_result_dry_run",
    "any_result_failed",
    "build_load_target_for_candidate",
    "clean_optional_string",
    "clean_required_string",
    "clear_source_loader_caches",
    "copy_candidate_assets",
    "create_candidate_archive",
    "determine_load_action",
    "discover_candidate_asset_files",
    "get_bundle_vplib_uid",
    "get_manifest_vplib_uid",
    "get_source_candidate_vplib_uid",
    "is_path_inside_root",
    "load_scan_result_to_library",
    "load_source_candidate_to_library",
    "load_source_root_to_library",
    "normalize_absolute_path",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_int",
    "normalize_options",
    "normalize_package_dir_name",
    "normalize_package_relative_path",
    "normalize_scan_result",
    "normalize_source_asset_relative_path",
    "normalize_source_candidate",
    "normalize_vplib_uid_safe",
    "object_to_dict",
    "parse_load_action_value",
    "parse_load_status_value",
    "parse_write_mode_value",
    "render_package_dir_name",
    "should_copy_asset_file",
    "sort_item_results",
    "validate_candidate_after_write",
    "validate_candidate_before_write",
    "validation_result_is_valid",
    "write_candidate_documents",
]