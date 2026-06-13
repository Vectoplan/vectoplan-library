# services/vectoplan-library/src/vplib/creators/package_creator.py
"""
Package creator for the VPLIB package engine.

Diese Datei orchestriert den vollständigen Erstellungsvorgang eines VPLIB-Packages.

Rolle dieser Datei:

    CreateRequest / CreationPlan / DocumentBundle
    -> validate
    -> create package directories
    -> write JSON documents
    -> copy assets
    -> optional create .vplib archive
    -> PackageCreationResult

Diese Datei ist der stabile Einstieg für spätere Routen und Services.
Die eigentliche Dateioperation wird an file_writer.py delegiert.

Wichtig für die neue VPLIB-ID-Architektur:
- Die eigentliche `vplib_uid` entsteht im Manifest-/DocumentBundle-Flow.
- Diese Datei erzeugt die ID nicht selbst neu, sondern liest sie aus dem Bundle.
- PackageCreationResult gibt `vplib_uid` explizit zurück.
- Damit kann `/create` die ID nach draft/package-plan/download/save im Frontend halten.
- Die Datenbank übernimmt diese ID später nur und erzeugt sie nicht.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Mapping


PACKAGE_CREATOR_SCHEMA_VERSION: Final[str] = "vplib.package_creator.v1"
MANIFEST_DOCUMENT_PATH: Final[str] = "vplib.manifest.json"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"


class PackageCreatorError(RuntimeError):
    """Wird ausgelöst, wenn ein VPLIB-Package nicht erstellt werden kann."""


class PackageCreationStatus(str, Enum):
    """Status einer Package-Erstellung."""

    CREATED = "created"
    DRY_RUN = "dry_run"
    SKIPPED = "skipped"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


class PackageCreationStage(str, Enum):
    """Stufe der Package-Erstellung."""

    PLAN = "plan"
    DOCUMENTS = "documents"
    VALIDATE_BEFORE_WRITE = "validate_before_write"
    CREATE_DIRECTORIES = "create_directories"
    WRITE_DOCUMENTS = "write_documents"
    COPY_ASSETS = "copy_assets"
    CREATE_ARCHIVE = "create_archive"
    VALIDATE_AFTER_WRITE = "validate_after_write"
    FINISH = "finish"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PackageCreationOptions:
    """Optionen für die VPLIB-Package-Erstellung."""

    write_mode: str = "fail"
    dry_run: bool = False
    validate_before_write: bool = True
    validate_after_write: bool = False
    write_documents: bool = True
    copy_assets: bool = True
    create_directories: bool = True
    create_archive: bool = False
    include_optional_documents: bool = True
    include_generated_documents: bool = True
    atomic_writes: bool = True
    backup_existing: bool = False
    fail_on_validation_error: bool = True
    fail_on_asset_copy_error: bool = True
    strict: bool = True
    validation_mode: str = "strict"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageCreationOptions":
        return PackageCreationOptions(
            write_mode=normalize_write_mode(self.write_mode),
            dry_run=bool(self.dry_run),
            validate_before_write=bool(self.validate_before_write),
            validate_after_write=bool(self.validate_after_write),
            write_documents=bool(self.write_documents),
            copy_assets=bool(self.copy_assets),
            create_directories=bool(self.create_directories),
            create_archive=bool(self.create_archive),
            include_optional_documents=bool(self.include_optional_documents),
            include_generated_documents=bool(self.include_generated_documents),
            atomic_writes=bool(self.atomic_writes),
            backup_existing=bool(self.backup_existing),
            fail_on_validation_error=bool(self.fail_on_validation_error),
            fail_on_asset_copy_error=bool(self.fail_on_asset_copy_error),
            strict=bool(self.strict),
            validation_mode=clean_required_string(self.validation_mode or "strict", "validation_mode"),
            metadata=normalize_metadata(self.metadata),
        )

    def to_file_write_options(self) -> Any:
        """Baut FileWriteOptions für file_writer.py."""
        from .file_writer import FileWriteOptions

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

    def to_document_bundle_options(self) -> Any:
        """Baut DocumentBundleOptions für defaults/document_bundle.py."""
        from ..defaults.document_bundle import DocumentBundleOptions

        normalized = self.normalized()

        return DocumentBundleOptions(
            include_optional=normalized.include_optional_documents,
            include_generated=normalized.include_generated_documents,
            strict=normalized.strict,
        ).normalized()

    def to_validation_options(self) -> Any:
        """Baut PackageValidationOptions für validators/package_validator.py."""
        from ..validators.package_validator import PackageValidationOptions

        normalized = self.normalized()

        return PackageValidationOptions(
            mode=normalized.validation_mode,
            validate_schema=True,
            validate_semantics=True,
            validate_assets=True,
            validate_package_plan=True,
            strict=normalized.strict,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "write_mode": normalized.write_mode,
            "dry_run": normalized.dry_run,
            "validate_before_write": normalized.validate_before_write,
            "validate_after_write": normalized.validate_after_write,
            "write_documents": normalized.write_documents,
            "copy_assets": normalized.copy_assets,
            "create_directories": normalized.create_directories,
            "create_archive": normalized.create_archive,
            "include_optional_documents": normalized.include_optional_documents,
            "include_generated_documents": normalized.include_generated_documents,
            "atomic_writes": normalized.atomic_writes,
            "backup_existing": normalized.backup_existing,
            "fail_on_validation_error": normalized.fail_on_validation_error,
            "fail_on_asset_copy_error": normalized.fail_on_asset_copy_error,
            "strict": normalized.strict,
            "validation_mode": normalized.validation_mode,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class PackageCreationEvent:
    """Ein Ereignis während der Package-Erstellung."""

    stage: str
    status: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageCreationEvent":
        return PackageCreationEvent(
            stage=parse_creation_stage_value(self.stage),
            status=parse_creation_status_value(self.status),
            message=clean_required_string(self.message, "message"),
            details=normalize_metadata(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "stage": normalized.stage,
            "status": normalized.status,
            "message": normalized.message,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class PackageCreationResult:
    """Ergebnis der VPLIB-Package-Erstellung."""

    package_root: Path
    creation_plan: Any | None = None
    document_bundle: Any | None = None
    validation_before_write: Any | None = None
    validation_after_write: Any | None = None
    directory_write_result: Any | None = None
    document_write_result: Any | None = None
    asset_copy_result: Any | None = None
    archive_result: Any | None = None
    events: tuple[PackageCreationEvent, ...] = field(default_factory=tuple)
    status: str = PackageCreationStatus.CREATED.value
    schema_version: str = PACKAGE_CREATOR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageCreationResult":
        package_root = normalize_absolute_path(self.package_root, "package_root")
        status = parse_creation_status_value(self.status)
        events = tuple(event.normalized() for event in self.events or ())
        metadata = normalize_metadata(self.metadata)

        if any(event.status == PackageCreationStatus.FAILED.value for event in events):
            status = PackageCreationStatus.FAILED.value

        if is_dry_run_result(
            self.directory_write_result,
            self.document_write_result,
            self.asset_copy_result,
            self.archive_result,
        ) and status != PackageCreationStatus.FAILED.value:
            status = PackageCreationStatus.DRY_RUN.value

        uid = get_vplib_uid_safe(
            self.creation_plan,
            self.document_bundle,
            metadata,
        )
        if uid:
            metadata = {
                **metadata,
                MANIFEST_VPLIB_UID_FIELD: uid,
            }

        return PackageCreationResult(
            package_root=package_root,
            creation_plan=normalize_optional_creation_plan(self.creation_plan),
            document_bundle=normalize_optional_document_bundle(self.document_bundle),
            validation_before_write=normalize_optional_validation_like(self.validation_before_write),
            validation_after_write=normalize_optional_validation_like(self.validation_after_write),
            directory_write_result=normalize_optional_write_result(self.directory_write_result),
            document_write_result=normalize_optional_write_result(self.document_write_result),
            asset_copy_result=normalize_optional_write_result(self.asset_copy_result),
            archive_result=normalize_optional_archive_result(self.archive_result),
            events=events,
            status=status,
            schema_version=self.schema_version or PACKAGE_CREATOR_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def ok(self) -> bool:
        normalized = self.normalized()

        return normalized.status in {
            PackageCreationStatus.CREATED.value,
            PackageCreationStatus.DRY_RUN.value,
            PackageCreationStatus.SKIPPED.value,
        }

    @property
    def failed(self) -> bool:
        return self.normalized().status == PackageCreationStatus.FAILED.value

    @property
    def vplib_uid(self) -> str | None:
        """Liest die finale VPLIB-ID aus Bundle/Plan/Metadata."""
        normalized = self.normalized()
        return get_vplib_uid_safe(
            normalized.creation_plan,
            normalized.document_bundle,
            normalized.metadata,
        )

    def raise_for_errors(self) -> None:
        normalized = self.normalized()

        if normalized.failed:
            messages = [
                event.message
                for event in normalized.events
                if event.status == PackageCreationStatus.FAILED.value
            ]
            raise PackageCreatorError("; ".join(messages) or "Package creation failed.")

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        uid = get_vplib_uid_safe(
            normalized.creation_plan,
            normalized.document_bundle,
            normalized.metadata,
        )

        return {
            "schema_version": normalized.schema_version,
            "status": normalized.status,
            "ok": normalized.ok,
            "failed": normalized.failed,
            "package_root": str(normalized.package_root),
            "vplib_uid": uid,
            "package_id": get_package_id_safe(normalized.creation_plan, normalized.document_bundle),
            "family_id": get_family_id_safe(normalized.creation_plan, normalized.document_bundle),
            "family_slug": get_family_slug_safe(normalized.creation_plan, normalized.document_bundle),
            "object_kind": get_object_kind_safe(normalized.creation_plan, normalized.document_bundle),
            "creation_plan": object_to_dict(normalized.creation_plan),
            "document_bundle": object_to_dict(normalized.document_bundle),
            "validation_before_write": object_to_dict(normalized.validation_before_write),
            "validation_after_write": object_to_dict(normalized.validation_after_write),
            "directory_write_result": object_to_dict(normalized.directory_write_result),
            "document_write_result": object_to_dict(normalized.document_write_result),
            "asset_copy_result": object_to_dict(normalized.asset_copy_result),
            "archive_result": object_to_dict(normalized.archive_result),
            "events": [event.to_dict() for event in normalized.events],
            "metadata": {
                **dict(normalized.metadata),
                **({MANIFEST_VPLIB_UID_FIELD: uid} if uid else {}),
            },
        }


def create_vplib_package_from_request(
    *,
    request: Any,
    service_root: str | Path,
    library_catalog_root: str | Path | None = None,
    source_root: str | Path | None = None,
    generated_root: str | Path | None = None,
    archive_root: str | Path | None = None,
    options: PackageCreationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageCreationResult:
    """
    Plant und erstellt ein VPLIB-Package direkt aus einem CreateRequest.

    Dies ist ein stabiler Einstieg für spätere API-Routen.
    """
    normalized_options = normalize_options(options)
    raw_vplib_uid = extract_raw_vplib_uid_from_any(request) or extract_raw_vplib_uid_from_any(metadata)
    creator_metadata = {
        "source": "package_creator",
        **dict(metadata or {}),
    }
    if raw_vplib_uid is not None:
        creator_metadata[MANIFEST_VPLIB_UID_FIELD] = raw_vplib_uid

    try:
        from ..planning.creation_planner import plan_vplib_creation

        creation_plan = plan_vplib_creation(
            request=request,
            service_root=service_root,
            library_catalog_root=library_catalog_root,
            source_root=source_root,
            generated_root=generated_root,
            archive_root=archive_root,
            write_mode=normalized_options.write_mode,
            metadata=creator_metadata,
        )

        return create_vplib_package_from_plan(
            creation_plan=creation_plan,
            options=normalized_options,
            metadata=creator_metadata,
        ).normalized()
    except PackageCreatorError:
        raise
    except Exception as exc:
        return failed_creation_result(
            package_root=generated_root or service_root,
            stage=PackageCreationStage.PLAN.value,
            message=f"Could not create VPLIB package from request: {exc}",
            metadata=creator_metadata,
        )


def create_vplib_package_from_plan(
    *,
    creation_plan: Any,
    options: PackageCreationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageCreationResult:
    """Erstellt ein VPLIB-Package aus einem vorhandenen CreationPlan."""
    normalized_options = normalize_options(options)
    events: list[PackageCreationEvent] = []
    creator_metadata = normalize_metadata(metadata)

    try:
        plan = normalize_creation_plan(creation_plan)
        package_root = get_package_root_from_plan(plan)

        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(plan)
            or extract_raw_vplib_uid_from_any(creation_plan)
            or extract_raw_vplib_uid_from_any(creator_metadata)
        )
        if raw_vplib_uid is not None:
            creator_metadata[MANIFEST_VPLIB_UID_FIELD] = raw_vplib_uid

        events.append(
            creation_event(
                stage=PackageCreationStage.PLAN.value,
                status=PackageCreationStatus.CREATED.value,
                message="CreationPlan normalized.",
                details={
                    "package_root": str(package_root),
                    "package_id": get_package_id_safe(plan, None),
                    "vplib_uid": normalize_vplib_uid_safe(raw_vplib_uid),
                },
            )
        )

        bundle = build_document_bundle_for_plan(
            plan,
            options=normalized_options,
            metadata=creator_metadata,
        )
        uid = get_vplib_uid_safe(plan, bundle, creator_metadata)
        if uid:
            creator_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

        events.append(
            creation_event(
                stage=PackageCreationStage.DOCUMENTS.value,
                status=PackageCreationStatus.CREATED.value,
                message="DocumentBundle created.",
                details={
                    "document_count": len(bundle.to_documents()),
                    "vplib_uid": uid,
                },
            )
        )

        validation_before = None
        if normalized_options.validate_before_write:
            validation_before = validate_package_before_write(
                creation_plan=plan,
                bundle=bundle,
                options=normalized_options,
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.VALIDATE_BEFORE_WRITE.value,
                    status=PackageCreationStatus.CREATED.value if is_validation_valid(validation_before) else PackageCreationStatus.FAILED.value,
                    message="Pre-write validation completed.",
                    details={
                        "valid": is_validation_valid(validation_before),
                        "vplib_uid": uid,
                    },
                )
            )

            if not is_validation_valid(validation_before) and normalized_options.fail_on_validation_error:
                return PackageCreationResult(
                    package_root=package_root,
                    creation_plan=plan,
                    document_bundle=bundle,
                    validation_before_write=validation_before,
                    events=tuple(events),
                    status=PackageCreationStatus.FAILED.value,
                    metadata={
                        "source": "creation_plan",
                        **creator_metadata,
                    },
                ).normalized()

        directory_result = None
        if normalized_options.create_directories:
            directory_result = create_package_directories(
                package_root=package_root,
                creation_plan=plan,
                options=normalized_options,
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.CREATE_DIRECTORIES.value,
                    status=status_from_write_result(directory_result),
                    message="Package directories processed.",
                    details={
                        **result_summary(directory_result),
                        "vplib_uid": uid,
                    },
                )
            )

        document_result = None
        if normalized_options.write_documents:
            document_result = write_package_documents(
                package_root=package_root,
                document_bundle=bundle,
                options=normalized_options,
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.WRITE_DOCUMENTS.value,
                    status=status_from_write_result(document_result),
                    message="Package documents processed.",
                    details={
                        **result_summary(document_result),
                        "vplib_uid": uid,
                    },
                )
            )

        asset_result = None
        if normalized_options.copy_assets:
            asset_result = copy_package_assets(
                package_root=package_root,
                creation_plan=plan,
                options=normalized_options,
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.COPY_ASSETS.value,
                    status=status_from_write_result(asset_result),
                    message="Package assets processed.",
                    details={
                        **result_summary(asset_result),
                        "vplib_uid": uid,
                    },
                )
            )

            if is_write_result_failed(asset_result) and normalized_options.fail_on_asset_copy_error:
                return PackageCreationResult(
                    package_root=package_root,
                    creation_plan=plan,
                    document_bundle=bundle,
                    validation_before_write=validation_before,
                    directory_write_result=directory_result,
                    document_write_result=document_result,
                    asset_copy_result=asset_result,
                    events=tuple(events),
                    status=PackageCreationStatus.FAILED.value,
                    metadata={
                        "source": "creation_plan",
                        **creator_metadata,
                    },
                ).normalized()

        archive_result = None
        if normalized_options.create_archive:
            archive_result = create_package_archive(
                creation_plan=plan,
                package_root=package_root,
                options=normalized_options,
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.CREATE_ARCHIVE.value,
                    status=status_from_archive_result(archive_result),
                    message="Package archive processed.",
                    details={
                        **object_to_summary(archive_result),
                        "vplib_uid": uid,
                    },
                )
            )

        validation_after = None
        if normalized_options.validate_after_write:
            validation_after = validate_package_after_write(
                creation_plan=plan,
                bundle=bundle,
                options=normalized_options,
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.VALIDATE_AFTER_WRITE.value,
                    status=PackageCreationStatus.CREATED.value if is_validation_valid(validation_after) else PackageCreationStatus.FAILED.value,
                    message="Post-write validation completed.",
                    details={
                        "valid": is_validation_valid(validation_after),
                        "vplib_uid": uid,
                    },
                )
            )

            if not is_validation_valid(validation_after) and normalized_options.fail_on_validation_error:
                return PackageCreationResult(
                    package_root=package_root,
                    creation_plan=plan,
                    document_bundle=bundle,
                    validation_before_write=validation_before,
                    validation_after_write=validation_after,
                    directory_write_result=directory_result,
                    document_write_result=document_result,
                    asset_copy_result=asset_result,
                    archive_result=archive_result,
                    events=tuple(events),
                    status=PackageCreationStatus.FAILED.value,
                    metadata={
                        "source": "creation_plan",
                        **creator_metadata,
                    },
                ).normalized()

        events.append(
            creation_event(
                stage=PackageCreationStage.FINISH.value,
                status=PackageCreationStatus.DRY_RUN.value if normalized_options.dry_run else PackageCreationStatus.CREATED.value,
                message="Package creation completed.",
                details={
                    "dry_run": normalized_options.dry_run,
                    "vplib_uid": uid,
                },
            )
        )

        return PackageCreationResult(
            package_root=package_root,
            creation_plan=plan,
            document_bundle=bundle,
            validation_before_write=validation_before,
            validation_after_write=validation_after,
            directory_write_result=directory_result,
            document_write_result=document_result,
            asset_copy_result=asset_result,
            archive_result=archive_result,
            events=tuple(events),
            status=PackageCreationStatus.DRY_RUN.value if normalized_options.dry_run else PackageCreationStatus.CREATED.value,
            metadata={
                "source": "creation_plan",
                **creator_metadata,
            },
        ).normalized()
    except PackageCreatorError:
        raise
    except Exception as exc:
        package_root = get_package_root_from_plan_safe(creation_plan)

        return PackageCreationResult(
            package_root=package_root,
            creation_plan=normalize_optional_creation_plan(creation_plan),
            events=(
                *tuple(events),
                creation_event(
                    stage=PackageCreationStage.FINISH.value,
                    status=PackageCreationStatus.FAILED.value,
                    message=f"Package creation failed: {exc}",
                    details={
                        "error": str(exc),
                        "vplib_uid": normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(creator_metadata)),
                    },
                ),
            ),
            status=PackageCreationStatus.FAILED.value,
            metadata=dict(creator_metadata or {}),
        ).normalized()


def create_vplib_package_from_bundle(
    *,
    package_root: str | Path,
    bundle: Any,
    options: PackageCreationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageCreationResult:
    """Schreibt ein vorhandenes DocumentBundle als Package."""
    normalized_options = normalize_options(options)
    creator_metadata = normalize_metadata(metadata)

    try:
        root = normalize_absolute_path(package_root, "package_root")
        normalized_bundle = normalize_document_bundle(bundle)
        uid = get_vplib_uid_safe(None, normalized_bundle, creator_metadata)
        if uid:
            creator_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

        events: list[PackageCreationEvent] = []

        validation_before = None
        if normalized_options.validate_before_write:
            from ..validators.package_validator import validate_package_document_bundle

            validation_before = validate_package_document_bundle(
                normalized_bundle,
                options=normalized_options.to_validation_options(),
                metadata={
                    "source": "package_creator.bundle",
                    **creator_metadata,
                },
            )

            events.append(
                creation_event(
                    stage=PackageCreationStage.VALIDATE_BEFORE_WRITE.value,
                    status=PackageCreationStatus.CREATED.value if is_validation_valid(validation_before) else PackageCreationStatus.FAILED.value,
                    message="Bundle pre-write validation completed.",
                    details={
                        "valid": is_validation_valid(validation_before),
                        "vplib_uid": uid,
                    },
                )
            )

            if not is_validation_valid(validation_before) and normalized_options.fail_on_validation_error:
                return PackageCreationResult(
                    package_root=root,
                    document_bundle=normalized_bundle,
                    validation_before_write=validation_before,
                    events=tuple(events),
                    status=PackageCreationStatus.FAILED.value,
                    metadata=dict(creator_metadata or {}),
                ).normalized()

        document_result = write_package_documents(
            package_root=root,
            document_bundle=normalized_bundle,
            options=normalized_options,
        )

        events.append(
            creation_event(
                stage=PackageCreationStage.WRITE_DOCUMENTS.value,
                status=status_from_write_result(document_result),
                message="Bundle documents processed.",
                details={
                    **result_summary(document_result),
                    "vplib_uid": uid,
                },
            )
        )

        return PackageCreationResult(
            package_root=root,
            document_bundle=normalized_bundle,
            validation_before_write=validation_before,
            document_write_result=document_result,
            events=tuple(events),
            status=PackageCreationStatus.DRY_RUN.value if normalized_options.dry_run else status_from_write_result(document_result),
            metadata={
                "source": "document_bundle",
                **creator_metadata,
            },
        ).normalized()
    except Exception as exc:
        return failed_creation_result(
            package_root=package_root,
            stage=PackageCreationStage.WRITE_DOCUMENTS.value,
            message=f"Could not create VPLIB package from bundle: {exc}",
            metadata=creator_metadata,
        )


def build_document_bundle_for_plan(
    creation_plan: Any,
    *,
    options: PackageCreationOptions,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Baut ein DocumentBundle für einen CreationPlan."""
    try:
        from ..defaults.document_bundle import build_document_bundle_from_creation_plan

        plan = normalize_creation_plan(creation_plan)
        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(plan)
            or extract_raw_vplib_uid_from_any(creation_plan)
            or extract_raw_vplib_uid_from_any(metadata)
        )

        bundle_metadata = {
            "source": "package_creator",
            **dict(metadata or {}),
        }
        if raw_vplib_uid is not None:
            bundle_metadata[MANIFEST_VPLIB_UID_FIELD] = raw_vplib_uid

        return build_document_bundle_from_creation_plan(
            plan,
            options=options.to_document_bundle_options(),
            metadata=bundle_metadata,
        ).normalized()
    except Exception as exc:
        raise PackageCreatorError(f"Could not build DocumentBundle: {exc}") from exc


