# services/vectoplan-library/models/__init__.py
"""
Database models package for vectoplan-library.

Diese Datei bündelt die SQLAlchemy-Modelle des vectoplan-library-Service.

Aktueller Fokus:
- Creative Library
- gescannte VPLIB-Packages
- stabile `vplib_uid`
- Revisionen
- Varianten
- Assets
- Dokumente
- File-/Upload-Metadaten
- Definition Catalog
- Taxonomie
- Creative-Library User Collections / Overrides
- Creative-Library Drafts / Generator-Arbeitsstände
- Creative-Library Inventory-Slots
- User-Inventar-State
- User-Inventar-Slots
- User-Inventar-Audit
- Editor-/Hotbar-Auswahl pro User

Wichtige Architekturregel:
- Die Datenbank erzeugt nicht die fachliche Block-ID.
- `vplib_uid` entsteht beim Erstellen des .vplib-Packages.
- Die Datenbank übernimmt `vplib_uid` nur aus `vplib.manifest.json`.
- DB-interne Primary Keys dürfen existieren, sind aber nicht die fachliche
  VECTOPLAN-/VPLIB-Identität.
- UserInventoryState/UserInventorySlot speichern nur User-Zustand und
  Slot-Zuordnungen; sie erzeugen keine Library-Items und keine VPLIB-UIDs.
- Definitionen, Taxonomie, Files, Drafts und User-Collections sind eigene
  Model-Module und werden hier nur registriert.

Wichtig für Flask-Migrate:
- `flask db migrate` lädt die App über FLASK_APP=wsgi:app.
- create_app() ruft `models.import_all_models()` auf.
- Diese Funktion muss alle Modelklassen importieren, damit SQLAlchemy/Alembic
  die Tabellen in `db.metadata.tables` sieht.
- Diese Datei führt keine Migration aus.
- Diese Datei erzeugt keine Tabellen.
- Diese Datei führt kein db.create_all() aus.
- Diese Datei spricht keine Datenbankverbindung aktiv an.

Diese Datei ist bewusst defensiv:
- Keine harten Imports auf noch nicht existierende Model-Dateien beim Package-Import.
- Lazy Imports über `__getattr__`.
- Explizites `import_all_models()` für App-Startup, Flask-Migrate und Tests.
- Health-/Diagnosefunktionen für App-Startup und Tests.
- Fehlende optionale Model-Module brechen nicht sofort den Import von `models`,
  können aber mit `assert_models_ready()` hart geprüft werden.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Final, Iterable, Mapping


MODELS_PACKAGE_VERSION: Final[str] = "vectoplan_library.models.v5"


class ModelsImportError(ImportError):
    """Wird ausgelöst, wenn ein Model-Modul oder Model-Symbol nicht geladen werden kann."""


@dataclass(frozen=True, slots=True)
class ModelModuleStatus:
    """Importstatus eines Model-Moduls."""

    module_key: str
    module_path: str
    loaded: bool
    error: str | None
    exported_symbols: tuple[str, ...]
    model_class_names: tuple[str, ...]
    table_names: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MODELS_PACKAGE_VERSION,
            "module_key": self.module_key,
            "module_path": self.module_path,
            "loaded": self.loaded,
            "error": self.error,
            "exported_symbols": list(self.exported_symbols),
            "exported_symbol_count": len(self.exported_symbols),
            "model_class_names": list(self.model_class_names),
            "model_class_count": len(self.model_class_names),
            "table_names": list(self.table_names),
            "table_count": len(self.table_names),
        }


# ---------------------------------------------------------------------------
# Lazy model module registry
# ---------------------------------------------------------------------------

_RELATIVE_MODEL_MODULES: Final[dict[str, str]] = {
    "creative_library": ".creative_library",
    "library_definitions": ".library_definitions",
    "library_files": ".library_files",
    "library_taxonomy": ".library_taxonomy",
    "creative_library_user": ".creative_library_user",
    "creative_library_drafts": ".creative_library_drafts",
    "user_inventory": ".user_inventory",
}


_RELATIVE_MODEL_MODULE_ALIASES: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # Backward-compatible Creative-Library aliases
    # ---------------------------------------------------------------------
    "creative": "creative_library",
    "library": "creative_library",
    "inventory": "creative_library",
    "scan": "creative_library",
    "scans": "creative_library",
    "published_library": "creative_library",
    "creative_published": "creative_library",

    # ---------------------------------------------------------------------
    # Definition Catalog aliases
    # ---------------------------------------------------------------------
    "definitions": "library_definitions",
    "definition": "library_definitions",
    "definition_catalog": "library_definitions",
    "library_definition": "library_definitions",
    "library_definition_models": "library_definitions",
    "variables": "library_definitions",
    "units": "library_definitions",
    "materials": "library_definitions",
    "document_types": "library_definitions",
    "profiles": "library_definitions",
    "variant_profiles": "library_definitions",
    "profile_bindings": "library_definitions",

    # ---------------------------------------------------------------------
    # File / Upload aliases
    # ---------------------------------------------------------------------
    "files": "library_files",
    "file": "library_files",
    "uploads": "library_files",
    "upload": "library_files",
    "assets": "library_files",
    "library_file": "library_files",
    "library_file_models": "library_files",

    # ---------------------------------------------------------------------
    # Taxonomy aliases
    # ---------------------------------------------------------------------
    "taxonomy": "library_taxonomy",
    "taxonomies": "library_taxonomy",
    "library_taxonomy_models": "library_taxonomy",
    "taxonomy_nodes": "library_taxonomy",

    # ---------------------------------------------------------------------
    # Creative-Library User aliases
    # ---------------------------------------------------------------------
    "creative_user": "creative_library_user",
    "creative_library_collections": "creative_library_user",
    "collections": "creative_library_user",
    "collection": "creative_library_user",
    "creative_library_overrides": "creative_library_user",
    "user_library": "creative_library_user",
    "user_collections": "creative_library_user",

    # ---------------------------------------------------------------------
    # Creative-Library Draft aliases
    # ---------------------------------------------------------------------
    "drafts": "creative_library_drafts",
    "draft": "creative_library_drafts",
    "creative_drafts": "creative_library_drafts",
    "creative_library_draft": "creative_library_drafts",
    "generator_drafts": "creative_library_drafts",
    "generator": "creative_library_drafts",

    # ---------------------------------------------------------------------
    # User-Inventory aliases
    # ---------------------------------------------------------------------
    "user": "user_inventory",
    "users": "user_inventory",
    "user_inventory_models": "user_inventory",
    "user_hotbar": "user_inventory",
    "hotbar": "user_inventory",
    "editor_inventory": "user_inventory",
}


_MODULE_MODEL_ITERATOR_NAMES: Final[dict[str, tuple[str, ...]]] = {
    "creative_library": (
        "iter_creative_library_models",
        "iter_models",
        "get_models",
    ),
    "library_definitions": (
        "iter_library_definition_models",
        "iter_models",
        "get_models",
    ),
    "library_files": (
        "iter_library_file_models",
        "iter_models",
        "get_models",
    ),
    "library_taxonomy": (
        "iter_library_taxonomy_models",
        "iter_models",
        "get_models",
    ),
    "creative_library_user": (
        "iter_creative_library_user_models",
        "iter_models",
        "get_models",
    ),
    "creative_library_drafts": (
        "iter_creative_library_draft_models",
        "iter_models",
        "get_models",
    ),
    "user_inventory": (
        "iter_user_inventory_models",
        "iter_models",
        "get_models",
    ),
}


# ---------------------------------------------------------------------------
# Lazy symbol map
# ---------------------------------------------------------------------------

_SYMBOL_TO_MODULE: Final[dict[str, str]] = {
    # ---------------------------------------------------------------------
    # creative_library.py
    # ---------------------------------------------------------------------
    "CREATIVE_LIBRARY_MODELS_SCHEMA_VERSION": "creative_library",
    "CREATIVE_LIBRARY_UID_FIELD": "creative_library",
    "DEFAULT_INVENTORY_KEY": "creative_library",
    "DEFAULT_USER_ID": "user_inventory",
    "CreativeLibrarySourceScope": "creative_library",
    "CreativeLibraryStatus": "creative_library",
    "CreativeLibraryScanStatus": "creative_library",
    "CreativeLibraryIssueSeverity": "creative_library",
    "CreativeLibraryAssetKind": "creative_library",
    "CreativeLibraryItem": "creative_library",
    "CreativeLibraryRevision": "creative_library",
    "CreativeLibraryVariant": "creative_library",
    "CreativeLibraryAsset": "creative_library",
    "CreativeLibraryDocument": "creative_library",
    "CreativeLibraryScanRun": "creative_library",
    "CreativeLibraryScanIssue": "creative_library",
    "CreativeLibraryInventorySlot": "creative_library",
    "CreativeLibraryFamily": "creative_library",
    "CreativeLibraryFamilyRevision": "creative_library",
    "iter_creative_library_models": "creative_library",
    "iter_creative_library_model_aliases": "creative_library",
    "get_creative_library_alias_names": "creative_library",
    "get_creative_library_model_names": "creative_library",
    "get_creative_library_models_health": "creative_library",
    "get_creative_library_table_names": "creative_library",
    "assert_creative_library_models_ready": "creative_library",
    "clear_creative_library_models_cache": "creative_library",

    # ---------------------------------------------------------------------
    # library_definitions.py
    # ---------------------------------------------------------------------
    "LIBRARY_DEFINITIONS_MODELS_SCHEMA_VERSION": "library_definitions",
    "DEFAULT_DEFINITIONS_VERSION": "library_definitions",
    "DEFAULT_SCHEMA_VERSION": "library_definitions",
    "DATASET_VARIABLES": "library_definitions",
    "DATASET_UNITS": "library_definitions",
    "DATASET_MATERIALS": "library_definitions",
    "DATASET_DOCUMENT_TYPES": "library_definitions",
    "DATASET_OBJECT_KINDS": "library_definitions",
    "DATASET_FAMILY_PROFILES": "library_definitions",
    "DATASET_VARIANT_PROFILES": "library_definitions",
    "DATASET_PROFILE_BINDINGS": "library_definitions",
    "LIBRARY_DEFINITION_DATASET_KEYS": "library_definitions",
    "MODEL_BY_DATASET_KEY": "library_definitions",
    "LibraryDefinitionSourceScope": "library_definitions",
    "LibraryDefinitionStatus": "library_definitions",
    "LibraryDefinitionSeedStatus": "library_definitions",
    "LibraryDefinitionOverrideAction": "library_definitions",
    "LibraryDefinitionValueType": "library_definitions",
    "LibraryDefinitionDataset": "library_definitions",
    "LibraryDefinitionSeedRun": "library_definitions",
    "LibraryDefinitionVariable": "library_definitions",
    "LibraryDefinitionUnit": "library_definitions",
    "LibraryDefinitionMaterial": "library_definitions",
    "LibraryDefinitionDocumentType": "library_definitions",
    "LibraryDefinitionObjectKind": "library_definitions",
    "LibraryDefinitionFamilyProfile": "library_definitions",
    "LibraryDefinitionVariantProfile": "library_definitions",
    "LibraryDefinitionProfileBinding": "library_definitions",
    "LibraryDefinitionOverride": "library_definitions",
    "model_class_for_dataset": "library_definitions",
    "create_definition_model_from_item": "library_definitions",
    "iter_library_definition_models": "library_definitions",
    "get_library_definition_model_names": "library_definitions",
    "get_library_definition_table_names": "library_definitions",
    "get_library_definition_models_health": "library_definitions",
    "assert_library_definition_models_ready": "library_definitions",
    "clear_library_definition_model_caches": "library_definitions",

    # ---------------------------------------------------------------------
    # library_files.py
    # ---------------------------------------------------------------------
    "LIBRARY_FILES_MODELS_SCHEMA_VERSION": "library_files",
    "MODEL_3D_EXTENSIONS": "library_files",
    "IMAGE_EXTENSIONS": "library_files",
    "DRAWING_EXTENSIONS": "library_files",
    "DOCUMENT_EXTENSIONS": "library_files",
    "FORBIDDEN_UPLOAD_EXTENSIONS": "library_files",
    "MANUAL_MIME_TYPES": "library_files",
    "LibraryFileSourceScope": "library_files",
    "LibraryFileStatus": "library_files",
    "LibraryFileStorageBackend": "library_files",
    "LibraryFileAssetKind": "library_files",
    "LibraryFileRole": "library_files",
    "LibraryFileLinkContextType": "library_files",
    "LibraryFileAuditEventType": "library_files",
    "LibraryFile": "library_files",
    "LibraryFileVersion": "library_files",
    "LibraryFileLink": "library_files",
    "LibraryFileAuditEvent": "library_files",
    "build_file_payload_summary": "library_files",
    "build_link_context_payload": "library_files",
    "iter_library_file_models": "library_files",
    "get_library_file_model_names": "library_files",
    "get_library_file_table_names": "library_files",
    "get_library_file_models_health": "library_files",
    "assert_library_file_models_ready": "library_files",
    "clear_library_file_model_caches": "library_files",

    # ---------------------------------------------------------------------
    # library_taxonomy.py
    # ---------------------------------------------------------------------
    "LIBRARY_TAXONOMY_MODELS_SCHEMA_VERSION": "library_taxonomy",
    "NODE_TYPE_DOMAIN": "library_taxonomy",
    "NODE_TYPE_CATEGORY": "library_taxonomy",
    "NODE_TYPE_SUBCATEGORY": "library_taxonomy",
    "TAXONOMY_NODE_TYPES": "library_taxonomy",
    "RESERVED_TAXONOMY_PARTS": "library_taxonomy",
    "LibraryTaxonomySourceScope": "library_taxonomy",
    "LibraryTaxonomyNodeType": "library_taxonomy",
    "LibraryTaxonomyStatus": "library_taxonomy",
    "LibraryTaxonomyOverrideAction": "library_taxonomy",
    "LibraryTaxonomyAuditEventType": "library_taxonomy",
    "LibraryTaxonomyNode": "library_taxonomy",
    "LibraryTaxonomyOverride": "library_taxonomy",
    "LibraryTaxonomyAuditEvent": "library_taxonomy",
    "apply_override_to_node_payload": "library_taxonomy",
    "build_taxonomy_tree_from_nodes": "library_taxonomy",
    "iter_library_taxonomy_models": "library_taxonomy",
    "get_library_taxonomy_model_names": "library_taxonomy",
    "get_library_taxonomy_table_names": "library_taxonomy",
    "get_library_taxonomy_models_health": "library_taxonomy",
    "assert_library_taxonomy_models_ready": "library_taxonomy",
    "clear_library_taxonomy_model_caches": "library_taxonomy",

    # ---------------------------------------------------------------------
    # creative_library_user.py
    # ---------------------------------------------------------------------
    "CREATIVE_LIBRARY_USER_MODELS_SCHEMA_VERSION": "creative_library_user",
    "DEFAULT_COLLECTION_KEY": "creative_library_user",
    "DEFAULT_USER_COLLECTION_KEY": "creative_library_user",
    "CreativeLibraryUserSourceScope": "creative_library_user",
    "CreativeLibraryUserStatus": "creative_library_user",
    "CreativeLibraryCollectionKind": "creative_library_user",
    "CreativeLibraryUserOverrideAction": "creative_library_user",
    "CreativeLibraryUserTargetType": "creative_library_user",
    "CreativeLibraryUserAuditEventType": "creative_library_user",
    "CreativeLibraryCollection": "creative_library_user",
    "CreativeLibraryCollectionItem": "creative_library_user",
    "CreativeLibraryUserOverride": "creative_library_user",
    "CreativeLibraryUserAuditEvent": "creative_library_user",
    "apply_user_override_to_item_payload": "creative_library_user",
    "build_resolved_collection_payload": "creative_library_user",
    "iter_creative_library_user_models": "creative_library_user",
    "get_creative_library_user_model_names": "creative_library_user",
    "get_creative_library_user_table_names": "creative_library_user",
    "get_creative_library_user_models_health": "creative_library_user",
    "assert_creative_library_user_models_ready": "creative_library_user",
    "clear_creative_library_user_model_caches": "creative_library_user",

    # ---------------------------------------------------------------------
    # creative_library_drafts.py
    # ---------------------------------------------------------------------
    "CREATIVE_LIBRARY_DRAFTS_MODELS_SCHEMA_VERSION": "creative_library_drafts",
    "DEFAULT_DRAFT_KEY_PREFIX": "creative_library_drafts",
    "DEFAULT_VARIANT_ID": "creative_library_drafts",
    "CreativeLibraryDraftSourceScope": "creative_library_drafts",
    "CreativeLibraryDraftMode": "creative_library_drafts",
    "CreativeLibraryDraftStatus": "creative_library_drafts",
    "CreativeLibraryDraftStage": "creative_library_drafts",
    "CreativeLibraryDraftItemStatus": "creative_library_drafts",
    "CreativeLibraryDraftAssetRole": "creative_library_drafts",
    "CreativeLibraryDraftDocumentKind": "creative_library_drafts",
    "CreativeLibraryDraftIssueSeverity": "creative_library_drafts",
    "CreativeLibraryDraftAuditEventType": "creative_library_drafts",
    "CreativeLibraryDraft": "creative_library_drafts",
    "CreativeLibraryDraftVariant": "creative_library_drafts",
    "CreativeLibraryDraftAsset": "creative_library_drafts",
    "CreativeLibraryDraftDocument": "creative_library_drafts",
    "CreativeLibraryDraftValidationIssue": "creative_library_drafts",
    "CreativeLibraryDraftAuditEvent": "creative_library_drafts",
    "build_draft_payload_summary": "creative_library_drafts",
    "draft_has_blocking_issues": "creative_library_drafts",
    "iter_creative_library_draft_models": "creative_library_drafts",
    "get_creative_library_draft_model_names": "creative_library_drafts",
    "get_creative_library_draft_table_names": "creative_library_drafts",
    "get_creative_library_draft_models_health": "creative_library_drafts",
    "assert_creative_library_draft_models_ready": "creative_library_drafts",
    "clear_creative_library_draft_model_caches": "creative_library_drafts",

    # ---------------------------------------------------------------------
    # user_inventory.py
    # ---------------------------------------------------------------------
    "USER_INVENTORY_MODELS_SCHEMA_VERSION": "user_inventory",
    "DEFAULT_SLOT_COUNT": "user_inventory",
    "MIN_SLOT_INDEX": "user_inventory",
    "MAX_SLOT_INDEX": "user_inventory",
    "UserInventoryAuditEventType": "user_inventory",
    "UserInventoryContentType": "user_inventory",
    "UserInventoryMode": "user_inventory",
    "UserInventorySource": "user_inventory",
    "UserInventoryStatus": "user_inventory",
    "UserInventoryState": "user_inventory",
    "UserInventorySlot": "user_inventory",
    "UserInventoryAuditEvent": "user_inventory",
    "build_default_inventory_slots": "user_inventory",
    "build_inventory_snapshot": "user_inventory",
    "slot_payload_summary": "user_inventory",
    "get_user_inventory_model_names": "user_inventory",
    "get_user_inventory_models_health": "user_inventory",
    "get_user_inventory_table_names": "user_inventory",
    "iter_user_inventory_models": "user_inventory",
    "assert_user_inventory_models_ready": "user_inventory",
    "clear_user_inventory_models_cache": "user_inventory",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _canonical_module_key(module_key: str) -> str:
    """Normalisiert Model-Modulkeys und Komfort-Aliase."""
    try:
        key = str(module_key).strip()
    except Exception as exc:
        raise ModelsImportError("Invalid models module key.") from exc

    if not key:
        raise ModelsImportError("Empty models module key.")

    return _RELATIVE_MODEL_MODULE_ALIASES.get(key, key)


@lru_cache(maxsize=128)
def _load_model_module(module_key: str) -> ModuleType:
    """Lädt ein Model-Modul lazy über relative Imports."""
    canonical_key = _canonical_module_key(module_key)

    if canonical_key not in _RELATIVE_MODEL_MODULES:
        raise ModelsImportError(f"Unknown models module {module_key!r}.")

    relative_path = _RELATIVE_MODEL_MODULES[canonical_key]

    try:
        return importlib.import_module(relative_path, package=__name__)
    except Exception as exc:
        raise ModelsImportError(
            f"Could not import models module "
            f"{canonical_key!r} from {relative_path!r}: {exc}"
        ) from exc


def __getattr__(name: str) -> Any:
    """
    Lazy-Reexport für öffentliche Model-Symbole.

    Beispiele:
        from models import CreativeLibraryItem
        from models import LibraryDefinitionVariable
        from models import LibraryFile
        from models import LibraryTaxonomyNode
        from models import CreativeLibraryCollection
        from models import CreativeLibraryDraft
        from models import UserInventoryState
        from models import import_all_models
    """
    canonical_module_name = _RELATIVE_MODEL_MODULE_ALIASES.get(name, name)

    if canonical_module_name in _RELATIVE_MODEL_MODULES:
        module = _load_model_module(canonical_module_name)
        globals()[name] = module
        return module

    module_key = _SYMBOL_TO_MODULE.get(name)

    if not module_key:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = _load_model_module(module_key)

    try:
        value = getattr(module, name)
    except AttributeError as exc:
        raise ModelsImportError(
            f"Model symbol {name!r} is mapped to module {module_key!r}, "
            f"but the module does not export it."
        ) from exc

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Ergänzt Lazy-Reexport-Symbole in dir(models)."""
    names = set(globals().keys())
    names.update(_RELATIVE_MODEL_MODULES.keys())
    names.update(_RELATIVE_MODEL_MODULE_ALIASES.keys())
    names.update(_SYMBOL_TO_MODULE.keys())
    return sorted(names)


