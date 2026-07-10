# services/vectoplan-library/src/vplib/models/package_context.py
"""
PackageContext model for the VPLIB package engine.

Diese Datei beschreibt den unveränderlichen Laufzeitkontext für die Planung,
Erstellung, Validierung und Archivierung eines modularen VPLIB-Packages.

    normalized CreateRequest
    -> PackageContext
    -> planning / creation / validation / serialization

Der Context schreibt keine Dateien und legt keine Verzeichnisse an. Er hält nur
kanonische Identitäten, Profilbindungen, sichere Zielpfade, Ausführungsoptionen,
Status- und Diagnosemetadaten.

Verbindlicher Vertrag:
- ``vplib_uid`` bleibt über Request, Context, Plan und Archiv unverändert.
- Family-/Variant-Profile bleiben explizit und widerspruchsfrei erhalten.
- ``cell_block`` verwendet ``simple_cell_block`` / ``simple_cell_block.v1``.
- Source-Pfade sind vierteilig: domain/category/subcategory/family_slug.
- Package- und Archivpfade dürfen ihre konfigurierten Roots nicht verlassen.
- Alle Normalisierungen sind import-sicher und ohne Dateisystem-Schreibzugriff.
- Metadaten sind JSON-kompatibel, begrenzt und können geschützte Identitäten
  nicht überschreiben.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Mapping


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PACKAGE_CONTEXT_SCHEMA_VERSION: Final[str] = "vplib.package_context.v1"
PACKAGE_CONTEXT_COMPONENT: Final[str] = "vplib-package-context"
PACKAGE_CONTEXT_COMPONENT_VERSION: Final[str] = "2.0.0"

DEFAULT_PACKAGE_ROOT_NAME: Final[str] = "library_catalog"
DEFAULT_SOURCE_ROOT_NAME: Final[str] = "source"
DEFAULT_GENERATED_ROOT_NAME: Final[str] = "generated"
DEFAULT_ARCHIVE_ROOT_NAME: Final[str] = "packages"

DEFAULT_STARTER_OBJECT_KIND: Final[str] = "cell_block"
DEFAULT_STARTER_FAMILY_PROFILE_ID: Final[str] = "simple_cell_block"
DEFAULT_STARTER_VARIANT_PROFILE_ID: Final[str] = "simple_cell_block.v1"

MAX_METADATA_DEPTH: Final[int] = 12
MAX_METADATA_ITEMS: Final[int] = 20_000
MAX_STRING_LENGTH: Final[int] = 16_384
MAX_PATH_LENGTH: Final[int] = 4096
MAX_SEGMENT_LENGTH: Final[int] = 160

SAFE_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_PROFILE_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_CORRELATION_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$"
)

PROTECTED_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "component",
        "component_version",
        "vplib_uid",
        "family_profile_id",
        "variant_profile_id",
        "object_kind",
        "family_id",
        "package_id",
        "family_slug",
        "classification_path",
        "source_path",
        "package_relative_dir",
        "package_dir",
        "archive_path",
        "request_fingerprint",
        "context_fingerprint",
        "correlation_id",
    }
)

_STATUS_TRANSITIONS: Final[Mapping[str, frozenset[str]]] = {
    "created": frozenset({
        "created", "normalized", "planned", "writing", "written",
        "validating", "validated", "archived", "failed",
    }),
    "normalized": frozenset({
        "normalized", "planned", "writing", "written", "validating",
        "validated", "archived", "failed",
    }),
    "planned": frozenset({
        "planned", "writing", "written", "validating", "validated",
        "archived", "failed",
    }),
    "writing": frozenset({
        "writing", "written", "validating", "validated", "archived",
        "failed",
    }),
    "written": frozenset({
        "written", "validating", "validated", "archived", "failed",
    }),
    "validating": frozenset({
        "validating", "validated", "archived", "failed",
    }),
    "validated": frozenset({"validated", "archived", "failed"}),
    "archived": frozenset({"archived"}),
    "failed": frozenset({"failed"}),
}


# ---------------------------------------------------------------------------
# Exceptions and enums
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PackageRootPaths:
    """
    Root-Pfade für die Package-Erstellung.

    Alle Werte sind absolute, normalisierte ``Path``-Objekte. Die Klasse prüft
    Pfadform und Root-Konsistenz, erzeugt aber keine Ordner.
    """

    service_root: Path
    library_catalog_root: Path
    source_root: Path
    generated_root: Path
    archive_root: Path

    def normalized(self) -> "PackageRootPaths":
        roots = PackageRootPaths(
            service_root=normalize_path(self.service_root, "service_root"),
            library_catalog_root=normalize_path(
                self.library_catalog_root,
                "library_catalog_root",
            ),
            source_root=normalize_path(self.source_root, "source_root"),
            generated_root=normalize_path(self.generated_root, "generated_root"),
            archive_root=normalize_path(self.archive_root, "archive_root"),
        )
        validate_root_paths(roots)
        return roots

    def contains_source_path(self, path: Any) -> bool:
        normalized = self.normalized()
        return is_path_within(normalize_path(path, "source_path"), normalized.source_root)

    def contains_archive_path(self, path: Any) -> bool:
        normalized = self.normalized()
        return is_path_within(normalize_path(path, "archive_path"), normalized.archive_root)

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
    """Normalisierte Package-Identität inklusive stabiler ``vplib_uid``."""

    package_id: str
    family_id: str
    family_slug: str
    family_name: str
    version: str
    vplib_uid: str | None = None

    def normalized(self) -> "PackageIdentityContext":
        return PackageIdentityContext(
            package_id=normalize_identifier(self.package_id, "package_id"),
            family_id=normalize_identifier(self.family_id, "family_id"),
            family_slug=normalize_slug_like(self.family_slug, "family_slug"),
            family_name=normalize_required_string(self.family_name, "family_name"),
            version=normalize_package_version(self.version),
            vplib_uid=(
                normalize_vplib_uid(self.vplib_uid)
                if self.vplib_uid is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "vplib_uid": normalized.vplib_uid,
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
        domain = normalize_taxonomy_segment(self.domain, "domain")
        category = normalize_taxonomy_segment(self.category, "category")
        subcategory = normalize_taxonomy_segment(self.subcategory, "subcategory")
        expected_path = f"{domain}/{category}/{subcategory}"

        parsed = try_build_classification_path(
            domain=domain,
            category=category,
            subcategory=subcategory,
        )
        if parsed is not None:
            domain = normalize_taxonomy_segment(
                extract_value(parsed, "domain", fallback=domain),
                "domain",
            )
            category = normalize_taxonomy_segment(
                extract_value(parsed, "category", fallback=category),
                "category",
            )
            subcategory = normalize_taxonomy_segment(
                extract_value(parsed, "subcategory", fallback=subcategory),
                "subcategory",
            )
            expected_path = normalize_classification_path(
                extract_value(parsed, "path", fallback=f"{domain}/{category}/{subcategory}"),
                domain=domain,
                category=category,
                subcategory=subcategory,
            )

        supplied_path = normalize_optional_string(self.classification_path)
        if supplied_path:
            actual_path = normalize_classification_path(
                supplied_path,
                domain=domain,
                category=category,
                subcategory=subcategory,
            )
            if actual_path != expected_path:
                raise PackageContextError(
                    "classification_path does not match domain/category/subcategory: "
                    f"expected {expected_path!r}, got {actual_path!r}."
                )

        return PackageClassificationContext(
            domain=domain,
            category=category,
            subcategory=subcategory,
            classification_path=expected_path,
        )

    @property
    def source_parts(self) -> tuple[str, str, str]:
        normalized = self.normalized()
        return (
            normalized.domain,
            normalized.category,
            normalized.subcategory,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "classification_path": normalized.classification_path,
            "source_parts": list(normalized.source_parts),
        }


@dataclass(frozen=True, slots=True)
class PackageProfileContext:
    """Explizite, unveränderliche Profilbindung eines CreateRequests."""

    object_kind: str
    family_profile_id: str
    variant_profile_id: str

    def normalized(self) -> "PackageProfileContext":
        object_kind = normalize_object_kind_value(self.object_kind)
        family_profile_id = normalize_profile_id(
            self.family_profile_id,
            "family_profile_id",
        )
        variant_profile_id = normalize_profile_id(
            self.variant_profile_id,
            "variant_profile_id",
        )

        if object_kind == DEFAULT_STARTER_OBJECT_KIND:
            if family_profile_id != DEFAULT_STARTER_FAMILY_PROFILE_ID:
                raise PackageContextError(
                    "cell_block requires family_profile_id="
                    f"{DEFAULT_STARTER_FAMILY_PROFILE_ID!r}."
                )
            if variant_profile_id != DEFAULT_STARTER_VARIANT_PROFILE_ID:
                raise PackageContextError(
                    "cell_block requires variant_profile_id="
                    f"{DEFAULT_STARTER_VARIANT_PROFILE_ID!r}."
                )

        return PackageProfileContext(
            object_kind=object_kind,
            family_profile_id=family_profile_id,
            variant_profile_id=variant_profile_id,
        )

    @property
    def profile_key(self) -> str:
        return self.normalized().variant_profile_id

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "object_kind": normalized.object_kind,
            "family_profile_id": normalized.family_profile_id,
            "variant_profile_id": normalized.variant_profile_id,
            "profile_key": normalized.variant_profile_id,
        }


@dataclass(frozen=True, slots=True)
class PackageLocationContext:
    """
    Zielpfade eines Packages.

    ``package_relative_dir`` ist relativ zu ``source_root``. ``package_dir`` ist
    absolut. ``archive_path`` ist optional und zeigt auf die spätere
    ``.vplib``-Datei.
    """

    package_relative_dir: str
    package_dir: Path
    archive_path: Path | None = None

    def normalized(self) -> "PackageLocationContext":
        package_relative_dir = normalize_relative_package_dir(self.package_relative_dir)
        package_dir = normalize_path(self.package_dir, "package_dir")
        archive_path = (
            normalize_archive_path(self.archive_path)
            if self.archive_path is not None
            else None
        )

        return PackageLocationContext(
            package_relative_dir=package_relative_dir,
            package_dir=package_dir,
            archive_path=archive_path,
        )

    @property
    def source_path(self) -> str:
        return self.normalized().package_relative_dir

    @property
    def archive_filename(self) -> str | None:
        normalized = self.normalized()
        return normalized.archive_path.name if normalized.archive_path else None

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "package_relative_dir": normalized.package_relative_dir,
            "source_path": normalized.package_relative_dir,
            "package_path": normalized.package_relative_dir,
            "package_dir": str(normalized.package_dir),
            "archive_path": str(normalized.archive_path) if normalized.archive_path else None,
            "archive_filename": normalized.archive_filename,
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
            strict=normalize_bool(self.strict, default=True),
            validate_after_create=normalize_bool(
                self.validate_after_create,
                default=True,
            ),
            create_archive=normalize_bool(self.create_archive, default=False),
            include_docs=normalize_bool(self.include_docs, default=False),
            include_tests=normalize_bool(self.include_tests, default=False),
        )

    @property
    def is_dry_run(self) -> bool:
        return self.normalized().write_mode == PackageWriteMode.DRY_RUN.value

    @property
    def may_overwrite(self) -> bool:
        return self.normalized().write_mode == PackageWriteMode.OVERWRITE.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        return {
            "write_mode": normalized.write_mode,
            "strict": normalized.strict,
            "validate_after_create": normalized.validate_after_create,
            "create_archive": normalized.create_archive,
            "include_docs": normalized.include_docs,
            "include_tests": normalized.include_tests,
            "is_dry_run": normalized.is_dry_run,
            "may_overwrite": normalized.may_overwrite,
        }


@dataclass(frozen=True, slots=True)
class PackageContext:
    """
    Zentraler Laufzeitkontext für einen VPLIB-Erstellvorgang.

    Der Context ist immutable. Jede Phase erzeugt bei Status-, Metadaten- oder
    Location-Änderungen eine neue Instanz.
    """

    request: Any
    roots: PackageRootPaths
    identity: PackageIdentityContext
    classification: PackageClassificationContext
    location: PackageLocationContext
    execution: PackageExecutionContext
    object_kind: str
    status: str = PackageContextStatus.CREATED.value
    correlation_id: str = ""
    created_at: str = field(default_factory=lambda: utc_now_iso())
    updated_at: str = field(default_factory=lambda: utc_now_iso())
    metadata: Mapping[str, Any] = field(default_factory=dict)
    profiles: PackageProfileContext | None = None

    def normalized(self) -> "PackageContext":
        request = normalize_create_request(self.request)
        request_contract = extract_request_contract(request)

        roots = self.roots.normalized()
        identity = self.identity.normalized()
        classification = self.classification.normalized()
        location = self.location.normalized()
        execution = self.execution.normalized()
        object_kind = normalize_object_kind_value(self.object_kind)

        profiles = (
            self.profiles.normalized()
            if self.profiles is not None
            else PackageProfileContext(
                object_kind=object_kind,
                family_profile_id=request_contract["family_profile_id"],
                variant_profile_id=request_contract["variant_profile_id"],
            ).normalized()
        )

        status = parse_context_status_value(self.status)
        created_at = normalize_timestamp(self.created_at, "created_at")
        updated_at = normalize_timestamp(self.updated_at, "updated_at")
        if parse_timestamp(updated_at) < parse_timestamp(created_at):
            raise PackageContextError("updated_at must not be earlier than created_at.")

        request_uid = request_contract["vplib_uid"]
        if identity.vplib_uid is None:
            identity = replace(identity, vplib_uid=request_uid).normalized()
        elif identity.vplib_uid != request_uid:
            raise PackageContextError(
                f"Identity vplib_uid {identity.vplib_uid!r} does not match request "
                f"vplib_uid {request_uid!r}."
            )

        validate_context_identity_against_request(
            identity=identity,
            classification=classification,
            profiles=profiles,
            object_kind=object_kind,
            request_contract=request_contract,
        )
        validate_canonical_identity(identity, classification)
        ensure_location_matches_classification(
            location=location,
            classification=classification,
            identity=identity,
        )
        ensure_location_within_roots(
            roots=roots,
            location=location,
            execution=execution,
        )

        correlation_id = normalize_correlation_id(
            self.correlation_id or build_stable_correlation_id(request_uid)
        )
        metadata = enrich_context_metadata(
            normalize_metadata(self.metadata),
            request=request,
            roots=roots,
            identity=identity,
            classification=classification,
            location=location,
            execution=execution,
            profiles=profiles,
            object_kind=object_kind,
            correlation_id=correlation_id,
        )

        return PackageContext(
            request=request,
            roots=roots,
            identity=identity,
            classification=classification,
            location=location,
            execution=execution,
            object_kind=object_kind,
            profiles=profiles,
            status=status,
            correlation_id=correlation_id,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )

    @property
    def vplib_uid(self) -> str:
        identity = self.identity.normalized()
        if identity.vplib_uid:
            return identity.vplib_uid
        return extract_request_contract(self.request)["vplib_uid"]

    @property
    def family_profile_id(self) -> str:
        if self.profiles is not None:
            return self.profiles.normalized().family_profile_id
        return extract_request_contract(self.request)["family_profile_id"]

    @property
    def variant_profile_id(self) -> str:
        if self.profiles is not None:
            return self.profiles.normalized().variant_profile_id
        return extract_request_contract(self.request)["variant_profile_id"]

    @property
    def profile_key(self) -> str:
        return self.variant_profile_id

    @property
    def package_dir(self) -> Path:
        return self.location.normalized().package_dir

    @property
    def package_relative_dir(self) -> str:
        return self.location.normalized().package_relative_dir

    @property
    def source_path(self) -> str:
        return self.package_relative_dir

    @property
    def source_parts(self) -> tuple[str, str, str, str]:
        classification = self.classification.normalized()
        identity = self.identity.normalized()
        return (
            classification.domain,
            classification.category,
            classification.subcategory,
            identity.family_slug,
        )

    @property
    def archive_path(self) -> Path | None:
        return self.location.normalized().archive_path

    @property
    def is_dry_run(self) -> bool:
        return self.execution.normalized().is_dry_run

    @property
    def may_overwrite(self) -> bool:
        return self.execution.normalized().may_overwrite

    @property
    def request_fingerprint(self) -> str:
        return fingerprint_request(self.request)

    @property
    def context_fingerprint(self) -> str:
        return fingerprint_context(self)

    def with_status(self, status: str, *, force: bool = False) -> "PackageContext":
        """Erzeugt einen neuen Context mit geprüftem Statusübergang."""
        normalized = self.normalized()
        next_status = parse_context_status_value(status)
        if not force:
            validate_status_transition(normalized.status, next_status)

        return replace(
            normalized,
            status=next_status,
            updated_at=utc_now_iso(),
        ).normalized()

    def with_metadata(
        self,
        metadata: Mapping[str, Any],
        *,
        replace_existing: bool = False,
    ) -> "PackageContext":
        """Erzeugt einen Context mit JSON-sicher zusammengeführten Metadaten."""
        normalized = self.normalized()
        incoming = normalize_metadata(metadata)
        merged = {} if replace_existing else dict(normalized.metadata)

        for key, value in incoming.items():
            if key in PROTECTED_METADATA_KEYS:
                continue
            merged[key] = value

        return replace(
            normalized,
            metadata=merged,
            updated_at=utc_now_iso(),
        ).normalized()

    def with_execution(self, execution: PackageExecutionContext | Mapping[str, Any]) -> "PackageContext":
        """Erzeugt einen Context mit neuen, normalisierten Ausführungsoptionen."""
        normalized = self.normalized()
        next_execution = normalize_execution_context(execution)

        archive_path = normalized.location.archive_path
        if not next_execution.create_archive:
            archive_path = None
        elif archive_path is None:
            archive_path = safe_join_root(
                normalized.roots.archive_root,
                build_archive_filename(normalized.identity),
                field_name="archive_path",
            )

        next_location = replace(
            normalized.location,
            archive_path=archive_path,
        ).normalized()

        return replace(
            normalized,
            execution=next_execution,
            location=next_location,
            updated_at=utc_now_iso(),
        ).normalized()

    def with_archive_path(self, archive_path: str | Path | None) -> "PackageContext":
        """Erzeugt einen Context mit geprüftem Archivpfad."""
        normalized = self.normalized()
        next_path = normalize_archive_path(archive_path) if archive_path is not None else None
        if next_path is not None and not is_path_within(next_path, normalized.roots.archive_root):
            raise PackageContextError("archive_path escapes archive_root.")

        next_execution = normalized.execution
        if next_path is not None and not next_execution.create_archive:
            next_execution = replace(next_execution, create_archive=True).normalized()

        return replace(
            normalized,
            location=replace(normalized.location, archive_path=next_path).normalized(),
            execution=next_execution,
            updated_at=utc_now_iso(),
        ).normalized()

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        """Validiert den Context ohne Exceptions nach außen zu geben."""
        try:
            self.normalized()
            return True, ()
        except Exception as exc:
            return False, (str(exc),)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        profiles = normalized.profiles.to_dict() if normalized.profiles else {}
        vplib_uid = normalized.identity.vplib_uid or ""
        family_profile_id = profiles.get("family_profile_id", "")
        variant_profile_id = profiles.get("variant_profile_id", "")
        source_path = normalized.location.package_relative_dir
        source_parts = (
            normalized.classification.domain,
            normalized.classification.category,
            normalized.classification.subcategory,
            normalized.identity.family_slug,
        )
        archive_path = normalized.location.archive_path
        request_fingerprint = fingerprint_request(normalized.request)
        context_fingerprint = fingerprint_context_parts(normalized)
        return {
            "schema_version": PACKAGE_CONTEXT_SCHEMA_VERSION,
            "component": PACKAGE_CONTEXT_COMPONENT,
            "component_version": PACKAGE_CONTEXT_COMPONENT_VERSION,
            "vplib_uid": vplib_uid,
            "correlation_id": normalized.correlation_id,
            "status": normalized.status,
            "created_at": normalized.created_at,
            "updated_at": normalized.updated_at,
            "object_kind": normalized.object_kind,
            "family_profile_id": family_profile_id,
            "variant_profile_id": variant_profile_id,
            "profile_key": variant_profile_id,
            "profiles": profiles,
            "identity": normalized.identity.to_dict(),
            "classification": normalized.classification.to_dict(),
            "roots": normalized.roots.to_dict(),
            "location": normalized.location.to_dict(),
            "execution": normalized.execution.to_dict(),
            "source_path": source_path,
            "source_parts": list(source_parts),
            "package_dir": str(normalized.location.package_dir),
            "archive_path": str(archive_path) if archive_path else None,
            "request_fingerprint": request_fingerprint,
            "context_fingerprint": context_fingerprint,
            "metadata": dict(normalized.metadata),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        profiles = normalized.profiles.normalized() if normalized.profiles else None
        archive_path = normalized.location.archive_path
        return {
            "schema_version": PACKAGE_CONTEXT_SCHEMA_VERSION,
            "vplib_uid": normalized.identity.vplib_uid or "",
            "correlation_id": normalized.correlation_id,
            "status": normalized.status,
            "package_id": normalized.identity.package_id,
            "family_id": normalized.identity.family_id,
            "family_slug": normalized.identity.family_slug,
            "object_kind": normalized.object_kind,
            "family_profile_id": profiles.family_profile_id if profiles else "",
            "variant_profile_id": profiles.variant_profile_id if profiles else "",
            "classification_path": normalized.classification.classification_path,
            "source_path": normalized.location.package_relative_dir,
            "package_dir": str(normalized.location.package_dir),
            "archive_path": str(archive_path) if archive_path else None,
            "write_mode": normalized.execution.write_mode,
            "strict": normalized.execution.strict,
            "request_fingerprint": fingerprint_request(normalized.request),
            "context_fingerprint": fingerprint_context_parts(normalized),
        }


# ---------------------------------------------------------------------------
# Public factories
# ---------------------------------------------------------------------------

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
    """Erzeugt einen sicheren, schreibfreien PackageContext aus einem Request."""
    try:
        normalized_request = normalize_create_request(request)
        contract = extract_request_contract(normalized_request)

        service_root_path = normalize_path(service_root, "service_root")
        library_catalog_root_path = normalize_path(
            library_catalog_root
            if library_catalog_root is not None
            else service_root_path / DEFAULT_PACKAGE_ROOT_NAME,
            "library_catalog_root",
        )
        source_root_path = normalize_path(
            source_root
            if source_root is not None
            else library_catalog_root_path / DEFAULT_SOURCE_ROOT_NAME,
            "source_root",
        )
        generated_root_path = normalize_path(
            generated_root
            if generated_root is not None
            else library_catalog_root_path / DEFAULT_GENERATED_ROOT_NAME,
            "generated_root",
        )
        archive_root_path = normalize_path(
            archive_root
            if archive_root is not None
            else generated_root_path / DEFAULT_ARCHIVE_ROOT_NAME,
            "archive_root",
        )

        roots = PackageRootPaths(
            service_root=service_root_path,
            library_catalog_root=library_catalog_root_path,
            source_root=source_root_path,
            generated_root=generated_root_path,
            archive_root=archive_root_path,
        ).normalized()

        identity = PackageIdentityContext(
            package_id=contract["package_id"],
            family_id=contract["family_id"],
            family_slug=contract["family_slug"],
            family_name=contract["family_name"],
            version=contract["version"],
            vplib_uid=contract["vplib_uid"],
        ).normalized()

        classification = PackageClassificationContext(
            domain=contract["domain"],
            category=contract["category"],
            subcategory=contract["subcategory"],
            classification_path=contract["classification_path"],
        ).normalized()

        profiles = PackageProfileContext(
            object_kind=contract["object_kind"],
            family_profile_id=contract["family_profile_id"],
            variant_profile_id=contract["variant_profile_id"],
        ).normalized()

        relative_dir = build_package_relative_dir(
            classification=classification,
            identity=identity,
        )
        package_dir = safe_join_root(
            roots.source_root,
            relative_dir,
            field_name="package_dir",
        )

        request_options = extract_request_options(normalized_request)
        resolved_write_mode = resolve_write_mode(
            requested_write_mode=write_mode,
            overwrite_existing=normalize_bool(
                request_options.get("overwrite_existing"),
                default=False,
            ),
        )
        execution = PackageExecutionContext(
            write_mode=resolved_write_mode,
            strict=normalize_bool(request_options.get("strict"), default=True),
            validate_after_create=normalize_bool(
                request_options.get("validate_after_create"),
                default=True,
            ),
            create_archive=normalize_bool(
                request_options.get("create_archive"),
                default=False,
            ),
            include_docs=normalize_bool(
                request_options.get("include_docs"),
                default=False,
            ),
            include_tests=normalize_bool(
                request_options.get("include_tests"),
                default=False,
            ),
        ).normalized()

        archive_path = (
            safe_join_root(
                roots.archive_root,
                build_archive_filename(identity),
                field_name="archive_path",
            )
            if execution.create_archive
            else None
        )
        location = PackageLocationContext(
            package_relative_dir=relative_dir,
            package_dir=package_dir,
            archive_path=archive_path,
        ).normalized()

        normalized_metadata = normalize_metadata(metadata)
        correlation_id = normalize_correlation_id(
            normalized_metadata.get("correlation_id")
            or build_stable_correlation_id(contract["vplib_uid"])
        )
        created_at = normalize_timestamp(
            normalized_metadata.get("created_at") or utc_now_iso(),
            "created_at",
        )

        return PackageContext(
            request=normalized_request,
            roots=roots,
            identity=identity,
            classification=classification,
            location=location,
            execution=execution,
            object_kind=contract["object_kind"],
            profiles=profiles,
            status=PackageContextStatus.NORMALIZED.value,
            correlation_id=correlation_id,
            created_at=created_at,
            updated_at=created_at,
            metadata=normalized_metadata,
        ).normalized()
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Could not create package context: {exc}") from exc


def context_from_dict(
    data: Mapping[str, Any],
    *,
    request: Any | None = None,
) -> PackageContext:
    """Baut einen PackageContext aus einem serialisierten Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise PackageContextError("PackageContext data must be a mapping.")

        request_value = request if request is not None else data.get("request")
        if request_value is None:
            raise PackageContextError(
                "request is required because PackageContext serialization does not "
                "embed the complete CreateRequest by default."
            )

        roots_data = require_mapping(data, "roots")
        identity_data = require_mapping(data, "identity")
        classification_data = require_mapping(data, "classification")
        location_data = require_mapping(data, "location")
        execution_data = require_mapping(data, "execution")
        profiles_data = optional_mapping(data, "profiles")

        family_profile_id = first_non_empty(
            profiles_data.get("family_profile_id"),
            data.get("family_profile_id"),
        )
        variant_profile_id = first_non_empty(
            profiles_data.get("variant_profile_id"),
            data.get("variant_profile_id"),
        )
        object_kind = first_non_empty(
            profiles_data.get("object_kind"),
            data.get("object_kind"),
        )

        return PackageContext(
            request=request_value,
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
                vplib_uid=first_non_empty(
                    identity_data.get("vplib_uid"),
                    data.get("vplib_uid"),
                ),
            ),
            classification=PackageClassificationContext(
                domain=classification_data["domain"],
                category=classification_data["category"],
                subcategory=classification_data["subcategory"],
                classification_path=classification_data.get("classification_path")
                or f"{classification_data['domain']}/{classification_data['category']}/"
                f"{classification_data['subcategory']}",
            ),
            location=PackageLocationContext(
                package_relative_dir=first_non_empty(
                    location_data.get("package_relative_dir"),
                    location_data.get("source_path"),
                    data.get("source_path"),
                ),
                package_dir=location_data.get("package_dir") or data.get("package_dir"),
                archive_path=first_non_empty(
                    location_data.get("archive_path"),
                    data.get("archive_path"),
                ),
            ),
            execution=PackageExecutionContext(
                write_mode=execution_data.get(
                    "write_mode",
                    PackageWriteMode.CREATE_ONLY.value,
                ),
                strict=execution_data.get("strict", True),
                validate_after_create=execution_data.get(
                    "validate_after_create",
                    True,
                ),
                create_archive=execution_data.get("create_archive", False),
                include_docs=execution_data.get("include_docs", False),
                include_tests=execution_data.get("include_tests", False),
            ),
            object_kind=object_kind,
            profiles=(
                PackageProfileContext(
                    object_kind=object_kind,
                    family_profile_id=family_profile_id,
                    variant_profile_id=variant_profile_id,
                )
                if family_profile_id and variant_profile_id and object_kind
                else None
            ),
            status=data.get("status", PackageContextStatus.CREATED.value),
            correlation_id=data.get("correlation_id", ""),
            created_at=data.get("created_at", utc_now_iso()),
            updated_at=data.get("updated_at", data.get("created_at", utc_now_iso())),
            metadata=normalize_metadata(data.get("metadata")),
        ).normalized()
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Could not build PackageContext from dict: {exc}") from exc


