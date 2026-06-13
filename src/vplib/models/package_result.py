# services/vectoplan-library/src/vplib/models/package_result.py
"""
PackageResult model for the VPLIB package engine.

Diese Datei beschreibt das Ergebnis eines VPLIB-Erstellvorgangs.

Rolle dieser Datei:

    PackagePlan
    -> creators / validators / archive writer
    -> PackageResult
    -> route response / admin UI / report / logs

Ein PackageResult ist kein Validator und kein Creator. Es sammelt:
- erzeugte Ordner
- erzeugte Dateien
- kopierte Assets
- übersprungene Dateien
- Archivpfad
- Validierungsergebnis
- Fehler/Warnungen
- Laufzeitstatus

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


PACKAGE_RESULT_SCHEMA_VERSION: Final[str] = "vplib.package_result.v1"


class PackageResultError(ValueError):
    """Wird ausgelöst, wenn ein PackageResult ungültig aufgebaut wird."""


class PackageResultStatus(str, Enum):
    """Status eines Package-Erstellvorgangs."""

    PENDING = "pending"
    PLANNED = "planned"
    CREATED = "created"
    VALIDATED = "validated"
    ARCHIVED = "archived"
    SKIPPED = "skipped"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


class ResultItemKind(str, Enum):
    """Art eines Ergebnis-Items."""

    DIRECTORY = "directory"
    FILE = "file"
    ASSET = "asset"
    ARCHIVE = "archive"
    REPORT = "report"

    @property
    def key(self) -> str:
        return str(self.value)


class ResultItemStatus(str, Enum):
    """Status eines Ergebnis-Items."""

    CREATED = "created"
    COPIED = "copied"
    WRITTEN = "written"
    SKIPPED = "skipped"
    EXISTS = "exists"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PackageResultItem:
    """Ein einzelnes Ergebnis-Item."""

    path: str
    kind: str
    status: str
    module_name: str | None = None
    message: str = ""
    source_path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageResultItem":
        path = clean_required_string(self.path, "path")
        kind = parse_result_item_kind_value(self.kind)
        status = parse_result_item_status_value(self.status)
        module_name = normalize_optional_module_name(self.module_name)
        message = clean_optional_string(self.message) or ""
        source_path = clean_optional_string(self.source_path)
        metadata = normalize_metadata(self.metadata)

        return PackageResultItem(
            path=path,
            kind=kind,
            status=status,
            module_name=module_name,
            message=message,
            source_path=source_path,
            metadata=metadata,
        )

    @property
    def failed(self) -> bool:
        return self.normalized().status == ResultItemStatus.FAILED.value

    @property
    def successful(self) -> bool:
        return self.normalized().status in {
            ResultItemStatus.CREATED.value,
            ResultItemStatus.COPIED.value,
            ResultItemStatus.WRITTEN.value,
            ResultItemStatus.EXISTS.value,
        }

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "path": normalized.path,
            "kind": normalized.kind,
            "status": normalized.status,
            "module_name": normalized.module_name,
            "message": normalized.message,
            "source_path": normalized.source_path,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class PackageResult:
    """
    Ergebnis eines VPLIB-Erstellvorgangs.

    success wird aus Status, Issues und Item-Fehlern abgeleitet, sofern es nicht
    explizit gesetzt wurde.
    """

    package_id: str
    family_id: str
    package_path: str
    status: str = PackageResultStatus.PENDING.value
    success: bool | None = None
    archive_path: str | None = None
    items: tuple[PackageResultItem, ...] = field(default_factory=tuple)
    validation_result: Any | None = None
    started_at: str | None = None
    finished_at: str | None = None
    correlation_id: str | None = None
    schema_version: str = PACKAGE_RESULT_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageResult":
        package_id = clean_required_string(self.package_id, "package_id")
        family_id = clean_required_string(self.family_id, "family_id")
        package_path = clean_required_string(self.package_path, "package_path")
        status = parse_package_result_status_value(self.status)
        archive_path = clean_optional_string(self.archive_path)
        items = tuple(item.normalized() for item in self.items or ())
        validation_result = normalize_validation_result(self.validation_result)
        started_at = clean_optional_string(self.started_at) or utc_now_iso()
        finished_at = clean_optional_string(self.finished_at)
        correlation_id = clean_optional_string(self.correlation_id)
        metadata = normalize_metadata(self.metadata)

        computed_success = compute_success(
            status=status,
            items=items,
            validation_result=validation_result,
        )
        success = computed_success if self.success is None else bool(self.success)

        if success and not computed_success:
            success = False

        return PackageResult(
            package_id=package_id,
            family_id=family_id,
            package_path=package_path,
            status=status,
            success=success,
            archive_path=archive_path,
            items=items,
            validation_result=validation_result,
            started_at=started_at,
            finished_at=finished_at,
            correlation_id=correlation_id,
            schema_version=self.schema_version or PACKAGE_RESULT_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def is_success(self) -> bool:
        return bool(self.normalized().success)

    @property
    def is_failed(self) -> bool:
        return not self.is_success

    @property
    def created_directories(self) -> tuple[PackageResultItem, ...]:
        return tuple(
            item
            for item in self.normalized().items
            if item.kind == ResultItemKind.DIRECTORY.value
        )

    @property
    def created_files(self) -> tuple[PackageResultItem, ...]:
        return tuple(
            item
            for item in self.normalized().items
            if item.kind == ResultItemKind.FILE.value
        )

    @property
    def copied_assets(self) -> tuple[PackageResultItem, ...]:
        return tuple(
            item
            for item in self.normalized().items
            if item.kind == ResultItemKind.ASSET.value
        )

    @property
    def archives(self) -> tuple[PackageResultItem, ...]:
        return tuple(
            item
            for item in self.normalized().items
            if item.kind == ResultItemKind.ARCHIVE.value
        )

    @property
    def failed_items(self) -> tuple[PackageResultItem, ...]:
        return tuple(item for item in self.normalized().items if item.failed)

    @property
    def skipped_items(self) -> tuple[PackageResultItem, ...]:
        return tuple(
            item
            for item in self.normalized().items
            if item.status == ResultItemStatus.SKIPPED.value
        )

    @property
    def item_count(self) -> int:
        return len(self.normalized().items)

    @property
    def failed_item_count(self) -> int:
        return len(self.failed_items)

    def with_item(self, item: PackageResultItem) -> "PackageResult":
        normalized = self.normalized()

        return PackageResult(
            package_id=normalized.package_id,
            family_id=normalized.family_id,
            package_path=normalized.package_path,
            status=normalized.status,
            success=None,
            archive_path=normalized.archive_path,
            items=(*normalized.items, item.normalized()),
            validation_result=normalized.validation_result,
            started_at=normalized.started_at,
            finished_at=normalized.finished_at,
            correlation_id=normalized.correlation_id,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_items(self, items: Iterable[PackageResultItem]) -> "PackageResult":
        result = self.normalized()

        for item in items or ():
            result = result.with_item(item)

        return result.normalized()

    def with_status(self, status: str) -> "PackageResult":
        normalized = self.normalized()

        return PackageResult(
            package_id=normalized.package_id,
            family_id=normalized.family_id,
            package_path=normalized.package_path,
            status=parse_package_result_status_value(status),
            success=None,
            archive_path=normalized.archive_path,
            items=normalized.items,
            validation_result=normalized.validation_result,
            started_at=normalized.started_at,
            finished_at=utc_now_iso() if status in {PackageResultStatus.FAILED.value, PackageResultStatus.ARCHIVED.value, PackageResultStatus.VALIDATED.value, PackageResultStatus.CREATED.value} else normalized.finished_at,
            correlation_id=normalized.correlation_id,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_validation_result(self, validation_result: Any) -> "PackageResult":
        normalized = self.normalized()

        return PackageResult(
            package_id=normalized.package_id,
            family_id=normalized.family_id,
            package_path=normalized.package_path,
            status=(
                PackageResultStatus.VALIDATED.value
                if get_validation_result_valid(validation_result)
                else PackageResultStatus.FAILED.value
            ),
            success=None,
            archive_path=normalized.archive_path,
            items=normalized.items,
            validation_result=normalize_validation_result(validation_result),
            started_at=normalized.started_at,
            finished_at=utc_now_iso(),
            correlation_id=normalized.correlation_id,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_archive_path(self, archive_path: str | Path) -> "PackageResult":
        normalized = self.normalized()

        return PackageResult(
            package_id=normalized.package_id,
            family_id=normalized.family_id,
            package_path=normalized.package_path,
            status=PackageResultStatus.ARCHIVED.value,
            success=None,
            archive_path=str(archive_path),
            items=(
                *normalized.items,
                PackageResultItem(
                    path=str(archive_path),
                    kind=ResultItemKind.ARCHIVE.value,
                    status=ResultItemStatus.WRITTEN.value,
                    message="VPLIB archive written.",
                ).normalized(),
            ),
            validation_result=normalized.validation_result,
            started_at=normalized.started_at,
            finished_at=utc_now_iso(),
            correlation_id=normalized.correlation_id,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_metadata(self, metadata: Mapping[str, Any]) -> "PackageResult":
        normalized = self.normalized()
        merged = dict(normalized.metadata)
        merged.update(normalize_metadata(metadata))

        return PackageResult(
            package_id=normalized.package_id,
            family_id=normalized.family_id,
            package_path=normalized.package_path,
            status=normalized.status,
            success=None,
            archive_path=normalized.archive_path,
            items=normalized.items,
            validation_result=normalized.validation_result,
            started_at=normalized.started_at,
            finished_at=normalized.finished_at,
            correlation_id=normalized.correlation_id,
            schema_version=normalized.schema_version,
            metadata=merged,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        validation_payload = (
            normalized.validation_result.to_dict()
            if hasattr(normalized.validation_result, "to_dict")
            else normalized.validation_result
        )

        return {
            "schema_version": normalized.schema_version,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "package_path": normalized.package_path,
            "status": normalized.status,
            "success": normalized.success,
            "archive_path": normalized.archive_path,
            "started_at": normalized.started_at,
            "finished_at": normalized.finished_at,
            "correlation_id": normalized.correlation_id,
            "item_count": normalized.item_count,
            "failed_item_count": normalized.failed_item_count,
            "created_directories": [item.to_dict() for item in normalized.created_directories],
            "created_files": [item.to_dict() for item in normalized.created_files],
            "copied_assets": [item.to_dict() for item in normalized.copied_assets],
            "archives": [item.to_dict() for item in normalized.archives],
            "skipped_items": [item.to_dict() for item in normalized.skipped_items],
            "failed_items": [item.to_dict() for item in normalized.failed_items],
            "items": [item.to_dict() for item in normalized.items],
            "validation_result": validation_payload,
            "metadata": dict(normalized.metadata),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        validation_summary = None

        if hasattr(normalized.validation_result, "to_summary_dict"):
            validation_summary = normalized.validation_result.to_summary_dict()
        elif isinstance(normalized.validation_result, Mapping):
            validation_summary = {
                "valid": normalized.validation_result.get("valid"),
                "issue_count": normalized.validation_result.get("issue_count"),
            }

        return {
            "schema_version": normalized.schema_version,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "package_path": normalized.package_path,
            "status": normalized.status,
            "success": normalized.success,
            "archive_path": normalized.archive_path,
            "item_count": normalized.item_count,
            "failed_item_count": normalized.failed_item_count,
            "validation": validation_summary,
        }


def package_result_from_plan(
    plan: Any,
    *,
    status: str = PackageResultStatus.PLANNED.value,
    metadata: Mapping[str, Any] | None = None,
) -> PackageResult:
    """Baut ein PackageResult aus einem PackagePlan-ähnlichen Objekt."""
    try:
        normalized_plan = plan.normalized() if hasattr(plan, "normalized") else plan
        context = normalized_plan.context.normalized()

        return PackageResult(
            package_id=context.identity.package_id,
            family_id=context.identity.family_id,
            package_path=str(context.package_dir),
            status=status,
            archive_path=str(context.archive_path) if context.archive_path else None,
            correlation_id=context.correlation_id,
            metadata=dict(metadata or {}),
        ).normalized()
    except Exception as exc:
        raise PackageResultError(f"Could not build PackageResult from plan: {exc}") from exc


def package_result_from_context(
    context: Any,
    *,
    status: str = PackageResultStatus.PENDING.value,
    metadata: Mapping[str, Any] | None = None,
) -> PackageResult:
    """Baut ein PackageResult aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context

        return PackageResult(
            package_id=normalized_context.identity.package_id,
            family_id=normalized_context.identity.family_id,
            package_path=str(normalized_context.package_dir),
            status=status,
            archive_path=str(normalized_context.archive_path) if normalized_context.archive_path else None,
            correlation_id=normalized_context.correlation_id,
            metadata=dict(metadata or {}),
        ).normalized()
    except Exception as exc:
        raise PackageResultError(f"Could not build PackageResult from context: {exc}") from exc


