# services/vectoplan-library/src/vplib/defaults/family_defaults.py
"""
Family defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    family/identity.json
    family/classification.json
    optional: family/lifecycle.json
    optional: family/aliases.json
    optional: family/metadata.json

Die Family beschreibt das semantische Objekt selbst. Varianten beschreiben nur
Ausprägungen derselben Family.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Wichtig:
- utc_now_iso() ist bewusst vor jeder dataclass/default_factory definiert.
- keine Editor-/Flask-Abhängigkeiten
- keine Dateisystem-Schreiboperation
- robuste Fallbacks für Labels und optionale Felder
- package_id wird optional in family/identity.json mitgeführt

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


FAMILY_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.family_defaults.v1"
FAMILY_IDENTITY_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.family.identity.v1"
FAMILY_CLASSIFICATION_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.family.classification.v1"
FAMILY_LIFECYCLE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.family.lifecycle.v1"
FAMILY_ALIASES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.family.aliases.v1"
FAMILY_METADATA_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.family.metadata.v1"

DEFAULT_FAMILY_VERSION: Final[str] = "0.1.0"
DEFAULT_LANGUAGE: Final[str] = "de"
DEFAULT_STATUS: Final[str] = "draft"
DEFAULT_GENERATOR_NAME: Final[str] = "vectoplan-library.vplib"
DEFAULT_GENERATOR_VERSION: Final[str] = "0.1.0"

SAFE_FAMILY_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_SLUG_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9_-]*[a-z0-9]$|^[a-z0-9]$"
)


class FamilyDefaultsError(ValueError):
    """Wird ausgelöst, wenn Family-Defaults ungültig erzeugt werden."""


def utc_now_iso() -> str:
    """
    Gibt einen UTC-Zeitstempel im ISO-Format zurück.

    Diese Funktion muss vor allen Dataclasses definiert sein, die sie als
    default_factory verwenden.
    """
    try:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


class FamilyLifecycleStatus(str, Enum):
    """Lifecycle-Status einer Family."""

    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"

    @property
    def key(self) -> str:
        return str(self.value)


class FamilySourceKind(str, Enum):
    """Quelle der Family-Definition."""

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
class FamilyIdentityDefaults:
    """Defaults für family/identity.json."""

    family_id: str
    family_slug: str
    family_name: str
    package_id: str | None = None
    display_name: str | None = None
    short_name: str | None = None
    description: str = ""
    version: str = DEFAULT_FAMILY_VERSION
    author: str | None = None
    language: str = DEFAULT_LANGUAGE
    tags: tuple[str, ...] = field(default_factory=tuple)
    aliases: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FamilyIdentityDefaults":
        family_id = normalize_family_id(self.family_id, "family_id")
        package_id = normalize_optional_family_id(self.package_id, "package_id")
        family_slug = normalize_slug(self.family_slug, "family_slug")
        family_name = clean_required_string(self.family_name, "family_name")
        display_name = clean_optional_string(self.display_name) or family_name
        short_name = clean_optional_string(self.short_name) or display_name
        description = clean_optional_string(self.description) or ""
        version = clean_required_string(self.version or DEFAULT_FAMILY_VERSION, "version")
        author = clean_optional_string(self.author)
        language = clean_required_string(self.language or DEFAULT_LANGUAGE, "language")
        tags = normalize_string_tuple(self.tags)
        aliases = normalize_string_tuple(self.aliases)
        created_at = clean_required_string(self.created_at, "created_at")
        updated_at = clean_required_string(self.updated_at, "updated_at")
        metadata = normalize_metadata(self.metadata)

        return FamilyIdentityDefaults(
            family_id=family_id,
            family_slug=family_slug,
            family_name=family_name,
            package_id=package_id,
            display_name=display_name,
            short_name=short_name,
            description=description,
            version=version,
            author=author,
            language=language,
            tags=tags,
            aliases=aliases,
            created_at=created_at,
            updated_at=updated_at,
            metadata=metadata,
        )

    def with_package_id(self, package_id: str | None) -> "FamilyIdentityDefaults":
        """Gibt Identity mit package_id zurück."""
        normalized = self.normalized()

        return FamilyIdentityDefaults(
            family_id=normalized.family_id,
            family_slug=normalized.family_slug,
            family_name=normalized.family_name,
            package_id=package_id,
            display_name=normalized.display_name,
            short_name=normalized.short_name,
            description=normalized.description,
            version=normalized.version,
            author=normalized.author,
            language=normalized.language,
            tags=normalized.tags,
            aliases=normalized.aliases,
            created_at=normalized.created_at,
            updated_at=utc_now_iso(),
            metadata=dict(normalized.metadata),
        ).normalized()

    def to_document(self) -> dict[str, Any]:
        """Erzeugt family/identity.json."""
        normalized = self.normalized()

        return {
            "schema_version": FAMILY_IDENTITY_DOCUMENT_SCHEMA_VERSION,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "family_slug": normalized.family_slug,
            "family_name": normalized.family_name,
            "display_name": normalized.display_name,
            "short_name": normalized.short_name,
            "description": normalized.description,
            "version": normalized.version,
            "author": normalized.author,
            "language": normalized.language,
            "tags": list(normalized.tags),
            "aliases": list(normalized.aliases),
            "created_at": normalized.created_at,
            "updated_at": normalized.updated_at,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class FamilyClassificationDefaults:
    """Defaults für family/classification.json."""

    domain: str
    category: str
    subcategory: str
    object_kind: str
    classification_path: str | None = None
    domain_label: str | None = None
    category_label: str | None = None
    subcategory_label: str | None = None
    object_kind_label: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FamilyClassificationDefaults":
        try:
            from ..domain.classification import (
                build_classification_path,
                get_category_definition,
                get_domain_definition,
                get_subcategory_definition,
            )

            parsed = build_classification_path(
                domain=self.domain,
                category=self.category,
                subcategory=self.subcategory,
            )

            domain_definition = get_domain_definition(parsed.domain)
            category_definition = get_category_definition(parsed.domain, parsed.category)
            subcategory_definition = get_subcategory_definition(
                parsed.domain,
                parsed.category,
                parsed.subcategory,
            )

            domain_value = value_or_enum_value(parsed.domain)
            category_value = value_or_enum_value(parsed.category)
            subcategory_value = value_or_enum_value(parsed.subcategory)

            object_kind = normalize_object_kind_value(self.object_kind)
            object_kind_label = clean_optional_string(self.object_kind_label) or object_kind

            return FamilyClassificationDefaults(
                domain=domain_value,
                category=category_value,
                subcategory=subcategory_value,
                object_kind=object_kind,
                classification_path=str(parsed.path),
                domain_label=clean_optional_string(self.domain_label) or safe_definition_label(domain_definition, domain_value),
                category_label=clean_optional_string(self.category_label) or safe_definition_label(category_definition, category_value),
                subcategory_label=clean_optional_string(self.subcategory_label) or safe_definition_label(subcategory_definition, subcategory_value),
                object_kind_label=object_kind_label,
                tags=normalize_string_tuple(self.tags),
                metadata=normalize_metadata(self.metadata),
            )
        except FamilyDefaultsError:
            raise
        except Exception as exc:
            raise FamilyDefaultsError(f"Invalid family classification defaults: {exc}") from exc

    def to_document(self) -> dict[str, Any]:
        """Erzeugt family/classification.json."""
        normalized = self.normalized()

        return {
            "schema_version": FAMILY_CLASSIFICATION_DOCUMENT_SCHEMA_VERSION,
            "domain": normalized.domain,
            "domain_label": normalized.domain_label,
            "tab": normalized.domain,
            "tab_label": normalized.domain_label,
            "category": normalized.category,
            "category_label": normalized.category_label,
            "subcategory": normalized.subcategory,
            "subcategory_label": normalized.subcategory_label,
            "classification_path": normalized.classification_path,
            "object_kind": normalized.object_kind,
            "object_kind_label": normalized.object_kind_label,
            "tags": list(normalized.tags),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class FamilyLifecycleDefaults:
    """Defaults für optionales family/lifecycle.json."""

    status: str = DEFAULT_STATUS
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    published_at: str | None = None
    deprecated_at: str | None = None
    archived_at: str | None = None
    change_note: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FamilyLifecycleDefaults":
        status = parse_lifecycle_status_value(self.status)

        return FamilyLifecycleDefaults(
            status=status,
            created_at=clean_required_string(self.created_at, "created_at"),
            updated_at=clean_required_string(self.updated_at, "updated_at"),
            published_at=clean_optional_string(self.published_at),
            deprecated_at=clean_optional_string(self.deprecated_at),
            archived_at=clean_optional_string(self.archived_at),
            change_note=clean_optional_string(self.change_note) or "",
            metadata=normalize_metadata(self.metadata),
        )

    def with_status(self, status: str, *, change_note: str | None = None) -> "FamilyLifecycleDefaults":
        """Gibt Lifecycle mit anderem Status zurück."""
        normalized = self.normalized()
        next_status = parse_lifecycle_status_value(status)
        now = utc_now_iso()

        return FamilyLifecycleDefaults(
            status=next_status,
            created_at=normalized.created_at,
            updated_at=now,
            published_at=now if next_status == FamilyLifecycleStatus.PUBLISHED.value else normalized.published_at,
            deprecated_at=now if next_status == FamilyLifecycleStatus.DEPRECATED.value else normalized.deprecated_at,
            archived_at=now if next_status == FamilyLifecycleStatus.ARCHIVED.value else normalized.archived_at,
            change_note=clean_optional_string(change_note) or normalized.change_note,
            metadata=dict(normalized.metadata),
        ).normalized()

    def to_document(self) -> dict[str, Any]:
        """Erzeugt family/lifecycle.json."""
        normalized = self.normalized()

        return {
            "schema_version": FAMILY_LIFECYCLE_DOCUMENT_SCHEMA_VERSION,
            "status": normalized.status,
            "created_at": normalized.created_at,
            "updated_at": normalized.updated_at,
            "published_at": normalized.published_at,
            "deprecated_at": normalized.deprecated_at,
            "archived_at": normalized.archived_at,
            "change_note": normalized.change_note,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class FamilyAliasesDefaults:
    """Defaults für optionales family/aliases.json."""

    aliases: tuple[str, ...] = field(default_factory=tuple)
    legacy_ids: tuple[str, ...] = field(default_factory=tuple)
    search_terms: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FamilyAliasesDefaults":
        return FamilyAliasesDefaults(
            aliases=normalize_string_tuple(self.aliases),
            legacy_ids=normalize_string_tuple(self.legacy_ids),
            search_terms=normalize_string_tuple(self.search_terms),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt family/aliases.json."""
        normalized = self.normalized()

        return {
            "schema_version": FAMILY_ALIASES_DOCUMENT_SCHEMA_VERSION,
            "aliases": list(normalized.aliases),
            "legacy_ids": list(normalized.legacy_ids),
            "search_terms": list(normalized.search_terms),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class FamilyMetadataDefaults:
    """Defaults für optionales family/metadata.json."""

    source_kind: str = FamilySourceKind.SYSTEM.value
    source_path: str | None = None
    generator: str = DEFAULT_GENERATOR_NAME
    generator_version: str = DEFAULT_GENERATOR_VERSION
    profile_key: str | None = None
    correlation_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "FamilyMetadataDefaults":
        return FamilyMetadataDefaults(
            source_kind=parse_source_kind_value(self.source_kind),
            source_path=clean_optional_string(self.source_path),
            generator=clean_required_string(self.generator or DEFAULT_GENERATOR_NAME, "generator"),
            generator_version=clean_required_string(self.generator_version or DEFAULT_GENERATOR_VERSION, "generator_version"),
            profile_key=clean_optional_string(self.profile_key),
            correlation_id=clean_optional_string(self.correlation_id),
            metadata=normalize_metadata(self.metadata),
        )

    def with_source_kind(self, source_kind: str) -> "FamilyMetadataDefaults":
        """Gibt MetadataDefaults mit anderem source_kind zurück."""
        normalized = self.normalized()

        return FamilyMetadataDefaults(
            source_kind=source_kind,
            source_path=normalized.source_path,
            generator=normalized.generator,
            generator_version=normalized.generator_version,
            profile_key=normalized.profile_key,
            correlation_id=normalized.correlation_id,
            metadata=dict(normalized.metadata),
        ).normalized()

    def to_document(self) -> dict[str, Any]:
        """Erzeugt family/metadata.json."""
        normalized = self.normalized()

        return {
            "schema_version": FAMILY_METADATA_DOCUMENT_SCHEMA_VERSION,
            "source_kind": normalized.source_kind,
            "source_path": normalized.source_path,
            "generator": normalized.generator,
            "generator_version": normalized.generator_version,
            "profile_key": normalized.profile_key,
            "correlation_id": normalized.correlation_id,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class FamilyDefaults:
    """Vollständige Family-Defaults für alle family/*.json-Dokumente."""

    identity: FamilyIdentityDefaults
    classification: FamilyClassificationDefaults
    lifecycle: FamilyLifecycleDefaults = field(default_factory=FamilyLifecycleDefaults)
    aliases: FamilyAliasesDefaults = field(default_factory=FamilyAliasesDefaults)
    metadata_defaults: FamilyMetadataDefaults = field(default_factory=FamilyMetadataDefaults)

    def normalized(self) -> "FamilyDefaults":
        return FamilyDefaults(
            identity=self.identity.normalized(),
            classification=self.classification.normalized(),
            lifecycle=self.lifecycle.normalized(),
            aliases=self.aliases.normalized(),
            metadata_defaults=self.metadata_defaults.normalized(),
        )

    def with_source_kind(self, source_kind: str) -> "FamilyDefaults":
        """Gibt FamilyDefaults mit anderem source_kind zurück."""
        normalized = self.normalized()

        return FamilyDefaults(
            identity=normalized.identity,
            classification=normalized.classification,
            lifecycle=normalized.lifecycle,
            aliases=normalized.aliases,
            metadata_defaults=normalized.metadata_defaults.with_source_kind(source_kind),
        ).normalized()

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Family-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents = {
            "family/identity.json": normalized.identity.to_document(),
            "family/classification.json": normalized.classification.to_document(),
        }

        if include_optional:
            documents["family/lifecycle.json"] = normalized.lifecycle.to_document()
            documents["family/aliases.json"] = normalized.aliases.to_document()
            documents["family/metadata.json"] = normalized.metadata_defaults.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": FAMILY_DEFAULTS_SCHEMA_VERSION,
            "identity": normalized.identity.to_dict(),
            "classification": normalized.classification.to_dict(),
            "lifecycle": normalized.lifecycle.to_dict(),
            "aliases": normalized.aliases.to_dict(),
            "metadata_defaults": normalized.metadata_defaults.to_dict(),
        }


def build_family_defaults(
    *,
    family_id: str,
    family_slug: str,
    family_name: str,
    object_kind: str,
    domain: str,
    category: str,
    subcategory: str,
    package_id: str | None = None,
    display_name: str | None = None,
    short_name: str | None = None,
    description: str = "",
    version: str = DEFAULT_FAMILY_VERSION,
    author: str | None = None,
    language: str = DEFAULT_LANGUAGE,
    tags: Iterable[Any] = (),
    aliases: Iterable[Any] = (),
    legacy_ids: Iterable[Any] = (),
    search_terms: Iterable[Any] = (),
    status: str = DEFAULT_STATUS,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    source_kind: str = FamilySourceKind.SYSTEM.value,
    source_path: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FamilyDefaults:
    """Baut FamilyDefaults aus expliziten Werten."""
    try:
        normalized_tags = normalize_string_tuple(tags)
        normalized_aliases = normalize_string_tuple(aliases)
        normalized_legacy_ids = normalize_string_tuple(legacy_ids)
        normalized_search_terms = normalize_string_tuple((*tuple(search_terms or ()), *normalized_tags))
        metadata_payload = dict(metadata or {})

        generated_aliases = normalize_string_tuple(
            (
                *normalized_aliases,
                display_name,
                short_name,
                family_name,
            )
        )

        return FamilyDefaults(
            identity=FamilyIdentityDefaults(
                family_id=family_id,
                family_slug=family_slug,
                family_name=family_name,
                package_id=package_id,
                display_name=display_name,
                short_name=short_name,
                description=description,
                version=version,
                author=author,
                language=language,
                tags=normalized_tags,
                aliases=generated_aliases,
                metadata=metadata_payload,
            ),
            classification=FamilyClassificationDefaults(
                domain=domain,
                category=category,
                subcategory=subcategory,
                object_kind=object_kind,
                tags=normalized_tags,
                metadata=metadata_payload,
            ),
            lifecycle=FamilyLifecycleDefaults(
                status=status,
                metadata=metadata_payload,
            ),
            aliases=FamilyAliasesDefaults(
                aliases=generated_aliases,
                legacy_ids=normalized_legacy_ids,
                search_terms=normalized_search_terms,
                metadata=metadata_payload,
            ),
            metadata_defaults=FamilyMetadataDefaults(
                source_kind=source_kind,
                source_path=source_path,
                profile_key=profile_key,
                correlation_id=correlation_id,
                metadata=metadata_payload,
            ),
        ).normalized()
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"Could not build family defaults: {exc}") from exc


def family_defaults_from_create_request(
    request: Any,
    *,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FamilyDefaults:
    """Baut FamilyDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        identity = normalized_request.identity.normalized()
        classification = normalized_request.classification.normalized()

        return build_family_defaults(
            package_id=getattr(identity, "package_id", None),
            family_id=getattr(identity, "family_id", None),
            family_slug=getattr(identity, "family_slug", None) or getattr(identity, "family_id", "").split(".")[-1],
            family_name=getattr(identity, "family_name", None),
            display_name=getattr(identity, "display_name", None),
            short_name=getattr(identity, "short_name", None),
            description=getattr(identity, "description", ""),
            version=getattr(identity, "version", DEFAULT_FAMILY_VERSION),
            author=getattr(identity, "author", None),
            tags=getattr(identity, "tags", ()),
            object_kind=getattr(normalized_request, "object_kind", None),
            domain=getattr(classification, "domain", None),
            category=getattr(classification, "category", None),
            subcategory=getattr(classification, "subcategory", None),
            profile_key=profile_key,
            correlation_id=correlation_id,
            source_kind=FamilySourceKind.CREATE_REQUEST.value,
            metadata=metadata,
        )
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"Could not build family defaults from CreateRequest: {exc}") from exc


def family_defaults_from_context(
    context: Any,
    *,
    profile_key: str | None = None,
    source_kind: str = FamilySourceKind.PACKAGE_CONTEXT.value,
    metadata: Mapping[str, Any] | None = None,
) -> FamilyDefaults:
    """Baut FamilyDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        identity = getattr(normalized_context, "identity", None)
        classification = getattr(normalized_context, "classification", None)
        location = getattr(normalized_context, "location", None)

        if identity is None:
            raise FamilyDefaultsError("PackageContext identity is required.")

        if classification is None:
            raise FamilyDefaultsError("PackageContext classification is required.")

        family_name = getattr(identity, "family_name", None)

        return build_family_defaults(
            package_id=getattr(identity, "package_id", None),
            family_id=getattr(identity, "family_id", None),
            family_slug=getattr(identity, "family_slug", None),
            family_name=family_name,
            display_name=getattr(identity, "display_name", None) or family_name,
            short_name=getattr(identity, "short_name", None) or family_name,
            description=getattr(identity, "description", ""),
            version=getattr(identity, "version", DEFAULT_FAMILY_VERSION),
            author=getattr(identity, "author", None),
            tags=getattr(identity, "tags", ()),
            object_kind=getattr(normalized_context, "object_kind", None),
            domain=getattr(classification, "domain", None),
            category=getattr(classification, "category", None),
            subcategory=getattr(classification, "subcategory", None),
            profile_key=profile_key,
            correlation_id=getattr(normalized_context, "correlation_id", None),
            source_kind=source_kind,
            source_path=getattr(location, "package_relative_dir", None) if location is not None else None,
            metadata=metadata,
        )
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"Could not build family defaults from PackageContext: {exc}") from exc


def family_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> FamilyDefaults:
    """Baut FamilyDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan
        context = getattr(normalized_plan, "context", None)
        profile = getattr(normalized_plan, "profile", None)

        if context is None:
            raise FamilyDefaultsError("CreationPlan context is required.")

        return family_defaults_from_context(
            context,
            profile_key=getattr(profile, "profile_key", None),
            source_kind=FamilySourceKind.CREATION_PLAN.value,
            metadata={
                "creation_plan_status": getattr(normalized_plan, "status", None),
                **dict(metadata or {}),
            },
        )
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"Could not build family defaults from CreationPlan: {exc}") from exc


def family_identity_document_from_create_request(
    request: Any,
    *,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut family/identity.json aus CreateRequest."""
    return family_defaults_from_create_request(
        request,
        profile_key=profile_key,
        correlation_id=correlation_id,
        metadata=metadata,
    ).identity.to_document()


def family_classification_document_from_create_request(
    request: Any,
    *,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Baut family/classification.json aus CreateRequest."""
    return family_defaults_from_create_request(
        request,
        profile_key=profile_key,
        correlation_id=correlation_id,
        metadata=metadata,
    ).classification.to_document()


def family_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle Family-Dokumente aus CreateRequest."""
    return family_defaults_from_create_request(
        request,
        profile_key=profile_key,
        correlation_id=correlation_id,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def validate_family_identity_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob family/identity.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("family/identity.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "family_id",
            "family_slug",
            "family_name",
            "display_name",
            "version",
            "created_at",
            "updated_at",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing identity field {field_name!r}.")

        if "package_id" in document and document.get("package_id") is not None:
            try:
                normalize_family_id(document["package_id"], "package_id")
            except Exception as exc:
                messages.append(str(exc))

        if "family_id" in document:
            try:
                normalize_family_id(document["family_id"], "family_id")
            except Exception as exc:
                messages.append(str(exc))

        if "family_slug" in document:
            try:
                normalize_slug(document["family_slug"], "family_slug")
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate family identity document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_family_classification_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob family/classification.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("family/classification.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "domain",
            "category",
            "subcategory",
            "classification_path",
            "object_kind",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing classification field {field_name!r}.")

        try:
            FamilyClassificationDefaults(
                domain=document.get("domain"),
                category=document.get("category"),
                subcategory=document.get("subcategory"),
                object_kind=document.get("object_kind"),
            ).normalized()
        except Exception as exc:
            messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate family classification document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_family_identity_document(document: Mapping[str, Any]) -> None:
    """Wirft FamilyDefaultsError, wenn family/identity.json ungültig ist."""
    valid, messages = validate_family_identity_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid family identity document."
        raise FamilyDefaultsError(joined)


def assert_valid_family_classification_document(document: Mapping[str, Any]) -> None:
    """Wirft FamilyDefaultsError, wenn family/classification.json ungültig ist."""
    valid, messages = validate_family_classification_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid family classification document."
        raise FamilyDefaultsError(joined)


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

        raise FamilyDefaultsError("CreateRequest value is required.")
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise FamilyDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_family_id(value: Any, field_name: str) -> str:
    """Normalisiert family_id/package_id."""
    raw = clean_required_string(value, field_name).lower().replace(" ", "_")

    if not all(part for part in raw.split(".")):
        raise FamilyDefaultsError(f"{field_name} must not contain empty dot segments.")

    for part in raw.split("."):
        if not SAFE_FAMILY_ID_RE.match(part):
            raise FamilyDefaultsError(f"{field_name} contains unsafe segment {part!r}.")

    return raw


def normalize_optional_family_id(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale family_id/package_id."""
    if value is None:
        return None

    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    return normalize_family_id(cleaned, field_name)


def normalize_slug(value: Any, field_name: str) -> str:
    """Normalisiert einfache Slugs."""
    raw = clean_required_string(value, field_name).lower().replace(" ", "_").replace("-", "_")

    if not SAFE_SLUG_RE.match(raw):
        raise FamilyDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return raw


@lru_cache(maxsize=128)
def parse_lifecycle_status_value(value: Any) -> str:
    """Parst FamilyLifecycleStatus."""
    try:
        if isinstance(value, FamilyLifecycleStatus):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "draft": FamilyLifecycleStatus.DRAFT.value,
            "ready": FamilyLifecycleStatus.READY.value,
            "published": FamilyLifecycleStatus.PUBLISHED.value,
            "publish": FamilyLifecycleStatus.PUBLISHED.value,
            "deprecated": FamilyLifecycleStatus.DEPRECATED.value,
            "archived": FamilyLifecycleStatus.ARCHIVED.value,
            "archive": FamilyLifecycleStatus.ARCHIVED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return FamilyLifecycleStatus(raw).value
    except Exception as exc:
        raise FamilyDefaultsError(f"Invalid family lifecycle status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_source_kind_value(value: Any) -> str:
    """Parst FamilySourceKind."""
    try:
        if isinstance(value, FamilySourceKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "request": FamilySourceKind.CREATE_REQUEST.value,
            "create_request": FamilySourceKind.CREATE_REQUEST.value,
            "context": FamilySourceKind.PACKAGE_CONTEXT.value,
            "package_context": FamilySourceKind.PACKAGE_CONTEXT.value,
            "creation_plan": FamilySourceKind.CREATION_PLAN.value,
            "plan": FamilySourceKind.CREATION_PLAN.value,
            "scanner": FamilySourceKind.SCANNER.value,
            "scan": FamilySourceKind.SCANNER.value,
            "import": FamilySourceKind.IMPORT.value,
            "system": FamilySourceKind.SYSTEM.value,
        }

        if raw in aliases:
            return aliases[raw]

        return FamilySourceKind(raw).value
    except Exception as exc:
        raise FamilyDefaultsError(f"Invalid family source kind {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise FamilyDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_string_tuple(values: Iterable[Any] | Any) -> tuple[str, ...]:
    """Normalisiert Stringlisten ohne Duplikate."""
    if values is None:
        return tuple()

    if isinstance(values, str):
        values = (values,)

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
        raise FamilyDefaultsError("metadata must be a mapping.")

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
            raise FamilyDefaultsError(f"{field_name} is required.")

        return cleaned
    except FamilyDefaultsError:
        raise
    except Exception as exc:
        raise FamilyDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def value_or_enum_value(value: Any) -> str:
    """Gibt Enum.value oder str(value) zurück."""
    try:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)
    except Exception:
        return ""


def safe_definition_label(definition: Any, fallback: str) -> str:
    """Liest label aus Definition oder nutzt Fallback."""
    try:
        label = getattr(definition, "label", None)
        cleaned = clean_optional_string(label)
        return cleaned or fallback
    except Exception:
        return fallback


def clear_family_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_lifecycle_status_value.cache_clear()
    parse_source_kind_value.cache_clear()


__all__ = [
    "DEFAULT_FAMILY_VERSION",
    "DEFAULT_GENERATOR_NAME",
    "DEFAULT_GENERATOR_VERSION",
    "DEFAULT_LANGUAGE",
    "DEFAULT_STATUS",
    "FAMILY_ALIASES_DOCUMENT_SCHEMA_VERSION",
    "FAMILY_CLASSIFICATION_DOCUMENT_SCHEMA_VERSION",
    "FAMILY_DEFAULTS_SCHEMA_VERSION",
    "FAMILY_IDENTITY_DOCUMENT_SCHEMA_VERSION",
    "FAMILY_LIFECYCLE_DOCUMENT_SCHEMA_VERSION",
    "FAMILY_METADATA_DOCUMENT_SCHEMA_VERSION",
    "SAFE_FAMILY_ID_RE",
    "SAFE_SLUG_RE",
    "FamilyAliasesDefaults",
    "FamilyClassificationDefaults",
    "FamilyDefaults",
    "FamilyDefaultsError",
    "FamilyIdentityDefaults",
    "FamilyLifecycleDefaults",
    "FamilyLifecycleStatus",
    "FamilyMetadataDefaults",
    "FamilySourceKind",
    "assert_valid_family_classification_document",
    "assert_valid_family_identity_document",
    "build_family_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_family_defaults_caches",
    "family_classification_document_from_create_request",
    "family_defaults_from_context",
    "family_defaults_from_create_request",
    "family_defaults_from_creation_plan",
    "family_documents_from_create_request",
    "family_identity_document_from_create_request",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_family_id",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_object_kind_value",
    "normalize_optional_family_id",
    "normalize_slug",
    "normalize_string_tuple",
    "parse_lifecycle_status_value",
    "parse_source_kind_value",
    "safe_definition_label",
    "utc_now_iso",
    "validate_family_classification_document",
    "validate_family_identity_document",
    "value_or_enum_value",
]