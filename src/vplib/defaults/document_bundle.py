# services/vectoplan-library/src/vplib/defaults/document_bundle.py
"""
Document bundle defaults for the VPLIB package engine.

Diese Datei bündelt die Default-Dokumente eines VPLIB-Packages.

Rolle dieser Datei:

    CreateRequest / PackageContext / CreationPlan
    -> defaults/*
    -> DocumentBundle
    -> later: document_writer / package_creator

Diese Datei schreibt keine Dateien. Sie erzeugt nur eine stabile Sammlung aus:

    relative_path -> JSON-compatible document payload

Beispiele:
- vplib.manifest.json
- vplib.modules.json
- family/identity.json
- variants/index.json
- editor/placement.json
- render/render_variants.json
- physical/base.json
- material/base.json
- calculation/variables.json
- manufacturer/contract.json
- dynamic/context_rules.json

Wichtig für die neue VPLIB-ID-Architektur:
- Jedes Bundle mit `vplib.manifest.json` muss eine gültige `vplib_uid` enthalten.
- Fehlende `vplib_uid` wird beim Bundle-Bau erzeugt.
- Vorhandene gültige `vplib_uid` wird beibehalten.
- Vorhandene ungültige `vplib_uid` wird nicht still ersetzt.
- Wenn ein CreationPlan/CreateRequest/PackageContext bereits eine `vplib_uid`
  enthält, wird diese ID in das Manifest übernommen.
- Dadurch erzeugen Package-Plan, Download und Save nicht ungewollt verschiedene IDs,
  sofern der gleiche Payload/Context die ID weiterreicht.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


DOCUMENT_BUNDLE_SCHEMA_VERSION: Final[str] = "vplib.document_bundle.v1"

ROOT_DOCUMENTS: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
    "vplib.modules.json",
)

MANIFEST_DOCUMENT_PATH: Final[str] = "vplib.manifest.json"
MODULES_DOCUMENT_PATH: Final[str] = "vplib.modules.json"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"

CORE_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "manufacturer",
)

DEFAULT_INCLUDE_OPTIONAL: Final[bool] = True


class DocumentBundleError(ValueError):
    """Wird ausgelöst, wenn ein DocumentBundle ungültig erzeugt wird."""


class DocumentBundleSource(str, Enum):
    """Quelle eines DocumentBundle."""

    CREATE_REQUEST = "create_request"
    PACKAGE_CONTEXT = "package_context"
    CREATION_PLAN = "creation_plan"
    COMPONENTS = "components"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class DocumentKind(str, Enum):
    """Art eines Dokuments."""

    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class DocumentRequirement(str, Enum):
    """Anforderungsstatus eines Bundle-Dokuments."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class DocumentBundleOptions:
    """Optionen für die Dokumentbündelung."""

    include_optional: bool = DEFAULT_INCLUDE_OPTIONAL
    include_generated: bool = True
    include_docs_module: bool = False
    include_tests_module: bool = False
    include_empty_optional_documents: bool = True
    include_inactive_module_documents: bool = False
    strict: bool = True

    def normalized(self) -> "DocumentBundleOptions":
        return DocumentBundleOptions(
            include_optional=bool(self.include_optional),
            include_generated=bool(self.include_generated),
            include_docs_module=bool(self.include_docs_module),
            include_tests_module=bool(self.include_tests_module),
            include_empty_optional_documents=bool(self.include_empty_optional_documents),
            include_inactive_module_documents=bool(self.include_inactive_module_documents),
            strict=bool(self.strict),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "include_optional": normalized.include_optional,
            "include_generated": normalized.include_generated,
            "include_docs_module": normalized.include_docs_module,
            "include_tests_module": normalized.include_tests_module,
            "include_empty_optional_documents": normalized.include_empty_optional_documents,
            "include_inactive_module_documents": normalized.include_inactive_module_documents,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class DocumentBundleItem:
    """Ein einzelnes Dokument im Bundle."""

    relative_path: str
    document: Mapping[str, Any]
    module_name: str
    requirement: str = DocumentRequirement.REQUIRED.value
    document_kind: str = DocumentKind.JSON.value
    source: str = DocumentBundleSource.SYSTEM.value
    schema_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DocumentBundleItem":
        relative_path = normalize_package_path(self.relative_path)
        document = normalize_bundle_document_for_path(relative_path, self.document)
        module_name = infer_or_normalize_module_name(self.module_name, relative_path)
        requirement = parse_document_requirement_value(self.requirement)
        document_kind = parse_document_kind_value(self.document_kind)
        source = parse_bundle_source_value(self.source)
        schema_version = clean_optional_string(self.schema_version) or clean_optional_string(document.get("schema_version"))
        metadata = normalize_metadata(self.metadata)

        if document_kind == DocumentKind.JSON.value and not isinstance(document, Mapping):
            raise DocumentBundleError(f"Document {relative_path!r} must be a JSON mapping.")

        return DocumentBundleItem(
            relative_path=relative_path,
            document=document,
            module_name=module_name,
            requirement=requirement,
            document_kind=document_kind,
            source=source,
            schema_version=schema_version,
            metadata=metadata,
        )

    @property
    def required(self) -> bool:
        return self.normalized().requirement == DocumentRequirement.REQUIRED.value

    @property
    def optional(self) -> bool:
        return self.normalized().requirement == DocumentRequirement.OPTIONAL.value

    @property
    def generated(self) -> bool:
        return self.normalized().requirement == DocumentRequirement.GENERATED.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "module_name": normalized.module_name,
            "requirement": normalized.requirement,
            "document_kind": normalized.document_kind,
            "source": normalized.source,
            "schema_version": normalized.schema_version,
            "document": dict(normalized.document),
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class DocumentBundle:
    """Vollständiges Dokumentbundle für ein VPLIB-Package."""

    items: tuple[DocumentBundleItem, ...]
    source: str = DocumentBundleSource.SYSTEM.value
    active_modules: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str = DOCUMENT_BUNDLE_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DocumentBundle":
        source = parse_bundle_source_value(self.source)
        active_modules = normalize_module_tuple(self.active_modules)
        metadata = normalize_metadata(self.metadata)

        items = tuple(item.normalized() for item in self.items or ())
        items = dedupe_bundle_items(items)
        items = ensure_bundle_items_manifest_vplib_uid(items)
        items = filter_items_for_active_modules(
            items,
            active_modules=active_modules,
            include_inactive=True if not active_modules else False,
        )
        items = sort_bundle_items(items)

        bundle = DocumentBundle(
            items=items,
            source=source,
            active_modules=active_modules,
            schema_version=self.schema_version or DOCUMENT_BUNDLE_SCHEMA_VERSION,
            metadata=metadata,
        )

        valid, messages = bundle.validate()
        if not valid:
            raise DocumentBundleError(" ".join(messages))

        return bundle

    @property
    def documents(self) -> dict[str, dict[str, Any]]:
        normalized = self.normalized()
        return {
            item.relative_path: dict(item.document)
            for item in normalized.items
        }

    @property
    def vplib_uid(self) -> str | None:
        """Liest die VPLIB-Paket-ID aus dem Manifest-Dokument."""
        return get_vplib_uid_from_items(self.normalized().items)

    @property
    def required_items(self) -> tuple[DocumentBundleItem, ...]:
        return tuple(item for item in self.normalized().items if item.required)

    @property
    def optional_items(self) -> tuple[DocumentBundleItem, ...]:
        return tuple(item for item in self.normalized().items if item.optional)

    @property
    def generated_items(self) -> tuple[DocumentBundleItem, ...]:
        return tuple(item for item in self.normalized().items if item.generated)

    @property
    def relative_paths(self) -> tuple[str, ...]:
        return tuple(item.relative_path for item in self.normalized().items)

    @property
    def module_names(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(item.module_name for item in self.normalized().items))

    def by_module(self, module_name: Any) -> tuple[DocumentBundleItem, ...]:
        module_value = normalize_module_name(module_name)

        return tuple(
            item
            for item in self.normalized().items
            if item.module_name == module_value
        )

    def get_document(self, relative_path: Any) -> dict[str, Any] | None:
        path = normalize_package_path(relative_path)

        for item in self.normalized().items:
            if item.relative_path == path:
                return dict(item.document)

        return None

    def require_document(self, relative_path: Any) -> dict[str, Any]:
        document = self.get_document(relative_path)

        if document is None:
            raise DocumentBundleError(f"Document {relative_path!r} does not exist in bundle.")

        return document

    def with_item(self, item: DocumentBundleItem) -> "DocumentBundle":
        normalized = self.normalized()

        return DocumentBundle(
            items=(*normalized.items, item.normalized()),
            source=normalized.source,
            active_modules=normalized.active_modules,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_documents(
        self,
        documents: Mapping[str, Mapping[str, Any]],
        *,
        module_name: str | None = None,
        requirement: str = DocumentRequirement.OPTIONAL.value,
        source: str = DocumentBundleSource.SYSTEM.value,
    ) -> "DocumentBundle":
        normalized = self.normalized()
        items = list(normalized.items)
        items.extend(
            bundle_items_from_documents(
                documents,
                module_name=module_name,
                requirement=requirement,
                source=source,
            )
        )

        return DocumentBundle(
            items=tuple(items),
            source=normalized.source,
            active_modules=normalized.active_modules,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        messages: list[str] = []

        try:
            paths = [item.relative_path for item in self.items or ()]
            duplicates = find_duplicates(paths)
            for path in duplicates:
                messages.append(f"Duplicate bundle document path {path!r}.")

            for item in self.items or ():
                normalized_item = item.normalized()

                if normalized_item.document_kind == DocumentKind.JSON.value:
                    if not isinstance(normalized_item.document, Mapping):
                        messages.append(f"Document {normalized_item.relative_path!r} is not a mapping.")

                if normalized_item.relative_path.endswith(".json") and "schema_version" not in normalized_item.document:
                    messages.append(f"Document {normalized_item.relative_path!r} has no schema_version.")

                if normalized_item.relative_path == MANIFEST_DOCUMENT_PATH:
                    manifest_valid, manifest_messages = validate_manifest_document_for_bundle(normalized_item.document)
                    if not manifest_valid:
                        messages.extend(manifest_messages)

            required_root_documents = set(ROOT_DOCUMENTS)
            present_root_documents = set(paths)
            missing_root_documents = required_root_documents - present_root_documents
            for path in sorted(missing_root_documents):
                messages.append(f"Missing required root document {path!r}.")

            if MANIFEST_DOCUMENT_PATH in present_root_documents:
                uid = get_vplib_uid_from_items(self.items or ())
                if not uid:
                    messages.append(f"Manifest document {MANIFEST_DOCUMENT_PATH!r} has no valid {MANIFEST_VPLIB_UID_FIELD!r}.")

        except DocumentBundleError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate document bundle: {exc}")

        return len(messages) == 0, tuple(messages)

    def to_documents(self) -> dict[str, dict[str, Any]]:
        """Gibt nur path -> document zurück."""
        return self.documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        vplib_uid = get_vplib_uid_from_items(normalized.items)

        return {
            "schema_version": normalized.schema_version,
            "source": normalized.source,
            "vplib_uid": vplib_uid,
            "active_modules": list(normalized.active_modules),
            "item_count": len(normalized.items),
            "required_item_count": len(normalized.required_items),
            "optional_item_count": len(normalized.optional_items),
            "generated_item_count": len(normalized.generated_items),
            "relative_paths": list(normalized.relative_paths),
            "module_names": list(normalized.module_names),
            "items": [item.to_dict() for item in normalized.items],
            "metadata": dict(normalized.metadata),
        }


def build_document_bundle_from_creation_plan(
    creation_plan: Any,
    *,
    options: DocumentBundleOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentBundle:
    """Baut ein vollständiges DocumentBundle aus einem CreationPlan."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan
        normalized_options = normalize_options(options)

        active_modules = tuple(getattr(normalized_plan.module_plan, "active_module_names", ()) or ())
        request = normalized_plan.request
        context = normalized_plan.context
        profile = normalized_plan.profile
        module_plan = normalized_plan.module_plan
        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(normalized_plan)
            or extract_raw_vplib_uid_from_any(request)
            or extract_raw_vplib_uid_from_any(context)
            or extract_raw_vplib_uid_from_any(metadata)
        )

        items: list[DocumentBundleItem] = []

        items.extend(
            root_document_items_from_context_and_module_plan(
                context=context,
                module_plan=module_plan,
                profile_key=getattr(profile, "profile_key", None),
                source=DocumentBundleSource.CREATION_PLAN.value,
                vplib_uid=raw_vplib_uid,
            )
        )

        items.extend(
            module_document_items_from_create_request(
                request,
                active_modules=active_modules,
                options=normalized_options,
                source=DocumentBundleSource.CREATION_PLAN.value,
            )
        )

        return DocumentBundle(
            items=tuple(items),
            source=DocumentBundleSource.CREATION_PLAN.value,
            active_modules=active_modules,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(profile, "profile_key", None),
                "package_id": getattr(context.identity, "package_id", None),
                "vplib_uid": raw_vplib_uid,
                **dict(metadata or {}),
            },
        ).normalized()
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"Could not build document bundle from CreationPlan: {exc}") from exc


def build_document_bundle_from_create_request(
    request: Any,
    *,
    module_plan: Any | None = None,
    profile_key: str | None = None,
    correlation_id: str | None = None,
    options: DocumentBundleOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentBundle:
    """Baut ein DocumentBundle direkt aus einem CreateRequest."""
    try:
        normalized_request = normalize_create_request(request)
        normalized_options = normalize_options(options)
        active_modules = infer_active_modules(
            request=normalized_request,
            module_plan=module_plan,
            options=normalized_options,
        )
        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(normalized_request)
            or extract_raw_vplib_uid_from_any(request)
            or extract_raw_vplib_uid_from_any(metadata)
        )

        items: list[DocumentBundleItem] = []

        items.extend(
            root_document_items_from_create_request(
                normalized_request,
                module_plan=module_plan,
                profile_key=profile_key,
                correlation_id=correlation_id,
                source=DocumentBundleSource.CREATE_REQUEST.value,
                vplib_uid=raw_vplib_uid,
            )
        )

        items.extend(
            module_document_items_from_create_request(
                normalized_request,
                active_modules=active_modules,
                options=normalized_options,
                source=DocumentBundleSource.CREATE_REQUEST.value,
            )
        )

        return DocumentBundle(
            items=tuple(items),
            source=DocumentBundleSource.CREATE_REQUEST.value,
            active_modules=active_modules,
            metadata={
                "source": "create_request",
                "object_kind": normalized_request.object_kind,
                "profile_key": profile_key,
                "vplib_uid": raw_vplib_uid,
                **dict(metadata or {}),
            },
        ).normalized()
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"Could not build document bundle from CreateRequest: {exc}") from exc


def build_document_bundle_from_context(
    context: Any,
    *,
    module_plan: Any | None = None,
    profile_key: str | None = None,
    options: DocumentBundleOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentBundle:
    """Baut ein minimales DocumentBundle aus einem PackageContext."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        normalized_options = normalize_options(options)
        active_modules = infer_active_modules(
            request=None,
            module_plan=module_plan,
            options=normalized_options,
        )
        raw_vplib_uid = (
            extract_raw_vplib_uid_from_any(normalized_context)
            or extract_raw_vplib_uid_from_any(context)
            or extract_raw_vplib_uid_from_any(metadata)
        )

        if not active_modules:
            active_modules = CORE_MODULES

        items: list[DocumentBundleItem] = []

        items.extend(
            root_document_items_from_context_and_module_plan(
                context=normalized_context,
                module_plan=module_plan,
                profile_key=profile_key,
                source=DocumentBundleSource.PACKAGE_CONTEXT.value,
                vplib_uid=raw_vplib_uid,
            )
        )

        items.extend(
            module_document_items_from_context(
                normalized_context,
                active_modules=active_modules,
                options=normalized_options,
                source=DocumentBundleSource.PACKAGE_CONTEXT.value,
            )
        )

        return DocumentBundle(
            items=tuple(items),
            source=DocumentBundleSource.PACKAGE_CONTEXT.value,
            active_modules=active_modules,
            metadata={
                "source": "package_context",
                "object_kind": normalized_context.object_kind,
                "profile_key": profile_key,
                "vplib_uid": raw_vplib_uid,
                **dict(metadata or {}),
            },
        ).normalized()
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"Could not build document bundle from PackageContext: {exc}") from exc


def build_document_bundle_from_components(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    active_modules: Iterable[Any] = (),
    source: str = DocumentBundleSource.COMPONENTS.value,
    metadata: Mapping[str, Any] | None = None,
) -> DocumentBundle:
    """Baut ein DocumentBundle aus bereits erzeugten Dokumenten."""
    try:
        items = bundle_items_from_documents(
            documents,
            module_name=None,
            requirement=DocumentRequirement.REQUIRED.value,
            source=source,
        )

        return DocumentBundle(
            items=items,
            source=source,
            active_modules=normalize_module_tuple(active_modules),
            metadata=dict(metadata or {}),
        ).normalized()
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"Could not build document bundle from components: {exc}") from exc


def root_document_items_from_create_request(
    request: Any,
    *,
    module_plan: Any | None,
    profile_key: str | None,
    correlation_id: str | None,
    source: str,
    vplib_uid: Any | None = None,
) -> tuple[DocumentBundleItem, ...]:
    """Erzeugt Root-Dokumente aus CreateRequest."""
    normalized_request = normalize_create_request(request)
    documents: dict[str, Mapping[str, Any]] = {}

    try:
        from .manifest_defaults import manifest_document_from_create_request
        from .manifest_defaults import manifest_document_with_vplib_uid

        manifest = manifest_document_from_create_request(
            normalized_request,
            profile_key=profile_key,
            correlation_id=correlation_id,
        )

        if vplib_uid is not None:
            manifest = manifest_document_with_vplib_uid(
                manifest,
                vplib_uid=vplib_uid,
                overwrite=True,
            )

        documents[MANIFEST_DOCUMENT_PATH] = manifest
    except Exception as exc:
        raise DocumentBundleError(f"Could not create manifest document: {exc}") from exc

    try:
        if module_plan is not None:
            from .module_defaults import modules_document_from_module_plan

            documents[MODULES_DOCUMENT_PATH] = modules_document_from_module_plan(module_plan)
        else:
            from .module_defaults import build_modules_document

            documents[MODULES_DOCUMENT_PATH] = build_modules_document(
                object_kind=normalized_request.object_kind,
                profile_key=profile_key,
                active_modules=CORE_MODULES,
                required_modules=CORE_MODULES,
            )
    except Exception as exc:
        raise DocumentBundleError(f"Could not create modules document: {exc}") from exc

    return bundle_items_from_documents(
        documents,
        module_name=None,
        requirement=DocumentRequirement.REQUIRED.value,
        source=source,
    )


def root_document_items_from_context_and_module_plan(
    *,
    context: Any,
    module_plan: Any | None,
    profile_key: str | None,
    source: str,
    vplib_uid: Any | None = None,
) -> tuple[DocumentBundleItem, ...]:
    """Erzeugt Root-Dokumente aus Context und ModulePlan."""
    normalized_context = context.normalized() if hasattr(context, "normalized") else context
    documents: dict[str, Mapping[str, Any]] = {}

    try:
        from .manifest_defaults import manifest_document_from_context
        from .manifest_defaults import manifest_document_with_vplib_uid

        manifest = manifest_document_from_context(
            normalized_context,
            profile_key=profile_key,
        )

        if vplib_uid is not None:
            manifest = manifest_document_with_vplib_uid(
                manifest,
                vplib_uid=vplib_uid,
                overwrite=True,
            )

        documents[MANIFEST_DOCUMENT_PATH] = manifest
    except Exception as exc:
        raise DocumentBundleError(f"Could not create manifest document: {exc}") from exc

    try:
        if module_plan is not None:
            from .module_defaults import modules_document_from_module_plan

            documents[MODULES_DOCUMENT_PATH] = modules_document_from_module_plan(module_plan)
        else:
            from .module_defaults import build_modules_document

            documents[MODULES_DOCUMENT_PATH] = build_modules_document(
                object_kind=normalized_context.object_kind,
                profile_key=profile_key,
                active_modules=CORE_MODULES,
                required_modules=CORE_MODULES,
            )
    except Exception as exc:
        raise DocumentBundleError(f"Could not create modules document: {exc}") from exc

    return bundle_items_from_documents(
        documents,
        module_name=None,
        requirement=DocumentRequirement.REQUIRED.value,
        source=source,
    )


def module_document_items_from_create_request(
    request: Any,
    *,
    active_modules: Iterable[Any],
    options: DocumentBundleOptions,
    source: str,
) -> tuple[DocumentBundleItem, ...]:
    """Erzeugt Modul-Dokumente aus CreateRequest."""
    normalized_request = normalize_create_request(request)
    normalized_options = options.normalized()
    active = set(normalize_module_tuple(active_modules))
    documents: dict[str, Mapping[str, Any]] = {}

    if should_include_module("family", active, normalized_options):
        from .family_defaults import family_documents_from_create_request

        documents.update(
            family_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("variants", active, normalized_options):
        from .variant_defaults import variant_documents_from_create_request

        documents.update(
            variant_documents_from_create_request(normalized_request)
        )

    if should_include_module("editor", active, normalized_options):
        from .editor_defaults import editor_documents_from_create_request

        documents.update(
            editor_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("render", active, normalized_options):
        from .render_defaults import render_documents_from_create_request

        documents.update(
            render_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("physical", active, normalized_options):
        from .physical_defaults import physical_documents_from_create_request

        documents.update(
            physical_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("material", active, normalized_options):
        from .material_defaults import material_documents_from_create_request

        documents.update(
            material_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("calculation", active, normalized_options):
        from .calculation_defaults import calculation_documents_from_create_request

        documents.update(
            calculation_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("analysis", active, normalized_options):
        from .analysis_defaults import analysis_documents_from_create_request

        documents.update(
            analysis_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("dynamic", active, normalized_options):
        from .dynamic_defaults import dynamic_documents_from_create_request

        documents.update(
            dynamic_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("manufacturer", active, normalized_options):
        from .manufacturer_defaults import manufacturer_documents_from_create_request

        documents.update(
            manufacturer_documents_from_create_request(
                normalized_request,
                include_optional=normalized_options.include_optional,
            )
        )

    return bundle_items_from_documents(
        documents,
        module_name=None,
        requirement=DocumentRequirement.REQUIRED.value,
        source=source,
    )


def module_document_items_from_context(
    context: Any,
    *,
    active_modules: Iterable[Any],
    options: DocumentBundleOptions,
    source: str,
) -> tuple[DocumentBundleItem, ...]:
    """Erzeugt Modul-Dokumente aus PackageContext."""
    normalized_context = context.normalized() if hasattr(context, "normalized") else context
    normalized_options = options.normalized()
    active = set(normalize_module_tuple(active_modules))
    documents: dict[str, Mapping[str, Any]] = {}

    if should_include_module("family", active, normalized_options):
        from .family_defaults import family_defaults_from_context

        documents.update(
            family_defaults_from_context(normalized_context).to_documents(
                include_optional=normalized_options.include_optional
            )
        )

    if should_include_module("variants", active, normalized_options):
        from .variant_defaults import build_variant_defaults

        documents.update(build_variant_defaults().to_documents())

    if should_include_module("editor", active, normalized_options):
        from .editor_defaults import editor_documents_from_context

        documents.update(
            editor_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("render", active, normalized_options):
        from .render_defaults import render_documents_from_context

        documents.update(
            render_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("physical", active, normalized_options):
        from .physical_defaults import physical_documents_from_context

        documents.update(
            physical_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("material", active, normalized_options):
        from .material_defaults import material_documents_from_context

        documents.update(
            material_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("calculation", active, normalized_options):
        from .calculation_defaults import calculation_documents_from_context

        documents.update(
            calculation_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("analysis", active, normalized_options):
        from .analysis_defaults import analysis_documents_from_context

        documents.update(
            analysis_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("dynamic", active, normalized_options):
        from .dynamic_defaults import dynamic_documents_from_context

        documents.update(
            dynamic_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    if should_include_module("manufacturer", active, normalized_options):
        from .manufacturer_defaults import manufacturer_documents_from_context

        documents.update(
            manufacturer_documents_from_context(
                normalized_context,
                include_optional=normalized_options.include_optional,
            )
        )

    return bundle_items_from_documents(
        documents,
        module_name=None,
        requirement=DocumentRequirement.REQUIRED.value,
        source=source,
    )


def bundle_items_from_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    module_name: str | None,
    requirement: str,
    source: str,
) -> tuple[DocumentBundleItem, ...]:
    """Wandelt path -> document in BundleItems um."""
    if not isinstance(documents, Mapping):
        raise DocumentBundleError("documents must be a mapping.")

    items: list[DocumentBundleItem] = []

    for relative_path, document in documents.items():
        path = normalize_package_path(relative_path)
        inferred_module = module_name or infer_module_from_path_safe(path)
        normalized_document = normalize_bundle_document_for_path(path, document)

        items.append(
            DocumentBundleItem(
                relative_path=path,
                document=normalized_document,
                module_name=inferred_module or "manifest",
                requirement=requirement_for_path(path, default=requirement),
                document_kind=DocumentKind.JSON.value if path.endswith(".json") else DocumentKind.OTHER.value,
                source=source,
                schema_version=normalized_document.get("schema_version") if isinstance(normalized_document, Mapping) else None,
            ).normalized()
        )

    return tuple(items)


def infer_active_modules(
    *,
    request: Any | None,
    module_plan: Any | None,
    options: DocumentBundleOptions,
) -> tuple[str, ...]:
    """Leitet aktive Module aus ModulePlan oder Request ab."""
    if module_plan is not None:
        try:
            normalized_plan = module_plan.normalized() if hasattr(module_plan, "normalized") else module_plan
            return normalize_module_tuple(getattr(normalized_plan, "active_module_names", ()) or ())
        except Exception as exc:
            if options.strict:
                raise DocumentBundleError(f"Could not infer active modules from ModulePlan: {exc}") from exc

    modules: list[str] = list(CORE_MODULES)

    if request is not None:
        try:
            normalized_request = normalize_create_request(request)
            modules.extend(("render", "physical"))

            if has_material_data(normalized_request):
                modules.append("material")
            if has_calculation_data(normalized_request):
                modules.append("calculation")
            if has_analysis_data(normalized_request):
                modules.append("analysis")
            if has_dynamic_data(normalized_request):
                modules.append("dynamic")
            if getattr(normalized_request.options, "include_docs", False) or options.include_docs_module:
                modules.append("docs")
            if getattr(normalized_request.options, "include_tests", False) or options.include_tests_module:
                modules.append("tests")
        except Exception as exc:
            if options.strict:
                raise DocumentBundleError(f"Could not infer active modules from request: {exc}") from exc

    if options.include_docs_module:
        modules.append("docs")

    if options.include_tests_module:
        modules.append("tests")

    return normalize_module_tuple(modules)


def should_include_module(
    module_name: str,
    active_modules: set[str],
    options: DocumentBundleOptions,
) -> bool:
    """Prüft, ob ein Modul in das Bundle aufgenommen werden soll."""
    module_value = normalize_module_name(module_name)

    if options.include_inactive_module_documents:
        return True

    return module_value in active_modules


def filter_items_for_active_modules(
    items: Iterable[DocumentBundleItem],
    *,
    active_modules: Iterable[str],
    include_inactive: bool,
) -> tuple[DocumentBundleItem, ...]:
    """Filtert BundleItems anhand aktiver Module."""
    if include_inactive:
        return tuple(item.normalized() for item in items or ())

    active = set(normalize_module_tuple(active_modules))
    if not active:
        return tuple(item.normalized() for item in items or ())

    return tuple(
        item.normalized()
        for item in items or ()
        if item.normalized().module_name in active
        or item.normalized().relative_path in ROOT_DOCUMENTS
    )


def dedupe_bundle_items(items: Iterable[DocumentBundleItem]) -> tuple[DocumentBundleItem, ...]:
    """Dedupliziert Items anhand relative_path."""
    by_path: dict[str, DocumentBundleItem] = {}

    for item in items or ():
        normalized = item.normalized()
        existing = by_path.get(normalized.relative_path)

        if existing is None:
            by_path[normalized.relative_path] = normalized
            continue

        by_path[normalized.relative_path] = merge_bundle_items(existing, normalized)

    return tuple(by_path.values())


def ensure_bundle_items_manifest_vplib_uid(
    items: Iterable[DocumentBundleItem],
) -> tuple[DocumentBundleItem, ...]:
    """
    Stellt sicher, dass das Manifest-Item eine gültige vplib_uid enthält.

    Diese Funktion wird nach Deduplizierung ausgeführt.
    """
    result: list[DocumentBundleItem] = []

    for item in items or ():
        normalized = item.normalized()

        if normalized.relative_path != MANIFEST_DOCUMENT_PATH:
            result.append(normalized)
            continue

        manifest = normalize_bundle_document_for_path(
            normalized.relative_path,
            normalized.document,
        )

        result.append(
            DocumentBundleItem(
                relative_path=normalized.relative_path,
                document=manifest,
                module_name=normalized.module_name,
                requirement=normalized.requirement,
                document_kind=normalized.document_kind,
                source=normalized.source,
                schema_version=normalized.schema_version or clean_optional_string(manifest.get("schema_version")),
                metadata=dict(normalized.metadata),
            ).normalized()
        )

    return tuple(result)


def merge_bundle_items(left: DocumentBundleItem, right: DocumentBundleItem) -> DocumentBundleItem:
    """Merged zwei BundleItems desselben Pfads."""
    left_normalized = left.normalized()
    right_normalized = right.normalized()

    if left_normalized.relative_path != right_normalized.relative_path:
        raise DocumentBundleError(
            f"Cannot merge documents with different paths: "
            f"{left_normalized.relative_path!r}, {right_normalized.relative_path!r}."
        )

    merged_document = right_normalized.document or left_normalized.document

    if left_normalized.relative_path == MANIFEST_DOCUMENT_PATH:
        left_uid = get_vplib_uid_from_document(left_normalized.document)
        right_uid = get_vplib_uid_from_document(right_normalized.document)

        if left_uid and right_uid and left_uid != right_uid:
            raise DocumentBundleError(
                f"Cannot merge manifest documents with different {MANIFEST_VPLIB_UID_FIELD!r}: "
                f"{left_uid!r} != {right_uid!r}."
            )

        merged_document = normalize_bundle_document_for_path(
            MANIFEST_DOCUMENT_PATH,
            merged_document,
        )

    return DocumentBundleItem(
        relative_path=left_normalized.relative_path,
        document=merged_document,
        module_name=right_normalized.module_name or left_normalized.module_name,
        requirement=stronger_requirement(left_normalized.requirement, right_normalized.requirement),
        document_kind=right_normalized.document_kind or left_normalized.document_kind,
        source=right_normalized.source or left_normalized.source,
        schema_version=right_normalized.schema_version or left_normalized.schema_version,
        metadata={
            **dict(left_normalized.metadata),
            **dict(right_normalized.metadata),
        },
    ).normalized()


def sort_bundle_items(items: Iterable[DocumentBundleItem]) -> tuple[DocumentBundleItem, ...]:
    """Sortiert BundleItems stabil."""
    return tuple(
        sorted(
            (item.normalized() for item in items or ()),
            key=lambda item: (
                module_order(item.module_name),
                requirement_order(item.requirement),
                item.relative_path,
            ),
        )
    )


def requirement_for_path(path: str, *, default: str) -> str:
    """Leitet Requirement für bekannte Pfade ab."""
    normalized_path = normalize_package_path(path)

    if normalized_path in {
        MANIFEST_DOCUMENT_PATH,
        MODULES_DOCUMENT_PATH,
        "family/identity.json",
        "family/classification.json",
        "variants/index.json",
        "variants/default.json",
        "editor/inventory.json",
        "editor/placement.json",
        "manufacturer/contract.json",
    }:
        return DocumentRequirement.REQUIRED.value

    return parse_document_requirement_value(default)


def stronger_requirement(left: str, right: str) -> str:
    """Ermittelt stärkeren Dokumentstatus."""
    left_value = parse_document_requirement_value(left)
    right_value = parse_document_requirement_value(right)

    order = {
        DocumentRequirement.OPTIONAL.value: 10,
        DocumentRequirement.GENERATED.value: 20,
        DocumentRequirement.REQUIRED.value: 30,
    }

    return left_value if order[left_value] >= order[right_value] else right_value


def requirement_order(value: str) -> int:
    """Sortierwert für Requirement."""
    requirement = parse_document_requirement_value(value)
    return {
        DocumentRequirement.REQUIRED.value: 10,
        DocumentRequirement.GENERATED.value: 20,
        DocumentRequirement.OPTIONAL.value: 30,
    }.get(requirement, 99)


def module_order(module_name: str) -> int:
    """Sortierwert für Module."""
    order = {
        "manifest": 10,
        "modules": 20,
        "family": 30,
        "variants": 40,
        "editor": 50,
        "render": 60,
        "physical": 70,
        "material": 80,
        "calculation": 90,
        "analysis": 100,
        "dynamic": 110,
        "manufacturer": 120,
        "docs": 130,
        "tests": 140,
    }

    try:
        return order.get(normalize_module_name(module_name), 999)
    except Exception:
        return 999


def has_material_data(request: Any) -> bool:
    """Prüft, ob Materialdaten im Request vorhanden sind."""
    material = getattr(request, "material", None)
    if material is None:
        return False

    return any(
        getattr(material, attr, None) is not None
        for attr in (
            "material_id",
            "material_name",
            "material_class",
            "surface_finish",
            "thermal_conductivity",
            "u_value",
            "compressive_strength",
        )
    )


def has_calculation_data(request: Any) -> bool:
    """Prüft, ob Calculationdaten im Request vorhanden sind."""
    calculation = getattr(request, "calculation", None)
    if calculation is None:
        return False

    return any(
        bool(getattr(calculation, attr, None))
        for attr in (
            "variables",
            "formulas",
            "quantities",
            "constraints",
            "measure_logic",
        )
    )


def has_analysis_data(request: Any) -> bool:
    """Prüft, ob Analysisdaten implizit sinnvoll sind."""
    physical = getattr(request, "physical", None)
    if physical is None:
        return False

    return bool(getattr(physical, "load_bearing", False))


def has_dynamic_data(request: Any) -> bool:
    """Prüft, ob Dynamicdaten im Request vorhanden sind."""
    if getattr(request, "object_kind", None) == "adaptive_system":
        return True

    dynamic = getattr(request, "dynamic", None)
    if dynamic is None:
        return False

    return any(
        bool(getattr(dynamic, attr, None))
        for attr in (
            "context_rules",
            "bindings",
            "generator",
            "parameters",
        )
    )


def normalize_options(
    options: DocumentBundleOptions | Mapping[str, Any] | None,
) -> DocumentBundleOptions:
    """Normalisiert DocumentBundleOptions."""
    if options is None:
        return DocumentBundleOptions().normalized()

    if isinstance(options, DocumentBundleOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return DocumentBundleOptions(
            include_optional=bool(options.get("include_optional", DEFAULT_INCLUDE_OPTIONAL)),
            include_generated=bool(options.get("include_generated", True)),
            include_docs_module=bool(options.get("include_docs_module", False)),
            include_tests_module=bool(options.get("include_tests_module", False)),
            include_empty_optional_documents=bool(options.get("include_empty_optional_documents", True)),
            include_inactive_module_documents=bool(options.get("include_inactive_module_documents", False)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise DocumentBundleError("options must be DocumentBundleOptions, mapping or None.")


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

        raise DocumentBundleError("CreateRequest value is required.")
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"Invalid CreateRequest: {exc}") from exc


def normalize_package_path(value: Any) -> str:
    """Normalisiert package-relative Pfade."""
    try:
        from ..domain.package_paths import normalize_package_path as normalize

        if str(value).strip() in ROOT_DOCUMENTS:
            return str(value).strip()

        return normalize(value)
    except Exception:
        raw = clean_required_string(value, "relative_path").replace("\\", "/").strip("/")
        if not raw or raw.startswith("../") or "/../" in raw:
            raise DocumentBundleError(f"Invalid package path {value!r}.")
        return raw


def infer_module_from_path_safe(path: Any) -> str | None:
    """Leitet Modul aus Pfad ab."""
    normalized_path = str(path).replace("\\", "/").strip()

    if normalized_path == MANIFEST_DOCUMENT_PATH:
        return "manifest"

    if normalized_path == MODULES_DOCUMENT_PATH:
        return "modules"

    try:
        from ..domain.package_paths import infer_module_from_path

        return infer_module_from_path(normalized_path)
    except Exception:
        first = normalized_path.split("/", 1)[0]
        if first.endswith(".json"):
            return "manifest"
        return first or None


def infer_or_normalize_module_name(module_name: Any, relative_path: str) -> str:
    """Normalisiert Modulnamen oder leitet ihn aus dem Pfad ab."""
    if module_name:
        return normalize_module_name(module_name)

    inferred = infer_module_from_path_safe(relative_path)
    if inferred:
        return normalize_module_name(inferred)

    raise DocumentBundleError(f"Could not infer module for path {relative_path!r}.")


def normalize_module_name(value: Any) -> str:
    """Normalisiert Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raw = clean_required_string(value, "module_name").lower().replace(" ", "_").replace("-", "_")
        allowed = {
            "manifest",
            "modules",
            "family",
            "variants",
            "editor",
            "render",
            "physical",
            "material",
            "calculation",
            "analysis",
            "dynamic",
            "manufacturer",
            "docs",
            "tests",
        }
        if raw not in allowed:
            raise DocumentBundleError(f"Invalid module_name {value!r}: {exc}") from exc
        return raw


def normalize_module_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Modulnamen ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        module_name = normalize_module_name(value)

        if module_name in seen:
            continue

        result.append(module_name)
        seen.add(module_name)

    return tuple(sorted(result, key=module_order))


def normalize_bundle_document_for_path(
    relative_path: Any,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Normalisiert ein Dokument abhängig vom Package-Pfad.

    Speziell:
    - `vplib.manifest.json` bekommt immer eine gültige `vplib_uid`.
    - Fehlende `vplib_uid` wird erzeugt.
    - Ungültige vorhandene `vplib_uid` schlägt fehl.
    """
    path = normalize_package_path(relative_path)
    normalized_document = normalize_document_mapping(document)

    if path != MANIFEST_DOCUMENT_PATH:
        return normalized_document

    try:
        from .manifest_defaults import manifest_document_with_vplib_uid

        return manifest_document_with_vplib_uid(normalized_document)
    except Exception as exc:
        raise DocumentBundleError(f"Invalid manifest {MANIFEST_VPLIB_UID_FIELD!r}: {exc}") from exc


def validate_manifest_document_for_bundle(
    document: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    """Validiert das Manifest-Dokument inklusive `vplib_uid`."""
    try:
        from .manifest_defaults import validate_manifest_document

        return validate_manifest_document(document)
    except Exception as exc:
        return False, (f"Could not validate manifest document: {exc}",)


def get_vplib_uid_from_document(document: Mapping[str, Any] | None) -> str | None:
    """Liest eine gültige VPLIB-ID aus einem Manifest-Dokument."""
    if not isinstance(document, Mapping):
        return None

    try:
        from ..vplib_id_service import get_vplib_uid_from_mapping

        return get_vplib_uid_from_mapping(document)
    except Exception:
        return None


def get_vplib_uid_from_items(items: Iterable[DocumentBundleItem]) -> str | None:
    """Liest die VPLIB-ID aus den BundleItems."""
    for item in items or ():
        try:
            normalized = item.normalized()
            if normalized.relative_path != MANIFEST_DOCUMENT_PATH:
                continue

            uid = get_vplib_uid_from_document(normalized.document)
            if uid:
                return uid
        except Exception:
            continue

    return None


def extract_raw_vplib_uid_from_any(value: Any) -> Any | None:
    """Delegiert Roh-ID-Extraktion an manifest_defaults, falls verfügbar."""
    try:
        from .manifest_defaults import extract_raw_vplib_uid_from_any as extract

        return extract(value)
    except Exception:
        return None


def normalize_document_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert Dokumentpayload JSON-kompatibel."""
    if not isinstance(value, Mapping):
        raise DocumentBundleError("document must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
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


@lru_cache(maxsize=128)
def parse_bundle_source_value(value: Any) -> str:
    """Parst DocumentBundleSource."""
    try:
        if isinstance(value, DocumentBundleSource):
            return value.value

        raw = normalize_enum_key(value)
        return DocumentBundleSource(raw).value
    except Exception as exc:
        raise DocumentBundleError(f"Invalid document bundle source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_document_kind_value(value: Any) -> str:
    """Parst DocumentKind."""
    try:
        if isinstance(value, DocumentKind):
            return value.value

        raw = normalize_enum_key(value)
        return DocumentKind(raw).value
    except Exception as exc:
        raise DocumentBundleError(f"Invalid document kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_document_requirement_value(value: Any) -> str:
    """Parst DocumentRequirement."""
    try:
        if isinstance(value, DocumentRequirement):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "required": DocumentRequirement.REQUIRED.value,
            "mandatory": DocumentRequirement.REQUIRED.value,
            "optional": DocumentRequirement.OPTIONAL.value,
            "generated": DocumentRequirement.GENERATED.value,
            "auto": DocumentRequirement.GENERATED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return DocumentRequirement(raw).value
    except Exception as exc:
        raise DocumentBundleError(f"Invalid document requirement {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise DocumentBundleError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"Invalid enum value {value!r}.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise DocumentBundleError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def find_duplicates(values: Iterable[Any]) -> tuple[str, ...]:
    """Findet doppelte Werte."""
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned:
            continue
        if cleaned in seen:
            duplicates.add(cleaned)
        seen.add(cleaned)

    return tuple(sorted(duplicates))


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise DocumentBundleError(f"{field_name} is required.")

        return cleaned
    except DocumentBundleError:
        raise
    except Exception as exc:
        raise DocumentBundleError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_document_bundle_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_bundle_source_value.cache_clear()
    parse_document_kind_value.cache_clear()
    parse_document_requirement_value.cache_clear()


__all__ = [
    "CORE_MODULES",
    "DEFAULT_INCLUDE_OPTIONAL",
    "DOCUMENT_BUNDLE_SCHEMA_VERSION",
    "MANIFEST_DOCUMENT_PATH",
    "MANIFEST_VPLIB_UID_FIELD",
    "MODULES_DOCUMENT_PATH",
    "ROOT_DOCUMENTS",
    "DocumentBundle",
    "DocumentBundleError",
    "DocumentBundleItem",
    "DocumentBundleOptions",
    "DocumentBundleSource",
    "DocumentKind",
    "DocumentRequirement",
    "build_document_bundle_from_components",
    "build_document_bundle_from_context",
    "build_document_bundle_from_create_request",
    "build_document_bundle_from_creation_plan",
    "bundle_items_from_documents",
    "clean_optional_string",
    "clean_required_string",
    "clear_document_bundle_caches",
    "dedupe_bundle_items",
    "ensure_bundle_items_manifest_vplib_uid",
    "extract_raw_vplib_uid_from_any",
    "filter_items_for_active_modules",
    "find_duplicates",
    "get_vplib_uid_from_document",
    "get_vplib_uid_from_items",
    "has_analysis_data",
    "has_calculation_data",
    "has_dynamic_data",
    "has_material_data",
    "infer_active_modules",
    "infer_module_from_path_safe",
    "infer_or_normalize_module_name",
    "merge_bundle_items",
    "module_document_items_from_context",
    "module_document_items_from_create_request",
    "module_order",
    "normalize_bundle_document_for_path",
    "normalize_create_request",
    "normalize_document_mapping",
    "normalize_enum_key",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_module_name",
    "normalize_module_tuple",
    "normalize_options",
    "normalize_package_path",
    "parse_bundle_source_value",
    "parse_document_kind_value",
    "parse_document_requirement_value",
    "requirement_for_path",
    "requirement_order",
    "root_document_items_from_context_and_module_plan",
    "root_document_items_from_create_request",
    "should_include_module",
    "sort_bundle_items",
    "stronger_requirement",
    "validate_manifest_document_for_bundle",
]