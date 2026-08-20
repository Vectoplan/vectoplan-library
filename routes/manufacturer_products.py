"""Manufacturer product catalog, availability and authorization context routes."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify, request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.creative_library import (
    CreativeLibraryItem,
    CreativeLibraryPermissionGrant,
    CreativeLibraryProductAvailability,
    CreativeLibraryProductVariant,
    CreativeLibraryVariant,
    normalize_bool,
    normalize_json_mapping,
    normalize_optional_string,
    utc_now,
)
from models.manufacturer_registry import (
    ManufacturerFamilyLink,
    ManufacturerOrganization,
)
try:
    from platform_private.manufacturer_registry_service import (
        ManufacturerRegistryAccessError,
        manufacturer_registry_service,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"platform_private", "platform_private.manufacturer_registry_service"}:
        raise
    from src.services.manufacturer_registry_service import (  # type: ignore[no-redef]
        ManufacturerRegistryAccessError,
        manufacturer_registry_service,
    )
from src.authorization.policy import LibraryPermission, get_authorization_service


manufacturer_products_bp = Blueprint(
    "manufacturer_products",
    __name__,
    url_prefix="/api/v1/vplib/manufacturer-products",
)
bp = manufacturer_products_bp
blueprint = manufacturer_products_bp


def _response(payload: Mapping[str, Any], status: int = 200):
    return jsonify(dict(payload)), status


def _error(message: str, *, code: str, status: int, details: Any = None):
    payload = {"ok": False, "status": "error", "code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return _response(payload, status)


def _payload() -> dict[str, Any]:
    value = request.get_json(silent=True)
    return dict(value) if isinstance(value, Mapping) else {}


def _resolve_family(reference: Any) -> CreativeLibraryItem | None:
    text = str(reference or "").strip()
    if not text:
        return None
    if text.isdigit():
        item = CreativeLibraryItem.query.filter_by(id=int(text)).first()
        if item is not None:
            return item
    return CreativeLibraryItem.query.filter(
        or_(
            CreativeLibraryItem.vplib_uid == text,
            CreativeLibraryItem.family_id == text,
            CreativeLibraryItem.package_id == text,
            CreativeLibraryItem.family_slug == text,
        )
    ).first()


def _resolve_base_variant(family: CreativeLibraryItem, reference: Any) -> CreativeLibraryVariant | None:
    text = str(reference or "").strip()
    if not text:
        return None
    if text.isdigit():
        match = CreativeLibraryVariant.query.filter_by(id=int(text), family_db_id=family.id).first()
        if match is not None:
            return match
    return CreativeLibraryVariant.query.filter_by(family_db_id=family.id, variant_id=text).first()


def _resolve_manufacturer(reference: Any) -> ManufacturerOrganization | None:
    text = str(reference or "").strip()
    if not text:
        return None
    if text.isdigit():
        match = ManufacturerOrganization.query.filter_by(id=int(text)).first()
        if match is not None:
            return match
    return ManufacturerOrganization.query.filter(
        or_(
            ManufacturerOrganization.uid == text,
            ManufacturerOrganization.organization_key == text,
        )
    ).first()


def _open_source_mode(service: Any) -> bool:
    return getattr(getattr(service, "provider", None), "name", "") == "open_source_allow_all"


def _manufacturer_payload(
    organization: ManufacturerOrganization,
    *,
    family: CreativeLibraryItem | None = None,
    include_access: bool = False,
) -> dict[str, Any]:
    payload = organization.to_dict(include_access=include_access)
    if family is None:
        return payload
    link = ManufacturerFamilyLink.query.filter_by(
        organization_id=organization.id,
        family_db_id=family.id,
        active=True,
    ).first()
    assignments = normalize_json_mapping(getattr(link, "variant_assignments_json", None)) if link else {}
    by_location = {
        str(item.get("location_id") or ""): dict(item)
        for item in (assignments.get("by_location") or [])
        if isinstance(item, Mapping)
    }
    for location in payload.get("locations") or []:
        assignment = by_location.get(str(location.get("location_id") or location.get("uid") or ""))
        if assignment:
            location["applies_to_all_variants"] = normalize_bool(
                assignment.get("applies_to_all_variants"), default=False
            )
            location["variant_ids"] = list(assignment.get("variant_ids") or [])
    payload["family_link"] = link.to_dict() if link else None
    payload["variant_assignments"] = assignments
    return payload


def _deny(decision):
    return _error(
        "Für diese Library-Familie fehlt die erforderliche Berechtigung.",
        code="library_permission_denied",
        status=403,
        details=decision.to_dict(),
    )


@manufacturer_products_bp.get("/permissions")
def permissions_context():
    family_ref = request.args.get("family_ref")
    family = _resolve_family(family_ref) if family_ref else None
    service = get_authorization_service()
    identity = service.identity()
    decisions = {
        permission.value: service.decide(permission, family=family).to_dict()
        for permission in LibraryPermission
    }
    capabilities = service.capabilities(family=family)
    capabilities["system_admin"] = "system_admin" in {
        str(role or "").strip().lower().replace("-", "_")
        for role in identity.roles
    }
    return _response(
        {
            "ok": True,
            "data": {
                "mode": "platform" if service.provider.name != "open_source_allow_all" else "open_source",
                "provider": service.provider.name,
                "identity": identity.to_dict(),
                "family_ref": family_ref,
                "family_db_id": getattr(family, "id", None),
                "capabilities": capabilities,
                "decisions": decisions,
            },
        }
    )


@manufacturer_products_bp.get("/manufacturers")
def list_manufacturers():
    """List reusable manufacturer master records, optionally for one family."""
    family_ref = request.args.get("family_ref")
    family = _resolve_family(family_ref) if family_ref else None
    authz = get_authorization_service()
    identity = authz.identity()
    is_admin = manufacturer_registry_service.is_platform_admin(
        identity,
        open_source=_open_source_mode(authz),
    )
    query = ManufacturerOrganization.query.filter_by(active=True)
    if family is not None and not normalize_bool(request.args.get("include_all"), default=False):
        query = query.join(ManufacturerFamilyLink).filter(
            ManufacturerFamilyLink.family_db_id == family.id,
            ManufacturerFamilyLink.active.is_(True),
        )
    search = str(request.args.get("q") or "").strip()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                ManufacturerOrganization.name.ilike(pattern),
                ManufacturerOrganization.brand.ilike(pattern),
                ManufacturerOrganization.organization_key.ilike(pattern),
            )
        )
    items = query.order_by(ManufacturerOrganization.name.asc()).limit(250).all()
    visible = [
        item
        for item in items
        if is_admin
        or manufacturer_registry_service.can_read(
            item,
            identity,
            open_source=_open_source_mode(authz),
        )
    ]
    return _response(
        {
            "ok": True,
            "count": len(visible),
            "items": [
                _manufacturer_payload(item, family=family, include_access=is_admin)
                for item in visible
            ],
            "family_ref": family_ref,
            "scope": "all" if request.args.get("include_all") else "family",
            "capabilities": {
                "platform_admin": is_admin,
                "manufacturer_create": is_admin,
                "ownership_transfer": is_admin,
            },
        }
    )


@manufacturer_products_bp.post("/manufacturers")
def create_manufacturer():
    data = _payload()
    family = _resolve_family(data.get("family_ref")) if data.get("family_ref") else None
    authz = get_authorization_service()
    try:
        organization = manufacturer_registry_service.create(
            data,
            identity=authz.identity(),
            family=family,
            open_source=_open_source_mode(authz),
        )
        db.session.commit()
        return _response(
            {"ok": True, "status": "created", "item": _manufacturer_payload(organization, family=family, include_access=True)},
            201,
        )
    except ManufacturerRegistryAccessError as exc:
        db.session.rollback()
        return _error(str(exc), code="manufacturer_access_denied", status=403)
    except IntegrityError:
        db.session.rollback()
        return _error("Dieser Hersteller existiert bereits.", code="manufacturer_conflict", status=409)
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return _error(str(exc), code="invalid_manufacturer", status=400)


@manufacturer_products_bp.get("/manufacturers/<string:manufacturer_ref>")
def manufacturer_detail(manufacturer_ref: str):
    organization = _resolve_manufacturer(manufacturer_ref)
    if organization is None:
        return _error("Hersteller wurde nicht gefunden.", code="manufacturer_not_found", status=404)
    authz = get_authorization_service()
    identity = authz.identity()
    is_admin = manufacturer_registry_service.is_platform_admin(identity, open_source=_open_source_mode(authz))
    if not manufacturer_registry_service.can_read(organization, identity, open_source=_open_source_mode(authz)):
        return _error("Kein Zugriff auf diesen Hersteller.", code="manufacturer_access_denied", status=403)
    family = _resolve_family(request.args.get("family_ref")) if request.args.get("family_ref") else None
    return _response({"ok": True, "item": _manufacturer_payload(organization, family=family, include_access=is_admin)})


@manufacturer_products_bp.patch("/manufacturers/<string:manufacturer_ref>")
def update_manufacturer(manufacturer_ref: str):
    organization = _resolve_manufacturer(manufacturer_ref)
    if organization is None:
        return _error("Hersteller wurde nicht gefunden.", code="manufacturer_not_found", status=404)
    authz = get_authorization_service()
    identity = authz.identity()
    if not manufacturer_registry_service.can_manage(organization, identity, open_source=_open_source_mode(authz)):
        return _error("Kein Schreibzugriff auf diesen Hersteller.", code="manufacturer_access_denied", status=403)
    data = _payload()
    try:
        for attribute, key, maximum in (
            ("name", "name", 255),
            ("brand", "brand", 255),
            ("website", "website", 1024),
            ("country_code", "country_code", 2),
        ):
            if key in data:
                value = normalize_optional_string(data.get(key), max_length=maximum)
                if attribute == "name" and not value:
                    raise ValueError("name is required")
                setattr(organization, attribute, value.upper() if attribute == "country_code" and value else value)
        location_id_map = {}
        if "locations" in data:
            location_id_map = manufacturer_registry_service.replace_locations(organization, data.get("locations"))
        family = _resolve_family(data.get("family_ref")) if data.get("family_ref") else None
        if family is not None:
            manufacturer_registry_service.link_family(
                organization,
                family,
                identity=identity,
                variant_assignments=manufacturer_registry_service.remap_variant_assignments(
                    data.get("variant_assignments"), location_id_map
                ),
            )
        db.session.commit()
        return _response({"ok": True, "status": "updated", "item": _manufacturer_payload(organization, family=family, include_access=True)})
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return _error(str(exc), code="invalid_manufacturer", status=400)


@manufacturer_products_bp.post("/manufacturers/<string:manufacturer_ref>/link-family")
def link_manufacturer_family(manufacturer_ref: str):
    organization = _resolve_manufacturer(manufacturer_ref)
    data = _payload()
    family = _resolve_family(data.get("family_ref"))
    if organization is None or family is None:
        return _error("Hersteller oder Library-Familie wurde nicht gefunden.", code="link_target_not_found", status=404)
    authz = get_authorization_service()
    identity = authz.identity()
    if not manufacturer_registry_service.can_manage(organization, identity, open_source=_open_source_mode(authz)):
        return _error("Kein Schreibzugriff auf diesen Hersteller.", code="manufacturer_access_denied", status=403)
    link = manufacturer_registry_service.link_family(
        organization,
        family,
        identity=identity,
        variant_assignments=data.get("variant_assignments"),
    )
    db.session.commit()
    return _response({"ok": True, "status": "linked", "link": link.to_dict()})


@manufacturer_products_bp.post("/manufacturers/<string:manufacturer_ref>/transfer")
def transfer_manufacturer_ownership(manufacturer_ref: str):
    organization = _resolve_manufacturer(manufacturer_ref)
    if organization is None:
        return _error("Hersteller wurde nicht gefunden.", code="manufacturer_not_found", status=404)
    data = _payload()
    authz = get_authorization_service()
    try:
        event = manufacturer_registry_service.transfer(
            organization,
            data,
            identity=authz.identity(),
            open_source=_open_source_mode(authz),
        )
        db.session.commit()
        family = _resolve_family(data.get("family_ref")) if data.get("family_ref") else None
        return _response(
            {
                "ok": True,
                "status": "transferred",
                "item": _manufacturer_payload(organization, family=family, include_access=True),
                "transfer": event.to_dict(),
                "platform_admin_retains_access": True,
                "scoped_manufacturer_access_granted": True,
                "required_auth_role": "manufacturer",
            }
        )
    except ManufacturerRegistryAccessError as exc:
        db.session.rollback()
        return _error(str(exc), code="manufacturer_transfer_denied", status=403)
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return _error(str(exc), code="invalid_manufacturer_transfer", status=400)


@manufacturer_products_bp.get("/geocode")
def geocode_manufacturer_address():
    """Small server-side Mapbox proxy; access tokens never enter the browser."""
    query = str(request.args.get("q") or "").strip()
    if len(query) < 3:
        return _error("Mindestens drei Zeichen eingeben.", code="geocode_query_too_short", status=400)
    token = str(
        os.getenv("VECTOPLAN_MAPBOX_TOKEN")
        or os.getenv("MAPBOX_ACCESS_TOKEN")
        or os.getenv("MAPBOX_TOKEN")
        or ""
    ).strip()
    if not token:
        return _error("Mapbox-Geocoder ist nicht konfiguriert.", code="geocoder_not_configured", status=503)
    endpoint = str(
        os.getenv("VECTOPLAN_LIBRARY_MAPBOX_GEOCODING_ENDPOINT")
        or "https://api.mapbox.com/search/geocode/v6/forward"
    ).strip()
    params = urlencode(
        {
            "q": query,
            "country": "DE",
            "language": "de",
            "limit": min(max(int(request.args.get("limit", 5)), 1), 8),
            "access_token": token,
        }
    )
    try:
        upstream = Request(f"{endpoint}?{params}", headers={"Accept": "application/json", "User-Agent": "vectoplan-library/1"})
        with urlopen(upstream, timeout=5) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
        items = []
        for feature in payload.get("features") or []:
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            properties = feature.get("properties") or {}
            if len(coordinates) < 2:
                continue
            items.append(
                {
                    "mapbox_feature_id": feature.get("id"),
                    "address": properties.get("full_address") or properties.get("name") or feature.get("place_name"),
                    "formatted_address": properties.get("full_address") or feature.get("place_name"),
                    "country_code": "DE",
                    "longitude": coordinates[0],
                    "latitude": coordinates[1],
                }
            )
        return _response({"ok": True, "provider": "mapbox", "items": items})
    except Exception as exc:
        return _error("Adresssuche ist vorübergehend nicht erreichbar.", code="geocoder_unavailable", status=502, details=str(exc))


@manufacturer_products_bp.get("")
@manufacturer_products_bp.get("/")
def list_products():
    family_ref = request.args.get("family_ref")
    family = _resolve_family(family_ref) if family_ref else None
    service = get_authorization_service()
    decision = service.decide(LibraryPermission.PRODUCT_VARIANT_READ, family=family)
    if not decision.allowed:
        return _deny(decision)

    query = CreativeLibraryProductVariant.query
    if family is not None:
        query = query.filter_by(family_db_id=family.id)
    manufacturer_org_id = request.args.get("manufacturer_org_id")
    if manufacturer_org_id:
        query = query.filter_by(manufacturer_org_id=manufacturer_org_id)
    if not normalize_bool(request.args.get("include_inactive"), default=False):
        query = query.filter_by(active=True)
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
    except (TypeError, ValueError):
        return _error("limit muss eine ganze Zahl sein.", code="invalid_limit", status=400)
    items = query.order_by(CreativeLibraryProductVariant.updated_at.desc()).limit(limit).all()
    return _response({"ok": True, "count": len(items), "items": [item.to_dict() for item in items]})


@manufacturer_products_bp.post("")
@manufacturer_products_bp.post("/")
def create_product():
    data = _payload()
    family = _resolve_family(data.get("family_ref") or data.get("family_db_id") or data.get("vplib_uid"))
    if family is None:
        return _error("Die ausgewählte Library-Familie wurde nicht gefunden.", code="family_not_found", status=404)

    service = get_authorization_service()
    decision = service.decide(
        LibraryPermission.PRODUCT_VARIANT_CREATE,
        family=family,
        context=data,
    )
    if not decision.allowed:
        return _deny(decision)

    locations = data.get("locations")
    if not isinstance(locations, list) or not locations:
        return _error(
            "Mindestens ein Vertriebsstandort mit Abdeckungsradius ist erforderlich.",
            code="distribution_location_required",
            status=400,
        )

    try:
        identity = service.identity()
        base_variant = _resolve_base_variant(family, data.get("base_variant_id"))
        product = CreativeLibraryProductVariant.create_from_payload(
            family=family,
            payload=data,
            submitted_by_subject=identity.subject,
            base_variant=base_variant,
        )
        db.session.add(product)
        for index, location_payload in enumerate(locations):
            if not isinstance(location_payload, Mapping):
                raise ValueError(f"locations[{index}] must be an object")
            db.session.add(
                CreativeLibraryProductAvailability.create_from_payload(
                    product_variant=product,
                    payload=location_payload,
                    sort_order=index,
                )
            )
        db.session.commit()
        return _response(
            {
                "ok": True,
                "status": "created",
                "item": product.to_dict(),
                "authorization": decision.to_dict(),
                "storage": "database_reference_layer",
                "embedded_in_vplib": False,
            },
            201,
        )
    except IntegrityError:
        db.session.rollback()
        return _error(
            "Diese Artikelnummer existiert für den Hersteller und die Familie bereits.",
            code="manufacturer_sku_conflict",
            status=409,
        )
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return _error(str(exc), code="invalid_product_variant", status=400)
    except Exception as exc:
        db.session.rollback()
        return _error("Produktvariante konnte nicht gespeichert werden.", code="product_variant_save_failed", status=500, details=str(exc))


@manufacturer_products_bp.patch("/<string:product_ref>")
def update_product(product_ref: str):
    product = CreativeLibraryProductVariant.query.filter_by(uid=product_ref).first()
    if product is None and product_ref.isdigit():
        product = CreativeLibraryProductVariant.query.filter_by(id=int(product_ref)).first()
    if product is None:
        return _error("Produktvariante wurde nicht gefunden.", code="product_variant_not_found", status=404)

    data = _payload()
    service = get_authorization_service()
    decision = service.decide(
        LibraryPermission.PRODUCT_VARIANT_EDIT,
        family=product.family,
        resource=product,
        context=data,
    )
    if not decision.allowed:
        return _deny(decision)

    try:
        for attribute, key, maximum in (
            ("brand", "brand", 255),
            ("product_name", "product_name", 255),
            ("sku", "sku", 255),
            ("gtin", "gtin", 255),
            ("description", "description", None),
            ("product_url", "product_url", 1024),
            ("base_variant_id", "base_variant_id", 160),
        ):
            if key in data:
                normalized = normalize_optional_string(data.get(key), max_length=maximum)
                if attribute in {"product_name", "sku"} and not normalized:
                    raise ValueError(f"{key} is required")
                setattr(product, attribute, normalized)
        if "properties" in data:
            product.properties_json = normalize_json_mapping(data.get("properties"))
        if "metadata" in data:
            product.metadata_json = normalize_json_mapping(data.get("metadata"))
        if "status" in data:
            requested_status = str(data.get("status") or "").strip().lower()
            if requested_status in {"approved", "published"}:
                approve = service.decide(LibraryPermission.PRODUCT_VARIANT_APPROVE, family=product.family, resource=product)
                if not approve.allowed:
                    return _deny(approve)
                product.approved_by_subject = service.identity().subject
                product.approved_at = utc_now()
            product.status = requested_status or product.status
        if isinstance(data.get("locations"), list):
            if not data["locations"]:
                raise ValueError("Mindestens ein Vertriebsstandort ist erforderlich.")
            product.locations[:] = []
            for index, location_payload in enumerate(data["locations"]):
                if not isinstance(location_payload, Mapping):
                    raise ValueError(f"locations[{index}] must be an object")
                db.session.add(
                    CreativeLibraryProductAvailability.create_from_payload(
                        product_variant=product,
                        payload=location_payload,
                        sort_order=index,
                    )
                )
        db.session.commit()
        return _response({"ok": True, "status": "updated", "item": product.to_dict()})
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return _error(str(exc), code="invalid_product_variant", status=400)
    except Exception as exc:
        db.session.rollback()
        return _error("Produktvariante konnte nicht aktualisiert werden.", code="product_variant_update_failed", status=500, details=str(exc))


@manufacturer_products_bp.get("/grants")
def list_grants():
    service = get_authorization_service()
    family = _resolve_family(request.args.get("family_ref")) if request.args.get("family_ref") else None
    decision = service.decide(LibraryPermission.RIGHTS_MANAGE, family=family)
    if not decision.allowed:
        return _deny(decision)
    query = CreativeLibraryPermissionGrant.query
    if family is not None:
        query = query.filter_by(family_db_id=family.id)
    items = query.order_by(CreativeLibraryPermissionGrant.created_at.desc()).limit(500).all()
    return _response({"ok": True, "count": len(items), "items": [item.to_dict() for item in items]})


@manufacturer_products_bp.post("/grants")
def create_grant():
    data = _payload()
    family = _resolve_family(data.get("family_ref")) if data.get("family_ref") else None
    service = get_authorization_service()
    decision = service.decide(LibraryPermission.RIGHTS_MANAGE, family=family)
    if not decision.allowed:
        return _deny(decision)
    try:
        grant = CreativeLibraryPermissionGrant(
            family=family,
            family_db_id=getattr(family, "id", None),
            subject_type=str(data.get("subject_type") or "").strip().lower(),
            subject_id=str(data.get("subject_id") or "").strip(),
            permission=str(data.get("permission") or "").strip(),
            effect=str(data.get("effect") or "allow").strip().lower(),
            active=normalize_bool(data.get("active"), default=True),
            created_by_subject=service.identity().subject,
            reason=normalize_optional_string(data.get("reason")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
        )
        if not grant.subject_type or not grant.subject_id or not grant.permission:
            raise ValueError("subject_type, subject_id and permission are required")
        db.session.add(grant)
        db.session.commit()
        return _response({"ok": True, "status": "created", "grant": grant.to_dict()}, 201)
    except IntegrityError:
        db.session.rollback()
        return _error("Diese Berechtigung existiert bereits.", code="grant_conflict", status=409)
    except (TypeError, ValueError) as exc:
        db.session.rollback()
        return _error(str(exc), code="invalid_grant", status=400)


__all__ = ["manufacturer_products_bp", "bp", "blueprint"]
