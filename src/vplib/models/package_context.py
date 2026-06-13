# services/vectoplan-library/src/vplib/models/package_context.py
"""
PackageContext model for the VPLIB package engine.

Diese Datei beschreibt den Laufzeitkontext für die Erstellung eines modularen
VPLIB-Packages.

Rolle dieser Datei:

    normalized CreateRequest
    -> PackageContext
    -> planning / creation / validation / serialization

Der Context enthält keine fertigen Modulpläne. Er hält nur:
- stabile IDs
- Zielpfade
- Zeitstempel
- Schreiboptionen
- Klassifikationspfad
- Request-Referenz
- Metadaten für Reports und spätere Routen

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping


PACKAGE_CONTEXT_SCHEMA_VERSION: Final[str] = "vplib.package_context.v1"

DEFAULT_PACKAGE_ROOT_NAME: Final[str] = "library_catalog"
DEFAULT_SOURCE_ROOT_NAME: Final[str] = "source"
DEFAULT_GENERATED_ROOT_NAME: Final[str] = "generated"
DEFAULT_ARCHIVE_ROOT_NAME: Final[str] = "packages"


class PackageContextError(ValueError):
    """Wird ausgelöst, wenn ein PackageContext ungültig aufgebaut wird."""


class PackageWriteMode(str, Enum):
    """Schreibmodus für Package-Erstellung."""

    CREATE_ONLY = "create_only"
    OVERWRITE = "overwrite"
    DRY_RUN = "dry_run"

    @property
    def key(self) -> str:
        return str(self.value)


class PackageContextStatus(str, Enum):
    """Status des Package-Kontexts."""

    CREATED = "created"
    NORMALIZED = "normalized"
    PLANNED = "planned"
    WRITING = "writing"
    WRITTEN = "written"
    VALIDATING = "validating"
    VALIDATED = "validated"
    ARCHIVED = "archived"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PackageRootPaths:
    """
    Root-Pfade für die Package-Erstellung.

    Alle Pfade sind pathlib.Path-Objekte. Diese Klasse erzeugt keine Ordner.
    """

    service_root: Path
    library_catalog_root: Path
    source_root: Path
    generated_root: Path
    archive_root: Path

    def normalized(self) -> "PackageRootPaths":
        service_root = normalize_path(self.service_root, "service_root")
        library_catalog_root = normalize_path(
            self.library_catalog_root,
            "library_catalog_root",
        )
        source_root = normalize_path(self.source_root, "source_root")
        generated_root = normalize_path(self.generated_root, "generated_root")
        archive_root = normalize_path(self.archive_root, "archive_root")

        return PackageRootPaths(
            service_root=service_root,
            library_catalog_root=library_catalog_root,
            source_root=source_root,
            generated_root=generated_root,
            archive_root=archive_root,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "service_root": str(normalized.service_root),
            "library_catalog_root": str(normalized.library_catalog_root),
            "source_root": str(normalized.source_root),
            "generated_root": str(normalized.generated_root),
            "archive_root": str(normalized.archive_root),
        }


@dataclass(frozen=True, slots=True)
class PackageIdentityContext:
    """Normalisierte Package-Identität."""

    package_id: str
    family_id: str
    family_slug: str
    family_name: str
    version: str

    def normalized(self) -> "PackageIdentityContext":
        return PackageIdentityContext(
            package_id=normalize_required_string(self.package_id, "package_id"),
            family_id=normalize_required_string(self.family_id, "family_id"),
            family_slug=normalize_slug_like(self.family_slug, "family_slug"),
            family_name=normalize_required_string(self.family_name, "family_name"),
            version=normalize_required_string(self.version, "version"),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "family_slug": normalized.family_slug,
            "family_name": normalized.family_name,
            "version": normalized.version,
        }


@dataclass(frozen=True, slots=True)
class PackageClassificationContext:
    """Normalisierter Klassifikationskontext."""

    domain: str
    category: str
    subcategory: str
    classification_path: str

    def normalized(self) -> "PackageClassificationContext":
        try:
            from ..domain.classification import build_classification_path

            parsed = build_classification_path(
                domain=self.domain,
                category=self.category,
                subcategory=self.subcategory,
            )

            return PackageClassificationContext(
                domain=parsed.domain.value,
                category=parsed.category,
                subcategory=parsed.subcategory,
                classification_path=parsed.path,
            )
        except Exception as exc:
            raise PackageContextError(f"Invalid package classification context: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "classification_path": normalized.classification_path,
        }


@dataclass(frozen=True, slots=True)
class PackageLocationContext:
    """
    Zielpfade eines Packages.

    package_relative_dir ist relativ zum source_root.
    package_dir ist der absolute Zielordner.
    archive_path ist optional und zeigt auf die spätere .vplib-Datei.
    """

    package_relative_dir: str
    package_dir: Path
    archive_path: Path | None = None

    def normalized(self) -> "PackageLocationContext":
        package_relative_dir = normalize_relative_package_dir(self.package_relative_dir)
        package_dir = normalize_path(self.package_dir, "package_dir")
        archive_path = (
            normalize_path(self.archive_path, "archive_path")
            if self.archive_path is not None
            else None
        )

        return PackageLocationContext(
            package_relative_dir=package_relative_dir,
            package_dir=package_dir,
            archive_path=archive_path,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "package_relative_dir": normalized.package_relative_dir,
            "package_dir": str(normalized.package_dir),
            "archive_path": str(normalized.archive_path) if normalized.archive_path else None,
        }


@dataclass(frozen=True, slots=True)
class PackageExecutionContext:
    """Ausführungsoptionen des Erstellvorgangs."""

    write_mode: str = PackageWriteMode.CREATE_ONLY.value
    strict: bool = True
    validate_after_create: bool = True
    create_archive: bool = False
    include_docs: bool = False
    include_tests: bool = False

    def normalized(self) -> "PackageExecutionContext":
        write_mode = parse_write_mode_value(self.write_mode)

        return PackageExecutionContext(
            write_mode=write_mode,
            strict=bool(self.strict),
            validate_after_create=bool(self.validate_after_create),
            create_archive=bool(self.create_archive),
            include_docs=bool(self.include_docs),
            include_tests=bool(self.include_tests),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "write_mode": normalized.write_mode,
            "strict": normalized.strict,
            "validate_after_create": normalized.validate_after_create,
            "create_archive": normalized.create_archive,
            "include_docs": normalized.include_docs,
            "include_tests": normalized.include_tests,
        }


@dataclass(frozen=True, slots=True)
class PackageContext:
    """
    Zentraler Laufzeitkontext für einen VPLIB-Erstellvorgang.

    Der Context ist absichtlich immutable. Jede Phase kann einen neuen Context
    mit geändertem Status erzeugen, statt diesen zu verändern.
    """

    request: Any
    roots: PackageRootPaths
    identity: PackageIdentityContext
    classification: PackageClassificationContext
    location: PackageLocationContext
    execution: PackageExecutionContext
    object_kind: str
    status: str = PackageContextStatus.CREATED.value
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageContext":
        request = normalize_create_request(self.request)
        roots = self.roots.normalized()
        identity = self.identity.normalized()
        classification = self.classification.normalized()
        location = self.location.normalized()
        execution = self.execution.normalized()
        object_kind = normalize_object_kind_value(self.object_kind)
        status = parse_context_status_value(self.status)
        correlation_id = normalize_required_string(self.correlation_id, "correlation_id")
        created_at = normalize_required_string(self.created_at, "created_at")
        updated_at = normalize_required_string(self.updated_at, "updated_at")
        metadata = dict(self.metadata or {})

        ensure_location_matches_classification(
            location=location,
            classification=classification,
            identity=identity,
        )

        return PackageContext(
            request=request,
            roots=roots,
            identity=identity,
            classification=classification,
            location=location,
            execution=execution,
            object_kind=object_kind,
            status=status,
            correlation_id=correlation_id,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )

    def with_status(self, status: str) -> "PackageContext":
        """Erzeugt einen neuen Context mit geändertem Status."""
        normalized = self.normalized()

        return PackageContext(
            request=normalized.request,
            roots=normalized.roots,
            identity=normalized.identity,
            classification=normalized.classification,
            location=normalized.location,
            execution=normalized.execution,
            object_kind=normalized.object_kind,
            status=parse_context_status_value(status),
            correlation_id=normalized.correlation_id,
            created_at=normalized.created_at,
            updated_at=utc_now_iso(),
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_metadata(self, metadata: Mapping[str, Any]) -> "PackageContext":
        """Erzeugt einen neuen Context mit zusammengeführten Metadaten."""
        normalized = self.normalized()
        merged_metadata = dict(normalized.metadata)
        merged_metadata.update(dict(metadata or {}))

        return PackageContext(
            request=normalized.request,
            roots=normalized.roots,
            identity=normalized.identity,
            classification=normalized.classification,
            location=normalized.location,
            execution=normalized.execution,
            object_kind=normalized.object_kind,
            status=normalized.status,
            correlation_id=normalized.correlation_id,
            created_at=normalized.created_at,
            updated_at=utc_now_iso(),
            metadata=merged_metadata,
        ).normalized()

    @property
    def package_dir(self) -> Path:
        """Gibt den absoluten Package-Zielordner zurück."""
        return self.normalized().location.package_dir

    @property
    def package_relative_dir(self) -> str:
        """Gibt den relativen Package-Pfad ab source_root zurück."""
        return self.normalized().location.package_relative_dir

    @property
    def archive_path(self) -> Path | None:
        """Gibt den optionalen Archivpfad zurück."""
        return self.normalized().location.archive_path

    @property
    def is_dry_run(self) -> bool:
        """Gibt zurück, ob der Context im Dry-Run-Modus arbeitet."""
        return self.normalized().execution.write_mode == PackageWriteMode.DRY_RUN.value

    @property
    def may_overwrite(self) -> bool:
        """Gibt zurück, ob bestehende Packages überschrieben werden dürfen."""
        return self.normalized().execution.write_mode == PackageWriteMode.OVERWRITE.value

    def to_dict(self) -> dict[str, Any]:
        """Serialisiert den Context JSON-kompatibel."""
        normalized = self.normalized()

        return {
            "schema_version": PACKAGE_CONTEXT_SCHEMA_VERSION,
            "correlation_id": normalized.correlation_id,
            "status": normalized.status,
            "created_at": normalized.created_at,
            "updated_at": normalized.updated_at,
            "object_kind": normalized.object_kind,
            "identity": normalized.identity.to_dict(),
            "classification": normalized.classification.to_dict(),
            "roots": normalized.roots.to_dict(),
            "location": normalized.location.to_dict(),
            "execution": normalized.execution.to_dict(),
            "metadata": dict(normalized.metadata),
        }


def create_package_context(
    *,
    request: Any,
    service_root: str | Path,
    library_catalog_root: str | Path | None = None,
    source_root: str | Path | None = None,
    generated_root: str | Path | None = None,
    archive_root: str | Path | None = None,
    write_mode: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageContext:
    """
    Erzeugt einen PackageContext aus einem CreateRequest.

    Diese Funktion ist der bevorzugte Einstieg für Planner und Creator.
    """
    try:
        normalized_request = normalize_create_request(request)

        service_root_path = normalize_path(service_root, "service_root")
        library_catalog_root_path = (
            normalize_path(library_catalog_root, "library_catalog_root")
            if library_catalog_root is not None
            else service_root_path / DEFAULT_PACKAGE_ROOT_NAME
        )
        source_root_path = (
            normalize_path(source_root, "source_root")
            if source_root is not None
            else library_catalog_root_path / DEFAULT_SOURCE_ROOT_NAME
        )
        generated_root_path = (
            normalize_path(generated_root, "generated_root")
            if generated_root is not None
            else library_catalog_root_path / DEFAULT_GENERATED_ROOT_NAME
        )
        archive_root_path = (
            normalize_path(archive_root, "archive_root")
            if archive_root is not None
            else generated_root_path / DEFAULT_ARCHIVE_ROOT_NAME
        )

        identity = PackageIdentityContext(
            package_id=normalized_request.identity.package_id or normalized_request.identity.family_id,
            family_id=normalized_request.identity.family_id,
            family_slug=normalized_request.identity.family_slug or normalized_request.identity.family_id.split(".")[-1],
            family_name=normalized_request.identity.family_name,
            version=normalized_request.identity.version,
        ).normalized()

        classification = PackageClassificationContext(
            domain=normalized_request.classification.domain,
            category=normalized_request.classification.category,
            subcategory=normalized_request.classification.subcategory,
            classification_path=(
                f"{normalized_request.classification.domain}/"
                f"{normalized_request.classification.category}/"
                f"{normalized_request.classification.subcategory}"
            ),
        ).normalized()

        relative_dir = build_package_relative_dir(
            classification=classification,
            identity=identity,
        )
        package_dir = source_root_path / Path(relative_dir)
        archive_path = archive_root_path / f"{identity.family_slug}.vplib"

        roots = PackageRootPaths(
            service_root=service_root_path,
            library_catalog_root=library_catalog_root_path,
            source_root=source_root_path,
            generated_root=generated_root_path,
            archive_root=archive_root_path,
        ).normalized()

        resolved_write_mode = resolve_write_mode(
            requested_write_mode=write_mode,
            overwrite_existing=normalized_request.options.overwrite_existing,
        )

        execution = PackageExecutionContext(
            write_mode=resolved_write_mode,
            strict=normalized_request.options.strict,
            validate_after_create=normalized_request.options.validate_after_create,
            create_archive=normalized_request.options.create_archive,
            include_docs=normalized_request.options.include_docs,
            include_tests=normalized_request.options.include_tests,
        ).normalized()

        location = PackageLocationContext(
            package_relative_dir=relative_dir,
            package_dir=package_dir,
            archive_path=archive_path if execution.create_archive else None,
        ).normalized()

        return PackageContext(
            request=normalized_request,
            roots=roots,
            identity=identity,
            classification=classification,
            location=location,
            execution=execution,
            object_kind=normalized_request.object_kind,
            status=PackageContextStatus.NORMALIZED.value,
            metadata=dict(metadata or {}),
        ).normalized()
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Could not create package context: {exc}") from exc


def normalize_create_request(request: Any) -> Any:
    """
    Normalisiert ein CreateRequest-Objekt.

    Wenn ein Mapping übergeben wird, wird daraus ein CreateRequest erzeugt.
    """
    try:
        from .create_request import CreateRequest, create_request_from_mapping

        if isinstance(request, CreateRequest):
            return request.normalized()

        if isinstance(request, Mapping):
            return create_request_from_mapping(request).normalized()

        if hasattr(request, "normalized") and callable(request.normalized):
            return request.normalized()

        raise PackageContextError("request must be a CreateRequest or mapping.")
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Invalid create request: {exc}") from exc


def build_package_relative_dir(
    *,
    classification: PackageClassificationContext,
    identity: PackageIdentityContext,
) -> str:
    """
    Baut den relativen Package-Pfad:

        domain/category/family_slug

    Die Subkategorie bleibt in family/classification.json enthalten, aber der
    Ordnerpfad bleibt bewusst flacher und kompatibel mit:
        source/<domain>/<category>/<family>/
    """
    try:
        normalized_classification = classification.normalized()
        normalized_identity = identity.normalized()

        relative_dir = (
            f"{normalized_classification.domain}/"
            f"{normalized_classification.category}/"
            f"{normalized_identity.family_slug}"
        )

        return normalize_relative_package_dir(relative_dir)
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Could not build package relative directory: {exc}") from exc


def ensure_location_matches_classification(
    *,
    location: PackageLocationContext,
    classification: PackageClassificationContext,
    identity: PackageIdentityContext,
) -> None:
    """Prüft, ob der relative Package-Pfad zur Klassifikation passt."""
    expected = build_package_relative_dir(
        classification=classification,
        identity=identity,
    )
    actual = location.normalized().package_relative_dir

    if actual != expected:
        raise PackageContextError(
            f"Package location mismatch. Expected {expected!r}, got {actual!r}."
        )


def resolve_write_mode(
    *,
    requested_write_mode: str | None,
    overwrite_existing: bool,
) -> str:
    """Löst den Schreibmodus aus explizitem Wert und Request-Optionen auf."""
    if requested_write_mode:
        return parse_write_mode_value(requested_write_mode)

    if overwrite_existing:
        return PackageWriteMode.OVERWRITE.value

    return PackageWriteMode.CREATE_ONLY.value


def parse_write_mode_value(value: Any) -> str:
    """Parst einen Schreibmodus."""
    try:
        if isinstance(value, PackageWriteMode):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")

        aliases = {
            "create": PackageWriteMode.CREATE_ONLY.value,
            "create_only": PackageWriteMode.CREATE_ONLY.value,
            "new": PackageWriteMode.CREATE_ONLY.value,
            "overwrite": PackageWriteMode.OVERWRITE.value,
            "replace": PackageWriteMode.OVERWRITE.value,
            "dry": PackageWriteMode.DRY_RUN.value,
            "dry_run": PackageWriteMode.DRY_RUN.value,
            "preview": PackageWriteMode.DRY_RUN.value,
        }

        if raw in aliases:
            return aliases[raw]

        return PackageWriteMode(raw).value
    except Exception as exc:
        raise PackageContextError(f"Invalid write mode {value!r}.") from exc


def parse_context_status_value(value: Any) -> str:
    """Parst einen Context-Status."""
    try:
        if isinstance(value, PackageContextStatus):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return PackageContextStatus(raw).value
    except Exception as exc:
        raise PackageContextError(f"Invalid package context status {value!r}.") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert die Objektart."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise PackageContextError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_path(value: Any, field_name: str) -> Path:
    """Normalisiert einen lokalen Dateisystempfad."""
    try:
        if value is None:
            raise PackageContextError(f"{field_name} is required.")

        path = Path(value).expanduser()

        if not str(path).strip():
            raise PackageContextError(f"{field_name} is empty.")

        return path
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_relative_package_dir(value: Any) -> str:
    """Normalisiert einen relativen Package-Ordnerpfad."""
    try:
        from ..domain.package_paths import normalize_package_path

        normalized = normalize_package_path(value)

        if "." in Path(normalized).name:
            raise PackageContextError(
                f"Package directory must not look like a file path: {normalized!r}."
            )

        return normalized
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Invalid relative package directory {value!r}: {exc}") from exc


def normalize_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise PackageContextError(f"{field_name} is required.")

        return cleaned
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"{field_name} must be string-like.") from exc


def normalize_slug_like(value: Any, field_name: str) -> str:
    """Normalisiert und prüft einen einfachen Slug."""
    try:
        from .create_request import normalize_slug

        return normalize_slug(value, field_name=field_name)
    except Exception as exc:
        raise PackageContextError(f"Invalid slug for {field_name}: {exc}") from exc


def utc_now_iso() -> str:
    """Gibt einen UTC-Zeitstempel im ISO-Format zurück."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def context_from_dict(data: Mapping[str, Any], *, request: Any) -> PackageContext:
    """
    Baut einen PackageContext aus einem Dictionary.

    Diese Funktion ist primär für Tests, Reports oder spätere Persistenz gedacht.
    """
    try:
        if not isinstance(data, Mapping):
            raise PackageContextError("PackageContext data must be a mapping.")

        roots_data = require_mapping(data, "roots")
        identity_data = require_mapping(data, "identity")
        classification_data = require_mapping(data, "classification")
        location_data = require_mapping(data, "location")
        execution_data = require_mapping(data, "execution")

        return PackageContext(
            request=request,
            roots=PackageRootPaths(
                service_root=roots_data["service_root"],
                library_catalog_root=roots_data["library_catalog_root"],
                source_root=roots_data["source_root"],
                generated_root=roots_data["generated_root"],
                archive_root=roots_data["archive_root"],
            ),
            identity=PackageIdentityContext(
                package_id=identity_data["package_id"],
                family_id=identity_data["family_id"],
                family_slug=identity_data["family_slug"],
                family_name=identity_data["family_name"],
                version=identity_data["version"],
            ),
            classification=PackageClassificationContext(
                domain=classification_data["domain"],
                category=classification_data["category"],
                subcategory=classification_data["subcategory"],
                classification_path=classification_data["classification_path"],
            ),
            location=PackageLocationContext(
                package_relative_dir=location_data["package_relative_dir"],
                package_dir=location_data["package_dir"],
                archive_path=location_data.get("archive_path"),
            ),
            execution=PackageExecutionContext(
                write_mode=execution_data.get("write_mode", PackageWriteMode.CREATE_ONLY.value),
                strict=execution_data.get("strict", True),
                validate_after_create=execution_data.get("validate_after_create", True),
                create_archive=execution_data.get("create_archive", False),
                include_docs=execution_data.get("include_docs", False),
                include_tests=execution_data.get("include_tests", False),
            ),
            object_kind=data["object_kind"],
            status=data.get("status", PackageContextStatus.CREATED.value),
            correlation_id=data.get("correlation_id", uuid.uuid4().hex),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", utc_now_iso()),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Could not build PackageContext from dict: {exc}") from exc


