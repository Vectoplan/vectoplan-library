# services/vectoplan-library/src/vplib/models/package_plan.py
"""
PackagePlan model for the VPLIB package engine.

Diese Datei beschreibt den vollständigen Erstellplan für ein modulares
VPLIB-Package.

Rolle dieser Datei:

    PackageContext
    + ModulePlan
    -> PackagePlan
    -> skeleton_creator / module_creator / asset_creator / validators

Der PackagePlan schreibt keine Dateien. Er beschreibt nur:
- Zielordner
- zu erstellende Ordner
- zu erstellende Dateien
- optionale Dateien
- generierte Dateien
- Asset-Kopien
- erwartete Archivpfade
- Validierungsanforderungen

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


PACKAGE_PLAN_SCHEMA_VERSION: Final[str] = "vplib.package_plan.v1"


class PackagePlanError(ValueError):
    """Wird ausgelöst, wenn ein PackagePlan ungültig ist."""


class PlannedPathKind(str, Enum):
    """Art eines geplanten Package-Pfads."""

    DIRECTORY = "directory"
    REQUIRED_FILE = "required_file"
    OPTIONAL_FILE = "optional_file"
    GENERATED_FILE = "generated_file"
    ASSET_FILE = "asset_file"
    ARCHIVE_FILE = "archive_file"

    @property
    def key(self) -> str:
        return str(self.value)


class PlannedFileStatus(str, Enum):
    """Status eines geplanten Files."""

    PLANNED = "planned"
    REQUIRED = "required"
    OPTIONAL = "optional"
    GENERATED = "generated"
    ASSET = "asset"
    SKIPPED = "skipped"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PlannedPath:
    """Ein geplanter Package-Pfad."""

    relative_path: str
    absolute_path: Path
    kind: str
    module_name: str | None = None
    required: bool = False
    create_parent_directories: bool = True
    overwrite_allowed: bool = False
    reason: str = ""

    def normalized(self) -> "PlannedPath":
        relative_path = normalize_package_relative_path(self.relative_path)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        kind = parse_planned_path_kind_value(self.kind)
        module_name = normalize_optional_module_name(self.module_name)
        required = bool(self.required)
        create_parent_directories = bool(self.create_parent_directories)
        overwrite_allowed = bool(self.overwrite_allowed)
        reason = clean_optional_string(self.reason) or ""

        return PlannedPath(
            relative_path=relative_path,
            absolute_path=absolute_path,
            kind=kind,
            module_name=module_name,
            required=required,
            create_parent_directories=create_parent_directories,
            overwrite_allowed=overwrite_allowed,
            reason=reason,
        )

    @property
    def is_directory(self) -> bool:
        return self.normalized().kind == PlannedPathKind.DIRECTORY.value

    @property
    def is_file(self) -> bool:
        return self.normalized().kind != PlannedPathKind.DIRECTORY.value

    @property
    def is_asset(self) -> bool:
        return self.normalized().kind == PlannedPathKind.ASSET_FILE.value

    @property
    def is_archive(self) -> bool:
        return self.normalized().kind == PlannedPathKind.ARCHIVE_FILE.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "kind": normalized.kind,
            "module_name": normalized.module_name,
            "required": normalized.required,
            "create_parent_directories": normalized.create_parent_directories,
            "overwrite_allowed": normalized.overwrite_allowed,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class PlannedDirectory:
    """Ein geplanter zu erstellender Ordner."""

    relative_path: str
    absolute_path: Path
    module_name: str | None = None
    required: bool = True
    reason: str = ""

    def normalized(self) -> "PlannedDirectory":
        relative_path = normalize_package_relative_path(self.relative_path)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        module_name = normalize_optional_module_name(self.module_name)
        required = bool(self.required)
        reason = clean_optional_string(self.reason) or ""

        return PlannedDirectory(
            relative_path=relative_path,
            absolute_path=absolute_path,
            module_name=module_name,
            required=required,
            reason=reason,
        )

    def to_planned_path(self) -> PlannedPath:
        normalized = self.normalized()

        return PlannedPath(
            relative_path=normalized.relative_path,
            absolute_path=normalized.absolute_path,
            kind=PlannedPathKind.DIRECTORY.value,
            module_name=normalized.module_name,
            required=normalized.required,
            create_parent_directories=True,
            overwrite_allowed=True,
            reason=normalized.reason,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "module_name": normalized.module_name,
            "required": normalized.required,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class PlannedFile:
    """Eine geplante zu erstellende oder zu erwartende Datei."""

    relative_path: str
    absolute_path: Path
    module_name: str
    status: str = PlannedFileStatus.PLANNED.value
    required: bool = False
    overwrite_allowed: bool = False
    content_kind: str = "json"
    reason: str = ""

    def normalized(self) -> "PlannedFile":
        relative_path = normalize_package_relative_path(self.relative_path)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        module_name = normalize_module_name(self.module_name)
        status = parse_planned_file_status_value(self.status)
        required = bool(self.required)
        overwrite_allowed = bool(self.overwrite_allowed)
        content_kind = clean_optional_string(self.content_kind) or "json"
        reason = clean_optional_string(self.reason) or ""

        if status == PlannedFileStatus.REQUIRED.value:
            required = True

        return PlannedFile(
            relative_path=relative_path,
            absolute_path=absolute_path,
            module_name=module_name,
            status=status,
            required=required,
            overwrite_allowed=overwrite_allowed,
            content_kind=content_kind,
            reason=reason,
        )

    def to_planned_path(self) -> PlannedPath:
        normalized = self.normalized()

        kind = {
            PlannedFileStatus.REQUIRED.value: PlannedPathKind.REQUIRED_FILE.value,
            PlannedFileStatus.OPTIONAL.value: PlannedPathKind.OPTIONAL_FILE.value,
            PlannedFileStatus.GENERATED.value: PlannedPathKind.GENERATED_FILE.value,
            PlannedFileStatus.ASSET.value: PlannedPathKind.ASSET_FILE.value,
        }.get(normalized.status, PlannedPathKind.REQUIRED_FILE.value if normalized.required else PlannedPathKind.OPTIONAL_FILE.value)

        return PlannedPath(
            relative_path=normalized.relative_path,
            absolute_path=normalized.absolute_path,
            kind=kind,
            module_name=normalized.module_name,
            required=normalized.required,
            create_parent_directories=True,
            overwrite_allowed=normalized.overwrite_allowed,
            reason=normalized.reason,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "module_name": normalized.module_name,
            "status": normalized.status,
            "required": normalized.required,
            "overwrite_allowed": normalized.overwrite_allowed,
            "content_kind": normalized.content_kind,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class PlannedAssetCopy:
    """Geplante Asset-Kopie von einer Quelle in das Package."""

    role: str
    source_path: Path
    target_relative_path: str
    target_absolute_path: Path
    module_name: str = "render"
    required: bool = False
    overwrite_allowed: bool = False
    asset_id: str | None = None
    mime_type: str | None = None
    reason: str = ""

    def normalized(self) -> "PlannedAssetCopy":
        role = clean_required_string(self.role, "role")
        source_path = normalize_absolute_path(self.source_path, "source_path")
        target_relative_path = normalize_package_relative_path(self.target_relative_path)
        target_absolute_path = normalize_absolute_path(self.target_absolute_path, "target_absolute_path")
        module_name = normalize_module_name(self.module_name)
        required = bool(self.required)
        overwrite_allowed = bool(self.overwrite_allowed)
        asset_id = clean_optional_string(self.asset_id)
        mime_type = clean_optional_string(self.mime_type)
        reason = clean_optional_string(self.reason) or ""

        return PlannedAssetCopy(
            role=role,
            source_path=source_path,
            target_relative_path=target_relative_path,
            target_absolute_path=target_absolute_path,
            module_name=module_name,
            required=required,
            overwrite_allowed=overwrite_allowed,
            asset_id=asset_id,
            mime_type=mime_type,
            reason=reason,
        )

    def to_planned_file(self) -> PlannedFile:
        normalized = self.normalized()

        return PlannedFile(
            relative_path=normalized.target_relative_path,
            absolute_path=normalized.target_absolute_path,
            module_name=normalized.module_name,
            status=PlannedFileStatus.ASSET.value,
            required=normalized.required,
            overwrite_allowed=normalized.overwrite_allowed,
            content_kind="asset",
            reason=normalized.reason,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "role": normalized.role,
            "source_path": str(normalized.source_path),
            "target_relative_path": normalized.target_relative_path,
            "target_absolute_path": str(normalized.target_absolute_path),
            "module_name": normalized.module_name,
            "required": normalized.required,
            "overwrite_allowed": normalized.overwrite_allowed,
            "asset_id": normalized.asset_id,
            "mime_type": normalized.mime_type,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class PackagePlan:
    """
    Vollständiger Erstellplan für ein VPLIB-Package.

    Der Plan ist immutable und enthält keine Datei-Inhalte.
    """

    context: Any
    module_plan: Any
    directories: tuple[PlannedDirectory, ...] = field(default_factory=tuple)
    files: tuple[PlannedFile, ...] = field(default_factory=tuple)
    asset_copies: tuple[PlannedAssetCopy, ...] = field(default_factory=tuple)
    archive_path: Path | None = None
    validation_required: bool = True
    schema_version: str = PACKAGE_PLAN_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackagePlan":
        context = normalize_package_context(self.context)
        module_plan = normalize_module_plan(self.module_plan)

        directories = tuple(directory.normalized() for directory in self.directories or ())
        files = tuple(file.normalized() for file in self.files or ())
        asset_copies = tuple(asset.normalized() for asset in self.asset_copies or ())

        if not directories:
            directories = build_directories_from_context_and_module_plan(context, module_plan)

        if not files:
            files = build_files_from_context_and_module_plan(context, module_plan)

        asset_files = tuple(asset.to_planned_file() for asset in asset_copies)
        files = merge_planned_files((*files, *asset_files))

        archive_path = (
            normalize_absolute_path(self.archive_path, "archive_path")
            if self.archive_path is not None
            else context.archive_path
        )

        validation_required = bool(self.validation_required)
        schema_version = self.schema_version or PACKAGE_PLAN_SCHEMA_VERSION
        metadata = dict(self.metadata or {})

        plan = PackagePlan(
            context=context,
            module_plan=module_plan,
            directories=merge_planned_directories(directories),
            files=files,
            asset_copies=asset_copies,
            archive_path=archive_path,
            validation_required=validation_required,
            schema_version=schema_version,
            metadata=metadata,
        )

        valid, messages = plan.validate()
        if not valid:
            raise PackagePlanError(" ".join(messages))

        return plan

    @property
    def package_dir(self) -> Path:
        return self.normalized().context.package_dir

    @property
    def active_module_names(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.active_module_names)

    @property
    def required_files(self) -> tuple[PlannedFile, ...]:
        return tuple(file for file in self.normalized().files if file.required)

    @property
    def optional_files(self) -> tuple[PlannedFile, ...]:
        return tuple(file for file in self.normalized().files if not file.required)

    @property
    def generated_files(self) -> tuple[PlannedFile, ...]:
        return tuple(
            file
            for file in self.normalized().files
            if file.status == PlannedFileStatus.GENERATED.value
        )

    @property
    def asset_files(self) -> tuple[PlannedFile, ...]:
        return tuple(
            file
            for file in self.normalized().files
            if file.status == PlannedFileStatus.ASSET.value
        )

    @property
    def planned_paths(self) -> tuple[PlannedPath, ...]:
        normalized = self.normalized()
        paths: list[PlannedPath] = []

        for directory in normalized.directories:
            paths.append(directory.to_planned_path())

        for file in normalized.files:
            paths.append(file.to_planned_path())

        if normalized.archive_path is not None:
            paths.append(
                PlannedPath(
                    relative_path=normalized.archive_path.name,
                    absolute_path=normalized.archive_path,
                    kind=PlannedPathKind.ARCHIVE_FILE.value,
                    module_name=None,
                    required=False,
                    create_parent_directories=True,
                    overwrite_allowed=normalized.context.may_overwrite,
                    reason="Optional .vplib archive output.",
                ).normalized()
            )

        return tuple(paths)

    @property
    def created_directory_paths(self) -> tuple[Path, ...]:
        return tuple(directory.absolute_path for directory in self.normalized().directories)

    @property
    def created_file_paths(self) -> tuple[Path, ...]:
        return tuple(file.absolute_path for file in self.normalized().files)

    def get_files_for_module(self, module_name: Any) -> tuple[PlannedFile, ...]:
        normalized_module_name = normalize_module_name(module_name)

        return tuple(
            file
            for file in self.normalized().files
            if file.module_name == normalized_module_name
        )

    def get_directories_for_module(self, module_name: Any) -> tuple[PlannedDirectory, ...]:
        normalized_module_name = normalize_module_name(module_name)

        return tuple(
            directory
            for directory in self.normalized().directories
            if directory.module_name == normalized_module_name
        )

    def has_file(self, relative_path: Any) -> bool:
        normalized_path = normalize_package_relative_path(relative_path)

        return any(
            file.relative_path == normalized_path
            for file in self.normalized().files
        )

    def has_directory(self, relative_path: Any) -> bool:
        normalized_path = normalize_package_relative_path(relative_path)

        return any(
            directory.relative_path == normalized_path
            for directory in self.normalized().directories
        )

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        messages: list[str] = []

        try:
            context = normalize_package_context(self.context)
            module_plan = normalize_module_plan(self.module_plan)

            if not module_plan.active_module_names:
                messages.append("PackagePlan requires at least one active module.")

            for module_name in module_plan.active_module_names:
                if not module_plan.has_active_module(module_name):
                    messages.append(f"Inactive module in active module list: {module_name!r}.")

            directory_paths = set()
            for directory in self.directories or ():
                normalized_directory = directory.normalized()
                if normalized_directory.relative_path in directory_paths:
                    messages.append(f"Duplicate planned directory: {normalized_directory.relative_path!r}.")
                directory_paths.add(normalized_directory.relative_path)

            file_paths = set()
            for file in self.files or ():
                normalized_file = file.normalized()
                if normalized_file.relative_path in file_paths:
                    messages.append(f"Duplicate planned file: {normalized_file.relative_path!r}.")
                file_paths.add(normalized_file.relative_path)

                if normalized_file.module_name not in module_plan.active_module_names:
                    messages.append(
                        f"File {normalized_file.relative_path!r} belongs to inactive module "
                        f"{normalized_file.module_name!r}."
                    )

            for required_path in module_plan.required_files:
                if required_path not in file_paths:
                    messages.append(f"Required file is missing from PackagePlan: {required_path!r}.")

            for asset in self.asset_copies or ():
                normalized_asset = asset.normalized()
                if normalized_asset.module_name not in module_plan.active_module_names:
                    messages.append(
                        f"Asset {normalized_asset.target_relative_path!r} belongs to inactive module "
                        f"{normalized_asset.module_name!r}."
                    )

            if self.archive_path is not None and not context.execution.create_archive:
                messages.append("Archive path is set, but context execution has create_archive=False.")

        except PackagePlanError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate package plan: {exc}")

        return len(messages) == 0, tuple(messages)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "context": normalized.context.to_dict(),
            "module_plan": normalized.module_plan.to_dict(),
            "package_dir": str(normalized.package_dir),
            "active_module_names": list(normalized.active_module_names),
            "directories": [directory.to_dict() for directory in normalized.directories],
            "files": [file.to_dict() for file in normalized.files],
            "asset_copies": [asset.to_dict() for asset in normalized.asset_copies],
            "archive_path": str(normalized.archive_path) if normalized.archive_path else None,
            "validation_required": normalized.validation_required,
            "planned_paths": [path.to_dict() for path in normalized.planned_paths],
            "metadata": dict(normalized.metadata),
        }


def build_package_plan(
    *,
    context: Any,
    module_plan: Any,
    asset_copies: Iterable[PlannedAssetCopy] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackagePlan:
    """Baut einen PackagePlan aus Context und ModulePlan."""
    try:
        normalized_context = normalize_package_context(context)
        normalized_module_plan = normalize_module_plan(module_plan)

        directories = build_directories_from_context_and_module_plan(
            normalized_context,
            normalized_module_plan,
        )
        files = build_files_from_context_and_module_plan(
            normalized_context,
            normalized_module_plan,
        )

        return PackagePlan(
            context=normalized_context,
            module_plan=normalized_module_plan,
            directories=directories,
            files=files,
            asset_copies=tuple(asset_copies or ()),
            archive_path=normalized_context.archive_path,
            validation_required=normalized_context.execution.validate_after_create,
            metadata=dict(metadata or {}),
        ).normalized()
    except PackagePlanError:
        raise
    except Exception as exc:
        raise PackagePlanError(f"Could not build PackagePlan: {exc}") from exc


def build_directories_from_context_and_module_plan(
    context: Any,
    module_plan: Any,
) -> tuple[PlannedDirectory, ...]:
    """Baut geplante Ordner aus Context und ModulePlan."""
    normalized_context = normalize_package_context(context)
    normalized_module_plan = normalize_module_plan(module_plan)

    directories: list[PlannedDirectory] = [
        PlannedDirectory(
            relative_path=".",
            absolute_path=normalized_context.package_dir,
            module_name=None,
            required=True,
            reason="Package root directory.",
        )
    ]

    for directory in normalized_module_plan.directories:
        module_name = infer_module_from_path_safe(directory)
        directories.append(
            PlannedDirectory(
                relative_path=directory,
                absolute_path=normalized_context.package_dir / directory,
                module_name=module_name,
                required=True,
                reason="Active module directory.",
            )
        )

    for directory in normalized_module_plan.allowed_subdirectories:
        module_name = infer_module_from_path_safe(directory)
        directories.append(
            PlannedDirectory(
                relative_path=directory,
                absolute_path=normalized_context.package_dir / directory,
                module_name=module_name,
                required=False,
                reason="Allowed module subdirectory.",
            )
        )

    return merge_planned_directories(directories)


def build_files_from_context_and_module_plan(
    context: Any,
    module_plan: Any,
) -> tuple[PlannedFile, ...]:
    """Baut geplante Dateien aus Context und ModulePlan."""
    normalized_context = normalize_package_context(context)
    normalized_module_plan = normalize_module_plan(module_plan)

    files: list[PlannedFile] = []

    for relative_path in normalized_module_plan.required_files:
        module_name = infer_module_from_path_safe(relative_path) or "manifest"
        files.append(
            PlannedFile(
                relative_path=relative_path,
                absolute_path=normalized_context.package_dir / relative_path,
                module_name=module_name,
                status=PlannedFileStatus.REQUIRED.value,
                required=True,
                overwrite_allowed=normalized_context.may_overwrite,
                content_kind=infer_content_kind(relative_path),
                reason="Required file for active module.",
            )
        )

    for relative_path in normalized_module_plan.optional_files:
        module_name = infer_module_from_path_safe(relative_path)
        if module_name is None:
            continue

        files.append(
            PlannedFile(
                relative_path=relative_path,
                absolute_path=normalized_context.package_dir / relative_path,
                module_name=module_name,
                status=PlannedFileStatus.OPTIONAL.value,
                required=False,
                overwrite_allowed=normalized_context.may_overwrite,
                content_kind=infer_content_kind(relative_path),
                reason="Optional file for active module.",
            )
        )

    for relative_path in normalized_module_plan.generated_files:
        module_name = infer_module_from_path_safe(relative_path)
        if module_name is None:
            continue

        files.append(
            PlannedFile(
                relative_path=relative_path,
                absolute_path=normalized_context.package_dir / relative_path,
                module_name=module_name,
                status=PlannedFileStatus.GENERATED.value,
                required=False,
                overwrite_allowed=True,
                content_kind=infer_content_kind(relative_path),
                reason="Generated file for active module.",
            )
        )

    return merge_planned_files(files)


def merge_planned_directories(
    directories: Iterable[PlannedDirectory],
) -> tuple[PlannedDirectory, ...]:
    """Merged geplante Ordner ohne Duplikate."""
    by_path: dict[str, PlannedDirectory] = {}

    for directory in directories or ():
        normalized = directory.normalized()
        existing = by_path.get(normalized.relative_path)

        if existing is None:
            by_path[normalized.relative_path] = normalized
            continue

        by_path[normalized.relative_path] = PlannedDirectory(
            relative_path=normalized.relative_path,
            absolute_path=normalized.absolute_path,
            module_name=normalized.module_name or existing.module_name,
            required=existing.required or normalized.required,
            reason=normalized.reason or existing.reason,
        ).normalized()

    return tuple(
        by_path[key]
        for key in sorted(by_path.keys(), key=lambda value: (value != ".", value))
    )


def merge_planned_files(files: Iterable[PlannedFile]) -> tuple[PlannedFile, ...]:
    """Merged geplante Dateien ohne Duplikate."""
    by_path: dict[str, PlannedFile] = {}

    for file in files or ():
        normalized = file.normalized()
        existing = by_path.get(normalized.relative_path)

        if existing is None:
            by_path[normalized.relative_path] = normalized
            continue

        by_path[normalized.relative_path] = PlannedFile(
            relative_path=normalized.relative_path,
            absolute_path=normalized.absolute_path,
            module_name=normalized.module_name or existing.module_name,
            status=strongest_file_status(existing.status, normalized.status),
            required=existing.required or normalized.required,
            overwrite_allowed=existing.overwrite_allowed or normalized.overwrite_allowed,
            content_kind=normalized.content_kind or existing.content_kind,
            reason=normalized.reason or existing.reason,
        ).normalized()

    return tuple(
        by_path[key]
        for key in sorted(by_path.keys())
    )


def strongest_file_status(left: Any, right: Any) -> str:
    """Ermittelt den stärkeren File-Status."""
    left_value = parse_planned_file_status_value(left)
    right_value = parse_planned_file_status_value(right)

    order = {
        PlannedFileStatus.SKIPPED.value: 0,
        PlannedFileStatus.PLANNED.value: 1,
        PlannedFileStatus.OPTIONAL.value: 2,
        PlannedFileStatus.GENERATED.value: 3,
        PlannedFileStatus.ASSET.value: 4,
        PlannedFileStatus.REQUIRED.value: 5,
    }

    return left_value if order[left_value] >= order[right_value] else right_value


def package_plan_from_mapping(
    data: Mapping[str, Any],
    *,
    context: Any,
    module_plan: Any,
) -> PackagePlan:
    """Baut einen PackagePlan aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PackagePlanError("PackagePlan data must be a mapping.")

        directories = tuple(
            planned_directory_from_mapping(item)
            for item in data.get("directories", ()) or ()
            if isinstance(item, Mapping)
        )
        files = tuple(
            planned_file_from_mapping(item)
            for item in data.get("files", ()) or ()
            if isinstance(item, Mapping)
        )
        asset_copies = tuple(
            planned_asset_copy_from_mapping(item)
            for item in data.get("asset_copies", ()) or ()
            if isinstance(item, Mapping)
        )

        return PackagePlan(
            context=context,
            module_plan=module_plan,
            directories=directories,
            files=files,
            asset_copies=asset_copies,
            archive_path=data.get("archive_path"),
            validation_required=bool(data.get("validation_required", True)),
            schema_version=data.get("schema_version", PACKAGE_PLAN_SCHEMA_VERSION),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except PackagePlanError:
        raise
    except Exception as exc:
        raise PackagePlanError(f"Could not build PackagePlan from mapping: {exc}") from exc


def planned_directory_from_mapping(data: Mapping[str, Any]) -> PlannedDirectory:
    """Baut ein PlannedDirectory aus einem Mapping."""
    try:
        return PlannedDirectory(
            relative_path=data["relative_path"],
            absolute_path=data["absolute_path"],
            module_name=data.get("module_name"),
            required=bool(data.get("required", True)),
            reason=data.get("reason", ""),
        ).normalized()
    except Exception as exc:
        raise PackagePlanError(f"Could not build PlannedDirectory: {exc}") from exc


def planned_file_from_mapping(data: Mapping[str, Any]) -> PlannedFile:
    """Baut ein PlannedFile aus einem Mapping."""
    try:
        return PlannedFile(
            relative_path=data["relative_path"],
            absolute_path=data["absolute_path"],
            module_name=data["module_name"],
            status=data.get("status", PlannedFileStatus.PLANNED.value),
            required=bool(data.get("required", False)),
            overwrite_allowed=bool(data.get("overwrite_allowed", False)),
            content_kind=data.get("content_kind", "json"),
            reason=data.get("reason", ""),
        ).normalized()
    except Exception as exc:
        raise PackagePlanError(f"Could not build PlannedFile: {exc}") from exc


def planned_asset_copy_from_mapping(data: Mapping[str, Any]) -> PlannedAssetCopy:
    """Baut ein PlannedAssetCopy aus einem Mapping."""
    try:
        return PlannedAssetCopy(
            role=data["role"],
            source_path=data["source_path"],
            target_relative_path=data["target_relative_path"],
            target_absolute_path=data["target_absolute_path"],
            module_name=data.get("module_name", "render"),
            required=bool(data.get("required", False)),
            overwrite_allowed=bool(data.get("overwrite_allowed", False)),
            asset_id=data.get("asset_id"),
            mime_type=data.get("mime_type"),
            reason=data.get("reason", ""),
        ).normalized()
    except Exception as exc:
        raise PackagePlanError(f"Could not build PlannedAssetCopy: {exc}") from exc


def normalize_package_context(context: Any) -> Any:
    """Normalisiert einen PackageContext."""
    try:
        from .package_context import PackageContext

        if isinstance(context, PackageContext):
            return context.normalized()

        if hasattr(context, "normalized") and callable(context.normalized):
            return context.normalized()

        raise PackagePlanError("context must be a PackageContext.")
    except PackagePlanError:
        raise
    except Exception as exc:
        raise PackagePlanError(f"Invalid package context: {exc}") from exc


def normalize_module_plan(module_plan: Any) -> Any:
    """Normalisiert einen ModulePlan."""
    try:
        from .module_plan import ModulePlan, module_plan_from_mapping

        if isinstance(module_plan, ModulePlan):
            return module_plan.normalized()

        if isinstance(module_plan, Mapping):
            return module_plan_from_mapping(module_plan).normalized()

        if hasattr(module_plan, "normalized") and callable(module_plan.normalized):
            return module_plan.normalized()

        raise PackagePlanError("module_plan must be a ModulePlan.")
    except PackagePlanError:
        raise
    except Exception as exc:
        raise PackagePlanError(f"Invalid module plan: {exc}") from exc


def normalize_module_name(value: Any) -> str:
    """Normalisiert einen Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise PackagePlanError(f"Invalid module name {value!r}: {exc}") from exc


def normalize_optional_module_name(value: Any) -> str | None:
    """Normalisiert einen optionalen Modulnamen."""
    if value is None:
        return None

    return normalize_module_name(value)


def normalize_package_relative_path(value: Any) -> str:
    """Normalisiert einen package-relativen Pfad."""
    try:
        from ..domain.package_paths import normalize_package_path

        return normalize_package_path(value)
    except Exception as exc:
        raise PackagePlanError(f"Invalid package-relative path {value!r}: {exc}") from exc


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert einen lokalen Pfad."""
    try:
        if value is None:
            raise PackagePlanError(f"{field_name} is required.")

        return Path(value).expanduser()
    except PackagePlanError:
        raise
    except Exception as exc:
        raise PackagePlanError(f"Invalid path for {field_name}: {value!r}.") from exc


def infer_module_from_path_safe(value: Any) -> str | None:
    """Ermittelt das Modul aus einem Package-Pfad."""
    try:
        from ..domain.package_paths import infer_module_from_path

        return infer_module_from_path(value)
    except Exception:
        return None


def infer_content_kind(relative_path: Any) -> str:
    """Leitet einen einfachen Content-Kind aus dem Dateipfad ab."""
    path = str(relative_path).lower()

    if path.endswith(".json"):
        return "json"

    if path.endswith(".md"):
        return "markdown"

    if path.endswith((".glb", ".gltf")):
        return "model"

    if path.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")):
        return "image"

    if path.endswith((".ktx2", ".basis")):
        return "texture"

    return "file"


def parse_planned_path_kind_value(value: Any) -> str:
    """Parst PlannedPathKind."""
    try:
        if isinstance(value, PlannedPathKind):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return PlannedPathKind(raw).value
    except Exception as exc:
        raise PackagePlanError(f"Invalid planned path kind {value!r}.") from exc


def parse_planned_file_status_value(value: Any) -> str:
    """Parst PlannedFileStatus."""
    try:
        if isinstance(value, PlannedFileStatus):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return PlannedFileStatus(raw).value
    except Exception as exc:
        raise PackagePlanError(f"Invalid planned file status {value!r}.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise PackagePlanError(f"{field_name} is required.")

        return cleaned
    except PackagePlanError:
        raise
    except Exception as exc:
        raise PackagePlanError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_package_plan_caches() -> None:
    """Reserviert für spätere Caches; derzeit keine externen Caches."""
    return None


__all__ = [
    "PACKAGE_PLAN_SCHEMA_VERSION",
    "PackagePlan",
    "PackagePlanError",
    "PlannedAssetCopy",
    "PlannedDirectory",
    "PlannedFile",
    "PlannedFileStatus",
    "PlannedPath",
    "PlannedPathKind",
    "build_directories_from_context_and_module_plan",
    "build_files_from_context_and_module_plan",
    "build_package_plan",
    "clean_optional_string",
    "clean_required_string",
    "clear_package_plan_caches",
    "infer_content_kind",
    "infer_module_from_path_safe",
    "merge_planned_directories",
    "merge_planned_files",
    "normalize_absolute_path",
    "normalize_module_name",
    "normalize_module_plan",
    "normalize_optional_module_name",
    "normalize_package_context",
    "normalize_package_relative_path",
    "package_plan_from_mapping",
    "parse_planned_file_status_value",
    "parse_planned_path_kind_value",
    "planned_asset_copy_from_mapping",
    "planned_directory_from_mapping",
    "planned_file_from_mapping",
    "strongest_file_status",
]