def validate_package_before_write(
    *,
    creation_plan: Any,
    bundle: Any,
    options: PackageCreationOptions,
) -> Any:
    """Führt Pre-Write-Validierung aus."""
    try:
        from ..validators.package_validator import validate_package_document_bundle

        plan = normalize_creation_plan(creation_plan)

        return validate_package_document_bundle(
            bundle,
            profile=getattr(plan, "profile", None),
            package_plan=getattr(plan, "package_plan", None),
            module_plan=getattr(plan, "module_plan", None),
            context=getattr(plan, "context", None),
            options=options.to_validation_options(),
            metadata={
                "source": "package_creator.pre_write",
                "vplib_uid": get_vplib_uid_safe(plan, bundle, None),
            },
        ).normalized()
    except Exception as exc:
        raise PackageCreatorError(f"Pre-write package validation failed: {exc}") from exc


def validate_package_after_write(
    *,
    creation_plan: Any,
    bundle: Any,
    options: PackageCreationOptions,
) -> Any:
    """Führt Post-Write-Validierung aus."""
    try:
        from ..validators.package_validator import validate_package_document_bundle

        plan = normalize_creation_plan(creation_plan)

        return validate_package_document_bundle(
            bundle,
            profile=getattr(plan, "profile", None),
            package_plan=getattr(plan, "package_plan", None),
            module_plan=getattr(plan, "module_plan", None),
            context=getattr(plan, "context", None),
            options=options.to_validation_options(),
            metadata={
                "source": "package_creator.after_write",
                "vplib_uid": get_vplib_uid_safe(plan, bundle, None),
            },
        ).normalized()
    except Exception as exc:
        raise PackageCreatorError(f"Post-write package validation failed: {exc}") from exc