def package_result_from_mapping(data: Mapping[str, Any]) -> PackageResult:
    """Baut ein PackageResult aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PackageResultError("PackageResult data must be a mapping.")

        items = tuple(
            package_result_item_from_mapping(item)
            for item in data.get("items", ()) or ()
            if isinstance(item, Mapping)
        )

        validation_result = data.get("validation_result")
        if isinstance(validation_result, Mapping):
            validation_result = validation_result_from_mapping_safe(validation_result)

        return PackageResult(
            package_id=data.get("package_id"),
            family_id=data.get("family_id"),
            package_path=data.get("package_path"),
            status=data.get("status", PackageResultStatus.PENDING.value),
            success=data.get("success"),
            archive_path=data.get("archive_path"),
            items=items,
            validation_result=validation_result,
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            correlation_id=data.get("correlation_id"),
            schema_version=data.get("schema_version", PACKAGE_RESULT_SCHEMA_VERSION),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except PackageResultError:
        raise
    except Exception as exc:
        raise PackageResultError(f"Could not build PackageResult from mapping: {exc}") from exc


def package_result_item_from_mapping(data: Mapping[str, Any]) -> PackageResultItem:
    """Baut ein PackageResultItem aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PackageResultError("PackageResultItem data must be a mapping.")

        return PackageResultItem(
            path=data.get("path"),
            kind=data.get("kind"),
            status=data.get("status"),
            module_name=data.get("module_name") or data.get("module"),
            message=data.get("message", ""),
            source_path=data.get("source_path"),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except PackageResultError:
        raise
    except Exception as exc:
        raise PackageResultError(f"Could not build PackageResultItem: {exc}") from exc


def created_directory_item(
    path: str | Path,
    *,
    module_name: str | None = None,
    message: str = "Directory created.",
) -> PackageResultItem:
    """Factory für erzeugten Ordner."""
    return PackageResultItem(
        path=str(path),
        kind=ResultItemKind.DIRECTORY.value,
        status=ResultItemStatus.CREATED.value,
        module_name=module_name,
        message=message,
    ).normalized()


def created_file_item(
    path: str | Path,
    *,
    module_name: str | None = None,
    message: str = "File written.",
) -> PackageResultItem:
    """Factory für erzeugte Datei."""
    return PackageResultItem(
        path=str(path),
        kind=ResultItemKind.FILE.value,
        status=ResultItemStatus.WRITTEN.value,
        module_name=module_name,
        message=message,
    ).normalized()


def copied_asset_item(
    target_path: str | Path,
    *,
    source_path: str | Path | None = None,
    module_name: str | None = "render",
    message: str = "Asset copied.",
) -> PackageResultItem:
    """Factory für kopiertes Asset."""
    return PackageResultItem(
        path=str(target_path),
        kind=ResultItemKind.ASSET.value,
        status=ResultItemStatus.COPIED.value,
        module_name=module_name,
        message=message,
        source_path=str(source_path) if source_path is not None else None,
    ).normalized()


def skipped_item(
    path: str | Path,
    *,
    kind: str = ResultItemKind.FILE.value,
    module_name: str | None = None,
    message: str = "Skipped.",
) -> PackageResultItem:
    """Factory für übersprungenes Item."""
    return PackageResultItem(
        path=str(path),
        kind=kind,
        status=ResultItemStatus.SKIPPED.value,
        module_name=module_name,
        message=message,
    ).normalized()


def failed_item(
    path: str | Path,
    *,
    kind: str = ResultItemKind.FILE.value,
    module_name: str | None = None,
    message: str = "Failed.",
    metadata: Mapping[str, Any] | None = None,
) -> PackageResultItem:
    """Factory für fehlgeschlagenes Item."""
    return PackageResultItem(
        path=str(path),
        kind=kind,
        status=ResultItemStatus.FAILED.value,
        module_name=module_name,
        message=message,
        metadata=dict(metadata or {}),
    ).normalized()


def compute_success(
    *,
    status: str,
    items: Iterable[PackageResultItem],
    validation_result: Any | None,
) -> bool:
    """Berechnet Erfolg aus Status, Items und Validierung."""
    status_value = parse_package_result_status_value(status)

    if status_value == PackageResultStatus.FAILED.value:
        return False

    for item in items or ():
        if item.normalized().failed:
            return False

    if validation_result is not None and not get_validation_result_valid(validation_result):
        return False

    return status_value in {
        PackageResultStatus.PLANNED.value,
        PackageResultStatus.CREATED.value,
        PackageResultStatus.VALIDATED.value,
        PackageResultStatus.ARCHIVED.value,
        PackageResultStatus.SKIPPED.value,
        PackageResultStatus.PENDING.value,
    }


def normalize_validation_result(value: Any) -> Any | None:
    """Normalisiert optional ein ValidationResult."""
    if value is None:
        return None

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping):
            return validation_result_from_mapping_safe(value)

        return value
    except Exception as exc:
        raise PackageResultError(f"Invalid validation result: {exc}") from exc