# ---------------------------------------------------------------------------
# Request normalization and extraction
# ---------------------------------------------------------------------------

def normalize_create_request(request: Any) -> Any:
    """Normalisiert einen CreateRequest oder dessen Mapping-Vertrag."""
    try:
        from .create_request import CreateRequest, create_request_from_mapping

        if isinstance(request, CreateRequest):
            return request.normalized()
        if isinstance(request, Mapping):
            return create_request_from_mapping(request).normalized()
        if hasattr(request, "normalized") and callable(request.normalized):
            normalized = request.normalized()
            if normalized is None:
                raise PackageContextError("request.normalized() returned None.")
            return normalized
        raise PackageContextError("request must be a CreateRequest or mapping.")
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Invalid create request: {exc}") from exc


def extract_request_contract(request: Any) -> dict[str, str]:
    """Extrahiert den kanonischen Minimalvertrag eines normalisierten Requests."""
    normalized = normalize_create_request(request)
    identity = extract_mapping_or_object(normalized, "identity")
    classification = extract_mapping_or_object(normalized, "classification")

    object_kind = normalize_object_kind_value(
        extract_value(normalized, "object_kind", fallback="")
    )
    vplib_uid = normalize_vplib_uid(
        extract_value(normalized, "vplib_uid", fallback=None)
    )
    family_profile_id = normalize_profile_id(
        extract_value(normalized, "family_profile_id", fallback=""),
        "family_profile_id",
    )
    variant_profile_id = normalize_profile_id(
        extract_value(normalized, "variant_profile_id", fallback=""),
        "variant_profile_id",
    )

    family_id = normalize_identifier(
        extract_value(identity, "family_id", fallback=""),
        "family_id",
    )
    package_id = normalize_identifier(
        first_non_empty(
            extract_value(identity, "package_id", fallback=None),
            f"vplib.{family_id}",
        ),
        "package_id",
    )
    family_slug = normalize_slug_like(
        first_non_empty(
            extract_value(identity, "family_slug", fallback=None),
            family_id.split(".")[-1],
        ),
        "family_slug",
    )
    family_name = normalize_required_string(
        extract_value(identity, "family_name", fallback=""),
        "family_name",
    )
    version = normalize_package_version(
        extract_value(identity, "version", fallback="0.1.0")
    )

    domain = normalize_taxonomy_segment(
        extract_value(classification, "domain", fallback=""),
        "domain",
    )
    category = normalize_taxonomy_segment(
        extract_value(classification, "category", fallback=""),
        "category",
    )
    subcategory = normalize_taxonomy_segment(
        extract_value(classification, "subcategory", fallback=""),
        "subcategory",
    )
    classification_path = normalize_classification_path(
        extract_value(
            classification,
            "classification_path",
            fallback=f"{domain}/{category}/{subcategory}",
        ),
        domain=domain,
        category=category,
        subcategory=subcategory,
    )

    return {
        "vplib_uid": vplib_uid,
        "family_profile_id": family_profile_id,
        "variant_profile_id": variant_profile_id,
        "object_kind": object_kind,
        "family_id": family_id,
        "package_id": package_id,
        "family_slug": family_slug,
        "family_name": family_name,
        "version": version,
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "classification_path": classification_path,
    }