def create_package_directories(
    *,
    package_root: str | Path,
    creation_plan: Any,
    options: PackageCreationOptions,
) -> Any:
    """Legt alle geplanten Package-Verzeichnisse an."""
    try:
        from .file_writer import write_package_plan_directories

        plan = normalize_creation_plan(creation_plan)

        return write_package_plan_directories(
            package_root=package_root,
            package_plan=plan.package_plan,
            options=options.to_file_write_options(),
            metadata={
                "source": "package_creator.directories",
                "vplib_uid": get_vplib_uid_safe(plan, None, None),
            },
        ).normalized()
    except Exception as exc:
        raise PackageCreatorError(f"Could not create package directories: {exc}") from exc


def write_package_documents(
    *,
    package_root: str | Path,
    document_bundle: Any,
    options: PackageCreationOptions,
) -> Any:
    """Schreibt Package-Dokumente."""
    try:
        from .file_writer import write_document_bundle_to_package

        bundle = normalize_document_bundle(document_bundle)

        return write_document_bundle_to_package(
            package_root=package_root,
            bundle=bundle,
            options=options.to_file_write_options(),
            metadata={
                "source": "package_creator.documents",
                "vplib_uid": get_vplib_uid_safe(None, bundle, None),
            },
        ).normalized()
    except Exception as exc:
        raise PackageCreatorError(f"Could not write package documents: {exc}") from exc


