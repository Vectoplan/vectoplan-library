# services/vectoplan-library/src/services/library_create_variant_payload_service.py
"""
Create Variant Payload Service.

Diese Datei normalisiert Payloads aus der `/create`-Route, bevor daraus
VPLIB-Dokumente, Package-Pläne, Downloads oder gespeicherte Source-Packages
erzeugt werden.

Rolle dieser Datei:

    /create frontend payload
    -> normalize_create_variant_payload(...)
    -> stabiler Payload für VPLIB defaults / creators / validators

Wichtig für die neue VPLIB-ID-Architektur:
- `vplib_uid` entsteht beim Erstellen eines neuen .vplib-Packages.
- Wenn der Payload bereits eine gültige `vplib_uid` enthält, wird sie behalten.
- Wenn keine `vplib_uid` vorhanden ist, wird eine neue erzeugt.
- Wenn eine ungültige `vplib_uid` vorhanden ist, wird sie nicht still ersetzt.
- Die Datenbank erzeugt später keine eigene fachliche Block-ID.
- Die Datenbank übernimmt später nur die validierte `vplib_uid`.

Wichtig für die neue Variant Runtime:
- `definition_variants_json` wird robust aus JSON-String, Liste oder Mapping normalisiert.
- `default_variant_id` wird stabil bestimmt.
- `definition_values` wird robust aus JSON-String oder Mapping normalisiert.
- `additional_field_keys` wird robust aus JSON-String, Liste oder CSV-String normalisiert.
- Varianten bekommen stabile `variant_id`-Werte.
- Der Service erzeugt keine Dateien und spricht keine Datenbank an.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Iterable, Mapping, MutableMapping


CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION: Final[str] = "library.create_variant_payload.v1"

VPLIB_UID_FIELD: Final[str] = "vplib_uid"

NORMALIZATION_REPORT_FIELD: Final[str] = "_vplib_create_normalization"

DEFAULT_VARIANT_ID: Final[str] = "default"
DEFAULT_VARIANT_LABEL: Final[str] = "Default"

SAFE_VARIANT_ID_RE: Final[re.Pattern[str]] = re.compile(
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
}


class CreateVariantPayloadError(ValueError):
    """Wird ausgelöst, wenn ein Create-Variant-Payload nicht normalisiert werden kann."""


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
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "variant_id": normalized.variant_id,
            "label": normalized.label,
            "description": normalized.description,
            "is_default": normalized.is_default,
            "family_profile_id": normalized.family_profile_id,
            "variant_profile_id": normalized.variant_profile_id,
            "definition_values": dict(normalized.definition_values),
            "additional_field_keys": list(normalized.additional_field_keys),
            "metadata": dict(normalized.metadata),
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
        return tuple(message.normalized() for message in self.messages or () if message.normalized().level == "error")

    @property
    def warnings(self) -> tuple[PayloadNormalizationMessage, ...]:
        return tuple(message.normalized() for message in self.messages or () if message.normalized().level == "warning")

    @property
    def vplib_uid(self) -> str | None:
        return normalize_vplib_uid_safe(self.normalized().payload.get(VPLIB_UID_FIELD))

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "ok": normalized.ok,
            "vplib_uid": normalized.vplib_uid,
            "message_count": len(normalized.messages),
            "error_count": len(normalized.errors),
            "warning_count": len(normalized.warnings),
            "messages": [message.to_dict() for message in normalized.messages],
            "payload": dict(normalized.payload),
        }


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

    Diese Funktion ist der wichtigste Einstieg für Routen.

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
            "ok": result.ok,
            "message_count": len(result.messages),
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "messages": [message.to_dict() for message in result.messages],
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
    Normalisiert einen `/create`-Payload und gibt einen strukturierten Report zurück.
    """
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

        normalized_payload["definition_values"] = common_definition_values
        normalized_payload["additional_field_keys"] = list(additional_field_keys)
        normalized_payload["definition_variants_json"] = [variant.to_dict() for variant in variants]
        normalized_payload["default_variant_id"] = default_variant_id

        if family_profile_id:
            normalized_payload["family_profile_id"] = family_profile_id

        if variant_profile_id:
            normalized_payload["variant_profile_id"] = variant_profile_id

        normalized_payload["variant_count"] = len(variants)
        normalized_payload["has_variants"] = bool(variants)

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
            "ok": False,
            "messages": [message.to_dict() for message in messages],
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

        if index == 0 and not variant_values and common_values:
            variant_values = dict(common_values)

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
                definition_values=variant_values,
                additional_field_keys=merged_additional_keys,
                metadata=extract_variant_metadata(variant_mapping),
                source_index=index,
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

    return {
        str(key): normalize_json_value(value)
        for key, value in payload.items()
    }


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
        if "variants" in value:
            nested = parse_json_like(value.get("variants"), default=())
            return coerce_variants_to_list(nested)

        if "items" in value:
            nested = parse_json_like(value.get("items"), default=())
            return coerce_variants_to_list(nested)

        if "definition_variants_json" in value:
            nested = parse_json_like(value.get("definition_variants_json"), default=())
            return coerce_variants_to_list(nested)

        # Mapping als variant_id -> variant_payload interpretieren.
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

    extra: dict[str, Any] = {}
    for key, child_value in value.items():
        if key in RESERVED_VARIANT_KEYS:
            continue
        extra[str(key)] = normalize_json_value(child_value)

    if extra:
        metadata["extra"] = extra

    return metadata


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
    normalized = (
        raw.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )
    normalized = "_".join(part for part in normalized.split("_") if part)

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

    key = (
        cleaned.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )
    key = "_".join(part for part in key.split("_") if part)

    if not key:
        return None

    return key


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
    if cleaned in {"1", "true", "yes", "y", "on", "default"}:
        return True
    if cleaned in {"0", "false", "no", "n", "off"}:
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


