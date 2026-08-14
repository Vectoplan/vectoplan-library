"""Normalize manufacturer identity and market coverage for a VPLIB family."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


MANUFACTURER_SCHEMA_VERSION = "vplib.manufacturer.v2"
MAX_LOCATIONS = 128
MAX_TERRITORIES = 64
ALLOWED_SCOPES = {"manufacturer"}
ALLOWED_COVERAGE_MODES = {"locations", "territories"}
ALLOWED_LOCATION_ROLES = {
    "production",
    "warehouse",
    "delivery",
    "distribution",
    "showroom",
    "online",
}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _text(value: Any, default: str = "", *, maximum: int = 255) -> str:
    return str(value or default).replace("\x00", "").strip()[:maximum]


def _token(value: Any, default: str = "") -> str:
    token = re.sub(r"[^a-z0-9_]+", "_", _text(value).lower()).strip("_")
    return token or default


def _number(
    value: Any,
    default: float | None = None,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value in (None, ""):
        return default
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}


def _normalize_roles(value: Any) -> list[str]:
    raw = value.split(",") if isinstance(value, str) else value
    if not isinstance(raw, (list, tuple, set)):
        return []
    roles: list[str] = []
    for item in raw:
        role = _token(item)
        if role in ALLOWED_LOCATION_ROLES and role not in roles:
            roles.append(role)
    return roles


def _normalize_regions(value: Any) -> list[str]:
    raw = value.split(",") if isinstance(value, str) else value
    if not isinstance(raw, (list, tuple, set)):
        return []
    regions: list[str] = []
    for item in raw:
        region = _text(item, maximum=120)
        if region and region not in regions:
            regions.append(region)
    return regions[:64]


def _normalize_variant_assignment(source: Mapping[str, Any]) -> dict[str, Any]:
    raw_ids = source.get("variant_ids", source.get("variantIds", []))
    if isinstance(raw_ids, str):
        raw_ids = raw_ids.split(",")
    variant_ids: list[str] = []
    if isinstance(raw_ids, (list, tuple, set)):
        for value in raw_ids:
            variant_id = _text(value, maximum=160)
            if variant_id and variant_id not in variant_ids:
                variant_ids.append(variant_id)
    applies_to_all = _bool(
        source.get("applies_to_all_variants", source.get("appliesToAllVariants")),
        default=not variant_ids,
    )
    return {
        "applies_to_all_variants": applies_to_all,
        "variant_ids": variant_ids[:256],
    }


def _normalize_location(value: Any, index: int) -> dict[str, Any] | None:
    source = _mapping(value)
    if not source:
        return None
    name = _text(source.get("name"), f"Standort {index + 1}", maximum=160)
    raw_coverage_mode = _token(source.get("coverage_mode") or source.get("coverageMode"), "radius")
    coverage_mode = raw_coverage_mode if raw_coverage_mode in {"radius", "territories", "country"} else "radius"
    raw_territory_codes = source.get("territory_codes") or source.get("territoryCodes") or []
    if isinstance(raw_territory_codes, str):
        raw_territory_codes = raw_territory_codes.split(",")
    territory_codes = []
    if isinstance(raw_territory_codes, (list, tuple, set)):
        territory_codes = unique_codes = []
        for item in raw_territory_codes:
            code = _text(item, maximum=12).upper()
            if re.fullmatch(r"DE(?:-[A-Z0-9]{1,3})?", code) and code not in unique_codes:
                unique_codes.append(code)
    if coverage_mode == "country":
        territory_codes = ["DE"]
    radius = _number(
        source.get("radius_km", source.get("delivery_radius_km")),
        100.0,
        minimum=0.0,
        maximum=2500.0,
    )
    return {
        "location_id": _token(source.get("location_id") or source.get("id") or name, f"location_{index + 1}"),
        "name": name,
        "roles": _normalize_roles(source.get("roles") or source.get("channels") or source.get("channel")),
        "address": _text(source.get("address"), maximum=255),
        "formatted_address": _text(source.get("formatted_address") or source.get("formattedAddress"), maximum=512),
        "mapbox_feature_id": _text(source.get("mapbox_feature_id") or source.get("mapboxFeatureId"), maximum=255),
        "postal_code": _text(source.get("postal_code") or source.get("postalCode"), maximum=32),
        "city": _text(source.get("city"), maximum=120),
        "country_code": _text(source.get("country_code") or source.get("countryCode") or "DE", maximum=2).upper(),
        "coverage_mode": coverage_mode,
        "radius_km": radius if coverage_mode == "radius" else None,
        "delivery_radius_km": radius if coverage_mode == "radius" else None,
        "territory_codes": territory_codes,
        "sales_regions": _normalize_regions(source.get("sales_regions") or source.get("salesRegions")),
        "latitude": _number(source.get("latitude"), None, minimum=-90.0, maximum=90.0),
        "longitude": _number(source.get("longitude"), None, minimum=-180.0, maximum=180.0),
        **_normalize_variant_assignment(source),
    }


def _normalize_territory(value: Any, index: int) -> dict[str, Any] | None:
    source = _mapping(value)
    if not source:
        return None
    raw_code = _text(
        source.get("territory_code")
        or source.get("territoryCode")
        or source.get("subdivision_code")
        or source.get("subdivisionCode")
        or source.get("country_code")
        or source.get("countryCode")
        or "DE",
        maximum=12,
    ).upper()
    territory_code = raw_code if re.fullmatch(r"[A-Z]{2}(?:-[A-Z0-9]{1,3})?", raw_code) else "DE"
    territory_type = "subdivision" if "-" in territory_code else "country"
    channels = [role for role in _normalize_roles(source.get("channels") or ["delivery", "distribution"]) if role in {"delivery", "distribution", "online"}]
    return {
        "territory_id": _token(
            source.get("territory_id") or source.get("territoryId") or source.get("id") or territory_code,
            f"territory_{index + 1}",
        ),
        "territory_type": territory_type,
        "territory_code": territory_code,
        "country_code": territory_code.split("-", 1)[0],
        "subdivision_code": territory_code if territory_type == "subdivision" else "",
        "label": _text(source.get("label") or territory_code, maximum=160),
        "channels": channels or ["distribution"],
        **_normalize_variant_assignment(source),
    }


def normalize_manufacturer_profile(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a compact family-level manufacturer and availability contract."""
    raw = _mapping(
        payload.get("manufacturer_profile")
        or payload.get("manufacturerProfile")
        or payload.get("manufacturer_profile_json")
        or payload.get("manufacturerProfileJson")
    )
    organization = _mapping(raw.get("organization"))
    availability = _mapping(raw.get("availability"))
    enforced = bool(raw) or any(
        _text(payload.get(field))
        for field in (
            "manufacturer_name",
            "manufacturer_org_id",
            "manufacturer_locations_json",
            "manufacturer_territories_json",
        )
    )
    scope = _token(raw.get("scope") or payload.get("manufacturer_scope"), "manufacturer")
    if scope not in ALLOWED_SCOPES:
        scope = "manufacturer"

    raw_locations = (
        availability.get("locations")
        or raw.get("locations")
        or payload.get("manufacturer_locations")
        or payload.get("manufacturer_locations_json")
        or payload.get("manufacturerLocationsJson")
        or []
    )
    locations: list[dict[str, Any]] = []
    for index, item in enumerate(_list(raw_locations)[:MAX_LOCATIONS]):
        location = _normalize_location(item, index)
        if location is not None:
            locations.append(location)

    raw_territories = (
        availability.get("territories")
        or raw.get("territories")
        or payload.get("manufacturer_territories")
        or payload.get("manufacturer_territories_json")
        or payload.get("manufacturerTerritoriesJson")
        or []
    )
    territories: list[dict[str, Any]] = []
    for index, item in enumerate(_list(raw_territories)[:MAX_TERRITORIES]):
        territory = _normalize_territory(item, index)
        if territory is not None:
            territories.append(territory)

    coverage_mode = _token(
        availability.get("coverage_mode")
        or availability.get("coverageMode")
        or payload.get("manufacturer_coverage_mode"),
        "territories" if territories else "locations",
    )
    if coverage_mode not in ALLOWED_COVERAGE_MODES:
        coverage_mode = "locations"
    if coverage_mode == "locations":
        territories = []
    else:
        locations = []

    profile = {
        "schema_version": MANUFACTURER_SCHEMA_VERSION,
        "enforced": enforced,
        "scope": scope,
        "manufacturer_bound": scope == "manufacturer",
        "organization": {
            "organization_id": _text(
                organization.get("organization_id")
                or organization.get("organizationId")
                or payload.get("manufacturer_org_id"),
                maximum=160,
            ),
            "name": _text(organization.get("name") or payload.get("manufacturer_name"), maximum=200),
            "brand": _text(organization.get("brand") or payload.get("manufacturer_brand"), maximum=160),
            "website": _text(organization.get("website") or payload.get("manufacturer_website"), maximum=512),
            "country_code": _text(
                organization.get("country_code")
                or organization.get("countryCode")
                or payload.get("manufacturer_country_code")
                or "DE",
                maximum=2,
            ).upper(),
        },
        "availability": {
            "storage": "platform_database_with_package_snapshot",
            "coverage_mode": coverage_mode,
            "location_count": len(locations),
            "territory_count": len(territories),
            "locations": locations,
            "territories": territories,
        },
    }
    return profile


__all__ = ["MANUFACTURER_SCHEMA_VERSION", "normalize_manufacturer_profile"]
