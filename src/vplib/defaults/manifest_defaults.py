# services/vectoplan-library/src/vplib/defaults/manifest_defaults.py
"""
Manifest defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    vplib.manifest.json

Das Manifest ist die technische Paketklammer eines modularen VPLIB-Packages.
Es beschreibt nicht alle Inhalte, sondern die stabile Identität und den
technischen Kontext des Packages.

Typische Manifest-Inhalte:
- schema_version
- vplib_uid
- vplib_version
- package_id
- family_id
- family_slug
- family_name
- package_version
- object_kind
- classification
- lifecycle/status
- created_at / updated_at
- source metadata
- package metadata

Wichtig für die neue DB-/Creative-Library-Synchronisation:
- vplib_uid ist die unveränderliche technische Paket-ID.
- vplib_uid wird beim Erstellen des .vplib-Packages erzeugt.
- Die Datenbank übernimmt vplib_uid später nur, sie erzeugt sie nicht.
- package_id, family_id, family_slug und family_name dürfen fachlich weiter
  existieren und sich kontrolliert verändern.
- vplib_uid darf nach der ersten Erzeugung nicht still überschrieben werden.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Wichtig:
- utc_now_iso() ist bewusst vor jeder dataclass/default_factory definiert.
- Keine dynamischen setattr-Methoden.
- Alle Payloads bleiben JSON-kompatibel.
- Fehler werden in ManifestDefaultsError gekapselt.
- ID-Erzeugung wird an src/vplib/vplib_id_service.py delegiert.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Mapping


MANIFEST_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.manifest_defaults.v1"
MANIFEST_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.manifest.v1"

DEFAULT_VPLIB_VERSION: Final[str] = "0.1.0"
DEFAULT_PACKAGE_VERSION: Final[str] = "0.1.0"
DEFAULT_GENERATOR_NAME: Final[str] = "vectoplan-library.vplib"
DEFAULT_GENERATOR_VERSION: Final[str] = "0.1.0"

MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"

SAFE_MANIFEST_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)


class ManifestDefaultsError(ValueError):
    """Wird ausgelöst, wenn Manifest-Defaults ungültig erzeugt werden."""


def utc_now_iso() -> str:
    """
    Gibt einen UTC-Zeitstempel im ISO-Format zurück.

    Diese Funktion muss vor ManifestTimestamps definiert sein, weil sie dort
    als dataclass default_factory verwendet wird.
    """
    try:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


class ManifestLifecycleStatus(str, Enum):
    """Lifecycle-Status eines VPLIB-Packages."""

    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"

    @property
    def key(self) -> str:
        return str(self.value)


class ManifestSourceKind(str, Enum):
    """Quelle, aus der das Manifest erzeugt wurde."""

    CREATE_REQUEST = "create_request"
    PACKAGE_CONTEXT = "package_context"
    CREATION_PLAN = "creation_plan"
    SCANNER = "scanner"
    IMPORT = "import"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ManifestClassification:
    """Klassifikationsdaten im Manifest."""

    domain: str
    category: str
    subcategory: str
    classification_path: str | None = None

    def normalized(self) -> "ManifestClassification":
        try:
            from ..domain.classification import build_classification_path

            parsed = build_classification_path(
                domain=self.domain,
                category=self.category,
                subcategory=self.subcategory,
            )

            return ManifestClassification(
                domain=str(parsed.domain.value if hasattr(parsed.domain, "value") else parsed.domain),
                category=str(parsed.category),
                subcategory=str(parsed.subcategory),
                classification_path=str(parsed.path),
            )
        except Exception as exc:
            raise ManifestDefaultsError(f"Invalid manifest classification: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "classification_path": normalized.classification_path,
        }


@dataclass(frozen=True, slots=True)
class ManifestIdentity:
    """
    Identitätsdaten im Manifest.

    vplib_uid:
        Unveränderliche technische Paket-ID.
        Sie wird beim Package-Erzeugen generiert und später von der DB übernommen.

    package_id:
        Technische/semantische Package-ID. Kann lesbar und taxonomisch sein.

    family_id:
        Semantische Family-ID.

    family_slug:
        Dateisystem-/URL-freundlicher Family-Slug.

    family_name:
        Menschlich lesbarer Name.
    """

    package_id: str
    family_id: str
    family_slug: str
    family_name: str
    package_version: str = DEFAULT_PACKAGE_VERSION
    vplib_uid: str | None = None

    def normalized(self) -> "ManifestIdentity":
        return ManifestIdentity(
            package_id=normalize_manifest_id(self.package_id, "package_id"),
            family_id=normalize_manifest_id(self.family_id, "family_id"),
            family_slug=normalize_slug(self.family_slug, "family_slug"),
            family_name=clean_required_string(self.family_name, "family_name"),
            package_version=clean_required_string(
                self.package_version or DEFAULT_PACKAGE_VERSION,
                "package_version",
            ),
            vplib_uid=normalize_or_generate_manifest_vplib_uid(self.vplib_uid),
        )

    def with_vplib_uid(self, vplib_uid: Any, *, overwrite: bool = False) -> "ManifestIdentity":
        """
        Gibt ManifestIdentity mit konkreter vplib_uid zurück.

        Wenn bereits eine andere gültige vplib_uid vorhanden ist, wird sie nur
        ersetzt, wenn overwrite=True gesetzt ist.
        """
        normalized = self.normalized()
        next_uid = normalize_required_manifest_vplib_uid(vplib_uid)

        if normalized.vplib_uid and normalized.vplib_uid != next_uid and not overwrite:
            raise ManifestDefaultsError(
                f"Refusing to overwrite existing {MANIFEST_VPLIB_UID_FIELD!r} "
                f"{normalized.vplib_uid!r} with {next_uid!r}."
            )

        return ManifestIdentity(
            package_id=normalized.package_id,
            family_id=normalized.family_id,
            family_slug=normalized.family_slug,
            family_name=normalized.family_name,
            package_version=normalized.package_version,
            vplib_uid=next_uid,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "vplib_uid": normalized.vplib_uid,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "family_slug": normalized.family_slug,
            "family_name": normalized.family_name,
            "package_version": normalized.package_version,
        }


@dataclass(frozen=True, slots=True)
class ManifestSource:
    """Source-Metadaten im Manifest."""

    source_kind: str = ManifestSourceKind.SYSTEM.value
    generator: str = DEFAULT_GENERATOR_NAME
    generator_version: str = DEFAULT_GENERATOR_VERSION
    profile_key: str | None = None
    correlation_id: str | None = None
    source_path: str | None = None

    def normalized(self) -> "ManifestSource":
        return ManifestSource(
            source_kind=parse_source_kind_value(self.source_kind),
            generator=clean_required_string(self.generator or DEFAULT_GENERATOR_NAME, "generator"),
            generator_version=clean_required_string(
                self.generator_version or DEFAULT_GENERATOR_VERSION,
                "generator_version",
            ),
            profile_key=clean_optional_string(self.profile_key),
            correlation_id=clean_optional_string(self.correlation_id),
            source_path=clean_optional_string(self.source_path),
        )

    def with_source_kind(self, source_kind: str) -> "ManifestSource":
        """Gibt Source mit anderem source_kind zurück."""
        normalized = self.normalized()

        return ManifestSource(
            source_kind=source_kind,
            generator=normalized.generator,
            generator_version=normalized.generator_version,
            profile_key=normalized.profile_key,
            correlation_id=normalized.correlation_id,
            source_path=normalized.source_path,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "source_kind": normalized.source_kind,
            "generator": normalized.generator,
            "generator_version": normalized.generator_version,
            "profile_key": normalized.profile_key,
            "correlation_id": normalized.correlation_id,
            "source_path": normalized.source_path,
        }


@dataclass(frozen=True, slots=True)
class ManifestTimestamps:
    """Zeitstempel im Manifest."""

    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def normalized(self) -> "ManifestTimestamps":
        return ManifestTimestamps(
            created_at=clean_required_string(self.created_at, "created_at"),
            updated_at=clean_required_string(self.updated_at, "updated_at"),
        )

    def touch(self) -> "ManifestTimestamps":
        """Gibt Timestamps mit aktualisiertem updated_at zurück."""
        normalized = self.normalized()

        return ManifestTimestamps(
            created_at=normalized.created_at,
            updated_at=utc_now_iso(),
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "created_at": normalized.created_at,
            "updated_at": normalized.updated_at,
        }


@dataclass(frozen=True, slots=True)
class ManifestDefaults:
    """
    Vollständige Manifest-Defaults.

    Diese Struktur ist die interne Quelle für vplib.manifest.json.
    """

    identity: ManifestIdentity
    classification: ManifestClassification
    object_kind: str
    source: ManifestSource = field(default_factory=ManifestSource)
    timestamps: ManifestTimestamps = field(default_factory=ManifestTimestamps)
    lifecycle_status: str = ManifestLifecycleStatus.DRAFT.value
    schema_version: str = MANIFEST_DOCUMENT_SCHEMA_VERSION
    vplib_version: str = DEFAULT_VPLIB_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ManifestDefaults":
        identity = self.identity.normalized()
        classification = self.classification.normalized()
        object_kind = normalize_object_kind_value(self.object_kind)
        source = self.source.normalized()
        timestamps = self.timestamps.normalized()
        lifecycle_status = parse_lifecycle_status_value(self.lifecycle_status)
        schema_version = clean_required_string(
            self.schema_version or MANIFEST_DOCUMENT_SCHEMA_VERSION,
            "schema_version",
        )
        vplib_version = clean_required_string(
            self.vplib_version or DEFAULT_VPLIB_VERSION,
            "vplib_version",
        )
        metadata = normalize_metadata(self.metadata)

        return ManifestDefaults(
            identity=identity,
            classification=classification,
            object_kind=object_kind,
            source=source,
            timestamps=timestamps,
            lifecycle_status=lifecycle_status,
            schema_version=schema_version,
            vplib_version=vplib_version,
            metadata=metadata,
        )

    def with_vplib_uid(self, vplib_uid: Any, *, overwrite: bool = False) -> "ManifestDefaults":
        """
        Gibt ManifestDefaults mit konkreter vplib_uid zurück.

        Diese Funktion ist für Backfill-/Migrations- und Create-Flows gedacht,
        wenn eine bereits erzeugte ID explizit gesetzt werden muss.
        """
        normalized = self.normalized()

        return ManifestDefaults(
            identity=normalized.identity.with_vplib_uid(vplib_uid, overwrite=overwrite),
            classification=normalized.classification,
            object_kind=normalized.object_kind,
            source=normalized.source,
            timestamps=normalized.timestamps.touch(),
            lifecycle_status=normalized.lifecycle_status,
            schema_version=normalized.schema_version,
            vplib_version=normalized.vplib_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_source_kind(self, source_kind: str) -> "ManifestDefaults":
        """Gibt ManifestDefaults mit anderem source_kind zurück."""
        normalized = self.normalized()

        return ManifestDefaults(
            identity=normalized.identity,
            classification=normalized.classification,
            object_kind=normalized.object_kind,
            source=normalized.source.with_source_kind(source_kind),
            timestamps=normalized.timestamps,
            lifecycle_status=normalized.lifecycle_status,
            schema_version=normalized.schema_version,
            vplib_version=normalized.vplib_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_lifecycle_status(self, lifecycle_status: str) -> "ManifestDefaults":
        """Gibt ManifestDefaults mit anderem lifecycle_status zurück."""
        normalized = self.normalized()

        return ManifestDefaults(
            identity=normalized.identity,
            classification=normalized.classification,
            object_kind=normalized.object_kind,
            source=normalized.source,
            timestamps=normalized.timestamps.touch(),
            lifecycle_status=lifecycle_status,
            schema_version=normalized.schema_version,
            vplib_version=normalized.vplib_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_metadata(self, metadata: Mapping[str, Any] | None, *, merge: bool = True) -> "ManifestDefaults":
        """Gibt ManifestDefaults mit aktualisierter Metadata zurück."""
        normalized = self.normalized()
        next_metadata = dict(normalized.metadata) if merge else {}
        next_metadata.update(normalize_metadata(metadata or {}))

        return ManifestDefaults(
            identity=normalized.identity,
            classification=normalized.classification,
            object_kind=normalized.object_kind,
            source=normalized.source,
            timestamps=normalized.timestamps.touch(),
            lifecycle_status=normalized.lifecycle_status,
            schema_version=normalized.schema_version,
            vplib_version=normalized.vplib_version,
            metadata=next_metadata,
        ).normalized()

    def to_document(self) -> dict[str, Any]:
        """Erzeugt den JSON-kompatiblen Inhalt für vplib.manifest.json."""
        normalized = self.normalized()
        identity = normalized.identity.to_dict()
        timestamps = normalized.timestamps.to_dict()

        return {
            "schema_version": normalized.schema_version,
            "vplib_uid": identity["vplib_uid"],
            "vplib_version": normalized.vplib_version,
            "package_id": identity["package_id"],
            "family_id": identity["family_id"],
            "family_slug": identity["family_slug"],
            "family_name": identity["family_name"],
            "package_version": identity["package_version"],
            "object_kind": normalized.object_kind,
            "classification": normalized.classification.to_dict(),
            "lifecycle_status": normalized.lifecycle_status,
            "created_at": timestamps["created_at"],
            "updated_at": timestamps["updated_at"],
            "source": normalized.source.to_dict(),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        """Alias für to_document()."""
        return self.to_document()


def build_manifest_defaults(
    *,
    package_id: str,
    family_id: str,
    family_slug: str,
    family_name: str,
    object_kind: str,
    domain: str,
    category: str,
    subcategory: str,
    package_version: str = DEFAULT_PACKAGE_VERSION,
    vplib_uid: str | None = None,
    lifecycle_status: str = ManifestLifecycleStatus.DRAFT.value,
    source_kind: str = ManifestSourceKind.SYSTEM.value,
    generator: str = DEFAULT_GENERATOR_NAME,
    generator_version: str = DEFAULT_GENERATOR_VERSION,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    source_path: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ManifestDefaults:
    """Baut ManifestDefaults aus expliziten Werten."""
    try:
        return ManifestDefaults(
            identity=ManifestIdentity(
                package_id=package_id,
                family_id=family_id,
                family_slug=family_slug,
                family_name=family_name,
                package_version=package_version,
                vplib_uid=vplib_uid,
            ),
            classification=ManifestClassification(
                domain=domain,
                category=category,
                subcategory=subcategory,
            ),
            object_kind=object_kind,
            source=ManifestSource(
                source_kind=source_kind,
                generator=generator,
                generator_version=generator_version,
                profile_key=profile_key,
                correlation_id=correlation_id,
                source_path=source_path,
            ),
            lifecycle_status=lifecycle_status,
            metadata=dict(metadata or {}),
        ).normalized()
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not build manifest defaults: {exc}") from exc


def build_manifest_document(**kwargs: Any) -> dict[str, Any]:
    """Baut direkt den JSON-kompatiblen Manifest-Payload."""
    return build_manifest_defaults(**kwargs).to_document()


def manifest_defaults_from_create_request(
    request: Any,
    *,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ManifestDefaults:
    """Baut ManifestDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)

        identity = normalized_request.identity.normalized()
        classification = normalized_request.classification.normalized()

        family_id = clean_required_string(getattr(identity, "family_id", None), "family_id")
        family_slug = clean_optional_string(getattr(identity, "family_slug", None)) or family_id.split(".")[-1]
        package_id = clean_optional_string(getattr(identity, "package_id", None)) or family_id
        package_version = clean_optional_string(getattr(identity, "version", None)) or DEFAULT_PACKAGE_VERSION
        raw_vplib_uid = extract_raw_vplib_uid_from_any(normalized_request) or extract_raw_vplib_uid_from_any(request)

        return build_manifest_defaults(
            package_id=package_id,
            family_id=family_id,
            family_slug=family_slug,
            family_name=getattr(identity, "family_name", None),
            package_version=package_version,
            vplib_uid=raw_vplib_uid,
            object_kind=getattr(normalized_request, "object_kind", None),
            domain=getattr(classification, "domain", None),
            category=getattr(classification, "category", None),
            subcategory=getattr(classification, "subcategory", None),
            source_kind=ManifestSourceKind.CREATE_REQUEST.value,
            profile_key=profile_key,
            correlation_id=correlation_id,
            metadata=metadata,
        )
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not build manifest defaults from CreateRequest: {exc}") from exc


