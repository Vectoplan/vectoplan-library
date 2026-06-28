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

import importlib
import json
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

CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION: Final[str] = "library.create_variant_payload.v2"
CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT: Final[str] = "library-create-variant-payload-service"

VPLIB_UID_FIELD: Final[str] = "vplib_uid"

NORMALIZATION_REPORT_FIELD: Final[str] = "_vplib_create_normalization"

DEFAULT_VARIANT_ID: Final[str] = "default"
DEFAULT_VARIANT_LABEL: Final[str] = "Default"

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

        return {
            "variant_id": normalized.variant_id,
            "variant_key": normalized.variant_id,
            "label": normalized.label,
            "description": normalized.description,
            "is_default": normalized.is_default,
            "family_profile_id": normalized.family_profile_id,
            "variant_profile_id": normalized.variant_profile_id,
            "definition_values": dict(normalized.definition_values),
            "additional_field_keys": list(normalized.additional_field_keys),
            "metadata": dict(normalized.metadata),
            "source_index": normalized.source_index,
            "sort_order": normalized.sort_order,
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
    """Normalisiert einen `/create`-Payload und gibt einen strukturierten Report zurück."""
    messages: list[PayloadNormalizationMessage] = []

    try:
        normalized_payload = normalize_payload_mapping(payload)

        try:
            uid = ensure_create_payload_vplib_uid(
                normalized_payload,
                ensure_uid=ensure_uid,
                existing_uids=existing_uids,
                overwrite_invalid_uid=overwrite_invalid_uid,
            )
            if uid:
                normalized_payload[VPLIB_UID_FIELD] = uid
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

        common_definition_values = normalize_definition_values(
            first_present_value(normalized_payload, DEFINITION_VALUES_KEYS)
        )
        additional_field_keys = normalize_additional_field_keys(
            first_present_value(normalized_payload, ADDITIONAL_FIELD_KEYS_KEYS)
        )
        family_profile_id = clean_optional_string(first_present_value(normalized_payload, FAMILY_PROFILE_ID_KEYS))
        variant_profile_id = clean_optional_string(first_present_value(normalized_payload, VARIANT_PROFILE_ID_KEYS))

        raw_variants = first_present_value(normalized_payload, DEFINITION_VARIANTS_KEYS)
        variants = normalize_definition_variants_json(
            raw_variants,
            common_definition_values=common_definition_values,
            additional_field_keys=additional_field_keys,
            family_profile_id=family_profile_id,
            variant_profile_id=variant_profile_id,
        )

        default_variant_id = resolve_default_variant_id(
            explicit_default_variant_id=first_present_value(normalized_payload, DEFAULT_VARIANT_ID_KEYS),
            variants=variants,
        )

        variants = mark_default_variant(variants, default_variant_id=default_variant_id)

        normalized_documents = normalize_documents_payload(first_present_value(normalized_payload, DOCUMENTS_KEYS))
        normalized_assets = normalize_assets_payload(first_present_value(normalized_payload, ASSETS_KEYS))
        normalized_variables = normalize_variables_payload(first_present_value(normalized_payload, VARIABLES_KEYS))

        normalized_payload["definition_values"] = common_definition_values
        normalized_payload["additional_field_keys"] = list(additional_field_keys)
        normalized_payload["definition_variants_json"] = [variant.to_dict() for variant in variants]
        normalized_payload["variants"] = [variant.to_dict() for variant in variants]
        normalized_payload["default_variant_id"] = default_variant_id

        if normalized_documents:
            normalized_payload["documents"] = [document.to_dict() for document in normalized_documents]

        if normalized_assets:
            normalized_payload["assets"] = [asset.to_dict() for asset in normalized_assets]

        if normalized_variables:
            normalized_payload["variables"] = normalized_variables

        if family_profile_id:
            normalized_payload["family_profile_id"] = family_profile_id

        if variant_profile_id:
            normalized_payload["variant_profile_id"] = variant_profile_id

        normalized_payload["variant_count"] = len(variants)
        normalized_payload["has_variants"] = bool(variants)
        normalized_payload["_create_payload_schema_version"] = CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION
        normalized_payload["_create_payload_component"] = CREATE_VARIANT_PAYLOAD_SERVICE_COMPONENT

        messages.append(
            normalization_message(
                level="info",
                code="CREATE_PAYLOAD_NORMALIZED",
                message="Create variant payload normalized.",
                details={
                    "vplib_uid": normalized_payload.get(VPLIB_UID_FIELD),
                    "variant_count": len(variants),
                    "default_variant_id": default_variant_id,
                    "additional_field_key_count": len(additional_field_keys),
                    "document_count": len(normalized_documents),
                    "asset_count": len(normalized_assets),
                    "variable_count": len(normalized_variables),
                },
            )
        )

        return CreateVariantPayloadNormalizationResult(
            payload=normalized_payload,
            messages=tuple(messages),
        ).normalized()

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
                "; ".join(message.message for message in messages if message.level == "error")
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
        if len(value) == 1:
            return normalize_json_value(value[0])
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

    for source in (geometry, dimensions):
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