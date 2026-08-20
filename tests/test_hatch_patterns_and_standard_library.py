"""Regression coverage for CAD hatches and the canonical standard library."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = SERVICE_ROOT / "src"
for candidate in (SERVICE_ROOT, SRC_ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))


def pattern_defaults():
    return importlib.import_module("vplib.defaults.pattern_defaults")


def create_service():
    return importlib.import_module("library.services.library_create_service")


def test_hatch_catalog_is_large_grouped_and_contains_core_construction_patterns() -> None:
    module = pattern_defaults()
    catalog = module.load_hatch_pattern_catalog()
    options = module.get_hatch_pattern_options()
    ids = {item["id"] for item in options}

    assert len(options) >= 40
    assert len(ids) == len(options)
    assert {
        "masonry_general",
        "brick_running_bond",
        "concrete_reinforced",
        "mineral_wool",
        "eps",
        "asphalt",
        "rail_ballast",
        "steel",
        "green_roof",
    } <= ids
    assert len({item["category"] for item in options}) >= 10
    assert catalog["catalog_version"] == "1.0.0"


def test_variant_patterns_build_a_self_contained_render_document() -> None:
    module = pattern_defaults()
    document = module.build_cad_patterns_document(
        [
            {
                "variant_id": "default",
                "definition_values": {
                    "cad.cut_pattern_id": "masonry_general",
                    "cad.surface_pattern_id": "brick_running_bond",
                    "cad.pattern_scale": 0.5,
                    "cad.pattern_rotation_deg": 45,
                    "cad.pattern_foreground_color": "#112233",
                    "cad.pattern_background_color": "#FAFAFA",
                },
            },
            {
                "variant_id": "daemmung_160",
                "definition_values": {
                    "cad.cut_pattern_id": "mineral_wool",
                    "cad.surface_pattern_id": "insulation_batt",
                },
            },
        ]
    )

    assert document["schema_version"] == "vplib.render.cad_patterns.v1"
    assert document["pattern_ids"] == [
        "brick_running_bond",
        "insulation_batt",
        "masonry_general",
        "mineral_wool",
    ]
    assert len(document["assignments"]) == 2
    assert document["assignments"][0]["cut"]["scale"] == 0.5
    assert document["assignments"][0]["surface"]["rotation_deg"] == 45
    assert {item["id"] for item in document["patterns"]} == set(document["pattern_ids"])
    assert module.validate_cad_patterns_document(document)[0]


def test_unknown_pattern_ids_are_rejected() -> None:
    module = pattern_defaults()
    with pytest.raises(module.PatternDefaultsError, match="Unknown hatch pattern"):
        module.build_cad_patterns_document(
            [{"variant_id": "default", "definition_values": {"cad.cut_pattern_id": "not_a_pattern"}}]
        )


def test_cad_pattern_schema_validator_is_registered() -> None:
    schema_validator = importlib.import_module("vplib.validators.schema_validator")
    validator = schema_validator.get_document_validator("render/cad_patterns.json")
    assert callable(validator)
    document = pattern_defaults().build_cad_patterns_document([])
    assert validator(document)[0]


def test_generator_package_plan_contains_variant_specific_cad_patterns() -> None:
    payload = {
        "vplib_uid": "d258392e-7168-51ab-9ca9-cd3c92462bce",
        "family_slug": "pattern_regression",
        "family_name": "Pattern Regression",
        "family_description": "Pattern generator regression.",
        "object_kind": "cell_block",
        "domain": "hochbau",
        "category": "waende",
        "subcategory": "mauerwerkswaende",
        "family_profile_id": "simple_cell_block",
        "variant_profile_id": "simple_cell_block.v1",
        "default_variant_id": "default",
        "geometry_width": 1,
        "geometry_height": 3,
        "geometry_depth": 0.24,
        "geometry_unit": "m",
        "definition_variants": [
            {
                "variant_id": "default",
                "label": "240 mm",
                "is_default": True,
                "definition_values": {
                    "cad.cut_pattern_id": "masonry_general",
                    "cad.surface_pattern_id": "brick_running_bond",
                },
            }
        ],
    }
    result = create_service().build_package_plan(payload, include_documents=True)

    assert result.ok, [issue.to_dict() for issue in result.errors]
    document = result.data["documents"]["render/cad_patterns.json"]
    assert document["assignments"][0]["cut"]["pattern_id"] == "masonry_general"
    assert document["assignments"][0]["surface"]["pattern_id"] == "brick_running_bond"
    assert "render/cad_patterns.json" in result.data["documents"]


def test_generator_adds_parametric_editor_contract_for_new_pipe_families() -> None:
    payload = {
        "vplib_uid": "399cb8ae-5d13-536a-b36e-5882ace25b7b",
        "family_slug": "generator_pipe_regression",
        "family_name": "Generator Pipe Regression",
        "family_description": "Parametric pipe contract regression.",
        "object_kind": "adaptive_system",
        "domain": "tiefbau",
        "category": "leitungen",
        "subcategory": "wasserleitungen",
        "family_profile_id": "simple_cell_block",
        "variant_profile_id": "simple_cell_block.v1",
        "primitive_shape": "pipe",
        "geometry_width": 1,
        "geometry_height": 0.11,
        "geometry_depth": 0.11,
        "geometry_unit": "m",
    }
    result = create_service().build_package_plan(payload, include_documents=True)

    assert result.ok, [issue.to_dict() for issue in result.errors]
    values = result.data["documents"]["variants/default.json"]["definition_values"]
    assert values["geometry.profile_id"] == "pipe_segment"
    assert values["geometry.axis"] == "x"
    assert values["inventory.icon_kind"] == "pipe"
    assert values["dimensions.length_mm"] == 1000


def test_standard_library_v1_is_complete_and_every_family_embeds_patterns() -> None:
    root = SERVICE_ROOT / "standard_library" / "v1"
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8-sig"))
    package_root = root / "packages"
    manifests = sorted(package_root.rglob("vplib.manifest.json"))
    pattern_documents = sorted(package_root.rglob("render/cad_patterns.json"))

    assert catalog["family_count"] == 52
    assert catalog["variant_count"] >= 300
    assert len(catalog["content_revision"]) == 64
    assert catalog["domain_counts"] == {"hochbau": 20, "ingenieurbau": 16, "tiefbau": 16}
    assert len(manifests) == catalog["family_count"]
    assert len(pattern_documents) == catalog["family_count"]
    assert sum(item["variant_count"] for item in catalog["families"]) == catalog["variant_count"]
    assert all(item["embedded_pattern_count"] >= 2 for item in catalog["families"])

    for path in pattern_documents:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        assert document["assignments"]
        assert document["patterns"]
        assert pattern_defaults().validate_cad_patterns_document(document)[0]

    for manifest_path in manifests:
        contract = json.loads(
            (manifest_path.parent / "manufacturer" / "contract.json").read_text(
                encoding="utf-8-sig"
            )
        )
        assert contract["scope"] == "generic"
        assert contract["manufacturer_bound"] is False
        assert contract["manufacturer_data_required"] is False
        assert contract["required_fields"] == []


def test_creative_inventory_always_renders_a_standard_library_block_preview() -> None:
    runtime = (SERVICE_ROOT / "static/js/inventar/creative-library.js").read_text(
        encoding="utf-8-sig"
    )

    assert "function bundledMaterialPreviewUrl(materialType)" in runtime
    assert "/static/textures/materials/masonry.webp" in runtime
    assert "/static/textures/materials/concrete.webp" in runtime
    assert "function createSemanticPreview(item, textureUrl)" in runtime
    assert 'item.icon_kind === "pipe"' in runtime
    assert 'item.icon_kind === "window"' in runtime
    assert 'item.icon_kind === "door"' in runtime
    assert "domainRank" in runtime


def test_standard_library_technical_objects_expose_editor_geometry_semantics() -> None:
    package_root = SERVICE_ROOT / "standard_library" / "v1" / "packages"

    def values(relative_path: str) -> dict[str, object]:
        return json.loads(
            (package_root / relative_path / "variants" / "default.json").read_text(
                encoding="utf-8-sig"
            )
        )["definition_values"]

    pipe = values("tiefbau/leitungen/abwasserleitungen/kanalrohr")
    window = values("hochbau/oeffnungen/fenster/standardfenster")
    interior_door = values("hochbau/oeffnungen/innentueren/innentuer")
    exterior_door = values("hochbau/oeffnungen/aussentueren/aussentuer")

    assert pipe["geometry.profile_id"] == "pipe_segment"
    assert pipe["geometry.primitive_shape"] == "pipe"
    assert window["geometry.profile_id"] == "thin_window"
    assert window["dimensions.depth_mm"] < window["dimensions.width_mm"]
    for door in (interior_door, exterior_door):
        assert door["geometry.profile_id"] == "hinged_door"
        assert door["interaction.kind"] == "swing_door"
        assert door["interaction.openable"] is True


def test_standard_library_source_overlay_replaces_stale_variants_and_adds_new_families() -> None:
    source_service = importlib.import_module(
        "library.services.standard_library_source_service"
    )
    stale = {
        "family_id": "vp.tiefbau.leitungen.abwasserleitungen.kanalrohr",
        "name": "Alter Name",
        "variants": [
            {
                "id": 123,
                "variant_id": "default",
                "definition_values": {"geometry.profile_id": "cell_block"},
            }
        ],
        "assets": [{"id": 7, "role": "preview"}],
    }

    items = source_service.overlay_standard_library_source_items([stale])
    by_family = {item["family_id"]: item for item in items}
    pipe = by_family["vp.tiefbau.leitungen.abwasserleitungen.kanalrohr"]

    assert len(items) == 52
    assert pipe["name"] == "Kanalrohr"
    assert pipe["variants"][0]["id"] == 123
    assert pipe["variants"][0]["definition_values"]["geometry.profile_id"] == "pipe_segment"
    assert pipe["assets"] == stale["assets"]
    assert "vp.hochbau.oeffnungen.aussentueren.aussentuer" in by_family


def test_cad_pattern_variables_are_registered_for_every_variant_profile() -> None:
    variables = json.loads(
        (SRC_ROOT / "library" / "definitions" / "data" / "variables.v1.json").read_text(encoding="utf-8-sig")
    )["items"]
    by_key = {item["key"]: item for item in variables}
    expected = {
        "cad.cut_pattern_id",
        "cad.surface_pattern_id",
        "cad.pattern_scale",
        "cad.pattern_rotation_deg",
        "cad.pattern_foreground_color",
        "cad.pattern_background_color",
    }
    assert expected <= by_key.keys()
    assert all(len(by_key[key]["applies_to"]) == 8 for key in expected)