def copy_package_assets(
    *,
    package_root: str | Path,
    creation_plan: Any,
    options: PackageCreationOptions,
) -> Any:
    """Kopiert geplante Assets."""
    try:
        from .file_writer import copy_package_plan_assets

        plan = normalize_creation_plan(creation_plan)

        return copy_package_plan_assets(
            package_root=package_root,
            package_plan=plan.package_plan,
            options=options.to_file_write_options(),
            metadata={
                "source": "package_creator.assets",
                "vplib_uid": get_vplib_uid_safe(plan, None, None),
            },
        ).normalized()
    except Exception as exc:
        if options.normalized().fail_on_asset_copy_error:
            raise PackageCreatorError(f"Could not copy package assets: {exc}") from exc

        from .file_writer import FileWriteBatchResult

        return FileWriteBatchResult(
            package_root=package_root,
            results=tuple(),
            options=options.to_file_write_options(),
            metadata={
                "source": "package_creator.assets",
                "vplib_uid": get_vplib_uid_safe(creation_plan, None, None),
                "skipped_due_error": str(exc),
            },
        ).normalized()


def create_package_archive(
    *,
    creation_plan: Any,
    package_root: str | Path,
    options: PackageCreationOptions,
) -> Any:
    """Erzeugt optional ein .vplib-Archiv, wenn archive_creator verfügbar ist."""
    try:
        from .archive_creator import create_vplib_archive_from_package

        plan = normalize_creation_plan(creation_plan)

        archive_path = getattr(plan.package_plan, "archive_path", None)

        return create_vplib_archive_from_package(
            package_root=package_root,
            archive_path=archive_path,
            dry_run=options.normalized().dry_run,
            overwrite=options.normalized().write_mode == "overwrite",
            metadata={
                "source": "package_creator.archive",
                "vplib_uid": get_vplib_uid_safe(plan, None, None),
            },
        )
    except ModuleNotFoundError as exc:
        raise PackageCreatorError(
            "Archive creation requested, but archive_creator.py is not available yet."
        ) from exc
    except Exception as exc:
        raise PackageCreatorError(f"Could not create VPLIB archive: {exc}") from exc


