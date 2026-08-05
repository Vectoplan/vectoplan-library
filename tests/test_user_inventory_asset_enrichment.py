"""Regression tests for current published assets in persisted user slots."""

from __future__ import annotations

from typing import Any

from src.library.services import user_inventory_service as service


def test_legacy_slots_are_hydrated_from_current_published_revision(monkeypatch: Any) -> None:
    calls: list[Any] = []

    class PublishedService:
        def get_item(self, item_ref: Any, **_: Any) -> dict[str, Any]:
            calls.append(item_ref)
            return {
                "ok": True,
                "payload": {
                    "item": {
                        "metadata": {"published": True},
                        "assets": [
                            {
                                "asset_kind": "texture",
                                "role": "albedo",
                                "uri": "/static/textures/materials/steel.webp",
                                "checksum": "texture-sha",
                            }
                        ],
                    }
                },
            }

    monkeypatch.setattr(service, "_published_service", lambda: PublishedService())
    slots = [
        {
            "slot_index": 2,
            "item_db_id": 9,
            "empty": False,
            "assets": [],
            "metadata": {"variant": True},
            "payload": {},
        },
        {
            "slot_index": 3,
            "item_db_id": 9,
            "empty": False,
            "assets": [],
            "payload": {},
        },
    ]

    enriched = service.enrich_slots_with_published_assets(slots)

    assert calls == [9]
    assert enriched[0]["assets"][0]["checksum"] == "texture-sha"
    assert enriched[0]["preview"]["url"] == "/static/textures/materials/steel.webp"
    assert enriched[0]["metadata"] == {"published": True, "variant": True}
    assert enriched[0]["payload"]["assets"] == enriched[0]["assets"]


def test_existing_slot_assets_are_not_overwritten(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        service,
        "_published_service",
        lambda: (_ for _ in ()).throw(AssertionError("published read not expected")),
    )
    existing = [{"uri": "https://assets.example/existing.webp"}]

    enriched = service.enrich_slots_with_published_assets(
        [{"slot_index": 1, "item_db_id": 4, "empty": False, "assets": existing}]
    )

    assert enriched[0]["assets"] == existing