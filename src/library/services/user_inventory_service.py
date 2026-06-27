# services/vectoplan-library/src/library/services/user_inventory_service.py
"""
User inventory service for vectoplan-library.

Diese Datei kapselt die fachliche Service-Logik für das persistierte
User-Inventar.

Ziel:

    routes/inventar_user.py
        -> user_inventory_service.py
        -> user_inventory_repository.py
        -> models/user_inventory.py
        -> PostgreSQL

Aufgaben:

- Default user_id=1 für Phase 1.
- Default inventory_key="default".
- 9-Slot-Hotbar sicherstellen.
- Inventarzustand laden.
- Slot per Mausrad-/Frontend-Auswahl speichern.
- Slot-Inhalt setzen.
- Slot-Inhalt löschen.
- Einheitliche JSON-kompatible Response-Payloads erzeugen.

Wichtig:

- Keine Flask-Imports.
- Keine Route.
- Kein Rendering.
- Keine Migration.
- Kein db.create_all().
- Kein direkter SQLAlchemy-Code außerhalb des Repository.
- Keine Scanner-/Validation-/Create-Logik.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Final, Mapping


USER_INVENTORY_SERVICE_VERSION: Final[str] = "vectoplan_library.user_inventory.service.v1"
USER_INVENTORY_COMPONENT: Final[str] = "user-inventory-service"

DEFAULT_USER_ID: Final[int] = 1
DEFAULT_INVENTORY_KEY: Final[str] = "default"
DEFAULT_SLOT_COUNT: Final[int] = 9
MIN_SLOT_INDEX: Final[int] = 1
MAX_SLOT_INDEX: Final[int] = 9

STATUS_OK: Final[str] = "ok"
STATUS_READY: Final[str] = "ready"
STATUS_SELECTED: Final[str] = "slot_selected"
STATUS_SLOT_SET: Final[str] = "slot_set"
STATUS_SLOT_CLEARED: Final[str] = "slot_cleared"
STATUS_CACHE_CLEARED: Final[str] = "cache_cleared"
STATUS_HEALTHY: Final[str] = "healthy"
STATUS_ERROR: Final[str] = "error"


# ---------------------------------------------------------------------------
# Lazy repository imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_repository_module() -> Any:
    """
    Lädt das User-Inventory-Repository defensiv.

    Unterstützt mehrere Importpfade, weil der Service lokal, in Docker, über
    Flask-Migrate und in Tests unterschiedlich gestartet werden kann.
    """

    errors: list[str] = []

    for import_path in (
        "library.repositories.user_inventory_repository",
        "src.library.repositories.user_inventory_repository",
        "vectoplan_library.library.repositories.user_inventory_repository",
        "repositories.user_inventory_repository",
    ):
        try:
            module = __import__(
                import_path,
                fromlist=[
                    "UserInventoryRepository",
                    "UserInventoryRepositoryError",
                    "get_user_inventory_repository",
                    "get_user_inventory_repository_health",
                    "clear_repository_caches",
                    "normalize_repository_inventory_key",
                    "normalize_repository_slot_index",
                    "normalize_repository_user_id",
                ],
            )

            required = (
                "UserInventoryRepository",
                "get_user_inventory_repository",
                "get_user_inventory_repository_health",
                "clear_repository_caches",
                "normalize_repository_inventory_key",
                "normalize_repository_slot_index",
                "normalize_repository_user_id",
            )

            missing = [name for name in required if not hasattr(module, name)]
            if missing:
                errors.append(f"{import_path}: missing {', '.join(missing)}")
                continue

            return module

        except Exception as exc:
            errors.append(f"{import_path}: {type(exc).__name__}: {exc}")

    raise UserInventoryServiceError(
        "Could not import user inventory repository. "
        f"Import attempts: {'; '.join(errors)}"
    )


def _repository_module() -> Any:
    return _load_repository_module()


def _repository() -> Any:
    module = _repository_module()
    return module.get_user_inventory_repository()


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class UserInventoryServiceError(RuntimeError):
    """Basisklasse für Service-Fehler."""


class UserInventoryServiceValidationError(UserInventoryServiceError):
    """Wird ausgelöst, wenn Service-Eingaben ungültig sind."""


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

def get_inventory_response(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Lädt das User-Inventar und stellt 9 Slots sicher.

    Erwarteter Payload:
        {
            "user_id": 1,
            "inventory_key": "default"
        }
    """

    request_payload = normalize_payload(payload)

    try:
        user_id = normalize_user_id(request_payload.get("user_id"))
        inventory_key = normalize_inventory_key(request_payload.get("inventory_key"))

        snapshot = _repository().get_snapshot(
            user_id=user_id,
            inventory_key=inventory_key,
            ensure=True,
            commit=True,
        )

        return success_response(
            status=STATUS_READY,
            route="inventory",
            data=inventory_payload_from_snapshot(snapshot),
            info=[
                info_item(
                    code="inventory_ready",
                    message="User-Inventar wurde geladen.",
                    details={
                        "user_id": user_id,
                        "inventory_key": inventory_key,
                    },
                )
            ],
        )

    except Exception as exc:
        return failure_response(
            route="inventory",
            code="inventory_failed",
            message="User-Inventar konnte nicht geladen werden.",
            exc=exc,
            http_status=500,
        )


