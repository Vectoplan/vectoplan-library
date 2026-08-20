from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manufacturer_step_is_optional_via_regular_wizard_navigation():
    template = (ROOT / "templates/vplib/create/sections/_manufacturer.html").read_text(encoding="utf-8")
    profile_template = (ROOT / "templates/vplib/create/sections/_manufacturer_profile.html").read_text(
        encoding="utf-8"
    )
    runtime = (ROOT / "static/js/vplib/create/create_manufacturer_profile.js").read_text(encoding="utf-8")

    assert "Optionaler Schritt" not in template
    assert "Ohne Hersteller und Vertrieb fortfahren" not in template
    assert "data-vp-skip-manufacturer" not in template
    assert 'name="manufacturer_scope" value="generic"' in profile_template
    assert 'name="manufacturer_name"' in profile_template
    assert 'data-vp-manufacturer-profile-field="name" required' not in profile_template
    assert 'var scope = manufacturerBound ? "manufacturer" : "generic";' in runtime
    assert "manufacturerSkipped" not in runtime


def test_variant_step_contains_only_variant_authoring_not_distribution_locations():
    workspace = (ROOT / "templates/vplib/create/variants/_variant_workspace.html").read_text(encoding="utf-8")

    assert "_manufacturer_product.html" not in workspace
    assert "data-vp-distribution-locations-json" not in workspace