def extract_request_options(request: Any) -> dict[str, Any]:
    normalized = normalize_create_request(request)
    options = extract_value(normalized, "options", fallback={})
    return normalize_mapping_like(options)


def validate_context_identity_against_request(
    *,
    identity: PackageIdentityContext,
    classification: PackageClassificationContext,
    profiles: PackageProfileContext,
    object_kind: str,
    request_contract: Mapping[str, str],
) -> None:
    comparisons = {
        "vplib_uid": (identity.vplib_uid, request_contract.get("vplib_uid")),
        "family_id": (identity.family_id, request_contract.get("family_id")),
        "package_id": (identity.package_id, request_contract.get("package_id")),
        "family_slug": (identity.family_slug, request_contract.get("family_slug")),
        "domain": (classification.domain, request_contract.get("domain")),
        "category": (classification.category, request_contract.get("category")),
        "subcategory": (classification.subcategory, request_contract.get("subcategory")),
        "object_kind": (object_kind, request_contract.get("object_kind")),
        "profile.object_kind": (profiles.object_kind, request_contract.get("object_kind")),
        "family_profile_id": (
            profiles.family_profile_id,
            request_contract.get("family_profile_id"),
        ),
        "variant_profile_id": (
            profiles.variant_profile_id,
            request_contract.get("variant_profile_id"),
        ),
    }

    for field_name, (actual, expected) in comparisons.items():
        if expected and actual != expected:
            raise PackageContextError(
                f"Context {field_name} {actual!r} does not match request {expected!r}."
            )