def failed_creation_result(
    *,
    package_root: str | Path,
    stage: str,
    message: str,
    metadata: Mapping[str, Any] | None = None,
) -> PackageCreationResult:
    """Erzeugt ein fehlgeschlagenes PackageCreationResult."""
    root = normalize_absolute_path(package_root, "package_root")
    normalized_metadata = normalize_metadata(metadata)
    uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(normalized_metadata))

    if uid:
        normalized_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

    return PackageCreationResult(
        package_root=root,
        events=(
            creation_event(
                stage=stage,
                status=PackageCreationStatus.FAILED.value,
                message=message,
                details={
                    "error": message,
                    "vplib_uid": uid,
                },
            ),
        ),
        status=PackageCreationStatus.FAILED.value,
        metadata=normalized_metadata,
    ).normalized()


def creation_event(
    *,
    stage: str,
    status: str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> PackageCreationEvent:
    """Factory für PackageCreationEvent."""
    return PackageCreationEvent(
        stage=stage,
        status=status,
        message=message,
        details=dict(details or {}),
    ).normalized()


def get_package_root_from_plan(creation_plan: Any) -> Path:
    """Liest package_root aus einem CreationPlan."""
    plan = normalize_creation_plan(creation_plan)

    try:
        return normalize_absolute_path(plan.package_dir, "package_root")
    except Exception:
        pass

    try:
        return normalize_absolute_path(plan.context.package_dir, "package_root")
    except Exception:
        pass

    try:
        return normalize_absolute_path(plan.package_plan.context.package_dir, "package_root")
    except Exception as exc:
        raise PackageCreatorError("Could not resolve package_root from CreationPlan.") from exc


def get_package_root_from_plan_safe(value: Any) -> Path:
    """Liest package_root defensiv aus einem CreationPlan-ähnlichen Objekt."""
    try:
        return get_package_root_from_plan(value)
    except Exception:
        return Path(".").expanduser()


def get_vplib_uid_safe(
    creation_plan: Any | None = None,
    bundle: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> str | None:
    """
    Liest `vplib_uid` defensiv aus Bundle, CreationPlan oder Metadata.

    Priorität:
    1. Bundle-Manifest
    2. Bundle.to_dict()
    3. CreationPlan / Context / Request / Identity
    4. Metadata
    """
    uid = get_vplib_uid_from_bundle_safe(bundle)
    if uid:
        return uid

    uid = get_vplib_uid_from_creation_plan_safe(creation_plan)
    if uid:
        return uid

    uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(metadata))
    if uid:
        return uid

    return None


def get_vplib_uid_from_bundle_safe(bundle: Any | None) -> str | None:
    """Liest `vplib_uid` defensiv aus einem DocumentBundle-ähnlichen Objekt."""
    if bundle is None:
        return None

    try:
        normalized_bundle = normalize_document_bundle(bundle)

        try:
            uid = normalize_vplib_uid_safe(getattr(normalized_bundle, "vplib_uid", None))
            if uid:
                return uid
        except Exception:
            pass

        manifest = normalized_bundle.get_document(MANIFEST_DOCUMENT_PATH)
        uid = get_vplib_uid_from_manifest_safe(manifest)
        if uid:
            return uid

        if hasattr(normalized_bundle, "to_dict"):
            data = normalized_bundle.to_dict()
            uid = normalize_vplib_uid_safe(data.get(MANIFEST_VPLIB_UID_FIELD))
            if uid:
                return uid
    except Exception:
        pass

    if isinstance(bundle, Mapping):
        try:
            if MANIFEST_DOCUMENT_PATH in bundle:
                uid = get_vplib_uid_from_manifest_safe(bundle.get(MANIFEST_DOCUMENT_PATH))
                if uid:
                    return uid

            uid = normalize_vplib_uid_safe(bundle.get(MANIFEST_VPLIB_UID_FIELD))
            if uid:
                return uid
        except Exception:
            pass

    return None


def get_vplib_uid_from_creation_plan_safe(creation_plan: Any | None) -> str | None:
    """Liest `vplib_uid` defensiv aus CreationPlan/Context/Request-Strukturen."""
    if creation_plan is None:
        return None

    try:
        plan = normalize_creation_plan(creation_plan)
        uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(plan))
        if uid:
            return uid

        for attr_name in ("request", "context", "identity", "package_plan"):
            try:
                uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(getattr(plan, attr_name, None)))
                if uid:
                    return uid
            except Exception:
                continue
    except Exception:
        pass

    uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(creation_plan))
    if uid:
        return uid

    return None


