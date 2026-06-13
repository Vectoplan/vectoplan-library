# services/vectoplan-library/src/vplib/sources/source_scanner.py
"""
Source scanner for the VPLIB package engine.

Diese Datei scannt einen Source-Ordner mit vorbereiteten VPLIB-Objekten.

Rolle dieser Datei:

    sources/
      wall_24/
        vplib.manifest.json
        vplib.modules.json
        family/identity.json
        variants/default.json
        editor/placement.json
        ...
      chair_basic/
        ...

    -> SourceScanResult
    -> SourcePackageCandidate
    -> DocumentBundle
    -> later: creative library import/update
    -> later: database publication / creative-library sync

Diese Datei:
- liest Source-Verzeichnisse
- erkennt VPLIB-Package-Kandidaten
- lädt JSON-Dokumente
- liest `vplib_uid` aus `vplib.manifest.json`
- prüft package-relative Pfade
- kann optional Schema/Semantik/Asset/Package-Validierung ausführen
- erkennt doppelte `vplib_uid`
- erzeugt DocumentBundle-kompatible Dokument-Mappings

Wichtig für die neue DB-/Creative-Library-Synchronisation:
- `vplib_uid` ist die unveränderliche technische ID eines VPLIB-Packages.
- `vplib_uid` muss aus `vplib.manifest.json` kommen.
- Der Scanner erzeugt keine neuen IDs.
- Fehlende/ungültige `vplib_uid` macht einen Kandidaten invalid.
- Doppelte `vplib_uid` im selben Scan machen den Scan partiell/invalid.
- Die spätere Datenbank übernimmt diese ID nur.

Diese Datei schreibt keine Dateien.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping


SOURCE_SCANNER_SCHEMA_VERSION: Final[str] = "vplib.source_scanner.v1"
DEFAULT_MAX_DEPTH: Final[int] = 12
DEFAULT_ENCODING: Final[str] = "utf-8"

MANIFEST_DOCUMENT_PATH: Final[str] = "vplib.manifest.json"
MODULES_DOCUMENT_PATH: Final[str] = "vplib.modules.json"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"

ROOT_MARKER_DOCUMENTS: Final[tuple[str, ...]] = (
    MANIFEST_DOCUMENT_PATH,
    MODULES_DOCUMENT_PATH,
)

CORE_REQUIRED_DOCUMENTS: Final[tuple[str, ...]] = (
    MANIFEST_DOCUMENT_PATH,
    MODULES_DOCUMENT_PATH,
    "family/identity.json",
    "family/classification.json",
    "variants/index.json",
    "variants/default.json",
    "editor/inventory.json",
    "editor/placement.json",
    "manufacturer/contract.json",
)

IGNORED_DIRECTORY_NAMES: Final[tuple[str, ...]] = (
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "node_modules",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
)

IGNORED_FILE_NAMES: Final[tuple[str, ...]] = (
    ".DS_Store",
    "Thumbs.db",
)

ALLOWED_DOCUMENT_SUFFIXES: Final[tuple[str, ...]] = (
    ".json",
)


class SourceScannerError(ValueError):
    """Wird ausgelöst, wenn der Source-Scanner selbst fehlschlägt."""


class SourceCandidateStatus(str, Enum):
    """Status eines SourcePackageCandidate."""

    READY = "ready"
    INVALID = "invalid"
    PARTIAL = "partial"
    SKIPPED = "skipped"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class SourceScanStatus(str, Enum):
    """Status eines SourceScanResult."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    EMPTY = "empty"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


