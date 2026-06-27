# services/vectoplan-library/src/library/repositories/user_inventory_repository.py
"""
User inventory repository for vectoplan-library.

Diese Datei kapselt den direkten SQLAlchemy-/PostgreSQL-Zugriff für das
persistierte User-Inventar.

Ziel:

    routes/inventar_user.py
        -> services/user_inventory_service.py
        -> repositories/user_inventory_repository.py
        -> models/user_inventory.py
        -> PostgreSQL

Wichtig:

- Keine Flask-Route.
- Kein Rendering.
- Keine Response-Erzeugung.
- Keine Migration.
- Kein db.create_all().
- Keine Seed-Logik außerhalb expliziter ensure_* Methoden.
- Repository kennt SQLAlchemy und Models.
- Service/Route entscheiden, wann diese Funktionen aufgerufen werden.
- Phase 1 nutzt user_id=1 und 9 Slots.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


USER_INVENTORY_REPOSITORY_VERSION: Final[str] = "vectoplan_library.user_inventory.repository.v1"


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """
    Lädt die zentrale SQLAlchemy-Extension defensiv.
    """

    errors: list[str] = []

    for import_path in (
        "extensions",
        "src.extensions",
        "vectoplan_library.extensions",
    ):
        try:
            module = __import__(import_path, fromlist=["db"])
            db_obj = getattr(module, "db", None)

            if db_obj is not None:
                return db_obj

        except Exception as exc:
            errors.append(f"{import_path}: {type(exc).__name__}: {exc}")

    raise UserInventoryRepositoryError(
        "Could not import SQLAlchemy extension `db`. "
        f"Import attempts: {'; '.join(errors)}"
    )


@lru_cache(maxsize=1)
def _load_models() -> Any:
    """
    Lädt die User-Inventar-Models defensiv.
    """

    errors: list[str] = []

    for import_path in (
        "models",
        "src.models",
        "vectoplan_library.models",
    ):
        try:
            module = __import__(
                import_path,
                fromlist=[
                    "DEFAULT_INVENTORY_KEY",
                    "DEFAULT_SLOT_COUNT",
                    "DEFAULT_USER_ID",
                    "MAX_SLOT_INDEX",
                    "MIN_SLOT_INDEX",
                    "UserInventorySlot",
                    "UserInventoryState",
                    "normalize_slot_index",
                    "normalize_user_id",
                    "slot_key_for_index",
                    "utc_now",
                ],
            )

            required = (
                "DEFAULT_INVENTORY_KEY",
                "DEFAULT_SLOT_COUNT",
                "DEFAULT_USER_ID",
                "MAX_SLOT_INDEX",
                "MIN_SLOT_INDEX",
                "UserInventorySlot",
                "UserInventoryState",
                "normalize_slot_index",
                "normalize_user_id",
                "slot_key_for_index",
                "utc_now",
            )

            missing = [name for name in required if not hasattr(module, name)]
            if missing:
                errors.append(f"{import_path}: missing {', '.join(missing)}")
                continue

            return module

        except Exception as exc:
            errors.append(f"{import_path}: {type(exc).__name__}: {exc}")

    raise UserInventoryRepositoryError(
        "Could not import user inventory models. "
        f"Import attempts: {'; '.join(errors)}"
    )


def _db() -> Any:
    return _load_db()


def _models() -> Any:
    return _load_models()


# ---------------------------------------------------------------------------
# Exceptions / Result objects
# ---------------------------------------------------------------------------

class UserInventoryRepositoryError(RuntimeError):
    """Basisklasse für Repository-Fehler."""


class UserInventoryNotFoundError(UserInventoryRepositoryError):
    """Wird ausgelöst, wenn ein erwarteter Inventar-Datensatz fehlt."""


class UserInventoryValidationError(UserInventoryRepositoryError):
    """Wird ausgelöst, wenn Repository-Eingaben ungültig sind."""


@dataclass(frozen=True, slots=True)
class UserInventorySnapshot:
    """
    Kompakter Repository-Snapshot.

    Wird von Service/Route als stabile Zwischenstruktur genutzt.
    """

    user_id: int
    inventory_key: str
    active_slot_index: int
    slots: tuple[Any, ...]
    state: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        state_payload: dict[str, Any] = {}

        if self.state is not None and hasattr(self.state, "to_dict"):
            try:
                state_payload = self.state.to_dict(include_slots=False)
            except Exception:
                state_payload = {}

        return {
            "schema_version": USER_INVENTORY_REPOSITORY_VERSION,
            "user_id": self.user_id,
            "inventory_key": self.inventory_key,
            "active_slot_index": self.active_slot_index,
            "slot_count": len(self.slots),
            "state": state_payload,
            "slots": [
                slot.to_dict() if hasattr(slot, "to_dict") else {}
                for slot in self.slots
            ],
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_repository_user_id(value: Any | None = None) -> int:
    """
    Normalisiert User-ID.

    Phase 1:
    - Default user_id = 1
    """

    models = _models()
    default_user_id = getattr(models, "DEFAULT_USER_ID", 1)
    normalize_user_id = getattr(models, "normalize_user_id")

    return int(normalize_user_id(value if value is not None else default_user_id))


def normalize_repository_inventory_key(value: Any | None = None) -> str:
    """
    Normalisiert Inventory-Key.
    """

    models = _models()
    default_inventory_key = str(getattr(models, "DEFAULT_INVENTORY_KEY", "default"))

    try:
        text = str(value if value is not None else default_inventory_key).strip()
    except Exception:
        text = default_inventory_key

    if not text:
        text = default_inventory_key

    return text[:120]


def normalize_repository_slot_index(value: Any | None = None) -> int:
    """
    Normalisiert Slot-Index auf 1..9.
    """

    models = _models()
    normalize_slot_index = getattr(models, "normalize_slot_index")
    min_slot_index = int(getattr(models, "MIN_SLOT_INDEX", 1))

    return int(normalize_slot_index(value if value is not None else min_slot_index))


def get_default_slot_indices() -> tuple[int, ...]:
    """
    Gibt die kanonischen 9 Hotbar-Slot-Indizes zurück.
    """

    models = _models()
    min_slot_index = int(getattr(models, "MIN_SLOT_INDEX", 1))
    max_slot_index = int(getattr(models, "MAX_SLOT_INDEX", 9))

    return tuple(range(min_slot_index, max_slot_index + 1))


def _slot_key(slot_index: Any) -> str:
    models = _models()
    slot_key_for_index = getattr(models, "slot_key_for_index")
    return str(slot_key_for_index(slot_index))


def _now() -> Any:
    models = _models()
    utc_now = getattr(models, "utc_now")
    return utc_now()


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): _json_value(child) for key, child in value.items()}

    return {}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return _json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return _json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class UserInventoryRepository:
    """
    SQLAlchemy Repository für User-Inventar.

    Methoden mit Schreibzugriff nehmen `commit` entgegen.
    Bei `commit=False` kann ein Service mehrere Operationen in einer Transaktion
    bündeln.
    """

    def __init__(self, *, db: Any | None = None) -> None:
        self.db = db or _db()

    # ---------------------------------------------------------------------
    # Session helpers
    # ---------------------------------------------------------------------

    @property
    def session(self) -> Any:
        return self.db.session

    def flush(self) -> None:
        self.session.flush()

    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()

    def _finish_write(self, *, commit: bool) -> None:
        if commit:
            self.commit()
        else:
            self.flush()

    # ---------------------------------------------------------------------
    # Base queries
    # ---------------------------------------------------------------------

    def get_state(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
    ) -> Any | None:
        """
        Lädt den UserInventoryState oder None.
        """

        models = _models()
        UserInventoryState = getattr(models, "UserInventoryState")

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)

        return (
            self.session.query(UserInventoryState)
            .filter(
                UserInventoryState.user_id == normalized_user_id,
                UserInventoryState.inventory_key == normalized_inventory_key,
            )
            .one_or_none()
        )

    def get_slot(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
        slot_index: Any,
    ) -> Any | None:
        """
        Lädt einen Slot oder None.
        """

        models = _models()
        UserInventorySlot = getattr(models, "UserInventorySlot")

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)
        normalized_slot_index = normalize_repository_slot_index(slot_index)

        return (
            self.session.query(UserInventorySlot)
            .filter(
                UserInventorySlot.user_id == normalized_user_id,
                UserInventorySlot.inventory_key == normalized_inventory_key,
                UserInventorySlot.slot_index == normalized_slot_index,
            )
            .one_or_none()
        )

    def list_slots(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
    ) -> tuple[Any, ...]:
        """
        Lädt alle Slots für User + Inventory-Key.
        """

        models = _models()
        UserInventorySlot = getattr(models, "UserInventorySlot")

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)

        slots = (
            self.session.query(UserInventorySlot)
            .filter(
                UserInventorySlot.user_id == normalized_user_id,
                UserInventorySlot.inventory_key == normalized_inventory_key,
            )
            .order_by(UserInventorySlot.slot_index.asc())
            .all()
        )

        return tuple(slots or ())

    # ---------------------------------------------------------------------
    # Ensure / creation
    # ---------------------------------------------------------------------

    def ensure_default_inventory(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
        active_slot_index: Any | None = None,
        commit: bool = True,
    ) -> UserInventorySnapshot:
        """
        Stellt sicher, dass State + 9 Slots existieren.

        Existierende Slots werden nicht überschrieben.
        Fehlende Slots werden leer ergänzt.
        """

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)
        normalized_active_slot_index = normalize_repository_slot_index(active_slot_index)

        try:
            state = self.get_state(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
            )

            if state is None:
                state = self._create_state(
                    user_id=normalized_user_id,
                    inventory_key=normalized_inventory_key,
                    active_slot_index=normalized_active_slot_index,
                )
                self.session.add(state)
                self.flush()
            else:
                state.active_slot_index = normalize_repository_slot_index(
                    getattr(state, "active_slot_index", normalized_active_slot_index)
                )
                state.last_loaded_at = _now()
                state.touch()

            slots_by_index = {
                int(slot.slot_index): slot
                for slot in self.list_slots(
                    user_id=normalized_user_id,
                    inventory_key=normalized_inventory_key,
                )
            }

            active_index = normalize_repository_slot_index(
                getattr(state, "active_slot_index", normalized_active_slot_index)
            )

            for slot_index in get_default_slot_indices():
                if slot_index not in slots_by_index:
                    slot = self._create_empty_slot(
                        user_id=normalized_user_id,
                        inventory_key=normalized_inventory_key,
                        slot_index=slot_index,
                        state=state,
                        selected=slot_index == active_index,
                    )
                    self.session.add(slot)
                    slots_by_index[slot_index] = slot
                else:
                    slot = slots_by_index[slot_index]
                    slot.state = state
                    slot.state_id = getattr(state, "id", None)
                    slot.user_id = normalized_user_id
                    slot.inventory_key = normalized_inventory_key
                    slot.slot_key = _slot_key(slot_index)
                    slot.sort_order = slot_index
                    slot.selected = slot_index == active_index
                    if slot.selected:
                        slot.selected_at = _now()
                    slot.touch()

            selected_slot = slots_by_index.get(active_index)
            self._sync_state_selection(state=state, selected_slot=selected_slot, slot_index=active_index)

            self._finish_write(commit=commit)

            slots = tuple(slots_by_index[index] for index in sorted(slots_by_index))

            return UserInventorySnapshot(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
                active_slot_index=active_index,
                state=state,
                slots=slots,
            )

        except Exception:
            self.rollback()
            raise

    def _create_state(
        self,
        *,
        user_id: int,
        inventory_key: str,
        active_slot_index: int,
    ) -> Any:
        models = _models()
        UserInventoryState = getattr(models, "UserInventoryState")

        if hasattr(UserInventoryState, "create_default"):
            return UserInventoryState.create_default(
                user_id=user_id,
                inventory_key=inventory_key,
                active_slot_index=active_slot_index,
                metadata={
                    "source": "repository.ensure_default_inventory",
                    "repository_version": USER_INVENTORY_REPOSITORY_VERSION,
                },
            )

        return UserInventoryState(
            user_id=user_id,
            inventory_key=inventory_key,
            active_slot_index=active_slot_index,
            last_selected_slot_index=active_slot_index,
            last_selected_slot_key=_slot_key(active_slot_index),
            slot_count=len(get_default_slot_indices()),
            selected_at=_now(),
            last_loaded_at=_now(),
            metadata_json={
                "source": "repository.ensure_default_inventory",
                "repository_version": USER_INVENTORY_REPOSITORY_VERSION,
            },
        )

    def _create_empty_slot(
        self,
        *,
        user_id: int,
        inventory_key: str,
        slot_index: int,
        state: Any | None = None,
        selected: bool = False,
    ) -> Any:
        models = _models()
        UserInventorySlot = getattr(models, "UserInventorySlot")

        if hasattr(UserInventorySlot, "create_empty"):
            return UserInventorySlot.create_empty(
                user_id=user_id,
                inventory_key=inventory_key,
                slot_index=slot_index,
                state=state,
                selected=selected,
                metadata={
                    "source": "repository.ensure_default_inventory",
                    "repository_version": USER_INVENTORY_REPOSITORY_VERSION,
                },
            )

        return UserInventorySlot(
            state=state,
            state_id=getattr(state, "id", None),
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=slot_index,
            slot_key=_slot_key(slot_index),
            empty=True,
            selected=selected,
            quantity=0,
            sort_order=slot_index,
            selected_at=_now() if selected else None,
            metadata_json={
                "source": "repository.ensure_default_inventory",
                "repository_version": USER_INVENTORY_REPOSITORY_VERSION,
            },
        )

    # ---------------------------------------------------------------------
    # Selection
    # ---------------------------------------------------------------------

    def select_slot(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
        slot_index: Any,
        commit: bool = True,
    ) -> UserInventorySnapshot:
        """
        Wählt einen Slot aus und speichert die Auswahl persistent.
        """

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)
        normalized_slot_index = normalize_repository_slot_index(slot_index)

        try:
            snapshot = self.ensure_default_inventory(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
                active_slot_index=normalized_slot_index,
                commit=False,
            )

            slots = list(snapshot.slots)
            selected_slot = None

            for slot in slots:
                is_selected = int(slot.slot_index) == normalized_slot_index
                slot.selected = is_selected
                slot.slot_key = _slot_key(slot.slot_index)
                slot.sort_order = int(slot.slot_index)

                if is_selected:
                    slot.selected_at = _now()
                    selected_slot = slot

                slot.touch()

            state = snapshot.state or self.get_state(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
            )

            self._sync_state_selection(
                state=state,
                selected_slot=selected_slot,
                slot_index=normalized_slot_index,
            )

            self._finish_write(commit=commit)

            slots = tuple(sorted(slots, key=lambda slot: int(slot.slot_index)))

            return UserInventorySnapshot(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
                active_slot_index=normalized_slot_index,
                state=state,
                slots=slots,
            )

        except Exception:
            self.rollback()
            raise

    def _sync_state_selection(
        self,
        *,
        state: Any | None,
        selected_slot: Any | None,
        slot_index: int,
    ) -> None:
        """
        Synchronisiert State-Felder mit ausgewähltem Slot.
        """

        if state is None:
            return

        normalized_slot_index = normalize_repository_slot_index(slot_index)

        if hasattr(state, "select_slot"):
            state.select_slot(selected_slot, slot_index=normalized_slot_index)
            return

        state.active_slot_index = normalized_slot_index
        state.last_selected_slot_index = normalized_slot_index
        state.last_selected_slot_key = _slot_key(normalized_slot_index)
        state.selected_at = _now()

        if selected_slot is not None:
            state.last_selected_item_db_id = getattr(selected_slot, "item_db_id", None)
            state.last_selected_vplib_uid = getattr(selected_slot, "vplib_uid", None)
            state.last_selected_family_id = getattr(selected_slot, "family_id", None)
            state.last_selected_package_id = getattr(selected_slot, "package_id", None)
            state.last_selected_variant_id = getattr(selected_slot, "variant_id", None)
            state.last_selected_label = getattr(selected_slot, "label", None)
            state.last_selected_object_kind = getattr(selected_slot, "object_kind", None)
            state.last_selected_domain = getattr(selected_slot, "domain", None)
            state.last_selected_category = getattr(selected_slot, "category", None)
            state.last_selected_subcategory = getattr(selected_slot, "subcategory", None)
            state.last_selected_taxonomy_path = getattr(selected_slot, "taxonomy_path", None)

        if hasattr(state, "touch"):
            state.touch()

    # ---------------------------------------------------------------------
    # Slot item mutations
    # ---------------------------------------------------------------------

    def set_slot_item(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
        slot_index: Any,
        item_payload: Mapping[str, Any] | None,
        select_after_set: bool = True,
        commit: bool = True,
    ) -> UserInventorySnapshot:
        """
        Setzt oder ersetzt den Inhalt eines Slots.

        item_payload darf leer sein; dann wird der Slot geleert.
        """

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)
        normalized_slot_index = normalize_repository_slot_index(slot_index)
        normalized_payload = _json_mapping(item_payload)

        try:
            snapshot = self.ensure_default_inventory(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
                active_slot_index=normalized_slot_index,
                commit=False,
            )

            slot = self.get_slot(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
                slot_index=normalized_slot_index,
            )

            if slot is None:
                raise UserInventoryNotFoundError(
                    f"Slot {normalized_slot_index} for user_id={normalized_user_id} "
                    f"inventory={normalized_inventory_key!r} was not found after ensure_default_inventory()."
                )

            if normalized_payload:
                self._assign_slot_item(slot, normalized_payload)
            else:
                self._clear_slot_item(slot)

            if select_after_set:
                snapshot = self.select_slot(
                    user_id=normalized_user_id,
                    inventory_key=normalized_inventory_key,
                    slot_index=normalized_slot_index,
                    commit=False,
                )
            else:
                snapshot = self.get_snapshot(
                    user_id=normalized_user_id,
                    inventory_key=normalized_inventory_key,
                    ensure=True,
                    commit=False,
                )

            self._finish_write(commit=commit)

            return snapshot

        except Exception:
            self.rollback()
            raise

    def clear_slot(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
        slot_index: Any,
        select_after_clear: bool = True,
        commit: bool = True,
    ) -> UserInventorySnapshot:
        """
        Leert einen Slot.
        """

        return self.set_slot_item(
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=slot_index,
            item_payload={},
            select_after_set=select_after_clear,
            commit=commit,
        )

    def _assign_slot_item(self, slot: Any, item_payload: Mapping[str, Any]) -> None:
        if hasattr(slot, "assign_item"):
            slot.assign_item(item_payload)
            return

        slot.item_db_id = _optional_int(item_payload.get("item_db_id", item_payload.get("id")))
        slot.vplib_uid = _optional_string(item_payload.get("vplib_uid"), max_length=80)
        slot.family_id = _optional_string(item_payload.get("family_id"), max_length=255)
        slot.package_id = _optional_string(item_payload.get("package_id"), max_length=255)
        slot.variant_id = _optional_string(item_payload.get("variant_id"), max_length=160)
        slot.label = _optional_string(item_payload.get("label", item_payload.get("name")), max_length=255)
        slot.description = _optional_string(item_payload.get("description"))
        slot.object_kind = _optional_string(item_payload.get("object_kind"), max_length=80)
        slot.domain = _optional_string(item_payload.get("domain"), max_length=80)
        slot.category = _optional_string(item_payload.get("category"), max_length=120)
        slot.subcategory = _optional_string(item_payload.get("subcategory"), max_length=120)
        slot.quantity = max(1, _optional_int(item_payload.get("quantity")) or 1)
        slot.empty = False
        slot.assigned_at = _now()
        slot.cleared_at = None
        slot.payload = _json_mapping(item_payload)

        if hasattr(slot, "touch"):
            slot.touch()

    def _clear_slot_item(self, slot: Any) -> None:
        if hasattr(slot, "clear_item"):
            slot.clear_item()
            return

        slot.item_db_id = None
        slot.vplib_uid = None
        slot.family_id = None
        slot.package_id = None
        slot.variant_id = None
        slot.label = None
        slot.description = None
        slot.object_kind = None
        slot.domain = None
        slot.category = None
        slot.subcategory = None
        slot.taxonomy_path = None
        slot.quantity = 0
        slot.empty = True
        slot.assigned_at = None
        slot.cleared_at = _now()
        slot.payload = {}

        if hasattr(slot, "touch"):
            slot.touch()

    # ---------------------------------------------------------------------
    # Snapshot / serialization
    # ---------------------------------------------------------------------

    def get_snapshot(
        self,
        *,
        user_id: Any | None = None,
        inventory_key: Any | None = None,
        ensure: bool = True,
        commit: bool = True,
    ) -> UserInventorySnapshot:
        """
        Lädt einen vollständigen Inventar-Snapshot.
        """

        normalized_user_id = normalize_repository_user_id(user_id)
        normalized_inventory_key = normalize_repository_inventory_key(inventory_key)

        if ensure:
            return self.ensure_default_inventory(
                user_id=normalized_user_id,
                inventory_key=normalized_inventory_key,
                commit=commit,
            )

        state = self.get_state(
            user_id=normalized_user_id,
            inventory_key=normalized_inventory_key,
        )

        slots = self.list_slots(
            user_id=normalized_user_id,
            inventory_key=normalized_inventory_key,
        )

        active_slot_index = normalize_repository_slot_index(
            getattr(state, "active_slot_index", None)
            if state is not None
            else None
        )

        return UserInventorySnapshot(
            user_id=normalized_user_id,
            inventory_key=normalized_inventory_key,
            active_slot_index=active_slot_index,
            state=state,
            slots=slots,
        )

    def get_health(self) -> dict[str, Any]:
        """
        Gibt einen Repository-Health-Snapshot ohne Schreibzugriff zurück.
        """

        try:
            db = self.db
            models = _models()

            return {
                "ok": True,
                "healthy": True,
                "schema_version": USER_INVENTORY_REPOSITORY_VERSION,
                "database_available": db is not None,
                "session_available": getattr(db, "session", None) is not None,
                "models_available": True,
                "state_model": getattr(getattr(models, "UserInventoryState", None), "__name__", None),
                "slot_model": getattr(getattr(models, "UserInventorySlot", None), "__name__", None),
                "default_user_id": int(getattr(models, "DEFAULT_USER_ID", 1)),
                "default_inventory_key": str(getattr(models, "DEFAULT_INVENTORY_KEY", "default")),
                "slot_indices": list(get_default_slot_indices()),
            }

        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "schema_version": USER_INVENTORY_REPOSITORY_VERSION,
                "database_available": False,
                "models_available": False,
                "error": str(exc),
            }


# ---------------------------------------------------------------------------
# Small helper functions
# ---------------------------------------------------------------------------

def _optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    try:
        if value is None:
            return None

        text = str(value).strip()
        if not text:
            return None

        if max_length is not None and max_length > 0:
            return text[:max_length]

        return text

    except Exception:
        return None


def _optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None

        return int(value)

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Default repository helpers
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_user_inventory_repository() -> UserInventoryRepository:
    """
    Gibt eine gecachte Repository-Instanz zurück.

    Die Instanz hält keine eigene DB-Verbindung, sondern nutzt db.session.
    """

    return UserInventoryRepository()


def clear_repository_caches() -> None:
    """
    Leert interne Import-/Repository-Caches.
    """

    for cached_function in (
        _load_db,
        _load_models,
        get_user_inventory_repository,
    ):
        try:
            cached_function.cache_clear()
        except Exception:
            pass


def get_user_inventory_repository_health() -> dict[str, Any]:
    """
    Health-Funktion für App-/Service-Diagnose.
    """

    try:
        return get_user_inventory_repository().get_health()
    except Exception as exc:
        return {
            "ok": False,
            "healthy": False,
            "schema_version": USER_INVENTORY_REPOSITORY_VERSION,
            "error": str(exc),
        }


__all__ = [
    "USER_INVENTORY_REPOSITORY_VERSION",
    "UserInventoryNotFoundError",
    "UserInventoryRepository",
    "UserInventoryRepositoryError",
    "UserInventorySnapshot",
    "UserInventoryValidationError",
    "clear_repository_caches",
    "get_default_slot_indices",
    "get_user_inventory_repository",
    "get_user_inventory_repository_health",
    "normalize_repository_inventory_key",
    "normalize_repository_slot_index",
    "normalize_repository_user_id",
]