# ---------------------------------------------------------------------------
# Public registry helpers
# ---------------------------------------------------------------------------

def get_model_module_keys(*, include_aliases: bool = False) -> tuple[str, ...]:
    """
    Gibt alle bekannten Model-Modulkeys zurück.

    Args:
        include_aliases:
            Wenn True, werden Komfort-Aliase ergänzt.
    """
    keys = list(_RELATIVE_MODEL_MODULES.keys())

    if include_aliases:
        keys.extend(_RELATIVE_MODEL_MODULE_ALIASES.keys())

    return tuple(_dedupe_strings(keys))


def get_model_module_alias_map() -> Mapping[str, str]:
    """Gibt die Alias-zu-Modul-Zuordnung zurück."""
    return dict(_RELATIVE_MODEL_MODULE_ALIASES)


def get_model_symbol_names() -> tuple[str, ...]:
    """Gibt alle lazy exportierten öffentlichen Symbolnamen zurück."""
    return tuple(sorted(_SYMBOL_TO_MODULE.keys()))


def get_model_symbol_module_map() -> Mapping[str, str]:
    """Gibt die Symbol-zu-Modul-Zuordnung zurück."""
    return dict(_SYMBOL_TO_MODULE)


def is_model_symbol(name: str) -> bool:
    """Gibt zurück, ob ein Symbol oder Modul-Alias über dieses Package exportiert wird."""
    try:
        key = str(name).strip()
    except Exception:
        return False

    if not key:
        return False

    return (
        key in _SYMBOL_TO_MODULE
        or key in _RELATIVE_MODEL_MODULES
        or key in _RELATIVE_MODEL_MODULE_ALIASES
    )