def get_vplib_uid_from_manifest_safe(manifest: Any | None) -> str | None:
    """Liest `vplib_uid` defensiv aus einem Manifest-Mapping."""
    if not isinstance(manifest, Mapping):
        return None

    try:
        from ..vplib_id_service import get_vplib_uid_from_mapping

        return get_vplib_uid_from_mapping(manifest)
    except Exception:
        return normalize_vplib_uid_safe(manifest.get(MANIFEST_VPLIB_UID_FIELD))


def get_package_id_safe(creation_plan: Any | None, bundle: Any | None) -> str | None:
    """Liest package_id defensiv."""
    if creation_plan is not None:
        try:
            plan = normalize_creation_plan(creation_plan)
            return clean_optional_string(plan.package_id)
        except Exception:
            pass

        try:
            return clean_optional_string(creation_plan.context.identity.package_id)
        except Exception:
            pass

    if bundle is not None:
        try:
            manifest = get_manifest_from_bundle_safe(bundle)
            if manifest:
                return clean_optional_string(manifest.get("package_id"))
        except Exception:
            pass

    return None


def get_family_id_safe(creation_plan: Any | None, bundle: Any | None) -> str | None:
    """Liest family_id defensiv."""
    if creation_plan is not None:
        try:
            plan = normalize_creation_plan(creation_plan)
            return clean_optional_string(plan.context.identity.family_id)
        except Exception:
            pass

        try:
            return clean_optional_string(creation_plan.context.identity.family_id)
        except Exception:
            pass

    if bundle is not None:
        try:
            manifest = get_manifest_from_bundle_safe(bundle)
            if manifest:
                return clean_optional_string(manifest.get("family_id"))
        except Exception:
            pass

    return None


def get_family_slug_safe(creation_plan: Any | None, bundle: Any | None) -> str | None:
    """Liest family_slug defensiv."""
    if creation_plan is not None:
        try:
            plan = normalize_creation_plan(creation_plan)
            return clean_optional_string(plan.context.identity.family_slug)
        except Exception:
            pass

        try:
            return clean_optional_string(creation_plan.context.identity.family_slug)
        except Exception:
            pass

    if bundle is not None:
        try:
            manifest = get_manifest_from_bundle_safe(bundle)
            if manifest:
                return clean_optional_string(manifest.get("family_slug"))
        except Exception:
            pass

    return None


def get_object_kind_safe(creation_plan: Any | None, bundle: Any | None) -> str | None:
    """Liest object_kind defensiv."""
    if creation_plan is not None:
        try:
            plan = normalize_creation_plan(creation_plan)
            return clean_optional_string(plan.object_kind)
        except Exception:
            pass

        try:
            return clean_optional_string(creation_plan.context.object_kind)
        except Exception:
            pass

    if bundle is not None:
        try:
            manifest = get_manifest_from_bundle_safe(bundle)
            if manifest:
                return clean_optional_string(manifest.get("object_kind"))
        except Exception:
            pass

    return None


def get_manifest_from_bundle_safe(bundle: Any | None) -> dict[str, Any] | None:
    """Liest `vplib.manifest.json` defensiv aus einem Bundle."""
    if bundle is None:
        return None

    try:
        normalized_bundle = normalize_document_bundle(bundle)
        manifest = normalized_bundle.get_document(MANIFEST_DOCUMENT_PATH)
        if isinstance(manifest, Mapping):
            return dict(manifest)
    except Exception:
        pass

    if isinstance(bundle, Mapping):
        try:
            manifest = bundle.get(MANIFEST_DOCUMENT_PATH)
            if isinstance(manifest, Mapping):
                return dict(manifest)
        except Exception:
            pass

    return None


def status_from_write_result(value: Any | None) -> str:
    """Leitet PackageCreationStatus aus FileWriteBatchResult ab."""
    if value is None:
        return PackageCreationStatus.SKIPPED.value

    if is_write_result_failed(value):
        return PackageCreationStatus.FAILED.value

    try:
        if getattr(value, "options", None) is not None and bool(value.options.dry_run):
            return PackageCreationStatus.DRY_RUN.value
    except Exception:
        pass

    try:
        if getattr(value, "ok", False):
            return PackageCreationStatus.CREATED.value
    except Exception:
        pass

    if isinstance(value, Mapping):
        if value.get("failed"):
            return PackageCreationStatus.FAILED.value
        if value.get("ok"):
            return PackageCreationStatus.CREATED.value

    return PackageCreationStatus.SKIPPED.value