# ---------------------------------------------------------------------------
# Identity, classification and location validation
# ---------------------------------------------------------------------------

def build_canonical_family_id(
    classification: PackageClassificationContext,
    family_slug: str,
) -> str:
    normalized = classification.normalized()
    slug = normalize_slug_like(family_slug, "family_slug")
    return (
        f"vp.{normalized.domain}.{normalized.category}."
        f"{normalized.subcategory}.{slug}"
    )


def build_canonical_package_id(family_id: str) -> str:
    normalized_family_id = normalize_identifier(family_id, "family_id")
    return f"vplib.{normalized_family_id}"


def validate_canonical_identity(
    identity: PackageIdentityContext,
    classification: PackageClassificationContext,
) -> None:
    normalized_identity = identity.normalized()
    expected_family_id = build_canonical_family_id(
        classification,
        normalized_identity.family_slug,
    )
    expected_package_id = build_canonical_package_id(expected_family_id)

    if normalized_identity.family_id != expected_family_id:
        raise PackageContextError(
            f"family_id must be canonical. Expected {expected_family_id!r}, "
            f"got {normalized_identity.family_id!r}."
        )
    if normalized_identity.package_id != expected_package_id:
        raise PackageContextError(
            f"package_id must be canonical. Expected {expected_package_id!r}, "
            f"got {normalized_identity.package_id!r}."
        )