def load_model_module(module_key: str) -> ModuleType:
    """Öffentlicher Loader für ein einzelnes Model-Modul."""
    return _load_model_module(module_key)


def load_all_model_modules(*, strict: bool = True) -> tuple[ModuleType, ...]:
    """
    Lädt alle kanonischen Model-Module.

    Nützlich für:
    - App-Startup
    - Flask-Migrate/Alembic
    - Tests
    - Healthchecks

    Aliase werden nicht doppelt geladen.
    """
    modules: list[ModuleType] = []
    errors: list[str] = []

    for module_key in get_model_module_keys(include_aliases=False):
        try:
            modules.append(_load_model_module(module_key))
        except Exception as exc:
            errors.append(f"{module_key}: {exc}")
            if strict:
                raise

    if errors and strict:
        raise ModelsImportError("; ".join(errors))

    return tuple(modules)


def import_all_models(*, strict: bool = True) -> tuple[type[Any], ...]:
    """
    Importiert alle bekannten Model-Module und gibt erkannte SQLAlchemy-Modelklassen zurück.

    Diese Funktion wird von `app.py` genutzt:

        from models import import_all_models
        import_all_models()

    Dadurch sind die Modelklassen importiert und SQLAlchemy/Alembic kann sie
    über die gemeinsame `db.Model`-Registry erkennen.

    Args:
        strict:
            Wenn True, bricht ein Importfehler hart ab.
            Wenn False, werden bestmögliche Ergebnisse zurückgegeben.
    """
    model_classes: list[type[Any]] = []
    errors: list[str] = []

    for module_key in get_model_module_keys(include_aliases=False):
        try:
            module = _load_model_module(module_key)
            model_classes.extend(_iter_model_classes_from_module(module, module_key=module_key))
        except Exception as exc:
            errors.append(f"{module_key}: {exc}")
            if strict:
                raise

    if errors and strict:
        raise ModelsImportError("; ".join(errors))

    return tuple(_dedupe_model_classes(model_classes))