def validation_result_from_mapping_safe(value: Mapping[str, Any]) -> Any:
    """Baut ein ValidationResult, wenn das Modell verfügbar ist."""
    try:
        from .validation_result import validation_result_from_mapping

        return validation_result_from_mapping(value)
    except Exception:
        return dict(value)


def get_validation_result_valid(value: Any) -> bool:
    """Liest gültig/ungültig aus einem ValidationResult-ähnlichen Objekt."""
    if value is None:
        return True

    if hasattr(value, "is_valid"):
        return bool(value.is_valid)

    if hasattr(value, "valid"):
        return bool(value.valid)

    if isinstance(value, Mapping):
        return bool(value.get("valid", False))

    return False


def parse_package_result_status_value(value: Any) -> str:
    """Parst PackageResultStatus."""
    try:
        if isinstance(value, PackageResultStatus):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return PackageResultStatus(raw).value
    except Exception as exc:
        raise PackageResultError(f"Invalid package result status {value!r}.") from exc


def parse_result_item_kind_value(value: Any) -> str:
    """Parst ResultItemKind."""
    try:
        if isinstance(value, ResultItemKind):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return ResultItemKind(raw).value
    except Exception as exc:
        raise PackageResultError(f"Invalid result item kind {value!r}.") from exc


def parse_result_item_status_value(value: Any) -> str:
    """Parst ResultItemStatus."""
    try:
        if isinstance(value, ResultItemStatus):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return ResultItemStatus(raw).value
    except Exception as exc:
        raise PackageResultError(f"Invalid result item status {value!r}.") from exc


