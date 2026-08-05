# services/vectoplan-library/src/services/library_create_variant_payload_service.py
"""
Create Variant Payload Service.

Diese Datei normalisiert Payloads aus der `/create`-Route, bevor daraus
VPLIB-Dokumente, Package-Pläne, Downloads, gespeicherte Source-Packages oder
persistente Creative-Library-Drafts erzeugt werden.

Rolle dieser Datei:

    /create frontend payload
    -> normalize_create_variant_payload(...)
    -> stabiler Payload für VPLIB defaults / creators / validators

Wichtig für die VPLIB-ID-Architektur:
- `vplib_uid` entsteht beim Erstellen eines neuen .vplib-Packages.
- Wenn der Payload bereits eine gültige `vplib_uid` enthält, wird sie behalten.
- Wenn keine `vplib_uid` vorhanden ist, wird eine neue erzeugt.
- Wenn eine ungültige `vplib_uid` vorhanden ist, wird sie nicht still ersetzt.
- Die Datenbank erzeugt später keine eigene fachliche Block-ID.
- Die Datenbank übernimmt später nur die validierte `vplib_uid`.

Wichtig für die Variant Runtime:
- `definition_variants_json` wird robust aus JSON-String, Liste oder Mapping normalisiert.
- `default_variant_id` wird stabil bestimmt.
- `definition_values` wird robust aus JSON-String oder Mapping normalisiert.
- `additional_field_keys` wird robust aus JSON-String, Liste oder CSV-String normalisiert.
- Varianten bekommen stabile `variant_id`-Werte.
- Family Profile und Variant Profile werden als Backend-Definitions-IDs durchgereicht.
- Upload-/Dokument-/Asset-Metadaten werden für Draft-Services normalisiert.
- Der Service erzeugt keine Dateien und spricht keine Datenbank an.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Iterable, Mapping, MutableMapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION: Final[str] = "library.create_variant_payload.v3"
CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT: Final[str] = "library-create-variant-payload-service"

VPLIB_UID_FIELD: Final[str] = "vplib_uid"

NORMALIZATION_REPORT_FIELD: Final[str] = "_vplib_create_normalization"

DEFAULT_VARIANT_ID: Final[str] = "default"
DEFAULT_VARIANT_LABEL: Final[str] = "Standard"


STARTER_OBJECT_KIND: Final[str] = "cell_block"
STARTER_FAMILY_PROFILE_ID: Final[str] = "simple_cell_block"
STARTER_VARIANT_PROFILE_ID: Final[str] = "simple_cell_block.v1"
STARTER_FAMILY_NAME: Final[str] = "Simple Cell Block"
STARTER_PRIMITIVE_SHAPE: Final[str] = "block"

STARTER_TAXONOMY: Final[Mapping[str, str]] = {
    "domain": "hochbau",
    "category": "bloecke",
    "subcategory": "basis",
}

STARTER_DIMENSIONS_MM: Final[Mapping[str, int]] = {
    "dimensions.width_mm": 1000,
    "dimensions.height_mm": 1000,
    "dimensions.depth_mm": 1000,
}

STARTER_REQUIRED_VALUE_KEYS: Final[tuple[str, ...]] = (
    "variant.variant_id",
    "variant.label",
    "dimensions.width_mm",
    "dimensions.height_mm",
    "dimensions.depth_mm",
)

STARTER_FAMILY_PROFILE_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "",
        "simple_cell_block",
        "simple_cellblock",
        "cell_block",
        "cellblock",
        "starter_cell_block",
    }
)

STARTER_VARIANT_PROFILE_ALIASES: Final[frozenset[str]] = frozenset(
    {
        "",
        "simple_cell_block.v1",
        "simple_cell_block_v1",
        "simple_cell_block",
        "simple_block",
        "basic_block",
        "basisblock",
        "basic_stone_block",
        "starter_cell_block",
    }
)

SUPPORTED_GEOMETRY_UNITS: Final[frozenset[str]] = frozenset({"m", "cm", "mm"})

UPLOAD_CONTRACT_FIELDS: Final[tuple[tuple[str, str, str], ...]] = (
    ("geometry_model", "geometry_model_uploads", "geometryModelUploads"),
    (
        "technical_documents",
        "technical_document_uploads",
        "technicalDocumentUploads",
    ),
    (
        "variant_documents",
        "variant_document_uploads",
        "variantDocumentUploads",
    ),
)

PAYLOAD_FINGERPRINT_IGNORED_KEYS: Final[frozenset[str]] = frozenset(
    {
        VPLIB_UID_FIELD,
        "vplibUid",
        "vplib_uid_v1",
        NORMALIZATION_REPORT_FIELD,
        "_create_payload_fingerprint",
        "_create_payload_schema_version",
        "_create_payload_component",
        "workflow_action",
        "client_action",
        "clientAction",
        "action",
    }
)

SAFE_VARIANT_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_FIELD_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

VPLIB_UID_KEYS: Final[tuple[str, ...]] = (
    "vplib_uid",
    "vplibUid",
    "vplib_uid_v1",
)

DEFINITION_VARIANTS_KEYS: Final[tuple[str, ...]] = (
    "definition_variants_json",
    "definitionVariantsJson",
    "definition_variants",
    "definitionVariants",
    "variants_json",
    "variantsJson",
    "variants",
)

DEFAULT_VARIANT_ID_KEYS: Final[tuple[str, ...]] = (
    "default_variant_id",
    "defaultVariantId",
    "default_variant",
    "defaultVariant",
)

DEFINITION_VALUES_KEYS: Final[tuple[str, ...]] = (
    "definition_values",
    "definitionValues",
    "values",
    "variable_values",
    "variableValues",
)

ADDITIONAL_FIELD_KEYS_KEYS: Final[tuple[str, ...]] = (
    "additional_field_keys",
    "additionalFieldKeys",
    "additional_fields",
    "additionalFields",
    "extra_field_keys",
    "extraFieldKeys",
)

FAMILY_PROFILE_ID_KEYS: Final[tuple[str, ...]] = (
    "family_profile_id",
    "familyProfileId",
    "profile_key",
    "profileKey",
)

VARIANT_PROFILE_ID_KEYS: Final[tuple[str, ...]] = (
    "variant_profile_id",
    "variantProfileId",
)

VARIANT_ID_KEYS: Final[tuple[str, ...]] = (
    "variant_id",
    "variantId",
    "id",
    "slug",
    "key",
)

VARIANT_LABEL_KEYS: Final[tuple[str, ...]] = (
    "label",
    "name",
    "title",
    "variant_label",
    "variantLabel",
)

VARIANT_DESCRIPTION_KEYS: Final[tuple[str, ...]] = (
    "description",
    "desc",
    "text",
)

VARIANT_DEFAULT_KEYS: Final[tuple[str, ...]] = (
    "is_default",
    "isDefault",
    "default",
    "is_selected_default",
    "isSelectedDefault",
)

TAXONOMY_DOMAIN_KEYS: Final[tuple[str, ...]] = (
    "domain",
    "domain_id",
    "domainId",
    "reiter",
)

TAXONOMY_CATEGORY_KEYS: Final[tuple[str, ...]] = (
    "category",
    "category_id",
    "categoryId",
    "kategorie",
)

TAXONOMY_SUBCATEGORY_KEYS: Final[tuple[str, ...]] = (
    "subcategory",
    "subcategory_id",
    "subcategoryId",
    "sub_category",
    "subCategory",
    "unterkategorie",
)

OBJECT_KIND_KEYS: Final[tuple[str, ...]] = (
    "object_kind",
    "objectKind",
    "object_class",
    "objectClass",
)

MATERIAL_CLASS_KEYS: Final[tuple[str, ...]] = (
    "material_class",
    "materialClass",
)

MATERIAL_CLASSES_KEYS: Final[tuple[str, ...]] = (
    "material_classes",
    "materialClasses",
)

UNIT_KEYS: Final[tuple[str, ...]] = (
    "unit",
    "geometry_unit",
    "geometryUnit",
)

DOCUMENTS_KEYS: Final[tuple[str, ...]] = (
    "documents",
    "documents_json",
    "documentsJson",
    "uploaded_documents",
    "uploadedDocuments",
)

ASSETS_KEYS: Final[tuple[str, ...]] = (
    "assets",
    "assets_json",
    "assetsJson",
    "uploaded_assets",
    "uploadedAssets",
)

VARIABLES_KEYS: Final[tuple[str, ...]] = (
    "variables",
    "variables_json",
    "variablesJson",
)

INDEXED_ROW_PREFIXES: Final[tuple[str, ...]] = (
    "variants",
    "variables",
    "documents",
    "assets",
    "validation_issues",
    "technical_profile",
    "host_rules",
)

NESTED_OBJECT_PREFIXES: Final[tuple[str, ...]] = (
    "taxonomy",
    "classification",
    "identity",
    "family",
    "geometry",
    "dimensions",
    "technical",
    "generator",
    "manifest",
    "modules",
    "metadata",
)

JSON_KEY_ALIASES: Final[Mapping[str, str]] = {
    "definition_variants_json": "definition_variants_json",
    "definitionVariantsJson": "definition_variants_json",
    "variants_json": "variants",
    "variantsJson": "variants",
    "definition_values_json": "definition_values",
    "definitionValuesJson": "definition_values",
    "variables_json": "variables",
    "variablesJson": "variables",
    "documents_json": "documents",
    "documentsJson": "documents",
    "assets_json": "assets",
    "assetsJson": "assets",
    "taxonomy_json": "taxonomy",
    "taxonomyJson": "taxonomy",
    "classification_json": "classification",
    "classificationJson": "classification",
    "family_json": "family",
    "familyJson": "family",
    "geometry_json": "geometry",
    "geometryJson": "geometry",
    "metadata_json": "metadata",
    "metadataJson": "metadata",
    "geometry_model_uploads_json": "geometry_model_uploads",
    "geometryModelUploadsJson": "geometry_model_uploads",
    "technical_document_uploads_json": "technical_document_uploads",
    "technicalDocumentUploadsJson": "technical_document_uploads",
    "variant_document_uploads_json": "variant_document_uploads",
    "variantDocumentUploadsJson": "variant_document_uploads",
    "uploads_json": "uploads",
    "uploadsJson": "uploads",
    "draft_json": "__merge__",
    "draftJson": "__merge__",
}

RESERVED_VARIANT_KEYS: Final[set[str]] = {
    *VARIANT_ID_KEYS,
    *VARIANT_LABEL_KEYS,
    *VARIANT_DESCRIPTION_KEYS,
    *VARIANT_DEFAULT_KEYS,
    *FAMILY_PROFILE_ID_KEYS,
    *VARIANT_PROFILE_ID_KEYS,
    *DEFINITION_VALUES_KEYS,
    *ADDITIONAL_FIELD_KEYS_KEYS,
    "metadata",
    "status",
    "enabled",
    "active",
    "visible",
    "sort_order",
    "sortOrder",
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreateVariantPayloadError(ValueError):
    """Wird ausgelöst, wenn ein Create-Variant-Payload nicht normalisiert werden kann."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PayloadNormalizationMessage:
    """Ein Hinweis, eine Warnung oder ein Fehler aus der Payload-Normalisierung."""

    level: str
    code: str
    message: str
    field_path: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PayloadNormalizationMessage":
        return PayloadNormalizationMessage(
            level=normalize_message_level(self.level),
            code=clean_required_string(self.code, "code"),
            message=clean_required_string(self.message, "message"),
            field_path=clean_optional_string(self.field_path),
            details=normalize_json_mapping(self.details),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "level": normalized.level,
            "code": normalized.code,
            "message": normalized.message,
            "field_path": normalized.field_path,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class NormalizedVariant:
    """Normalisierte Variant-Struktur für den Create-Payload."""

    variant_id: str
    label: str
    description: str | None = None
    is_default: bool = False
    family_profile_id: str | None = None
    variant_profile_id: str | None = None
    definition_values: Mapping[str, Any] = field(default_factory=dict)
    additional_field_keys: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_index: int | None = None
    sort_order: int = 0
    active: bool = True
    visible: bool = True

    def normalized(self) -> "NormalizedVariant":
        variant_id = normalize_variant_id(self.variant_id, field_name="variant_id")
        label = clean_optional_string(self.label) or label_from_variant_id(variant_id)

        return NormalizedVariant(
            variant_id=variant_id,
            label=label,
            description=clean_optional_string(self.description),
            is_default=bool(self.is_default),
            family_profile_id=clean_optional_string(self.family_profile_id),
            variant_profile_id=clean_optional_string(self.variant_profile_id),
            definition_values=normalize_json_mapping(self.definition_values),
            additional_field_keys=normalize_additional_field_keys(self.additional_field_keys),
            metadata=normalize_json_mapping(self.metadata),
            source_index=normalize_optional_non_negative_int(self.source_index, "source_index"),
            sort_order=normalize_non_negative_int(self.sort_order, "sort_order"),
            active=bool(self.active),
            visible=bool(self.visible),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        definition_values = dict(normalized.definition_values)
        definition_values_json = compact_json(definition_values)
        additional_field_keys = list(normalized.additional_field_keys)

        return {
            "variant_id": normalized.variant_id,
            "variantId": normalized.variant_id,
            "variant_key": normalized.variant_id,
            "variantKey": normalized.variant_id,
            "label": normalized.label,
            "name": normalized.label,
            "description": normalized.description,
            "is_default": normalized.is_default,
            "isDefault": normalized.is_default,
            "family_profile_id": normalized.family_profile_id,
            "familyProfileId": normalized.family_profile_id,
            "variant_profile_id": normalized.variant_profile_id,
            "variantProfileId": normalized.variant_profile_id,
            "definition_values": definition_values,
            "definitionValues": definition_values,
            "definition_values_json": definition_values_json,
            "definitionValuesJson": definition_values_json,
            "additional_field_keys": additional_field_keys,
            "additionalFieldKeys": additional_field_keys,
            "metadata": dict(normalized.metadata),
            "source_index": normalized.source_index,
            "sourceIndex": normalized.source_index,
            "sort_order": normalized.sort_order,
            "sortOrder": normalized.sort_order,
            "active": normalized.active,
            "visible": normalized.visible,
        }


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    """Normalisierte Dokument-/Upload-Metadaten für Create/Draft."""

    document_type: str | None = None
    document_kind: str | None = None
    field_key: str | None = None
    title: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    library_file_id: int | None = None
    file_version_id: int | None = None
    file_uid: str | None = None
    storage_path: str | None = None
    url: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_index: int | None = None

    def normalized(self) -> "NormalizedDocument":
        return NormalizedDocument(
            document_type=clean_optional_string(self.document_type),
            document_kind=clean_optional_string(self.document_kind),
            field_key=normalize_field_key(self.field_key),
            title=clean_optional_string(self.title),
            filename=clean_optional_string(self.filename),
            mime_type=clean_optional_string(self.mime_type),
            library_file_id=normalize_optional_positive_int(self.library_file_id, "library_file_id"),
            file_version_id=normalize_optional_positive_int(self.file_version_id, "file_version_id"),
            file_uid=clean_optional_string(self.file_uid),
            storage_path=clean_optional_string(self.storage_path),
            url=clean_optional_string(self.url),
            metadata=normalize_json_mapping(self.metadata),
            source_index=normalize_optional_non_negative_int(self.source_index, "source_index"),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "document_type": normalized.document_type,
            "document_kind": normalized.document_kind,
            "field_key": normalized.field_key,
            "title": normalized.title,
            "filename": normalized.filename,
            "mime_type": normalized.mime_type,
            "library_file_id": normalized.library_file_id,
            "file_version_id": normalized.file_version_id,
            "file_uid": normalized.file_uid,
            "storage_path": normalized.storage_path,
            "url": normalized.url,
            "metadata": dict(normalized.metadata),
            "source_index": normalized.source_index,
        }


@dataclass(frozen=True, slots=True)
class NormalizedAsset:
    """Normalisierte Asset-Metadaten für Create/Draft."""

    asset_kind: str | None = None
    role: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    library_file_id: int | None = None
    file_version_id: int | None = None
    file_uid: str | None = None
    source_path: str | None = None
    storage_path: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    source_index: int | None = None

    def normalized(self) -> "NormalizedAsset":
        return NormalizedAsset(
            asset_kind=clean_optional_string(self.asset_kind),
            role=clean_optional_string(self.role),
            filename=clean_optional_string(self.filename),
            mime_type=clean_optional_string(self.mime_type),
            size_bytes=normalize_optional_non_negative_int(self.size_bytes, "size_bytes"),
            sha256=clean_optional_string(self.sha256),
            library_file_id=normalize_optional_positive_int(self.library_file_id, "library_file_id"),
            file_version_id=normalize_optional_positive_int(self.file_version_id, "file_version_id"),
            file_uid=clean_optional_string(self.file_uid),
            source_path=clean_optional_string(self.source_path),
            storage_path=clean_optional_string(self.storage_path),
            metadata=normalize_json_mapping(self.metadata),
            source_index=normalize_optional_non_negative_int(self.source_index, "source_index"),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "asset_kind": normalized.asset_kind,
            "role": normalized.role,
            "filename": normalized.filename,
            "mime_type": normalized.mime_type,
            "size_bytes": normalized.size_bytes,
            "sha256": normalized.sha256,
            "library_file_id": normalized.library_file_id,
            "file_version_id": normalized.file_version_id,
            "file_uid": normalized.file_uid,
            "source_path": normalized.source_path,
            "storage_path": normalized.storage_path,
            "metadata": dict(normalized.metadata),
            "source_index": normalized.source_index,
        }


@dataclass(frozen=True, slots=True)
class CreateVariantPayloadNormalizationResult:
    """Strukturiertes Ergebnis der Payload-Normalisierung."""

    payload: Mapping[str, Any]
    messages: tuple[PayloadNormalizationMessage, ...] = field(default_factory=tuple)
    schema_version: str = CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION

    def normalized(self) -> "CreateVariantPayloadNormalizationResult":
        return CreateVariantPayloadNormalizationResult(
            payload=normalize_json_mapping(self.payload),
            messages=tuple(message.normalized() for message in self.messages or ()),
            schema_version=self.schema_version or CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION,
        )

    @property
    def ok(self) -> bool:
        return not any(message.normalized().level == "error" for message in self.messages or ())

    @property
    def errors(self) -> tuple[PayloadNormalizationMessage, ...]:
        return tuple(
            message.normalized()
            for message in self.messages or ()
            if message.normalized().level == "error"
        )

    @property
    def warnings(self) -> tuple[PayloadNormalizationMessage, ...]:
        return tuple(
            message.normalized()
            for message in self.messages or ()
            if message.normalized().level == "warning"
        )

    @property
    def vplib_uid(self) -> str | None:
        return normalize_vplib_uid_safe(self.normalized().payload.get(VPLIB_UID_FIELD))

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "component": CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT,
            "ok": normalized.ok,
            "vplib_uid": normalized.vplib_uid,
            "message_count": len(normalized.messages),
            "error_count": len(normalized.errors),
            "warning_count": len(normalized.warnings),
            "messages": [message.to_dict() for message in normalized.messages],
            "payload": dict(normalized.payload),
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_create_variant_payload(
    payload: Mapping[str, Any] | MutableMapping[str, Any] | None,
    *,
    ensure_uid: bool = True,
    existing_uids: Iterable[Any] | None = None,
    overwrite_invalid_uid: bool = False,
    include_report: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    """
    Normalisiert einen `/create`-Payload.

    Args:
        payload:
            Rohpayload aus FormData, JSON-Body oder internem Service.
        ensure_uid:
            Wenn True, wird fehlende `vplib_uid` erzeugt.
        existing_uids:
            Optional bekannte IDs für zusätzliche lokale Kollisionsvermeidung.
        overwrite_invalid_uid:
            Wenn True, darf eine vorhandene ungültige ID ersetzt werden.
            Standard ist False, damit kaputte IDs sichtbar fehlschlagen.
        include_report:
            Wenn True, wird ein Report unter `_vplib_create_normalization`
            in den Payload geschrieben.
        strict:
            Wenn True, wirft die Funktion bei Fehlern.
            Wenn False, wird der bestmögliche Payload mit Report zurückgegeben.

    Returns:
        dict[str, Any]
    """
    result = normalize_create_variant_payload_result(
        payload,
        ensure_uid=ensure_uid,
        existing_uids=existing_uids,
        overwrite_invalid_uid=overwrite_invalid_uid,
        strict=strict,
    ).normalized()

    normalized_payload = dict(result.payload)

    if include_report:
        normalized_payload[NORMALIZATION_REPORT_FIELD] = {
            "schema_version": result.schema_version,
            "component": CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT,
            "ok": result.ok,
            "vplib_uid": result.vplib_uid,
            "message_count": len(result.messages),
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "messages": [message.to_dict() for message in result.messages],
            "normalized_at": utc_now_iso(),
        }

    if strict and not result.ok:
        raise CreateVariantPayloadError(
            "; ".join(message.message for message in result.errors)
            or "Create variant payload normalization failed."
        )

    return normalized_payload


def normalize_create_variant_payload_result(
    payload: Mapping[str, Any] | MutableMapping[str, Any] | None,
    *,
    ensure_uid: bool = True,
    existing_uids: Iterable[Any] | None = None,
    overwrite_invalid_uid: bool = False,
    strict: bool = True,
) -> CreateVariantPayloadNormalizationResult:
    """
    Normalize a ``/create`` payload and return a structured report.

    The function materializes the starter contract before variants are
    normalized. This guarantees that validation, package planning and download
    receive the same canonical object kind, profile IDs, dimensions, uploads and
    default variant.
    """
    messages: list[PayloadNormalizationMessage] = []

    try:
        normalized_payload = normalize_payload_mapping(payload)
        normalized_payload = materialize_starter_payload(
            normalized_payload,
            messages=messages,
        )

        try:
            uid = ensure_create_payload_vplib_uid(
                normalized_payload,
                ensure_uid=ensure_uid,
                existing_uids=existing_uids,
                overwrite_invalid_uid=overwrite_invalid_uid,
            )
            if uid:
                normalized_payload[VPLIB_UID_FIELD] = uid
                normalized_payload["vplibUid"] = uid
        except Exception as exc:
            messages.append(
                normalization_message(
                    level="error",
                    code="CREATE_PAYLOAD_INVALID_VPLIB_UID",
                    message=str(exc),
                    field_path=VPLIB_UID_FIELD,
                )
            )
            if strict:
                raise

        taxonomy_payload = normalize_taxonomy_payload(normalized_payload)
        normalized_payload.update(taxonomy_payload)
        normalized_payload["taxonomy_path"] = normalize_taxonomy_path(
            first_present_value(
                normalized_payload,
                ("taxonomy_path", "taxonomyPath"),
            )
            or "/".join(
                str(normalized_payload.get(key) or "")
                for key in ("domain", "category", "subcategory")
            )
        )
        normalized_payload["taxonomyPath"] = normalized_payload["taxonomy_path"]

        common_definition_values = normalize_definition_values(
            first_present_value(normalized_payload, DEFINITION_VALUES_KEYS)
        )
        common_definition_values = materialize_starter_definition_values(
            normalized_payload,
            common_definition_values,
        )

        additional_field_keys = normalize_additional_field_keys(
            first_present_value(normalized_payload, ADDITIONAL_FIELD_KEYS_KEYS)
        )
        family_profile_id = canonicalize_family_profile_id(
            first_present_value(normalized_payload, FAMILY_PROFILE_ID_KEYS)
        )
        variant_profile_id = canonicalize_variant_profile_id(
            first_present_value(normalized_payload, VARIANT_PROFILE_ID_KEYS)
        )

        if family_profile_id:
            normalized_payload["family_profile_id"] = family_profile_id
            normalized_payload["familyProfileId"] = family_profile_id

        if variant_profile_id:
            normalized_payload["variant_profile_id"] = variant_profile_id
            normalized_payload["variantProfileId"] = variant_profile_id

        raw_variants = first_present_value(normalized_payload, DEFINITION_VARIANTS_KEYS)
        variants = normalize_definition_variants_json(
            raw_variants,
            common_definition_values=common_definition_values,
            additional_field_keys=additional_field_keys,
            family_profile_id=family_profile_id,
            variant_profile_id=variant_profile_id,
        )

        default_variant_id = resolve_default_variant_id(
            explicit_default_variant_id=first_present_value(
                normalized_payload,
                DEFAULT_VARIANT_ID_KEYS,
            ),
            variants=variants,
        )
        variants = mark_default_variant(
            variants,
            default_variant_id=default_variant_id,
        )

        variant_payloads = materialize_variant_payloads(
            variants,
            normalized_payload,
        )
        default_variant_id = resolve_default_variant_id_from_payloads(
            variant_payloads,
            explicit_default_variant_id=default_variant_id,
        )
        variant_payloads = enforce_single_default_variant_payload(
            variant_payloads,
            default_variant_id=default_variant_id,
        )

        normalized_documents = normalize_documents_payload(
            first_present_value(normalized_payload, DOCUMENTS_KEYS)
        )
        normalized_assets = normalize_assets_payload(
            first_present_value(normalized_payload, ASSETS_KEYS)
        )
        normalized_variables = normalize_variables_payload(
            first_present_value(normalized_payload, VARIABLES_KEYS)
        )

        normalized_payload["definition_values"] = common_definition_values
        normalized_payload["definitionValues"] = common_definition_values
        normalized_payload["definition_values_json"] = compact_json(
            common_definition_values
        )
        normalized_payload["definitionValuesJson"] = normalized_payload[
            "definition_values_json"
        ]
        normalized_payload["additional_field_keys"] = list(additional_field_keys)
        normalized_payload["additionalFieldKeys"] = list(additional_field_keys)

        normalized_payload["definition_variants"] = variant_payloads
        normalized_payload["definitionVariants"] = variant_payloads
        normalized_payload["variants"] = variant_payloads
        normalized_payload["definition_variants_json"] = compact_json(
            variant_payloads
        )
        normalized_payload["definitionVariantsJson"] = normalized_payload[
            "definition_variants_json"
        ]
        normalized_payload["default_variant_id"] = default_variant_id
        normalized_payload["defaultVariantId"] = default_variant_id

        normalized_payload["documents"] = [
            document.to_dict() for document in normalized_documents
        ]
        normalized_payload["assets"] = [
            asset.to_dict() for asset in normalized_assets
        ]
        normalized_payload["variables"] = normalized_variables

        normalized_payload = normalize_upload_contracts(normalized_payload)

        normalized_payload["variant_count"] = len(variant_payloads)
        normalized_payload["variantCount"] = len(variant_payloads)
        normalized_payload["has_variants"] = bool(variant_payloads)
        normalized_payload["hasVariants"] = bool(variant_payloads)
        normalized_payload[
            "_create_payload_schema_version"
        ] = CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION
        normalized_payload[
            "_create_payload_component"
        ] = CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT
        normalized_payload["_create_payload_fingerprint"] = compute_payload_fingerprint(
            normalized_payload
        )

        validation = validate_create_variant_payload(normalized_payload)
        for issue in validation["errors"]:
            messages.append(
                normalization_message(
                    level="error",
                    code=str(issue.get("code") or "CREATE_PAYLOAD_INVALID"),
                    message=str(issue.get("message") or "Create payload is invalid."),
                    field_path=clean_optional_string(issue.get("field")),
                    details=normalize_json_mapping(
                        issue.get("details")
                        if isinstance(issue.get("details"), Mapping)
                        else {}
                    ),
                )
            )

        for issue in validation["warnings"]:
            messages.append(
                normalization_message(
                    level="warning",
                    code=str(issue.get("code") or "CREATE_PAYLOAD_WARNING"),
                    message=str(issue.get("message") or "Create payload warning."),
                    field_path=clean_optional_string(issue.get("field")),
                    details=normalize_json_mapping(
                        issue.get("details")
                        if isinstance(issue.get("details"), Mapping)
                        else {}
                    ),
                )
            )

        messages.append(
            normalization_message(
                level="info",
                code="CREATE_PAYLOAD_NORMALIZED",
                message="Create variant payload normalized.",
                details={
                    "vplib_uid": normalized_payload.get(VPLIB_UID_FIELD),
                    "variant_count": len(variant_payloads),
                    "default_variant_id": default_variant_id,
                    "family_profile_id": family_profile_id,
                    "variant_profile_id": variant_profile_id,
                    "object_kind": normalized_payload.get("object_kind"),
                    "starter_contract": normalized_payload.get(
                        "_starter_contract",
                        {},
                    ),
                    "additional_field_key_count": len(additional_field_keys),
                    "document_count": len(normalized_documents),
                    "asset_count": len(normalized_assets),
                    "variable_count": len(normalized_variables),
                    "payload_fingerprint": normalized_payload.get(
                        "_create_payload_fingerprint"
                    ),
                },
            )
        )

        result = CreateVariantPayloadNormalizationResult(
            payload=normalized_payload,
            messages=tuple(messages),
        ).normalized()

        if strict and not result.ok:
            raise CreateVariantPayloadError(
                "; ".join(message.message for message in result.errors)
                or "Create variant payload normalization failed."
            )

        return result

    except Exception as exc:
        if not messages:
            messages.append(
                normalization_message(
                    level="error",
                    code="CREATE_PAYLOAD_NORMALIZATION_FAILED",
                    message=str(exc),
                )
            )

        if strict:
            raise CreateVariantPayloadError(
                "; ".join(
                    message.message
                    for message in messages
                    if message.level == "error"
                )
                or str(exc)
            ) from exc

        fallback_payload = normalize_payload_mapping(payload, strict=False)
        fallback_payload[NORMALIZATION_REPORT_FIELD] = {
            "schema_version": CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION,
            "component": CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT,
            "ok": False,
            "messages": [message.to_dict() for message in messages],
            "normalized_at": utc_now_iso(),
        }

        return CreateVariantPayloadNormalizationResult(
            payload=fallback_payload,
            messages=tuple(messages),
        ).normalized()


# ---------------------------------------------------------------------------
# Starter contract / payload validation
# ---------------------------------------------------------------------------


def canonicalize_family_profile_id(value: Any) -> str | None:
    """Return the canonical starter family profile ID for known aliases."""
    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    normalized = normalize_profile_identifier(cleaned)
    if normalized in STARTER_FAMILY_PROFILE_ALIASES:
        return STARTER_FAMILY_PROFILE_ID
    return cleaned


def canonicalize_variant_profile_id(value: Any) -> str | None:
    """Return the canonical starter variant profile ID for known aliases."""
    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    normalized = normalize_profile_identifier(cleaned)
    if normalized in STARTER_VARIANT_PROFILE_ALIASES:
        return STARTER_VARIANT_PROFILE_ID
    return cleaned


def normalize_profile_identifier(value: Any) -> str:
    """Normalize a profile ID without removing its version separator."""
    cleaned = str(value or "").replace("\x00", "").strip().lower()
    cleaned = cleaned.replace("-", "_").replace(" ", "")
    cleaned = re.sub(r"[^a-z0-9._]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned.strip("_")


def is_starter_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether the payload belongs to the minimal starter contract."""
    object_kind = normalize_slug_token(
        first_present_value(payload, OBJECT_KIND_KEYS) or STARTER_OBJECT_KIND
    )
    family_profile_id = canonicalize_family_profile_id(
        first_present_value(payload, FAMILY_PROFILE_ID_KEYS)
    )
    variant_profile_id = canonicalize_variant_profile_id(
        first_present_value(payload, VARIANT_PROFILE_ID_KEYS)
    )

    return (
        object_kind == STARTER_OBJECT_KIND
        and family_profile_id in {None, STARTER_FAMILY_PROFILE_ID}
        and variant_profile_id in {None, STARTER_VARIANT_PROFILE_ID}
    )


def materialize_starter_payload(
    payload: Mapping[str, Any],
    *,
    messages: list[PayloadNormalizationMessage] | None = None,
) -> dict[str, Any]:
    """
    Materialize canonical values for the first downloadable ``cell_block``.

    Existing valid values are preserved where possible. Profile aliases are
    canonicalized and optional upload/document requirements remain optional.
    """
    data = normalize_json_mapping(payload)
    object_kind = normalize_slug_token(
        first_present_value(data, OBJECT_KIND_KEYS) or STARTER_OBJECT_KIND
    )
    family_profile_id = canonicalize_family_profile_id(
        first_present_value(data, FAMILY_PROFILE_ID_KEYS)
    )
    variant_profile_id = canonicalize_variant_profile_id(
        first_present_value(data, VARIANT_PROFILE_ID_KEYS)
    )

    starter_requested = (
        object_kind == STARTER_OBJECT_KIND
        and family_profile_id in {None, STARTER_FAMILY_PROFILE_ID}
        and variant_profile_id in {None, STARTER_VARIANT_PROFILE_ID}
    )

    data["object_kind"] = object_kind
    data["objectKind"] = object_kind

    if family_profile_id:
        data["family_profile_id"] = family_profile_id
        data["familyProfileId"] = family_profile_id

    if variant_profile_id:
        data["variant_profile_id"] = variant_profile_id
        data["variantProfileId"] = variant_profile_id

    if not starter_requested:
        return data

    data["object_kind"] = STARTER_OBJECT_KIND
    data["objectKind"] = STARTER_OBJECT_KIND
    data["family_profile_id"] = STARTER_FAMILY_PROFILE_ID
    data["familyProfileId"] = STARTER_FAMILY_PROFILE_ID
    data["variant_profile_id"] = STARTER_VARIANT_PROFILE_ID
    data["variantProfileId"] = STARTER_VARIANT_PROFILE_ID

    family_name = clean_optional_string(
        first_present_value(
            data,
            ("family_name", "familyName", "name", "title"),
        )
    ) or STARTER_FAMILY_NAME
    data["family_name"] = family_name
    data["familyName"] = family_name

    family_description = clean_optional_string(
        first_present_value(
            data,
            ("family_description", "familyDescription", "description"),
        )
    )
    if family_description:
        data["family_description"] = family_description
        data["familyDescription"] = family_description

    for key, default_value in STARTER_TAXONOMY.items():
        data[key] = normalize_slug_token(data.get(key) or default_value)

    data["taxonomy_path"] = normalize_taxonomy_path(
        first_present_value(data, ("taxonomy_path", "taxonomyPath"))
        or "/".join(data[key] for key in ("domain", "category", "subcategory"))
    )
    data["taxonomyPath"] = data["taxonomy_path"]

    primitive_shape = normalize_slug_token(
        first_present_value(
            data,
            ("primitive_shape", "primitiveShape"),
        )
        or STARTER_PRIMITIVE_SHAPE
    )
    data["primitive_shape"] = primitive_shape or STARTER_PRIMITIVE_SHAPE
    data["primitiveShape"] = data["primitive_shape"]

    geometry_unit = normalize_geometry_unit(
        first_present_value(data, UNIT_KEYS) or "m"
    )
    dimensions_mm = normalize_dimensions_mm(
        data,
        default_dimensions=STARTER_DIMENSIONS_MM,
        geometry_unit=geometry_unit,
    )
    data["geometry_unit"] = geometry_unit
    data["geometryUnit"] = geometry_unit

    dimensions = normalize_json_mapping(
        data.get("dimensions")
        if isinstance(data.get("dimensions"), Mapping)
        else {}
    )
    for axis in ("width", "height", "depth"):
        mm_value = dimensions_mm[f"dimensions.{axis}_mm"]
        dimensions[f"{axis}_mm"] = mm_value
        data[f"{axis}_mm"] = mm_value
        data[f"dimensions_{axis}_mm"] = mm_value

        geometry_value = dimension_mm_to_geometry_value(
            mm_value,
            geometry_unit,
        )
        snake_key = f"geometry_{axis}"
        camel_key = f"geometry{axis.title()}"
        formatted = format_decimal(geometry_value)
        data[snake_key] = formatted
        data[camel_key] = formatted

    data["dimensions"] = dimensions

    editor_block = normalize_json_mapping(
        data.get("editor_block")
        if isinstance(data.get("editor_block"), Mapping)
        else {}
    )
    cells = normalize_json_mapping(
        editor_block.get("cells")
        if isinstance(editor_block.get("cells"), Mapping)
        else {}
    )

    for axis in ("x", "y", "z"):
        snake_key = f"editor_cells_{axis}"
        camel_key = f"editorCells{axis.upper()}"
        value = normalize_positive_int(
            first_present_value(data, (snake_key, camel_key))
            or cells.get(axis)
            or 1,
            default=1,
        )
        data[snake_key] = str(value)
        data[camel_key] = str(value)
        cells[axis] = value

    editor_block["cells"] = cells
    data["editor_block"] = editor_block
    data["editorBlock"] = editor_block

    data.setdefault("documents", [])
    data.setdefault("assets", [])
    data.setdefault("variables", [])
    data["documents_required"] = False
    data["documentsRequired"] = False
    data["requires_documents"] = False
    data["requiresDocuments"] = False
    data["requires_external_assets"] = False
    data["requiresExternalAssets"] = False
    data["manufacturer_mode"] = (
        clean_optional_string(data.get("manufacturer_mode")) or "optional"
    )
    data["manufacturerMode"] = data["manufacturer_mode"]

    data = normalize_upload_contracts(data)

    data["_starter_contract"] = {
        "requested": True,
        "ready": True,
        "object_kind": STARTER_OBJECT_KIND,
        "family_profile_id": STARTER_FAMILY_PROFILE_ID,
        "variant_profile_id": STARTER_VARIANT_PROFILE_ID,
        "default_variant_id": DEFAULT_VARIANT_ID,
        "dimensions_mm": {
            axis: dimensions_mm[f"dimensions.{axis}_mm"]
            for axis in ("width", "height", "depth")
        },
        "documents_required": False,
        "external_assets_required": False,
        "manufacturer_data_required": False,
    }

    if messages is not None:
        messages.append(
            normalization_message(
                level="info",
                code="CREATE_STARTER_CONTRACT_MATERIALIZED",
                message="Canonical simple cell block starter contract materialized.",
                details=data["_starter_contract"],
            )
        )

    return data


def materialize_starter_definition_values(
    payload: Mapping[str, Any],
    values: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge canonical starter defaults into top-level definition values."""
    result = normalize_json_mapping(values)
    if not is_starter_payload(payload):
        return result

    dimensions_mm = normalize_dimensions_mm(
        payload,
        default_dimensions=STARTER_DIMENSIONS_MM,
        geometry_unit=normalize_geometry_unit(
            first_present_value(payload, UNIT_KEYS) or "m"
        ),
    )
    result["variant.variant_id"] = (
        clean_optional_string(result.get("variant.variant_id"))
        or DEFAULT_VARIANT_ID
    )
    result["variant.label"] = (
        clean_optional_string(result.get("variant.label"))
        or DEFAULT_VARIANT_LABEL
    )
    result.setdefault(
        "variant.description",
        "Standardvariante für einen einfachen Rasterblock.",
    )

    for key, value in dimensions_mm.items():
        result[key] = value

    result.setdefault("material.type", "generic")
    result.setdefault("material.subtype", "generic_block")
    result.setdefault("material.color_hint", "#9CA3AF")
    return result


def materialize_variant_payloads(
    variants: Iterable[NormalizedVariant],
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Convert normalized variants into the canonical route-service shape."""
    starter = is_starter_payload(payload)
    family_profile_id = canonicalize_family_profile_id(
        first_present_value(payload, FAMILY_PROFILE_ID_KEYS)
    )
    variant_profile_id = canonicalize_variant_profile_id(
        first_present_value(payload, VARIANT_PROFILE_ID_KEYS)
    )
    object_kind = normalize_slug_token(
        first_present_value(payload, OBJECT_KIND_KEYS) or STARTER_OBJECT_KIND
    )
    dimensions_mm = normalize_dimensions_mm(
        payload,
        default_dimensions=STARTER_DIMENSIONS_MM if starter else {},
        geometry_unit=normalize_geometry_unit(
            first_present_value(payload, UNIT_KEYS) or "m"
        ),
    )

    result: list[dict[str, Any]] = []
    for index, variant in enumerate(variants or ()):
        item = variant.to_dict()
        variant_id = normalize_variant_id_or_fallback(
            item.get("variant_id"),
            fallback=DEFAULT_VARIANT_ID if index == 0 else f"variant_{index + 1}",
            index=index,
            used_ids={
                str(existing.get("variant_id"))
                for existing in result
                if existing.get("variant_id")
            },
        )
        label = clean_optional_string(item.get("label")) or (
            DEFAULT_VARIANT_LABEL
            if variant_id == DEFAULT_VARIANT_ID
            else label_from_variant_id(variant_id)
        )

        definition_values = normalize_definition_values(
            item.get("definition_values")
        )
        definition_values["variant.variant_id"] = variant_id
        definition_values["variant.label"] = label
        if starter:
            for key, value in dimensions_mm.items():
                definition_values.setdefault(key, value)

        additional_keys = list(
            normalize_additional_field_keys(
                item.get("additional_field_keys")
            )
        )

        item.update(
            {
                "variant_id": variant_id,
                "variantId": variant_id,
                "variant_key": variant_id,
                "variantKey": variant_id,
                "label": label,
                "name": label,
                "family_profile_id": family_profile_id,
                "familyProfileId": family_profile_id,
                "variant_profile_id": variant_profile_id,
                "variantProfileId": variant_profile_id,
                "object_kind": object_kind,
                "objectKind": object_kind,
                "definition_values": definition_values,
                "definitionValues": definition_values,
                "definition_values_json": compact_json(definition_values),
                "definitionValuesJson": compact_json(definition_values),
                "additional_field_keys": additional_keys,
                "additionalFieldKeys": additional_keys,
            }
        )
        result.append(item)

    if not result:
        definition_values = materialize_starter_definition_values(payload, {})
        result = [
            {
                "variant_id": DEFAULT_VARIANT_ID,
                "variantId": DEFAULT_VARIANT_ID,
                "variant_key": DEFAULT_VARIANT_ID,
                "variantKey": DEFAULT_VARIANT_ID,
                "label": DEFAULT_VARIANT_LABEL,
                "name": DEFAULT_VARIANT_LABEL,
                "description": "",
                "is_default": True,
                "isDefault": True,
                "family_profile_id": family_profile_id,
                "familyProfileId": family_profile_id,
                "variant_profile_id": variant_profile_id,
                "variantProfileId": variant_profile_id,
                "object_kind": object_kind,
                "objectKind": object_kind,
                "definition_values": definition_values,
                "definitionValues": definition_values,
                "definition_values_json": compact_json(definition_values),
                "definitionValuesJson": compact_json(definition_values),
                "additional_field_keys": [],
                "additionalFieldKeys": [],
                "source": (
                    "library_create_variant_payload_service.starter_default"
                ),
            }
        ]

    return result


def resolve_default_variant_id_from_payloads(
    variants: Sequence[Mapping[str, Any]],
    *,
    explicit_default_variant_id: Any = None,
) -> str:
    """Resolve a valid default ID from canonical variant mappings."""
    explicit = clean_optional_string(explicit_default_variant_id)
    if explicit:
        try:
            explicit = normalize_variant_id(
                explicit,
                field_name="default_variant_id",
            )
        except Exception:
            explicit = None

    available_ids = [
        clean_optional_string(item.get("variant_id"))
        for item in variants
        if isinstance(item, Mapping)
    ]
    available_ids = [item for item in available_ids if item]

    if explicit and explicit in available_ids:
        return explicit

    for item in variants:
        if not isinstance(item, Mapping):
            continue
        if parse_bool(
            item.get("is_default", item.get("isDefault")),
            default=False,
        ):
            candidate = clean_optional_string(item.get("variant_id"))
            if candidate:
                return candidate

    return available_ids[0] if available_ids else DEFAULT_VARIANT_ID


def enforce_single_default_variant_payload(
    variants: Sequence[Mapping[str, Any]],
    *,
    default_variant_id: str,
) -> list[dict[str, Any]]:
    """Return variant mappings with exactly one selected default."""
    normalized_default = normalize_variant_id(
        default_variant_id,
        field_name="default_variant_id",
    )
    result: list[dict[str, Any]] = []

    for raw_item in variants:
        item = normalize_json_mapping(raw_item)
        variant_id = normalize_variant_id(
            item.get("variant_id"),
            field_name="variant_id",
        )
        is_default = variant_id == normalized_default
        item["is_default"] = is_default
        item["isDefault"] = is_default
        result.append(item)

    return result


def normalize_upload_contracts(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize all upload blocks and keep starter uploads optional."""
    data = normalize_json_mapping(payload)
    by_kind: dict[str, Any] = {}

    existing_uploads = data.get("uploads")
    if isinstance(existing_uploads, Mapping):
        by_kind.update(normalize_json_mapping(existing_uploads))

    for kind, snake_key, camel_key in UPLOAD_CONTRACT_FIELDS:
        candidate = first_present_value(
            data,
            (
                snake_key,
                camel_key,
                f"{snake_key}_json",
                f"{camel_key}Json",
            ),
        )
        contract = normalize_upload_contract(candidate, kind=kind)
        data[snake_key] = contract
        data[camel_key] = contract
        data[f"{snake_key}_json"] = compact_json(contract)
        data[f"{camel_key}Json"] = data[f"{snake_key}_json"]
        by_kind[kind] = contract

    data["uploads"] = by_kind
    data["uploadsByKind"] = by_kind
    data["uploads_json"] = compact_json(by_kind)
    data["uploadsJson"] = data["uploads_json"]

    file_count = sum(
        normalize_non_negative_int(
            contract.get("count"),
            "upload_count",
        )
        for contract in by_kind.values()
        if isinstance(contract, Mapping)
    )
    error_count = sum(
        len(contract.get("errors") or [])
        for contract in by_kind.values()
        if isinstance(contract, Mapping)
    )
    summary = {
        "fileCount": file_count,
        "file_count": file_count,
        "errorCount": error_count,
        "error_count": error_count,
        "ok": error_count == 0,
        "kinds": sorted(by_kind.keys()),
    }
    data["uploads_summary"] = summary
    data["uploadsSummary"] = summary
    return data


def normalize_upload_contract(value: Any, *, kind: str) -> dict[str, Any]:
    """Normalize one upload metadata block without requiring file bytes."""
    parsed = parse_json_like(value, default={})
    source = normalize_json_mapping(parsed) if isinstance(parsed, Mapping) else {}
    files = source.get("files")
    errors = source.get("errors")

    if not isinstance(files, list):
        files = []
    if not isinstance(errors, list):
        errors = []

    normalized_files = [
        normalize_json_mapping(item)
        if isinstance(item, Mapping)
        else {"name": clean_optional_string(item) or ""}
        for item in files
    ]
    contract = {
        "version": (
            clean_optional_string(source.get("version"))
            or CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION
        ),
        "kind": normalize_slug_token(source.get("kind") or kind),
        "purpose": normalize_slug_token(
            source.get("purpose") or upload_purpose_for_kind(kind)
        ),
        "required": parse_bool(source.get("required"), default=False),
        "minimum_count": normalize_non_negative_int(
            source.get("minimum_count", source.get("minimumCount", 0)),
            "minimum_count",
        ),
        "count": len(normalized_files),
        "valid_count": sum(
            1 for item in normalized_files if item.get("valid", True) is not False
        ),
        "invalid_count": sum(
            1 for item in normalized_files if item.get("valid", True) is False
        ),
        "files": normalized_files,
        "errors": [normalize_json_value(item) for item in errors],
        "ok": len(errors) == 0,
        "backend_enabled": parse_bool(
            source.get("backend_enabled", source.get("backendEnabled")),
            default=True,
        ),
        "local_only": parse_bool(
            source.get("local_only", source.get("localOnly")),
            default=bool(normalized_files),
        ),
        "source": (
            clean_optional_string(source.get("source"))
            or "library_create_variant_payload_service"
        ),
    }
    contract["minimumCount"] = contract["minimum_count"]
    contract["validCount"] = contract["valid_count"]
    contract["invalidCount"] = contract["invalid_count"]
    contract["backendEnabled"] = contract["backend_enabled"]
    contract["localOnly"] = contract["local_only"]
    return contract


def empty_upload_contract(kind: str) -> dict[str, Any]:
    """Return a canonical optional empty upload contract."""
    return normalize_upload_contract({}, kind=kind)


def upload_purpose_for_kind(kind: str) -> str:
    mapping = {
        "geometry_model": "geometry_model",
        "technical_documents": "manufacturer_documents",
        "variant_documents": "variant_document_list",
    }
    return mapping.get(kind, kind or "upload")


def normalize_dimensions_mm(
    payload: Mapping[str, Any],
    *,
    default_dimensions: Mapping[str, Any] | None = None,
    geometry_unit: str = "m",
) -> dict[str, int]:
    """Resolve width, height and depth into positive millimetre integers."""
    defaults = dict(default_dimensions or {})
    definition_values = normalize_definition_values(
        first_present_value(payload, DEFINITION_VALUES_KEYS)
    )
    dimensions = (
        normalize_json_mapping(payload.get("dimensions"))
        if isinstance(payload.get("dimensions"), Mapping)
        else {}
    )
    result: dict[str, int] = {}

    for axis in ("width", "height", "depth"):
        key = f"dimensions.{axis}_mm"
        direct_candidates = (
            definition_values.get(key),
            payload.get(key),
            dimensions.get(f"{axis}_mm"),
            payload.get(f"{axis}_mm"),
            payload.get(f"dimensions_{axis}_mm"),
        )

        resolved: int | None = None
        for candidate in direct_candidates:
            numeric = positive_float(candidate)
            if numeric is not None:
                resolved = max(1, int(round(numeric)))
                break

        if resolved is None:
            geometry_candidate = first_present_value(
                payload,
                (
                    f"geometry_{axis}",
                    f"geometry{axis.title()}",
                    axis,
                ),
            )
            numeric = positive_float(geometry_candidate)
            if numeric is not None:
                resolved = geometry_value_to_mm(numeric, geometry_unit)

        if resolved is None:
            fallback = positive_float(defaults.get(key))
            resolved = max(1, int(round(fallback or 1000.0)))

        result[key] = resolved

    return result


def normalize_geometry_unit(value: Any) -> str:
    unit = str(value or "m").replace("\x00", "").strip().lower()
    return unit if unit in SUPPORTED_GEOMETRY_UNITS else "m"


def geometry_value_to_mm(value: float, unit: str) -> int:
    factor = {"m": 1000.0, "cm": 10.0, "mm": 1.0}.get(
        normalize_geometry_unit(unit),
        1000.0,
    )
    return max(1, int(round(value * factor)))


def dimension_mm_to_geometry_value(value_mm: int, unit: str) -> float:
    divisor = {"m": 1000.0, "cm": 10.0, "mm": 1.0}.get(
        normalize_geometry_unit(unit),
        1000.0,
    )
    return float(value_mm) / divisor


def positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        number = float(str(value).replace(",", ".").strip())
    except Exception:
        return None

    if not math.isfinite(number) or number <= 0:
        return None
    return number


def normalize_positive_int(value: Any, *, default: int = 1) -> int:
    try:
        number = int(float(str(value).replace(",", ".").strip()))
    except Exception:
        number = default
    return max(1, number)


def format_decimal(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def normalize_taxonomy_path(value: Any) -> str:
    parts = [
        normalize_slug_token(part)
        for part in str(value or "").replace("\\", "/").split("/")
    ]
    return "/".join(part for part in parts if part)


def validate_create_variant_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the normalized payload contract without calling VPLIB services."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    data = normalize_json_mapping(payload)

    for field_name in ("family_name", "domain", "category", "subcategory"):
        if not clean_optional_string(data.get(field_name)):
            errors.append(
                {
                    "code": "CREATE_PAYLOAD_REQUIRED_FIELD_MISSING",
                    "field": field_name,
                    "message": f"Required create payload field is missing: {field_name}",
                }
            )

    object_kind = normalize_slug_token(
        first_present_value(data, OBJECT_KIND_KEYS) or ""
    )
    if not object_kind:
        errors.append(
            {
                "code": "CREATE_PAYLOAD_OBJECT_KIND_MISSING",
                "field": "object_kind",
                "message": "object_kind is required.",
            }
        )

    family_profile_id = canonicalize_family_profile_id(
        first_present_value(data, FAMILY_PROFILE_ID_KEYS)
    )
    variant_profile_id = canonicalize_variant_profile_id(
        first_present_value(data, VARIANT_PROFILE_ID_KEYS)
    )
    if not family_profile_id:
        errors.append(
            {
                "code": "CREATE_PAYLOAD_FAMILY_PROFILE_MISSING",
                "field": "family_profile_id",
                "message": "family_profile_id is required.",
            }
        )
    if not variant_profile_id:
        errors.append(
            {
                "code": "CREATE_PAYLOAD_VARIANT_PROFILE_MISSING",
                "field": "variant_profile_id",
                "message": "variant_profile_id is required.",
            }
        )

    variants = data.get("definition_variants")
    if not isinstance(variants, list):
        variants = coerce_variants_to_list(
            parse_json_like(data.get("definition_variants_json"), default=[])
        )

    if not variants:
        errors.append(
            {
                "code": "CREATE_PAYLOAD_VARIANTS_MISSING",
                "field": "definition_variants",
                "message": "At least one definition variant is required.",
            }
        )

    default_ids = [
        clean_optional_string(item.get("variant_id"))
        for item in variants
        if isinstance(item, Mapping)
        and parse_bool(
            item.get("is_default", item.get("isDefault")),
            default=False,
        )
    ]
    if len(default_ids) != 1:
        errors.append(
            {
                "code": "CREATE_PAYLOAD_DEFAULT_VARIANT_INVALID",
                "field": "default_variant_id",
                "message": "Exactly one default variant is required.",
                "details": {"default_variant_ids": default_ids},
            }
        )

    explicit_default = clean_optional_string(
        first_present_value(data, DEFAULT_VARIANT_ID_KEYS)
    )
    if explicit_default and default_ids and explicit_default != default_ids[0]:
        errors.append(
            {
                "code": "CREATE_PAYLOAD_DEFAULT_VARIANT_MISMATCH",
                "field": "default_variant_id",
                "message": "default_variant_id does not match the selected default variant.",
                "details": {
                    "explicit": explicit_default,
                    "selected": default_ids[0],
                },
            }
        )

    if is_starter_payload(data):
        if family_profile_id != STARTER_FAMILY_PROFILE_ID:
            errors.append(
                {
                    "code": "CREATE_STARTER_FAMILY_PROFILE_INVALID",
                    "field": "family_profile_id",
                    "message": "Starter family profile must be simple_cell_block.",
                }
            )
        if variant_profile_id != STARTER_VARIANT_PROFILE_ID:
            errors.append(
                {
                    "code": "CREATE_STARTER_VARIANT_PROFILE_INVALID",
                    "field": "variant_profile_id",
                    "message": "Starter variant profile must be simple_cell_block.v1.",
                }
            )

        default_variant = next(
            (
                item
                for item in variants
                if isinstance(item, Mapping)
                and parse_bool(
                    item.get("is_default", item.get("isDefault")),
                    default=False,
                )
            ),
            {},
        )
        definition_values = normalize_definition_values(
            default_variant.get("definition_values")
            if isinstance(default_variant, Mapping)
            else {}
        )

        for key in STARTER_REQUIRED_VALUE_KEYS:
            if key not in definition_values:
                errors.append(
                    {
                        "code": "CREATE_STARTER_VALUE_MISSING",
                        "field": key,
                        "message": f"Starter definition value is missing: {key}",
                    }
                )

        for key in (
            "dimensions.width_mm",
            "dimensions.height_mm",
            "dimensions.depth_mm",
        ):
            if positive_float(definition_values.get(key)) is None:
                errors.append(
                    {
                        "code": "CREATE_STARTER_DIMENSION_INVALID",
                        "field": key,
                        "message": f"Starter dimension must be greater than zero: {key}",
                    }
                )

        for _, snake_key, _ in UPLOAD_CONTRACT_FIELDS:
            contract = data.get(snake_key)
            if isinstance(contract, Mapping) and parse_bool(
                contract.get("required"),
                default=False,
            ):
                errors.append(
                    {
                        "code": "CREATE_STARTER_UPLOAD_MUST_BE_OPTIONAL",
                        "field": snake_key,
                        "message": "Starter uploads must remain optional.",
                    }
                )

    uid = data.get(VPLIB_UID_FIELD)
    if uid and not normalize_vplib_uid_safe(uid):
        errors.append(
            {
                "code": "CREATE_PAYLOAD_INVALID_VPLIB_UID",
                "field": VPLIB_UID_FIELD,
                "message": "vplib_uid is invalid.",
            }
        )

    if not data.get("documents"):
        warnings.append(
            {
                "code": "CREATE_PAYLOAD_NO_DOCUMENTS",
                "field": "documents",
                "message": "No documents are attached; this is allowed for the starter profile.",
            }
        )

    return {
        "ok": not errors,
        "ready": not errors,
        "status": "ready" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "starter": is_starter_payload(data),
        "variant_count": len(variants),
        "default_variant_id": explicit_default or (
            default_ids[0] if default_ids else None
        ),
    }


def compute_payload_fingerprint(payload: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 fingerprint without volatile request metadata."""
    canonical = _fingerprint_value(payload)
    encoded = compact_json(canonical).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fingerprint_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(str(item) for item in value.keys()):
            if key in PAYLOAD_FINGERPRINT_IGNORED_KEYS:
                continue
            if key.startswith("_"):
                continue
            result[key] = _fingerprint_value(value.get(key))
        return result

    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]

    return normalize_json_value(value)


def compact_json(value: Any) -> str:
    """Serialize a JSON-compatible value deterministically."""
    return json.dumps(
        normalize_json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )



def ensure_create_payload_vplib_uid(
    payload: MutableMapping[str, Any],
    *,
    ensure_uid: bool = True,
    existing_uids: Iterable[Any] | None = None,
    overwrite_invalid_uid: bool = False,
) -> str | None:
    """
    Stellt sicher, dass der Payload eine gültige `vplib_uid` enthält.

    Verhalten:
    - vorhandene gültige ID wird normalisiert und behalten
    - fehlende ID wird erzeugt, wenn ensure_uid=True
    - ungültige vorhandene ID erzeugt Fehler, außer overwrite_invalid_uid=True
    """
    if not isinstance(payload, MutableMapping):
        raise CreateVariantPayloadError("payload must be mutable mapping.")

    raw_uid = first_present_value(payload, VPLIB_UID_KEYS)
    normalized_uid = normalize_vplib_uid_safe(raw_uid)

    if normalized_uid:
        payload[VPLIB_UID_FIELD] = normalized_uid
        return normalized_uid

    has_invalid_uid = raw_uid is not None and str(raw_uid).strip() != ""

    if has_invalid_uid and not overwrite_invalid_uid:
        raise CreateVariantPayloadError(
            f"Existing {VPLIB_UID_FIELD!r} is invalid and must not be replaced silently."
        )

    if not ensure_uid:
        return None

    uid = generate_unique_vplib_uid_safe(existing_uids=existing_uids)
    payload[VPLIB_UID_FIELD] = uid
    return uid


def get_service_health() -> dict[str, Any]:
    """Import-safe health payload for route diagnostics."""
    uid_health = get_vplib_uid_service_health()

    return {
        "ok": True,
        "healthy": True,
        "status": "healthy",
        "component": CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT,
        "schema_version": CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION,
        "vplib_uid_field": VPLIB_UID_FIELD,
        "normalization_report_field": NORMALIZATION_REPORT_FIELD,
        "uid_service": uid_health,
        "supports": {
            "stable_vplib_uid": True,
            "variant_normalization": True,
            "default_variant_resolution": True,
            "definition_values": True,
            "additional_field_keys": True,
            "family_profile_id": True,
            "variant_profile_id": True,
            "taxonomy_aliases": True,
            "documents": True,
            "assets": True,
            "variables": True,
            "form_bracket_notation": True,
            "json_string_fields": True,
            "starter_cell_block_contract": True,
            "canonical_profile_aliases": True,
            "millimetre_dimensions": True,
            "optional_upload_contracts": True,
            "payload_fingerprint": True,
            "contract_validation": True,
        },
    }


health = get_service_health
get_health = get_service_health


# Backward-compatible alias expected by some callers.
def normalize_create_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return normalize_create_variant_payload(*args, **kwargs)


# ---------------------------------------------------------------------------
# Variant normalization
# ---------------------------------------------------------------------------

def normalize_definition_variants_json(
    value: Any,
    *,
    common_definition_values: Mapping[str, Any] | None = None,
    additional_field_keys: Iterable[Any] = (),
    family_profile_id: str | None = None,
    variant_profile_id: str | None = None,
) -> tuple[NormalizedVariant, ...]:
    """
    Normalisiert `definition_variants_json`.

    Akzeptiert:
    - JSON-String mit Liste
    - JSON-String mit Mapping
    - Python-Liste
    - Python-Mapping
    - None / leer

    Gibt immer mindestens eine Default-Variante zurück.
    """
    parsed = parse_json_like(value, default=None)
    common_values = normalize_json_mapping(common_definition_values)
    common_additional_keys = normalize_additional_field_keys(additional_field_keys)
    normalized_variants: list[NormalizedVariant] = []

    if parsed is None or parsed == "":
        normalized_variants.append(
            NormalizedVariant(
                variant_id=DEFAULT_VARIANT_ID,
                label=DEFAULT_VARIANT_LABEL,
                is_default=True,
                family_profile_id=family_profile_id,
                variant_profile_id=variant_profile_id,
                definition_values=common_values,
                additional_field_keys=common_additional_keys,
                metadata={"source": "generated_default"},
                source_index=0,
                sort_order=0,
            ).normalized()
        )
        return tuple(normalized_variants)

    raw_variants = coerce_variants_to_list(parsed)

    if not raw_variants:
        normalized_variants.append(
            NormalizedVariant(
                variant_id=DEFAULT_VARIANT_ID,
                label=DEFAULT_VARIANT_LABEL,
                is_default=True,
                family_profile_id=family_profile_id,
                variant_profile_id=variant_profile_id,
                definition_values=common_values,
                additional_field_keys=common_additional_keys,
                metadata={"source": "generated_default_empty_variants"},
                source_index=0,
                sort_order=0,
            ).normalized()
        )
        return tuple(normalized_variants)

    used_ids: set[str] = set()

    for index, raw_variant in enumerate(raw_variants):
        variant_mapping = normalize_variant_mapping(raw_variant)
        raw_variant_id = first_present_value(variant_mapping, VARIANT_ID_KEYS)
        raw_label = first_present_value(variant_mapping, VARIANT_LABEL_KEYS)

        variant_id = normalize_variant_id_or_fallback(
            raw_variant_id,
            fallback=raw_label or f"variant_{index + 1}",
            index=index,
            used_ids=used_ids,
        )
        used_ids.add(variant_id)

        variant_values = normalize_definition_values(
            first_present_value(variant_mapping, DEFINITION_VALUES_KEYS)
        )
        merged_values = {
            **common_values,
            **variant_values,
        }

        variant_additional_keys = normalize_additional_field_keys(
            first_present_value(variant_mapping, ADDITIONAL_FIELD_KEYS_KEYS)
        )
        merged_additional_keys = merge_string_tuples(common_additional_keys, variant_additional_keys)

        normalized_variants.append(
            NormalizedVariant(
                variant_id=variant_id,
                label=clean_optional_string(raw_label) or label_from_variant_id(variant_id),
                description=clean_optional_string(first_present_value(variant_mapping, VARIANT_DESCRIPTION_KEYS)),
                is_default=parse_bool(first_present_value(variant_mapping, VARIANT_DEFAULT_KEYS), default=False),
                family_profile_id=clean_optional_string(first_present_value(variant_mapping, FAMILY_PROFILE_ID_KEYS)) or family_profile_id,
                variant_profile_id=clean_optional_string(first_present_value(variant_mapping, VARIANT_PROFILE_ID_KEYS)) or variant_profile_id,
                definition_values=merged_values,
                additional_field_keys=merged_additional_keys,
                metadata=extract_variant_metadata(variant_mapping),
                source_index=index,
                sort_order=normalize_non_negative_int(
                    variant_mapping.get("sort_order", variant_mapping.get("sortOrder", index)),
                    "sort_order",
                ),
                active=parse_bool(variant_mapping.get("active"), default=True),
                visible=parse_bool(variant_mapping.get("visible"), default=True),
            ).normalized()
        )

    if not any(variant.is_default for variant in normalized_variants):
        first = normalized_variants[0].normalized()
        normalized_variants[0] = NormalizedVariant(
            variant_id=first.variant_id,
            label=first.label,
            description=first.description,
            is_default=True,
            family_profile_id=first.family_profile_id,
            variant_profile_id=first.variant_profile_id,
            definition_values=first.definition_values,
            additional_field_keys=first.additional_field_keys,
            metadata=first.metadata,
            source_index=first.source_index,
            sort_order=first.sort_order,
            active=first.active,
            visible=first.visible,
        ).normalized()

    return tuple(normalized_variants)


def resolve_default_variant_id(
    *,
    explicit_default_variant_id: Any,
    variants: Iterable[NormalizedVariant],
) -> str:
    """Bestimmt die default_variant_id."""
    normalized_variants = tuple(variant.normalized() for variant in variants or ())
    explicit = clean_optional_string(explicit_default_variant_id)

    if explicit:
        normalized_explicit = normalize_variant_id(explicit, field_name="default_variant_id")
        if any(variant.variant_id == normalized_explicit for variant in normalized_variants):
            return normalized_explicit

    for variant in normalized_variants:
        if variant.is_default:
            return variant.variant_id

    if normalized_variants:
        return normalized_variants[0].variant_id

    return DEFAULT_VARIANT_ID


def mark_default_variant(
    variants: Iterable[NormalizedVariant],
    *,
    default_variant_id: str,
) -> tuple[NormalizedVariant, ...]:
    """Setzt genau eine Default-Variante."""
    normalized_default_id = normalize_variant_id(default_variant_id, field_name="default_variant_id")
    result: list[NormalizedVariant] = []

    for variant in variants or ():
        normalized = variant.normalized()
        result.append(
            NormalizedVariant(
                variant_id=normalized.variant_id,
                label=normalized.label,
                description=normalized.description,
                is_default=normalized.variant_id == normalized_default_id,
                family_profile_id=normalized.family_profile_id,
                variant_profile_id=normalized.variant_profile_id,
                definition_values=normalized.definition_values,
                additional_field_keys=normalized.additional_field_keys,
                metadata=normalized.metadata,
                source_index=normalized.source_index,
                sort_order=normalized.sort_order,
                active=normalized.active,
                visible=normalized.visible,
            ).normalized()
        )

    if not result:
        result.append(
            NormalizedVariant(
                variant_id=normalized_default_id,
                label=label_from_variant_id(normalized_default_id),
                is_default=True,
            ).normalized()
        )

    if not any(variant.is_default for variant in result):
        first = result[0].normalized()
        result[0] = NormalizedVariant(
            variant_id=first.variant_id,
            label=first.label,
            description=first.description,
            is_default=True,
            family_profile_id=first.family_profile_id,
            variant_profile_id=first.variant_profile_id,
            definition_values=first.definition_values,
            additional_field_keys=first.additional_field_keys,
            metadata=first.metadata,
            source_index=first.source_index,
            sort_order=first.sort_order,
            active=first.active,
            visible=first.visible,
        ).normalized()

    return tuple(result)


def normalize_definition_values(value: Any) -> dict[str, Any]:
    """Normalisiert `definition_values`."""
    parsed = parse_json_like(value, default={})

    if parsed is None or parsed == "":
        return {}

    if not isinstance(parsed, Mapping):
        return {
            "value": normalize_json_value(parsed),
        }

    return normalize_json_mapping(parsed)


def normalize_additional_field_keys(value: Any) -> tuple[str, ...]:
    """Normalisiert `additional_field_keys`."""
    parsed = parse_json_like(value, default=())

    if parsed is None or parsed == "":
        return tuple()

    raw_values: list[Any]

    if isinstance(parsed, str):
        raw_values = split_string_list(parsed)
    elif isinstance(parsed, Mapping):
        raw_values = list(parsed.keys())
    elif isinstance(parsed, (list, tuple, set)):
        raw_values = list(parsed)
    else:
        raw_values = [parsed]

    result: list[str] = []
    seen: set[str] = set()

    for raw_value in raw_values:
        key = normalize_field_key(raw_value)
        if not key or key in seen:
            continue

        result.append(key)
        seen.add(key)

    return tuple(result)


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------

def normalize_payload_mapping(
    payload: Mapping[str, Any] | MutableMapping[str, Any] | None,
    *,
    strict: bool = True,
) -> dict[str, Any]:
    """Normalisiert den Rohpayload zu einem JSON-kompatiblen Dict."""
    if payload is None:
        return {}

    if not isinstance(payload, Mapping):
        if strict:
            raise CreateVariantPayloadError("payload must be a mapping.")
        return {
            "value": str(payload),
        }

    normalized = {
        str(key): normalize_json_value_from_form(value)
        for key, value in payload.items()
    }

    normalized = expand_bracket_notation(normalized)
    normalized = decode_known_json_fields(normalized, strict=strict)
    normalized = merge_nested_aliases(normalized)

    return normalize_json_mapping(normalized)


def normalize_json_value_from_form(value: Any) -> Any:
    """Normalisiert Flask/Werkzeug-Formwerte defensiv."""
    getlist = getattr(value, "getlist", None)
    if callable(getlist):
        try:
            values = value.getlist()
            if len(values) == 1:
                return normalize_json_value(values[0])
            if len(values) > 1:
                return [normalize_json_value(item) for item in values]
        except Exception:
            pass

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        # Native Python lists represent structured JSON arrays. Only Werkzeug
        # getlist() values above may be safely collapsed as scalar form fields.
        return [normalize_json_value(item) for item in value]

    return normalize_json_value(value)


def expand_bracket_notation(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Expandiert einfache FormData-Bracket-Notation."""
    normalized = dict(payload)

    for prefix in INDEXED_ROW_PREFIXES:
        rows = extract_indexed_rows(normalized, prefix)
        if rows:
            normalized[prefix] = rows

    for prefix in NESTED_OBJECT_PREFIXES:
        nested = extract_bracket_object(normalized, prefix)
        if nested:
            existing = normalized.get(prefix)
            if isinstance(existing, Mapping):
                merged = dict(existing)
                merged.update(nested)
                normalized[prefix] = merged
            else:
                normalized[prefix] = nested

    return normalized


def decode_known_json_fields(payload: Mapping[str, Any], *, strict: bool = True) -> dict[str, Any]:
    """Dekodiert bekannte JSON-String-Felder."""
    normalized = dict(payload)

    for json_key, target_key in JSON_KEY_ALIASES.items():
        if json_key not in normalized:
            continue

        value = normalized.get(json_key)
        try:
            decoded = parse_json_like(value, default=value)
        except Exception:
            if strict:
                raise
            decoded = value

        if target_key == "__merge__":
            if isinstance(decoded, Mapping):
                normalized.update(decoded)
            continue

        normalized[target_key] = decoded

    return normalized


def merge_nested_aliases(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Hebt wichtige verschachtelte Aliaswerte auf Top-Level."""
    normalized = dict(payload)

    for nested_key in ("taxonomy", "classification"):
        nested = normalized.get(nested_key)
        if not isinstance(nested, Mapping):
            continue

        for target_key, aliases in (
            ("domain", TAXONOMY_DOMAIN_KEYS),
            ("category", TAXONOMY_CATEGORY_KEYS),
            ("subcategory", TAXONOMY_SUBCATEGORY_KEYS),
            ("object_kind", OBJECT_KIND_KEYS),
        ):
            if clean_optional_string(normalized.get(target_key)):
                continue

            value = first_present_value(nested, aliases)
            if value is not None:
                normalized[target_key] = value

    family = normalized.get("family")
    if isinstance(family, Mapping):
        for target_key, aliases in (
            ("family_name", ("family_name", "name", "label", "title")),
            ("family_slug", ("family_slug", "slug", "key")),
            ("family_description", ("family_description", "description", "desc")),
        ):
            if clean_optional_string(normalized.get(target_key)):
                continue

            value = first_present_value(family, aliases)
            if value is not None:
                normalized[target_key] = value

    geometry = normalized.get("geometry")
    dimensions = normalized.get("dimensions")
    geometry_dimensions = (
        geometry.get("dimensions")
        if isinstance(geometry, Mapping)
        and isinstance(geometry.get("dimensions"), Mapping)
        else None
    )

    for source in (geometry, geometry_dimensions, dimensions):
        if not isinstance(source, Mapping):
            continue

        for target_key, aliases in (
            ("width", ("width", "geometry_width")),
            ("height", ("height", "geometry_height")),
            ("depth", ("depth", "geometry_depth")),
            ("unit", UNIT_KEYS),
            ("primitive_shape", ("primitive_shape", "shape")),
        ):
            if normalized.get(target_key) is not None:
                continue

            value = first_present_value(source, aliases)
            if value is not None:
                normalized[target_key] = value

    technical = normalized.get("technical")
    if isinstance(technical, Mapping):
        for target_key, aliases in (
            ("material_class", MATERIAL_CLASS_KEYS),
            ("material_classes", MATERIAL_CLASSES_KEYS),
            ("variables", VARIABLES_KEYS),
        ):
            if normalized.get(target_key) is not None:
                continue

            value = first_present_value(technical, aliases)
            if value is not None:
                normalized[target_key] = value

    return normalized


def normalize_taxonomy_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert Taxonomie-Felder ohne Fallback-Domain/Kategorie."""
    result: dict[str, Any] = {}

    domain = first_present_value(payload, TAXONOMY_DOMAIN_KEYS)
    category = first_present_value(payload, TAXONOMY_CATEGORY_KEYS)
    subcategory = first_present_value(payload, TAXONOMY_SUBCATEGORY_KEYS)
    object_kind = first_present_value(payload, OBJECT_KIND_KEYS)

    if domain is not None:
        result["domain"] = normalize_slug_token(domain)

    if category is not None:
        result["category"] = normalize_slug_token(category)

    if subcategory is not None:
        result["subcategory"] = normalize_slug_token(subcategory)

    if object_kind is not None:
        result["object_kind"] = normalize_slug_token(object_kind)

    return result


# ---------------------------------------------------------------------------
# Documents / assets / variables
# ---------------------------------------------------------------------------

def normalize_documents_payload(value: Any) -> tuple[NormalizedDocument, ...]:
    parsed = parse_json_like(value, default=())
    items = coerce_items_to_list(parsed)
    result: list[NormalizedDocument] = []

    for index, item in enumerate(items):
        mapping = normalize_item_mapping(item)
        metadata = normalize_json_mapping(mapping.get("metadata") if isinstance(mapping.get("metadata"), Mapping) else {})
        extra = extract_extra_mapping(
            mapping,
            reserved={
                "document_type",
                "documentType",
                "document_kind",
                "documentKind",
                "field_key",
                "fieldKey",
                "title",
                "label",
                "filename",
                "file_name",
                "fileName",
                "mime_type",
                "mimeType",
                "library_file_id",
                "libraryFileId",
                "file_version_id",
                "fileVersionId",
                "file_uid",
                "fileUid",
                "storage_path",
                "storagePath",
                "url",
                "metadata",
            },
        )
        if extra:
            metadata["extra"] = extra

        result.append(
            NormalizedDocument(
                document_type=first_present_value(mapping, ("document_type", "documentType", "type")),
                document_kind=first_present_value(mapping, ("document_kind", "documentKind", "kind")),
                field_key=first_present_value(mapping, ("field_key", "fieldKey", "key")),
                title=first_present_value(mapping, ("title", "label", "name")),
                filename=first_present_value(mapping, ("filename", "file_name", "fileName", "original_filename", "originalFilename")),
                mime_type=first_present_value(mapping, ("mime_type", "mimeType", "content_type", "contentType")),
                library_file_id=first_present_value(mapping, ("library_file_id", "libraryFileId")),
                file_version_id=first_present_value(mapping, ("file_version_id", "fileVersionId")),
                file_uid=first_present_value(mapping, ("file_uid", "fileUid")),
                storage_path=first_present_value(mapping, ("storage_path", "storagePath", "path")),
                url=mapping.get("url"),
                metadata=metadata,
                source_index=index,
            ).normalized()
        )

    return tuple(result)


def normalize_assets_payload(value: Any) -> tuple[NormalizedAsset, ...]:
    parsed = parse_json_like(value, default=())
    items = coerce_items_to_list(parsed)
    result: list[NormalizedAsset] = []

    for index, item in enumerate(items):
        mapping = normalize_item_mapping(item)
        metadata = normalize_json_mapping(mapping.get("metadata") if isinstance(mapping.get("metadata"), Mapping) else {})
        extra = extract_extra_mapping(
            mapping,
            reserved={
                "asset_kind",
                "assetKind",
                "role",
                "filename",
                "file_name",
                "fileName",
                "mime_type",
                "mimeType",
                "size_bytes",
                "sizeBytes",
                "sha256",
                "library_file_id",
                "libraryFileId",
                "file_version_id",
                "fileVersionId",
                "file_uid",
                "fileUid",
                "source_path",
                "sourcePath",
                "storage_path",
                "storagePath",
                "metadata",
            },
        )
        if extra:
            metadata["extra"] = extra

        result.append(
            NormalizedAsset(
                asset_kind=first_present_value(mapping, ("asset_kind", "assetKind", "kind", "type")),
                role=first_present_value(mapping, ("role", "asset_role", "assetRole")),
                filename=first_present_value(mapping, ("filename", "file_name", "fileName", "original_filename", "originalFilename")),
                mime_type=first_present_value(mapping, ("mime_type", "mimeType", "content_type", "contentType")),
                size_bytes=first_present_value(mapping, ("size_bytes", "sizeBytes")),
                sha256=mapping.get("sha256"),
                library_file_id=first_present_value(mapping, ("library_file_id", "libraryFileId")),
                file_version_id=first_present_value(mapping, ("file_version_id", "fileVersionId")),
                file_uid=first_present_value(mapping, ("file_uid", "fileUid")),
                source_path=first_present_value(mapping, ("source_path", "sourcePath")),
                storage_path=first_present_value(mapping, ("storage_path", "storagePath", "path")),
                metadata=metadata,
                source_index=index,
            ).normalized()
        )

    return tuple(result)


def normalize_variables_payload(value: Any) -> list[dict[str, Any]]:
    parsed = parse_json_like(value, default=())
    items = coerce_items_to_list(parsed)
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items:
        mapping = normalize_item_mapping(item)
        key = normalize_field_key(first_present_value(mapping, ("key", "name", "id")))
        if not key or key in seen:
            continue

        seen.add(key)
        result.append(
            {
                "key": key,
                "label": clean_optional_string(first_present_value(mapping, ("label", "title", "name"))) or key,
                "description": clean_optional_string(first_present_value(mapping, ("description", "desc"))),
                "value": normalize_json_value(mapping.get("value")),
                "unit": clean_optional_string(mapping.get("unit")),
                "value_type": normalize_slug_token(first_present_value(mapping, ("value_type", "valueType", "type")) or "auto"),
                "scope": normalize_slug_token(mapping.get("scope") or "family"),
                "metadata": normalize_json_mapping(mapping.get("metadata") if isinstance(mapping.get("metadata"), Mapping) else {}),
            }
        )

    return result


def coerce_items_to_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []

    if isinstance(value, list):
        return list(value)

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    if isinstance(value, Mapping):
        if isinstance(value.get("items"), list):
            return list(value["items"])

        result: list[dict[str, Any]] = []
        for key, child_value in value.items():
            if isinstance(child_value, Mapping):
                row = dict(child_value)
                row.setdefault("key", key)
                result.append(row)
            else:
                result.append(
                    {
                        "key": key,
                        "value": normalize_json_value(child_value),
                    }
                )
        return result

    return [value]


def normalize_item_mapping(value: Any) -> dict[str, Any]:
    parsed = parse_json_like(value, default={})

    if isinstance(parsed, Mapping):
        return normalize_json_mapping(parsed)

    return {
        "value": normalize_json_value(parsed),
    }


# ---------------------------------------------------------------------------
# Variant helpers
# ---------------------------------------------------------------------------

def normalize_variant_mapping(value: Any) -> dict[str, Any]:
    """Normalisiert ein Variant-Mapping."""
    parsed = parse_json_like(value, default={})

    if isinstance(parsed, Mapping):
        return normalize_json_mapping(parsed)

    if isinstance(parsed, str):
        return {
            "variant_id": parsed,
            "label": label_from_variant_id(parsed),
        }

    return {
        "variant_id": str(parsed),
        "label": label_from_variant_id(str(parsed)),
    }


def coerce_variants_to_list(value: Any) -> list[Any]:
    """Konvertiert verschiedene Variantenformen in eine Liste."""
    if value is None:
        return []

    if isinstance(value, list):
        return list(value)

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, set):
        return list(value)

    if isinstance(value, Mapping):
        for nested_key in ("variants", "items", "definition_variants_json"):
            if nested_key in value:
                nested = parse_json_like(value.get(nested_key), default=())
                return coerce_variants_to_list(nested)

        result: list[dict[str, Any]] = []
        for key, child_value in value.items():
            if isinstance(child_value, Mapping):
                item = dict(child_value)
                item.setdefault("variant_id", key)
                result.append(item)
            else:
                result.append(
                    {
                        "variant_id": key,
                        "label": label_from_variant_id(key),
                        "definition_values": {
                            "value": normalize_json_value(child_value),
                        },
                    }
                )
        return result

    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return []
        return [
            {
                "variant_id": cleaned,
                "label": label_from_variant_id(cleaned),
            }
        ]

    return [value]


def extract_variant_metadata(value: Mapping[str, Any]) -> dict[str, Any]:
    """Extrahiert freie Variant-Metadata."""
    metadata = normalize_json_mapping(value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {})

    extra = extract_extra_mapping(value, reserved=RESERVED_VARIANT_KEYS)
    if extra:
        metadata["extra"] = extra

    return metadata


def extract_extra_mapping(value: Mapping[str, Any], *, reserved: Iterable[str]) -> dict[str, Any]:
    reserved_set = set(reserved)
    extra: dict[str, Any] = {}

    for key, child_value in value.items():
        if key in reserved_set:
            continue
        extra[str(key)] = normalize_json_value(child_value)

    return extra


def first_present_value(mapping: Mapping[str, Any], keys: Iterable[str]) -> Any | None:
    """Liest den ersten vorhandenen Wert aus Alias-Keys."""
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def parse_json_like(value: Any, *, default: Any = None) -> Any:
    """Parst JSON-Strings defensiv, lässt native Python-Werte aber intakt."""
    if value is None:
        return default

    if isinstance(value, (Mapping, list, tuple, set, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return parse_json_like(value.decode("utf-8", errors="replace"), default=default)

    if isinstance(value, str):
        cleaned = value.strip()

        if not cleaned:
            return default

        if cleaned[0:1] in {"{", "["}:
            try:
                return json.loads(cleaned)
            except Exception as exc:
                raise CreateVariantPayloadError(f"Invalid JSON payload: {exc}") from exc

        return cleaned

    return value


def normalize_variant_id_or_fallback(
    value: Any,
    *,
    fallback: Any,
    index: int,
    used_ids: set[str],
) -> str:
    """Normalisiert variant_id oder erzeugt eine stabile Fallback-ID."""
    candidates = (
        value,
        fallback,
        DEFAULT_VARIANT_ID if index == 0 else f"variant_{index + 1}",
    )

    for candidate in candidates:
        try:
            variant_id = normalize_variant_id(candidate, field_name="variant_id")
            if variant_id not in used_ids:
                return variant_id
        except Exception:
            continue

    base = f"variant_{index + 1}"
    counter = 1
    while f"{base}_{counter}" in used_ids:
        counter += 1

    return f"{base}_{counter}"


def normalize_variant_id(value: Any, *, field_name: str = "variant_id") -> str:
    """Normalisiert eine Variant-ID."""
    raw = clean_required_string(value, field_name)
    normalized = normalize_slug_token(raw)

    if not normalized:
        raise CreateVariantPayloadError(f"{field_name} is required.")

    if not SAFE_VARIANT_ID_RE.match(normalized):
        raise CreateVariantPayloadError(f"{field_name} contains unsafe characters: {value!r}.")

    return normalized


def normalize_field_key(value: Any) -> str | None:
    """Normalisiert einen zusätzlichen Feld-Key."""
    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    key = normalize_slug_token(cleaned)

    if not key:
        return None

    if not SAFE_FIELD_KEY_RE.match(key):
        return None

    return key


def normalize_slug_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "é": "e",
        "è": "e",
        "ê": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ç": "c",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)

    text = (
        text.replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )
    text = re.sub(r"[^a-z0-9._]+", "_", text)
    text = "_".join(part for part in text.split("_") if part)
    text = text.strip("._-")
    return text


def split_string_list(value: str) -> list[str]:
    """Splittet CSV-/Semicolon-/Whitespace-nahe Listen robust."""
    cleaned = value.strip()
    if not cleaned:
        return []

    if "," in cleaned:
        return [item.strip() for item in cleaned.split(",") if item.strip()]

    if ";" in cleaned:
        return [item.strip() for item in cleaned.split(";") if item.strip()]

    if "\n" in cleaned:
        return [item.strip() for item in cleaned.splitlines() if item.strip()]

    return [cleaned]


def label_from_variant_id(value: Any) -> str:
    """Erzeugt ein Label aus einer Variant-ID."""
    cleaned = clean_optional_string(value) or DEFAULT_VARIANT_LABEL
    return " ".join(part for part in cleaned.replace("-", "_").split("_") if part).title()


def parse_bool(value: Any, *, default: bool = False) -> bool:
    """Parst bool-ähnliche Werte."""
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    cleaned = str(value).strip().lower()
    if cleaned in {"1", "true", "yes", "y", "on", "default", "active", "enabled", "visible"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off", "inactive", "disabled", "hidden"}:
        return False

    return default


def merge_string_tuples(*values: Iterable[Any]) -> tuple[str, ...]:
    """Merged mehrere String-Iterables ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for group in values:
        for value in group or ():
            cleaned = clean_optional_string(value)
            if not cleaned or cleaned in seen:
                continue
            result.append(cleaned)
            seen.add(cleaned)

    return tuple(result)


# ---------------------------------------------------------------------------
# VPLIB UID
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_vplib_id_service_module() -> ModuleType | None:
    for module_name in (
        "vplib.vplib_id_service",
        "src.vplib.vplib_id_service",
        "services.vplib.vplib_id_service",
        "vectoplan_library.vplib.vplib_id_service",
        "vectoplan_library.src.vplib.vplib_id_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception:
            continue
    return None


def generate_unique_vplib_uid_safe(*, existing_uids: Iterable[Any] | None = None) -> str:
    """Erzeugt eine VPLIB-ID über den VPLIB-ID-Service mit Fallback."""
    module = _load_vplib_id_service_module()

    if module is not None:
        for function_name in ("generate_unique_vplib_uid", "generate_vplib_uid"):
            function = getattr(module, function_name, None)
            if callable(function):
                try:
                    if function_name == "generate_unique_vplib_uid":
                        return str(function(existing_uids=existing_uids))
                    return str(function())
                except TypeError:
                    try:
                        return str(function(existing_uids))
                    except Exception:
                        continue
                except Exception:
                    continue

    normalized_existing = {
        normalized
        for normalized in (normalize_vplib_uid_safe(value) for value in existing_uids or ())
        if normalized
    }

    for _attempt in range(100):
        candidate = str(uuid.uuid4()).lower()
        if candidate not in normalized_existing:
            return candidate

    return str(uuid.uuid4()).lower()


def normalize_vplib_uid_safe(value: Any) -> str | None:
    """Normalisiert eine VPLIB-ID über den VPLIB-ID-Service mit Fallback."""
    module = _load_vplib_id_service_module()

    if module is not None:
        normalizer = getattr(module, "normalize_vplib_uid", None)
        if callable(normalizer):
            try:
                uid = normalizer(value)
                if uid:
                    return str(uid)
            except Exception:
                pass

    try:
        if value is None:
            return None
        parsed = uuid.UUID(str(value).strip())
        return str(parsed).lower()
    except Exception:
        return None


def get_vplib_uid_service_health() -> dict[str, Any]:
    module = _load_vplib_id_service_module()

    if module is None:
        return {
            "available": False,
            "field": VPLIB_UID_FIELD,
            "fallback": "uuid.uuid4",
        }

    try:
        generator = getattr(module, "generate_vplib_uid", None) or getattr(module, "generate_unique_vplib_uid", None)
        normalizer = getattr(module, "normalize_vplib_uid", None)

        generated = generator() if callable(generator) else str(uuid.uuid4()).lower()
        normalized = normalizer(generated) if callable(normalizer) else normalize_vplib_uid_safe(generated)

        return {
            "available": bool(normalized),
            "generated_sample_valid": bool(normalized),
            "field": VPLIB_UID_FIELD,
            "module": getattr(module, "__name__", ""),
        }
    except Exception as exc:
        return {
            "available": False,
            "field": VPLIB_UID_FIELD,
            "module": getattr(module, "__name__", ""),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "fallback": "uuid.uuid4",
        }


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Mapping JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise CreateVariantPayloadError("value must be a mapping.")

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

    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")

    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_value(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    if hasattr(value, "isoformat") and callable(value.isoformat):
        try:
            return value.isoformat()
        except Exception:
            return str(value)

    if hasattr(value, "filename"):
        return {
            "filename": clean_optional_string(getattr(value, "filename", None)),
            "mime_type": clean_optional_string(getattr(value, "mimetype", None)),
            "content_type": clean_optional_string(getattr(value, "content_type", None)),
        }

    return str(value)


def normalize_message_level(value: Any) -> str:
    """Normalisiert Message-Level."""
    cleaned = clean_required_string(value, "level").lower()
    if cleaned in {"info", "warning", "error"}:
        return cleaned
    if cleaned in {"warn"}:
        return "warning"
    return "info"


def normalization_message(
    *,
    level: str,
    code: str,
    message: str,
    field_path: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> PayloadNormalizationMessage:
    """Factory für PayloadNormalizationMessage."""
    return PayloadNormalizationMessage(
        level=level,
        code=code,
        message=message,
        field_path=field_path,
        details=dict(details or {}),
    ).normalized()


def normalize_optional_non_negative_int(value: Any, field_name: str) -> int | None:
    """Normalisiert optionale nicht-negative Integer."""
    if value is None or value == "":
        return None

    try:
        number = int(value)
        if number < 0:
            raise CreateVariantPayloadError(f"{field_name} must be >= 0.")
        return number
    except CreateVariantPayloadError:
        raise
    except Exception as exc:
        raise CreateVariantPayloadError(f"{field_name} must be an integer.") from exc


def normalize_optional_positive_int(value: Any, field_name: str) -> int | None:
    """Normalisiert optionale positive Integer."""
    if value is None or value == "":
        return None

    try:
        number = int(value)
        if number < 1:
            raise CreateVariantPayloadError(f"{field_name} must be >= 1.")
        return number
    except CreateVariantPayloadError:
        raise
    except Exception as exc:
        raise CreateVariantPayloadError(f"{field_name} must be an integer.") from exc


def normalize_non_negative_int(value: Any, field_name: str) -> int:
    if value is None or value == "":
        return 0

    try:
        number = int(value)
        if number < 0:
            raise CreateVariantPayloadError(f"{field_name} must be >= 0.")
        return number
    except CreateVariantPayloadError:
        raise
    except Exception as exc:
        raise CreateVariantPayloadError(f"{field_name} must be an integer.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).replace("\x00", "").strip()
        if not cleaned:
            raise CreateVariantPayloadError(f"{field_name} is required.")
        return cleaned
    except CreateVariantPayloadError:
        raise
    except Exception as exc:
        raise CreateVariantPayloadError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).replace("\x00", "").strip()
        return cleaned or None
    except Exception:
        return None


def extract_indexed_rows(payload: Mapping[str, Any], prefix: str) -> list[dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    pattern = re.compile(rf"^{re.escape(prefix)}\[(\d+)\]\[([^\]]+)\]$")

    for key, value in payload.items():
        match = pattern.match(str(key))
        if not match:
            continue
        index = int(match.group(1))
        field_name = match.group(2)
        rows.setdefault(index, {})[field_name] = value

    return [rows[index] for index in sorted(rows.keys())]


def extract_bracket_object(payload: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    pattern = re.compile(rf"^{re.escape(prefix)}\[([^\]]+)\]$")

    for key, value in payload.items():
        match = pattern.match(str(key))
        if not match:
            continue
        result[match.group(1)] = value

    return result


def utc_now_iso() -> str:
    """UTC-Zeitstempel für Diagnose/Reports."""
    try:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


def clear_library_create_variant_payload_service_caches() -> dict[str, Any]:
    """Leert interne Import-Caches."""
    cleared: list[str] = []

    try:
        _load_vplib_id_service_module.cache_clear()
        cleared.append("_load_vplib_id_service_module")
    except Exception:
        pass

    return {
        "ok": True,
        "cleared": cleared,
    }


clear_create_variant_payload_service_caches = clear_library_create_variant_payload_service_caches


__all__ = [
    "ADDITIONAL_FIELD_KEYS_KEYS",
    "ASSETS_KEYS",
    "CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT",
    "CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION",
    "DEFAULT_VARIANT_ID",
    "DEFAULT_VARIANT_LABEL",
    "STARTER_OBJECT_KIND",
    "STARTER_FAMILY_PROFILE_ID",
    "STARTER_VARIANT_PROFILE_ID",
    "STARTER_FAMILY_NAME",
    "STARTER_PRIMITIVE_SHAPE",
    "STARTER_TAXONOMY",
    "STARTER_DIMENSIONS_MM",
    "STARTER_REQUIRED_VALUE_KEYS",
    "DEFINITION_VALUES_KEYS",
    "DEFINITION_VARIANTS_KEYS",
    "DOCUMENTS_KEYS",
    "FAMILY_PROFILE_ID_KEYS",
    "NORMALIZATION_REPORT_FIELD",
    "RESERVED_VARIANT_KEYS",
    "SAFE_FIELD_KEY_RE",
    "SAFE_VARIANT_ID_RE",
    "TAXONOMY_CATEGORY_KEYS",
    "TAXONOMY_DOMAIN_KEYS",
    "TAXONOMY_SUBCATEGORY_KEYS",
    "VARIANT_DEFAULT_KEYS",
    "VARIANT_DESCRIPTION_KEYS",
    "VARIANT_ID_KEYS",
    "VARIANT_LABEL_KEYS",
    "VARIANT_PROFILE_ID_KEYS",
    "VARIABLES_KEYS",
    "VPLIB_UID_FIELD",
    "VPLIB_UID_KEYS",

    # Exceptions
    "CreateVariantPayloadError",

    # Dataclasses
    "CreateVariantPayloadNormalizationResult",
    "NormalizedAsset",
    "NormalizedDocument",
    "NormalizedVariant",
    "PayloadNormalizationMessage",

    # Public API
    "clear_create_variant_payload_service_caches",
    "clear_library_create_variant_payload_service_caches",
    "ensure_create_payload_vplib_uid",
    "get_health",
    "get_service_health",
    "get_vplib_uid_service_health",
    "health",
    "normalize_create_payload",
    "normalize_create_variant_payload",
    "normalize_create_variant_payload_result",
    "canonicalize_family_profile_id",
    "canonicalize_variant_profile_id",
    "compute_payload_fingerprint",
    "empty_upload_contract",
    "is_starter_payload",
    "materialize_starter_definition_values",
    "materialize_starter_payload",
    "materialize_variant_payloads",
    "normalize_dimensions_mm",
    "normalize_profile_identifier",
    "normalize_taxonomy_path",
    "normalize_upload_contract",
    "normalize_upload_contracts",
    "validate_create_variant_payload",

    # Variant helpers
    "coerce_variants_to_list",
    "extract_variant_metadata",
    "first_present_value",
    "label_from_variant_id",
    "mark_default_variant",
    "merge_string_tuples",
    "normalize_additional_field_keys",
    "normalize_definition_values",
    "normalize_definition_variants_json",
    "normalize_field_key",
    "normalize_variant_id",
    "normalize_variant_id_or_fallback",
    "normalize_variant_mapping",
    "parse_bool",
    "parse_json_like",
    "resolve_default_variant_id",
    "split_string_list",

    # Document/asset/variable helpers
    "normalize_assets_payload",
    "normalize_documents_payload",
    "normalize_variables_payload",

    # Payload helpers
    "decode_known_json_fields",
    "expand_bracket_notation",
    "extract_bracket_object",
    "extract_indexed_rows",
    "merge_nested_aliases",
    "normalize_payload_mapping",
    "normalize_taxonomy_payload",

    # JSON/string helpers
    "clean_optional_string",
    "clean_required_string",
    "generate_unique_vplib_uid_safe",
    "normalization_message",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_message_level",
    "normalize_non_negative_int",
    "normalize_optional_non_negative_int",
    "normalize_optional_positive_int",
    "normalize_slug_token",
    "normalize_vplib_uid_safe",
    "utc_now_iso",
]