def select_slot_response(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Speichert den aktiven Slot.

    Erwarteter Payload:
        {
            "user_id": 1,
            "inventory_key": "default",
            "slot_index": 3
        }
    """

    request_payload = normalize_payload(payload)

    try:
        user_id = normalize_user_id(request_payload.get("user_id"))
        inventory_key = normalize_inventory_key(request_payload.get("inventory_key"))
        slot_index = normalize_slot_index(request_payload.get("slot_index"))

        snapshot = _repository().select_slot(
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=slot_index,
            commit=True,
        )

        return success_response(
            status=STATUS_SELECTED,
            route="select-slot",
            data=inventory_payload_from_snapshot(snapshot),
            info=[
                info_item(
                    code="slot_selected",
                    message="Inventar-Slot wurde ausgewählt.",
                    details={
                        "user_id": user_id,
                        "inventory_key": inventory_key,
                        "slot_index": slot_index,
                    },
                )
            ],
        )

    except Exception as exc:
        return failure_response(
            route="select-slot",
            code="select_slot_failed",
            message="Inventar-Slot konnte nicht ausgewählt werden.",
            exc=exc,
            http_status=422,
        )


def set_slot_response(
    slot_index: Any,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Setzt oder ersetzt den Inhalt eines Slots.

    Erwarteter Payload:
        {
            "user_id": 1,
            "inventory_key": "default",
            "item": {...},
            "select": true
        }

    Tolerant:
    - Wenn kein `item` enthalten ist, wird der komplette Payload als Item-Payload
      interpretiert, sofern er Item-ähnliche Felder enthält.
    """

    request_payload = normalize_payload(payload)

    try:
        user_id = normalize_user_id(request_payload.get("user_id"))
        inventory_key = normalize_inventory_key(request_payload.get("inventory_key"))
        normalized_slot_index = normalize_slot_index(slot_index)
        select_after_set = normalize_bool(request_payload.get("select"), default=True)

        item_payload = extract_item_payload(request_payload)

        snapshot = _repository().set_slot_item(
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=normalized_slot_index,
            item_payload=item_payload,
            select_after_set=select_after_set,
            commit=True,
        )

        return success_response(
            status=STATUS_SLOT_SET if item_payload else STATUS_SLOT_CLEARED,
            route="set-slot",
            data=inventory_payload_from_snapshot(snapshot),
            info=[
                info_item(
                    code="slot_set" if item_payload else "slot_cleared",
                    message=(
                        "Inventar-Slot wurde gesetzt."
                        if item_payload
                        else "Inventar-Slot wurde geleert."
                    ),
                    details={
                        "user_id": user_id,
                        "inventory_key": inventory_key,
                        "slot_index": normalized_slot_index,
                        "selected": select_after_set,
                    },
                )
            ],
        )

    except Exception as exc:
        return failure_response(
            route="set-slot",
            code="set_slot_failed",
            message="Inventar-Slot konnte nicht gesetzt werden.",
            exc=exc,
            http_status=422,
        )


def clear_slot_response(
    slot_index: Any,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Leert den Inhalt eines Slots.

    Erwarteter Payload:
        {
            "user_id": 1,
            "inventory_key": "default",
            "select": true
        }
    """

    request_payload = normalize_payload(payload)

    try:
        user_id = normalize_user_id(request_payload.get("user_id"))
        inventory_key = normalize_inventory_key(request_payload.get("inventory_key"))
        normalized_slot_index = normalize_slot_index(slot_index)
        select_after_clear = normalize_bool(request_payload.get("select"), default=True)

        snapshot = _repository().clear_slot(
            user_id=user_id,
            inventory_key=inventory_key,
            slot_index=normalized_slot_index,
            select_after_clear=select_after_clear,
            commit=True,
        )

        return success_response(
            status=STATUS_SLOT_CLEARED,
            route="clear-slot",
            data=inventory_payload_from_snapshot(snapshot),
            info=[
                info_item(
                    code="slot_cleared",
                    message="Inventar-Slot wurde geleert.",
                    details={
                        "user_id": user_id,
                        "inventory_key": inventory_key,
                        "slot_index": normalized_slot_index,
                        "selected": select_after_clear,
                    },
                )
            ],
        )

    except Exception as exc:
        return failure_response(
            route="clear-slot",
            code="clear_slot_failed",
            message="Inventar-Slot konnte nicht geleert werden.",
            exc=exc,
            http_status=422,
        )


def clear_cache_response() -> dict[str, Any]:
    """
    Leert Service-/Repository-Caches.

    Nützlich für Entwicklungs-Restarts, Tests und Hot-Reload-Szenarien.
    """

    warnings: list[dict[str, Any]] = []

    try:
        try:
            _load_repository_module.cache_clear()
        except Exception as exc:
            warnings.append(
                warning_item(
                    code="service_cache_clear_warning",
                    message="Service-Repository-Importcache konnte nicht geleert werden.",
                    details={"exception": str(exc)},
                )
            )

        try:
            module = _repository_module()
            clear_repository_caches = getattr(module, "clear_repository_caches", None)
            if callable(clear_repository_caches):
                clear_repository_caches()
        except Exception as exc:
            warnings.append(
                warning_item(
                    code="repository_cache_clear_warning",
                    message="Repository-Caches konnten nicht vollständig geleert werden.",
                    details={"exception": str(exc)},
                )
            )

        return success_response(
            status=STATUS_CACHE_CLEARED,
            route="cache-clear",
            data={
                "cache_cleared": True,
            },
            warnings=warnings,
            info=[
                info_item(
                    code="cache_cleared",
                    message="User-Inventar-Caches wurden geleert.",
                )
            ],
        )

    except Exception as exc:
        return failure_response(
            route="cache-clear",
            code="cache_clear_failed",
            message="User-Inventar-Caches konnten nicht geleert werden.",
            exc=exc,
            http_status=500,
        )


def get_service_health_response() -> dict[str, Any]:
    """
    Health-Response für Route, Repository und Model-Anbindung.
    """

    try:
        repository_health = {}

        try:
            module = _repository_module()
            get_repository_health = getattr(module, "get_user_inventory_repository_health", None)
            if callable(get_repository_health):
                repository_health = normalize_json_mapping(get_repository_health())
            else:
                repository_health = _repository().get_health()
        except Exception as exc:
            repository_health = {
                "ok": False,
                "healthy": False,
                "error": str(exc),
            }

        repository_ok = bool(repository_health.get("ok", False) or repository_health.get("healthy", False))

        return success_response(
            status=STATUS_HEALTHY if repository_ok else "degraded",
            route="health",
            data={
                "component": USER_INVENTORY_COMPONENT,
                "version": USER_INVENTORY_SERVICE_VERSION,
                "default_user_id": DEFAULT_USER_ID,
                "default_inventory_key": DEFAULT_INVENTORY_KEY,
                "slot_count": DEFAULT_SLOT_COUNT,
                "min_slot_index": MIN_SLOT_INDEX,
                "max_slot_index": MAX_SLOT_INDEX,
                "repository": repository_health,
            },
            warnings=[] if repository_ok else [
                warning_item(
                    code="repository_not_healthy",
                    message="User-Inventar-Repository ist nicht vollständig healthy.",
                    details=repository_health,
                )
            ],
            http_status=200 if repository_ok else 503,
        )

    except Exception as exc:
        return failure_response(
            route="health",
            code="health_failed",
            message="User-Inventar-Health konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )


# ---------------------------------------------------------------------------
# Snapshot serialization
# ---------------------------------------------------------------------------

def inventory_payload_from_snapshot(snapshot: Any) -> dict[str, Any]:
    """
    Serialisiert Repository-Snapshot für die API.
    """

    try:
        if hasattr(snapshot, "to_dict") and callable(snapshot.to_dict):
            raw = normalize_json_mapping(snapshot.to_dict())
        elif isinstance(snapshot, Mapping):
            raw = normalize_json_mapping(snapshot)
        else:
            raw = {}
    except Exception:
        raw = {}

    user_id = normalize_user_id(raw.get("user_id"))
    inventory_key = normalize_inventory_key(raw.get("inventory_key"))
    active_slot_index = normalize_slot_index(raw.get("active_slot_index"))

    raw_slots = raw.get("slots", [])
    slots = normalize_slots(raw_slots, active_slot_index=active_slot_index)

    state = normalize_json_mapping(raw.get("state"))

    return {
        "schema_version": USER_INVENTORY_SERVICE_VERSION,
        "user_id": user_id,
        "inventory_key": inventory_key,
        "active_slot_index": active_slot_index,
        "last_selected_slot_index": normalize_slot_index(
            state.get("last_selected_slot_index", active_slot_index)
        ),
        "slot_count": DEFAULT_SLOT_COUNT,
        "slots": slots,
        "state": state,
        "selected_slot": selected_slot_from_slots(slots, active_slot_index=active_slot_index),
    }


def normalize_slots(value: Any, *, active_slot_index: int) -> list[dict[str, Any]]:
    """
    Normalisiert Slot-Liste auf exakt 9 Slots.
    """

    result_by_index: dict[int, dict[str, Any]] = {}

    if isinstance(value, list):
        candidates = value
    elif isinstance(value, tuple):
        candidates = list(value)
    else:
        candidates = []

    for candidate in candidates:
        slot = normalize_slot_payload(candidate)
        index = normalize_slot_index(slot.get("slot_index"))
        slot["slot_index"] = index
        slot["slot_key"] = slot.get("slot_key") or slot_key_for_index(index)
        slot["selected"] = index == active_slot_index
        result_by_index[index] = slot

    for slot_index in range(MIN_SLOT_INDEX, MAX_SLOT_INDEX + 1):
        if slot_index not in result_by_index:
            result_by_index[slot_index] = empty_slot_payload(
                slot_index=slot_index,
                selected=slot_index == active_slot_index,
            )

    return [
        result_by_index[slot_index]
        for slot_index in range(MIN_SLOT_INDEX, MAX_SLOT_INDEX + 1)
    ]


def normalize_slot_payload(value: Any) -> dict[str, Any]:
    """
    Normalisiert einen einzelnen Slot.
    """

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            raw = normalize_json_mapping(value.to_dict())
        except Exception:
            raw = {}
    elif isinstance(value, Mapping):
        raw = normalize_json_mapping(value)
    else:
        raw = {}

    slot_index = normalize_slot_index(raw.get("slot_index"))

    payload = {
        "id": raw.get("id"),
        "state_id": raw.get("state_id"),
        "user_id": normalize_user_id(raw.get("user_id")),
        "inventory_key": normalize_inventory_key(raw.get("inventory_key")),
        "slot_index": slot_index,
        "slot_key": raw.get("slot_key") or slot_key_for_index(slot_index),
        "item_db_id": raw.get("item_db_id"),
        "vplib_uid": raw.get("vplib_uid"),
        "family_id": raw.get("family_id"),
        "package_id": raw.get("package_id"),
        "variant_id": raw.get("variant_id"),
        "label": raw.get("label"),
        "description": raw.get("description"),
        "object_kind": raw.get("object_kind"),
        "domain": raw.get("domain"),
        "category": raw.get("category"),
        "subcategory": raw.get("subcategory"),
        "taxonomy_path": raw.get("taxonomy_path"),
        "quantity": normalize_non_negative_int(raw.get("quantity"), default=0),
        "empty": normalize_bool(raw.get("empty"), default=True),
        "selected": normalize_bool(raw.get("selected"), default=False),
        "active": normalize_bool(raw.get("active"), default=True),
        "locked": normalize_bool(raw.get("locked"), default=False),
        "pinned": normalize_bool(raw.get("pinned"), default=False),
        "source": raw.get("source") or "user",
        "scope": raw.get("scope") or "editor",
        "mode": raw.get("mode") or "creative",
        "sort_order": normalize_non_negative_int(raw.get("sort_order"), default=slot_index),
        "icon": normalize_json_mapping(raw.get("icon")),
        "preview": normalize_json_mapping(raw.get("preview")),
        "assets": normalize_json_list(raw.get("assets")),
        "variant": normalize_json_mapping(raw.get("variant")),
        "placement": normalize_json_mapping(raw.get("placement")),
        "selected_at": raw.get("selected_at"),
        "assigned_at": raw.get("assigned_at"),
        "cleared_at": raw.get("cleared_at"),
        "payload": normalize_json_mapping(raw.get("payload")),
        "meta": normalize_json_mapping(raw.get("meta")),
        "metadata": normalize_json_mapping(raw.get("metadata")),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
    }

    payload["empty"] = infer_slot_empty(payload)

    return payload


def empty_slot_payload(*, slot_index: int, selected: bool = False) -> dict[str, Any]:
    """
    Erzeugt einen leeren Slot-Payload.
    """

    normalized_slot_index = normalize_slot_index(slot_index)

    return {
        "id": None,
        "state_id": None,
        "user_id": DEFAULT_USER_ID,
        "inventory_key": DEFAULT_INVENTORY_KEY,
        "slot_index": normalized_slot_index,
        "slot_key": slot_key_for_index(normalized_slot_index),
        "item_db_id": None,
        "vplib_uid": None,
        "family_id": None,
        "package_id": None,
        "variant_id": None,
        "label": None,
        "description": None,
        "object_kind": None,
        "domain": None,
        "category": None,
        "subcategory": None,
        "taxonomy_path": None,
        "quantity": 0,
        "empty": True,
        "selected": bool(selected),
        "active": True,
        "locked": False,
        "pinned": False,
        "source": "user",
        "scope": "editor",
        "mode": "creative",
        "sort_order": normalized_slot_index,
        "icon": {},
        "preview": {},
        "assets": [],
        "variant": {},
        "placement": {},
        "selected_at": None,
        "assigned_at": None,
        "cleared_at": None,
        "payload": {},
        "meta": {},
        "metadata": {},
        "created_at": None,
        "updated_at": None,
    }


def selected_slot_from_slots(slots: list[dict[str, Any]], *, active_slot_index: int) -> dict[str, Any]:
    """
    Gibt den aktiv ausgewählten Slot zurück.
    """

    for slot in slots:
        if normalize_slot_index(slot.get("slot_index")) == active_slot_index:
            return slot

    return empty_slot_payload(slot_index=active_slot_index, selected=True)


def infer_slot_empty(slot: Mapping[str, Any]) -> bool:
    """
    Leitet defensiv ab, ob ein Slot leer ist.
    """

    if normalize_bool(slot.get("empty"), default=False):
        return True

    meaningful_keys = (
        "item_db_id",
        "vplib_uid",
        "family_id",
        "package_id",
        "variant_id",
        "label",
        "object_kind",
    )

    return not any(slot.get(key) for key in meaningful_keys)


# ---------------------------------------------------------------------------
# Payload normalization
# ---------------------------------------------------------------------------

def normalize_payload(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """
    Normalisiert eingehenden Payload.
    """

    if payload is None:
        return {}

    if isinstance(payload, Mapping):
        return normalize_json_mapping(payload)

    return {}


def extract_item_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """
    Extrahiert Item-Daten aus einem Request-Payload.

    Unterstützte Formen:
        {"item": {...}}
        {"slot": {"item": {...}}}
        {"data": {"item": {...}}}
        {"vplib_uid": "...", "family_id": "..."}
    """

    normalized = normalize_json_mapping(payload)

    for key in ("item", "block", "library_item", "creative_item"):
        candidate = normalized.get(key)
        if isinstance(candidate, Mapping):
            return normalize_json_mapping(candidate)

    slot = normalized.get("slot")
    if isinstance(slot, Mapping):
        for key in ("item", "block", "library_item", "creative_item"):
            candidate = slot.get(key)
            if isinstance(candidate, Mapping):
                return normalize_json_mapping(candidate)

    data = normalized.get("data")
    if isinstance(data, Mapping):
        for key in ("item", "block", "library_item", "creative_item"):
            candidate = data.get(key)
            if isinstance(candidate, Mapping):
                return normalize_json_mapping(candidate)

    item_like_keys = {
        "item_db_id",
        "id",
        "vplib_uid",
        "family_id",
        "package_id",
        "variant_id",
        "label",
        "name",
        "object_kind",
        "domain",
        "category",
        "subcategory",
        "quantity",
        "icon",
        "preview",
        "assets",
        "variant",
        "placement",
    }

    if any(key in normalized for key in item_like_keys):
        excluded_keys = {
            "user_id",
            "inventory_key",
            "slot_index",
            "slot_key",
            "select",
            "selected",
            "active_slot_index",
        }
        return {
            key: value
            for key, value in normalized.items()
            if key not in excluded_keys
        }

    return {}


def normalize_user_id(value: Any | None = None) -> int:
    """
    Normalisiert User-ID.

    Phase 1:
    - Default user_id = 1
    """

    try:
        module = _repository_module()
        normalize_repository_user_id = getattr(module, "normalize_repository_user_id", None)
        if callable(normalize_repository_user_id):
            return int(normalize_repository_user_id(value))
    except Exception:
        pass

    return normalize_positive_int(value, default=DEFAULT_USER_ID)


def normalize_inventory_key(value: Any | None = None) -> str:
    """
    Normalisiert Inventory-Key.
    """

    try:
        module = _repository_module()
        normalize_repository_inventory_key = getattr(module, "normalize_repository_inventory_key", None)
        if callable(normalize_repository_inventory_key):
            return str(normalize_repository_inventory_key(value))
    except Exception:
        pass

    try:
        text = str(value if value is not None else DEFAULT_INVENTORY_KEY).strip()
    except Exception:
        text = DEFAULT_INVENTORY_KEY

    return (text or DEFAULT_INVENTORY_KEY)[:120]


def normalize_slot_index(value: Any | None = None) -> int:
    """
    Normalisiert Slot-Index auf 1..9.
    """

    try:
        module = _repository_module()
        normalize_repository_slot_index = getattr(module, "normalize_repository_slot_index", None)
        if callable(normalize_repository_slot_index):
            return int(normalize_repository_slot_index(value))
    except Exception:
        pass

    try:
        number = int(value if value is not None else MIN_SLOT_INDEX)
    except Exception:
        number = MIN_SLOT_INDEX

    return max(MIN_SLOT_INDEX, min(MAX_SLOT_INDEX, number))


def slot_key_for_index(value: Any) -> str:
    """
    Erzeugt stabilen Slot-Key.
    """

    return f"user-slot-{normalize_slot_index(value)}"


def normalize_positive_int(value: Any, *, default: int) -> int:
    """
    Normalisiert positive Integer.
    """

    try:
        number = int(value)
    except Exception:
        number = int(default)

    return max(1, number)


def normalize_non_negative_int(value: Any, *, default: int = 0) -> int:
    """
    Normalisiert nichtnegative Integer.
    """

    try:
        number = int(value)
    except Exception:
        number = int(default)

    return max(0, number)


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """
    Normalisiert Bool-Werte.
    """

    if isinstance(value, bool):
        return value

    if value is None:
        return default

    try:
        text = str(value).strip().lower()
    except Exception:
        return default

    if text in {"1", "true", "yes", "ja", "on", "enabled", "active", "selected"}:
        return True

    if text in {"0", "false", "no", "nein", "off", "disabled", "inactive"}:
        return False

    return default


def normalize_json_mapping(value: Any) -> dict[str, Any]:
    """
    Normalisiert Mapping JSON-kompatibel.
    """

    if value is None:
        return {}

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}

        for key, child_value in value.items():
            try:
                result[str(key)] = normalize_json_value(child_value)
            except Exception:
                result[str(key)] = str(child_value)

        return result

    return {}


def normalize_json_list(value: Any) -> list[Any]:
    """
    Normalisiert Liste JSON-kompatibel.
    """

    if value is None:
        return []

    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]

    if isinstance(value, tuple):
        return [normalize_json_value(item) for item in value]

    if isinstance(value, set):
        return [normalize_json_value(item) for item in sorted(value, key=str)]

    return []


def normalize_json_value(value: Any) -> Any:
    """
    Normalisiert beliebigen Wert JSON-kompatibel.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return normalize_json_list(value)

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def success_response(
    *,
    status: str,
    route: str,
    data: Mapping[str, Any] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    info: list[dict[str, Any]] | None = None,
    http_status: int = 200,
) -> dict[str, Any]:
    """
    Einheitliche erfolgreiche Service-Response.
    """

    return {
        "ok": True,
        "healthy": http_status < 400,
        "status": status,
        "route": route,
        "component": USER_INVENTORY_COMPONENT,
        "version": USER_INVENTORY_SERVICE_VERSION,
        "data": normalize_json_mapping(data),
        "errors": [],
        "warnings": normalize_issue_list(warnings),
        "info": normalize_issue_list(info),
        "_http_status": safe_http_status(http_status),
    }


def failure_response(
    *,
    route: str,
    code: str,
    message: str,
    exc: BaseException | None = None,
    details: Mapping[str, Any] | None = None,
    http_status: int = 500,
) -> dict[str, Any]:
    """
    Einheitliche Fehler-Response.
    """

    issue_details: dict[str, Any] = normalize_json_mapping(details)

    if exc is not None:
        issue_details["exception_type"] = type(exc).__name__
        issue_details["exception"] = str(exc)

    return {
        "ok": False,
        "healthy": False,
        "status": STATUS_ERROR,
        "route": route,
        "component": USER_INVENTORY_COMPONENT,
        "version": USER_INVENTORY_SERVICE_VERSION,
        "data": {},
        "errors": [
            error_item(
                code=code,
                message=message,
                field=route,
                details=issue_details,
            )
        ],
        "warnings": [],
        "info": [],
        "_http_status": safe_http_status(http_status),
    }


def error_item(
    *,
    code: str,
    message: str,
    field: str = "user_inventory",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return issue_item(
        severity="error",
        code=code,
        message=message,
        field=field,
        details=details,
    )


def warning_item(
    *,
    code: str,
    message: str,
    field: str = "user_inventory",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return issue_item(
        severity="warning",
        code=code,
        message=message,
        field=field,
        details=details,
    )


def info_item(
    *,
    code: str,
    message: str,
    field: str = "user_inventory",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return issue_item(
        severity="info",
        code=code,
        message=message,
        field=field,
        details=details,
    )


def issue_item(
    *,
    severity: str,
    code: str,
    message: str,
    field: str = "user_inventory",
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Baut einen JSON-kompatiblen Issue-Eintrag.
    """

    return {
        "severity": str(severity or "info"),
        "code": str(code or "unknown"),
        "field": str(field or "user_inventory"),
        "message": str(message or ""),
        "details": normalize_json_mapping(details),
    }


def normalize_issue_list(value: Any) -> list[dict[str, Any]]:
    """
    Normalisiert Issue-Listen.
    """

    if not value:
        return []

    if not isinstance(value, list):
        return []

    result: list[dict[str, Any]] = []

    for item in value:
        if isinstance(item, Mapping):
            result.append(normalize_json_mapping(item))

    return result


def safe_http_status(value: Any) -> int:
    """
    Normalisiert HTTP-Statuscode.
    """

    try:
        status = int(value)
    except Exception:
        return 500

    if status < 100 or status > 599:
        return 500

    return status


# ---------------------------------------------------------------------------
# Convenience aliases for future route imports
# ---------------------------------------------------------------------------

def get_inventory(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return get_inventory_response(payload)


def select_slot(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return select_slot_response(payload)


def set_slot(slot_index: Any, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return set_slot_response(slot_index, payload)


def clear_slot(slot_index: Any, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return clear_slot_response(slot_index, payload)


def health() -> dict[str, Any]:
    return get_service_health_response()


__all__ = [
    "DEFAULT_INVENTORY_KEY",
    "DEFAULT_SLOT_COUNT",
    "DEFAULT_USER_ID",
    "MAX_SLOT_INDEX",
    "MIN_SLOT_INDEX",
    "STATUS_CACHE_CLEARED",
    "STATUS_ERROR",
    "STATUS_HEALTHY",
    "STATUS_OK",
    "STATUS_READY",
    "STATUS_SELECTED",
    "STATUS_SLOT_CLEARED",
    "STATUS_SLOT_SET",
    "USER_INVENTORY_COMPONENT",
    "USER_INVENTORY_SERVICE_VERSION",
    "UserInventoryServiceError",
    "UserInventoryServiceValidationError",
    "clear_cache_response",
    "clear_slot",
    "clear_slot_response",
    "empty_slot_payload",
    "extract_item_payload",
    "failure_response",
    "get_inventory",
    "get_inventory_response",
    "get_service_health_response",
    "health",
    "inventory_payload_from_snapshot",
    "normalize_bool",
    "normalize_inventory_key",
    "normalize_json_list",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_payload",
    "normalize_slot_index",
    "normalize_slots",
    "normalize_user_id",
    "safe_http_status",
    "select_slot",
    "select_slot_response",
    "set_slot",
    "set_slot_response",
    "slot_key_for_index",
    "success_response",
]