def iter_model_classes() -> tuple[type[Any], ...]:
    """Alias für import_all_models(), semantisch für Diagnose/Tests."""
    return import_all_models(strict=True)


def get_model_class_names() -> tuple[str, ...]:
    """Gibt erkannte SQLAlchemy-Modelklassennamen zurück."""
    try:
        return tuple(sorted(model.__name__ for model in import_all_models(strict=False)))
    except Exception:
        return tuple()


def get_model_table_names() -> tuple[str, ...]:
    """Gibt deklarierte Tabellennamen der importierten Modelklassen zurück."""
    try:
        return tuple(
            sorted(
                table_name
                for table_name in (
                    _get_model_table_name(model)
                    for model in import_all_models(strict=False)
                )
                if table_name
            )
        )
    except Exception:
        return tuple()


def get_model_module_statuses() -> tuple[ModelModuleStatus, ...]:
    """
    Gibt Importstatus für alle Model-Module zurück.

    Diese Funktion wirft nicht, sondern sammelt Fehler in Statusobjekten.
    """
    statuses: list[ModelModuleStatus] = []

    for module_key, relative_path in _RELATIVE_MODEL_MODULES.items():
        exported_symbols = tuple(
            sorted(
                symbol
                for symbol, mapped_module_key in _SYMBOL_TO_MODULE.items()
                if mapped_module_key == module_key
            )
        )

        try:
            module = _load_model_module(module_key)
            model_classes = _iter_model_classes_from_module(module, module_key=module_key)
            model_class_names = tuple(sorted(model.__name__ for model in model_classes))
            table_names = tuple(
                sorted(
                    table_name
                    for table_name in (_get_model_table_name(model) for model in model_classes)
                    if table_name
                )
            )

            statuses.append(
                ModelModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=True,
                    error=None,
                    exported_symbols=exported_symbols,
                    model_class_names=model_class_names,
                    table_names=table_names,
                )
            )
        except Exception as exc:
            statuses.append(
                ModelModuleStatus(
                    module_key=module_key,
                    module_path=relative_path,
                    loaded=False,
                    error=str(exc),
                    exported_symbols=exported_symbols,
                    model_class_names=tuple(),
                    table_names=tuple(),
                )
            )

    return tuple(statuses)