def build_package_relative_dir(
    *,
    classification: PackageClassificationContext,
    identity: PackageIdentityContext,
) -> str:
    """Baut ``domain/category/subcategory/family_slug``."""
    try:
        cls = classification.normalized()
        ident = identity.normalized()
        relative_dir = PurePosixPath(
            cls.domain,
            cls.category,
            cls.subcategory,
            ident.family_slug,
        ).as_posix()
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
    expected = build_package_relative_dir(
        classification=classification,
        identity=identity,
    )
    actual = location.normalized().package_relative_dir
    if actual != expected:
        raise PackageContextError(
            f"Package location mismatch. Expected {expected!r}, got {actual!r}."
        )


def ensure_location_within_roots(
    *,
    roots: PackageRootPaths,
    location: PackageLocationContext,
    execution: PackageExecutionContext,
) -> None:
    normalized_roots = roots.normalized()
    normalized_location = location.normalized()
    normalized_execution = execution.normalized()

    expected_package_dir = safe_join_root(
        normalized_roots.source_root,
        normalized_location.package_relative_dir,
        field_name="package_dir",
    )
    if normalized_location.package_dir != expected_package_dir:
        raise PackageContextError(
            "package_dir does not match source_root + package_relative_dir: "
            f"expected {str(expected_package_dir)!r}, "
            f"got {str(normalized_location.package_dir)!r}."
        )

    if not is_path_within(normalized_location.package_dir, normalized_roots.source_root):
        raise PackageContextError("package_dir escapes source_root.")

    archive_path = normalized_location.archive_path
    if normalized_execution.create_archive and archive_path is None:
        raise PackageContextError("create_archive=True requires archive_path.")
    if not normalized_execution.create_archive and archive_path is not None:
        raise PackageContextError("archive_path requires create_archive=True.")
    if archive_path is not None:
        if not is_path_within(archive_path, normalized_roots.archive_root):
            raise PackageContextError("archive_path escapes archive_root.")
        if archive_path.suffix.lower() != ".vplib":
            raise PackageContextError("archive_path must use .vplib suffix.")


def build_archive_filename(identity: PackageIdentityContext) -> str:
    normalized = identity.normalized()
    return f"{normalized.family_slug}.vplib"


# ---------------------------------------------------------------------------
# Write mode and status
# ---------------------------------------------------------------------------

def resolve_write_mode(
    *,
    requested_write_mode: str | None,
    overwrite_existing: bool,
) -> str:
    if requested_write_mode:
        return parse_write_mode_value(requested_write_mode)
    if normalize_bool(overwrite_existing, default=False):
        return PackageWriteMode.OVERWRITE.value
    return PackageWriteMode.CREATE_ONLY.value


@lru_cache(maxsize=64)
def _parse_write_mode_cached(raw: str) -> str:
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


def parse_write_mode_value(value: Any) -> str:
    try:
        if isinstance(value, PackageWriteMode):
            return value.value
        raw = normalize_token(value)
        return _parse_write_mode_cached(raw)
    except Exception as exc:
        raise PackageContextError(f"Invalid write mode {value!r}.") from exc


@lru_cache(maxsize=64)
def _parse_context_status_cached(raw: str) -> str:
    return PackageContextStatus(raw).value


def parse_context_status_value(value: Any) -> str:
    try:
        if isinstance(value, PackageContextStatus):
            return value.value
        return _parse_context_status_cached(normalize_token(value))
    except Exception as exc:
        raise PackageContextError(f"Invalid package context status {value!r}.") from exc


