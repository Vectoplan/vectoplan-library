# services/vectoplan-library/models/creative_library_drafts.py
"""
Database models for Creative Library Drafts.

Diese Datei modelliert die sichere Generator-/Bearbeitungs-Zwischenschicht:

- CreativeLibraryDraft
- CreativeLibraryDraftVariant
- CreativeLibraryDraftAsset
- CreativeLibraryDraftDocument
- CreativeLibraryDraftValidationIssue
- CreativeLibraryDraftAuditEvent

Ziel:

    Create UI / Generator / Edit Existing VPLIB
        -> Draft
        -> Draft Variants
        -> Draft Assets / Files
        -> Draft Documents
        -> Validate
        -> Publish as CreativeLibraryRevision
        -> Published Creative Library

Wichtige Architekturregeln:

- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt keine Migration aus.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei spricht keine Datenbankverbindung aktiv an.
- Diese Datei schreibt keine VPLIB-Dateien.
- Diese Datei erzeugt keine finale VPLIB-UID aus dem Nichts.
- Neue VPLIB-UIDs entstehen weiterhin im VPLIB/Create-/Manifest-/Bundle-Flow.
- Drafts dürfen eine vorhandene vplib_uid referenzieren oder eine aus dem
  Create-Flow übernommene vplib_uid zwischenspeichern.
- Published Creative Library Tabellen bleiben die Wahrheit für veröffentlichte
  Items/Revisions.
- Drafts sind Arbeitsstände und dürfen verworfen werden.
- Technische Namen, JSON-Keys und Variablen bleiben Englisch.

Phase 1:

- user_id darf weiterhin 1 sein.
- Drafts können neue VPLIBs oder Updates bestehender VPLIBs vorbereiten.
- Publish-Logik wird später im Service implementiert, nicht im Model.
"""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


# ---------------------------------------------------------------------------
# Metadata / constants
# ---------------------------------------------------------------------------

CREATIVE_LIBRARY_DRAFTS_MODELS_SCHEMA_VERSION: Final[str] = "vectoplan_library.creative_library_drafts.models.v2"
DEFAULT_USER_ID: Final[int] = 1

MAX_UID_LENGTH: Final[int] = 80
MAX_KEY_LENGTH: Final[int] = 255
MAX_SHORT_KEY_LENGTH: Final[int] = 160
MAX_LABEL_LENGTH: Final[int] = 255
MAX_STATUS_LENGTH: Final[int] = 40
MAX_STAGE_LENGTH: Final[int] = 80
MAX_SOURCE_SCOPE_LENGTH: Final[int] = 40
MAX_OWNER_SCOPE_LENGTH: Final[int] = 120
MAX_VPLIB_UID_LENGTH: Final[int] = 128
MAX_FAMILY_ID_LENGTH: Final[int] = 255
MAX_PACKAGE_ID_LENGTH: Final[int] = 255
MAX_VARIANT_ID_LENGTH: Final[int] = 160
MAX_OBJECT_KIND_LENGTH: Final[int] = 80
MAX_PROFILE_ID_LENGTH: Final[int] = 160
MAX_TAXONOMY_PART_LENGTH: Final[int] = 120
MAX_TAXONOMY_PATH_LENGTH: Final[int] = 512
MAX_HASH_LENGTH: Final[int] = 128
MAX_PATH_LENGTH: Final[int] = 1024
MAX_MIME_TYPE_LENGTH: Final[int] = 160
MAX_ROLE_LENGTH: Final[int] = 120
MAX_SEVERITY_LENGTH: Final[int] = 40
MAX_CODE_LENGTH: Final[int] = 160
MAX_SCOPE_LENGTH: Final[int] = 120
MAX_FIELD_LENGTH: Final[int] = 255

DEFAULT_DRAFT_KEY_PREFIX: Final[str] = "draft"
DEFAULT_VARIANT_ID: Final[str] = "default"


# ---------------------------------------------------------------------------
# SQLAlchemy extension import
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_db() -> Any:
    """
    Lädt die zentrale Flask-SQLAlchemy Extension defensiv.

    Erwarteter Service-Standard:

        services/vectoplan-library/extensions.py

    mit:

        db = SQLAlchemy()

    Diese Funktion ist bewusst tolerant gegenüber mehreren Import-Pfaden, weil
    der Service lokal, im Container, über Tests und über Flask-Migrate leicht
    unterschiedliche PYTHONPATH-Kontexte haben kann.
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

    raise RuntimeError(
        "Could not import SQLAlchemy extension `db`. "
        "Expected `db = SQLAlchemy()` in services/vectoplan-library/extensions.py. "
        f"Import attempts: {'; '.join(errors)}"
    )


db = _load_db()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CreativeLibraryDraftSourceScope(str, enum.Enum):
    USER = "user"
    SYSTEM = "system"
    IMPORTED = "imported"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftMode(str, enum.Enum):
    CREATE_NEW = "create_new"
    UPDATE_EXISTING = "update_existing"
    CLONE_EXISTING = "clone_existing"
    IMPORT_PACKAGE = "import_package"
    GENERATED = "generated"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftStatus(str, enum.Enum):
    DRAFT = "draft"
    EDITING = "editing"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    DISCARDED = "discarded"
    FAILED = "failed"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftStage(str, enum.Enum):
    CREATED = "created"
    IDENTITY = "identity"
    CLASSIFICATION = "classification"
    VARIANTS = "variants"
    ASSETS = "assets"
    DOCUMENTS = "documents"
    VALIDATION = "validation"
    READY = "ready"
    PUBLISHED = "published"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftItemStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    INVALID = "invalid"
    DELETED = "deleted"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftAssetRole(str, enum.Enum):
    ICON = "icon"
    PREVIEW = "preview"
    TEXTURE = "texture"
    MATERIAL_TEXTURE = "material_texture"
    RENDER_MODEL = "render_model"
    GLB_MODEL = "glb_model"
    GLTF_MODEL = "gltf_model"
    LOD_MODEL = "lod_model"
    DOCUMENT = "document"
    TECHNICAL_DRAWING = "technical_drawing"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftDocumentKind(str, enum.Enum):
    MANIFEST = "manifest"
    MODULES = "modules"
    FAMILY = "family"
    VARIANT = "variant"
    EDITOR = "editor"
    RENDER = "render"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    ANALYSIS = "analysis"
    DYNAMIC = "dynamic"
    MANUFACTURER = "manufacturer"
    DOCS = "docs"
    TESTS = "tests"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftIssueSeverity(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class CreativeLibraryDraftAuditEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    VARIANT_ADDED = "variant_added"
    VARIANT_UPDATED = "variant_updated"
    VARIANT_DELETED = "variant_deleted"
    ASSET_ADDED = "asset_added"
    ASSET_UPDATED = "asset_updated"
    ASSET_DELETED = "asset_deleted"
    DOCUMENT_ADDED = "document_added"
    DOCUMENT_UPDATED = "document_updated"
    DOCUMENT_DELETED = "document_deleted"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_FINISHED = "validation_finished"
    MARKED_VALID = "marked_valid"
    MARKED_INVALID = "marked_invalid"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    DISCARDED = "discarded"
    DELETED = "deleted"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now() -> datetime:
    """Timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def new_uid() -> str:
    """Stable lowercase UUID string for DB technical IDs."""
    return str(uuid.uuid4()).lower()


def enum_value(value: Any, *, default: str = "") -> str:
    """Normalisiert Enum-/String-Werte zu DB-Strings."""
    if value is None:
        return default

    if hasattr(value, "value"):
        try:
            text = str(value.value).strip()
            return text or default
        except Exception:
            return default

    try:
        text = str(value).strip()
    except Exception:
        return default

    return text or default


def first_non_empty(*values: Any) -> Any:
    """Liefert den ersten nicht-leeren Wert."""
    for value in values:
        if value is None:
            continue

        if isinstance(value, str) and not value.strip():
            continue

        return value

    return None


def clean_string(value: Any, *, fallback: str = "") -> str:
    """Normalisiert defensiv zu String."""
    try:
        if value is None:
            return fallback

        text = str(value).replace("\x00", "").strip()
        return text if text else fallback
    except Exception:
        return fallback


def normalize_optional_string(value: Any, *, max_length: int | None = None) -> str | None:
    """Normalisiert optionale Strings."""
    if value is None:
        return None

    try:
        text = str(value).replace("\x00", "").strip()
    except Exception:
        return None

    if not text:
        return None

    if max_length is not None and max_length > 0:
        text = text[:max_length]

    return text


