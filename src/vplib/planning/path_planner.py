# services/vectoplan-library/src/vplib/planning/path_planner.py
"""
Path planner for the VPLIB package engine.

Diese Datei plant package-relative und absolute Pfade für ein modulares
VPLIB-Package.

Rolle dieser Datei:

    PackageContext
    + ModulePlan
    + optional VariantSet
    + optional AssetReferenceCollection
    -> PathPlanningResult

Diese Datei schreibt keine Dateien. Sie erzeugt nur robuste Pfadpläne für:
- Package-root directory
- module directories
- allowed subdirectories
- required files
- optional files
- generated files
- variant files
- asset target files
- optional archive path

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


PATH_PLANNER_SCHEMA_VERSION: Final[str] = "vplib.path_planner.v1"


class PathPlannerError(ValueError):
    """Wird ausgelöst, wenn Pfade nicht geplant werden können."""


class PlannedPathPurpose(str, Enum):
    """Zweck eines geplanten Pfads."""

    PACKAGE_ROOT = "package_root"
    MODULE_DIRECTORY = "module_directory"
    MODULE_SUBDIRECTORY = "module_subdirectory"
    REQUIRED_DOCUMENT = "required_document"
    OPTIONAL_DOCUMENT = "optional_document"
    GENERATED_DOCUMENT = "generated_document"
    VARIANT_DOCUMENT = "variant_document"
    ASSET_TARGET = "asset_target"
    ARCHIVE_TARGET = "archive_target"

    @property
    def key(self) -> str:
        return str(self.value)


class PlannedPathType(str, Enum):
    """Technische Pfadart."""

    DIRECTORY = "directory"
    FILE = "file"
    ARCHIVE = "archive"

    @property
    def key(self) -> str:
        return str(self.value)


class PathCollisionPolicy(str, Enum):
    """Verhalten bei bestehenden Pfaden."""

    FAIL = "fail"
    SKIP = "skip"
    OVERWRITE = "overwrite"

    @property
    def key(self) -> str:
        return str(self.value)


class PathPlanSource(str, Enum):
    """Quelle, warum ein Pfad geplant wurde."""

    CONTEXT = "context"
    MODULE_PLAN = "module_plan"
    VARIANT_SET = "variant_set"
    ASSET_COLLECTION = "asset_collection"
    OPTIONS = "options"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PathPlanningOptions:
    """Optionen für die Pfadplanung."""

    include_optional_files: bool = True
    include_generated_files: bool = True
    include_allowed_subdirectories: bool = True
    include_variant_files: bool = True
    include_asset_targets: bool = True
    include_archive_target: bool = True
    collision_policy: str = PathCollisionPolicy.FAIL.value
    validate_module_ownership: bool = True
    validate_safe_paths: bool = True
    strict: bool = True

    def normalized(self) -> "PathPlanningOptions":
        return PathPlanningOptions(
            include_optional_files=bool(self.include_optional_files),
            include_generated_files=bool(self.include_generated_files),
            include_allowed_subdirectories=bool(self.include_allowed_subdirectories),
            include_variant_files=bool(self.include_variant_files),
            include_asset_targets=bool(self.include_asset_targets),
            include_archive_target=bool(self.include_archive_target),
            collision_policy=parse_collision_policy_value(self.collision_policy),
            validate_module_ownership=bool(self.validate_module_ownership),
            validate_safe_paths=bool(self.validate_safe_paths),
            strict=bool(self.strict),
        )

    @property
    def may_overwrite(self) -> bool:
        return self.normalized().collision_policy == PathCollisionPolicy.OVERWRITE.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "include_optional_files": normalized.include_optional_files,
            "include_generated_files": normalized.include_generated_files,
            "include_allowed_subdirectories": normalized.include_allowed_subdirectories,
            "include_variant_files": normalized.include_variant_files,
            "include_asset_targets": normalized.include_asset_targets,
            "include_archive_target": normalized.include_archive_target,
            "collision_policy": normalized.collision_policy,
            "validate_module_ownership": normalized.validate_module_ownership,
            "validate_safe_paths": normalized.validate_safe_paths,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class PlannedPathRecord:
    """Ein geplanter Pfad."""

    relative_path: str
    absolute_path: Path
    path_type: str
    purpose: str
    source: str
    module_name: str | None = None
    required: bool = False
    generated: bool = False
    overwrite_allowed: bool = False
    create_parent_directories: bool = True
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self, *, options: PathPlanningOptions | None = None) -> "PlannedPathRecord":
        normalized_options = (options or PathPlanningOptions()).normalized()
        relative_path = normalize_relative_path(self.relative_path)
        absolute_path = normalize_absolute_path(self.absolute_path, "absolute_path")
        path_type = parse_path_type_value(self.path_type)
        purpose = parse_path_purpose_value(self.purpose)
        source = parse_path_plan_source_value(self.source)
        module_name = normalize_optional_module_name(self.module_name)
        required = bool(self.required)
        generated = bool(self.generated)
        overwrite_allowed = bool(self.overwrite_allowed or normalized_options.may_overwrite)
        create_parent_directories = bool(self.create_parent_directories)
        reason = clean_optional_string(self.reason) or ""
        metadata = normalize_metadata(self.metadata)

        if normalized_options.validate_safe_paths:
            assert_safe_relative_path(relative_path)

        if normalized_options.validate_module_ownership and module_name:
            if path_type != PlannedPathType.ARCHIVE.value and relative_path != ".":
                if not is_path_under_module_safe(relative_path, module_name):
                    raise PathPlannerError(
                        f"Path {relative_path!r} is not under module {module_name!r}."
                    )

        if purpose in {
            PlannedPathPurpose.REQUIRED_DOCUMENT.value,
            PlannedPathPurpose.VARIANT_DOCUMENT.value,
        }:
            required = True

        if purpose == PlannedPathPurpose.GENERATED_DOCUMENT.value:
            generated = True

        if purpose == PlannedPathPurpose.PACKAGE_ROOT.value:
            path_type = PlannedPathType.DIRECTORY.value
            required = True

        if purpose == PlannedPathPurpose.ARCHIVE_TARGET.value:
            path_type = PlannedPathType.ARCHIVE.value

        return PlannedPathRecord(
            relative_path=relative_path,
            absolute_path=absolute_path,
            path_type=path_type,
            purpose=purpose,
            source=source,
            module_name=module_name,
            required=required,
            generated=generated,
            overwrite_allowed=overwrite_allowed,
            create_parent_directories=create_parent_directories,
            reason=reason,
            metadata=metadata,
        )

    @property
    def is_directory(self) -> bool:
        return self.normalized().path_type == PlannedPathType.DIRECTORY.value

    @property
    def is_file(self) -> bool:
        return self.normalized().path_type == PlannedPathType.FILE.value

    @property
    def is_archive(self) -> bool:
        return self.normalized().path_type == PlannedPathType.ARCHIVE.value

    @property
    def parent_directory(self) -> Path:
        normalized = self.normalized()
        return normalized.absolute_path if normalized.is_directory else normalized.absolute_path.parent

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "absolute_path": str(normalized.absolute_path),
            "path_type": normalized.path_type,
            "purpose": normalized.purpose,
            "source": normalized.source,
            "module_name": normalized.module_name,
            "required": normalized.required,
            "generated": normalized.generated,
            "overwrite_allowed": normalized.overwrite_allowed,
            "create_parent_directories": normalized.create_parent_directories,
            "reason": normalized.reason,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class PathPlanningResult:
    """Ergebnis der Pfadplanung."""

    package_dir: Path
    records: tuple[PlannedPathRecord, ...]
    options: PathPlanningOptions = field(default_factory=PathPlanningOptions)
    archive_path: Path | None = None
    schema_version: str = PATH_PLANNER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PathPlanningResult":
        options = self.options.normalized()
        package_dir = normalize_absolute_path(self.package_dir, "package_dir")
        archive_path = (
            normalize_absolute_path(self.archive_path, "archive_path")
            if self.archive_path is not None
            else None
        )
        metadata = normalize_metadata(self.metadata)

        records = tuple(
            record.normalized(options=options)
            for record in self.records or ()
        )
        records = dedupe_path_records(records, options=options)
        records = sort_path_records(records)

        result = PathPlanningResult(
            package_dir=package_dir,
            records=records,
            options=options,
            archive_path=archive_path,
            schema_version=self.schema_version or PATH_PLANNER_SCHEMA_VERSION,
            metadata=metadata,
        )

        valid, messages = result.validate()
        if not valid:
            raise PathPlannerError(" ".join(messages))

        return result

    @property
    def directories(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(record for record in self.normalized().records if record.is_directory)

    @property
    def files(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(record for record in self.normalized().records if record.is_file)

    @property
    def archives(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(record for record in self.normalized().records if record.is_archive)

    @property
    def required_files(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(record for record in self.files if record.required)

    @property
    def optional_files(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(record for record in self.files if not record.required)

    @property
    def generated_files(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(record for record in self.files if record.generated)

    @property
    def asset_targets(self) -> tuple[PlannedPathRecord, ...]:
        return tuple(
            record
            for record in self.normalized().records
            if record.purpose == PlannedPathPurpose.ASSET_TARGET.value
        )

    @property
    def relative_paths(self) -> tuple[str, ...]:
        return tuple(record.relative_path for record in self.normalized().records)

    @property
    def absolute_paths(self) -> tuple[Path, ...]:
        return tuple(record.absolute_path for record in self.normalized().records)

    def by_module(self, module_name: Any) -> tuple[PlannedPathRecord, ...]:
        module_value = normalize_module_name(module_name)

        return tuple(
            record
            for record in self.normalized().records
            if record.module_name == module_value
        )

    def by_purpose(self, purpose: Any) -> tuple[PlannedPathRecord, ...]:
        purpose_value = parse_path_purpose_value(purpose)

        return tuple(
            record
            for record in self.normalized().records
            if record.purpose == purpose_value
        )

    def has_relative_path(self, relative_path: Any) -> bool:
        path = normalize_relative_path(relative_path)
        return path in set(self.relative_paths)

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        messages: list[str] = []

        try:
            package_dir = normalize_absolute_path(self.package_dir, "package_dir")
            seen: set[str] = set()

            for record in self.records or ():
                normalized = record.normalized(options=self.options)

                if normalized.relative_path in seen:
                    messages.append(f"Duplicate planned path {normalized.relative_path!r}.")
                seen.add(normalized.relative_path)

                if normalized.absolute_path != package_dir and not is_child_path(
                    normalized.absolute_path,
                    package_dir,
                ):
                    if normalized.purpose != PlannedPathPurpose.ARCHIVE_TARGET.value:
                        messages.append(
                            f"Planned path {str(normalized.absolute_path)!r} is outside package_dir."
                        )

                if normalized.is_file and not normalized.absolute_path.suffix:
                    messages.append(f"Planned file has no file extension: {normalized.relative_path!r}.")

                if normalized.is_directory and normalized.absolute_path.suffix:
                    messages.append(
                        f"Planned directory looks like a file path: {normalized.relative_path!r}."
                    )

        except PathPlannerError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate path planning result: {exc}")

        return len(messages) == 0, tuple(messages)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "package_dir": str(normalized.package_dir),
            "archive_path": str(normalized.archive_path) if normalized.archive_path else None,
            "record_count": len(normalized.records),
            "directory_count": len(normalized.directories),
            "file_count": len(normalized.files),
            "archive_count": len(normalized.archives),
            "required_file_count": len(normalized.required_files),
            "optional_file_count": len(normalized.optional_files),
            "generated_file_count": len(normalized.generated_files),
            "asset_target_count": len(normalized.asset_targets),
            "options": normalized.options.to_dict(),
            "records": [record.to_dict() for record in normalized.records],
            "metadata": dict(normalized.metadata),
        }


def plan_paths_for_package(
    *,
    context: Any,
    module_plan: Any,
    variant_set: Any | None = None,
    asset_collection: Any | None = None,
    options: PathPlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PathPlanningResult:
    """Hauptfunktion für die packagebezogene Pfadplanung."""
    try:
        normalized_context = normalize_package_context(context)
        normalized_module_plan = normalize_module_plan(module_plan)
        normalized_options = normalize_options(options)

        records: list[PlannedPathRecord] = []

        records.extend(
            build_package_root_records(
                context=normalized_context,
                options=normalized_options,
            )
        )
        records.extend(
            build_module_directory_records(
                context=normalized_context,
                module_plan=normalized_module_plan,
                options=normalized_options,
            )
        )
        records.extend(
            build_module_file_records(
                context=normalized_context,
                module_plan=normalized_module_plan,
                options=normalized_options,
            )
        )

        if normalized_options.include_variant_files and variant_set is not None:
            records.extend(
                build_variant_file_records(
                    context=normalized_context,
                    variant_set=variant_set,
                    options=normalized_options,
                )
            )

        if normalized_options.include_asset_targets and asset_collection is not None:
            records.extend(
                build_asset_target_records(
                    context=normalized_context,
                    asset_collection=asset_collection,
                    options=normalized_options,
                )
            )

        archive_path = None
        if normalized_options.include_archive_target and normalized_context.archive_path is not None:
            archive_path = normalized_context.archive_path
            records.append(
                PlannedPathRecord(
                    relative_path=archive_path.name,
                    absolute_path=archive_path,
                    path_type=PlannedPathType.ARCHIVE.value,
                    purpose=PlannedPathPurpose.ARCHIVE_TARGET.value,
                    source=PathPlanSource.CONTEXT.value,
                    module_name=None,
                    required=False,
                    generated=True,
                    overwrite_allowed=normalized_options.may_overwrite,
                    create_parent_directories=True,
                    reason="Optional .vplib archive target.",
                ).normalized(options=normalized_options)
            )

        return PathPlanningResult(
            package_dir=normalized_context.package_dir,
            records=tuple(records),
            options=normalized_options,
            archive_path=archive_path,
            metadata={
                "planned_by": "path_planner",
                **dict(metadata or {}),
            },
        ).normalized()
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Could not plan package paths: {exc}") from exc


def build_package_root_records(
    *,
    context: Any,
    options: PathPlanningOptions,
) -> tuple[PlannedPathRecord, ...]:
    """Plant den Package-Root-Ordner."""
    normalized_context = normalize_package_context(context)

    return (
        PlannedPathRecord(
            relative_path=".",
            absolute_path=normalized_context.package_dir,
            path_type=PlannedPathType.DIRECTORY.value,
            purpose=PlannedPathPurpose.PACKAGE_ROOT.value,
            source=PathPlanSource.CONTEXT.value,
            module_name=None,
            required=True,
            generated=False,
            overwrite_allowed=True,
            create_parent_directories=True,
            reason="Package root directory.",
        ).normalized(options=options),
    )


def build_module_directory_records(
    *,
    context: Any,
    module_plan: Any,
    options: PathPlanningOptions,
) -> tuple[PlannedPathRecord, ...]:
    """Plant Modulordner und erlaubte Unterordner."""
    normalized_context = normalize_package_context(context)
    normalized_module_plan = normalize_module_plan(module_plan)
    records: list[PlannedPathRecord] = []

    for relative_path in normalized_module_plan.directories:
        module_name = infer_module_from_path_safe(relative_path)
        records.append(
            PlannedPathRecord(
                relative_path=relative_path,
                absolute_path=normalized_context.package_dir / relative_path,
                path_type=PlannedPathType.DIRECTORY.value,
                purpose=PlannedPathPurpose.MODULE_DIRECTORY.value,
                source=PathPlanSource.MODULE_PLAN.value,
                module_name=module_name,
                required=True,
                generated=False,
                overwrite_allowed=True,
                create_parent_directories=True,
                reason="Active module directory.",
            ).normalized(options=options)
        )

    if options.include_allowed_subdirectories:
        for relative_path in normalized_module_plan.allowed_subdirectories:
            module_name = infer_module_from_path_safe(relative_path)
            records.append(
                PlannedPathRecord(
                    relative_path=relative_path,
                    absolute_path=normalized_context.package_dir / relative_path,
                    path_type=PlannedPathType.DIRECTORY.value,
                    purpose=PlannedPathPurpose.MODULE_SUBDIRECTORY.value,
                    source=PathPlanSource.MODULE_PLAN.value,
                    module_name=module_name,
                    required=False,
                    generated=False,
                    overwrite_allowed=True,
                    create_parent_directories=True,
                    reason="Allowed module subdirectory.",
                ).normalized(options=options)
            )

    return tuple(records)


def build_module_file_records(
    *,
    context: Any,
    module_plan: Any,
    options: PathPlanningOptions,
) -> tuple[PlannedPathRecord, ...]:
    """Plant Required-, Optional- und Generated-Dateien aus dem ModulePlan."""
    normalized_context = normalize_package_context(context)
    normalized_module_plan = normalize_module_plan(module_plan)
    records: list[PlannedPathRecord] = []

    for relative_path in normalized_module_plan.required_files:
        module_name = infer_module_from_path_safe(relative_path)
        records.append(
            PlannedPathRecord(
                relative_path=relative_path,
                absolute_path=normalized_context.package_dir / relative_path,
                path_type=PlannedPathType.FILE.value,
                purpose=PlannedPathPurpose.REQUIRED_DOCUMENT.value,
                source=PathPlanSource.MODULE_PLAN.value,
                module_name=module_name,
                required=True,
                generated=False,
                overwrite_allowed=options.may_overwrite,
                create_parent_directories=True,
                reason="Required file for active module.",
            ).normalized(options=options)
        )

    if options.include_optional_files:
        for relative_path in normalized_module_plan.optional_files:
            module_name = infer_module_from_path_safe(relative_path)
            records.append(
                PlannedPathRecord(
                    relative_path=relative_path,
                    absolute_path=normalized_context.package_dir / relative_path,
                    path_type=PlannedPathType.FILE.value,
                    purpose=PlannedPathPurpose.OPTIONAL_DOCUMENT.value,
                    source=PathPlanSource.MODULE_PLAN.value,
                    module_name=module_name,
                    required=False,
                    generated=False,
                    overwrite_allowed=options.may_overwrite,
                    create_parent_directories=True,
                    reason="Optional file for active module.",
                ).normalized(options=options)
            )

    if options.include_generated_files:
        for relative_path in normalized_module_plan.generated_files:
            module_name = infer_module_from_path_safe(relative_path)
            records.append(
                PlannedPathRecord(
                    relative_path=relative_path,
                    absolute_path=normalized_context.package_dir / relative_path,
                    path_type=PlannedPathType.FILE.value,
                    purpose=PlannedPathPurpose.GENERATED_DOCUMENT.value,
                    source=PathPlanSource.MODULE_PLAN.value,
                    module_name=module_name,
                    required=False,
                    generated=True,
                    overwrite_allowed=True,
                    create_parent_directories=True,
                    reason="Generated file for active module.",
                ).normalized(options=options)
            )

    return tuple(records)


def build_variant_file_records(
    *,
    context: Any,
    variant_set: Any,
    options: PathPlanningOptions,
) -> tuple[PlannedPathRecord, ...]:
    """Plant zusätzliche Varianten-Dateien."""
    normalized_context = normalize_package_context(context)
    normalized_variant_set = normalize_variant_set(variant_set)
    records: list[PlannedPathRecord] = []

    for variant_id in normalized_variant_set.variant_ids:
        relative_path = make_variant_file_path_safe(variant_id)

        records.append(
            PlannedPathRecord(
                relative_path=relative_path,
                absolute_path=normalized_context.package_dir / relative_path,
                path_type=PlannedPathType.FILE.value,
                purpose=PlannedPathPurpose.VARIANT_DOCUMENT.value,
                source=PathPlanSource.VARIANT_SET.value,
                module_name="variants",
                required=True,
                generated=False,
                overwrite_allowed=options.may_overwrite,
                create_parent_directories=True,
                reason="Variant document.",
                metadata={
                    "variant_id": variant_id,
                    "default_variant": variant_id == normalized_variant_set.default_variant_id,
                },
            ).normalized(options=options)
        )

    return tuple(records)


def build_asset_target_records(
    *,
    context: Any,
    asset_collection: Any,
    options: PathPlanningOptions,
) -> tuple[PlannedPathRecord, ...]:
    """Plant Asset-Zielpfade aus einer AssetReferenceCollection."""
    normalized_context = normalize_package_context(context)
    normalized_collection = normalize_asset_collection(asset_collection)
    records: list[PlannedPathRecord] = []

    for asset in normalized_collection.assets:
        if not asset.target:
            continue

        records.append(
            PlannedPathRecord(
                relative_path=asset.target.package_path,
                absolute_path=normalized_context.package_dir / asset.target.package_path,
                path_type=PlannedPathType.FILE.value,
                purpose=PlannedPathPurpose.ASSET_TARGET.value,
                source=PathPlanSource.ASSET_COLLECTION.value,
                module_name=asset.target.module_name,
                required=asset.required,
                generated=False,
                overwrite_allowed=asset.target.overwrite_allowed or options.may_overwrite,
                create_parent_directories=True,
                reason=f"Asset target for role {asset.role}.",
                metadata={
                    "asset_id": asset.asset_id,
                    "asset_role": asset.role,
                    "asset_type": asset.asset_type,
                    "mime_type": asset.mime_type,
                },
            ).normalized(options=options)
        )

    return tuple(records)


def dedupe_path_records(
    records: Iterable[PlannedPathRecord],
    *,
    options: PathPlanningOptions,
) -> tuple[PlannedPathRecord, ...]:
    """Dedupliziert Pfadrecords anhand des relativen Pfads."""
    by_path: dict[str, PlannedPathRecord] = {}

    for record in records or ():
        normalized = record.normalized(options=options)
        existing = by_path.get(normalized.relative_path)

        if existing is None:
            by_path[normalized.relative_path] = normalized
            continue

        by_path[normalized.relative_path] = merge_path_records(existing, normalized, options=options)

    return tuple(by_path.values())


def merge_path_records(
    left: PlannedPathRecord,
    right: PlannedPathRecord,
    *,
    options: PathPlanningOptions,
) -> PlannedPathRecord:
    """Merged zwei Pfadrecords desselben relativen Pfads."""
    left_normalized = left.normalized(options=options)
    right_normalized = right.normalized(options=options)

    if left_normalized.relative_path != right_normalized.relative_path:
        raise PathPlannerError(
            f"Cannot merge different planned paths: "
            f"{left_normalized.relative_path!r}, {right_normalized.relative_path!r}."
        )

    if left_normalized.path_type != right_normalized.path_type:
        if {left_normalized.path_type, right_normalized.path_type} != {PlannedPathType.FILE.value, PlannedPathType.ARCHIVE.value}:
            raise PathPlannerError(
                f"Planned path {left_normalized.relative_path!r} has conflicting path types."
            )

    return PlannedPathRecord(
        relative_path=left_normalized.relative_path,
        absolute_path=right_normalized.absolute_path,
        path_type=right_normalized.path_type or left_normalized.path_type,
        purpose=stronger_path_purpose(left_normalized.purpose, right_normalized.purpose),
        source=right_normalized.source or left_normalized.source,
        module_name=right_normalized.module_name or left_normalized.module_name,
        required=left_normalized.required or right_normalized.required,
        generated=left_normalized.generated or right_normalized.generated,
        overwrite_allowed=left_normalized.overwrite_allowed or right_normalized.overwrite_allowed,
        create_parent_directories=left_normalized.create_parent_directories or right_normalized.create_parent_directories,
        reason=right_normalized.reason or left_normalized.reason,
        metadata={
            **dict(left_normalized.metadata),
            **dict(right_normalized.metadata),
        },
    ).normalized(options=options)


def stronger_path_purpose(left: str, right: str) -> str:
    """Ermittelt den stärkeren Pfadzweck."""
    left_value = parse_path_purpose_value(left)
    right_value = parse_path_purpose_value(right)

    order = {
        PlannedPathPurpose.PACKAGE_ROOT.value: 100,
        PlannedPathPurpose.MODULE_DIRECTORY.value: 90,
        PlannedPathPurpose.MODULE_SUBDIRECTORY.value: 80,
        PlannedPathPurpose.REQUIRED_DOCUMENT.value: 70,
        PlannedPathPurpose.VARIANT_DOCUMENT.value: 65,
        PlannedPathPurpose.ASSET_TARGET.value: 60,
        PlannedPathPurpose.GENERATED_DOCUMENT.value: 50,
        PlannedPathPurpose.OPTIONAL_DOCUMENT.value: 40,
        PlannedPathPurpose.ARCHIVE_TARGET.value: 30,
    }

    return left_value if order[left_value] >= order[right_value] else right_value


def sort_path_records(records: Iterable[PlannedPathRecord]) -> tuple[PlannedPathRecord, ...]:
    """Sortiert Pfadrecords stabil."""
    return tuple(
        sorted(
            (record.normalized() for record in records or ()),
            key=lambda record: (
                path_type_order(record.path_type),
                purpose_order(record.purpose),
                record.module_name or "",
                record.relative_path,
            ),
        )
    )


def path_type_order(path_type: str) -> int:
    """Sortierwert für Pfadtypen."""
    value = parse_path_type_value(path_type)
    return {
        PlannedPathType.DIRECTORY.value: 10,
        PlannedPathType.FILE.value: 20,
        PlannedPathType.ARCHIVE.value: 30,
    }.get(value, 99)


def purpose_order(purpose: str) -> int:
    """Sortierwert für Pfadzwecke."""
    value = parse_path_purpose_value(purpose)
    return {
        PlannedPathPurpose.PACKAGE_ROOT.value: 10,
        PlannedPathPurpose.MODULE_DIRECTORY.value: 20,
        PlannedPathPurpose.MODULE_SUBDIRECTORY.value: 30,
        PlannedPathPurpose.REQUIRED_DOCUMENT.value: 40,
        PlannedPathPurpose.VARIANT_DOCUMENT.value: 45,
        PlannedPathPurpose.OPTIONAL_DOCUMENT.value: 50,
        PlannedPathPurpose.GENERATED_DOCUMENT.value: 60,
        PlannedPathPurpose.ASSET_TARGET.value: 70,
        PlannedPathPurpose.ARCHIVE_TARGET.value: 80,
    }.get(value, 99)


def path_planning_result_from_mapping(data: Mapping[str, Any]) -> PathPlanningResult:
    """Baut ein PathPlanningResult aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PathPlannerError("PathPlanningResult data must be a mapping.")

        records = tuple(
            planned_path_record_from_mapping(item)
            for item in data.get("records", ()) or ()
            if isinstance(item, Mapping)
        )

        return PathPlanningResult(
            package_dir=data.get("package_dir"),
            records=records,
            options=path_planning_options_from_mapping(data.get("options", {}) or {}),
            archive_path=data.get("archive_path"),
            schema_version=data.get("schema_version", PATH_PLANNER_SCHEMA_VERSION),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Could not build PathPlanningResult from mapping: {exc}") from exc


def planned_path_record_from_mapping(data: Mapping[str, Any]) -> PlannedPathRecord:
    """Baut ein PlannedPathRecord aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PathPlannerError("PlannedPathRecord data must be a mapping.")

        return PlannedPathRecord(
            relative_path=data.get("relative_path"),
            absolute_path=data.get("absolute_path"),
            path_type=data.get("path_type"),
            purpose=data.get("purpose"),
            source=data.get("source", PathPlanSource.SYSTEM.value),
            module_name=data.get("module_name"),
            required=bool(data.get("required", False)),
            generated=bool(data.get("generated", False)),
            overwrite_allowed=bool(data.get("overwrite_allowed", False)),
            create_parent_directories=bool(data.get("create_parent_directories", True)),
            reason=data.get("reason", ""),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Could not build PlannedPathRecord from mapping: {exc}") from exc


def path_planning_options_from_mapping(data: Mapping[str, Any]) -> PathPlanningOptions:
    """Baut PathPlanningOptions aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PathPlannerError("PathPlanningOptions data must be a mapping.")

        return PathPlanningOptions(
            include_optional_files=bool(data.get("include_optional_files", True)),
            include_generated_files=bool(data.get("include_generated_files", True)),
            include_allowed_subdirectories=bool(data.get("include_allowed_subdirectories", True)),
            include_variant_files=bool(data.get("include_variant_files", True)),
            include_asset_targets=bool(data.get("include_asset_targets", True)),
            include_archive_target=bool(data.get("include_archive_target", True)),
            collision_policy=data.get("collision_policy", PathCollisionPolicy.FAIL.value),
            validate_module_ownership=bool(data.get("validate_module_ownership", True)),
            validate_safe_paths=bool(data.get("validate_safe_paths", True)),
            strict=bool(data.get("strict", True)),
        ).normalized()
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Could not build PathPlanningOptions from mapping: {exc}") from exc


def normalize_options(
    options: PathPlanningOptions | Mapping[str, Any] | None,
) -> PathPlanningOptions:
    """Normalisiert PathPlanningOptions."""
    if options is None:
        return PathPlanningOptions().normalized()

    if isinstance(options, PathPlanningOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return path_planning_options_from_mapping(options)

    raise PathPlannerError("options must be PathPlanningOptions, mapping or None.")


def normalize_package_context(value: Any) -> Any:
    """Normalisiert PackageContext."""
    try:
        from ..models.package_context import PackageContext

        if isinstance(value, PackageContext):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise PathPlannerError("PackageContext value is required.")
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Invalid PackageContext: {exc}") from exc


def normalize_module_plan(value: Any) -> Any:
    """Normalisiert ModulePlan."""
    try:
        from ..models.module_plan import ModulePlan, module_plan_from_mapping

        if isinstance(value, ModulePlan):
            return value.normalized()

        if isinstance(value, Mapping):
            return module_plan_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise PathPlannerError("ModulePlan value is required.")
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Invalid ModulePlan: {exc}") from exc


def normalize_variant_set(value: Any) -> Any:
    """Normalisiert VariantSet."""
    try:
        from ..models.variant_definition import VariantSet, variant_set_from_mapping

        if isinstance(value, VariantSet):
            return value.normalized()

        if isinstance(value, Mapping):
            return variant_set_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise PathPlannerError("VariantSet value is required.")
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Invalid VariantSet: {exc}") from exc


def normalize_asset_collection(value: Any) -> Any:
    """Normalisiert AssetReferenceCollection."""
    try:
        from ..models.asset_reference import (
            AssetReferenceCollection,
            asset_references_from_iterable,
        )

        if isinstance(value, AssetReferenceCollection):
            return value.normalized()

        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            return asset_references_from_iterable(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise PathPlannerError("AssetReferenceCollection value is required.")
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Invalid AssetReferenceCollection: {exc}") from exc


def normalize_module_name(value: Any) -> str:
    """Normalisiert einen Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise PathPlannerError(f"Invalid module name {value!r}: {exc}") from exc


def normalize_optional_module_name(value: Any) -> str | None:
    """Normalisiert einen optionalen Modulnamen."""
    if value is None:
        return None

    return normalize_module_name(value)


def normalize_relative_path(value: Any) -> str:
    """Normalisiert package-relative Pfade."""
    if value == ".":
        return "."

    try:
        from ..domain.package_paths import normalize_package_path

        return normalize_package_path(value)
    except Exception as exc:
        raise PathPlannerError(f"Invalid relative package path {value!r}: {exc}") from exc


def assert_safe_relative_path(value: Any) -> None:
    """Prüft package-relative Pfadsicherheit."""
    if value == ".":
        return

    try:
        from ..domain.package_paths import assert_safe_package_file_path, normalize_package_path

        normalized = normalize_package_path(value)
        if Path(normalized).suffix:
            assert_safe_package_file_path(normalized)
    except Exception as exc:
        raise PathPlannerError(f"Unsafe relative package path {value!r}: {exc}") from exc


def make_variant_file_path_safe(variant_id: Any) -> str:
    """Baut sicheren Variant-Dateipfad."""
    try:
        from ..domain.package_paths import make_variant_file_path

        return make_variant_file_path(variant_id)
    except Exception as exc:
        raise PathPlannerError(f"Could not build variant file path for {variant_id!r}: {exc}") from exc


def is_path_under_module_safe(path: Any, module_name: Any) -> bool:
    """Prüft, ob ein Pfad unter dem Modul liegt."""
    try:
        from ..domain.package_paths import is_path_under_module

        return is_path_under_module(path, module_name)
    except Exception:
        return False


def infer_module_from_path_safe(path: Any) -> str | None:
    """Leitet Modul aus Pfad ab."""
    try:
        from ..domain.package_paths import infer_module_from_path

        return infer_module_from_path(path)
    except Exception:
        return None


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert lokalen Pfad."""
    try:
        if value is None:
            raise PathPlannerError(f"{field_name} is required.")

        return Path(value).expanduser()
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Invalid path for {field_name}: {value!r}.") from exc


def is_child_path(path: Path, parent: Path) -> bool:
    """Prüft, ob path unter parent liegt."""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


@lru_cache(maxsize=128)
def parse_path_purpose_value(value: Any) -> str:
    """Parst PlannedPathPurpose."""
    try:
        if isinstance(value, PlannedPathPurpose):
            return value.value

        raw = normalize_enum_key(value)
        return PlannedPathPurpose(raw).value
    except Exception as exc:
        raise PathPlannerError(f"Invalid planned path purpose {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_path_type_value(value: Any) -> str:
    """Parst PlannedPathType."""
    try:
        if isinstance(value, PlannedPathType):
            return value.value

        raw = normalize_enum_key(value)
        return PlannedPathType(raw).value
    except Exception as exc:
        raise PathPlannerError(f"Invalid planned path type {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_collision_policy_value(value: Any) -> str:
    """Parst PathCollisionPolicy."""
    try:
        if isinstance(value, PathCollisionPolicy):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "fail": PathCollisionPolicy.FAIL.value,
            "error": PathCollisionPolicy.FAIL.value,
            "strict": PathCollisionPolicy.FAIL.value,
            "skip": PathCollisionPolicy.SKIP.value,
            "ignore": PathCollisionPolicy.SKIP.value,
            "overwrite": PathCollisionPolicy.OVERWRITE.value,
            "replace": PathCollisionPolicy.OVERWRITE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return PathCollisionPolicy(raw).value
    except Exception as exc:
        raise PathPlannerError(f"Invalid path collision policy {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_path_plan_source_value(value: Any) -> str:
    """Parst PathPlanSource."""
    try:
        if isinstance(value, PathPlanSource):
            return value.value

        raw = normalize_enum_key(value)
        return PathPlanSource(raw).value
    except Exception as exc:
        raise PathPlannerError(f"Invalid path plan source {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise PathPlannerError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except PathPlannerError:
        raise
    except Exception as exc:
        raise PathPlannerError(f"Invalid enum value {value!r}.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise PathPlannerError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert einen Metadata-Wert JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clear_path_planner_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_path_purpose_value.cache_clear()
    parse_path_type_value.cache_clear()
    parse_collision_policy_value.cache_clear()
    parse_path_plan_source_value.cache_clear()


__all__ = [
    "PATH_PLANNER_SCHEMA_VERSION",
    "PathCollisionPolicy",
    "PathPlanSource",
    "PathPlannerError",
    "PathPlanningOptions",
    "PathPlanningResult",
    "PlannedPathPurpose",
    "PlannedPathRecord",
    "PlannedPathType",
    "assert_safe_relative_path",
    "build_asset_target_records",
    "build_module_directory_records",
    "build_module_file_records",
    "build_package_root_records",
    "build_variant_file_records",
    "clean_optional_string",
    "clear_path_planner_caches",
    "dedupe_path_records",
    "infer_module_from_path_safe",
    "is_child_path",
    "is_path_under_module_safe",
    "make_variant_file_path_safe",
    "merge_path_records",
    "normalize_absolute_path",
    "normalize_asset_collection",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_module_name",
    "normalize_module_plan",
    "normalize_optional_module_name",
    "normalize_options",
    "normalize_package_context",
    "normalize_relative_path",
    "normalize_variant_set",
    "parse_collision_policy_value",
    "parse_path_plan_source_value",
    "parse_path_purpose_value",
    "parse_path_type_value",
    "path_planning_options_from_mapping",
    "path_planning_result_from_mapping",
    "path_type_order",
    "plan_paths_for_package",
    "planned_path_record_from_mapping",
    "purpose_order",
    "sort_path_records",
    "stronger_path_purpose",
]