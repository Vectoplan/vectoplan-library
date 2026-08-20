from __future__ import annotations

from library.services import library_create_service


def _payload(**overrides):
    payload = {
        "family_name": "Parametric test object",
        "family_description": "Generated object used to verify declarative geometry.",
        "domain": "hochbau",
        "category": "oeffnungen",
        "subcategory": "innentueren",
        "object_kind": "catalog_object",
        "family_profile_id": "simple_cell_block",
        "variant_profile_id": "simple_cell_block.v1",
        "primitive_shape": "frame",
        "geometry_width": 1,
        "geometry_height": 2,
        "geometry_depth": 0.12,
        "geometry_unit": "m",
    }
    payload.update(overrides)
    return payload


def test_hinged_door_is_two_cells_high_and_has_interaction_document():
    result = library_create_service.build_package_plan(
        _payload(geometry_profile_id="hinged_door", interaction_kind="swing_door"),
        include_documents=True,
    )

    assert result.ok is True
    documents = result.data["documents"]
    assert documents["editor/placement.json"]["editor_block"]["cells"] == {"x": 1, "y": 2, "z": 1}
    assert documents["render/geometry.json"]["profile_id"] == "hinged_door"
    assert documents["dynamic/interactions.json"]["openable"] is True
    assert documents["dynamic/interactions.json"]["states"] == ["closed", "open"]


def test_half_block_and_composite_parts_are_scanner_readable():
    parts = [
        {
            "id": "belt",
            "shape": "box",
            "size": [1, 0.12, 0.7],
            "position": [0, 0.2, 0],
            "color": "#334155",
        }
    ]
    result = library_create_service.build_package_plan(
        _payload(
            primitive_shape="composite",
            geometry_profile_id="composite_parts",
            category="ausbau",
            subcategory="trockenbau",
            object_kind="multi_cell_module",
            block_height_mode="half",
            geometry_parts=parts,
        ),
        include_documents=True,
    )

    assert result.ok is True
    documents = result.data["documents"]
    geometry = documents["render/geometry.json"]
    assert geometry["height_mode"] == "half"
    assert geometry["height_fraction"] == 0.5
    assert geometry["parts"][0]["part_id"] == "belt"
    default_values = documents["variants/default.json"]["definition_values"]
    assert default_values["geometry.profile_id"] == "composite_parts"
    assert '"part_id":"belt"' in default_values["geometry.parts_json"]
