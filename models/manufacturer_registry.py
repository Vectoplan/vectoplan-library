"""Reusable manufacturer master data for the hosted VECTOPLAN platform.

The tables keep organizations, sites and ownership separate from a VPLIB
family. A manufacturer is created once and can then be linked to any number of
technical families. Product and pricing records only reference that master
data, so addresses and distribution areas are not copied for every product.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from extensions import db
from models.creative_library import (
    JsonMixin,
    TimestampMixin,
    new_uid,
    normalize_bool,
    normalize_int,
    normalize_json_list,
    normalize_json_mapping,
    normalize_optional_string,
    normalize_required_string,
)


MANUFACTURER_REGISTRY_SCHEMA_VERSION = "vectoplan.manufacturer-registry.v1"
MANUFACTURER_ACCESS_ROLES = frozenset({"owner", "manager", "editor", "viewer"})
MANUFACTURER_COVERAGE_MODES = frozenset({"radius", "territories", "country"})


def _key(value: Any, fallback: str = "manufacturer") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or fallback)[:120]


def _optional_float(
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value in (None, ""):
        return None
    number = float(str(value).replace(",", "."))
    if minimum is not None and number < minimum:
        raise ValueError(f"value must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"value must be <= {maximum}")
    return number


class ManufacturerOrganization(TimestampMixin, JsonMixin, db.Model):
    __tablename__ = "manufacturer_organizations"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, default=new_uid, index=True)
    organization_key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    brand = db.Column(db.String(255), nullable=True, index=True)
    website = db.Column(db.String(1024), nullable=True)
    country_code = db.Column(db.String(2), nullable=False, default="DE", index=True)
    owner_subject = db.Column(db.String(160), nullable=False, index=True)
    owner_account_id = db.Column(db.String(160), nullable=True, index=True)
    created_by_subject = db.Column(db.String(160), nullable=True, index=True)
    status = db.Column(db.String(40), nullable=False, default="active", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    locations = db.relationship(
        "ManufacturerLocation",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ManufacturerLocation.sort_order",
        lazy="select",
    )
    family_links = db.relationship(
        "ManufacturerFamilyLink",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
    access_grants = db.relationship(
        "ManufacturerAccessGrant",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )

    @classmethod
    def create_from_payload(cls, payload: Mapping[str, Any], *, actor_subject: str) -> "ManufacturerOrganization":
        name = normalize_required_string(payload.get("name"), field_name="manufacturer.name", max_length=255)
        owner_subject = normalize_optional_string(payload.get("owner_subject"), max_length=160) or actor_subject
        return cls(
            organization_key=_key(payload.get("organization_key") or payload.get("key") or name),
            name=name,
            brand=normalize_optional_string(payload.get("brand"), max_length=255),
            website=normalize_optional_string(payload.get("website"), max_length=1024),
            country_code=(normalize_optional_string(payload.get("country_code"), max_length=2) or "DE").upper(),
            owner_subject=owner_subject,
            owner_account_id=normalize_optional_string(payload.get("owner_account_id"), max_length=160),
            created_by_subject=actor_subject,
            status=normalize_optional_string(payload.get("status"), max_length=40) or "active",
            active=normalize_bool(payload.get("active"), default=True),
            metadata_json=normalize_json_mapping(payload.get("metadata")),
        )

    def to_dict(self, *, include_locations: bool = True, include_access: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "uid": self.uid,
            "organization_id": self.uid,
            "organization_key": self.organization_key,
            "name": self.name,
            "brand": self.brand,
            "website": self.website,
            "country_code": self.country_code,
            "owner_subject": self.owner_subject,
            "owner_account_id": self.owner_account_id,
            "platform_admin_retains_access": True,
            "status": self.status,
            "active": self.active,
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_locations:
            result["locations"] = [location.to_dict() for location in (self.locations or [])]
        if include_access:
            result["access_grants"] = [grant.to_dict() for grant in (self.access_grants or [])]
        return result


class ManufacturerLocation(TimestampMixin, JsonMixin, db.Model):
    __tablename__ = "manufacturer_locations"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, default=new_uid, index=True)
    organization_id = db.Column(
        db.BigInteger,
        db.ForeignKey("manufacturer_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    roles_json = db.Column(db.JSON, nullable=False, default=list)
    address = db.Column(db.String(1024), nullable=False)
    formatted_address = db.Column(db.String(1024), nullable=True)
    mapbox_feature_id = db.Column(db.String(255), nullable=True, index=True)
    country_code = db.Column(db.String(2), nullable=False, default="DE", index=True)
    latitude = db.Column(db.Float, nullable=False, index=True)
    longitude = db.Column(db.Float, nullable=False, index=True)
    coverage_mode = db.Column(db.String(40), nullable=False, default="radius", index=True)
    radius_km = db.Column(db.Float, nullable=True, index=True)
    territory_codes_json = db.Column(db.JSON, nullable=False, default=list)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    organization = db.relationship("ManufacturerOrganization", back_populates="locations", lazy="select")

    @classmethod
    def create_from_payload(
        cls,
        *,
        organization: ManufacturerOrganization,
        payload: Mapping[str, Any],
        sort_order: int = 0,
    ) -> "ManufacturerLocation":
        coverage_mode = str(payload.get("coverage_mode") or "radius").strip().lower()
        if coverage_mode not in MANUFACTURER_COVERAGE_MODES:
            raise ValueError("coverage_mode must be radius, territories or country")
        latitude = _optional_float(payload.get("latitude"), minimum=-90.0, maximum=90.0)
        longitude = _optional_float(payload.get("longitude"), minimum=-180.0, maximum=180.0)
        if latitude is None or longitude is None:
            raise ValueError("A geocoded location requires latitude and longitude")
        radius = _optional_float(payload.get("radius_km"), minimum=0.0, maximum=2500.0)
        territory_codes = [
            str(code).strip().upper()
            for code in normalize_json_list(payload.get("territory_codes"))
            if str(code).strip()
        ]
        if coverage_mode == "radius" and radius is None:
            raise ValueError("radius_km is required for radius coverage")
        if coverage_mode == "territories" and not territory_codes:
            raise ValueError("territory_codes are required for territory coverage")
        if coverage_mode == "country":
            territory_codes = ["DE"]
        return cls(
            organization=organization,
            name=normalize_required_string(payload.get("name"), field_name="location.name", max_length=255),
            roles_json=normalize_json_list(payload.get("roles")),
            address=normalize_required_string(payload.get("address"), field_name="location.address", max_length=1024),
            formatted_address=normalize_optional_string(payload.get("formatted_address"), max_length=1024),
            mapbox_feature_id=normalize_optional_string(payload.get("mapbox_feature_id"), max_length=255),
            country_code=(normalize_optional_string(payload.get("country_code"), max_length=2) or "DE").upper(),
            latitude=latitude,
            longitude=longitude,
            coverage_mode=coverage_mode,
            radius_km=radius if coverage_mode == "radius" else None,
            territory_codes_json=territory_codes,
            active=normalize_bool(payload.get("active"), default=True),
            sort_order=normalize_int(sort_order, default=0, minimum=0) or 0,
            metadata_json=normalize_json_mapping(payload.get("metadata")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uid": self.uid,
            "location_id": self.uid,
            "organization_id": self.organization_id,
            "name": self.name,
            "roles": normalize_json_list(self.roles_json),
            "address": self.address,
            "formatted_address": self.formatted_address,
            "mapbox_feature_id": self.mapbox_feature_id,
            "country_code": self.country_code,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "coverage_mode": self.coverage_mode,
            "radius_km": self.radius_km,
            "delivery_radius_km": self.radius_km,
            "territory_codes": normalize_json_list(self.territory_codes_json),
            "active": self.active,
            "sort_order": self.sort_order,
        }


class ManufacturerFamilyLink(TimestampMixin, JsonMixin, db.Model):
    __tablename__ = "manufacturer_family_links"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, default=new_uid, index=True)
    organization_id = db.Column(db.BigInteger, db.ForeignKey("manufacturer_organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    family_db_id = db.Column(db.BigInteger, db.ForeignKey("creative_library_items.id", ondelete="CASCADE"), nullable=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    linked_by_subject = db.Column(db.String(160), nullable=True)
    variant_assignments_json = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    organization = db.relationship("ManufacturerOrganization", back_populates="family_links", lazy="select")
    family = db.relationship("CreativeLibraryItem", lazy="select")

    __table_args__ = (db.UniqueConstraint("organization_id", "family_db_id", name="uq_manufacturer_family_link"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "organization_id": getattr(self.organization, "uid", None),
            "family_db_id": self.family_db_id,
            "family_ref": getattr(self.family, "vplib_uid", None) or getattr(self.family, "family_id", None),
            "variant_assignments": normalize_json_mapping(self.variant_assignments_json),
            "active": self.active,
        }


class ManufacturerAccessGrant(TimestampMixin, JsonMixin, db.Model):
    __tablename__ = "manufacturer_access_grants"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, default=new_uid, index=True)
    organization_id = db.Column(db.BigInteger, db.ForeignKey("manufacturer_organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_type = db.Column(db.String(40), nullable=False, index=True)
    subject_id = db.Column(db.String(160), nullable=False, index=True)
    access_role = db.Column(db.String(40), nullable=False, default="editor", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    granted_by_subject = db.Column(db.String(160), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    organization = db.relationship("ManufacturerOrganization", back_populates="access_grants", lazy="select")
    __table_args__ = (db.UniqueConstraint("organization_id", "subject_type", "subject_id", name="uq_manufacturer_access_grant"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "organization_id": getattr(self.organization, "uid", None),
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "access_role": self.access_role,
            "active": self.active,
            "granted_by_subject": self.granted_by_subject,
        }


class ManufacturerOwnershipTransfer(TimestampMixin, JsonMixin, db.Model):
    __tablename__ = "manufacturer_ownership_transfers"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    uid = db.Column(db.String(80), nullable=False, unique=True, default=new_uid, index=True)
    organization_id = db.Column(db.BigInteger, db.ForeignKey("manufacturer_organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_owner_subject = db.Column(db.String(160), nullable=True)
    new_owner_subject = db.Column(db.String(160), nullable=False, index=True)
    new_owner_account_id = db.Column(db.String(160), nullable=True, index=True)
    transferred_by_subject = db.Column(db.String(160), nullable=False)
    status = db.Column(db.String(40), nullable=False, default="completed", index=True)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    organization = db.relationship("ManufacturerOrganization", lazy="select")

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "organization_id": getattr(self.organization, "uid", None),
            "previous_owner_subject": self.previous_owner_subject,
            "new_owner_subject": self.new_owner_subject,
            "new_owner_account_id": self.new_owner_account_id,
            "transferred_by_subject": self.transferred_by_subject,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def iter_manufacturer_registry_models() -> tuple[type[Any], ...]:
    return (
        ManufacturerOrganization,
        ManufacturerLocation,
        ManufacturerFamilyLink,
        ManufacturerAccessGrant,
        ManufacturerOwnershipTransfer,
    )


iter_models = iter_manufacturer_registry_models
get_models = iter_manufacturer_registry_models


__all__ = [
    "MANUFACTURER_ACCESS_ROLES",
    "MANUFACTURER_COVERAGE_MODES",
    "MANUFACTURER_REGISTRY_SCHEMA_VERSION",
    "ManufacturerAccessGrant",
    "ManufacturerFamilyLink",
    "ManufacturerLocation",
    "ManufacturerOrganization",
    "ManufacturerOwnershipTransfer",
    "iter_manufacturer_registry_models",
]
