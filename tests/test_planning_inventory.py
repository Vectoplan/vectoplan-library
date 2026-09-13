from types import SimpleNamespace

from src.library.inventory_defaults import planning_default_item, is_world_edit_item
from src.library.repositories.user_inventory_repository import UserInventoryRepository
from src.library.services import user_inventory_service as service


class MemoryInventory(UserInventoryRepository):
    def __init__(self):
        self.saved_state = None
        self.saved_slots = []
        self.db = SimpleNamespace(session=SimpleNamespace(add=lambda obj: None, flush=lambda: None,
                                                          commit=lambda: None, rollback=lambda: None))

    def get_state(self, **kwargs):
        return self.saved_state

    def list_slots(self, **kwargs):
        return self.saved_slots

    def _create_state(self, **kwargs):
        self.saved_state = SimpleNamespace(**kwargs, touch=lambda: None)
        return self.saved_state

    def _create_empty_slot(self, **kwargs):
        slot = SimpleNamespace(**kwargs, empty=True, touch=lambda: None)
        self.saved_slots.append(slot)
        return slot

    def _assign_slot_item(self, slot, payload):
        slot.empty = False
        slot.item = dict(payload)


def test_planning_seeds_nine_tools_once_and_keeps_user_edits():
    repository = MemoryInventory()
    first = repository.ensure_default_inventory(user_id=1, inventory_key="planning")
    assert first.active_slot_index == 1
    assert len(first.slots) == 9
    assert all(is_world_edit_item(slot.item) for slot in first.slots)
    assert first.slots[1].item["world_edit_tool"] == "room"
    first.slots[0].empty = True
    first.slots[0].item = {}
    first.slots[1].item = planning_default_item(4)
    second = repository.ensure_default_inventory(user_id=1, inventory_key="planning")
    assert second.slots[0].empty
    assert second.slots[1].item["world_edit_tool"] == "roof"


def test_ego_inventory_does_not_receive_planning_defaults():
    snapshot = MemoryInventory().ensure_default_inventory(user_id=1, inventory_key="default")
    assert all(slot.empty for slot in snapshot.slots)


def test_planning_cannot_receive_generic_blocks(monkeypatch):
    monkeypatch.setattr(service, "_repository", lambda: (_ for _ in ()).throw(AssertionError("write attempted")))
    result = service.set_slot_response(1, {"inventory_key": "planning", "item": {
        "family_id": "brick", "object_kind": "block", "label": "Brick",
    }})
    assert not result["ok"]
    assert "WorldEdit" in str(result)


def test_planning_does_not_reinsert_terrain(monkeypatch):
    monkeypatch.setattr(service, "_repository", lambda: (_ for _ in ()).throw(AssertionError("write attempted")))
    snapshot = SimpleNamespace(slots=(SimpleNamespace(empty=True),))
    assert service._ensure_terrain_test_item(snapshot, user_id=1, inventory_key="planning") is snapshot