def status_from_archive_result(value: Any | None) -> str:
    """Leitet PackageCreationStatus aus ArchiveResult ab."""
    if value is None:
        return PackageCreationStatus.SKIPPED.value

    try:
        if getattr(value, "failed", False):
            return PackageCreationStatus.FAILED.value
        if getattr(value, "dry_run", False):
            return PackageCreationStatus.DRY_RUN.value
        if getattr(value, "ok", False):
            return PackageCreationStatus.CREATED.value
    except Exception:
        pass

    if isinstance(value, Mapping):
        if value.get("failed"):
            return PackageCreationStatus.FAILED.value
        if value.get("dry_run"):
            return PackageCreationStatus.DRY_RUN.value
        if value.get("ok"):
            return PackageCreationStatus.CREATED.value

    return PackageCreationStatus.CREATED.value


def is_write_result_failed(value: Any | None) -> bool:
    """Prüft, ob FileWriteBatchResult fehlgeschlagen ist."""
    if value is None:
        return False

    try:
        return bool(value.failed)
    except Exception:
        pass

    if isinstance(value, Mapping):
        return bool(value.get("failed", False))

    return False


def is_validation_valid(value: Any | None) -> bool:
    """Prüft, ob ein Validierungsergebnis gültig ist."""
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


def is_dry_run_result(*values: Any | None) -> bool:
    """Prüft, ob mindestens ein Ergebnis Dry-Run ist."""
    for value in values:
        if value is None:
            continue

        try:
            if getattr(value, "options", None) is not None and bool(value.options.dry_run):
                return True
        except Exception:
            pass

        if isinstance(value, Mapping) and bool(value.get("dry_run", False)):
            return True

    return False


def result_summary(value: Any | None) -> dict[str, Any]:
    """Erzeugt kompakte Summary eines Result-Objekts."""
    if value is None:
        return {"present": False}

    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return {
                key: data.get(key)
                for key in (
                    "ok",
                    "failed",
                    "result_count",
                    "written_count",
                    "skipped_count",
                    "failed_count",
                    "total_bytes_written",
                )
                if key in data
            }
        except Exception:
            return {"present": True, "repr": str(value)}

    if isinstance(value, Mapping):
        return {
            key: value.get(key)
            for key in (
                "ok",
                "failed",
                "result_count",
                "written_count",
                "skipped_count",
                "failed_count",
                "total_bytes_written",
            )
            if key in value
        }

    return {"present": True, "repr": str(value)}


def object_to_summary(value: Any | None) -> dict[str, Any]:
    """Erzeugt kompakte Summary eines beliebigen Objekts."""
    if value is None:
        return {"present": False}

    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return {
                key: data.get(key)
                for key in (
                    "ok",
                    "failed",
                    "status",
                    "archive_path",
                    "bytes_written",
                    "dry_run",
                )
                if key in data
            }
        except Exception:
            return {"present": True, "repr": str(value)}

    if isinstance(value, Mapping):
        return {
            key: value.get(key)
            for key in (
                "ok",
                "failed",
                "status",
                "archive_path",
                "bytes_written",
                "dry_run",
            )
            if key in value
        }

    return {"present": True, "repr": str(value)}


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


