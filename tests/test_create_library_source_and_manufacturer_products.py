from __future__ import annotations

import importlib
import re
from pathlib import Path
from types import SimpleNamespace

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def _render_create_page() -> str:
    flask = pytest.importorskip("flask")
    route = importlib.import_module("routes.create")
    app = flask.Flask(
        __name__,
        template_folder=str(SERVICE_ROOT / "templates"),
        static_folder=str(SERVICE_ROOT / "static"),
    )
    app.register_blueprint(route.create_bp)
    response = app.test_client().get("/create")
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_create_page_has_nine_step_editor_with_manufacturer_before_variables() -> None:
    html = _render_create_page()
    assert 'data-vp-step-count="9"' in html
    assert 'data-vp-stepper-layout="sidebar"' in html
    assert 'data-vp-step-key="identity-taxonomy"' in html
    assert 'data-vp-step-key="spatial"' in html
    assert 'data-vp-step-key="manufacturer"' in html
    assert html.index('data-vp-step-key="manufacturer"') < html.index('data-vp-step-key="variables"')
    assert 'data-vp-step-key="pricing"' in html
    assert 'data-vp-create-section="manufacturer"' in html
    assert 'data-vp-create-section="identity-taxonomy"' in html
    assert html.count('data-vp-step-key="taxonomy"') == 0
    assert 'data-vp-library-source-root="true"' in html
    assert 'name="create_mode"' in html
    assert 'value="existing"' in html
    assert 'value="new"' in html
    assert 'create_library_source.js?v=20260815.1' in html
    assert 'create_manufacturer_products.js?v=20260815.1' in html
    assert 'create_manufacturer_profile.js?v=20260815.1' in html
    assert 'create_spatial_contract.js?v=20260815.1' in html
    assert 'create_pricing.js?v=20260815.1' in html
    assert 'name="spatial_contract_json"' in html
    assert 'name="connection_points_json"' in html
    assert 'name="model_scale_uniform"' in html
    assert 'name="model_scale_x"' in html
    assert 'name="model_scale_y"' in html
    assert 'name="model_scale_z"' in html
    assert 'name="pricing_contract_json"' in html
    assert 'data-vp-manufacturer-profile-root="true"' in html
    assert 'name="manufacturer_scope"' in html
    assert 'name="manufacturer_scope" value="generic"' in html
    assert 'name="manufacturer_name"' in html
    assert 'name="manufacturer_profile_json"' in html
    assert 'name="manufacturer_locations_json"' in html
    assert 'name="manufacturer_territories_json"' in html
    assert 'name="manufacturer_coverage_mode"' in html
    assert 'value="territories"' in html
    assert 'value="DE"' in html
    assert 'value="DE-BY"' in html
    assert 'data-vp-manufacturer-location-role' in html
    assert 'data-vp-manufacturer-variant-options' in html
    assert 'data-vp-manufacturer-state' in html
    assert 'data-vp-manufacturer-transfer' in html
    assert 'data-vp-manufacturer-search' in html
    assert 'data-vp-manufacturer-address' in html
    assert 'data-vp-clearance-side="left"' in html
    assert 'data-vp-clearance-side="right"' in html
    assert 'data-vp-editor-project-name' in html
    assert 'data-vp-definitions-available="true"' in html
    assert re.search(
        r'data-vp-variant-workspace-status-text="true"[^>]*\bhidden\b',
        html,
        flags=re.DOTALL,
    )


def test_existing_library_source_prefills_and_locks_master_data_for_non_admins() -> None:
    runtime = (SERVICE_ROOT / "static/js/vplib/create/create_library_source.js").read_text(
        encoding="utf-8"
    )

    assert "mapping(summary.payload)" in runtime
    assert 'replace(/-/g, "_") === "system_admin"' in runtime
    assert "setIdentityTaxonomyLocked(!isSystemAdmin(results[1]))" in runtime
    assert "Nur System-Admins dürfen diese Stammdaten ändern." in runtime
    assert "setIdentityTaxonomyLocked(false)" in runtime


def test_create_editor_shell_uses_panel_scrolling_instead_of_page_scrolling() -> None:
    css = (SERVICE_ROOT / "static/css/vplib/create.css").read_text(encoding="utf-8")
    assert "/* VECTOPLAN Create 4.0: fixed desktop application shell. */" in css
    assert "height: 100dvh;" in css
    assert "overflow: hidden;" in css
    assert ".vplib-create-step__body" in css
    assert "overflow-y: auto;" in css
    assert "/* VECTOPLAN Create 4.1: permanent light application chrome. */" in css
    assert "grid-template-rows: auto minmax(0, 1fr);" in css
    assert "/* VECTOPLAN Create 4.2: valid full-height app grid and distribution step. */" in css


def test_create_page_contains_only_the_single_outer_form() -> None:
    html = _render_create_page()
    assert html.count("<form") == 1
    assert html.count("</form>") == 1
    assert 'data-vp-variant-drawer-form="true"' in html


def test_create_editor_is_permanently_light() -> None:
    html = _render_create_page()
    theme = (SERVICE_ROOT / "static/js/vplib/create/create_theme.js").read_text(encoding="utf-8")
    assert 'data-theme="light"' in html
    assert 'data-vp-create-theme="light"' in html
    assert 'return "light";' in theme


def test_definitions_runtime_keeps_usable_catalogs_ready() -> None:
    runtime = (SERVICE_ROOT / "static/js/vplib/create/create_definitions.js").read_text(encoding="utf-8")
    workspace = (SERVICE_ROOT / "templates/vplib/create/variants/_variant_workspace.html").read_text(encoding="utf-8")
    assert "payload.definition_catalogs" in runtime
    assert 'getAttribute("data-vp-create-definitions-ready") === "true"' in workspace
    assert 'getAttribute("data-vp-definitions-available") === "true"' in workspace