def manifest_defaults_from_context(
    context: Any,
    *,
    profile_key: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ManifestDefaults:
    """Baut ManifestDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        identity = getattr(normalized_context, "identity", None)
        classification = getattr(normalized_context, "classification", None)
        location = getattr(normalized_context, "location", None)

        if identity is None:
            raise ManifestDefaultsError("PackageContext identity is required.")

        if classification is None:
            raise ManifestDefaultsError("PackageContext classification is required.")

        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(normalized_context)
            or extract_raw_vplib_uid_from_any(identity)
            or extract_raw_vplib_uid_from_any(context)
        )

        return build_manifest_defaults(
            package_id=getattr(identity, "package_id", None),
            family_id=getattr(identity, "family_id", None),
            family_slug=getattr(identity, "family_slug", None),
            family_name=getattr(identity, "family_name", None),
            package_version=getattr(identity, "version", DEFAULT_PACKAGE_VERSION),
            vplib_uid=raw_vplib_uid,
            object_kind=getattr(normalized_context, "object_kind", None),
            domain=getattr(classification, "domain", None),
            category=getattr(classification, "category", None),
            subcategory=getattr(classification, "subcategory", None),
            source_kind=ManifestSourceKind.PACKAGE_CONTEXT.value,
            profile_key=profile_key,
            correlation_id=getattr(normalized_context, "correlation_id", None),
            source_path=getattr(location, "package_relative_dir", None) if location is not None else None,
            metadata=metadata,
        )
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not build manifest defaults from PackageContext: {exc}") from exc


def manifest_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> ManifestDefaults:
    """Baut ManifestDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan
        context = getattr(normalized_plan, "context", None)
        profile = getattr(normalized_plan, "profile", None)

        if context is None:
            raise ManifestDefaultsError("CreationPlan context is required.")

        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(normalized_plan)
            or extract_raw_vplib_uid_from_any(context)
            or extract_raw_vplib_uid_from_any(creation_plan)
        )

        defaults = manifest_defaults_from_context(
            context,
            profile_key=getattr(profile, "profile_key", None),
            metadata={
                "creation_plan_status": getattr(normalized_plan, "status", None),
                **dict(metadata or {}),
            },
        ).with_source_kind(ManifestSourceKind.CREATION_PLAN.value)

        if raw_vplib_uid:
            defaults = defaults.with_vplib_uid(raw_vplib_uid, overwrite=True)

        return defaults.normalized()
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not build manifest defaults from CreationPlan: {exc}") from exc


