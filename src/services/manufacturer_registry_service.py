"""Public manufacturer-registry core with permissive open-source policy.

Reusable manufacturer and location data is part of the Apache-licensed
library service. Hosted deployments replace only the access decisions through
``platform_private.manufacturer_registry_service``. If that private package is
not distributed, this service deliberately permits all registry operations.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from extensions import db
from models.manufacturer_registry import (
    ManufacturerAccessGrant,
    ManufacturerFamilyLink,
    ManufacturerLocation,
    ManufacturerOrganization,
    ManufacturerOwnershipTransfer,
)
from src.authorization.policy import AuthorizationIdentity


MANUFACTURER_ROLE = "manufacturer"


class ManufacturerRegistryAccessError(PermissionError):
    pass


class ManufacturerRegistryCoreService:
    """Data operations plus the permissive policy used by open-source builds."""

    @staticmethod
    def is_platform_admin(identity: AuthorizationIdentity, *, open_source: bool = False) -> bool:
        return True

    @staticmethod
    def can_read(
        organization: ManufacturerOrganization,
        identity: AuthorizationIdentity,
        *,
        open_source: bool = False,
    ) -> bool:
        return True

    @staticmethod
    def can_manage(
        organization: ManufacturerOrganization,
        identity: AuthorizationIdentity,
        *,
        open_source: bool = False,
        read_only: bool = False,
    ) -> bool:
        return True

    def create(
        self,
        payload: Mapping[str, Any],
        *,
        identity: AuthorizationIdentity,
        family: Any = None,
        open_source: bool = False,
    ) -> ManufacturerOrganization:
        if not self.is_platform_admin(identity, open_source=open_source):
            raise ManufacturerRegistryAccessError("Only platform administrators may create manufacturers.")
        organization = ManufacturerOrganization.create_from_payload(payload, actor_subject=identity.subject)
        db.session.add(organization)
        db.session.flush()
        db.session.add(
            ManufacturerAccessGrant(
                organization=organization,
                subject_type="user" if identity.user_id else "organization",
                subject_id=identity.user_id or identity.organization_id or identity.subject,
                access_role="owner",
                active=True,
                granted_by_subject=identity.subject,
            )
        )
        location_id_map = self.replace_locations(organization, payload.get("locations") or [])
        if family is not None:
            self.link_family(
                organization,
                family,
                identity=identity,
                variant_assignments=self.remap_variant_assignments(
                    payload.get("variant_assignments"), location_id_map
                ),
            )
        return organization

    def replace_locations(self, organization: ManufacturerOrganization, locations: Any) -> dict[str, str]:
        if not isinstance(locations, list):
            raise ValueError("locations must be a list")
        existing = {str(location.uid): location for location in (organization.locations or []) if location.uid}
        retained: list[ManufacturerLocation] = []
        location_id_map: dict[str, str] = {}
        for index, location_payload in enumerate(locations):
            if not isinstance(location_payload, Mapping):
                raise ValueError(f"locations[{index}] must be an object")
            client_id = str(
                location_payload.get("location_id")
                or location_payload.get("uid")
                or f"location_{index + 1}"
            )
            normalized = ManufacturerLocation.create_from_payload(
                organization=organization,
                payload=location_payload,
                sort_order=index,
            )
            current = existing.get(client_id)
            if current is None:
                current = normalized
                current.uid = current.uid or str(uuid.uuid4())
                db.session.add(current)
            else:
                for attribute in (
                    "name",
                    "roles_json",
                    "address",
                    "formatted_address",
                    "mapbox_feature_id",
                    "country_code",
                    "latitude",
                    "longitude",
                    "coverage_mode",
                    "radius_km",
                    "territory_codes_json",
                    "active",
                    "sort_order",
                    "metadata_json",
                ):
                    setattr(current, attribute, getattr(normalized, attribute))
            retained.append(current)
            location_id_map[client_id] = str(current.uid)
        for stale in list(organization.locations or []):
            if stale not in retained:
                organization.locations.remove(stale)
        return location_id_map

    @staticmethod
    def remap_variant_assignments(value: Any, location_id_map: Mapping[str, str]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            return {}
        result = dict(value)
        rows = result.get("by_location")
        if isinstance(rows, list):
            remapped = []
            for item in rows:
                if not isinstance(item, Mapping):
                    continue
                row = dict(item)
                location_id = str(row.get("location_id") or "")
                row["location_id"] = location_id_map.get(location_id, location_id)
                remapped.append(row)
            result["by_location"] = remapped
        return result

    def link_family(
        self,
        organization: ManufacturerOrganization,
        family: Any,
        *,
        identity: AuthorizationIdentity,
        variant_assignments: Any = None,
    ) -> ManufacturerFamilyLink:
        link = ManufacturerFamilyLink.query.filter_by(
            organization_id=organization.id,
            family_db_id=family.id,
        ).first()
        if link is None:
            link = ManufacturerFamilyLink(
                organization=organization,
                family=family,
                family_db_id=family.id,
                linked_by_subject=identity.subject,
            )
            db.session.add(link)
        link.active = True
        if isinstance(variant_assignments, Mapping):
            link.variant_assignments_json = dict(variant_assignments)
        return link

    def transfer(
        self,
        organization: ManufacturerOrganization,
        payload: Mapping[str, Any],
        *,
        identity: AuthorizationIdentity,
        open_source: bool = False,
    ) -> ManufacturerOwnershipTransfer:
        if not self.is_platform_admin(identity, open_source=open_source):
            raise ManufacturerRegistryAccessError("Only platform administrators may transfer ownership.")
        new_owner_subject = str(payload.get("new_owner_subject") or "").strip()
        new_owner_account_id = str(payload.get("new_owner_account_id") or "").strip() or None
        if not new_owner_subject and new_owner_account_id:
            new_owner_subject = f"account:{new_owner_account_id}"
        if not new_owner_subject:
            raise ValueError("new_owner_subject or new_owner_account_id is required")

        event = ManufacturerOwnershipTransfer(
            organization=organization,
            previous_owner_subject=organization.owner_subject,
            new_owner_subject=new_owner_subject,
            new_owner_account_id=new_owner_account_id,
            transferred_by_subject=identity.subject,
            status="completed",
            metadata_json={"platform_admin_retains_access": True},
        )
        organization.owner_subject = new_owner_subject
        organization.owner_account_id = new_owner_account_id
        subject_type = "account" if new_owner_account_id else "user"
        subject_id = new_owner_account_id or new_owner_subject.removeprefix("user:")
        grant = ManufacturerAccessGrant.query.filter_by(
            organization_id=organization.id,
            subject_type=subject_type,
            subject_id=subject_id,
        ).first()
        if grant is None:
            grant = ManufacturerAccessGrant(
                organization=organization,
                subject_type=subject_type,
                subject_id=subject_id,
            )
            db.session.add(grant)
        grant.access_role = "owner"
        grant.active = True
        grant.granted_by_subject = identity.subject
        db.session.add(event)
        return event


manufacturer_registry_service = ManufacturerRegistryCoreService()


__all__ = [
    "MANUFACTURER_ROLE",
    "ManufacturerRegistryAccessError",
    "ManufacturerRegistryCoreService",
    "manufacturer_registry_service",
]
