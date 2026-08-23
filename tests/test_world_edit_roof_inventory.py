from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_creative_inventory_exposes_complete_roof_and_polygon_room_settings():
    template = (
        SERVICE_ROOT / "templates/inventar/creative-inventar.html"
    ).read_text(encoding="utf-8")
    runtime = (
        SERVICE_ROOT / "static/js/inventar/creative-library.js"
    ).read_text(encoding="utf-8")

    assert 'id: "roof"' in runtime
    assert "data-world-edit-roof-settings" in template
    assert "data-world-edit-config-room-height" in template
    for selector in (
        "roof-type",
        "roof-pitch",
        "roof-eaves-height",
        "roof-ridge-direction",
        "roof-overhang-north",
        "roof-edge-overhangs",
        "roof-skin-thickness",
        "roof-rafter-spacing",
        "roof-purlin-spacing",
        "roof-plateau-ratio",
        "roof-mansard-break",
        "roof-hip-end-ratio",
        "roof-barrel-segments",
        "roof-sawtooth-count",
    ):
        assert f"data-world-edit-config-{selector}" in template
        assert selector in runtime

    assert "roofParameters: roofParameters" in runtime
    assert "roomHeight: state.worldEditSettings.roomHeight" in runtime
    assert '["selection", "copy-transform", "cut-transform", "room", "roof", "tentacle"]' in runtime