def normalize_required_string(value: Any, *, field_name: str, max_length: int | None = None) -> str:
    """Normalisiert Pflicht-Strings."""
    text = normalize_optional_string(value, max_length=max_length)
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def normalize_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Normalisierung."""
    if value is None:
        return default

    if isinstance(value, bool):
        return value

    text = clean_string(value).lower()

    if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "active", "visible", "published"}:
        return True

    if text in {"0", "false", "no", "n", "nein", "off", "disabled", "inactive", "hidden", "deleted"}:
        return False

    return default


def normalize_int(
    value: Any,
    *,
    default: int | None = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    """Robuste Integer-Normalisierung."""
    if value is None and default is None:
        return None

    try:
        result = int(value)
    except Exception:
        if default is None:
            return None
        result = int(default)

    if minimum is not None:
        result = max(int(minimum), result)

    if maximum is not None:
        result = min(int(maximum), result)

    return result


def normalize_user_id(value: Any, *, default: int | None = DEFAULT_USER_ID) -> int | None:
    """Normalisiert User-ID. None bleibt None, wenn default=None."""
    return normalize_int(value, default=default, minimum=1)


def normalize_json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert JSON-Mapping defensiv."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": normalize_json_value(value)}

    result: dict[str, Any] = {}

    for key, child_value in value.items():
        try:
            result[str(key)] = normalize_json_value(child_value)
        except Exception:
            result[str(key)] = str(child_value)

    return result


def normalize_json_list(value: Iterable[Any] | None) -> list[Any]:
    """Normalisiert JSON-Listen defensiv."""
    if value is None:
        return []

    if isinstance(value, Mapping):
        return [normalize_json_mapping(value)]

    if isinstance(value, (str, bytes, bytearray)):
        return [normalize_json_value(value)]

    try:
        return [normalize_json_value(item) for item in value]
    except Exception:
        return [str(value)]


def normalize_json_value(value: Any) -> Any:
    """Normalisiert Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def merge_json(*values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Mergt mehrere JSON-Mappings defensiv."""
    merged: dict[str, Any] = {}

    for value in values:
        merged.update(normalize_json_mapping(value))

    return merged


def stable_json_hash(value: Any) -> str:
    """Erzeugt einen stabilen SHA-256 Hash für JSON-kompatible Werte."""
    try:
        safe = normalize_json_value(value)
        raw = json.dumps(safe, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        raw = str(value)

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_source_scope(value: Any, *, default: str = CreativeLibraryDraftSourceScope.USER.value) -> str:
    """Normalisiert source_scope."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "core": CreativeLibraryDraftSourceScope.SYSTEM.value,
        "default": CreativeLibraryDraftSourceScope.SYSTEM.value,
        "global": CreativeLibraryDraftSourceScope.SYSTEM.value,
        "system": CreativeLibraryDraftSourceScope.SYSTEM.value,
        "user": CreativeLibraryDraftSourceScope.USER.value,
        "custom": CreativeLibraryDraftSourceScope.USER.value,
        "import": CreativeLibraryDraftSourceScope.IMPORTED.value,
        "imported": CreativeLibraryDraftSourceScope.IMPORTED.value,
        "generated": CreativeLibraryDraftSourceScope.GENERATED.value,
        "generator": CreativeLibraryDraftSourceScope.GENERATED.value,
    }

    return aliases.get(text, text if text else default)[:MAX_SOURCE_SCOPE_LENGTH]


def owner_scope_for(
    *,
    source_scope: Any = CreativeLibraryDraftSourceScope.USER.value,
    owner_user_id: Any = DEFAULT_USER_ID,
) -> str:
    """
    Baut einen stabilen owner_scope.

    PostgreSQL behandelt NULL in UniqueConstraints nicht als gleich.
    Deshalb wird zusätzlich ein nicht-nullbarer owner_scope gespeichert.
    """

    scope = normalize_source_scope(source_scope)
    user_id = normalize_user_id(owner_user_id, default=None)

    if scope == CreativeLibraryDraftSourceScope.SYSTEM.value and user_id is None:
        return CreativeLibraryDraftSourceScope.SYSTEM.value

    if scope == CreativeLibraryDraftSourceScope.USER.value:
        return f"user:{user_id or DEFAULT_USER_ID}"

    if user_id is not None:
        return f"{scope}:{user_id}"

    return scope or CreativeLibraryDraftSourceScope.USER.value


def normalize_status(value: Any, *, default: str = CreativeLibraryDraftStatus.DRAFT.value) -> str:
    """Normalisiert Draft-Status."""
    text = enum_value(value, default=default).strip().lower()
    return (text or default)[:MAX_STATUS_LENGTH]


def normalize_item_status(value: Any, *, default: str = CreativeLibraryDraftItemStatus.ACTIVE.value) -> str:
    """Normalisiert Draft-Child-Status."""
    text = enum_value(value, default=default).strip().lower()
    return (text or default)[:MAX_STATUS_LENGTH]


def normalize_stage(value: Any, *, default: str = CreativeLibraryDraftStage.CREATED.value) -> str:
    """Normalisiert Draft-Stage."""
    text = enum_value(value, default=default).strip().lower()
    return (text or default)[:MAX_STAGE_LENGTH]


def normalize_mode(value: Any, *, default: str = CreativeLibraryDraftMode.CREATE_NEW.value) -> str:
    """Normalisiert Draft-Mode."""
    text = enum_value(value, default=default).strip().lower()

    aliases = {
        "create": CreativeLibraryDraftMode.CREATE_NEW.value,
        "new": CreativeLibraryDraftMode.CREATE_NEW.value,
        "update": CreativeLibraryDraftMode.UPDATE_EXISTING.value,
        "edit": CreativeLibraryDraftMode.UPDATE_EXISTING.value,
        "clone": CreativeLibraryDraftMode.CLONE_EXISTING.value,
        "copy": CreativeLibraryDraftMode.CLONE_EXISTING.value,
        "import": CreativeLibraryDraftMode.IMPORT_PACKAGE.value,
        "generated": CreativeLibraryDraftMode.GENERATED.value,
        "generator": CreativeLibraryDraftMode.GENERATED.value,
    }

    return aliases.get(text, text or default)[:80]


@lru_cache(maxsize=4096)
def _cached_slugify(value: str, max_length: int = MAX_SHORT_KEY_LENGTH) -> str:
    """Cached slugify."""
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "Ä": "ae",
        "Ö": "oe",
        "Ü": "ue",
    }

    text = value

    for source, target in replacements.items():
        text = text.replace(source, target)

    text = text.strip().lower()
    text = text.replace("\\", "/")
    text = text.replace("/", "-")
    text = text.replace(".", "-")
    text = text.replace("_", "-")

    cleaned: list[str] = []
    previous_dash = False

    for char in text:
        if char.isalnum():
            cleaned.append(char)
            previous_dash = False
            continue

        if char == "-":
            if not previous_dash:
                cleaned.append("-")
                previous_dash = True
            continue

        if not previous_dash:
            cleaned.append("-")
            previous_dash = True

    result = "".join(cleaned).strip("-")
    return result[:max_length] if result else ""


def normalize_slug(value: Any, *, fallback: str = DEFAULT_DRAFT_KEY_PREFIX, max_length: int = MAX_SHORT_KEY_LENGTH) -> str:
    """Normalisiert Slug/Key."""
    text = normalize_optional_string(value, max_length=max_length) or fallback
    return _cached_slugify(text, max_length) or fallback


def make_draft_key(
    *,
    label: Any = None,
    family_id: Any = None,
    package_id: Any = None,
    draft_uid: Any = None,
) -> str:
    """Baut stabilen draft_key."""
    base = normalize_slug(
        first_non_empty(label, family_id, package_id, DEFAULT_DRAFT_KEY_PREFIX),
        fallback=DEFAULT_DRAFT_KEY_PREFIX,
        max_length=120,
    )
    uid = normalize_optional_string(draft_uid, max_length=MAX_UID_LENGTH) or new_uid()
    return f"{base}-{uid[:12]}"[:MAX_KEY_LENGTH]


def normalize_taxonomy_part(value: Any, *, max_length: int = MAX_TAXONOMY_PART_LENGTH) -> str | None:
    """Normalisiert Taxonomie-Part."""
    text = normalize_optional_string(value, max_length=max_length)
    if not text:
        return None

    slug = _cached_slugify(text, max_length)
    return slug or None