class SourceIssueSeverity(str, Enum):
    """Schweregrad eines Source-Issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class SourceIssueCode(str, Enum):
    """Issue-Codes für Source-Scanning."""

    UNKNOWN = "VPLIB_SOURCE_UNKNOWN"
    SOURCE_ROOT_MISSING = "VPLIB_SOURCE_ROOT_MISSING"
    SOURCE_ROOT_NOT_DIRECTORY = "VPLIB_SOURCE_ROOT_NOT_DIRECTORY"
    INVALID_SOURCE_DIRECTORY = "VPLIB_SOURCE_INVALID_SOURCE_DIRECTORY"
    INVALID_PACKAGE_PATH = "VPLIB_SOURCE_INVALID_PACKAGE_PATH"
    INVALID_JSON = "VPLIB_SOURCE_INVALID_JSON"
    MISSING_MANIFEST = "VPLIB_SOURCE_MISSING_MANIFEST"
    MISSING_MODULES = "VPLIB_SOURCE_MISSING_MODULES"
    MISSING_REQUIRED_DOCUMENT = "VPLIB_SOURCE_MISSING_REQUIRED_DOCUMENT"
    MISSING_VPLIB_UID = "VPLIB_SOURCE_MISSING_VPLIB_UID"
    INVALID_VPLIB_UID = "VPLIB_SOURCE_INVALID_VPLIB_UID"
    DUPLICATE_VPLIB_UID = "VPLIB_SOURCE_DUPLICATE_VPLIB_UID"
    DUPLICATE_PACKAGE_ID = "VPLIB_SOURCE_DUPLICATE_PACKAGE_ID"
    DUPLICATE_FAMILY_ID = "VPLIB_SOURCE_DUPLICATE_FAMILY_ID"
    VALIDATION_FAILED = "VPLIB_SOURCE_VALIDATION_FAILED"
    INTERNAL_ERROR = "VPLIB_SOURCE_INTERNAL_ERROR"

    @property
    def key(self) -> str:
        return str(self.value)


class SourceScanMode(str, Enum):
    """Scan-Modus."""

    DIRECT_CHILDREN = "direct_children"
    RECURSIVE = "recursive"
    SINGLE_PACKAGE = "single_package"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SourceScanOptions:
    """Optionen für den Source-Scan."""

    scan_mode: str = SourceScanMode.DIRECT_CHILDREN.value
    max_depth: int = DEFAULT_MAX_DEPTH
    encoding: str = DEFAULT_ENCODING
    include_hidden_directories: bool = False
    include_hidden_files: bool = False
    follow_symlinks: bool = False
    require_manifest: bool = True
    require_modules: bool = True
    require_vplib_uid: bool = True
    require_core_documents: bool = False
    validate_schema: bool = True
    validate_semantics: bool = True
    validate_assets: bool = True
    skip_invalid_candidates: bool = False
    collect_all_errors: bool = True
    strict: bool = True

    def normalized(self) -> "SourceScanOptions":
        return SourceScanOptions(
            scan_mode=parse_scan_mode_value(self.scan_mode),
            max_depth=normalize_non_negative_int(self.max_depth, "max_depth"),
            encoding=clean_required_string(self.encoding or DEFAULT_ENCODING, "encoding"),
            include_hidden_directories=bool(self.include_hidden_directories),
            include_hidden_files=bool(self.include_hidden_files),
            follow_symlinks=bool(self.follow_symlinks),
            require_manifest=bool(self.require_manifest),
            require_modules=bool(self.require_modules),
            require_vplib_uid=bool(self.require_vplib_uid),
            require_core_documents=bool(self.require_core_documents),
            validate_schema=bool(self.validate_schema),
            validate_semantics=bool(self.validate_semantics),
            validate_assets=bool(self.validate_assets),
            skip_invalid_candidates=bool(self.skip_invalid_candidates),
            collect_all_errors=bool(self.collect_all_errors),
            strict=bool(self.strict),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "scan_mode": normalized.scan_mode,
            "max_depth": normalized.max_depth,
            "encoding": normalized.encoding,
            "include_hidden_directories": normalized.include_hidden_directories,
            "include_hidden_files": normalized.include_hidden_files,
            "follow_symlinks": normalized.follow_symlinks,
            "require_manifest": normalized.require_manifest,
            "require_modules": normalized.require_modules,
            "require_vplib_uid": normalized.require_vplib_uid,
            "require_core_documents": normalized.require_core_documents,
            "validate_schema": normalized.validate_schema,
            "validate_semantics": normalized.validate_semantics,
            "validate_assets": normalized.validate_assets,
            "skip_invalid_candidates": normalized.skip_invalid_candidates,
            "collect_all_errors": normalized.collect_all_errors,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class SourceIssue:
    """Ein einzelnes Source-Scanner-Issue."""

    code: str
    message: str
    severity: str = SourceIssueSeverity.ERROR.value
    source_path: Path | None = None
    relative_path: str | None = None
    field_path: str | None = None
    vplib_uid: str | None = None
    package_id: str | None = None
    family_id: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceIssue":
        return SourceIssue(
            code=parse_issue_code_value(self.code),
            message=clean_required_string(self.message, "message"),
            severity=parse_issue_severity_value(self.severity),
            source_path=Path(self.source_path).expanduser() if self.source_path is not None else None,
            relative_path=clean_optional_string(self.relative_path),
            field_path=clean_optional_string(self.field_path),
            vplib_uid=normalize_vplib_uid_safe(self.vplib_uid) or clean_optional_string(self.vplib_uid),
            package_id=clean_optional_string(self.package_id),
            family_id=clean_optional_string(self.family_id),
            details=normalize_metadata(self.details),
        )

    @property
    def blocks_success(self) -> bool:
        return self.normalized().severity in {
            SourceIssueSeverity.ERROR.value,
            SourceIssueSeverity.FATAL.value,
        }

    def fingerprint(self) -> str:
        normalized = self.normalized()

        return "|".join(
            (
                normalized.code,
                normalized.severity,
                str(normalized.source_path or ""),
                normalized.relative_path or "",
                normalized.field_path or "",
                normalized.vplib_uid or "",
                normalized.package_id or "",
                normalized.family_id or "",
                normalized.message,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "code": normalized.code,
            "message": normalized.message,
            "severity": normalized.severity,
            "source_path": str(normalized.source_path) if normalized.source_path else None,
            "relative_path": normalized.relative_path,
            "field_path": normalized.field_path,
            "vplib_uid": normalized.vplib_uid,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """Ein geladenes JSON-Dokument aus einem Source-Package."""

    relative_path: str
    absolute_path: Path
    document: Mapping[str, Any]
    schema_version: str | None = None
    module_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceDocument":
        relative_path = normalize_package_relative_path(self.relative_path)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        document = normalize_document_mapping(self.document)
        schema_version = clean_optional_string(self.schema_version) or clean_optional_string(document.get("schema_version"))
        module_name = normalize_optional_module_name(self.module_name) or infer_module_from_path_safe(relative_path)
        metadata = normalize_metadata(self.metadata)

        return SourceDocument(
            relative_path=relative_path,
            absolute_path=absolute_path,
            document=document,
            schema_version=schema_version,
            module_name=module_name,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "schema_version": normalized.schema_version,
            "module_name": normalized.module_name,
            "document": dict(normalized.document),
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SourcePackageCandidate:
    """Ein erkannter VPLIB-Source-Package-Kandidat."""

    source_dir: Path
    documents: tuple[SourceDocument, ...] = field(default_factory=tuple)
    issues: tuple[SourceIssue, ...] = field(default_factory=tuple)
    validation_result: Any | None = None
    status: str = SourceCandidateStatus.READY.value
    vplib_uid: str | None = None
    package_id: str | None = None
    family_id: str | None = None
    family_slug: str | None = None
    family_name: str | None = None
    object_kind: str | None = None
    classification_path: str | None = None
    active_modules: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourcePackageCandidate":
        source_dir = normalize_absolute_path(self.source_dir, "source_dir")
        documents = tuple(document.normalized() for document in self.documents or ())
        issues = sort_issues(dedupe_issues(tuple(issue.normalized() for issue in self.issues or ())))
        documents_by_path = {document.relative_path: document.document for document in documents}

        manifest = documents_by_path.get(MANIFEST_DOCUMENT_PATH, {})
        modules = documents_by_path.get(MODULES_DOCUMENT_PATH, {})
        family_identity = documents_by_path.get("family/identity.json", {})
        family_classification = documents_by_path.get("family/classification.json", {})

        vplib_uid = (
            normalize_vplib_uid_safe(self.vplib_uid)
            or get_vplib_uid_from_manifest_safe(manifest)
        )
        package_id = (
            clean_optional_string(self.package_id)
            or clean_optional_string(manifest.get("package_id"))
        )
        family_id = (
            clean_optional_string(self.family_id)
            or clean_optional_string(manifest.get("family_id"))
            or clean_optional_string(family_identity.get("family_id"))
        )
        family_slug = (
            clean_optional_string(self.family_slug)
            or clean_optional_string(manifest.get("family_slug"))
            or clean_optional_string(family_identity.get("family_slug"))
        )
        family_name = (
            clean_optional_string(self.family_name)
            or clean_optional_string(manifest.get("family_name"))
            or clean_optional_string(family_identity.get("family_name"))
        )
        object_kind = (
            clean_optional_string(self.object_kind)
            or clean_optional_string(manifest.get("object_kind"))
            or clean_optional_string(family_classification.get("object_kind"))
        )
        classification_path = (
            clean_optional_string(self.classification_path)
            or clean_optional_string(
                manifest.get("classification", {}).get("classification_path")
                if isinstance(manifest.get("classification"), Mapping)
                else None
            )
            or clean_optional_string(family_classification.get("classification_path"))
        )
        active_modules = normalize_string_tuple(
            self.active_modules
            or modules.get("active_modules", ())
            or tuple()
        )
        validation_result = normalize_optional_validation_result(self.validation_result)
        metadata = normalize_metadata(self.metadata)

        if vplib_uid:
            metadata = {
                **metadata,
                MANIFEST_VPLIB_UID_FIELD: vplib_uid,
            }

        status = parse_candidate_status_value(self.status)
        if any(issue.blocks_success for issue in issues):
            status = SourceCandidateStatus.INVALID.value
        elif validation_result is not None and not validation_result_is_valid(validation_result):
            status = SourceCandidateStatus.INVALID.value
        elif not vplib_uid:
            status = SourceCandidateStatus.INVALID.value
        elif not package_id or not family_id:
            status = SourceCandidateStatus.PARTIAL.value

        return SourcePackageCandidate(
            source_dir=source_dir,
            documents=sort_documents(documents),
            issues=issues,
            validation_result=validation_result,
            status=status,
            vplib_uid=vplib_uid,
            package_id=package_id,
            family_id=family_id,
            family_slug=family_slug,
            family_name=family_name,
            object_kind=object_kind,
            classification_path=classification_path,
            active_modules=active_modules,
            metadata=metadata,
        )

    @property
    def document_count(self) -> int:
        return len(self.normalized().documents)

    @property
    def valid(self) -> bool:
        normalized = self.normalized()

        if any(issue.blocks_success for issue in normalized.issues):
            return False

        if not normalized.vplib_uid:
            return False

        if normalized.validation_result is not None:
            return validation_result_is_valid(normalized.validation_result)

        return normalized.status == SourceCandidateStatus.READY.value

    @property
    def documents_mapping(self) -> dict[str, dict[str, Any]]:
        normalized = self.normalized()

        return {
            document.relative_path: dict(document.document)
            for document in normalized.documents
        }

    def get_document(self, relative_path: str) -> dict[str, Any] | None:
        path = normalize_package_relative_path(relative_path)

        for document in self.normalized().documents:
            if document.relative_path == path:
                return dict(document.document)

        return None

    def to_document_bundle(self) -> Any:
        """Wandelt den Kandidaten in ein DocumentBundle."""
        try:
            from ..defaults.document_bundle import build_document_bundle_from_components

            normalized = self.normalized()

            return build_document_bundle_from_components(
                documents=normalized.documents_mapping,
                active_modules=normalized.active_modules,
                metadata={
                    "source": "source_scanner",
                    "source_dir": str(normalized.source_dir),
                    "vplib_uid": normalized.vplib_uid,
                    "package_id": normalized.package_id,
                    "family_id": normalized.family_id,
                },
            ).normalized()
        except Exception as exc:
            raise SourceScannerError(f"Could not convert source candidate to DocumentBundle: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "source_dir": str(normalized.source_dir),
            "status": normalized.status,
            "valid": normalized.valid,
            "vplib_uid": normalized.vplib_uid,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "family_slug": normalized.family_slug,
            "family_name": normalized.family_name,
            "object_kind": normalized.object_kind,
            "classification_path": normalized.classification_path,
            "active_modules": list(normalized.active_modules),
            "document_count": normalized.document_count,
            "documents": [document.to_dict() for document in normalized.documents],
            "issues": [issue.to_dict() for issue in normalized.issues],
            "validation_result": object_to_dict(normalized.validation_result),
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SourceScanResult:
    """Ergebnis eines Source-Scans."""

    source_root: Path
    candidates: tuple[SourcePackageCandidate, ...] = field(default_factory=tuple)
    issues: tuple[SourceIssue, ...] = field(default_factory=tuple)
    options: SourceScanOptions = field(default_factory=SourceScanOptions)
    status: str = SourceScanStatus.COMPLETED.value
    schema_version: str = SOURCE_SCANNER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SourceScanResult":
        source_root = normalize_absolute_path(self.source_root, "source_root")
        candidates = sort_candidates(tuple(candidate.normalized() for candidate in self.candidates or ()))
        issues = sort_issues(dedupe_issues(tuple(issue.normalized() for issue in self.issues or ())))
        options = self.options.normalized()
        metadata = normalize_metadata(self.metadata)

        status = parse_scan_status_value(self.status)

        if not candidates and not issues:
            status = SourceScanStatus.EMPTY.value
        elif any(issue.severity == SourceIssueSeverity.FATAL.value for issue in issues):
            status = SourceScanStatus.FAILED.value
        elif any(not candidate.valid for candidate in candidates) or any(issue.blocks_success for issue in issues):
            status = SourceScanStatus.PARTIAL.value

        return SourceScanResult(
            source_root=source_root,
            candidates=candidates,
            issues=issues,
            options=options,
            status=status,
            schema_version=self.schema_version or SOURCE_SCANNER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def candidate_count(self) -> int:
        return len(self.normalized().candidates)

    @property
    def valid_candidates(self) -> tuple[SourcePackageCandidate, ...]:
        return tuple(candidate for candidate in self.normalized().candidates if candidate.valid)

    @property
    def invalid_candidates(self) -> tuple[SourcePackageCandidate, ...]:
        return tuple(candidate for candidate in self.normalized().candidates if not candidate.valid)

    @property
    def vplib_uids(self) -> tuple[str, ...]:
        return tuple(
            candidate.vplib_uid
            for candidate in self.normalized().candidates
            if candidate.vplib_uid
        )

    @property
    def package_ids(self) -> tuple[str, ...]:
        return tuple(
            candidate.package_id
            for candidate in self.normalized().candidates
            if candidate.package_id
        )

    @property
    def family_ids(self) -> tuple[str, ...]:
        return tuple(
            candidate.family_id
            for candidate in self.normalized().candidates
            if candidate.family_id
        )

    @property
    def ok(self) -> bool:
        normalized = self.normalized()

        return normalized.status in {
            SourceScanStatus.COMPLETED.value,
            SourceScanStatus.EMPTY.value,
        }

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "source_root": str(normalized.source_root),
            "status": normalized.status,
            "ok": normalized.ok,
            "candidate_count": normalized.candidate_count,
            "valid_candidate_count": len(normalized.valid_candidates),
            "invalid_candidate_count": len(normalized.invalid_candidates),
            "vplib_uids": list(normalized.vplib_uids),
            "package_ids": list(normalized.package_ids),
            "family_ids": list(normalized.family_ids),
            "options": normalized.options.to_dict(),
            "candidates": [candidate.to_dict() for candidate in normalized.candidates],
            "issues": [issue.to_dict() for issue in normalized.issues],
            "metadata": dict(normalized.metadata),
        }


def scan_source_root(
    source_root: str | Path,
    *,
    options: SourceScanOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SourceScanResult:
    """Scannt einen Source-Root nach VPLIB-Source-Package-Kandidaten."""
    normalized_options = normalize_options(options)
    root = normalize_absolute_path(source_root, "source_root")

    issues: list[SourceIssue] = []
    candidates: list[SourcePackageCandidate] = []

    try:
        if not root.exists():
            issues.append(
                source_issue(
                    code=SourceIssueCode.SOURCE_ROOT_MISSING.value,
                    severity=SourceIssueSeverity.FATAL.value,
                    message=f"Source root does not exist: {root}",
                    source_path=root,
                )
            )
            return SourceScanResult(
                source_root=root,
                candidates=tuple(),
                issues=tuple(issues),
                options=normalized_options,
                status=SourceScanStatus.FAILED.value,
                metadata=dict(metadata or {}),
            ).normalized()

        if not root.is_dir():
            issues.append(
                source_issue(
                    code=SourceIssueCode.SOURCE_ROOT_NOT_DIRECTORY.value,
                    severity=SourceIssueSeverity.FATAL.value,
                    message=f"Source root is not a directory: {root}",
                    source_path=root,
                )
            )
            return SourceScanResult(
                source_root=root,
                candidates=tuple(),
                issues=tuple(issues),
                options=normalized_options,
                status=SourceScanStatus.FAILED.value,
                metadata=dict(metadata or {}),
            ).normalized()

        candidate_dirs = discover_source_candidate_dirs(
            root,
            options=normalized_options,
        )

        for candidate_dir in candidate_dirs:
            try:
                candidate = scan_source_package(
                    candidate_dir,
                    options=normalized_options,
                ).normalized()

                if normalized_options.skip_invalid_candidates and not candidate.valid:
                    continue

                candidates.append(candidate)
            except Exception as exc:
                issue = source_issue(
                    code=SourceIssueCode.INTERNAL_ERROR.value,
                    severity=SourceIssueSeverity.ERROR.value,
                    message=f"Could not scan source package {candidate_dir}: {exc}",
                    source_path=candidate_dir,
                )
                issues.append(issue)

                if normalized_options.strict and not normalized_options.collect_all_errors:
                    raise

        issues.extend(validate_source_scan_uniqueness(candidates))

        return SourceScanResult(
            source_root=root,
            candidates=tuple(candidates),
            issues=tuple(issues),
            options=normalized_options,
            status=SourceScanStatus.COMPLETED.value,
            metadata={
                "source": "scan_source_root",
                "candidate_dir_count": len(candidate_dirs),
                "vplib_uid_count": len([candidate for candidate in candidates if candidate.normalized().vplib_uid]),
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        if isinstance(exc, SourceScannerError):
            error_message = str(exc)
        else:
            error_message = f"Source scan failed: {exc}"

        return SourceScanResult(
            source_root=root,
            candidates=tuple(candidates),
            issues=(
                *tuple(issues),
                source_issue(
                    code=SourceIssueCode.INTERNAL_ERROR.value,
                    severity=SourceIssueSeverity.FATAL.value,
                    message=error_message,
                    source_path=root,
                ),
            ),
            options=normalized_options,
            status=SourceScanStatus.FAILED.value,
            metadata=dict(metadata or {}),
        ).normalized()


def scan_source_package(
    source_dir: str | Path,
    *,
    options: SourceScanOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SourcePackageCandidate:
    """Scannt ein einzelnes Source-Package-Verzeichnis."""
    normalized_options = normalize_options(options)
    directory = normalize_absolute_path(source_dir, "source_dir")
    issues: list[SourceIssue] = []

    try:
        if not directory.exists() or not directory.is_dir():
            return SourcePackageCandidate(
                source_dir=directory,
                documents=tuple(),
                issues=(
                    source_issue(
                        code=SourceIssueCode.INVALID_SOURCE_DIRECTORY.value,
                        severity=SourceIssueSeverity.ERROR.value,
                        message=f"Source package directory is invalid: {directory}",
                        source_path=directory,
                    ),
                ),
                status=SourceCandidateStatus.ERROR.value,
                metadata=dict(metadata or {}),
            ).normalized()

        documents, document_issues = load_source_documents(
            directory,
            options=normalized_options,
        )
        issues.extend(document_issues)

        documents_by_path = {
            document.relative_path: document.document
            for document in documents
        }
        vplib_uid = get_vplib_uid_from_documents_safe(documents_by_path)

        issues.extend(
            validate_source_package_documents(
                source_dir=directory,
                documents=documents_by_path,
                options=normalized_options,
            )
        )

        validation_result = None
        if normalized_options.validate_schema or normalized_options.validate_semantics or normalized_options.validate_assets:
            validation_result = validate_loaded_documents(
                documents_by_path,
                options=normalized_options,
            )

            if not validation_result_is_valid(validation_result):
                issues.append(
                    source_issue(
                        code=SourceIssueCode.VALIDATION_FAILED.value,
                        severity=SourceIssueSeverity.ERROR.value,
                        message="Loaded source package documents failed validation.",
                        source_path=directory,
                        vplib_uid=vplib_uid,
                        details={
                            "validation_result": object_to_dict(validation_result),
                        },
                    )
                )

        return SourcePackageCandidate(
            source_dir=directory,
            documents=documents,
            issues=tuple(issues),
            validation_result=validation_result,
            status=SourceCandidateStatus.READY.value,
            vplib_uid=vplib_uid,
            metadata={
                "source": "scan_source_package",
                "vplib_uid": vplib_uid,
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        if isinstance(exc, SourceScannerError):
            error_message = str(exc)
        else:
            error_message = f"Could not scan source package: {exc}"

        return SourcePackageCandidate(
            source_dir=directory,
            documents=tuple(),
            issues=(
                *tuple(issues),
                source_issue(
                    code=SourceIssueCode.INTERNAL_ERROR.value,
                    severity=SourceIssueSeverity.ERROR.value,
                    message=error_message,
                    source_path=directory,
                ),
            ),
            status=SourceCandidateStatus.ERROR.value,
            metadata=dict(metadata or {}),
        ).normalized()


def discover_source_candidate_dirs(
    source_root: Path,
    *,
    options: SourceScanOptions,
) -> tuple[Path, ...]:
    """Findet Source-Package-Kandidaten."""
    root = normalize_absolute_path(source_root, "source_root")
    normalized_options = options.normalized()

    if normalized_options.scan_mode == SourceScanMode.SINGLE_PACKAGE.value:
        return (root,) if is_source_candidate_dir(root) else tuple()

    if normalized_options.scan_mode == SourceScanMode.DIRECT_CHILDREN.value:
        candidates = [
            child
            for child in sorted(root.iterdir(), key=lambda item: item.name)
            if child.is_dir()
            and should_include_directory(child, options=normalized_options)
            and is_source_candidate_dir(child)
        ]
        return tuple(candidates)

    if normalized_options.scan_mode == SourceScanMode.RECURSIVE.value:
        return discover_source_candidate_dirs_recursive(
            root,
            options=normalized_options,
            current_depth=0,
        )

    raise SourceScannerError(f"Unsupported scan mode {normalized_options.scan_mode!r}.")


def discover_source_candidate_dirs_recursive(
    directory: Path,
    *,
    options: SourceScanOptions,
    current_depth: int,
) -> tuple[Path, ...]:
    """Findet Kandidaten rekursiv."""
    normalized_options = options.normalized()

    if current_depth > normalized_options.max_depth:
        return tuple()

    if is_source_candidate_dir(directory):
        return (directory,)

    candidates: list[Path] = []

    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        if not child.is_dir():
            continue

        if not normalized_options.follow_symlinks and child.is_symlink():
            continue

        if not should_include_directory(child, options=normalized_options):
            continue

        candidates.extend(
            discover_source_candidate_dirs_recursive(
                child,
                options=normalized_options,
                current_depth=current_depth + 1,
            )
        )

    return tuple(candidates)


def is_source_candidate_dir(directory: Path) -> bool:
    """Prüft, ob ein Verzeichnis wie ein VPLIB-Source-Package aussieht."""
    if not directory.exists() or not directory.is_dir():
        return False

    return any((directory / marker).is_file() for marker in ROOT_MARKER_DOCUMENTS)


def load_source_documents(
    source_dir: Path,
    *,
    options: SourceScanOptions,
) -> tuple[tuple[SourceDocument, ...], tuple[SourceIssue, ...]]:
    """Lädt alle JSON-Dokumente aus einem Source-Package."""
    directory = normalize_absolute_path(source_dir, "source_dir")
    normalized_options = options.normalized()
    documents: list[SourceDocument] = []
    issues: list[SourceIssue] = []

    for path in sorted(directory.rglob("*.json"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue

        if not normalized_options.follow_symlinks and path.is_symlink():
            continue

        if not should_include_file(path, options=normalized_options):
            continue

        try:
            relative_path = normalize_source_file_relative_path(path, directory)
            payload = read_json_document(path, encoding=normalized_options.encoding)
            documents.append(
                SourceDocument(
                    relative_path=relative_path,
                    absolute_path=path,
                    document=payload,
                    metadata={
                        "source_dir": str(directory),
                        "vplib_uid": get_vplib_uid_from_manifest_safe(payload) if relative_path == MANIFEST_DOCUMENT_PATH else None,
                    },
                ).normalized()
            )
        except Exception as exc:
            issues.append(
                source_issue(
                    code=SourceIssueCode.INVALID_JSON.value,
                    severity=SourceIssueSeverity.ERROR.value,
                    message=f"Could not load JSON document {path}: {exc}",
                    source_path=path,
                    relative_path=safe_relative_to(path, directory),
                )
            )

            if normalized_options.strict and not normalized_options.collect_all_errors:
                raise

    return tuple(documents), tuple(issues)


def read_json_document(path: Path, *, encoding: str = DEFAULT_ENCODING) -> dict[str, Any]:
    """Liest eine JSON-Datei robust."""
    file_path = normalize_absolute_path(path, "path")

    try:
        with file_path.open("r", encoding=encoding) as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise SourceScannerError(f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    except Exception as exc:
        raise SourceScannerError(f"Could not read JSON file: {exc}") from exc

    if not isinstance(payload, Mapping):
        raise SourceScannerError("JSON root must be an object.")

    return normalize_document_mapping(payload)


def validate_source_package_documents(
    *,
    source_dir: Path,
    documents: Mapping[str, Mapping[str, Any]],
    options: SourceScanOptions,
) -> tuple[SourceIssue, ...]:
    """Prüft Dokumentstruktur eines Source-Package-Kandidaten."""
    normalized_options = options.normalized()
    issues: list[SourceIssue] = []
    manifest = documents.get(MANIFEST_DOCUMENT_PATH)
    vplib_uid = get_vplib_uid_from_manifest_safe(manifest)

    if normalized_options.require_manifest and MANIFEST_DOCUMENT_PATH not in documents:
        issues.append(
            source_issue(
                code=SourceIssueCode.MISSING_MANIFEST.value,
                severity=SourceIssueSeverity.ERROR.value,
                message="Source package is missing vplib.manifest.json.",
                source_path=source_dir,
                relative_path=MANIFEST_DOCUMENT_PATH,
            )
        )

    if normalized_options.require_modules and MODULES_DOCUMENT_PATH not in documents:
        issues.append(
            source_issue(
                code=SourceIssueCode.MISSING_MODULES.value,
                severity=SourceIssueSeverity.ERROR.value,
                message="Source package is missing vplib.modules.json.",
                source_path=source_dir,
                relative_path=MODULES_DOCUMENT_PATH,
                vplib_uid=vplib_uid,
            )
        )

    if normalized_options.require_vplib_uid:
        issues.extend(
            validate_source_vplib_uid(
                source_dir=source_dir,
                documents=documents,
            )
        )

    if normalized_options.require_core_documents:
        for path in CORE_REQUIRED_DOCUMENTS:
            if path not in documents:
                issues.append(
                    source_issue(
                        code=SourceIssueCode.MISSING_REQUIRED_DOCUMENT.value,
                        severity=SourceIssueSeverity.ERROR.value,
                        message=f"Source package is missing required core document {path!r}.",
                        source_path=source_dir,
                        relative_path=path,
                        vplib_uid=vplib_uid,
                    )
                )

    for relative_path in documents:
        try:
            normalize_package_relative_path(relative_path)
        except Exception as exc:
            issues.append(
                source_issue(
                    code=SourceIssueCode.INVALID_PACKAGE_PATH.value,
                    severity=SourceIssueSeverity.ERROR.value,
                    message=f"Invalid package-relative document path {relative_path!r}: {exc}",
                    source_path=source_dir,
                    relative_path=str(relative_path),
                    vplib_uid=vplib_uid,
                )
            )

    return tuple(issues)


def validate_source_vplib_uid(
    *,
    source_dir: Path,
    documents: Mapping[str, Mapping[str, Any]],
) -> tuple[SourceIssue, ...]:
    """Prüft `vplib_uid` im Manifest des Source-Packages."""
    manifest = documents.get(MANIFEST_DOCUMENT_PATH)

    if manifest is None:
        return (
            source_issue(
                code=SourceIssueCode.MISSING_VPLIB_UID.value,
                severity=SourceIssueSeverity.ERROR.value,
                message=f"Cannot validate {MANIFEST_VPLIB_UID_FIELD!r}: manifest document is missing.",
                source_path=source_dir,
                relative_path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
            ),
        )

    if not isinstance(manifest, Mapping):
        return (
            source_issue(
                code=SourceIssueCode.INVALID_VPLIB_UID.value,
                severity=SourceIssueSeverity.ERROR.value,
                message="Manifest document must be a JSON object.",
                source_path=source_dir,
                relative_path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
            ),
        )

    raw_uid = manifest.get(MANIFEST_VPLIB_UID_FIELD)
    uid = normalize_vplib_uid_safe(raw_uid)

    if raw_uid is None or str(raw_uid).strip() == "":
        return (
            source_issue(
                code=SourceIssueCode.MISSING_VPLIB_UID.value,
                severity=SourceIssueSeverity.ERROR.value,
                message=f"Manifest is missing required field {MANIFEST_VPLIB_UID_FIELD!r}.",
                source_path=source_dir,
                relative_path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
            ),
        )

    if not uid:
        return (
            source_issue(
                code=SourceIssueCode.INVALID_VPLIB_UID.value,
                severity=SourceIssueSeverity.ERROR.value,
                message=f"Manifest field {MANIFEST_VPLIB_UID_FIELD!r} is invalid. Expected UUID-like VPLIB UID.",
                source_path=source_dir,
                relative_path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
                details={
                    "value": str(raw_uid),
                },
            ),
        )

    return tuple()


def validate_loaded_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SourceScanOptions,
) -> Any:
    """Validiert geladene Dokumente über validators/package_validator.py."""
    try:
        from ..validators.package_validator import PackageValidationOptions, validate_package_documents

        normalized_options = options.normalized()

        return validate_package_documents(
            documents,
            options=PackageValidationOptions(
                mode="strict" if normalized_options.strict else "normal",
                validate_schema=normalized_options.validate_schema,
                validate_semantics=normalized_options.validate_semantics,
                validate_assets=normalized_options.validate_assets,
                validate_package_plan=False,
                validate_document_paths=True,
                validate_required_documents=normalized_options.require_core_documents,
                validate_vplib_uid=normalized_options.require_vplib_uid,
                strict=normalized_options.strict,
            ),
            metadata={
                "source": "source_scanner",
                "vplib_uid": get_vplib_uid_from_documents_safe(documents),
            },
        ).normalized()
    except Exception as exc:
        raise SourceScannerError(f"Source package validation failed: {exc}") from exc


def validate_source_scan_uniqueness(
    candidates: Iterable[SourcePackageCandidate],
) -> tuple[SourceIssue, ...]:
    """Prüft vplib_uid/package_id/family_id Eindeutigkeit im Scan-Ergebnis."""
    issues: list[SourceIssue] = []
    uid_map: dict[str, list[SourcePackageCandidate]] = {}
    package_map: dict[str, list[SourcePackageCandidate]] = {}
    family_map: dict[str, list[SourcePackageCandidate]] = {}

    for candidate in candidates or ():
        normalized = candidate.normalized()

        if normalized.vplib_uid:
            uid_map.setdefault(normalized.vplib_uid, []).append(normalized)

        if normalized.package_id:
            package_map.setdefault(normalized.package_id, []).append(normalized)

        if normalized.family_id:
            family_map.setdefault(normalized.family_id, []).append(normalized)

    for vplib_uid, grouped in uid_map.items():
        if len(grouped) <= 1:
            continue

        issues.append(
            source_issue(
                code=SourceIssueCode.DUPLICATE_VPLIB_UID.value,
                severity=SourceIssueSeverity.ERROR.value,
                message=f"Duplicate vplib_uid {vplib_uid!r} found in source scan.",
                vplib_uid=vplib_uid,
                details={
                    "source_dirs": [str(candidate.source_dir) for candidate in grouped],
                    "package_ids": [candidate.package_id for candidate in grouped],
                    "family_ids": [candidate.family_id for candidate in grouped],
                },
            )
        )

    for package_id, grouped in package_map.items():
        if len(grouped) <= 1:
            continue

        issues.append(
            source_issue(
                code=SourceIssueCode.DUPLICATE_PACKAGE_ID.value,
                severity=SourceIssueSeverity.ERROR.value,
                message=f"Duplicate package_id {package_id!r} found in source scan.",
                package_id=package_id,
                details={
                    "source_dirs": [str(candidate.source_dir) for candidate in grouped],
                    "vplib_uids": [candidate.vplib_uid for candidate in grouped],
                },
            )
        )

    for family_id, grouped in family_map.items():
        if len(grouped) <= 1:
            continue

        issues.append(
            source_issue(
                code=SourceIssueCode.DUPLICATE_FAMILY_ID.value,
                severity=SourceIssueSeverity.WARNING.value,
                message=f"Duplicate family_id {family_id!r} found in source scan.",
                family_id=family_id,
                details={
                    "source_dirs": [str(candidate.source_dir) for candidate in grouped],
                    "vplib_uids": [candidate.vplib_uid for candidate in grouped],
                },
            )
        )

    return tuple(issues)


def source_issue(
    *,
    code: str,
    message: str,
    severity: str = SourceIssueSeverity.ERROR.value,
    source_path: Path | None = None,
    relative_path: str | None = None,
    field_path: str | None = None,
    vplib_uid: str | None = None,
    package_id: str | None = None,
    family_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> SourceIssue:
    """Factory für SourceIssue."""
    return SourceIssue(
        code=code,
        message=message,
        severity=severity,
        source_path=source_path,
        relative_path=relative_path,
        field_path=field_path,
        vplib_uid=vplib_uid,
        package_id=package_id,
        family_id=family_id,
        details=dict(details or {}),
    ).normalized()


def should_include_directory(path: Path, *, options: SourceScanOptions) -> bool:
    """Prüft, ob ein Verzeichnis gescannt werden soll."""
    normalized_options = options.normalized()
    name = path.name

    if name in IGNORED_DIRECTORY_NAMES:
        return False

    if name.startswith(".") and not normalized_options.include_hidden_directories:
        return False

    return True


def should_include_file(path: Path, *, options: SourceScanOptions) -> bool:
    """Prüft, ob eine Datei geladen werden soll."""
    normalized_options = options.normalized()
    name = path.name

    if name in IGNORED_FILE_NAMES:
        return False

    if name.startswith(".") and not normalized_options.include_hidden_files:
        return False

    if path.suffix.lower() not in ALLOWED_DOCUMENT_SUFFIXES:
        return False

    for part in path.parts:
        if part in IGNORED_DIRECTORY_NAMES:
            return False
        if part.startswith(".") and not normalized_options.include_hidden_directories:
            return False

    return True


def normalize_source_file_relative_path(path: Path, source_dir: Path) -> str:
    """Normalisiert Dateipfad relativ zum Source-Package."""
    try:
        relative = path.resolve().relative_to(source_dir.resolve())
    except Exception as exc:
        raise SourceScannerError(f"File {path} is outside source_dir {source_dir}.") from exc

    return normalize_package_relative_path(PurePosixPath(*relative.parts).as_posix())


def safe_relative_to(path: Path, root: Path) -> str | None:
    """Erzeugt defensiv relativen Pfad."""
    try:
        return PurePosixPath(*path.resolve().relative_to(root.resolve()).parts).as_posix()
    except Exception:
        return None


def candidate_to_document_bundle(candidate: SourcePackageCandidate) -> Any:
    """Wandelt einen SourcePackageCandidate in ein DocumentBundle."""
    return candidate.normalized().to_document_bundle()


def candidates_to_document_bundles(
    candidates: Iterable[SourcePackageCandidate],
    *,
    only_valid: bool = True,
) -> tuple[Any, ...]:
    """Wandelt mehrere Kandidaten in DocumentBundles."""
    bundles: list[Any] = []

    for candidate in candidates or ():
        normalized = candidate.normalized()

        if only_valid and not normalized.valid:
            continue

        bundles.append(normalized.to_document_bundle())

    return tuple(bundles)


def result_to_document_bundles(
    result: SourceScanResult,
    *,
    only_valid: bool = True,
) -> tuple[Any, ...]:
    """Wandelt ein SourceScanResult in DocumentBundles."""
    return candidates_to_document_bundles(
        result.normalized().candidates,
        only_valid=only_valid,
    )


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


def normalize_options(options: SourceScanOptions | Mapping[str, Any] | None) -> SourceScanOptions:
    """Normalisiert SourceScanOptions."""
    if options is None:
        return SourceScanOptions().normalized()

    if isinstance(options, SourceScanOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return SourceScanOptions(
            scan_mode=options.get("scan_mode", SourceScanMode.DIRECT_CHILDREN.value),
            max_depth=options.get("max_depth", DEFAULT_MAX_DEPTH),
            encoding=options.get("encoding", DEFAULT_ENCODING),
            include_hidden_directories=bool(options.get("include_hidden_directories", False)),
            include_hidden_files=bool(options.get("include_hidden_files", False)),
            follow_symlinks=bool(options.get("follow_symlinks", False)),
            require_manifest=bool(options.get("require_manifest", True)),
            require_modules=bool(options.get("require_modules", True)),
            require_vplib_uid=bool(options.get("require_vplib_uid", True)),
            require_core_documents=bool(options.get("require_core_documents", False)),
            validate_schema=bool(options.get("validate_schema", True)),
            validate_semantics=bool(options.get("validate_semantics", True)),
            validate_assets=bool(options.get("validate_assets", True)),
            skip_invalid_candidates=bool(options.get("skip_invalid_candidates", False)),
            collect_all_errors=bool(options.get("collect_all_errors", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise SourceScannerError("options must be SourceScanOptions, mapping or None.")


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert lokalen Pfad."""
    try:
        if value is None:
            raise SourceScannerError(f"{field_name} is required.")

        return Path(value).expanduser()
    except SourceScannerError:
        raise
    except Exception as exc:
        raise SourceScannerError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_package_relative_path(value: Any) -> str:
    """Normalisiert package-relativen POSIX-Pfad."""
    raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

    if raw.startswith("/"):
        raise SourceScannerError(f"relative_path must not be absolute: {value!r}")

    path = PurePosixPath(raw)
    parts = tuple(part for part in path.parts if part not in {"", "."})

    if not parts:
        raise SourceScannerError("relative_path is required.")

    if any(part == ".." for part in parts):
        raise SourceScannerError(f"relative_path must not contain parent traversal: {value!r}")

    return PurePosixPath(*parts).as_posix()