def validate_status_transition(current: Any, next_status: Any) -> None:
    current_value = parse_context_status_value(current)
    next_value = parse_context_status_value(next_status)
    allowed = _STATUS_TRANSITIONS.get(current_value, frozenset())
    if next_value not in allowed:
        raise PackageContextError(
            f"Invalid package context status transition: {current_value!r} -> "
            f"{next_value!r}."
        )


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1024)
def _normalize_path_cached(text: str) -> Path:
    return Path(text).expanduser().resolve(strict=False)


def normalize_path(value: Any, field_name: str) -> Path:
    try:
        if value is None:
            raise PackageContextError(f"{field_name} is required.")
        text = normalize_required_string(value, field_name, max_length=MAX_PATH_LENGTH)
        if "\x00" in text or any(ord(char) < 32 for char in text):
            raise PackageContextError(f"{field_name} contains control characters.")
        return _normalize_path_cached(text)
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(f"Invalid path for {field_name}: {value!r}.") from exc


def normalize_archive_path(value: Any) -> Path:
    path = normalize_path(value, "archive_path")
    if path.suffix.lower() != ".vplib":
        raise PackageContextError("archive_path must use .vplib suffix.")
    return path


def normalize_relative_package_dir(value: Any) -> str:
    try:
        text = normalize_required_string(
            value,
            "package_relative_dir",
            max_length=MAX_PATH_LENGTH,
        ).replace("\\", "/")
        path = PurePosixPath(text)
        if path.is_absolute():
            raise PackageContextError("package_relative_dir must be relative.")

        parts = tuple(path.parts)
        if len(parts) != 4:
            raise PackageContextError(
                "package_relative_dir must contain exactly four segments: "
                "domain/category/subcategory/family_slug."
            )
        normalized_parts = tuple(
            normalize_path_segment(part, f"package_relative_dir[{index}]")
            for index, part in enumerate(parts)
        )
        normalized = PurePosixPath(*normalized_parts).as_posix()

        helper = try_normalize_package_path(normalized)
        if helper is not None:
            helper_text = str(helper).replace("\\", "/")
            if helper_text != normalized:
                raise PackageContextError(
                    "Domain package path normalization changed the canonical path: "
                    f"{normalized!r} -> {helper_text!r}."
                )
        return normalized
    except PackageContextError:
        raise
    except Exception as exc:
        raise PackageContextError(
            f"Invalid relative package directory {value!r}: {exc}"
        ) from exc


def safe_join_root(root: Any, relative: Any, *, field_name: str) -> Path:
    normalized_root = normalize_path(root, f"{field_name}_root")
    relative_text = normalize_required_string(relative, field_name, max_length=MAX_PATH_LENGTH)
    relative_text = relative_text.replace("\\", "/")
    relative_path = PurePosixPath(relative_text)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise PackageContextError(f"Unsafe relative path for {field_name}: {relative!r}.")

    target = normalized_root.joinpath(*relative_path.parts).resolve(strict=False)
    if not is_path_within(target, normalized_root):
        raise PackageContextError(f"{field_name} escapes its configured root.")
    return target


def is_path_within(path: Any, root: Any) -> bool:
    normalized_path = normalize_path(path, "path")
    normalized_root = normalize_path(root, "root")
    try:
        normalized_path.relative_to(normalized_root)
        return True
    except ValueError:
        return False


def validate_root_paths(roots: PackageRootPaths) -> None:
    values = {
        "service_root": roots.service_root,
        "library_catalog_root": roots.library_catalog_root,
        "source_root": roots.source_root,
        "generated_root": roots.generated_root,
        "archive_root": roots.archive_root,
    }
    for field_name, path in values.items():
        if path.name in {"", ".", ".."}:
            raise PackageContextError(f"{field_name} is not a usable root path.")

    if roots.source_root == roots.archive_root:
        raise PackageContextError("source_root and archive_root must be different paths.")


# ---------------------------------------------------------------------------
# Primitive normalization
# ---------------------------------------------------------------------------

def normalize_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0

    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active"}:
        return True
    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", ""}:
        return False
    return default


def normalize_required_string(
    value: Any,
    field_name: str,
    *,
    max_length: int = MAX_STRING_LENGTH,
) -> str:
    try:
        text = str(value).replace("\x00", "").strip()
    except Exception as exc:
        raise PackageContextError(f"{field_name} must be string-like.") from exc
    if not text:
        raise PackageContextError(f"{field_name} is required.")
    if max_length > 0 and len(text) > max_length:
        raise PackageContextError(
            f"{field_name} exceeds maximum length {max_length}."
        )
    return text


def normalize_optional_string(value: Any, *, max_length: int = MAX_STRING_LENGTH) -> str | None:
    if value is None:
        return None
    try:
        text = str(value).replace("\x00", "").strip()
    except Exception:
        return None
    if not text:
        return None
    if max_length > 0:
        text = text[:max_length]
    return text


def normalize_token(value: Any) -> str:
    return (
        normalize_required_string(value, "token", max_length=160)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def normalize_identifier(value: Any, field_name: str) -> str:
    text = normalize_required_string(value, field_name, max_length=MAX_SEGMENT_LENGTH * 8)
    normalized = text.strip().lower().replace(" ", "_").replace("-", "_")
    if not SAFE_IDENTIFIER_RE.fullmatch(normalized):
        raise PackageContextError(f"{field_name} contains unsafe characters: {value!r}.")
    if any(not part for part in normalized.split(".")):
        raise PackageContextError(f"{field_name} contains empty dot segments.")
    return normalized


def normalize_slug_like(value: Any, field_name: str) -> str:
    try:
        from .create_request import normalize_slug
    except (ImportError, ModuleNotFoundError):
        normalize_slug = None

    if callable(normalize_slug):
        try:
            return str(normalize_slug(value, field_name=field_name))
        except Exception as exc:
            raise PackageContextError(f"Invalid slug for {field_name}: {exc}") from exc

    return normalize_path_segment(value, field_name)


def normalize_path_segment(value: Any, field_name: str) -> str:
    text = normalize_required_string(value, field_name, max_length=MAX_SEGMENT_LENGTH)
    normalized = text.lower().replace(" ", "_").replace("-", "_")
    if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise PackageContextError(f"{field_name} is not a safe path segment.")
    if not SAFE_SEGMENT_RE.fullmatch(normalized):
        raise PackageContextError(f"{field_name} contains unsafe characters: {value!r}.")
    return normalized


def normalize_taxonomy_segment(value: Any, field_name: str) -> str:
    return normalize_path_segment(value, field_name)


def normalize_profile_id(value: Any, field_name: str) -> str:
    text = normalize_required_string(value, field_name, max_length=MAX_SEGMENT_LENGTH)
    normalized = text.lower().replace(" ", "").replace("-", "_")
    if not SAFE_PROFILE_ID_RE.fullmatch(normalized):
        raise PackageContextError(f"{field_name} contains unsafe characters: {value!r}.")
    return normalized


def normalize_vplib_uid(value: Any) -> str:
    try:
        from .create_request import normalize_vplib_uid as request_normalizer
    except (ImportError, ModuleNotFoundError):
        request_normalizer = None

    if callable(request_normalizer):
        try:
            return str(request_normalizer(value, field_name="vplib_uid"))
        except Exception as exc:
            raise PackageContextError(f"Invalid vplib_uid {value!r}: {exc}") from exc

    try:
        return str(uuid.UUID(str(value).strip())).lower()
    except Exception as exc:
        raise PackageContextError(f"Invalid vplib_uid {value!r}.") from exc


def normalize_package_version(value: Any) -> str:
    text = normalize_required_string(value, "version", max_length=64)
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]*", text):
        raise PackageContextError(f"Invalid package version {value!r}.")
    return text