def normalize_options(
    options: PackageCreationOptions | Mapping[str, Any] | None,
) -> PackageCreationOptions:
    """Normalisiert PackageCreationOptions."""
    if options is None:
        return PackageCreationOptions().normalized()

    if isinstance(options, PackageCreationOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return PackageCreationOptions(
            write_mode=options.get("write_mode", "fail"),
            dry_run=bool(options.get("dry_run", False)),
            validate_before_write=bool(options.get("validate_before_write", True)),
            validate_after_write=bool(options.get("validate_after_write", False)),
            write_documents=bool(options.get("write_documents", True)),
            copy_assets=bool(options.get("copy_assets", True)),
            create_directories=bool(options.get("create_directories", True)),
            create_archive=bool(options.get("create_archive", False)),
            include_optional_documents=bool(options.get("include_optional_documents", True)),
            include_generated_documents=bool(options.get("include_generated_documents", True)),
            atomic_writes=bool(options.get("atomic_writes", True)),
            backup_existing=bool(options.get("backup_existing", False)),
            fail_on_validation_error=bool(options.get("fail_on_validation_error", True)),
            fail_on_asset_copy_error=bool(options.get("fail_on_asset_copy_error", True)),
            strict=bool(options.get("strict", True)),
            validation_mode=options.get("validation_mode", "strict"),
            metadata=dict(options.get("metadata", {}) or {}),
        ).normalized()

    raise PackageCreatorError("options must be PackageCreationOptions, mapping or None.")


def normalize_creation_plan(value: Any) -> Any:
    """Normalisiert CreationPlan-ähnliche Werte."""
    try:
        from ..planning.creation_planner import CreationPlan, creation_plan_from_mapping

        if isinstance(value, CreationPlan):
            return value.normalized()

        if isinstance(value, Mapping):
            return creation_plan_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise PackageCreatorError("CreationPlan value is required.")
    except PackageCreatorError:
        raise
    except Exception as exc:
        raise PackageCreatorError(f"Invalid CreationPlan: {exc}") from exc


def normalize_optional_creation_plan(value: Any | None) -> Any | None:
    """Normalisiert optionalen CreationPlan."""
    if value is None:
        return None

    try:
        return normalize_creation_plan(value)
    except Exception:
        return value


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

        raise PackageCreatorError("DocumentBundle value is required.")
    except PackageCreatorError:
        raise
    except Exception as exc:
        raise PackageCreatorError(f"Invalid DocumentBundle: {exc}") from exc


def normalize_optional_document_bundle(value: Any | None) -> Any | None:
    """Normalisiert optionales DocumentBundle."""
    if value is None:
        return None

    try:
        return normalize_document_bundle(value)
    except Exception:
        return value


def normalize_optional_validation_like(value: Any | None) -> Any | None:
    """Normalisiert optionale ValidationResult-artige Objekte defensiv."""
    if value is None:
        return None

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()
    except Exception:
        return value

    return value


def normalize_optional_write_result(value: Any | None) -> Any | None:
    """Normalisiert optionale FileWriteBatchResult-artige Objekte defensiv."""
    if value is None:
        return None

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()
    except Exception:
        return value

    return value


def normalize_optional_archive_result(value: Any | None) -> Any | None:
    """Normalisiert optionale ArchiveResult-artige Objekte defensiv."""
    if value is None:
        return None

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()
    except Exception:
        return value

    return value


def normalize_absolute_path(value: Any, field_name: str) -> Path:
    """Normalisiert lokalen Pfad."""
    try:
        if value is None:
            raise PackageCreatorError(f"{field_name} is required.")

        return Path(value).expanduser()
    except PackageCreatorError:
        raise
    except Exception as exc:
        raise PackageCreatorError(f"Invalid path for {field_name}: {value!r}.") from exc


@lru_cache(maxsize=128)
def normalize_write_mode(value: Any) -> str:
    """Normalisiert WriteMode ohne direkten Importzwang."""
    try:
        from .file_writer import parse_write_mode_value

        return parse_write_mode_value(value)
    except Exception as exc:
        raise PackageCreatorError(f"Invalid write_mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_creation_status_value(value: Any) -> str:
    """Parst PackageCreationStatus."""
    try:
        if isinstance(value, PackageCreationStatus):
            return value.value

        raw = normalize_enum_key(value)
        return PackageCreationStatus(raw).value
    except Exception as exc:
        raise PackageCreatorError(f"Invalid package creation status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_creation_stage_value(value: Any) -> str:
    """Parst PackageCreationStage."""
    try:
        if isinstance(value, PackageCreationStage):
            return value.value

        raw = normalize_enum_key(value)
        return PackageCreationStage(raw).value
    except Exception as exc:
        raise PackageCreatorError(f"Invalid package creation stage {value!r}.") from exc


def extract_raw_vplib_uid_from_any(value: Any) -> Any | None:
    """Extrahiert rohe vplib_uid aus Mapping- oder Objektstrukturen."""
    if value is None:
        return None

    try:
        from ..defaults.document_bundle import extract_raw_vplib_uid_from_any as extract

        extracted = extract(value)
        if extracted is not None:
            return extracted
    except Exception:
        pass

    try:
        if isinstance(value, Mapping):
            for key in (MANIFEST_VPLIB_UID_FIELD, "vplibUid", "vplib_uid_v1"):
                if key in value:
                    return value.get(key)

            for nested_key in ("manifest", "vplib_manifest", "identity", "payload", "data", "metadata"):
                nested = value.get(nested_key)
                extracted = extract_raw_vplib_uid_from_any(nested)
                if extracted is not None:
                    return extracted
            return None

        for attr_name in (MANIFEST_VPLIB_UID_FIELD, "vplibUid", "vplib_uid_v1"):
            try:
                if hasattr(value, attr_name):
                    attr_value = getattr(value, attr_name)
                    if attr_value is not None:
                        return attr_value
            except Exception:
                continue

        for nested_attr in ("manifest", "vplib_manifest", "identity", "payload", "data", "metadata"):
            try:
                nested = getattr(value, nested_attr, None)
                extracted = extract_raw_vplib_uid_from_any(nested)
                if extracted is not None:
                    return extracted
            except Exception:
                continue
    except Exception:
        return None

    return None


def normalize_vplib_uid_safe(value: Any) -> str | None:
    """Normalisiert eine VPLIB-ID defensiv."""
    try:
        from ..vplib_id_service import normalize_vplib_uid

        return normalize_vplib_uid(value)
    except Exception:
        return None


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise PackageCreatorError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except PackageCreatorError:
        raise
    except Exception as exc:
        raise PackageCreatorError(f"Invalid enum value {value!r}.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise PackageCreatorError("metadata must be a mapping.")

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
            raise PackageCreatorError(f"{field_name} is required.")

        return cleaned
    except PackageCreatorError:
        raise
    except Exception as exc:
        raise PackageCreatorError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_package_creator_caches() -> None:
    """Leert interne Parser-Caches."""
    normalize_write_mode.cache_clear()
    parse_creation_status_value.cache_clear()
    parse_creation_stage_value.cache_clear()


__all__ = [
    "MANIFEST_DOCUMENT_PATH",
    "MANIFEST_VPLIB_UID_FIELD",
    "PACKAGE_CREATOR_SCHEMA_VERSION",
    "PackageCreationEvent",
    "PackageCreationOptions",
    "PackageCreationResult",
    "PackageCreationStage",
    "PackageCreationStatus",
    "PackageCreatorError",
    "build_document_bundle_for_plan",
    "clean_optional_string",
    "clean_required_string",
    "clear_package_creator_caches",
    "copy_package_assets",
    "create_package_archive",
    "create_package_directories",
    "create_vplib_package_from_bundle",
    "create_vplib_package_from_plan",
    "create_vplib_package_from_request",
    "creation_event",
    "extract_raw_vplib_uid_from_any",
    "failed_creation_result",
    "get_family_id_safe",
    "get_family_slug_safe",
    "get_manifest_from_bundle_safe",
    "get_object_kind_safe",
    "get_package_id_safe",
    "get_package_root_from_plan",
    "get_package_root_from_plan_safe",
    "get_vplib_uid_from_bundle_safe",
    "get_vplib_uid_from_creation_plan_safe",
    "get_vplib_uid_from_manifest_safe",
    "get_vplib_uid_safe",
    "is_dry_run_result",
    "is_validation_valid",
    "is_write_result_failed",
    "normalize_absolute_path",
    "normalize_creation_plan",
    "normalize_document_bundle",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_options",
    "normalize_optional_archive_result",
    "normalize_optional_creation_plan",
    "normalize_optional_document_bundle",
    "normalize_optional_validation_like",
    "normalize_optional_write_result",
    "normalize_vplib_uid_safe",
    "normalize_write_mode",
    "object_to_dict",
    "object_to_summary",
    "parse_creation_stage_value",
    "parse_creation_status_value",
    "result_summary",
    "status_from_archive_result",
    "status_from_write_result",
    "validate_package_after_write",
    "validate_package_before_write",
    "write_package_documents",
]