def normalize_optional_module_name(value: Any) -> str | None:
    """Normalisiert optionalen Modulnamen."""
    if value is None:
        return None

    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception:
        return clean_optional_string(value)


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise PackageResultError("metadata must be a mapping.")

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


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise PackageResultError(f"{field_name} is required.")

        return cleaned
    except PackageResultError:
        raise
    except Exception as exc:
        raise PackageResultError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def utc_now_iso() -> str:
    """Gibt einen UTC-Zeitstempel im ISO-Format zurück."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def clear_package_result_caches() -> None:
    """Reserviert für spätere Parser-Caches."""
    return None


__all__ = [
    "PACKAGE_RESULT_SCHEMA_VERSION",
    "PackageResult",
    "PackageResultError",
    "PackageResultItem",
    "PackageResultStatus",
    "ResultItemKind",
    "ResultItemStatus",
    "clean_optional_string",
    "clean_required_string",
    "clear_package_result_caches",
    "compute_success",
    "copied_asset_item",
    "created_directory_item",
    "created_file_item",
    "failed_item",
    "get_validation_result_valid",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_optional_module_name",
    "normalize_validation_result",
    "package_result_from_context",
    "package_result_from_mapping",
    "package_result_from_plan",
    "package_result_item_from_mapping",
    "parse_package_result_status_value",
    "parse_result_item_kind_value",
    "parse_result_item_status_value",
    "skipped_item",
    "utc_now_iso",
    "validation_result_from_mapping_safe",
]