def normalize_object_kind_value(value: Any) -> str:
    raw = normalize_token(value)
    aliases = {
        "block": "cell_block",
        "cell": "cell_block",
        "cellblock": "cell_block",
        "multi_cell": "multi_cell_module",
        "module": "multi_cell_module",
        "catalog": "catalog_object",
        "object": "catalog_object",
        "adaptive": "adaptive_system",
        "system": "adaptive_system",
    }
    raw = aliases.get(raw, raw)

    try:
        from ..domain.object_kinds import ensure_object_kind_value
    except (ImportError, ModuleNotFoundError):
        ensure_object_kind_value = None

    if callable(ensure_object_kind_value):
        try:
            return str(ensure_object_kind_value(raw))
        except Exception as exc:
            raise PackageContextError(f"Invalid object_kind {value!r}: {exc}") from exc

    if not SAFE_SEGMENT_RE.fullmatch(raw):
        raise PackageContextError(f"Invalid object_kind {value!r}.")
    return raw


def normalize_classification_path(
    value: Any,
    *,
    domain: str,
    category: str,
    subcategory: str,
) -> str:
    text = normalize_required_string(value, "classification_path", max_length=512)
    normalized = text.replace("\\", "/").strip("/")
    expected = f"{domain}/{category}/{subcategory}"
    parts = normalized.split("/")
    if len(parts) != 3:
        raise PackageContextError(
            "classification_path must contain domain/category/subcategory."
        )
    normalized_parts = [
        normalize_taxonomy_segment(part, f"classification_path[{index}]")
        for index, part in enumerate(parts)
    ]
    normalized = "/".join(normalized_parts)
    if normalized != expected:
        raise PackageContextError(
            f"classification_path must equal {expected!r}, got {normalized!r}."
        )
    return normalized


def normalize_correlation_id(value: Any) -> str:
    text = normalize_required_string(value, "correlation_id", max_length=192)
    if not SAFE_CORRELATION_ID_RE.fullmatch(text):
        raise PackageContextError(f"Invalid correlation_id {value!r}.")
    return text