def get_models_metadata_snapshot() -> dict[str, Any]:
    """
    Gibt einen Snapshot von `db.metadata.tables` zurück.

    Diese Funktion ist für App-Health und Flask-Migrate-Diagnose nützlich.
    Sie erzeugt keine Tabellen und öffnet keine DB-Verbindung.
    """
    try:
        import_all_models(strict=False)
    except Exception:
        pass

    try:
        db = _load_db_extension()
        metadata = getattr(db, "metadata", None)
        tables = getattr(metadata, "tables", None)

        if tables is None:
            return {
                "schema_version": MODELS_PACKAGE_VERSION,
                "available": False,
                "table_count": 0,
                "table_names": [],
                "expected_table_names": list(get_model_table_names()),
                "missing_expected_table_names": list(get_model_table_names()),
                "error": "db.metadata.tables is not available.",
            }

        table_names = tuple(sorted(str(name) for name in tables.keys()))
        expected_table_names = get_model_table_names()

        return {
            "schema_version": MODELS_PACKAGE_VERSION,
            "available": True,
            "table_count": len(table_names),
            "table_names": list(table_names),
            "expected_table_names": list(expected_table_names),
            "missing_expected_table_names": [
                name
                for name in expected_table_names
                if name not in table_names
            ],
        }
    except Exception as exc:
        return {
            "schema_version": MODELS_PACKAGE_VERSION,
            "available": False,
            "table_count": 0,
            "table_names": [],
            "expected_table_names": list(get_model_table_names()),
            "missing_expected_table_names": list(get_model_table_names()),
            "error": str(exc),
        }