def require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Liest ein Pflicht-Mapping aus einem Mapping."""
    value = data.get(key)

    if not isinstance(value, Mapping):
        raise PackageContextError(f"{key} must be an object.")

    return value


def clear_package_context_caches() -> None:
    """Reserviert für spätere Caches; derzeit keine externen Caches."""
    return None


__all__ = [
    "DEFAULT_ARCHIVE_ROOT_NAME",
    "DEFAULT_GENERATED_ROOT_NAME",
    "DEFAULT_PACKAGE_ROOT_NAME",
    "DEFAULT_SOURCE_ROOT_NAME",
    "PACKAGE_CONTEXT_SCHEMA_VERSION",
    "PackageClassificationContext",
    "PackageContext",
    "PackageContextError",
    "PackageContextStatus",
    "PackageExecutionContext",
    "PackageIdentityContext",
    "PackageLocationContext",
    "PackageRootPaths",
    "PackageWriteMode",
    "build_package_relative_dir",
    "clear_package_context_caches",
    "context_from_dict",
    "create_package_context",
    "ensure_location_matches_classification",
    "normalize_create_request",
    "normalize_object_kind_value",
    "normalize_path",
    "normalize_relative_package_dir",
    "normalize_required_string",
    "normalize_slug_like",
    "parse_context_status_value",
    "parse_write_mode_value",
    "require_mapping",
    "resolve_write_mode",
    "utc_now_iso",
]