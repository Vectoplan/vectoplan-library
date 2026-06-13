# services/vectoplan-library/src/library/domain/library_item.py
"""
Domain-Modell für einen Creative-Library-Eintrag.

Ein `LibraryItem` ist die kompakte, API-taugliche Repräsentation eines gültigen
oder ungültigen Block-/Objektpakets aus `src/library/source`.

Diese Datei ist bewusst unabhängig von:

- Flask
- Datenbank
- konkretem Scanner
- konkretem Validator
- VPLIB-Creator

Sie darf dadurch früh von Scanner, Read-Models, Routes, Tests und späteren
DB-Upsert-Prozessen verwendet werden.

Wichtige ID-Regel:

- `id` ist in Phase 1 identisch mit `family_id`
- `family_id` bleibt langfristig stabil
- `revision_hash` ändert sich bei Inhaltsänderungen
- spätere DB-Upserts sollen über `family_id` laufen

Taxonomie-Regel:

- Backend-Taxonomie ist fachlich kanonisch.
- Domain/Reiter, Kategorie und Subkategorie sind Pflicht für neue Packages.
- Der kanonische Source-Pfad lautet:
    {domain}/{category}/{subcategory}/{family_slug}
- `LibraryItem` trägt Taxonomie zusätzlich zur alten `classification`, damit
  Summary, Detail, Tree, Filter und spätere DB-Upserts dieselben Felder nutzen.

Wichtiger Kompatibilitätspunkt:

- `safe_int` akzeptiert `maximum`, damit Services wie `library_block_service`
  defensive Limit-/Offset-Normalisierung durchführen können.
- Bestehende Aufrufer, die nur `classification.domain/category/subcategory`
  verwenden, bleiben kompatibel.
- Neue Aufrufer können zusätzlich `taxonomy`, `taxonomy_version`,
  `taxonomy_path`, Labels und Source-Pfad-Metadaten setzen.

Version 0.2.0:

- `LibraryItemClassification` enthält Labels, Taxonomie-Version, Taxonomiepfad
  und Source-Pfad.
- `LibraryItem` serialisiert einen vollständigen `taxonomy`-Block.
- `to_summary_dict()` gibt domain/category/subcategory, Labels,
  taxonomy_path, classification_path und taxonomy_version direkt aus.
- `from_documents()` liest neue Manifest-/Classification-Felder:
  domain, category, subcategory, taxonomy_version, source_path,
  classification_path und labels.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Final


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_ITEM_MODEL_VERSION: Final[str] = "0.2.0"

DEFAULT_VARIANT_ID: Final[str] = "default"
DEFAULT_OBJECT_KIND: Final[str] = "unknown"
DEFAULT_STATUS: Final[str] = "unknown"

UNKNOWN_LABEL: Final[str] = "Unnamed Library Item"
UNKNOWN_TAXONOMY_VALUE: Final[str] = "unknown"

VALID_OBJECT_KINDS: Final[tuple[str, ...]] = (
    "cell_block",
    "multi_cell_module",
    "catalog_object",
    "adaptive_system",
)

VALID_ITEM_STATUSES: Final[tuple[str, ...]] = (
    "unknown",
    "candidate",
    "valid",
    "invalid",
    "duplicate",
    "error",
    "disabled",
)

STABLE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._:-]*[a-z0-9]$|^[a-z0-9]$"
)
UNSAFE_SLUG_CHARS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9_-]+")
WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
REPEATED_ID_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"[._:-]{2,}")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class LibraryItemStatus(str, Enum):
    """Status eines Library-Eintrags im dateibasierten Creative-Library-Index."""

    UNKNOWN = "unknown"
    CANDIDATE = "candidate"
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    ERROR = "error"
    DISABLED = "disabled"


class LibraryItemKind(str, Enum):
    """Unterstützte VPLIB-Objektarten für die Creative Library."""

    CELL_BLOCK = "cell_block"
    MULTI_CELL_MODULE = "multi_cell_module"
    CATALOG_OBJECT = "catalog_object"
    ADAPTIVE_SYSTEM = "adaptive_system"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Generic helper functions
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """Liefert eine UTC-Zeit im ISO-Format."""
    try:
        return datetime.now(timezone.utc).isoformat()
    except Exception:
        return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException | None,
    *,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """
    Serialisiert eine Exception JSON-kompatibel.

    Die Funktion ist bewusst tolerant gegenüber `None`, damit Fehlerpfade in
    Health-/Fallback-Funktionen keine Folgefehler erzeugen.
    """

    if exc is None:
        return {
            "type": None,
            "message": "",
        }

    try:
        data: dict[str, Any] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

        if include_traceback:
            data["traceback"] = traceback.format_exception(
                type(exc),
                exc,
                exc.__traceback__,
            )

        return data

    except Exception as serialization_exc:
        return {
            "type": "ExceptionSerializationError",
            "message": str(serialization_exc),
            "original_type": str(type(exc)),
        }


def json_safe(value: Any) -> Any:
    """Defensiver JSON-Safe-Konverter."""
    try:
        if value is None:
            return None

        if isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, Path):
            return str(value)

        if is_dataclass(value):
            return json_safe(asdict(value))

        if isinstance(value, Mapping):
            return {str(key): json_safe(item) for key, item in value.items()}

        if isinstance(value, (list, tuple, set)):
            return [json_safe(item) for item in value]

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return json_safe(to_dict())
            except TypeError:
                return json_safe(to_dict(flat=True))

        return str(value)

    except Exception as exc:
        return {
            "serialization_error": exception_to_dict(exc),
            "fallback_type": str(type(value)),
        }


def safe_str(value: Any, *, default: str = "") -> str:
    """
    Robuste String-Konvertierung.

    Leere Strings werden auf `default` normalisiert.
    """

    try:
        if value is None:
            return default

        if isinstance(value, bytes):
            try:
                text = value.decode("utf-8", errors="replace").strip()
            except Exception:
                text = str(value).strip()
        else:
            text = str(value).strip()

        if not text:
            return default

        return text

    except Exception:
        return default


def _coerce_int(value: Any, *, default: int = 0) -> int:
    """
    Interner Integer-Coercer ohne Grenzlogik.

    Akzeptiert normale Integer-Werte, numerische Strings und einfache Float-
    Strings wie `"12.0"`. Ungültige Werte fallen immer auf `default` zurück.
    """

    try:
        if value is None:
            return int(default)

        if isinstance(value, bool):
            return int(value)

        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        text = str(value).strip()

        if not text:
            return int(default)

        try:
            return int(text)
        except Exception:
            return int(float(text))

    except Exception:
        try:
            return int(default)
        except Exception:
            return 0


def safe_int(
    value: Any,
    *,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """
    Robuste Integer-Konvertierung mit optionaler Unter- und Obergrenze.

    Diese Signatur ist absichtlich rückwärtskompatibel zu älteren Aufrufern,
    die nur `default` und `minimum` verwenden, und kompatibel zu neueren
    Aufrufern wie `library_block_service`, die `maximum` übergeben.
    """

    number = _coerce_int(value, default=default)

    min_value: int | None = None
    max_value: int | None = None

    if minimum is not None:
        min_value = _coerce_int(minimum, default=0)

    if maximum is not None:
        max_value = _coerce_int(maximum, default=0)

    try:
        if min_value is not None and max_value is not None and min_value > max_value:
            min_value, max_value = max_value, min_value

        if min_value is not None:
            number = max(min_value, number)

        if max_value is not None:
            number = min(max_value, number)

        return int(number)

    except Exception:
        return _coerce_int(default, default=0)


def safe_bool(value: Any, *, default: bool = False) -> bool:
    """Robuste Bool-Konvertierung."""
    try:
        if isinstance(value, bool):
            return value

        if value is None:
            return default

        if isinstance(value, int) and value in {0, 1}:
            return bool(value)

        text = str(value).strip().lower()

        if text in {"1", "true", "yes", "y", "ja", "on", "enabled", "enable", "active"}:
            return True

        if text in {"0", "false", "no", "n", "nein", "off", "disabled", "disable", "inactive"}:
            return False

        return default

    except Exception:
        return default


def safe_path_str(value: Any) -> str | None:
    """
    Wandelt Pfade defensiv in Strings um.

    Kein Resolve, damit Pfade aus Containern/Hosts nicht versehentlich verändert
    werden. Diese Funktion normalisiert nur auf eine JSON-kompatible Form.
    """

    try:
        if value is None:
            return None

        if isinstance(value, Path):
            text = str(value)
        else:
            text = str(value).strip()

        return text or None

    except Exception:
        return None


def ensure_dict(value: Any) -> dict[str, Any]:
    """Normalisiert Mapping-artige Werte zu einem normalen Dict."""
    try:
        if value is None:
            return {}

        if isinstance(value, Mapping):
            return dict(value)

        if is_dataclass(value):
            return asdict(value)

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                raw = to_dict()
            except TypeError:
                raw = to_dict(flat=True)
            return dict(raw) if isinstance(raw, Mapping) else {}

        return {}

    except Exception:
        return {}


def ensure_list_of_strings(value: Any) -> list[str]:
    """Normalisiert beliebige Werte zu `list[str]`."""
    try:
        if value is None:
            return []

        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []

        if isinstance(value, Mapping):
            result_from_mapping: list[str] = []
            for key in value.keys():
                text = safe_str(key, default="")
                if text:
                    result_from_mapping.append(text)
            return result_from_mapping

        if isinstance(value, Iterable):
            result: list[str] = []
            for item in value:
                text = safe_str(item, default="")
                if text:
                    result.append(text)
            return result

        text = safe_str(value, default="")
        return [text] if text else []

    except Exception:
        return []


def deep_get(
    data: Mapping[str, Any] | None,
    path: str,
    *,
    default: Any = None,
) -> Any:
    """
    Liest defensiv einen verschachtelten Wert aus einem Dict.

    Beispiel:
      deep_get(manifest, "classification.domain")
    """

    if not isinstance(data, Mapping):
        return default

    try:
        current: Any = data

        for part in str(path).split("."):
            if not isinstance(current, Mapping):
                return default

            if part not in current:
                return default

            current = current[part]

        return current

    except Exception:
        return default


def first_non_empty(*values: Any, default: Any = None) -> Any:
    """Gibt den ersten nicht-leeren Wert zurück."""
    try:
        for value in values:
            if value is None:
                continue

            if isinstance(value, str) and not value.strip():
                continue

            if isinstance(value, (list, tuple, set, dict)) and not value:
                continue

            return value

        return default

    except Exception:
        return default


def dataclass_to_dict_safe(value: Any) -> dict[str, Any]:
    """Robuste Dataclass- oder Mapping-Serialisierung."""
    try:
        if value is None:
            return {}

        if is_dataclass(value):
            return asdict(value)

        if isinstance(value, Mapping):
            return dict(value)

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            raw = to_dict()
            return dict(raw) if isinstance(raw, Mapping) else {"value": raw}

        return {"value": str(value)}

    except Exception as exc:
        return {
            "status": "error",
            "error": exception_to_dict(exc),
        }


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_slug(value: Any, *, fallback: str = "library_item") -> str:
    """
    Erzeugt einen URL-/Dateinamen-tauglichen Slug.

    Diese Funktion verändert nicht die fachliche ID. Sie ist nur für Anzeige,
    Routen-Hilfen oder spätere Pfadableitungen gedacht.
    """

    try:
        text = safe_str(value, default=fallback).lower()
        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

        text = WHITESPACE_PATTERN.sub("_", text)
        text = text.replace(".", "_").replace(":", "_").replace("/", "_").replace("\\", "_")
        text = UNSAFE_SLUG_CHARS_PATTERN.sub("_", text)
        text = re.sub(r"_+", "_", text).strip("_-")

        fallback_text = safe_str(fallback, default="library_item")
        return text or fallback_text

    except Exception:
        return safe_str(fallback, default="library_item")


def normalize_taxonomy_slug(value: Any, *, fallback: str = "") -> str:
    """Normalisiert ein Taxonomie-Segment."""
    try:
        text = safe_str(value, default="").lower()
        if not text:
            return fallback

        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)

        text = re.sub(r"[^a-z0-9]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_-")
        return text or fallback
    except Exception:
        return fallback


def normalize_taxonomy_path(value: Any) -> str | None:
    """Normalisiert Taxonomie-/Source-Pfade auf Slash-Syntax."""
    try:
        if value is None:
            return None

        if isinstance(value, Path):
            raw_parts = value.parts
        elif isinstance(value, str):
            raw_parts = value.replace("\\", "/").split("/")
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
            raw_parts = list(value)
        else:
            raw_parts = str(value).replace("\\", "/").split("/")

        parts: list[str] = []

        for part in raw_parts:
            text = safe_str(part, default="")
            if not text or text in {".", ".."}:
                continue
            if text.endswith(":"):
                continue

            normalized = normalize_taxonomy_slug(text)
            if normalized:
                parts.append(normalized)

        path = "/".join(parts)
        return path or None
    except Exception:
        return None


def build_taxonomy_path(
    domain: Any = None,
    category: Any = None,
    subcategory: Any = None,
) -> str | None:
    """Baut `domain/category/subcategory`, wenn genügend Segmente vorhanden sind."""
    parts = [
        normalize_taxonomy_slug(domain),
        normalize_taxonomy_slug(category),
        normalize_taxonomy_slug(subcategory),
    ]
    parts = [part for part in parts if part]
    return "/".join(parts) if parts else None


def _normalize_stable_id_once(value: Any) -> str:
    """
    Normalisiert einen Wert einmalig zu einer stabilen ID.

    Kein rekursiver Fallback, damit ungültige Fallback-Werte keine Endlosrekursion
    auslösen können.
    """

    try:
        text = safe_str(value, default="").lower()
        text = WHITESPACE_PATTERN.sub("_", text)
        text = text.replace("/", ".").replace("\\", ".")
        text = re.sub(r"[^a-z0-9._:-]+", "_", text)
        text = REPEATED_ID_SEPARATOR_PATTERN.sub(".", text)
        text = text.strip("._:-")

        if text and STABLE_ID_PATTERN.match(text):
            return text

        return ""

    except Exception:
        return ""


def normalize_stable_id(value: Any, *, fallback: str | None = None) -> str:
    """
    Normalisiert eine stabile fachliche ID.

    Erlaubt sind bewusst:
    - Kleinbuchstaben
    - Zahlen
    - Punkt
    - Unterstrich
    - Bindestrich
    - Doppelpunkt

    Beispiele:
      vp.hochbau.waende.aussenwaende.ziegelwand
      vplib:basic_stone_block
    """

    normalized = _normalize_stable_id_once(value)

    if normalized:
        return normalized

    if fallback is not None:
        return _normalize_stable_id_once(fallback)

    return ""


def normalize_object_kind(value: Any) -> str:
    """Normalisiert `object_kind` auf bekannte Werte."""
    try:
        text = safe_str(value, default=DEFAULT_OBJECT_KIND).lower()

        aliases = {
            "block": "cell_block",
            "cell": "cell_block",
            "cellblock": "cell_block",
            "cell-block": "cell_block",
            "cell_block": "cell_block",
            "multi_cell": "multi_cell_module",
            "multi-cell": "multi_cell_module",
            "multi_cell_module": "multi_cell_module",
            "module": "multi_cell_module",
            "object": "catalog_object",
            "catalog": "catalog_object",
            "catalog-object": "catalog_object",
            "catalog_object": "catalog_object",
            "adaptive": "adaptive_system",
            "system": "adaptive_system",
            "adaptive-system": "adaptive_system",
            "adaptive_system": "adaptive_system",
        }

        normalized = aliases.get(text, text)

        if normalized in VALID_OBJECT_KINDS:
            return normalized

        return DEFAULT_OBJECT_KIND

    except Exception:
        return DEFAULT_OBJECT_KIND


def normalize_status(value: Any) -> str:
    """Normalisiert einen Item-Status."""
    try:
        text = safe_str(value, default=DEFAULT_STATUS).lower()

        if text in VALID_ITEM_STATUSES:
            return text

        return DEFAULT_STATUS

    except Exception:
        return DEFAULT_STATUS


def normalize_variant_id(value: Any) -> str:
    """Normalisiert eine Varianten-ID."""
    try:
        text = normalize_stable_id(value, fallback=DEFAULT_VARIANT_ID)

        if not text:
            return DEFAULT_VARIANT_ID

        return text

    except Exception:
        return DEFAULT_VARIANT_ID


def humanize_identifier(value: Any, *, fallback: str = UNKNOWN_LABEL) -> str:
    """Erzeugt ein lesbares Label aus Slug/ID, falls kein Label vorhanden ist."""
    try:
        text = safe_str(value, default="")

        if not text:
            return fallback

        last_part = re.split(r"[.:/\\]", text)[-1]
        last_part = last_part.replace("_", " ").replace("-", " ")
        last_part = WHITESPACE_PATTERN.sub(" ", last_part).strip()

        if not last_part:
            return fallback

        return " ".join(part.capitalize() for part in last_part.split(" "))

    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LibraryItemValidationSummary:
    """Kompakte Validierungszusammenfassung für Listen- und Detailansichten."""

    valid: bool = False
    warning_count: int = 0
    error_count: int = 0
    fatal_count: int = 0
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        try:
            warnings = tuple(ensure_list_of_strings(self.warnings))
            errors = tuple(ensure_list_of_strings(self.errors))

            object.__setattr__(self, "valid", safe_bool(self.valid, default=False))
            object.__setattr__(self, "warnings", warnings)
            object.__setattr__(self, "errors", errors)
            object.__setattr__(
                self,
                "warning_count",
                safe_int(self.warning_count, default=len(warnings), minimum=0),
            )
            object.__setattr__(
                self,
                "error_count",
                safe_int(self.error_count, default=len(errors), minimum=0),
            )
            object.__setattr__(self, "fatal_count", safe_int(self.fatal_count, default=0, minimum=0))

        except Exception:
            object.__setattr__(self, "valid", False)
            object.__setattr__(self, "warning_count", 0)
            object.__setattr__(self, "error_count", 0)
            object.__setattr__(self, "fatal_count", 0)
            object.__setattr__(self, "warnings", ())
            object.__setattr__(self, "errors", ())

    @classmethod
    def from_messages(
        cls,
        *,
        valid: bool,
        warnings: Iterable[Any] | None = None,
        errors: Iterable[Any] | None = None,
        fatal_count: int = 0,
    ) -> "LibraryItemValidationSummary":
        warning_list = tuple(ensure_list_of_strings(warnings))
        error_list = tuple(ensure_list_of_strings(errors))

        return cls(
            valid=bool(valid),
            warning_count=len(warning_list),
            error_count=len(error_list),
            fatal_count=safe_int(fatal_count, default=0, minimum=0),
            warnings=warning_list,
            errors=error_list,
        )

    @classmethod
    def from_raw(cls, value: Any) -> "LibraryItemValidationSummary":
        if isinstance(value, cls):
            return value

        data = ensure_dict(value)

        if not data:
            return cls()

        return cls(
            valid=safe_bool(data.get("valid"), default=False),
            warning_count=safe_int(data.get("warning_count"), default=0, minimum=0),
            error_count=safe_int(data.get("error_count"), default=0, minimum=0),
            fatal_count=safe_int(data.get("fatal_count"), default=0, minimum=0),
            warnings=tuple(ensure_list_of_strings(data.get("warnings"))),
            errors=tuple(ensure_list_of_strings(data.get("errors"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
            "fatal_count": self.fatal_count,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class LibraryItemAssetRefs:
    """
    Kompakte Asset-Referenzen eines Library-Items.

    In Phase 1 werden Assets nur referenziert, nicht ausgeliefert.
    """

    icon_ref: str | None = None
    preview_ref: str | None = None
    mesh_ref: str | None = None
    thumbnail_ref: str | None = None
    material_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "icon_ref", safe_path_str(self.icon_ref))
            object.__setattr__(self, "preview_ref", safe_path_str(self.preview_ref))
            object.__setattr__(self, "mesh_ref", safe_path_str(self.mesh_ref))
            object.__setattr__(self, "thumbnail_ref", safe_path_str(self.thumbnail_ref))
            object.__setattr__(self, "material_refs", tuple(ensure_list_of_strings(self.material_refs)))
        except Exception:
            object.__setattr__(self, "icon_ref", None)
            object.__setattr__(self, "preview_ref", None)
            object.__setattr__(self, "mesh_ref", None)
            object.__setattr__(self, "thumbnail_ref", None)
            object.__setattr__(self, "material_refs", ())

    @classmethod
    def from_raw(
        cls,
        *,
        icon_ref: Any = None,
        preview_ref: Any = None,
        mesh_ref: Any = None,
        thumbnail_ref: Any = None,
        material_refs: Any = None,
    ) -> "LibraryItemAssetRefs":
        return cls(
            icon_ref=safe_path_str(icon_ref),
            preview_ref=safe_path_str(preview_ref),
            mesh_ref=safe_path_str(mesh_ref),
            thumbnail_ref=safe_path_str(thumbnail_ref),
            material_refs=tuple(ensure_list_of_strings(material_refs)),
        )

    @classmethod
    def from_any(cls, value: Any) -> "LibraryItemAssetRefs":
        if isinstance(value, cls):
            return value

        data = ensure_dict(value)

        if not data:
            return cls()

        return cls.from_raw(
            icon_ref=first_non_empty(data.get("icon_ref"), data.get("icon")),
            preview_ref=first_non_empty(data.get("preview_ref"), data.get("preview")),
            mesh_ref=first_non_empty(data.get("mesh_ref"), data.get("mesh")),
            thumbnail_ref=first_non_empty(data.get("thumbnail_ref"), data.get("thumbnail")),
            material_refs=data.get("material_refs"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "icon_ref": self.icon_ref,
            "preview_ref": self.preview_ref,
            "mesh_ref": self.mesh_ref,
            "thumbnail_ref": self.thumbnail_ref,
            "material_refs": list(self.material_refs),
        }


@dataclass(frozen=True)
class LibraryItemClassification:
    """
    Fachliche Einordnung für Creative-Library-Navigation.

    `classification_path` und `taxonomy_path` sind bewusst beide vorhanden:
    - `classification_path` bleibt der bisherige Library-Begriff.
    - `taxonomy_path` ist die neue explizite Taxonomie-Sicht.
    """

    domain: str | None = None
    category: str | None = None
    subcategory: str | None = None
    classification_path: str | None = None

    domain_label: str | None = None
    category_label: str | None = None
    subcategory_label: str | None = None

    taxonomy_path: str | None = None
    source_path: str | None = None
    taxonomy_version: str | None = None

    def __post_init__(self) -> None:
        try:
            normalized_domain = normalize_taxonomy_slug(self.domain) if self.domain else None
            normalized_category = normalize_taxonomy_slug(self.category) if self.category else None
            normalized_subcategory = normalize_taxonomy_slug(self.subcategory) if self.subcategory else None

            explicit_classification_path = normalize_taxonomy_path(self.classification_path)
            explicit_taxonomy_path = normalize_taxonomy_path(self.taxonomy_path)
            derived_taxonomy_path = build_taxonomy_path(
                normalized_domain,
                normalized_category,
                normalized_subcategory,
            )

            taxonomy_path = explicit_taxonomy_path or explicit_classification_path or derived_taxonomy_path
            classification_path = explicit_classification_path or taxonomy_path

            domain_label = safe_str(self.domain_label, default="") or (
                humanize_identifier(normalized_domain) if normalized_domain else None
            )
            category_label = safe_str(self.category_label, default="") or (
                humanize_identifier(normalized_category) if normalized_category else None
            )
            subcategory_label = safe_str(self.subcategory_label, default="") or (
                humanize_identifier(normalized_subcategory) if normalized_subcategory else None
            )

            object.__setattr__(self, "domain", normalized_domain)
            object.__setattr__(self, "category", normalized_category)
            object.__setattr__(self, "subcategory", normalized_subcategory)
            object.__setattr__(self, "classification_path", classification_path)
            object.__setattr__(self, "domain_label", domain_label)
            object.__setattr__(self, "category_label", category_label)
            object.__setattr__(self, "subcategory_label", subcategory_label)
            object.__setattr__(self, "taxonomy_path", taxonomy_path)
            object.__setattr__(self, "source_path", normalize_taxonomy_path(self.source_path))
            object.__setattr__(self, "taxonomy_version", safe_str(self.taxonomy_version, default="") or None)

        except Exception:
            object.__setattr__(self, "domain", None)
            object.__setattr__(self, "category", None)
            object.__setattr__(self, "subcategory", None)
            object.__setattr__(self, "classification_path", None)
            object.__setattr__(self, "domain_label", None)
            object.__setattr__(self, "category_label", None)
            object.__setattr__(self, "subcategory_label", None)
            object.__setattr__(self, "taxonomy_path", None)
            object.__setattr__(self, "source_path", None)
            object.__setattr__(self, "taxonomy_version", None)

    @property
    def labels(self) -> dict[str, str | None]:
        return {
            "domain": self.domain_label,
            "category": self.category_label,
            "subcategory": self.subcategory_label,
        }

    @classmethod
    def from_raw(
        cls,
        *,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        classification_path: Any = None,
        domain_label: Any = None,
        category_label: Any = None,
        subcategory_label: Any = None,
        taxonomy_path: Any = None,
        source_path: Any = None,
        taxonomy_version: Any = None,
    ) -> "LibraryItemClassification":
        return cls(
            domain=domain,
            category=category,
            subcategory=subcategory,
            classification_path=classification_path,
            domain_label=domain_label,
            category_label=category_label,
            subcategory_label=subcategory_label,
            taxonomy_path=taxonomy_path,
            source_path=source_path,
            taxonomy_version=taxonomy_version,
        )

    @classmethod
    def from_any(cls, value: Any) -> "LibraryItemClassification":
        if isinstance(value, cls):
            return value

        data = ensure_dict(value)

        if not data:
            return cls()

        taxonomy = ensure_dict(data.get("taxonomy"))
        classification = ensure_dict(data.get("classification"))
        labels = ensure_dict(data.get("labels")) or ensure_dict(taxonomy.get("labels"))

        return cls.from_raw(
            domain=first_non_empty(data.get("domain"), taxonomy.get("domain"), classification.get("domain")),
            category=first_non_empty(data.get("category"), taxonomy.get("category"), classification.get("category")),
            subcategory=first_non_empty(data.get("subcategory"), taxonomy.get("subcategory"), classification.get("subcategory")),
            classification_path=first_non_empty(
                data.get("classification_path"),
                data.get("path"),
                taxonomy.get("classification_path"),
                taxonomy.get("taxonomy_path"),
                classification.get("classification_path"),
                classification.get("path"),
            ),
            domain_label=first_non_empty(data.get("domain_label"), taxonomy.get("domain_label"), labels.get("domain")),
            category_label=first_non_empty(data.get("category_label"), taxonomy.get("category_label"), labels.get("category")),
            subcategory_label=first_non_empty(data.get("subcategory_label"), taxonomy.get("subcategory_label"), labels.get("subcategory")),
            taxonomy_path=first_non_empty(data.get("taxonomy_path"), taxonomy.get("taxonomy_path")),
            source_path=first_non_empty(data.get("source_path"), taxonomy.get("source_path")),
            taxonomy_version=first_non_empty(data.get("taxonomy_version"), taxonomy.get("taxonomy_version")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "classification_path": self.classification_path,
            "domain_label": self.domain_label,
            "category_label": self.category_label,
            "subcategory_label": self.subcategory_label,
            "taxonomy_path": self.taxonomy_path,
            "source_path": self.source_path,
            "taxonomy_version": self.taxonomy_version,
            "labels": self.labels,
        }


def normalize_item_taxonomy_payload(
    *,
    classification: LibraryItemClassification,
    taxonomy: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    domain_label: Any = None,
    category_label: Any = None,
    subcategory_label: Any = None,
    taxonomy_path: Any = None,
    source_path: Any = None,
    taxonomy_version: Any = None,
) -> dict[str, Any]:
    """Baut den stabilen Taxonomieblock eines LibraryItems."""
    taxonomy_data = ensure_dict(taxonomy)
    metadata_data = ensure_dict(metadata)
    metadata_taxonomy = ensure_dict(metadata_data.get("taxonomy"))

    labels = (
        ensure_dict(taxonomy_data.get("labels"))
        or ensure_dict(metadata_taxonomy.get("labels"))
        or {}
    )

    domain = first_non_empty(
        taxonomy_data.get("domain"),
        metadata_taxonomy.get("domain"),
        classification.domain,
    )
    category = first_non_empty(
        taxonomy_data.get("category"),
        metadata_taxonomy.get("category"),
        classification.category,
    )
    subcategory = first_non_empty(
        taxonomy_data.get("subcategory"),
        metadata_taxonomy.get("subcategory"),
        classification.subcategory,
    )

    domain = normalize_taxonomy_slug(domain) if domain else None
    category = normalize_taxonomy_slug(category) if category else None
    subcategory = normalize_taxonomy_slug(subcategory) if subcategory else None

    resolved_taxonomy_path = normalize_taxonomy_path(
        first_non_empty(
            taxonomy_path,
            taxonomy_data.get("taxonomy_path"),
            metadata_taxonomy.get("taxonomy_path"),
            taxonomy_data.get("classification_path"),
            metadata_taxonomy.get("classification_path"),
            classification.taxonomy_path,
            classification.classification_path,
        )
    ) or build_taxonomy_path(domain, category, subcategory)

    resolved_classification_path = normalize_taxonomy_path(
        first_non_empty(
            taxonomy_data.get("classification_path"),
            metadata_taxonomy.get("classification_path"),
            classification.classification_path,
            resolved_taxonomy_path,
        )
    )

    resolved_source_path = normalize_taxonomy_path(
        first_non_empty(
            source_path,
            taxonomy_data.get("source_path"),
            metadata_taxonomy.get("source_path"),
            classification.source_path,
        )
    )

    resolved_taxonomy_version = safe_str(
        first_non_empty(
            taxonomy_version,
            taxonomy_data.get("taxonomy_version"),
            metadata_taxonomy.get("taxonomy_version"),
            classification.taxonomy_version,
        ),
        default="",
    ) or None

    resolved_domain_label = safe_str(
        first_non_empty(
            domain_label,
            taxonomy_data.get("domain_label"),
            metadata_taxonomy.get("domain_label"),
            labels.get("domain"),
            classification.domain_label,
            humanize_identifier(domain) if domain else None,
        ),
        default="",
    ) or None

    resolved_category_label = safe_str(
        first_non_empty(
            category_label,
            taxonomy_data.get("category_label"),
            metadata_taxonomy.get("category_label"),
            labels.get("category"),
            classification.category_label,
            humanize_identifier(category) if category else None,
        ),
        default="",
    ) or None

    resolved_subcategory_label = safe_str(
        first_non_empty(
            subcategory_label,
            taxonomy_data.get("subcategory_label"),
            metadata_taxonomy.get("subcategory_label"),
            labels.get("subcategory"),
            classification.subcategory_label,
            humanize_identifier(subcategory) if subcategory else None,
        ),
        default="",
    ) or None

    source_info = (
        ensure_dict(taxonomy_data.get("source"))
        or ensure_dict(metadata_taxonomy.get("source"))
        or {}
    )

    return {
        "domain": domain,
        "category": category,
        "subcategory": subcategory,
        "domain_label": resolved_domain_label,
        "category_label": resolved_category_label,
        "subcategory_label": resolved_subcategory_label,
        "taxonomy_path": resolved_taxonomy_path,
        "classification_path": resolved_classification_path,
        "source_path": resolved_source_path,
        "taxonomy_version": resolved_taxonomy_version,
        "labels": {
            "domain": resolved_domain_label,
            "category": resolved_category_label,
            "subcategory": resolved_subcategory_label,
        },
        "source": source_info,
    }


@dataclass(frozen=True)
class LibraryItem:
    """
    Kompakte Repräsentation eines Blocks/Objekts in der Creative Library.

    Dieses Modell ist für die Listenroute gedacht:
      GET /api/v1/vplib/library/blocks

    Die Detailroute nutzt zusätzlich `LibraryItemDetail`.
    """

    id: str
    family_id: str
    package_id: str | None = None
    slug: str | None = None
    label: str = UNKNOWN_LABEL
    description: str | None = None
    object_kind: str = DEFAULT_OBJECT_KIND
    status: str = DEFAULT_STATUS
    enabled: bool = True

    default_variant_id: str = DEFAULT_VARIANT_ID
    variant_count: int = 0
    variant_ids: tuple[str, ...] = field(default_factory=tuple)

    classification: LibraryItemClassification = field(default_factory=LibraryItemClassification)
    assets: LibraryItemAssetRefs = field(default_factory=LibraryItemAssetRefs)
    validation: LibraryItemValidationSummary = field(default_factory=LibraryItemValidationSummary)

    source_path: str | None = None
    package_root: str | None = None
    relative_package_root: str | None = None

    package_version: str | None = None
    schema_version: str | None = None
    revision_hash: str | None = None

    created_at: str | None = None
    updated_at: str | None = None
    scanned_at: str | None = None

    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)

    model_version: str = LIBRARY_ITEM_MODEL_VERSION

    taxonomy: dict[str, Any] = field(default_factory=dict)
    taxonomy_version: str | None = None
    taxonomy_path: str | None = None
    domain_label: str | None = None
    category_label: str | None = None
    subcategory_label: str | None = None

    def __post_init__(self) -> None:
        """Defensive Normalisierung auch bei direkter Dataclass-Nutzung."""
        try:
            normalized_family_id = normalize_stable_id(self.family_id, fallback=self.id)
            normalized_id = normalize_stable_id(self.id, fallback=normalized_family_id)

            if not normalized_id and normalized_family_id:
                normalized_id = normalized_family_id

            if not normalized_family_id and normalized_id:
                normalized_family_id = normalized_id

            if not normalized_id:
                normalized_id = normalize_stable_id(self.slug, fallback="unknown.library_item")

            if not normalized_family_id:
                normalized_family_id = normalized_id

            if not normalized_id:
                normalized_id = "unknown.library_item"

            if not normalized_family_id:
                normalized_family_id = normalized_id

            metadata = ensure_dict(self.metadata)

            classification = (
                self.classification
                if isinstance(self.classification, LibraryItemClassification)
                else LibraryItemClassification.from_any(self.classification)
            )

            taxonomy_payload = normalize_item_taxonomy_payload(
                classification=classification,
                taxonomy=self.taxonomy,
                metadata=metadata,
                domain_label=self.domain_label,
                category_label=self.category_label,
                subcategory_label=self.subcategory_label,
                taxonomy_path=self.taxonomy_path,
                source_path=classification.source_path,
                taxonomy_version=self.taxonomy_version,
            )

            classification = LibraryItemClassification.from_raw(
                domain=taxonomy_payload.get("domain"),
                category=taxonomy_payload.get("category"),
                subcategory=taxonomy_payload.get("subcategory"),
                classification_path=taxonomy_payload.get("classification_path"),
                domain_label=taxonomy_payload.get("domain_label"),
                category_label=taxonomy_payload.get("category_label"),
                subcategory_label=taxonomy_payload.get("subcategory_label"),
                taxonomy_path=taxonomy_payload.get("taxonomy_path"),
                source_path=taxonomy_payload.get("source_path"),
                taxonomy_version=taxonomy_payload.get("taxonomy_version"),
            )

            metadata.setdefault("taxonomy", taxonomy_payload)

            object.__setattr__(self, "id", normalized_id)
            object.__setattr__(self, "family_id", normalized_family_id)
            object.__setattr__(self, "package_id", safe_str(self.package_id, default="") or None)
            object.__setattr__(
                self,
                "slug",
                normalize_slug(first_non_empty(self.slug, self.family_id, self.id), fallback="library_item"),
            )
            object.__setattr__(
                self,
                "label",
                safe_str(self.label, default=humanize_identifier(normalized_family_id)),
            )
            object.__setattr__(self, "description", safe_str(self.description, default="") or None)
            object.__setattr__(self, "object_kind", normalize_object_kind(self.object_kind))
            object.__setattr__(self, "status", normalize_status(self.status))
            object.__setattr__(self, "enabled", safe_bool(self.enabled, default=True))
            object.__setattr__(self, "default_variant_id", normalize_variant_id(self.default_variant_id))

            normalized_variant_ids = tuple(
                normalize_variant_id(item)
                for item in ensure_list_of_strings(self.variant_ids)
                if normalize_variant_id(item)
            )

            object.__setattr__(self, "variant_ids", normalized_variant_ids)
            object.__setattr__(
                self,
                "variant_count",
                safe_int(self.variant_count, default=len(normalized_variant_ids), minimum=0),
            )

            object.__setattr__(self, "classification", classification)

            if not isinstance(self.assets, LibraryItemAssetRefs):
                object.__setattr__(self, "assets", LibraryItemAssetRefs.from_any(self.assets))

            if not isinstance(self.validation, LibraryItemValidationSummary):
                object.__setattr__(self, "validation", LibraryItemValidationSummary.from_raw(self.validation))

            object.__setattr__(self, "source_path", safe_path_str(self.source_path))
            object.__setattr__(self, "package_root", safe_path_str(self.package_root))
            object.__setattr__(self, "relative_package_root", safe_path_str(self.relative_package_root))
            object.__setattr__(self, "package_version", safe_str(self.package_version, default="") or None)
            object.__setattr__(self, "schema_version", safe_str(self.schema_version, default="") or None)
            object.__setattr__(self, "revision_hash", safe_str(self.revision_hash, default="") or None)
            object.__setattr__(self, "created_at", safe_str(self.created_at, default="") or None)
            object.__setattr__(self, "updated_at", safe_str(self.updated_at, default="") or None)
            object.__setattr__(self, "scanned_at", safe_str(self.scanned_at, default="") or None)
            object.__setattr__(self, "tags", tuple(ensure_list_of_strings(self.tags)))
            object.__setattr__(self, "metadata", metadata)
            object.__setattr__(self, "model_version", safe_str(self.model_version, default=LIBRARY_ITEM_MODEL_VERSION))
            object.__setattr__(self, "taxonomy", taxonomy_payload)
            object.__setattr__(self, "taxonomy_version", taxonomy_payload.get("taxonomy_version"))
            object.__setattr__(self, "taxonomy_path", taxonomy_payload.get("taxonomy_path"))
            object.__setattr__(self, "domain_label", taxonomy_payload.get("domain_label"))
            object.__setattr__(self, "category_label", taxonomy_payload.get("category_label"))
            object.__setattr__(self, "subcategory_label", taxonomy_payload.get("subcategory_label"))

        except Exception as exc:
            fallback_id = "unknown.library_item"
            object.__setattr__(self, "id", fallback_id)
            object.__setattr__(self, "family_id", fallback_id)
            object.__setattr__(self, "package_id", None)
            object.__setattr__(self, "slug", "library_item")
            object.__setattr__(self, "label", UNKNOWN_LABEL)
            object.__setattr__(self, "description", None)
            object.__setattr__(self, "object_kind", DEFAULT_OBJECT_KIND)
            object.__setattr__(self, "status", LibraryItemStatus.ERROR.value)
            object.__setattr__(self, "enabled", False)
            object.__setattr__(self, "default_variant_id", DEFAULT_VARIANT_ID)
            object.__setattr__(self, "variant_count", 0)
            object.__setattr__(self, "variant_ids", ())
            object.__setattr__(self, "classification", LibraryItemClassification())
            object.__setattr__(self, "assets", LibraryItemAssetRefs())
            object.__setattr__(
                self,
                "validation",
                LibraryItemValidationSummary.from_messages(
                    valid=False,
                    errors=[f"LibraryItem normalization failed: {exc}"],
                    fatal_count=1,
                ),
            )
            object.__setattr__(self, "source_path", None)
            object.__setattr__(self, "package_root", None)
            object.__setattr__(self, "relative_package_root", None)
            object.__setattr__(self, "package_version", None)
            object.__setattr__(self, "schema_version", None)
            object.__setattr__(self, "revision_hash", None)
            object.__setattr__(self, "created_at", None)
            object.__setattr__(self, "updated_at", None)
            object.__setattr__(self, "scanned_at", utc_now_iso())
            object.__setattr__(self, "tags", ())
            object.__setattr__(self, "metadata", {"normalization_error": exception_to_dict(exc)})
            object.__setattr__(self, "model_version", LIBRARY_ITEM_MODEL_VERSION)
            object.__setattr__(self, "taxonomy", {})
            object.__setattr__(self, "taxonomy_version", None)
            object.__setattr__(self, "taxonomy_path", None)
            object.__setattr__(self, "domain_label", None)
            object.__setattr__(self, "category_label", None)
            object.__setattr__(self, "subcategory_label", None)

    @property
    def is_valid(self) -> bool:
        try:
            return self.status == LibraryItemStatus.VALID.value and bool(self.validation.valid)
        except Exception:
            return False

    @property
    def is_invalid(self) -> bool:
        try:
            return self.status in {
                LibraryItemStatus.INVALID.value,
                LibraryItemStatus.ERROR.value,
                LibraryItemStatus.DUPLICATE.value,
            }
        except Exception:
            return True

    @property
    def display_label(self) -> str:
        return safe_str(self.label, default=humanize_identifier(self.family_id))

    @property
    def domain(self) -> str | None:
        return self.classification.domain

    @property
    def category(self) -> str | None:
        return self.classification.category

    @property
    def subcategory(self) -> str | None:
        return self.classification.subcategory

    @property
    def classification_path(self) -> str | None:
        return self.classification.classification_path

    @property
    def icon_ref(self) -> str | None:
        return self.assets.icon_ref

    @property
    def preview_ref(self) -> str | None:
        return self.assets.preview_ref

    def with_status(
        self,
        status: str,
        *,
        validation: LibraryItemValidationSummary | None = None,
    ) -> "LibraryItem":
        """Erstellt eine Kopie mit geändertem Status."""
        try:
            return replace(
                self,
                status=normalize_status(status),
                validation=validation if validation is not None else self.validation,
            )
        except Exception:
            return self

    def with_revision_hash(self, revision_hash: str | None) -> "LibraryItem":
        """Erstellt eine Kopie mit gesetztem Revision-Hash."""
        try:
            return replace(
                self,
                revision_hash=safe_str(revision_hash, default="") or None,
            )
        except Exception:
            return self

    def to_dict(self) -> dict[str, Any]:
        """JSON-kompatible Vollserialisierung."""
        try:
            return {
                "id": self.id,
                "family_id": self.family_id,
                "package_id": self.package_id,
                "slug": self.slug,
                "label": self.label,
                "display_label": self.display_label,
                "description": self.description,
                "object_kind": self.object_kind,
                "status": self.status,
                "enabled": self.enabled,
                "is_valid": self.is_valid,
                "is_invalid": self.is_invalid,
                "default_variant_id": self.default_variant_id,
                "variant_count": self.variant_count,
                "variant_ids": list(self.variant_ids),
                "classification": self.classification.to_dict(),
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "domain_label": self.domain_label,
                "category_label": self.category_label,
                "subcategory_label": self.subcategory_label,
                "classification_path": self.classification_path,
                "taxonomy_path": self.taxonomy_path,
                "taxonomy_version": self.taxonomy_version,
                "taxonomy": json_safe(self.taxonomy),
                "assets": self.assets.to_dict(),
                "icon_ref": self.icon_ref,
                "preview_ref": self.preview_ref,
                "validation": self.validation.to_dict(),
                "source_path": self.source_path,
                "package_root": self.package_root,
                "relative_package_root": self.relative_package_root,
                "package_version": self.package_version,
                "schema_version": self.schema_version,
                "revision_hash": self.revision_hash,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "scanned_at": self.scanned_at,
                "tags": list(self.tags),
                "metadata": json_safe(self.metadata),
                "model_version": self.model_version,
            }

        except Exception as exc:
            return {
                "id": getattr(self, "id", "unknown.library_item"),
                "family_id": getattr(self, "family_id", "unknown.library_item"),
                "status": "error",
                "error": exception_to_dict(exc),
                "model_version": LIBRARY_ITEM_MODEL_VERSION,
            }

    def to_summary_dict(self) -> dict[str, Any]:
        """Kompakte Serialisierung für Blocklisten."""
        try:
            return {
                "id": self.id,
                "family_id": self.family_id,
                "package_id": self.package_id,
                "slug": self.slug,
                "label": self.label,
                "description": self.description,
                "object_kind": self.object_kind,
                "status": self.status,
                "enabled": self.enabled,
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "domain_label": self.domain_label,
                "category_label": self.category_label,
                "subcategory_label": self.subcategory_label,
                "classification_path": self.classification_path,
                "taxonomy_path": self.taxonomy_path,
                "taxonomy_version": self.taxonomy_version,
                "taxonomy": json_safe(self.taxonomy),
                "default_variant_id": self.default_variant_id,
                "variant_count": self.variant_count,
                "icon_ref": self.icon_ref,
                "preview_ref": self.preview_ref,
                "revision_hash": self.revision_hash,
                "validation": {
                    "valid": self.validation.valid,
                    "warning_count": self.validation.warning_count,
                    "error_count": self.validation.error_count,
                    "fatal_count": self.validation.fatal_count,
                },
                "source_path": self.source_path,
                "package_version": self.package_version,
                "updated_at": self.updated_at,
                "scanned_at": self.scanned_at,
            }

        except Exception as exc:
            return {
                "id": getattr(self, "id", "unknown.library_item"),
                "family_id": getattr(self, "family_id", "unknown.library_item"),
                "status": "error",
                "error": exception_to_dict(exc),
                "model_version": LIBRARY_ITEM_MODEL_VERSION,
            }

    @classmethod
    def from_raw(
        cls,
        *,
        family_id: Any,
        package_id: Any = None,
        item_id: Any = None,
        slug: Any = None,
        label: Any = None,
        description: Any = None,
        object_kind: Any = None,
        status: Any = None,
        enabled: Any = True,
        default_variant_id: Any = DEFAULT_VARIANT_ID,
        variant_count: Any = 0,
        variant_ids: Any = None,
        domain: Any = None,
        category: Any = None,
        subcategory: Any = None,
        classification_path: Any = None,
        domain_label: Any = None,
        category_label: Any = None,
        subcategory_label: Any = None,
        taxonomy_path: Any = None,
        taxonomy_version: Any = None,
        taxonomy: Mapping[str, Any] | None = None,
        icon_ref: Any = None,
        preview_ref: Any = None,
        mesh_ref: Any = None,
        thumbnail_ref: Any = None,
        material_refs: Any = None,
        validation: LibraryItemValidationSummary | Mapping[str, Any] | None = None,
        source_path: Any = None,
        package_root: Any = None,
        relative_package_root: Any = None,
        package_version: Any = None,
        schema_version: Any = None,
        revision_hash: Any = None,
        created_at: Any = None,
        updated_at: Any = None,
        scanned_at: Any = None,
        tags: Any = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "LibraryItem":
        """Defensive Factory für manuelle oder scannerbasierte Erstellung."""
        try:
            normalized_family_id = normalize_stable_id(family_id, fallback=item_id)
            normalized_item_id = normalize_stable_id(item_id, fallback=normalized_family_id)

            if not normalized_item_id:
                normalized_item_id = normalized_family_id

            if not normalized_family_id:
                normalized_family_id = normalized_item_id or "unknown.library_item"

            final_label = first_non_empty(label, humanize_identifier(normalized_family_id))

            classification = LibraryItemClassification.from_raw(
                domain=domain,
                category=category,
                subcategory=subcategory,
                classification_path=classification_path,
                domain_label=domain_label,
                category_label=category_label,
                subcategory_label=subcategory_label,
                taxonomy_path=taxonomy_path,
                source_path=first_non_empty(ensure_dict(taxonomy).get("source_path"), source_path),
                taxonomy_version=taxonomy_version,
            )

            return cls(
                id=normalized_item_id or normalized_family_id,
                family_id=normalized_family_id,
                package_id=safe_str(package_id, default="") or None,
                slug=normalize_slug(first_non_empty(slug, normalized_family_id, normalized_item_id)),
                label=safe_str(final_label, default=UNKNOWN_LABEL),
                description=safe_str(description, default="") or None,
                object_kind=normalize_object_kind(object_kind),
                status=normalize_status(status),
                enabled=safe_bool(enabled, default=True),
                default_variant_id=normalize_variant_id(default_variant_id),
                variant_count=safe_int(variant_count, default=0, minimum=0),
                variant_ids=tuple(normalize_variant_id(item) for item in ensure_list_of_strings(variant_ids)),
                classification=classification,
                assets=LibraryItemAssetRefs.from_raw(
                    icon_ref=icon_ref,
                    preview_ref=preview_ref,
                    mesh_ref=mesh_ref,
                    thumbnail_ref=thumbnail_ref,
                    material_refs=material_refs,
                ),
                validation=LibraryItemValidationSummary.from_raw(validation)
                if validation is not None
                else LibraryItemValidationSummary(),
                source_path=safe_path_str(source_path),
                package_root=safe_path_str(package_root),
                relative_package_root=safe_path_str(relative_package_root),
                package_version=safe_str(package_version, default="") or None,
                schema_version=safe_str(schema_version, default="") or None,
                revision_hash=safe_str(revision_hash, default="") or None,
                created_at=safe_str(created_at, default="") or None,
                updated_at=safe_str(updated_at, default="") or None,
                scanned_at=safe_str(scanned_at, default="") or None,
                tags=tuple(ensure_list_of_strings(tags)),
                metadata=ensure_dict(metadata),
                taxonomy=ensure_dict(taxonomy),
                taxonomy_version=safe_str(taxonomy_version, default="") or None,
                taxonomy_path=normalize_taxonomy_path(taxonomy_path),
                domain_label=safe_str(domain_label, default="") or None,
                category_label=safe_str(category_label, default="") or None,
                subcategory_label=safe_str(subcategory_label, default="") or None,
            )

        except Exception as exc:
            fallback_id = normalize_stable_id(item_id, fallback="unknown.library_item") or "unknown.library_item"
            return cls(
                id=fallback_id,
                family_id=fallback_id,
                label=UNKNOWN_LABEL,
                object_kind=DEFAULT_OBJECT_KIND,
                status=LibraryItemStatus.ERROR.value,
                enabled=False,
                validation=LibraryItemValidationSummary.from_messages(
                    valid=False,
                    errors=[f"LibraryItem.from_raw failed: {exc}"],
                    fatal_count=1,
                ),
                scanned_at=utc_now_iso(),
                metadata={"factory_error": exception_to_dict(exc)},
            )

    @classmethod
    def from_documents(
        cls,
        documents: Mapping[str, Any],
        *,
        source_path: Any = None,
        package_root: Any = None,
        relative_package_root: Any = None,
        revision_hash: Any = None,
        status: str = LibraryItemStatus.CANDIDATE.value,
        validation: LibraryItemValidationSummary | Mapping[str, Any] | None = None,
        scanned_at: str | None = None,
    ) -> "LibraryItem":
        """
        Baut ein LibraryItem aus bereits gelesenen VPLIB-Dokumenten.

        Erwartete Keys im `documents` Mapping:
          - vplib.manifest.json
          - family/identity.json
          - family/classification.json
          - variants/index.json
          - variants/default.json
          - editor/inventory.json
          - render/render_variants.json
          - physical/base.json
          - manufacturer/contract.json

        Fehlende optionale Dokumente sind erlaubt.
        """

        try:
            safe_documents = ensure_dict(documents)

            manifest = ensure_dict(safe_documents.get("vplib.manifest.json"))
            identity = ensure_dict(safe_documents.get("family/identity.json"))
            classification = ensure_dict(safe_documents.get("family/classification.json"))
            variants_index = ensure_dict(safe_documents.get("variants/index.json"))
            default_variant = ensure_dict(safe_documents.get("variants/default.json"))
            inventory = ensure_dict(safe_documents.get("editor/inventory.json"))
            render_variants = ensure_dict(safe_documents.get("render/render_variants.json"))
            physical_base = ensure_dict(safe_documents.get("physical/base.json"))
            manufacturer_contract = ensure_dict(safe_documents.get("manufacturer/contract.json"))

            family_id = first_non_empty(
                deep_get(manifest, "family_id"),
                deep_get(identity, "family_id"),
                deep_get(identity, "id"),
                deep_get(manifest, "id"),
                deep_get(manifest, "package_id"),
            )

            package_id = first_non_empty(
                deep_get(manifest, "package_id"),
                deep_get(manifest, "id"),
            )

            label = first_non_empty(
                deep_get(identity, "label"),
                deep_get(identity, "name"),
                deep_get(identity, "family_name"),
                deep_get(manifest, "family_name"),
                deep_get(inventory, "label"),
                humanize_identifier(family_id),
            )

            description = first_non_empty(
                deep_get(identity, "description"),
                deep_get(inventory, "description"),
                deep_get(manifest, "description"),
            )

            object_kind = first_non_empty(
                deep_get(manifest, "object_kind"),
                deep_get(identity, "object_kind"),
                deep_get(classification, "object_kind"),
                deep_get(physical_base, "object_kind"),
            )

            domain = first_non_empty(
                deep_get(manifest, "domain"),
                deep_get(manifest, "classification.domain"),
                deep_get(classification, "domain"),
                deep_get(classification, "classification.domain"),
                deep_get(inventory, "domain"),
            )

            category = first_non_empty(
                deep_get(manifest, "category"),
                deep_get(manifest, "classification.category"),
                deep_get(classification, "category"),
                deep_get(classification, "classification.category"),
                deep_get(inventory, "category"),
            )

            subcategory = first_non_empty(
                deep_get(manifest, "subcategory"),
                deep_get(manifest, "classification.subcategory"),
                deep_get(classification, "subcategory"),
                deep_get(classification, "classification.subcategory"),
                deep_get(inventory, "subcategory"),
            )

            labels = ensure_dict(first_non_empty(
                deep_get(classification, "labels"),
                deep_get(manifest, "labels"),
                deep_get(inventory, "labels"),
                default={},
            ))

            classification_path = first_non_empty(
                deep_get(manifest, "classification_path"),
                deep_get(manifest, "classification.path"),
                deep_get(classification, "classification_path"),
                deep_get(classification, "path"),
            )

            taxonomy_path = first_non_empty(
                deep_get(manifest, "taxonomy_path"),
                deep_get(classification, "taxonomy_path"),
                classification_path,
            )

            taxonomy_version = first_non_empty(
                deep_get(manifest, "taxonomy_version"),
                deep_get(manifest, "classification.taxonomy_version"),
                deep_get(classification, "taxonomy_version"),
                deep_get(classification, "classification.taxonomy_version"),
            )

            document_source_path = first_non_empty(
                deep_get(manifest, "source_path"),
                deep_get(classification, "source_path"),
                deep_get(inventory, "source_path"),
            )

            default_variant_id = first_non_empty(
                deep_get(variants_index, "default_variant_id"),
                deep_get(variants_index, "default"),
                deep_get(default_variant, "variant_id"),
                deep_get(default_variant, "id"),
                DEFAULT_VARIANT_ID,
            )

            variant_ids_raw = first_non_empty(
                deep_get(variants_index, "variant_ids"),
                deep_get(variants_index, "variants"),
                default=[],
            )

            variant_ids = extract_variant_ids(variant_ids_raw)

            if not variant_ids:
                variant_ids = [normalize_variant_id(default_variant_id)]

            variant_count = first_non_empty(
                deep_get(variants_index, "variant_count"),
                len(variant_ids),
            )

            icon_ref = first_non_empty(
                deep_get(inventory, "icon_ref"),
                deep_get(inventory, "icon"),
                deep_get(render_variants, "icon_ref"),
                deep_get(render_variants, "icon"),
            )

            preview_ref = first_non_empty(
                deep_get(inventory, "preview_ref"),
                deep_get(inventory, "preview"),
                deep_get(render_variants, "preview_ref"),
                deep_get(render_variants, "preview"),
            )

            mesh_ref = first_non_empty(
                deep_get(render_variants, "mesh_ref"),
                deep_get(render_variants, "mesh"),
                deep_get(render_variants, "default.mesh_ref"),
            )

            tags = first_non_empty(
                deep_get(identity, "tags"),
                deep_get(inventory, "tags"),
                deep_get(manifest, "tags"),
                default=[],
            )

            enabled = first_non_empty(
                deep_get(manifest, "enabled"),
                deep_get(identity, "enabled"),
                deep_get(inventory, "enabled"),
                deep_get(inventory, "visible"),
                True,
            )

            package_version = first_non_empty(
                deep_get(manifest, "package_version"),
                deep_get(manifest, "version"),
            )

            schema_version = first_non_empty(
                deep_get(manifest, "schema_version"),
                deep_get(manifest, "vplib_schema_version"),
            )

            created_at = first_non_empty(
                deep_get(manifest, "created_at"),
                deep_get(identity, "created_at"),
            )

            updated_at = first_non_empty(
                deep_get(manifest, "updated_at"),
                deep_get(identity, "updated_at"),
            )

            taxonomy = normalize_item_taxonomy_payload(
                classification=LibraryItemClassification.from_raw(
                    domain=domain,
                    category=category,
                    subcategory=subcategory,
                    classification_path=classification_path,
                    domain_label=labels.get("domain"),
                    category_label=labels.get("category"),
                    subcategory_label=labels.get("subcategory"),
                    taxonomy_path=taxonomy_path,
                    source_path=document_source_path,
                    taxonomy_version=taxonomy_version,
                ),
                taxonomy={},
                metadata={},
            )

            metadata = {
                "manufacturer_ready": safe_bool(
                    first_non_empty(
                        deep_get(manufacturer_contract, "manufacturer_ready"),
                        deep_get(manufacturer_contract, "enabled"),
                        False,
                    ),
                    default=False,
                ),
                "document_count": len(safe_documents),
                "document_keys": sorted(str(key) for key in safe_documents.keys()),
                "taxonomy": taxonomy,
            }

            return cls.from_raw(
                family_id=family_id,
                package_id=package_id,
                item_id=family_id,
                slug=first_non_empty(deep_get(identity, "slug"), family_id),
                label=label,
                description=description,
                object_kind=object_kind,
                status=status,
                enabled=enabled,
                default_variant_id=default_variant_id,
                variant_count=variant_count,
                variant_ids=variant_ids,
                domain=domain,
                category=category,
                subcategory=subcategory,
                classification_path=classification_path,
                domain_label=taxonomy.get("domain_label"),
                category_label=taxonomy.get("category_label"),
                subcategory_label=taxonomy.get("subcategory_label"),
                taxonomy_path=taxonomy.get("taxonomy_path"),
                taxonomy_version=taxonomy_version,
                taxonomy=taxonomy,
                icon_ref=icon_ref,
                preview_ref=preview_ref,
                mesh_ref=mesh_ref,
                validation=validation,
                source_path=source_path,
                package_root=package_root,
                relative_package_root=relative_package_root,
                package_version=package_version,
                schema_version=schema_version,
                revision_hash=revision_hash,
                created_at=created_at,
                updated_at=updated_at,
                scanned_at=scanned_at or utc_now_iso(),
                tags=tags,
                metadata=metadata,
            )

        except Exception as exc:
            fallback_id = normalize_stable_id(source_path, fallback="unknown.library_item") or "unknown.library_item"
            return cls(
                id=fallback_id,
                family_id=fallback_id,
                label=UNKNOWN_LABEL,
                object_kind=DEFAULT_OBJECT_KIND,
                status=LibraryItemStatus.ERROR.value,
                enabled=False,
                validation=LibraryItemValidationSummary.from_messages(
                    valid=False,
                    errors=[f"LibraryItem.from_documents failed: {exc}"],
                    fatal_count=1,
                ),
                source_path=safe_path_str(source_path),
                package_root=safe_path_str(package_root),
                relative_package_root=safe_path_str(relative_package_root),
                scanned_at=scanned_at or utc_now_iso(),
                metadata={"documents_factory_error": exception_to_dict(exc)},
            )


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------

def extract_variant_ids(value: Any) -> list[str]:
    """
    Extrahiert Varianten-IDs aus verschiedenen möglichen Variantenindex-Formen.

    Unterstützt:
      ["default", "red"]
      [{"id": "default"}, {"variant_id": "red"}]
      {"default": {...}, "red": {...}}
    """

    result: list[str] = []

    try:
        if value is None:
            return result

        if isinstance(value, Mapping):
            for key, item in value.items():
                candidate = first_non_empty(
                    deep_get(item, "variant_id") if isinstance(item, Mapping) else None,
                    deep_get(item, "id") if isinstance(item, Mapping) else None,
                    key,
                )
                normalized = normalize_variant_id(candidate)
                if normalized and normalized not in result:
                    result.append(normalized)

            return result

        if isinstance(value, str):
            normalized = normalize_variant_id(value)
            return [normalized] if normalized else []

        if isinstance(value, Iterable):
            for item in value:
                if isinstance(item, Mapping):
                    candidate = first_non_empty(
                        deep_get(item, "variant_id"),
                        deep_get(item, "id"),
                        deep_get(item, "slug"),
                    )
                else:
                    candidate = item

                normalized = normalize_variant_id(candidate)

                if normalized and normalized not in result:
                    result.append(normalized)

            return result

    except Exception:
        return result

    return result


def sort_library_items(
    items: Iterable[LibraryItem],
    *,
    by: str = "classification",
) -> list[LibraryItem]:
    """
    Sortiert LibraryItems stabil für API-Ausgaben.

    `by="classification"` sortiert nach Domain/Kategorie/Subkategorie/Label.
    """

    try:
        item_list = list(items or [])

        if by == "label":
            return sorted(item_list, key=lambda item: (item.display_label.lower(), item.id))

        if by == "id":
            return sorted(item_list, key=lambda item: item.id)

        if by == "object_kind":
            return sorted(
                item_list,
                key=lambda item: (
                    item.object_kind,
                    item.display_label.lower(),
                    item.id,
                ),
            )

        if by == "updated_at":
            return sorted(
                item_list,
                key=lambda item: (
                    safe_str(item.updated_at, default=""),
                    item.id,
                ),
                reverse=True,
            )

        return sorted(
            item_list,
            key=lambda item: (
                item.domain or "",
                item.category or "",
                item.subcategory or "",
                item.display_label.lower(),
                item.id,
            ),
        )

    except Exception:
        try:
            return list(items or [])
        except Exception:
            return []


def index_library_items_by_id(
    items: Iterable[LibraryItem],
) -> tuple[dict[str, LibraryItem], list[LibraryItem]]:
    """
    Indexiert Items nach stabiler ID.

    Rückgabe:
      (items_by_id, duplicates)

    Das erste Item gewinnt. Weitere Items mit gleicher ID werden als Duplikate
    zurückgegeben.
    """

    items_by_id: dict[str, LibraryItem] = {}
    duplicates: list[LibraryItem] = []

    try:
        for item in items or []:
            try:
                item_id = safe_str(getattr(item, "id", None), default="")

                if not item_id:
                    duplicates.append(item.with_status(LibraryItemStatus.ERROR.value))
                    continue

                if item_id in items_by_id:
                    duplicates.append(item.with_status(LibraryItemStatus.DUPLICATE.value))
                    continue

                items_by_id[item_id] = item

            except Exception:
                try:
                    duplicates.append(item.with_status(LibraryItemStatus.ERROR.value))
                except Exception:
                    continue

    except Exception:
        return items_by_id, duplicates

    return items_by_id, duplicates


def filter_valid_library_items(
    items: Iterable[LibraryItem],
    *,
    enabled_only: bool = True,
) -> list[LibraryItem]:
    """Filtert gültige LibraryItems."""
    result: list[LibraryItem] = []

    try:
        for item in items or []:
            try:
                if enabled_only and not item.enabled:
                    continue

                if item.is_valid:
                    result.append(item)

            except Exception:
                continue

    except Exception:
        return result

    return result


def library_items_to_summary_dicts(
    items: Iterable[LibraryItem],
    *,
    sort: bool = True,
) -> list[dict[str, Any]]:
    """Serialisiert Items für Listenrouten."""
    try:
        item_list = sort_library_items(items) if sort else list(items or [])
    except Exception:
        item_list = []

    result: list[dict[str, Any]] = []

    for item in item_list:
        try:
            result.append(item.to_summary_dict())
        except Exception as exc:
            result.append(
                {
                    "id": getattr(item, "id", "unknown"),
                    "status": "error",
                    "error": exception_to_dict(exc),
                }
            )

    return result


def library_items_to_dicts(
    items: Iterable[LibraryItem],
    *,
    sort: bool = True,
) -> list[dict[str, Any]]:
    """Serialisiert Items vollständig."""
    try:
        item_list = sort_library_items(items) if sort else list(items or [])
    except Exception:
        item_list = []

    result: list[dict[str, Any]] = []

    for item in item_list:
        try:
            result.append(item.to_dict())
        except Exception as exc:
            result.append(
                {
                    "id": getattr(item, "id", "unknown"),
                    "status": "error",
                    "error": exception_to_dict(exc),
                }
            )

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[tuple[str, ...]] = (
    "LIBRARY_ITEM_MODEL_VERSION",
    "DEFAULT_VARIANT_ID",
    "DEFAULT_OBJECT_KIND",
    "DEFAULT_STATUS",
    "UNKNOWN_LABEL",
    "UNKNOWN_TAXONOMY_VALUE",
    "VALID_OBJECT_KINDS",
    "VALID_ITEM_STATUSES",
    "LibraryItemStatus",
    "LibraryItemKind",
    "LibraryItemValidationSummary",
    "LibraryItemAssetRefs",
    "LibraryItemClassification",
    "LibraryItem",
    "utc_now_iso",
    "exception_to_dict",
    "json_safe",
    "safe_str",
    "safe_int",
    "safe_bool",
    "safe_path_str",
    "normalize_slug",
    "normalize_taxonomy_slug",
    "normalize_taxonomy_path",
    "build_taxonomy_path",
    "normalize_stable_id",
    "normalize_object_kind",
    "normalize_status",
    "normalize_variant_id",
    "humanize_identifier",
    "ensure_list_of_strings",
    "ensure_dict",
    "deep_get",
    "first_non_empty",
    "dataclass_to_dict_safe",
    "normalize_item_taxonomy_payload",
    "extract_variant_ids",
    "sort_library_items",
    "index_library_items_by_id",
    "filter_valid_library_items",
    "library_items_to_summary_dicts",
    "library_items_to_dicts",
)