def get_models_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot der Models-Schicht zurück."""
    statuses = get_model_module_statuses()
    metadata_snapshot = get_models_metadata_snapshot()

    try:
        loaded = [status for status in statuses if status.loaded]
        failed = [status for status in statuses if not status.loaded]
        model_class_count = sum(len(status.model_class_names) for status in statuses)
        table_count = sum(len(status.table_names) for status in statuses)
        metadata_table_count = int(metadata_snapshot.get("table_count") or 0)
        missing_expected_table_names = metadata_snapshot.get("missing_expected_table_names") or []
        healthy = (
            len(failed) == 0
            and model_class_count > 0
            and metadata_table_count > 0
            and not missing_expected_table_names
        )
    except Exception:
        loaded = []
        failed = list(statuses)
        model_class_count = 0
        table_count = 0
        metadata_table_count = 0
        missing_expected_table_names = []
        healthy = False

    return {
        "schema_version": MODELS_PACKAGE_VERSION,
        "healthy": healthy,
        "module_count": len(statuses),
        "loaded_module_count": len(loaded),
        "failed_module_count": len(failed),
        "model_class_count": model_class_count,
        "table_count": table_count,
        "metadata_table_count": metadata_table_count,
        "symbol_count": len(_SYMBOL_TO_MODULE),
        "alias_count": len(_RELATIVE_MODEL_MODULE_ALIASES),
        "aliases": get_model_module_alias_map(),
        "model_module_keys": list(get_model_module_keys(include_aliases=False)),
        "model_class_names": list(get_model_class_names()),
        "table_names": list(get_model_table_names()),
        "missing_expected_table_names": list(missing_expected_table_names),
        "metadata": metadata_snapshot,
        "modules": [status.to_dict() for status in statuses],
        "supports_creative_library": is_model_symbol("CreativeLibraryItem"),
        "supports_library_definitions": is_model_symbol("LibraryDefinitionVariable"),
        "supports_library_files": is_model_symbol("LibraryFile"),
        "supports_library_taxonomy": is_model_symbol("LibraryTaxonomyNode"),
        "supports_creative_library_user": is_model_symbol("CreativeLibraryCollection"),
        "supports_creative_library_drafts": is_model_symbol("CreativeLibraryDraft"),
        "supports_user_inventory": is_model_symbol("UserInventoryState"),
        "supports_user_inventory_slots": is_model_symbol("UserInventorySlot"),
        "supports_user_inventory_audit": is_model_symbol("UserInventoryAuditEvent"),
        "supports_model_aliases": True,
        "supports_lazy_imports": True,
    }


def assert_models_ready() -> None:
    """
    Prüft, ob alle Model-Module ladbar sind und Modeltabellen sichtbar sind.

    Raises:
        ModelsImportError: Wenn mindestens ein Modul nicht importiert werden kann
        oder keine Tabellen in db.metadata sichtbar sind.
    """
    statuses = get_model_module_statuses()
    failed = [status for status in statuses if not status.loaded]

    if failed:
        details = "; ".join(
            f"{status.module_key}: {status.error}" for status in failed
        )
        raise ModelsImportError(f"Models package is not ready: {details}")

    model_classes = import_all_models(strict=True)
    if not model_classes:
        raise ModelsImportError("No SQLAlchemy model classes were imported.")

    metadata_snapshot = get_models_metadata_snapshot()
    if not metadata_snapshot.get("available"):
        raise ModelsImportError(f"db.metadata is not available: {metadata_snapshot.get('error')}")

    if int(metadata_snapshot.get("table_count") or 0) <= 0:
        raise ModelsImportError("No SQLAlchemy tables are registered in db.metadata.")

    missing_expected_table_names = metadata_snapshot.get("missing_expected_table_names") or []
    if missing_expected_table_names:
        raise ModelsImportError(
            "Not all expected SQLAlchemy tables are registered in db.metadata: "
            + ", ".join(str(name) for name in missing_expected_table_names)
        )


def clear_model_caches() -> None:
    """
    Leert interne Model-Import-Caches.

    Das ist vor allem für Tests, Reload-Szenarien und Entwicklungsdiagnose nützlich.
    """
    try:
        _load_model_module.cache_clear()
    except Exception:
        pass

    for module_key in get_model_module_keys(include_aliases=False):
        try:
            module = _load_model_module(module_key)
        except Exception:
            continue

        for function_name in (
            "clear_creative_library_models_cache",
            "clear_library_definition_model_caches",
            "clear_library_file_model_caches",
            "clear_library_taxonomy_model_caches",
            "clear_creative_library_user_model_caches",
            "clear_creative_library_draft_model_caches",
            "clear_user_inventory_models_cache",
        ):
            try:
                candidate = getattr(module, function_name, None)
                if callable(candidate):
                    candidate()
            except Exception:
                continue

    try:
        _load_model_module.cache_clear()
    except Exception:
        pass


def model_status_to_json(status: ModelModuleStatus) -> dict[str, Any]:
    """Serialisiert einen ModelModuleStatus JSON-kompatibel."""
    try:
        return status.to_dict()
    except Exception:
        return {
            "schema_version": MODELS_PACKAGE_VERSION,
            "module_key": str(getattr(status, "module_key", "<unknown>")),
            "module_path": str(getattr(status, "module_path", "<unknown>")),
            "loaded": bool(getattr(status, "loaded", False)),
            "error": str(getattr(status, "error", None)),
            "exported_symbols": list(getattr(status, "exported_symbols", ()) or ()),
            "model_class_names": list(getattr(status, "model_class_names", ()) or ()),
            "table_names": list(getattr(status, "table_names", ()) or ()),
        }


def model_statuses_to_json() -> list[dict[str, Any]]:
    """Serialisiert alle Model-Modulstatuswerte JSON-kompatibel."""
    return [model_status_to_json(status) for status in get_model_module_statuses()]


# ---------------------------------------------------------------------------
# Model introspection helpers
# ---------------------------------------------------------------------------

def _iter_model_classes_from_module(
    module: ModuleType,
    *,
    module_key: str | None = None,
) -> tuple[type[Any], ...]:
    """
    Erkennt SQLAlchemy-Modelklassen in einem Modul.

    Bevorzugt werden explizite Iterator-Funktionen des Moduls, z.B.:

        iter_creative_library_models()
        iter_library_definition_models()
        iter_library_file_models()
        iter_library_taxonomy_models()
        iter_creative_library_user_models()
        iter_creative_library_draft_models()
        iter_user_inventory_models()

    Fallback:
    - Objekt ist Klasse
    - Klasse hat `__tablename__`
    - Klasse wirkt wie SQLAlchemy-Declarative-Model
    """
    explicit = _iter_model_classes_from_explicit_module_iterator(module, module_key=module_key)
    if explicit:
        return explicit

    result: list[type[Any]] = []

    try:
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if _is_sqlalchemy_model_class(obj):
                result.append(obj)
    except Exception:
        return tuple()

    return tuple(_dedupe_model_classes(result))


def _iter_model_classes_from_explicit_module_iterator(
    module: ModuleType,
    *,
    module_key: str | None = None,
) -> tuple[type[Any], ...]:
    """Lädt Modelklassen bevorzugt über explizite Iterator-Funktionen des Moduls."""
    candidate_names: list[str] = []

    if module_key and module_key in _MODULE_MODEL_ITERATOR_NAMES:
        candidate_names.extend(_MODULE_MODEL_ITERATOR_NAMES[module_key])

    candidate_names.extend(("iter_models", "get_models"))

    seen_names: set[str] = set()
    deduped_candidate_names: list[str] = []

    for name in candidate_names:
        if name in seen_names:
            continue
        seen_names.add(name)
        deduped_candidate_names.append(name)

    for function_name in deduped_candidate_names:
        try:
            candidate = getattr(module, function_name, None)
            if not callable(candidate):
                continue

            values = candidate()
            result = [
                value
                for value in values or ()
                if _is_sqlalchemy_model_class(value)
            ]

            if result:
                return tuple(_dedupe_model_classes(result))
        except Exception:
            continue

    return tuple()


def _is_sqlalchemy_model_class(obj: Any) -> bool:
    """Heuristische Prüfung auf SQLAlchemy-Modelklasse."""
    try:
        if not inspect.isclass(obj):
            return False

        table_name = getattr(obj, "__tablename__", None)
        if not table_name:
            return False

        if getattr(obj, "__table__", None) is not None:
            return True

        if getattr(obj, "__abstract__", False):
            return False

        if getattr(obj, "metadata", None) is not None:
            return True

        if hasattr(obj, "query"):
            return True

        return True
    except Exception:
        return False


def _get_model_table_name(model_class: type[Any]) -> str | None:
    """Liest den Tabellennamen einer Modelklasse robust aus."""
    try:
        table = getattr(model_class, "__table__", None)
        table_name = getattr(table, "name", None)
        if table_name:
            return str(table_name)
    except Exception:
        pass

    try:
        table_name = getattr(model_class, "__tablename__", None)
        if table_name:
            return str(table_name)
    except Exception:
        pass

    return None


def _dedupe_model_classes(values: Iterable[type[Any]]) -> tuple[type[Any], ...]:
    """Dedupliziert Modelklassen stabil nach Modul + Klassenname."""
    result: list[type[Any]] = []
    seen: set[tuple[str, str]] = set()

    for value in values or ():
        try:
            key = (str(value.__module__), str(value.__name__))
        except Exception:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(value)

    return tuple(result)


def _dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
    """Dedupliziert Strings stabil in Eingabereihenfolge."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        try:
            key = str(value)
        except Exception:
            continue

        if key in seen:
            continue

        seen.add(key)
        result.append(key)

    return tuple(result)