def build_stable_correlation_id(vplib_uid: Any) -> str:
    uid = normalize_vplib_uid(vplib_uid)
    return "vplib:" + uuid.uuid5(uuid.NAMESPACE_URL, f"vplib:{uid}").hex


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_timestamp(value: Any) -> datetime:
    text = normalize_required_string(value, "timestamp", max_length=80)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception as exc:
        raise PackageContextError(f"Invalid timestamp {value!r}.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_timestamp(value: Any, field_name: str) -> str:
    try:
        return parse_timestamp(value).replace(microsecond=0).isoformat()
    except Exception as exc:
        if isinstance(exc, PackageContextError):
            raise PackageContextError(f"Invalid {field_name}: {exc}") from exc
        raise PackageContextError(f"Invalid {field_name} {value!r}.") from exc


# ---------------------------------------------------------------------------
# Metadata and fingerprints
# ---------------------------------------------------------------------------

def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PackageContextError("metadata must be a mapping.")
    counter = [0]
    return {
        str(key): normalize_metadata_value(child, depth=0, counter=counter)
        for key, child in sorted(value.items(), key=lambda item: str(item[0]))
    }


def normalize_metadata_value(value: Any, *, depth: int, counter: list[int]) -> Any:
    counter[0] += 1
    if counter[0] > MAX_METADATA_ITEMS:
        raise PackageContextError("metadata exceeds maximum item count.")
    if depth > MAX_METADATA_DEPTH:
        raise PackageContextError("metadata exceeds maximum nesting depth.")

    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
            return value[:MAX_STRING_LENGTH]
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PackageContextError("metadata must not contain NaN or infinity.")
        return value
    if isinstance(value, Enum):
        return normalize_metadata_value(value.value, depth=depth + 1, counter=counter)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).replace(microsecond=0).isoformat()
    if is_dataclass(value):
        return normalize_metadata_value(asdict(value), depth=depth + 1, counter=counter)
    if isinstance(value, Mapping):
        return {
            str(key): normalize_metadata_value(child, depth=depth + 1, counter=counter)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        if isinstance(value, (set, frozenset)):
            items.sort(key=lambda item: repr(item))
        return [
            normalize_metadata_value(item, depth=depth + 1, counter=counter)
            for item in items
        ]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_metadata_value(
                value.to_dict(),
                depth=depth + 1,
                counter=counter,
            )
        except Exception:
            pass
    return normalize_required_string(value, "metadata_value", max_length=MAX_STRING_LENGTH)


def enrich_context_metadata(
    metadata: Mapping[str, Any],
    *,
    request: Any,
    roots: PackageRootPaths,
    identity: PackageIdentityContext,
    classification: PackageClassificationContext,
    location: PackageLocationContext,
    execution: PackageExecutionContext,
    profiles: PackageProfileContext,
    object_kind: str,
    correlation_id: str,
) -> dict[str, Any]:
    result = {
        key: value
        for key, value in normalize_metadata(metadata).items()
        if key not in PROTECTED_METADATA_KEYS
    }
    result.update(
        {
            "schema_version": PACKAGE_CONTEXT_SCHEMA_VERSION,
            "component": PACKAGE_CONTEXT_COMPONENT,
            "component_version": PACKAGE_CONTEXT_COMPONENT_VERSION,
            "vplib_uid": identity.vplib_uid,
            "family_profile_id": profiles.family_profile_id,
            "variant_profile_id": profiles.variant_profile_id,
            "object_kind": object_kind,
            "family_id": identity.family_id,
            "package_id": identity.package_id,
            "family_slug": identity.family_slug,
            "classification_path": classification.classification_path,
            "source_path": location.package_relative_dir,
            "package_relative_dir": location.package_relative_dir,
            "package_dir": str(location.package_dir),
            "archive_path": str(location.archive_path) if location.archive_path else None,
            "request_fingerprint": fingerprint_request(request),
            "correlation_id": correlation_id,
            "roots": roots.to_dict(),
            "write_mode": execution.write_mode,
        }
    )
    result["context_fingerprint"] = fingerprint_payload(
        {
            "vplib_uid": identity.vplib_uid,
            "package_id": identity.package_id,
            "family_id": identity.family_id,
            "family_slug": identity.family_slug,
            "classification_path": classification.classification_path,
            "object_kind": object_kind,
            "family_profile_id": profiles.family_profile_id,
            "variant_profile_id": profiles.variant_profile_id,
            "source_path": location.package_relative_dir,
            "package_dir": str(location.package_dir),
            "archive_path": str(location.archive_path) if location.archive_path else None,
            "write_mode": execution.write_mode,
        }
    )
    return normalize_metadata(result)


def fingerprint_request(request: Any) -> str:
    normalized = normalize_create_request(request)
    payload = object_to_mapping(normalized)
    return fingerprint_payload(payload)


def fingerprint_context(context: PackageContext) -> str:
    return fingerprint_context_parts(context.normalized())


def fingerprint_context_parts(context: PackageContext) -> str:
    profiles = context.profiles.normalized() if context.profiles else None
    archive_path = context.location.archive_path
    return fingerprint_payload(
        {
            "vplib_uid": context.identity.vplib_uid or "",
            "package_id": context.identity.package_id,
            "family_id": context.identity.family_id,
            "family_slug": context.identity.family_slug,
            "classification_path": context.classification.classification_path,
            "object_kind": context.object_kind,
            "family_profile_id": profiles.family_profile_id if profiles else "",
            "variant_profile_id": profiles.variant_profile_id if profiles else "",
            "source_path": context.location.package_relative_dir,
            "package_dir": str(context.location.package_dir),
            "archive_path": str(archive_path) if archive_path else None,
            "execution": context.execution.to_dict(),
        }
    )


def fingerprint_payload(value: Any) -> str:
    safe = normalize_metadata_value(value, depth=0, counter=[0])
    encoded = json.dumps(
        safe,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Optional domain adapters
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _classification_builder() -> Any | None:
    try:
        from ..domain.classification import build_classification_path
        return build_classification_path
    except (ImportError, ModuleNotFoundError):
        return None


def try_build_classification_path(*, domain: str, category: str, subcategory: str) -> Any | None:
    builder = _classification_builder()
    if builder is None:
        return None
    try:
        return builder(domain=domain, category=category, subcategory=subcategory)
    except Exception as exc:
        raise PackageContextError(f"Invalid package classification context: {exc}") from exc


@lru_cache(maxsize=1)
def _package_path_normalizer() -> Any | None:
    try:
        from ..domain.package_paths import normalize_package_path
        return normalize_package_path
    except (ImportError, ModuleNotFoundError):
        return None


def try_normalize_package_path(value: str) -> Any | None:
    helper = _package_path_normalizer()
    if helper is None:
        return None
    try:
        return helper(value)
    except Exception as exc:
        raise PackageContextError(f"Domain package path validation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Generic mapping helpers
# ---------------------------------------------------------------------------

def extract_value(source: Any, key: str, *, fallback: Any = None) -> Any:
    if source is None:
        return fallback
    if isinstance(source, Mapping):
        value = source.get(key, fallback)
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "value") and isinstance(getattr(value, "value", None), (str, int, float, bool)):
            return getattr(value, "value")
        return value
    try:
        value = getattr(source, key)
        if isinstance(value, Enum):
            return value.value
        if hasattr(value, "value") and isinstance(getattr(value, "value", None), (str, int, float, bool)):
            return getattr(value, "value")
        return value
    except Exception:
        return fallback


def extract_mapping_or_object(source: Any, key: str) -> Any:
    value = extract_value(source, key, fallback=None)
    if value is None:
        raise PackageContextError(f"request.{key} is required.")
    return value


def object_to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return normalize_metadata(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return normalize_metadata(result)
    if is_dataclass(value):
        return normalize_metadata(asdict(value))
    try:
        return normalize_metadata(vars(value))
    except Exception as exc:
        raise PackageContextError(
            f"Value {type(value).__name__} cannot be converted to mapping."
        ) from exc


def normalize_mapping_like(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return {str(key): child for key, child in value.items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return {str(key): child for key, child in result.items()}
    if is_dataclass(value):
        return asdict(value)
    try:
        return dict(vars(value))
    except Exception:
        return {}


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise PackageContextError(f"{key} must be an object.")
    return value


def optional_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise PackageContextError(f"{key} must be an object.")
    return value


def normalize_execution_context(
    value: PackageExecutionContext | Mapping[str, Any],
) -> PackageExecutionContext:
    if isinstance(value, PackageExecutionContext):
        return value.normalized()
    if isinstance(value, Mapping):
        return PackageExecutionContext(
            write_mode=value.get("write_mode", PackageWriteMode.CREATE_ONLY.value),
            strict=value.get("strict", True),
            validate_after_create=value.get("validate_after_create", True),
            create_archive=value.get("create_archive", False),
            include_docs=value.get("include_docs", False),
            include_tests=value.get("include_tests", False),
        ).normalized()
    raise PackageContextError("execution must be PackageExecutionContext or mapping.")


# ---------------------------------------------------------------------------
# Diagnostics and caches
# ---------------------------------------------------------------------------

def get_package_context_health() -> dict[str, Any]:
    """Import-sichere Diagnose des Context-Modells."""
    try:
        sample_uid = str(uuid.uuid4()).lower()
        correlation_id = build_stable_correlation_id(sample_uid)
        return {
            "ok": True,
            "healthy": True,
            "status": "healthy",
            "component": PACKAGE_CONTEXT_COMPONENT,
            "component_version": PACKAGE_CONTEXT_COMPONENT_VERSION,
            "schema_version": PACKAGE_CONTEXT_SCHEMA_VERSION,
            "starter": {
                "object_kind": DEFAULT_STARTER_OBJECT_KIND,
                "family_profile_id": DEFAULT_STARTER_FAMILY_PROFILE_ID,
                "variant_profile_id": DEFAULT_STARTER_VARIANT_PROFILE_ID,
            },
            "source_path_segments": 4,
            "stable_correlation_id": bool(correlation_id),
            "cache": {
                "write_mode": _parse_write_mode_cached.cache_info()._asdict(),
                "context_status": _parse_context_status_cached.cache_info()._asdict(),
                "path": _normalize_path_cached.cache_info()._asdict(),
            },
        }
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "status": "unhealthy",
            "component": PACKAGE_CONTEXT_COMPONENT,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def clear_package_context_caches() -> dict[str, Any]:
    """Leert alle Parser-, Import- und Pfad-Caches dieser Datei."""
    cleared: list[str] = []
    errors: list[str] = []

    for cached_function in (
        _parse_write_mode_cached,
        _parse_context_status_cached,
        _normalize_path_cached,
        _classification_builder,
        _package_path_normalizer,
    ):
        try:
            cached_function.cache_clear()
            cleared.append(cached_function.__name__)
        except Exception as exc:
            errors.append(
                f"{getattr(cached_function, '__name__', cached_function)}: "
                f"{type(exc).__name__}: {exc}"
            )

    return {
        "ok": not errors,
        "cleared": cleared,
        "errors": errors,
    }


health = get_package_context_health
get_health = get_package_context_health


__all__ = [
    "DEFAULT_ARCHIVE_ROOT_NAME",
    "DEFAULT_GENERATED_ROOT_NAME",
    "DEFAULT_PACKAGE_ROOT_NAME",
    "DEFAULT_SOURCE_ROOT_NAME",
    "DEFAULT_STARTER_FAMILY_PROFILE_ID",
    "DEFAULT_STARTER_OBJECT_KIND",
    "DEFAULT_STARTER_VARIANT_PROFILE_ID",
    "PACKAGE_CONTEXT_COMPONENT",
    "PACKAGE_CONTEXT_COMPONENT_VERSION",
    "PACKAGE_CONTEXT_SCHEMA_VERSION",
    "PROTECTED_METADATA_KEYS",
    "PackageClassificationContext",
    "PackageContext",
    "PackageContextError",
    "PackageContextStatus",
    "PackageExecutionContext",
    "PackageIdentityContext",
    "PackageLocationContext",
    "PackageProfileContext",
    "PackageRootPaths",
    "PackageWriteMode",
    "build_archive_filename",
    "build_canonical_family_id",
    "build_canonical_package_id",
    "build_package_relative_dir",
    "build_stable_correlation_id",
    "clear_package_context_caches",
    "context_from_dict",
    "create_package_context",
    "ensure_location_matches_classification",
    "ensure_location_within_roots",
    "extract_request_contract",
    "extract_request_options",
    "fingerprint_context",
    "fingerprint_context_parts",
    "fingerprint_payload",
    "fingerprint_request",
    "get_health",
    "get_package_context_health",
    "health",
    "is_path_within",
    "normalize_archive_path",
    "normalize_bool",
    "normalize_classification_path",
    "normalize_correlation_id",
    "normalize_create_request",
    "normalize_execution_context",
    "normalize_identifier",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_object_kind_value",
    "normalize_optional_string",
    "normalize_package_version",
    "normalize_path",
    "normalize_path_segment",
    "normalize_profile_id",
    "normalize_relative_package_dir",
    "normalize_required_string",
    "normalize_slug_like",
    "normalize_taxonomy_segment",
    "normalize_timestamp",
    "normalize_vplib_uid",
    "parse_context_status_value",
    "parse_timestamp",
    "parse_write_mode_value",
    "require_mapping",
    "resolve_write_mode",
    "safe_join_root",
    "utc_now_iso",
    "validate_canonical_identity",
    "validate_context_identity_against_request",
    "validate_root_paths",
    "validate_status_transition",
]