def test_manufacturer_catalog_fields_do_not_enter_vplib_formdata() -> None:
    fragment = (SERVICE_ROOT / "templates/vplib/create/variants/_manufacturer_product.html").read_text(
        encoding="utf-8"
    )
    assert 'data-vp-manufacturer-field="manufacturer_product_name"' in fragment
    assert 'data-vp-location-field="radius_km"' in fragment
    assert 'name="manufacturer_' not in fragment
    assert 'name="distribution_' not in fragment


def test_manufacturer_registry_blueprint_exposes_master_data_routes() -> None:
    flask = pytest.importorskip("flask")
    route = importlib.import_module("routes.manufacturer_products")
    app = flask.Flask(__name__)
    app.register_blueprint(route.manufacturer_products_bp)
    rules: dict[str, set[str]] = {}
    for rule in app.url_map.iter_rules():
        rules.setdefault(rule.rule, set()).update(rule.methods or set())

    registry = "/api/v1/vplib/manufacturer-products/manufacturers"
    detail = "/api/v1/vplib/manufacturer-products/manufacturers/<string:manufacturer_ref>"
    assert {"GET", "POST"} <= rules[registry]
    assert {"GET", "PATCH"} <= rules[detail]
    assert "POST" in rules[f"{detail}/transfer"]
    assert "POST" in rules[f"{detail}/link-family"]
    assert "GET" in rules["/api/v1/vplib/manufacturer-products/geocode"]


def test_platform_manufacturer_write_access_requires_manufacturer_role() -> None:
    policy = importlib.import_module("src.authorization.policy")
    registry = importlib.import_module("platform_private.manufacturer_registry_service")
    organization = SimpleNamespace(owner_subject="user:brick-user", access_grants=[])
    ordinary_identity = policy.AuthorizationIdentity(
        user_id="brick-user",
        roles=("user",),
        authenticated=True,
    )
    manufacturer_identity = policy.AuthorizationIdentity(
        user_id="brick-user",
        roles=("manufacturer",),
        authenticated=True,
    )

    assert registry.manufacturer_registry_service.can_manage(organization, ordinary_identity) is False
    assert registry.manufacturer_registry_service.can_manage(organization, manufacturer_identity) is True
    assert registry.manufacturer_registry_service.can_manage(
        organization,
        ordinary_identity,
        open_source=True,
    ) is True


def test_open_source_manufacturer_registry_remains_permissive_without_private_policy() -> None:
    policy = importlib.import_module("src.authorization.policy")
    registry = importlib.import_module("src.services.manufacturer_registry_service")
    identity = policy.AuthorizationIdentity(roles=("user",), authenticated=True)
    organization = SimpleNamespace(owner_subject="another-user", access_grants=[])

    assert registry.manufacturer_registry_service.can_read(organization, identity) is True
    assert registry.manufacturer_registry_service.can_manage(organization, identity) is True
    assert registry.manufacturer_registry_service.is_platform_admin(identity) is True


def test_open_source_authorization_allows_every_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = importlib.import_module("src.authorization.policy")
    monkeypatch.delenv("VECTOPLAN_LIBRARY_AUTHZ_PROVIDER", raising=False)
    policy.get_authorization_service.cache_clear()
    service = policy.get_authorization_service()
    assert service.provider.name == "open_source_allow_all"
    assert all(service.capabilities().values())
    policy.get_authorization_service.cache_clear()


def test_explicit_broken_platform_provider_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    policy = importlib.import_module("src.authorization.policy")
    monkeypatch.setenv("VECTOPLAN_LIBRARY_AUTHZ_PROVIDER", "missing.platform:provider")
    policy.get_authorization_service.cache_clear()
    service = policy.get_authorization_service()
    decision = service.decide(policy.LibraryPermission.PRODUCT_VARIANT_CREATE)
    assert decision.allowed is False
    assert service.provider.name == "configured_provider_unavailable"
    policy.get_authorization_service.cache_clear()


def test_product_models_validate_coverage_and_keep_catalog_separate() -> None:
    model_package = importlib.import_module("models")
    model_package.import_all_models()
    models = importlib.import_module("models.creative_library")
    family = models.CreativeLibraryItem(
        vplib_uid="vplib:test-wall",
        family_id="masonry.wall.block",
        family_slug="masonry-wall-block",
        package_id="masonry.wall.block",
        name="Mauerwandblock",
    )
    product = models.CreativeLibraryProductVariant.create_from_payload(
        family=family,
        payload={
            "manufacturer_org_id": "manufacturer-1",
            "product_name": "ThermoPlan T12",
            "sku": "T12-365",
            "base_variant_id": "365mm",
            "status": "submitted",
        },
        submitted_by_subject="user:42",
    )
    location = models.CreativeLibraryProductAvailability.create_from_payload(
        product_variant=product,
        payload={
            "name": "Werk Nord",
            "postal_code": "10115",
            "city": "Berlin",
            "country_code": "de",
            "radius_km": 120,
            "latitude": 52.52,
            "longitude": 13.405,
        },
    )
    assert product.family is family
    assert product.sku == "T12-365"
    assert location.country_code == "DE"
    assert location.radius_km == 120
    assert product.__tablename__ != models.CreativeLibraryVariant.__tablename__

    with pytest.raises(ValueError):
        models.CreativeLibraryProductAvailability.create_from_payload(
            product_variant=product,
            payload={"name": "Unzulässig", "radius_km": 2501},
        )