def infer_module_from_path_safe(relative_path: Any) -> str | None:
    """Leitet Modul aus package-relativem Pfad ab."""
    try:
        path = normalize_package_relative_path(relative_path)

        if path == MANIFEST_DOCUMENT_PATH:
            return "manifest"

        if path == MODULES_DOCUMENT_PATH:
            return "modules"

        return path.split("/", 1)[0] if "/" in path else None
    except Exception:
        return None


def normalize_optional_module_name(value: Any) -> str | None:
    """Normalisiert optionalen Modulnamen."""
    if value is None:
        return None

    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception:
        return clean_optional_string(value)


def normalize_document_mapping(document: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert ein JSON-Dokument."""
    if not isinstance(document, Mapping):
        raise SourceScannerError("document must be a mapping.")

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


def normalize_optional_validation_result(value: Any | None) -> Any | None:
    """Normalisiert optionale ValidationResult-artige Objekte."""
    if value is None:
        return None

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()
    except Exception:
        return value

    return value


def get_vplib_uid_from_documents_safe(
    documents: Mapping[str, Mapping[str, Any]] | None,
) -> str | None:
    """Liest gültige `vplib_uid` aus Dokument-Mapping."""
    if not isinstance(documents, Mapping):
        return None

    try:
        return get_vplib_uid_from_manifest_safe(documents.get(MANIFEST_DOCUMENT_PATH))
    except Exception:
        return None


def get_vplib_uid_from_manifest_safe(manifest: Any | None) -> str | None:
    """Liest gültige `vplib_uid` aus einem Manifest-Mapping."""
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


@lru_cache(maxsize=128)
def parse_scan_mode_value(value: Any) -> str:
    """Parst SourceScanMode."""
    try:
        if isinstance(value, SourceScanMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "direct": SourceScanMode.DIRECT_CHILDREN.value,
            "direct_children": SourceScanMode.DIRECT_CHILDREN.value,
            "children": SourceScanMode.DIRECT_CHILDREN.value,
            "recursive": SourceScanMode.RECURSIVE.value,
            "all": SourceScanMode.RECURSIVE.value,
            "single": SourceScanMode.SINGLE_PACKAGE.value,
            "single_package": SourceScanMode.SINGLE_PACKAGE.value,
            "package": SourceScanMode.SINGLE_PACKAGE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return SourceScanMode(raw).value
    except Exception as exc:
        raise SourceScannerError(f"Invalid source scan mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_candidate_status_value(value: Any) -> str:
    """Parst SourceCandidateStatus."""
    try:
        if isinstance(value, SourceCandidateStatus):
            return value.value

        raw = normalize_enum_key(value)
        return SourceCandidateStatus(raw).value
    except Exception as exc:
        raise SourceScannerError(f"Invalid source candidate status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_scan_status_value(value: Any) -> str:
    """Parst SourceScanStatus."""
    try:
        if isinstance(value, SourceScanStatus):
            return value.value

        raw = normalize_enum_key(value)
        return SourceScanStatus(raw).value
    except Exception as exc:
        raise SourceScannerError(f"Invalid source scan status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_issue_severity_value(value: Any) -> str:
    """Parst SourceIssueSeverity."""
    try:
        if isinstance(value, SourceIssueSeverity):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "info": SourceIssueSeverity.INFO.value,
            "warning": SourceIssueSeverity.WARNING.value,
            "warn": SourceIssueSeverity.WARNING.value,
            "error": SourceIssueSeverity.ERROR.value,
            "fatal": SourceIssueSeverity.FATAL.value,
            "critical": SourceIssueSeverity.FATAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return SourceIssueSeverity(raw).value
    except Exception as exc:
        raise SourceScannerError(f"Invalid source issue severity {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_issue_code_value(value: Any) -> str:
    """Parst SourceIssueCode."""
    try:
        if isinstance(value, SourceIssueCode):
            return value.value

        raw = str(value).strip().upper().replace(" ", "_").replace("-", "_")

        if not raw:
            raise SourceScannerError("Source issue code is required.")

        if not raw.startswith("VPLIB_"):
            raw = f"VPLIB_SOURCE_{raw}"

        try:
            return SourceIssueCode(raw).value
        except ValueError:
            return raw
    except SourceScannerError:
        raise
    except Exception as exc:
        raise SourceScannerError(f"Invalid source issue code {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise SourceScannerError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except SourceScannerError:
        raise
    except Exception as exc:
        raise SourceScannerError(f"Invalid enum value {value!r}.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    """Normalisiert nicht-negative Integer."""
    try:
        if isinstance(value, bool):
            raise SourceScannerError(f"{field_name} must be an integer.")

        number = int(value)

        if number < 0:
            raise SourceScannerError(f"{field_name} must be >= 0.")

        return number
    except SourceScannerError:
        raise
    except Exception as exc:
        raise SourceScannerError(f"{field_name} must be a non-negative integer.") from exc


def normalize_string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Stringlisten ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise SourceScannerError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def dedupe_issues(issues: Iterable[SourceIssue]) -> tuple[SourceIssue, ...]:
    """Dedupliziert Issues."""
    result: list[SourceIssue] = []
    seen: set[str] = set()

    for issue in issues or ():
        normalized = issue.normalized()
        fingerprint = normalized.fingerprint()

        if fingerprint in seen:
            continue

        result.append(normalized)
        seen.add(fingerprint)

    return tuple(result)


def sort_issues(issues: Iterable[SourceIssue]) -> tuple[SourceIssue, ...]:
    """Sortiert Issues stabil."""
    severity_order = {
        SourceIssueSeverity.FATAL.value: 10,
        SourceIssueSeverity.ERROR.value: 20,
        SourceIssueSeverity.WARNING.value: 30,
        SourceIssueSeverity.INFO.value: 40,
    }

    return tuple(
        sorted(
            (issue.normalized() for issue in issues or ()),
            key=lambda issue: (
                severity_order.get(issue.severity, 99),
                str(issue.source_path or ""),
                issue.relative_path or "",
                issue.vplib_uid or "",
                issue.code,
                issue.message,
            ),
        )
    )


def sort_documents(documents: Iterable[SourceDocument]) -> tuple[SourceDocument, ...]:
    """Sortiert SourceDocuments stabil."""
    return tuple(
        sorted(
            (document.normalized() for document in documents or ()),
            key=lambda document: document.relative_path,
        )
    )


def sort_candidates(candidates: Iterable[SourcePackageCandidate]) -> tuple[SourcePackageCandidate, ...]:
    """Sortiert Kandidaten stabil."""
    return tuple(
        sorted(
            (candidate.normalized() for candidate in candidates or ()),
            key=lambda candidate: (
                candidate.vplib_uid or "",
                candidate.package_id or "",
                candidate.family_id or "",
                str(candidate.source_dir),
            ),
        )
    )


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise SourceScannerError(f"{field_name} is required.")

        return cleaned
    except SourceScannerError:
        raise
    except Exception as exc:
        raise SourceScannerError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_source_scanner_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_scan_mode_value.cache_clear()
    parse_candidate_status_value.cache_clear()
    parse_scan_status_value.cache_clear()
    parse_issue_severity_value.cache_clear()
    parse_issue_code_value.cache_clear()


__all__ = [
    "ALLOWED_DOCUMENT_SUFFIXES",
    "CORE_REQUIRED_DOCUMENTS",
    "DEFAULT_ENCODING",
    "DEFAULT_MAX_DEPTH",
    "IGNORED_DIRECTORY_NAMES",
    "IGNORED_FILE_NAMES",
    "MANIFEST_DOCUMENT_PATH",
    "MANIFEST_VPLIB_UID_FIELD",
    "MODULES_DOCUMENT_PATH",
    "ROOT_MARKER_DOCUMENTS",
    "SOURCE_SCANNER_SCHEMA_VERSION",
    "SourceCandidateStatus",
    "SourceDocument",
    "SourceIssue",
    "SourceIssueCode",
    "SourceIssueSeverity",
    "SourcePackageCandidate",
    "SourceScanMode",
    "SourceScanOptions",
    "SourceScanResult",
    "SourceScanStatus",
    "SourceScannerError",
    "candidate_to_document_bundle",
    "candidates_to_document_bundles",
    "clean_optional_string",
    "clean_required_string",
    "clear_source_scanner_caches",
    "dedupe_issues",
    "discover_source_candidate_dirs",
    "discover_source_candidate_dirs_recursive",
    "get_vplib_uid_from_documents_safe",
    "get_vplib_uid_from_manifest_safe",
    "infer_module_from_path_safe",
    "is_source_candidate_dir",
    "load_source_documents",
    "normalize_absolute_path",
    "normalize_document_mapping",
    "normalize_enum_key",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_non_negative_int",
    "normalize_optional_module_name",
    "normalize_optional_validation_result",
    "normalize_options",
    "normalize_package_relative_path",
    "normalize_source_file_relative_path",
    "normalize_string_tuple",
    "normalize_vplib_uid_safe",
    "object_to_dict",
    "parse_candidate_status_value",
    "parse_issue_code_value",
    "parse_issue_severity_value",
    "parse_scan_mode_value",
    "parse_scan_status_value",
    "read_json_document",
    "result_to_document_bundles",
    "safe_relative_to",
    "scan_source_package",
    "scan_source_root",
    "should_include_directory",
    "should_include_file",
    "sort_candidates",
    "sort_documents",
    "sort_issues",
    "source_issue",
    "validate_loaded_documents",
    "validate_source_package_documents",
    "validate_source_scan_uniqueness",
    "validate_source_vplib_uid",
    "validation_result_is_valid",
]