def _load_db_extension() -> Any:
    """Lädt die zentrale SQLAlchemy-Extension `db` defensiv."""
    errors: list[str] = []

    for module_name in (
        "extensions",
        "src.extensions",
        "vectoplan_library.extensions",
    ):
        try:
            module = importlib.import_module(module_name)
            db = getattr(module, "db", None)
            if db is not None:
                return db
            errors.append(f"{module_name}: db missing")
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ModelsImportError("Could not import SQLAlchemy extension db. " + " | ".join(errors))


__version__ = MODELS_PACKAGE_VERSION


__all__ = [
    "MODELS_PACKAGE_VERSION",
    "ModelModuleStatus",
    "ModelsImportError",
    "__version__",
    "assert_models_ready",
    "clear_model_caches",

    # Module aliases
    "assets",
    "collection",
    "collections",
    "creative",
    "creative_drafts",
    "creative_library",
    "creative_library_collections",
    "creative_library_draft",
    "creative_library_drafts",
    "creative_library_overrides",
    "creative_published",
    "creative_user",
    "definition",
    "definition_catalog",
    "definitions",
    "document_types",
    "draft",
    "drafts",
    "editor_inventory",
    "file",
    "files",
    "generator",
    "generator_drafts",
    "hotbar",
    "inventory",
    "library",
    "library_definition",
    "library_definition_models",
    "library_definitions",
    "library_file",
    "library_file_models",
    "library_files",
    "library_taxonomy",
    "library_taxonomy_models",
    "materials",
    "profiles",
    "published_library",
    "scan",
    "scans",
    "taxonomies",
    "taxonomy",
    "taxonomy_nodes",
    "units",
    "upload",
    "uploads",
    "user",
    "user_collections",
    "user_hotbar",
    "user_inventory",
    "user_inventory_models",
    "user_library",
    "users",
    "variables",
    "variant_profiles",
    "profile_bindings",

    # Registry helpers
    "get_model_class_names",
    "get_model_module_alias_map",
    "get_model_module_keys",
    "get_model_module_statuses",
    "get_model_symbol_module_map",
    "get_model_symbol_names",
    "get_model_table_names",
    "get_models_health",
    "get_models_metadata_snapshot",
    "import_all_models",
    "is_model_symbol",
    "iter_model_classes",
    "load_all_model_modules",
    "load_model_module",
    "model_status_to_json",
    "model_statuses_to_json",

    # Lazy symbols
    *_SYMBOL_TO_MODULE.keys(),
]