def manifest_document_from_context(
    context: Any,
    *,
    profile_key: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut Manifest-Dokument aus PackageContext."""
    return manifest_defaults_from_context(
        context,
        profile_key=profile_key,
        metadata=metadata,
    ).to_document()


def manifest_document_from_create_request(
    request: Any,
    *,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut Manifest-Dokument aus CreateRequest."""
    return manifest_defaults_from_create_request(
        request,
        profile_key=profile_key,
        correlation_id=correlation_id,
        metadata=metadata,
    ).to_document()


def manifest_document_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut Manifest-Dokument aus CreationPlan."""
    return manifest_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_document()


def validate_manifest_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob die Manifest-Payload-Struktur."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("Manifest document must be a mapping.",)

        required_fields = (
            "schema_version",
            "vplib_uid",
            "vplib_version",
            "package_id",
            "family_id",
            "family_slug",
            "family_name",
            "package_version",
            "object_kind",
            "classification",
            "lifecycle_status",
            "created_at",
            "updated_at",
            "source",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing manifest field {field_name!r}.")

        if MANIFEST_VPLIB_UID_FIELD in document:
            try:
                normalize_required_manifest_vplib_uid(document.get(MANIFEST_VPLIB_UID_FIELD))
            except Exception as exc:
                messages.append(str(exc))

        for field_name in ("package_id", "family_id"):
            if field_name in document:
                try:
                    normalize_manifest_id(document[field_name], field_name)
                except Exception as exc:
                    messages.append(str(exc))

        if "family_slug" in document:
            try:
                normalize_slug(document["family_slug"], "family_slug")
            except Exception as exc:
                messages.append(str(exc))

        if "object_kind" in document:
            try:
                normalize_object_kind_value(document["object_kind"])
            except Exception as exc:
                messages.append(str(exc))

        if "lifecycle_status" in document:
            try:
                parse_lifecycle_status_value(document["lifecycle_status"])
            except Exception as exc:
                messages.append(str(exc))

        classification = document.get("classification")
        if isinstance(classification, Mapping):
            try:
                ManifestClassification(
                    domain=classification.get("domain"),
                    category=classification.get("category"),
                    subcategory=classification.get("subcategory"),
                    classification_path=classification.get("classification_path"),
                ).normalized()
            except Exception as exc:
                messages.append(str(exc))
        else:
            messages.append("Manifest classification must be an object.")

        source = document.get("source")
        if isinstance(source, Mapping):
            try:
                ManifestSource(
                    source_kind=source.get("source_kind", ManifestSourceKind.SYSTEM.value),
                    generator=source.get("generator", DEFAULT_GENERATOR_NAME),
                    generator_version=source.get("generator_version", DEFAULT_GENERATOR_VERSION),
                    profile_key=source.get("profile_key"),
                    correlation_id=source.get("correlation_id"),
                    source_path=source.get("source_path"),
                ).normalized()
            except Exception as exc:
                messages.append(str(exc))
        elif "source" in document:
            messages.append("Manifest source must be an object.")

    except Exception as exc:
        messages.append(f"Could not validate manifest document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_manifest_document(document: Mapping[str, Any]) -> None:
    """Wirft ManifestDefaultsError, wenn ein Manifest-Dokument ungültig ist."""
    valid, messages = validate_manifest_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid manifest document."
        raise ManifestDefaultsError(joined)


def ensure_manifest_document_vplib_uid(
    document: dict[str, Any],
    *,
    overwrite_invalid: bool = False,
    existing_uids: Any | None = None,
) -> str:
    """
    Stellt sicher, dass ein Manifest-Dokument eine gültige vplib_uid enthält.

    Diese Funktion mutiert das übergebene Dict bewusst.
    Sie ist für Create-/Backfill-Flows gedacht.

    Verhalten:
    - vorhandene gültige ID wird normalisiert und behalten
    - fehlende ID wird erzeugt
    - ungültige ID erzeugt Fehler, außer overwrite_invalid=True
    """
    if not isinstance(document, dict):
        raise ManifestDefaultsError("Manifest document must be a mutable dict.")

    try:
        from ..vplib_id_service import ensure_mapping_vplib_uid

        return ensure_mapping_vplib_uid(
            document,
            overwrite_invalid=overwrite_invalid,
            existing_uids=existing_uids,
        )
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not ensure manifest vplib_uid: {exc}") from exc


def manifest_document_with_vplib_uid(
    document: Mapping[str, Any],
    *,
    vplib_uid: Any | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    Gibt eine Kopie eines Manifest-Dokuments mit gültiger vplib_uid zurück.

    Wenn vplib_uid=None ist, wird vorhandene vplib_uid übernommen oder neu erzeugt.
    """
    if not isinstance(document, Mapping):
        raise ManifestDefaultsError("Manifest document must be a mapping.")

    result = dict(document)

    try:
        if vplib_uid is not None:
            from ..vplib_id_service import set_mapping_vplib_uid

            set_mapping_vplib_uid(result, vplib_uid, overwrite=overwrite)
        else:
            ensure_manifest_document_vplib_uid(result)
        return result
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not build manifest document with vplib_uid: {exc}") from exc


def normalize_create_request(value: Any) -> Any:
    """Normalisiert CreateRequest-ähnliche Werte."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise ManifestDefaultsError("CreateRequest value is required.")
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise ManifestDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_manifest_id(value: Any, field_name: str) -> str:
    """Normalisiert package_id/family_id."""
    raw = clean_required_string(value, field_name).lower().replace(" ", "_")

    if not all(part for part in raw.split(".")):
        raise ManifestDefaultsError(f"{field_name} must not contain empty dot segments.")

    for part in raw.split("."):
        if not SAFE_MANIFEST_ID_RE.match(part):
            raise ManifestDefaultsError(f"{field_name} contains unsafe segment {part!r}.")

    return raw


def normalize_slug(value: Any, field_name: str) -> str:
    """Normalisiert einfache Slugs."""
    raw = clean_required_string(value, field_name).lower().replace(" ", "_").replace("-", "_")

    if not SAFE_MANIFEST_ID_RE.match(raw):
        raise ManifestDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return raw


def normalize_manifest_vplib_uid(value: Any) -> str | None:
    """
    Normalisiert eine optionale Manifest-vplib_uid.

    Gibt None zurück, wenn keine ID vorhanden ist.
    Wirft keinen Fehler bei None/leer, aber None bei ungültigen Werten.
    """
    try:
        from ..vplib_id_service import normalize_vplib_uid

        return normalize_vplib_uid(value)
    except Exception:
        return None


def normalize_required_manifest_vplib_uid(value: Any) -> str:
    """
    Validiert eine verpflichtende Manifest-vplib_uid.

    Raises:
        ManifestDefaultsError bei fehlender oder ungültiger ID.
    """
    try:
        from ..vplib_id_service import validate_vplib_uid

        return validate_vplib_uid(value, field_name=MANIFEST_VPLIB_UID_FIELD)
    except Exception as exc:
        raise ManifestDefaultsError(
            f"Invalid {MANIFEST_VPLIB_UID_FIELD!r}. Expected UUID-like VPLIB UID."
        ) from exc


def normalize_or_generate_manifest_vplib_uid(value: Any | None) -> str:
    """
    Normalisiert vorhandene vplib_uid oder erzeugt eine neue.

    Verhalten:
    - gültiger Wert: normalisiert zurückgeben
    - None / leer: neue ID erzeugen
    - ungültiger Wert: Fehler

    Das schützt davor, dass eine kaputte vorhandene ID still ersetzt wird.
    """
    try:
        normalized = normalize_manifest_vplib_uid(value)
        if normalized:
            return normalized

        if value is not None and str(value).strip():
            raise ManifestDefaultsError(
                f"Existing {MANIFEST_VPLIB_UID_FIELD!r} is invalid and must not be replaced silently."
            )

        from ..vplib_id_service import generate_vplib_uid

        return generate_vplib_uid()
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Could not normalize or generate manifest vplib_uid: {exc}") from exc


def extract_raw_vplib_uid_from_any(value: Any) -> Any | None:
    """
    Extrahiert rohe vplib_uid aus Mapping- oder Objektstrukturen.

    Diese Funktion validiert nicht. Sie liefert bewusst den Rohwert,
    damit ungültige vorhandene IDs später sichtbar fehlschlagen statt
    still ersetzt zu werden.

    Unterstützte Orte:
    - obj.vplib_uid
    - obj.vplibUid
    - mapping["vplib_uid"]
    - mapping["vplibUid"]
    - mapping["vplib_uid_v1"]
    - mapping["manifest"][...]
    - mapping["identity"][...]
    - obj.identity....
    - obj.manifest....
    """
    if value is None:
        return None

    try:
        if isinstance(value, Mapping):
            for key in ("vplib_uid", "vplibUid", "vplib_uid_v1"):
                if key in value:
                    return value.get(key)

            for nested_key in ("manifest", "vplib_manifest", "identity", "payload", "data"):
                nested = value.get(nested_key)
                nested_uid = extract_raw_vplib_uid_from_any(nested)
                if nested_uid is not None:
                    return nested_uid

            return None

        for attr_name in ("vplib_uid", "vplibUid", "vplib_uid_v1"):
            try:
                if hasattr(value, attr_name):
                    attr_value = getattr(value, attr_name)
                    if attr_value is not None:
                        return attr_value
            except Exception:
                continue

        for nested_attr in ("manifest", "vplib_manifest", "identity", "payload", "data"):
            try:
                nested = getattr(value, nested_attr, None)
                nested_uid = extract_raw_vplib_uid_from_any(nested)
                if nested_uid is not None:
                    return nested_uid
            except Exception:
                continue

        return None
    except Exception:
        return None


@lru_cache(maxsize=128)
def parse_lifecycle_status_value(value: Any) -> str:
    """Parst ManifestLifecycleStatus."""
    try:
        if isinstance(value, ManifestLifecycleStatus):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "draft": ManifestLifecycleStatus.DRAFT.value,
            "ready": ManifestLifecycleStatus.READY.value,
            "published": ManifestLifecycleStatus.PUBLISHED.value,
            "publish": ManifestLifecycleStatus.PUBLISHED.value,
            "deprecated": ManifestLifecycleStatus.DEPRECATED.value,
            "archived": ManifestLifecycleStatus.ARCHIVED.value,
            "archive": ManifestLifecycleStatus.ARCHIVED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ManifestLifecycleStatus(raw).value
    except Exception as exc:
        raise ManifestDefaultsError(f"Invalid manifest lifecycle status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_source_kind_value(value: Any) -> str:
    """Parst ManifestSourceKind."""
    try:
        if isinstance(value, ManifestSourceKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "request": ManifestSourceKind.CREATE_REQUEST.value,
            "create_request": ManifestSourceKind.CREATE_REQUEST.value,
            "context": ManifestSourceKind.PACKAGE_CONTEXT.value,
            "package_context": ManifestSourceKind.PACKAGE_CONTEXT.value,
            "creation_plan": ManifestSourceKind.CREATION_PLAN.value,
            "plan": ManifestSourceKind.CREATION_PLAN.value,
            "scanner": ManifestSourceKind.SCANNER.value,
            "scan": ManifestSourceKind.SCANNER.value,
            "import": ManifestSourceKind.IMPORT.value,
            "system": ManifestSourceKind.SYSTEM.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ManifestSourceKind(raw).value
    except Exception as exc:
        raise ManifestDefaultsError(f"Invalid manifest source kind {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ManifestDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ManifestDefaultsError("metadata must be a mapping.")

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
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ManifestDefaultsError(f"{field_name} is required.")

        return cleaned
    except ManifestDefaultsError:
        raise
    except Exception as exc:
        raise ManifestDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_manifest_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_lifecycle_status_value.cache_clear()
    parse_source_kind_value.cache_clear()


__all__ = [
    "DEFAULT_GENERATOR_NAME",
    "DEFAULT_GENERATOR_VERSION",
    "DEFAULT_PACKAGE_VERSION",
    "DEFAULT_VPLIB_VERSION",
    "MANIFEST_DEFAULTS_SCHEMA_VERSION",
    "MANIFEST_DOCUMENT_SCHEMA_VERSION",
    "MANIFEST_VPLIB_UID_FIELD",
    "SAFE_MANIFEST_ID_RE",
    "ManifestClassification",
    "ManifestDefaults",
    "ManifestDefaultsError",
    "ManifestIdentity",
    "ManifestLifecycleStatus",
    "ManifestSource",
    "ManifestSourceKind",
    "ManifestTimestamps",
    "assert_valid_manifest_document",
    "build_manifest_defaults",
    "build_manifest_document",
    "clear_manifest_defaults_caches",
    "clean_optional_string",
    "clean_required_string",
    "ensure_manifest_document_vplib_uid",
    "extract_raw_vplib_uid_from_any",
    "manifest_defaults_from_context",
    "manifest_defaults_from_create_request",
    "manifest_defaults_from_creation_plan",
    "manifest_document_from_context",
    "manifest_document_from_create_request",
    "manifest_document_from_creation_plan",
    "manifest_document_with_vplib_uid",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_manifest_id",
    "normalize_manifest_vplib_uid",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_object_kind_value",
    "normalize_or_generate_manifest_vplib_uid",
    "normalize_required_manifest_vplib_uid",
    "normalize_slug",
    "parse_lifecycle_status_value",
    "parse_source_kind_value",
    "utc_now_iso",
    "validate_manifest_document",
]