def generate_unique_vplib_uid_safe(*, existing_uids: Iterable[Any] | None = None) -> str:
    """Erzeugt eine VPLIB-ID über den VPLIB-ID-Service mit Fallback."""
    try:
        from ..vplib.vplib_id_service import generate_unique_vplib_uid

        return generate_unique_vplib_uid(existing_uids=existing_uids)
    except Exception:
        pass

    try:
        from vplib.vplib_id_service import generate_unique_vplib_uid

        return generate_unique_vplib_uid(existing_uids=existing_uids)
    except Exception:
        pass

    return str(uuid.uuid4()).lower()


def normalize_vplib_uid_safe(value: Any) -> str | None:
    """Normalisiert eine VPLIB-ID über den VPLIB-ID-Service mit Fallback."""
    try:
        from ..vplib.vplib_id_service import normalize_vplib_uid

        return normalize_vplib_uid(value)
    except Exception:
        pass

    try:
        from vplib.vplib_id_service import normalize_vplib_uid

        return normalize_vplib_uid(value)
    except Exception:
        pass

    try:
        if value is None:
            return None
        parsed = uuid.UUID(str(value).strip())
        return str(parsed).lower()
    except Exception:
        return None


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

    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_value(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

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
    if value is None:
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


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()
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
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def utc_now_iso() -> str:
    """UTC-Zeitstempel für Diagnose/Reports."""
    try:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


__all__ = [
    "ADDITIONAL_FIELD_KEYS_KEYS",
    "CREATE_VARIANT_PAYLOAD_SERVICE_SCHEMA_VERSION",
    "DEFAULT_VARIANT_ID",
    "DEFAULT_VARIANT_LABEL",
    "DEFINITION_VALUES_KEYS",
    "DEFINITION_VARIANTS_KEYS",
    "FAMILY_PROFILE_ID_KEYS",
    "NORMALIZATION_REPORT_FIELD",
    "RESERVED_VARIANT_KEYS",
    "SAFE_VARIANT_ID_RE",
    "VARIANT_DEFAULT_KEYS",
    "VARIANT_DESCRIPTION_KEYS",
    "VARIANT_ID_KEYS",
    "VARIANT_LABEL_KEYS",
    "VARIANT_PROFILE_ID_KEYS",
    "VPLIB_UID_FIELD",
    "VPLIB_UID_KEYS",
    "CreateVariantPayloadError",
    "CreateVariantPayloadNormalizationResult",
    "NormalizedVariant",
    "PayloadNormalizationMessage",
    "clean_optional_string",
    "clean_required_string",
    "coerce_variants_to_list",
    "ensure_create_payload_vplib_uid",
    "extract_variant_metadata",
    "first_present_value",
    "generate_unique_vplib_uid_safe",
    "label_from_variant_id",
    "mark_default_variant",
    "merge_string_tuples",
    "normalization_message",
    "normalize_additional_field_keys",
    "normalize_create_variant_payload",
    "normalize_create_variant_payload_result",
    "normalize_definition_values",
    "normalize_definition_variants_json",
    "normalize_field_key",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_message_level",
    "normalize_optional_non_negative_int",
    "normalize_payload_mapping",
    "normalize_variant_id",
    "normalize_variant_id_or_fallback",
    "normalize_variant_mapping",
    "normalize_vplib_uid_safe",
    "parse_bool",
    "parse_json_like",
    "resolve_default_variant_id",
    "split_string_list",
    "utc_now_iso",
]