def taxonomy_path_for(
    *,
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Baut Taxonomiepfad aus Domain/Kategorie/Subkategorie."""
    parts = [
        normalize_taxonomy_part(domain),
        normalize_taxonomy_part(category),
        normalize_taxonomy_part(subcategory),
    ]
    cleaned = [part for part in parts if part]
    return "/".join(cleaned) if cleaned else None


def extract_identity_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extrahiert Draft-/VPLIB-Identität aus Payload."""
    data = normalize_json_mapping(payload)

    classification = normalize_json_mapping(data.get("classification"))
    manifest = normalize_json_mapping(data.get("manifest") or data.get("manifest_payload"))

    domain = normalize_taxonomy_part(first_non_empty(data.get("domain"), manifest.get("domain"), classification.get("domain")))
    category = normalize_taxonomy_part(first_non_empty(data.get("category"), manifest.get("category"), classification.get("category")))
    subcategory = normalize_taxonomy_part(first_non_empty(data.get("subcategory"), manifest.get("subcategory"), classification.get("subcategory")))

    return {
        "vplib_uid": normalize_optional_string(
            first_non_empty(data.get("vplib_uid"), data.get("vplibUid"), manifest.get("vplib_uid")),
            max_length=MAX_VPLIB_UID_LENGTH,
        ),
        "package_id": normalize_optional_string(
            first_non_empty(data.get("package_id"), data.get("packageId"), manifest.get("package_id")),
            max_length=MAX_PACKAGE_ID_LENGTH,
        ),
        "family_id": normalize_optional_string(
            first_non_empty(data.get("family_id"), data.get("familyId"), manifest.get("family_id")),
            max_length=MAX_FAMILY_ID_LENGTH,
        ),
        "family_slug": normalize_optional_string(
            first_non_empty(data.get("family_slug"), data.get("slug"), manifest.get("family_slug"), manifest.get("slug")),
            max_length=MAX_SHORT_KEY_LENGTH,
        ),
        "label": normalize_optional_string(
            first_non_empty(data.get("label"), data.get("name"), data.get("family_name"), manifest.get("family_name"), manifest.get("label")),
            max_length=MAX_LABEL_LENGTH,
        ),
        "description": normalize_optional_string(first_non_empty(data.get("description"), manifest.get("description"))),
        "object_kind": normalize_optional_string(
            first_non_empty(data.get("object_kind"), data.get("objectKind"), manifest.get("object_kind")),
            max_length=MAX_OBJECT_KIND_LENGTH,
        ),
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "taxonomy_path": normalize_optional_string(data.get("taxonomy_path"), max_length=MAX_TAXONOMY_PATH_LENGTH)
        or taxonomy_path_for(domain=domain, category=category, subcategory=subcategory),
        "family_profile_id": normalize_optional_string(
            first_non_empty(data.get("family_profile_id"), data.get("familyProfileId"), manifest.get("family_profile_id")),
            max_length=MAX_PROFILE_ID_LENGTH,
        ),
        "variant_profile_id": normalize_optional_string(
            first_non_empty(data.get("variant_profile_id"), data.get("variantProfileId"), manifest.get("variant_profile_id")),
            max_length=MAX_PROFILE_ID_LENGTH,
        ),
    }


def extract_variant_identity(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extrahiert Variant-Identität aus Payload."""
    data = normalize_json_mapping(payload)

    values = normalize_json_mapping(
        first_non_empty(
            data.get("definition_values"),
            data.get("definitionValues"),
            data.get("values"),
        )
    )

    variant_id = normalize_optional_string(
        first_non_empty(
            data.get("variant_id"),
            data.get("variantId"),
            data.get("id"),
            data.get("slug"),
            values.get("variant.variant_id"),
        ),
        max_length=MAX_VARIANT_ID_LENGTH,
    ) or DEFAULT_VARIANT_ID

    label = normalize_optional_string(
        first_non_empty(
            data.get("label"),
            data.get("name"),
            values.get("variant.label"),
            variant_id,
        ),
        max_length=MAX_LABEL_LENGTH,
    )

    return {
        "variant_id": variant_id,
        "slug": normalize_slug(first_non_empty(data.get("slug"), variant_id), fallback=variant_id, max_length=MAX_SHORT_KEY_LENGTH),
        "label": label,
        "name": normalize_optional_string(first_non_empty(data.get("name"), label), max_length=MAX_LABEL_LENGTH),
        "description": normalize_optional_string(first_non_empty(data.get("description"), values.get("variant.description"))),
        "is_default": normalize_bool(
            first_non_empty(data.get("is_default"), data.get("isDefault"), data.get("default"), variant_id == DEFAULT_VARIANT_ID),
            default=variant_id == DEFAULT_VARIANT_ID,
        ),
        "family_profile_id": normalize_optional_string(
            first_non_empty(data.get("family_profile_id"), data.get("familyProfileId")),
            max_length=MAX_PROFILE_ID_LENGTH,
        ),
        "variant_profile_id": normalize_optional_string(
            first_non_empty(data.get("variant_profile_id"), data.get("variantProfileId")),
            max_length=MAX_PROFILE_ID_LENGTH,
        ),
    }


def infer_document_kind(relative_path: Any, *, module: Any = None, document_type: Any = None) -> str:
    """Leitet Dokumentkind aus Pfad/Modul/Typ ab."""
    explicit_module = normalize_optional_string(module, max_length=120)
    if explicit_module:
        return explicit_module.split(".", 1)[0].lower()

    path = normalize_optional_string(relative_path, max_length=MAX_PATH_LENGTH)
    if path:
        if path == "vplib.manifest.json":
            return CreativeLibraryDraftDocumentKind.MANIFEST.value

        if path == "vplib.modules.json":
            return CreativeLibraryDraftDocumentKind.MODULES.value

        if "/" in path:
            return path.split("/", 1)[0].lower()

    doc_type = clean_string(document_type).lower()
    if doc_type in {"manifest", "modules", "family", "variant", "editor", "render", "physical", "material", "calculation", "analysis", "dynamic", "manufacturer", "docs", "tests"}:
        return doc_type

    return CreativeLibraryDraftDocumentKind.OTHER.value


def normalize_relative_path(value: Any, *, field_name: str = "relative_path") -> str:
    """
    Normalisiert package-relative Pfade defensiv.

    Harte Service-Validierung passiert später im Service/Validator. Hier werden
    nur offensichtlich gefährliche absolute Pfade und Parent-Traversal verhindert.
    """

    path = normalize_required_string(value, field_name=field_name, max_length=MAX_PATH_LENGTH)
    cleaned = path.replace("\\", "/").strip()

    if cleaned.startswith("/"):
        raise ValueError(f"{field_name} must be package-relative.")

    parts = [part for part in cleaned.split("/") if part not in {"", "."}]

    if any(part == ".." for part in parts):
        raise ValueError(f"{field_name} must not contain parent traversal.")

    normalized = "/".join(parts)

    if not normalized:
        raise ValueError(f"{field_name} is required.")

    return normalized[:MAX_PATH_LENGTH]


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimestampMixin:
    """Gemeinsame created_at/updated_at-Felder."""

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    def touch(self) -> None:
        """Aktualisiert updated_at defensiv."""
        try:
            self.updated_at = utc_now()
        except Exception:
            pass


class JsonMixin:
    """Gemeinsame JSON-Helfer."""

    @staticmethod
    def json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
        return normalize_json_mapping(value)

    @staticmethod
    def json_list(value: Iterable[Any] | None) -> list[Any]:
        return normalize_json_list(value)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class CreativeLibraryDraft(TimestampMixin, JsonMixin, db.Model):
    """Arbeitsstand für neue oder bestehende VPLIB-Packages."""

    __tablename__ = "creative_library_drafts"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    draft_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)
    draft_key = db.Column(db.String(MAX_KEY_LENGTH), nullable=False, index=True)

    owner_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    source_scope = db.Column(
        db.String(MAX_SOURCE_SCOPE_LENGTH),
        nullable=False,
        default=CreativeLibraryDraftSourceScope.USER.value,
        index=True,
    )
    owner_scope = db.Column(
        db.String(MAX_OWNER_SCOPE_LENGTH),
        nullable=False,
        default=f"user:{DEFAULT_USER_ID}",
        index=True,
    )

    draft_mode = db.Column(
        db.String(80),
        nullable=False,
        default=CreativeLibraryDraftMode.CREATE_NEW.value,
        index=True,
    )

    target_item_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_items.id",
            name="fk_creative_library_drafts_target_item_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    base_revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_revisions.id",
            name="fk_creative_library_drafts_base_revision_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    published_revision_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_revisions.id",
            name="fk_creative_library_drafts_published_revision_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    vplib_uid = db.Column(db.String(MAX_VPLIB_UID_LENGTH), nullable=True, index=True)
    package_id = db.Column(db.String(MAX_PACKAGE_ID_LENGTH), nullable=True, index=True)
    family_id = db.Column(db.String(MAX_FAMILY_ID_LENGTH), nullable=True, index=True)
    family_slug = db.Column(db.String(MAX_SHORT_KEY_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    object_kind = db.Column(db.String(MAX_OBJECT_KIND_LENGTH), nullable=True, index=True)
    family_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)
    variant_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)

    domain = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    category = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    subcategory = db.Column(db.String(MAX_TAXONOMY_PART_LENGTH), nullable=True, index=True)
    taxonomy_path = db.Column(db.String(MAX_TAXONOMY_PATH_LENGTH), nullable=True, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=CreativeLibraryDraftStatus.DRAFT.value,
        index=True,
    )
    stage = db.Column(
        db.String(MAX_STAGE_LENGTH),
        nullable=False,
        default=CreativeLibraryDraftStage.CREATED.value,
        index=True,
    )
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    locked = db.Column(db.Boolean, nullable=False, default=False)

    variant_count = db.Column(db.Integer, nullable=False, default=0)
    asset_count = db.Column(db.Integer, nullable=False, default=0)
    document_count = db.Column(db.Integer, nullable=False, default=0)
    issue_count = db.Column(db.Integer, nullable=False, default=0)
    warning_count = db.Column(db.Integer, nullable=False, default=0)
    error_count = db.Column(db.Integer, nullable=False, default=0)

    manifest_payload = db.Column(db.JSON, nullable=False, default=dict)
    modules_payload = db.Column(db.JSON, nullable=False, default=dict)
    family_payload = db.Column(db.JSON, nullable=False, default=dict)
    classification_payload = db.Column(db.JSON, nullable=False, default=dict)
    generator_payload = db.Column(db.JSON, nullable=False, default=dict)
    validation_payload = db.Column(db.JSON, nullable=False, default=dict)
    publish_payload = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    validated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    published_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    discarded_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)

    validated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    discarded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    target_item = db.relationship("CreativeLibraryItem", foreign_keys=[target_item_id], lazy="joined")
    base_revision = db.relationship("CreativeLibraryRevision", foreign_keys=[base_revision_id], lazy="joined")
    published_revision = db.relationship("CreativeLibraryRevision", foreign_keys=[published_revision_id], lazy="joined")

    variants = db.relationship(
        "CreativeLibraryDraftVariant",
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftVariant.draft_id",
        lazy="selectin",
    )
    assets = db.relationship(
        "CreativeLibraryDraftAsset",
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftAsset.draft_id",
        lazy="selectin",
    )
    documents = db.relationship(
        "CreativeLibraryDraftDocument",
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftDocument.draft_id",
        lazy="selectin",
    )
    validation_issues = db.relationship(
        "CreativeLibraryDraftValidationIssue",
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftValidationIssue.draft_id",
        lazy="selectin",
    )
    audit_events = db.relationship(
        "CreativeLibraryDraftAuditEvent",
        back_populates="draft",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftAuditEvent.draft_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("owner_scope", "draft_key", name="uq_creative_library_draft_owner_key"),
        db.Index("ix_creative_library_drafts_owner_status", "owner_scope", "status", "active"),
        db.Index("ix_creative_library_drafts_target", "target_item_id", "base_revision_id"),
        db.Index("ix_creative_library_drafts_uid_status", "vplib_uid", "status"),
        db.Index("ix_creative_library_drafts_taxonomy", "domain", "category", "subcategory"),
        db.Index("ix_creative_library_drafts_profiles", "family_profile_id", "variant_profile_id"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDraft id={self.id!r} uid={self.draft_uid!r} status={self.status!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        owner_user_id: Any = DEFAULT_USER_ID,
        source_scope: Any = CreativeLibraryDraftSourceScope.USER.value,
        draft_mode: Any = CreativeLibraryDraftMode.CREATE_NEW.value,
        created_by_user_id: Any = None,
    ) -> "CreativeLibraryDraft":
        """Erstellt einen Draft aus Create-/Generator-/Edit-Payload."""
        data = normalize_json_mapping(payload)
        identity = extract_identity_payload(data)

        normalized_source_scope = normalize_source_scope(source_scope)
        normalized_owner_user_id = normalize_user_id(owner_user_id, default=None)

        draft_uid = normalize_optional_string(data.get("draft_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid()
        label = identity.get("label")

        return cls(
            draft_uid=draft_uid,
            draft_key=normalize_optional_string(data.get("draft_key"), max_length=MAX_KEY_LENGTH)
            or make_draft_key(label=label, family_id=identity.get("family_id"), package_id=identity.get("package_id"), draft_uid=draft_uid),
            owner_user_id=normalized_owner_user_id,
            source_scope=normalized_source_scope,
            owner_scope=owner_scope_for(source_scope=normalized_source_scope, owner_user_id=normalized_owner_user_id),
            draft_mode=normalize_mode(first_non_empty(data.get("draft_mode"), data.get("mode"), draft_mode)),
            target_item_id=normalize_int(data.get("target_item_id") or data.get("item_id"), default=None, minimum=1),
            base_revision_id=normalize_int(data.get("base_revision_id"), default=None, minimum=1),
            published_revision_id=normalize_int(data.get("published_revision_id"), default=None, minimum=1),
            vplib_uid=identity.get("vplib_uid"),
            package_id=identity.get("package_id"),
            family_id=identity.get("family_id"),
            family_slug=identity.get("family_slug"),
            label=label,
            name=normalize_optional_string(data.get("name") or label, max_length=MAX_LABEL_LENGTH),
            description=identity.get("description"),
            object_kind=identity.get("object_kind"),
            family_profile_id=identity.get("family_profile_id"),
            variant_profile_id=identity.get("variant_profile_id"),
            domain=identity.get("domain"),
            category=identity.get("category"),
            subcategory=identity.get("subcategory"),
            taxonomy_path=identity.get("taxonomy_path"),
            status=normalize_status(data.get("status"), default=CreativeLibraryDraftStatus.DRAFT.value),
            stage=normalize_stage(data.get("stage"), default=CreativeLibraryDraftStage.CREATED.value),
            active=normalize_bool(data.get("active"), default=True),
            locked=normalize_bool(data.get("locked"), default=False),
            variant_count=normalize_int(data.get("variant_count"), default=0, minimum=0) or 0,
            asset_count=normalize_int(data.get("asset_count"), default=0, minimum=0) or 0,
            document_count=normalize_int(data.get("document_count"), default=0, minimum=0) or 0,
            issue_count=normalize_int(data.get("issue_count"), default=0, minimum=0) or 0,
            warning_count=normalize_int(data.get("warning_count"), default=0, minimum=0) or 0,
            error_count=normalize_int(data.get("error_count"), default=0, minimum=0) or 0,
            manifest_payload=normalize_json_mapping(data.get("manifest") or data.get("manifest_payload")),
            modules_payload=normalize_json_mapping(data.get("modules") or data.get("modules_payload")),
            family_payload=normalize_json_mapping(data.get("family") or data.get("family_payload")),
            classification_payload=normalize_json_mapping(data.get("classification") or data.get("classification_payload")),
            generator_payload=normalize_json_mapping(data.get("generator") or data.get("generator_payload")),
            validation_payload=normalize_json_mapping(data.get("validation") or data.get("validation_payload")),
            publish_payload=normalize_json_mapping(data.get("publish") or data.get("publish_payload")),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def refresh_counts(self) -> None:
        """Aktualisiert Counts aus geladenen Relationships, falls vorhanden."""
        try:
            variants = [item for item in getattr(self, "variants", []) or [] if getattr(item, "active", False)]
            assets = [item for item in getattr(self, "assets", []) or [] if getattr(item, "active", False)]
            documents = [item for item in getattr(self, "documents", []) or [] if getattr(item, "active", False)]
            issues = [item for item in getattr(self, "validation_issues", []) or [] if getattr(item, "active", False)]

            self.variant_count = len(variants)
            self.asset_count = len(assets)
            self.document_count = len(documents)
            self.issue_count = len(issues)
            self.warning_count = len([issue for issue in issues if getattr(issue, "severity", "") == CreativeLibraryDraftIssueSeverity.WARNING.value])
            self.error_count = len([
                issue
                for issue in issues
                if getattr(issue, "severity", "") in {CreativeLibraryDraftIssueSeverity.ERROR.value, CreativeLibraryDraftIssueSeverity.FATAL.value}
            ])
            self.touch()
        except Exception:
            pass

    def mark_valid(self, *, validation_payload: Mapping[str, Any] | None = None, user_id: Any = None) -> None:
        self.status = CreativeLibraryDraftStatus.VALID.value
        self.stage = CreativeLibraryDraftStage.VALIDATION.value
        self.validation_payload = normalize_json_mapping(validation_payload)
        self.validated_by_user_id = normalize_user_id(user_id, default=self.validated_by_user_id)
        self.validated_at = utc_now()
        self.touch()

    def mark_invalid(self, *, validation_payload: Mapping[str, Any] | None = None, user_id: Any = None) -> None:
        self.status = CreativeLibraryDraftStatus.INVALID.value
        self.stage = CreativeLibraryDraftStage.VALIDATION.value
        self.validation_payload = normalize_json_mapping(validation_payload)
        self.validated_by_user_id = normalize_user_id(user_id, default=self.validated_by_user_id)
        self.validated_at = utc_now()
        self.touch()

    def mark_ready_to_publish(self, *, user_id: Any = None) -> None:
        self.status = CreativeLibraryDraftStatus.READY_TO_PUBLISH.value
        self.stage = CreativeLibraryDraftStage.READY.value
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def mark_published(
        self,
        *,
        revision_id: Any = None,
        publish_payload: Mapping[str, Any] | None = None,
        user_id: Any = None,
    ) -> None:
        self.status = CreativeLibraryDraftStatus.PUBLISHED.value
        self.stage = CreativeLibraryDraftStage.PUBLISHED.value
        self.active = False
        self.published_revision_id = normalize_int(revision_id, default=self.published_revision_id, minimum=1)
        self.publish_payload = normalize_json_mapping(publish_payload)
        self.published_by_user_id = normalize_user_id(user_id, default=self.published_by_user_id)
        self.published_at = utc_now()
        self.touch()

    def discard(self, *, user_id: Any = None) -> None:
        if self.status == CreativeLibraryDraftStatus.PUBLISHED.value:
            raise ValueError("Published drafts cannot be discarded.")

        self.status = CreativeLibraryDraftStatus.DISCARDED.value
        self.active = False
        self.discarded_by_user_id = normalize_user_id(user_id, default=None)
        self.discarded_at = utc_now()
        self.touch()

    def mark_deleted(self, *, user_id: Any = None) -> None:
        if self.status == CreativeLibraryDraftStatus.PUBLISHED.value:
            raise ValueError("Published drafts cannot be deleted directly.")

        self.status = CreativeLibraryDraftStatus.DELETED.value
        self.active = False
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.deleted_at = utc_now()
        self.touch()

    def to_dict(
        self,
        *,
        include_variants: bool = False,
        include_assets: bool = False,
        include_documents: bool = False,
        include_issues: bool = False,
        include_audit: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "draft_db_id": self.id,
            "draft_uid": self.draft_uid,
            "draft_key": self.draft_key,
            "owner_user_id": self.owner_user_id,
            "source_scope": self.source_scope,
            "owner_scope": self.owner_scope,
            "draft_mode": self.draft_mode,
            "target_item_id": self.target_item_id,
            "base_revision_id": self.base_revision_id,
            "published_revision_id": self.published_revision_id,
            "vplib_uid": self.vplib_uid,
            "package_id": self.package_id,
            "family_id": self.family_id,
            "family_slug": self.family_slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "object_kind": self.object_kind,
            "family_profile_id": self.family_profile_id,
            "variant_profile_id": self.variant_profile_id,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "taxonomy_path": self.taxonomy_path,
            "status": self.status,
            "stage": self.stage,
            "active": self.active,
            "locked": self.locked,
            "variant_count": self.variant_count,
            "asset_count": self.asset_count,
            "document_count": self.document_count,
            "issue_count": self.issue_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "manifest_payload": normalize_json_mapping(self.manifest_payload),
            "modules_payload": normalize_json_mapping(self.modules_payload),
            "family_payload": normalize_json_mapping(self.family_payload),
            "classification_payload": normalize_json_mapping(self.classification_payload),
            "generator_payload": normalize_json_mapping(self.generator_payload),
            "validation_payload": normalize_json_mapping(self.validation_payload),
            "publish_payload": normalize_json_mapping(self.publish_payload),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "validated_by_user_id": self.validated_by_user_id,
            "published_by_user_id": self.published_by_user_id,
            "discarded_by_user_id": self.discarded_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "discarded_at": self.discarded_at.isoformat() if self.discarded_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_variants:
            variants = list(getattr(self, "variants", []) or [])
            variants.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "variant_id", "") or ""))
            result["variants"] = [variant.to_dict(include_draft=False) for variant in variants]

        if include_assets:
            assets = list(getattr(self, "assets", []) or [])
            assets.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "role", "") or ""))
            result["assets"] = [asset.to_dict(include_draft=False) for asset in assets]

        if include_documents:
            documents = list(getattr(self, "documents", []) or [])
            documents.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "relative_path", "") or ""))
            result["documents"] = [document.to_dict(include_draft=False) for document in documents]

        if include_issues:
            issues = list(getattr(self, "validation_issues", []) or [])
            issues.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "severity", "") or ""))
            result["validation_issues"] = [issue.to_dict(include_draft=False) for issue in issues]

        if include_audit:
            audit_events = list(getattr(self, "audit_events", []) or [])
            audit_events.sort(key=lambda item: normalize_int(getattr(item, "id", 0), default=0) or 0)
            result["audit_events"] = [event.to_dict(include_draft=False) for event in audit_events]

        return result


class CreativeLibraryDraftVariant(TimestampMixin, JsonMixin, db.Model):
    """Variant-Arbeitsstand innerhalb eines Drafts."""

    __tablename__ = "creative_library_draft_variants"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    draft_variant_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_variant_id = db.Column(
        db.BigInteger,
        db.ForeignKey(
            "creative_library_variants.id",
            name="fk_creative_library_draft_variants_source_variant_id",
            use_alter=True,
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    variant_id = db.Column(db.String(MAX_VARIANT_ID_LENGTH), nullable=False, index=True)
    slug = db.Column(db.String(MAX_SHORT_KEY_LENGTH), nullable=True, index=True)
    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    name = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    is_default = db.Column(db.Boolean, nullable=False, default=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=CreativeLibraryDraftItemStatus.ACTIVE.value,
        index=True,
    )

    family_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)
    variant_profile_id = db.Column(db.String(MAX_PROFILE_ID_LENGTH), nullable=True, index=True)

    definition_values_json = db.Column(db.JSON, nullable=False, default=dict)
    additional_field_keys_json = db.Column(db.JSON, nullable=False, default=list)
    summary_json = db.Column(db.JSON, nullable=False, default=dict)
    resolved_payload = db.Column(db.JSON, nullable=False, default=dict)
    validation_payload = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    sort_order = db.Column(db.Integer, nullable=False, default=0)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    draft = db.relationship("CreativeLibraryDraft", back_populates="variants", foreign_keys=[draft_id], lazy="joined")
    source_variant = db.relationship("CreativeLibraryVariant", foreign_keys=[source_variant_id], lazy="joined")

    assets = db.relationship(
        "CreativeLibraryDraftAsset",
        back_populates="draft_variant",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftAsset.draft_variant_id",
        lazy="selectin",
    )
    documents = db.relationship(
        "CreativeLibraryDraftDocument",
        back_populates="draft_variant",
        cascade="all, delete-orphan",
        foreign_keys="CreativeLibraryDraftDocument.draft_variant_id",
        lazy="selectin",
    )

    __table_args__ = (
        db.UniqueConstraint("draft_id", "variant_id", name="uq_creative_library_draft_variant_draft_variant"),
        db.Index("ix_creative_library_draft_variants_profile", "variant_profile_id", "family_profile_id"),
        db.Index("ix_creative_library_draft_variants_status", "draft_id", "status", "active"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDraftVariant id={self.id!r} draft_id={self.draft_id!r} variant_id={self.variant_id!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        draft: CreativeLibraryDraft | None = None,
        source_variant_id: Any = None,
        created_by_user_id: Any = None,
        sort_order: Any = 0,
    ) -> "CreativeLibraryDraftVariant":
        """Erstellt Draft-Variant aus Payload."""
        data = normalize_json_mapping(payload)
        identity = extract_variant_identity(data)

        return cls(
            draft=draft,
            draft_id=getattr(draft, "id", None),
            source_variant_id=normalize_int(first_non_empty(source_variant_id, data.get("source_variant_id")), default=None, minimum=1),
            draft_variant_uid=normalize_optional_string(data.get("draft_variant_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            variant_id=identity["variant_id"],
            slug=identity["slug"],
            label=identity["label"],
            name=identity["name"],
            description=identity["description"],
            is_default=identity["is_default"],
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            status=normalize_item_status(data.get("status")),
            family_profile_id=identity["family_profile_id"] or getattr(draft, "family_profile_id", None),
            variant_profile_id=identity["variant_profile_id"] or getattr(draft, "variant_profile_id", None),
            definition_values_json=normalize_json_mapping(data.get("definition_values") or data.get("definitionValues") or data.get("values")),
            additional_field_keys_json=normalize_json_list(data.get("additional_field_keys") or data.get("additionalFieldKeys")),
            summary_json=normalize_json_mapping(data.get("summary")),
            resolved_payload=normalize_json_mapping(data.get("resolved_payload") or data.get("resolved")),
            validation_payload=normalize_json_mapping(data.get("validation")),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            sort_order=normalize_int(first_non_empty(sort_order, data.get("sort_order")), default=0, minimum=0) or 0,
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        self.status = CreativeLibraryDraftItemStatus.DELETED.value
        self.active = False
        self.visible = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_draft: bool = False, include_assets: bool = False, include_documents: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "draft_variant_db_id": self.id,
            "draft_variant_uid": self.draft_variant_uid,
            "draft_id": self.draft_id,
            "source_variant_id": self.source_variant_id,
            "variant_id": self.variant_id,
            "slug": self.slug,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "active": self.active,
            "visible": self.visible,
            "status": self.status,
            "family_profile_id": self.family_profile_id,
            "variant_profile_id": self.variant_profile_id,
            "definition_values": normalize_json_mapping(self.definition_values_json),
            "additional_field_keys": normalize_json_list(self.additional_field_keys_json),
            "summary": normalize_json_mapping(self.summary_json),
            "resolved_payload": normalize_json_mapping(self.resolved_payload),
            "validation_payload": normalize_json_mapping(self.validation_payload),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "sort_order": self.sort_order,
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_draft:
            result["draft"] = self.draft.to_dict() if self.draft is not None else None

        if include_assets:
            assets = list(getattr(self, "assets", []) or [])
            assets.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "role", "") or ""))
            result["assets"] = [asset.to_dict(include_draft=False, include_variant=False) for asset in assets]

        if include_documents:
            documents = list(getattr(self, "documents", []) or [])
            documents.sort(key=lambda item: (normalize_int(getattr(item, "sort_order", 0), default=0) or 0, getattr(item, "relative_path", "") or ""))
            result["documents"] = [document.to_dict(include_draft=False, include_variant=False) for document in documents]

        return result


class CreativeLibraryDraftAsset(TimestampMixin, JsonMixin, db.Model):
    """Asset-/File-Verweis im Draft."""

    __tablename__ = "creative_library_draft_assets"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    draft_asset_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_variant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_draft_variants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    library_file_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_files.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    library_file_version_id = db.Column(
        db.BigInteger,
        db.ForeignKey("library_file_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    role = db.Column(db.String(MAX_ROLE_LENGTH), nullable=False, default=CreativeLibraryDraftAssetRole.OTHER.value, index=True)
    asset_kind = db.Column(db.String(80), nullable=True, index=True)
    document_type = db.Column(db.String(120), nullable=True, index=True)
    field_key = db.Column(db.String(MAX_FIELD_LENGTH), nullable=True, index=True)

    label = db.Column(db.String(MAX_LABEL_LENGTH), nullable=True)
    description = db.Column(db.Text, nullable=True)

    relative_path = db.Column(db.String(MAX_PATH_LENGTH), nullable=True, index=True)
    storage_path = db.Column(db.Text, nullable=True)
    uri = db.Column(db.Text, nullable=True)

    mime_type = db.Column(db.String(MAX_MIME_TYPE_LENGTH), nullable=True, index=True)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    sha256 = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    bounds_json = db.Column(db.JSON, nullable=False, default=dict)
    transform_json = db.Column(db.JSON, nullable=False, default=dict)

    status = db.Column(db.String(MAX_STATUS_LENGTH), nullable=False, default=CreativeLibraryDraftItemStatus.ACTIVE.value, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)
    is_primary = db.Column(db.Boolean, nullable=False, default=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    draft = db.relationship("CreativeLibraryDraft", back_populates="assets", foreign_keys=[draft_id], lazy="joined")
    draft_variant = db.relationship("CreativeLibraryDraftVariant", back_populates="assets", foreign_keys=[draft_variant_id], lazy="joined")
    library_file = db.relationship("LibraryFile", foreign_keys=[library_file_id], lazy="joined")
    library_file_version = db.relationship("LibraryFileVersion", foreign_keys=[library_file_version_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_creative_library_draft_assets_draft_role", "draft_id", "role", "active"),
        db.Index("ix_creative_library_draft_assets_variant_role", "draft_variant_id", "role"),
        db.Index("ix_creative_library_draft_assets_file", "library_file_id", "library_file_version_id"),
        db.Index("ix_creative_library_draft_assets_field", "field_key", "document_type"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDraftAsset id={self.id!r} draft_id={self.draft_id!r} role={self.role!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        draft: CreativeLibraryDraft | None = None,
        draft_variant: CreativeLibraryDraftVariant | None = None,
        created_by_user_id: Any = None,
        sort_order: Any = 0,
    ) -> "CreativeLibraryDraftAsset":
        data = normalize_json_mapping(payload)

        role = enum_value(
            first_non_empty(data.get("role"), data.get("asset_role"), data.get("asset_kind")),
            default=CreativeLibraryDraftAssetRole.OTHER.value,
        )

        return cls(
            draft=draft,
            draft_id=getattr(draft, "id", None),
            draft_variant=draft_variant,
            draft_variant_id=getattr(draft_variant, "id", None),
            draft_asset_uid=normalize_optional_string(data.get("draft_asset_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            library_file_id=normalize_int(data.get("library_file_id") or data.get("file_id"), default=None, minimum=1),
            library_file_version_id=normalize_int(data.get("library_file_version_id") or data.get("file_version_id"), default=None, minimum=1),
            role=role,
            asset_kind=normalize_optional_string(data.get("asset_kind") or data.get("kind"), max_length=80),
            document_type=normalize_optional_string(data.get("document_type") or data.get("type"), max_length=120),
            field_key=normalize_optional_string(data.get("field_key") or data.get("fieldKey"), max_length=MAX_FIELD_LENGTH),
            label=normalize_optional_string(data.get("label"), max_length=MAX_LABEL_LENGTH),
            description=normalize_optional_string(data.get("description")),
            relative_path=normalize_optional_string(data.get("relative_path") or data.get("path"), max_length=MAX_PATH_LENGTH),
            storage_path=normalize_optional_string(data.get("storage_path")),
            uri=normalize_optional_string(data.get("uri") or data.get("url")),
            mime_type=normalize_optional_string(data.get("mime_type") or data.get("mimeType"), max_length=MAX_MIME_TYPE_LENGTH),
            size_bytes=normalize_int(data.get("size_bytes") or data.get("sizeBytes"), default=None, minimum=0),
            sha256=normalize_optional_string(data.get("sha256") or data.get("checksum"), max_length=MAX_HASH_LENGTH),
            bounds_json=normalize_json_mapping(data.get("bounds") or data.get("bounds_m")),
            transform_json=normalize_json_mapping(data.get("transform")),
            status=normalize_item_status(data.get("status")),
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            is_primary=normalize_bool(data.get("is_primary") or data.get("primary"), default=False),
            sort_order=normalize_int(first_non_empty(sort_order, data.get("sort_order")), default=0, minimum=0) or 0,
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def mark_deleted(self, *, user_id: Any = None) -> None:
        self.status = CreativeLibraryDraftItemStatus.DELETED.value
        self.active = False
        self.visible = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_draft: bool = False, include_variant: bool = False, include_file: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "draft_asset_db_id": self.id,
            "draft_asset_uid": self.draft_asset_uid,
            "draft_id": self.draft_id,
            "draft_variant_id": self.draft_variant_id,
            "library_file_id": self.library_file_id,
            "library_file_version_id": self.library_file_version_id,
            "role": self.role,
            "asset_kind": self.asset_kind,
            "document_type": self.document_type,
            "field_key": self.field_key,
            "label": self.label,
            "description": self.description,
            "relative_path": self.relative_path,
            "storage_path": self.storage_path,
            "uri": self.uri,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "bounds": normalize_json_mapping(self.bounds_json),
            "transform": normalize_json_mapping(self.transform_json),
            "status": self.status,
            "active": self.active,
            "visible": self.visible,
            "is_primary": self.is_primary,
            "sort_order": self.sort_order,
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_draft:
            result["draft"] = self.draft.to_dict() if self.draft is not None else None

        if include_variant:
            result["draft_variant"] = self.draft_variant.to_dict() if self.draft_variant is not None else None

        if include_file:
            result["library_file"] = self.library_file.to_dict() if self.library_file is not None and hasattr(self.library_file, "to_dict") else None
            result["library_file_version"] = (
                self.library_file_version.to_dict()
                if self.library_file_version is not None and hasattr(self.library_file_version, "to_dict")
                else None
            )

        return result


class CreativeLibraryDraftDocument(TimestampMixin, JsonMixin, db.Model):
    """JSON-Dokument im Draft."""

    __tablename__ = "creative_library_draft_documents"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    draft_document_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_variant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_draft_variants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    relative_path = db.Column(db.String(MAX_PATH_LENGTH), nullable=False, index=True)
    module = db.Column(db.String(120), nullable=True, index=True)
    document_kind = db.Column(db.String(120), nullable=True, index=True)
    document_type = db.Column(db.String(120), nullable=True, index=True)

    checksum = db.Column(db.String(MAX_HASH_LENGTH), nullable=True, index=True)

    document_json = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    generated = db.Column(db.Boolean, nullable=False, default=False, index=True)
    dirty = db.Column(db.Boolean, nullable=False, default=True, index=True)
    required = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    visible = db.Column(db.Boolean, nullable=False, default=True, index=True)

    status = db.Column(
        db.String(MAX_STATUS_LENGTH),
        nullable=False,
        default=CreativeLibraryDraftItemStatus.ACTIVE.value,
        index=True,
    )
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    created_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    updated_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_by_user_id = db.Column(db.BigInteger, nullable=True, index=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    draft = db.relationship("CreativeLibraryDraft", back_populates="documents", foreign_keys=[draft_id], lazy="joined")
    draft_variant = db.relationship("CreativeLibraryDraftVariant", back_populates="documents", foreign_keys=[draft_variant_id], lazy="joined")

    __table_args__ = (
        db.UniqueConstraint("draft_id", "relative_path", name="uq_creative_library_draft_document_path"),
        db.Index("ix_creative_library_draft_documents_module", "draft_id", "module"),
        db.Index("ix_creative_library_draft_documents_kind", "document_kind", "document_type"),
        db.Index("ix_creative_library_draft_documents_status", "draft_id", "status", "active"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDraftDocument id={self.id!r} draft_id={self.draft_id!r} path={self.relative_path!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        draft: CreativeLibraryDraft | None = None,
        draft_variant: CreativeLibraryDraftVariant | None = None,
        created_by_user_id: Any = None,
        sort_order: Any = 0,
    ) -> "CreativeLibraryDraftDocument":
        data = normalize_json_mapping(payload)

        relative_path = normalize_relative_path(first_non_empty(data.get("relative_path"), data.get("path")))
        module = normalize_optional_string(data.get("module"), max_length=120)
        document_type = normalize_optional_string(data.get("document_type") or data.get("type"), max_length=120)
        document_kind = infer_document_kind(relative_path, module=module, document_type=document_type)

        document_payload = first_non_empty(data.get("document"), data.get("document_json"), data.get("payload"), {})
        document_json = normalize_json_mapping(document_payload if isinstance(document_payload, Mapping) else {"value": document_payload})

        return cls(
            draft=draft,
            draft_id=getattr(draft, "id", None),
            draft_variant=draft_variant,
            draft_variant_id=getattr(draft_variant, "id", None),
            draft_document_uid=normalize_optional_string(data.get("draft_document_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            relative_path=relative_path,
            module=module or document_kind,
            document_kind=document_kind,
            document_type=document_type,
            checksum=normalize_optional_string(data.get("checksum"), max_length=MAX_HASH_LENGTH) or stable_json_hash(document_json),
            document_json=document_json,
            payload=normalize_json_mapping(data),
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
            generated=normalize_bool(data.get("generated"), default=False),
            dirty=normalize_bool(data.get("dirty"), default=True),
            required=normalize_bool(data.get("required"), default=False),
            active=normalize_bool(data.get("active"), default=True),
            visible=normalize_bool(data.get("visible"), default=True),
            status=normalize_item_status(data.get("status")),
            sort_order=normalize_int(first_non_empty(sort_order, data.get("sort_order")), default=0, minimum=0) or 0,
            created_by_user_id=normalize_user_id(created_by_user_id, default=None),
            updated_by_user_id=normalize_user_id(created_by_user_id, default=None),
        )

    def update_document(self, document: Mapping[str, Any] | None, *, user_id: Any = None) -> None:
        """Aktualisiert Dokumentinhalt und Checksum."""
        self.document_json = normalize_json_mapping(document)
        self.checksum = stable_json_hash(self.document_json)
        self.dirty = True
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def mark_clean(self) -> None:
        """Markiert Dokument als synchronisiert/generiert."""
        self.dirty = False
        self.touch()

    def mark_deleted(self, *, user_id: Any = None) -> None:
        self.status = CreativeLibraryDraftItemStatus.DELETED.value
        self.active = False
        self.visible = False
        self.deleted_at = utc_now()
        self.deleted_by_user_id = normalize_user_id(user_id, default=None)
        self.updated_by_user_id = normalize_user_id(user_id, default=self.updated_by_user_id)
        self.touch()

    def to_dict(self, *, include_draft: bool = False, include_variant: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "draft_document_db_id": self.id,
            "draft_document_uid": self.draft_document_uid,
            "draft_id": self.draft_id,
            "draft_variant_id": self.draft_variant_id,
            "relative_path": self.relative_path,
            "path": self.relative_path,
            "module": self.module,
            "document_kind": self.document_kind,
            "document_type": self.document_type,
            "checksum": self.checksum,
            "document": normalize_json_mapping(self.document_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "generated": self.generated,
            "dirty": self.dirty,
            "required": self.required,
            "active": self.active,
            "visible": self.visible,
            "status": self.status,
            "sort_order": self.sort_order,
            "created_by_user_id": self.created_by_user_id,
            "updated_by_user_id": self.updated_by_user_id,
            "deleted_by_user_id": self.deleted_by_user_id,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_draft:
            result["draft"] = self.draft.to_dict() if self.draft is not None else None

        if include_variant:
            result["draft_variant"] = self.draft_variant.to_dict() if self.draft_variant is not None else None

        return result


class CreativeLibraryDraftValidationIssue(TimestampMixin, JsonMixin, db.Model):
    """Validierungsproblem im Draft."""

    __tablename__ = "creative_library_draft_validation_issues"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    issue_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    draft_variant_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_draft_variants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    severity = db.Column(db.String(MAX_SEVERITY_LENGTH), nullable=False, default=CreativeLibraryDraftIssueSeverity.ERROR.value, index=True)
    code = db.Column(db.String(MAX_CODE_LENGTH), nullable=True, index=True)
    message = db.Column(db.Text, nullable=True)

    scope = db.Column(db.String(MAX_SCOPE_LENGTH), nullable=True, index=True)
    field = db.Column(db.String(MAX_FIELD_LENGTH), nullable=True, index=True)
    path = db.Column(db.String(MAX_PATH_LENGTH), nullable=True)
    relative_path = db.Column(db.String(MAX_PATH_LENGTH), nullable=True, index=True)

    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    resolved = db.Column(db.Boolean, nullable=False, default=False, index=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    context_json = db.Column(db.JSON, nullable=False, default=dict)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    draft = db.relationship("CreativeLibraryDraft", back_populates="validation_issues", foreign_keys=[draft_id], lazy="joined")
    draft_variant = db.relationship("CreativeLibraryDraftVariant", foreign_keys=[draft_variant_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_creative_library_draft_issues_draft_severity", "draft_id", "severity", "active"),
        db.Index("ix_creative_library_draft_issues_code", "code", "scope"),
        db.Index("ix_creative_library_draft_issues_field", "field", "relative_path"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDraftValidationIssue id={self.id!r} severity={self.severity!r} code={self.code!r}>"

    @classmethod
    def create_from_payload(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        draft: CreativeLibraryDraft | None = None,
        draft_variant: CreativeLibraryDraftVariant | None = None,
        sort_order: Any = 0,
    ) -> "CreativeLibraryDraftValidationIssue":
        data = normalize_json_mapping(payload)

        return cls(
            draft=draft,
            draft_id=getattr(draft, "id", None),
            draft_variant=draft_variant,
            draft_variant_id=getattr(draft_variant, "id", None),
            issue_uid=normalize_optional_string(data.get("issue_uid") or data.get("uid"), max_length=MAX_UID_LENGTH) or new_uid(),
            severity=enum_value(data.get("severity"), default=CreativeLibraryDraftIssueSeverity.ERROR.value),
            code=normalize_optional_string(data.get("code"), max_length=MAX_CODE_LENGTH),
            message=normalize_optional_string(data.get("message") or data.get("detail") or data.get("error")),
            scope=normalize_optional_string(data.get("scope"), max_length=MAX_SCOPE_LENGTH),
            field=normalize_optional_string(data.get("field"), max_length=MAX_FIELD_LENGTH),
            path=normalize_optional_string(data.get("path"), max_length=MAX_PATH_LENGTH),
            relative_path=normalize_optional_string(data.get("relative_path") or data.get("relativePath"), max_length=MAX_PATH_LENGTH),
            active=normalize_bool(data.get("active"), default=True),
            resolved=normalize_bool(data.get("resolved"), default=False),
            sort_order=normalize_int(first_non_empty(sort_order, data.get("sort_order")), default=0, minimum=0) or 0,
            context_json=normalize_json_mapping(data.get("context") or data.get("details")),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(data.get("metadata")),
        )

    def mark_resolved(self) -> None:
        self.resolved = True
        self.active = False
        self.touch()

    def to_dict(self, *, include_draft: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "issue_db_id": self.id,
            "issue_uid": self.issue_uid,
            "draft_id": self.draft_id,
            "draft_variant_id": self.draft_variant_id,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "scope": self.scope,
            "field": self.field,
            "path": self.path,
            "relative_path": self.relative_path,
            "active": self.active,
            "resolved": self.resolved,
            "sort_order": self.sort_order,
            "context": normalize_json_mapping(self.context_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_draft:
            result["draft"] = self.draft.to_dict() if self.draft is not None else None

        return result


class CreativeLibraryDraftAuditEvent(TimestampMixin, JsonMixin, db.Model):
    """Audit-Event für Draft-Operationen."""

    __tablename__ = "creative_library_draft_audit_events"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    event_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=False, unique=True, index=True, default=new_uid)

    draft_id = db.Column(
        db.BigInteger,
        db.ForeignKey("creative_library_drafts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    event_type = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.BigInteger, nullable=True, index=True)

    target_type = db.Column(db.String(120), nullable=True, index=True)
    target_db_id = db.Column(db.BigInteger, nullable=True, index=True)
    target_uid = db.Column(db.String(MAX_UID_LENGTH), nullable=True, index=True)

    before_json = db.Column(db.JSON, nullable=False, default=dict)
    after_json = db.Column(db.JSON, nullable=False, default=dict)
    diff_json = db.Column(db.JSON, nullable=False, default=dict)

    payload = db.Column(db.JSON, nullable=False, default=dict)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)

    draft = db.relationship("CreativeLibraryDraft", back_populates="audit_events", foreign_keys=[draft_id], lazy="joined")

    __table_args__ = (
        db.Index("ix_creative_library_draft_audit_draft_event", "draft_id", "event_type", "created_at"),
        db.Index("ix_creative_library_draft_audit_user_event", "user_id", "event_type", "created_at"),
        db.Index("ix_creative_library_draft_audit_target", "target_type", "target_uid"),
    )

    def __repr__(self) -> str:
        return f"<CreativeLibraryDraftAuditEvent id={self.id!r} event_type={self.event_type!r} draft_id={self.draft_id!r}>"

    @classmethod
    def create_event(
        cls,
        *,
        event_type: Any,
        draft: CreativeLibraryDraft | None = None,
        user_id: Any = None,
        target_type: Any = None,
        target_db_id: Any = None,
        target_uid: Any = None,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
        diff: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "CreativeLibraryDraftAuditEvent":
        data = normalize_json_mapping(payload)

        return cls(
            event_uid=new_uid(),
            draft=draft,
            draft_id=getattr(draft, "id", None),
            event_type=enum_value(event_type, default=CreativeLibraryDraftAuditEventType.UPDATED.value),
            user_id=normalize_user_id(first_non_empty(user_id, data.get("user_id")), default=None),
            target_type=normalize_optional_string(target_type or data.get("target_type"), max_length=120),
            target_db_id=normalize_int(target_db_id or data.get("target_db_id"), default=None, minimum=1),
            target_uid=normalize_optional_string(target_uid or data.get("target_uid"), max_length=MAX_UID_LENGTH),
            before_json=normalize_json_mapping(before),
            after_json=normalize_json_mapping(after),
            diff_json=normalize_json_mapping(diff),
            payload=data,
            meta=normalize_json_mapping(data.get("meta")),
            metadata_json=normalize_json_mapping(metadata),
        )

    def to_dict(self, *, include_draft: bool = False) -> dict[str, Any]:
        result = {
            "id": self.id,
            "event_uid": self.event_uid,
            "draft_id": self.draft_id,
            "event_type": self.event_type,
            "user_id": self.user_id,
            "target_type": self.target_type,
            "target_db_id": self.target_db_id,
            "target_uid": self.target_uid,
            "before": normalize_json_mapping(self.before_json),
            "after": normalize_json_mapping(self.after_json),
            "diff": normalize_json_mapping(self.diff_json),
            "payload": normalize_json_mapping(self.payload),
            "meta": normalize_json_mapping(self.meta),
            "metadata": normalize_json_mapping(self.metadata_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

        if include_draft:
            result["draft"] = self.draft.to_dict() if self.draft is not None else None

        return result


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------

def build_draft_payload_summary(draft: CreativeLibraryDraft | None) -> dict[str, Any]:
    """Kompakte Draft-Zusammenfassung für Services/Routen."""
    if draft is None:
        return {}

    return {
        "draft_uid": draft.draft_uid,
        "draft_key": draft.draft_key,
        "owner_user_id": draft.owner_user_id,
        "draft_mode": draft.draft_mode,
        "status": draft.status,
        "stage": draft.stage,
        "vplib_uid": draft.vplib_uid,
        "family_id": draft.family_id,
        "package_id": draft.package_id,
        "label": draft.label,
        "object_kind": draft.object_kind,
        "taxonomy_path": draft.taxonomy_path,
        "variant_count": draft.variant_count,
        "asset_count": draft.asset_count,
        "document_count": draft.document_count,
        "issue_count": draft.issue_count,
        "error_count": draft.error_count,
        "warning_count": draft.warning_count,
    }


def draft_has_blocking_issues(issues: Iterable[Mapping[str, Any]] | None) -> bool:
    """Prüft, ob serialisierte Issues ERROR/FATAL enthalten."""
    for issue in normalize_json_list(issues):
        if not isinstance(issue, Mapping):
            continue

        severity = clean_string(issue.get("severity")).lower()
        active = normalize_bool(issue.get("active"), default=True)
        resolved = normalize_bool(issue.get("resolved"), default=False)

        if active and not resolved and severity in {CreativeLibraryDraftIssueSeverity.ERROR.value, CreativeLibraryDraftIssueSeverity.FATAL.value}:
            return True

    return False


# ---------------------------------------------------------------------------
# Public model helpers
# ---------------------------------------------------------------------------

def iter_creative_library_draft_models() -> tuple[type[Any], ...]:
    """Gibt alle echten Modelklassen dieser Datei zurück."""
    return (
        CreativeLibraryDraft,
        CreativeLibraryDraftVariant,
        CreativeLibraryDraftAsset,
        CreativeLibraryDraftDocument,
        CreativeLibraryDraftValidationIssue,
        CreativeLibraryDraftAuditEvent,
    )


def iter_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für models.__init__.py."""
    return iter_creative_library_draft_models()


def get_models() -> tuple[type[Any], ...]:
    """Kompatibler Alias für Modelle-Discovery."""
    return iter_creative_library_draft_models()


def get_creative_library_draft_model_names() -> tuple[str, ...]:
    """Gibt alle Modelklassennamen zurück."""
    return tuple(model.__name__ for model in iter_creative_library_draft_models())


def get_creative_library_draft_table_names() -> tuple[str, ...]:
    """Gibt alle Tabellennamen zurück."""
    return tuple(str(getattr(model, "__tablename__", "")) for model in iter_creative_library_draft_models())


def get_creative_library_draft_models_health() -> dict[str, Any]:
    """JSON-kompatibler Health-Snapshot dieser Model-Datei."""
    model_names = get_creative_library_draft_model_names()
    table_names = get_creative_library_draft_table_names()

    try:
        metadata = getattr(db, "metadata", None)
        tables = getattr(metadata, "tables", None)

        if tables is None:
            metadata_table_names: tuple[str, ...] = tuple()
        else:
            metadata_table_names = tuple(sorted(str(name) for name in tables.keys()))

        missing_tables = [table_name for table_name in table_names if table_name not in metadata_table_names]
        healthy = len(model_names) > 0 and len(table_names) > 0 and not missing_tables

        return {
            "schema_version": CREATIVE_LIBRARY_DRAFTS_MODELS_SCHEMA_VERSION,
            "healthy": healthy,
            "ok": healthy,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "metadata_table_count": len(metadata_table_names),
            "metadata_table_names": list(metadata_table_names),
            "missing_tables": missing_tables,
            "supports_drafts": True,
            "supports_draft_variants": True,
            "supports_draft_assets": True,
            "supports_draft_documents": True,
            "supports_validation_issues": True,
            "supports_draft_audit_events": True,
            "supports_publish_pointer": True,
        }
    except Exception as exc:
        return {
            "schema_version": CREATIVE_LIBRARY_DRAFTS_MODELS_SCHEMA_VERSION,
            "healthy": False,
            "ok": False,
            "model_count": len(model_names),
            "table_count": len(table_names),
            "model_names": list(model_names),
            "table_names": list(table_names),
            "error": f"{type(exc).__name__}: {exc}",
        }


def assert_creative_library_draft_models_ready() -> None:
    """Wirft RuntimeError, wenn die Draft-Models nicht bereit sind."""
    health = get_creative_library_draft_models_health()

    if health.get("healthy"):
        return

    raise RuntimeError(f"Creative library draft models are not ready: {health}")


def clear_creative_library_draft_model_caches() -> dict[str, Any]:
    """Leert interne Caches dieser Datei."""
    cleared: list[str] = []

    for cached_func in (
        _load_db,
        _cached_slugify,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            continue

    return {
        "ok": True,
        "cleared": cleared,
    }


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    # Metadata / constants
    "CREATIVE_LIBRARY_DRAFTS_MODELS_SCHEMA_VERSION",
    "DEFAULT_USER_ID",
    "DEFAULT_DRAFT_KEY_PREFIX",
    "DEFAULT_VARIANT_ID",

    # Enums
    "CreativeLibraryDraftSourceScope",
    "CreativeLibraryDraftMode",
    "CreativeLibraryDraftStatus",
    "CreativeLibraryDraftStage",
    "CreativeLibraryDraftItemStatus",
    "CreativeLibraryDraftAssetRole",
    "CreativeLibraryDraftDocumentKind",
    "CreativeLibraryDraftIssueSeverity",
    "CreativeLibraryDraftAuditEventType",

    # Models
    "CreativeLibraryDraft",
    "CreativeLibraryDraftVariant",
    "CreativeLibraryDraftAsset",
    "CreativeLibraryDraftDocument",
    "CreativeLibraryDraftValidationIssue",
    "CreativeLibraryDraftAuditEvent",

    # Helpers
    "utc_now",
    "new_uid",
    "enum_value",
    "first_non_empty",
    "clean_string",
    "normalize_optional_string",
    "normalize_required_string",
    "normalize_bool",
    "normalize_int",
    "normalize_user_id",
    "normalize_json_mapping",
    "normalize_json_list",
    "normalize_json_value",
    "merge_json",
    "stable_json_hash",
    "normalize_source_scope",
    "owner_scope_for",
    "normalize_status",
    "normalize_item_status",
    "normalize_stage",
    "normalize_mode",
    "normalize_slug",
    "make_draft_key",
    "normalize_taxonomy_part",
    "taxonomy_path_for",
    "extract_identity_payload",
    "extract_variant_identity",
    "infer_document_kind",
    "normalize_relative_path",
    "build_draft_payload_summary",
    "draft_has_blocking_issues",

    # Model discovery / health
    "iter_creative_library_draft_models",
    "iter_models",
    "get_models",
    "get_creative_library_draft_model_names",
    "get_creative_library_draft_table_names",
    "get_creative_library_draft_models_health",
    "assert_creative_library_draft_models_ready",
    "clear_creative_library_draft_model_caches",
]