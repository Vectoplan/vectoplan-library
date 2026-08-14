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


def test_standard_library_v1_is_complete_and_every_family_embeds_patterns() -> None:
    root = SERVICE_ROOT / "standard_library" / "v1"
    catalog = json.loads((root / "catalog.json").read_text(encoding="utf-8-sig"))
    package_root = root / "packages"
    manifests = sorted(package_root.rglob("vplib.manifest.json"))
    pattern_documents = sorted(package_root.rglob("render/cad_patterns.json"))

    assert catalog["family_count"] == 48
    assert catalog["variant_count"] >= 300
    assert catalog["domain_counts"] == {"hochbau": 16, "ingenieurbau": 16, "tiefbau": 16}
    assert len(manifests) == catalog["family_count"]
    assert len(pattern_documents) == catalog["family_count"]
    assert sum(item["variant_count"] for item in catalog["families"]) == catalog["variant_count"]
    assert all(item["embedded_pattern_count"] >= 2 for item in catalog["families"])

    for path in pattern_documents:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        assert document["assignments"]
        assert document["patterns"]
        assert pattern_defaults().validate_cad_patterns_document(document)[0]


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
