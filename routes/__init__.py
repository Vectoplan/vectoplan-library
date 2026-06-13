# services/vectoplan-library/src/routes/__init__.py
"""
Central Blueprint registration for the vectoplan-library microservice.

Diese Datei bildet die HTTP-Außenkante auf Strukturebene ab:

- sie kennt die vorhandenen Route-Module
- sie lädt deren Blueprints defensiv
- sie registriert sie genau einmal an der Flask-App
- sie speichert Routing-Metadaten in app.extensions["vectoplan_library"]

Aktuell registriert:

Required:

- routes.vplib_routes:vplib_bp
- routes.library_routes:library_bp
- routes.taxonomy:taxonomy_bp

Optional:

- routes.api:api_bp
- routes.library_definition_routes:library_definition_bp
- routes.create:create_bp

Die frühere Editor-Route war nur ein Muster und wird hier nicht mehr registriert.

Wichtig:

- keine Business-Logik
- keine HTML-Erzeugung
- keine VPLIB-Erstellungslogik
- keine Creative-Library-Scanlogik
- keine Taxonomie-Fachlogik
- keine Definitions-Fachlogik
- keine DB-Sync-Fachlogik
- nur Routing-Verdrahtung und defensive Registrierung

Warum diese Datei wichtig ist:

- app.py soll nur die App erzeugen und dann zentral register_blueprints(app) aufrufen
- neue Routen werden hier sichtbar und nachvollziehbar ergänzt
- die Struktur bleibt konsistent:
  Routes sind HTTP-Adapter.
  Services sind Fachlogik.
  Repositories sind DB-Zugriff.
  Creators/Validators/Sources sind VPLIB-Kernlogik.
  library/* ist die Creative-Library-Schicht.
  library/taxonomy/* ist die kanonische Backend-Taxonomie-Schicht.
  library/definitions/* ist die kanonische Backend-Definitionsschicht für
  Object Kinds, Family Profiles, Variant Profiles, Variablen, Einheiten,
  Materialien, Dokumenttypen und Profile Bindings.

Neue Library-API-Route:

- routes.api:api_bp ist der neue API-Adapter für:
  GET  /api/v1/vplib/library/health
  GET  /api/v1/vplib/library/db/health
  GET  /api/v1/vplib/library/scan
  POST /api/v1/vplib/library/sync
  GET  /api/v1/vplib/library/sync-runs
  GET  /api/v1/vplib/library/sync-runs/<run_id>
  GET  /api/v1/vplib/library/publication-status
  GET  /api/v1/vplib/library/blocks
  GET  /api/v1/vplib/library/blocks/<block_id>
  GET  /api/v1/vplib/library/blocks/<block_id>/variants
  GET  /api/v1/vplib/library/tree
  GET  /api/v1/vplib/library/inventory

- Dieser Blueprint wird bewusst vor routes.library_routes registriert.
  Wenn beide dieselben Pfade bereitstellen, soll der neue API-Adapter zuerst
  in der Flask-Routing-Map stehen.
- Er bleibt optional, damit der Containerstart während der Migration nicht
  scheitert, falls die neue API-Datei in einem Zwischenstand fehlt.

Taxonomie-Route:

- /api/v1/vplib/taxonomy ist die kanonische Backend-Taxonomie-API
- sie liefert Reiter, Kategorien und Subkategorien für Create-Wizard, Scanner,
  Creative Library und spätere Editor-/Inventar-Integration
- sie wird hier als required Blueprint geführt, weil der neue Create-Flow und
  die spätere Navigation nicht mehr auf Frontend-Fallbacks oder verstreute
  Options-Listen angewiesen sein sollen

Definitions-Route:

- /api/v1/vplib/definitions ist die isolierte Test- und Read-API für die
  backendgesteuerte Definitionsschicht
- sie liefert Health, Summary, Options, Payload, Variant Profile Resolution,
  Empty Variant Values und Variant Validation
- sie wird hier zunächst optional geführt, damit der Containerstart nicht an
  einer noch jungen Definitions-Test-Route scheitert

Create-Route:

- /create ist der VPLIB-Erstellpfad
- der Create-Blueprint wird hier als optionaler Blueprint geführt
- optional bedeutet hier: Containerstart soll nicht allein an der UI-Create-Route
  scheitern, solange Kern-, Library- und Taxonomie-Routen verfügbar bleiben

Robustheitsziele:

- defensive Modul- und Blueprint-Auflösung
- keine Doppelregistrierung derselben Blueprint-Namen
- klare Fehlermeldungen bei Strukturfehlern
- JSON-kompatible Debug-/Health-Metadaten
- Cache-Clear-Funktion für Tests und Reloads
- optionale Health-/Info-Abfrage der Route-Module, falls vorhanden
"""

from __future__ import annotations

import importlib
import traceback
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Iterable, Mapping

from flask import Blueprint, Flask


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROUTES_PACKAGE_SCHEMA_VERSION: Final[str] = "vplib.routes.registry.v5"
ROUTES_PACKAGE_VERSION: Final[str] = "0.6.0"
ROUTES_COMPONENT_NAME: Final[str] = "vectoplan-library-routes"

EXTENSION_REGISTRY_KEY: Final[str] = "vectoplan_library"

DEFAULT_VPLIB_ROUTE_MODULE: Final[str] = "routes.vplib_routes"
DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE: Final[str] = "vplib_bp"

DEFAULT_API_ROUTE_MODULE: Final[str] = "routes.api"
DEFAULT_API_BLUEPRINT_ATTRIBUTE: Final[str] = "api_bp"

DEFAULT_LIBRARY_ROUTE_MODULE: Final[str] = "routes.library_routes"
DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE: Final[str] = "library_bp"

DEFAULT_TAXONOMY_ROUTE_MODULE: Final[str] = "routes.taxonomy"
DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE: Final[str] = "taxonomy_bp"

DEFAULT_DEFINITION_ROUTE_MODULE: Final[str] = "routes.library_definition_routes"
DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE: Final[str] = "library_definition_bp"

DEFAULT_CREATE_ROUTE_MODULE: Final[str] = "routes.create"
DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE: Final[str] = "create_bp"

DEFAULT_REQUIRED_BLUEPRINTS: Final[tuple[str, ...]] = (
    f"{DEFAULT_VPLIB_ROUTE_MODULE}:{DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_LIBRARY_ROUTE_MODULE}:{DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_TAXONOMY_ROUTE_MODULE}:{DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE}",
)

DEFAULT_OPTIONAL_BLUEPRINTS: Final[tuple[str, ...]] = (
    f"{DEFAULT_API_ROUTE_MODULE}:{DEFAULT_API_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_DEFINITION_ROUTE_MODULE}:{DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE}",
    f"{DEFAULT_CREATE_ROUTE_MODULE}:{DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE}",
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RouteRegistryError(RuntimeError):
    """
    Wird ausgelöst, wenn Blueprint-Registrierung oder Route-Registry fehlschlägt.
    """


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class BlueprintSpec:
    """
    Beschreibt, wie ein Blueprint geladen und optional mit Präfix registriert wird.

    url_prefix bleibt normalerweise None, weil die Blueprints selbst ihre Prefixe
    aus den jeweiligen Settings oder direkt im Blueprint setzen.

    Beispiele:

        routes.vplib_routes:vplib_bp
        routes.api:api_bp
        routes.library_routes:library_bp
        routes.taxonomy:taxonomy_bp
        routes.library_definition_routes:library_definition_bp
        routes.create:create_bp
    """

    module_name: str
    attribute_name: str
    url_prefix: str | None = None
    required: bool = True
    description: str = ""

    def normalized(self) -> "BlueprintSpec":
        return BlueprintSpec(
            module_name=clean_required_string(self.module_name, "module_name"),
            attribute_name=clean_required_string(self.attribute_name, "attribute_name"),
            url_prefix=clean_optional_string(self.url_prefix),
            required=bool(self.required),
            description=clean_optional_string(self.description) or "",
        )

    @property
    def key(self) -> str:
        normalized = self.normalized()
        return f"{normalized.module_name}:{normalized.attribute_name}"

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "module_name": normalized.module_name,
            "attribute_name": normalized.attribute_name,
            "url_prefix": normalized.url_prefix,
            "required": normalized.required,
            "description": normalized.description,
            "key": normalized.key,
        }


@dataclass(frozen=True, slots=True)
class BlueprintResolutionResult:
    """
    Ergebnis der Blueprint-Auflösung vor der eigentlichen Registrierung.
    """

    spec: BlueprintSpec
    resolved: bool
    blueprint_name: str | None = None
    error: str | None = None
    health: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "BlueprintResolutionResult":
        return BlueprintResolutionResult(
            spec=self.spec.normalized(),
            resolved=bool(self.resolved),
            blueprint_name=clean_optional_string(self.blueprint_name),
            error=clean_optional_string(self.error),
            health=normalize_metadata(self.health),
        )

    @property
    def ok(self) -> bool:
        return self.normalized().resolved

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "spec": normalized.spec.to_dict(),
            "resolved": normalized.resolved,
            "ok": normalized.ok,
            "blueprint_name": normalized.blueprint_name,
            "error": normalized.error,
            "health": normalized.health,
        }


@dataclass(frozen=True, slots=True)
class BlueprintRegistrationResult:
    """
    Ergebnis einer einzelnen Blueprint-Registrierung.
    """

    blueprint_name: str
    module_name: str
    attribute_name: str
    registered: bool
    skipped: bool = False
    url_prefix: str | None = None
    error: str | None = None
    required: bool = True
    description: str = ""

    def normalized(self) -> "BlueprintRegistrationResult":
        return BlueprintRegistrationResult(
            blueprint_name=clean_required_string(self.blueprint_name, "blueprint_name"),
            module_name=clean_required_string(self.module_name, "module_name"),
            attribute_name=clean_required_string(self.attribute_name, "attribute_name"),
            registered=bool(self.registered),
            skipped=bool(self.skipped),
            url_prefix=clean_optional_string(self.url_prefix),
            error=clean_optional_string(self.error),
            required=bool(self.required),
            description=clean_optional_string(self.description) or "",
        )

    @property
    def ok(self) -> bool:
        normalized = self.normalized()

        if normalized.registered or normalized.skipped:
            return True

        return not normalized.required

    @property
    def key(self) -> str:
        normalized = self.normalized()
        return f"{normalized.module_name}:{normalized.attribute_name}"

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "blueprint_name": normalized.blueprint_name,
            "module_name": normalized.module_name,
            "attribute_name": normalized.attribute_name,
            "key": normalized.key,
            "registered": normalized.registered,
            "skipped": normalized.skipped,
            "ok": normalized.ok,
            "url_prefix": normalized.url_prefix,
            "error": normalized.error,
            "required": normalized.required,
            "description": normalized.description,
        }


@dataclass(frozen=True, slots=True)
class BlueprintRegistrySnapshot:
    """
    Debug-/Health-Snapshot der Blueprint-Registry.
    """

    initialized: bool
    registered_blueprint_names: tuple[str, ...]
    specs: tuple[BlueprintSpec, ...]
    results: tuple[BlueprintRegistrationResult, ...]
    app_blueprint_names: tuple[str, ...] = tuple()
    route_count: int = 0
    errors: tuple[str, ...] = tuple()
    warnings: tuple[str, ...] = tuple()

    def normalized(self) -> "BlueprintRegistrySnapshot":
        return BlueprintRegistrySnapshot(
            initialized=bool(self.initialized),
            registered_blueprint_names=tuple(
                sorted(str(name) for name in self.registered_blueprint_names or ())
            ),
            specs=tuple(spec.normalized() for spec in self.specs or ()),
            results=tuple(result.normalized() for result in self.results or ()),
            app_blueprint_names=tuple(
                sorted(str(name) for name in self.app_blueprint_names or ())
            ),
            route_count=int(self.route_count or 0),
            errors=tuple(str(error) for error in self.errors or () if str(error).strip()),
            warnings=tuple(str(warning) for warning in self.warnings or () if str(warning).strip()),
        )

    @property
    def ok(self) -> bool:
        normalized = self.normalized()
        return not normalized.errors and all(result.ok for result in normalized.results)

    @property
    def registered_count(self) -> int:
        return len(self.normalized().registered_blueprint_names)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": ROUTES_PACKAGE_SCHEMA_VERSION,
            "version": ROUTES_PACKAGE_VERSION,
            "component": ROUTES_COMPONENT_NAME,
            "initialized": normalized.initialized,
            "ok": normalized.ok,
            "registered_count": normalized.registered_count,
            "registered_blueprint_names": list(normalized.registered_blueprint_names),
            "app_blueprint_names": list(normalized.app_blueprint_names),
            "route_count": normalized.route_count,
            "specs": [spec.to_dict() for spec in normalized.specs],
            "results": [result.to_dict() for result in normalized.results],
            "warnings": list(normalized.warnings),
            "errors": list(normalized.errors),
        }


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    """
    Liefert eine UTC-Zeit im ISO-Format.
    """

    return datetime.now(timezone.utc).isoformat()


def exception_to_dict(
    exc: BaseException,
    *,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """
    Serialisiert Exceptions JSON-kompatibel.
    """

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


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Normalisiert Metadata JSON-kompatibel.
    """

    if value is None:
        return {}

    if not isinstance(value, Mapping):
        return {"value": str(value)}

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """
    Normalisiert Metadata-Werte JSON-kompatibel.
    """

    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value):
        try:
            return normalize_metadata(asdict(value))
        except Exception:
            return str(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return normalize_metadata_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def clean_required_string(value: Any, field_name: str) -> str:
    """
    Normalisiert Pflicht-String.
    """

    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise RouteRegistryError(f"{field_name} is required.")

        return cleaned

    except RouteRegistryError:
        raise

    except Exception as exc:
        raise RouteRegistryError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """
    Normalisiert optionalen String.
    """

    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def safe_tuple(value: Any) -> tuple[Any, ...]:
    """
    Normalisiert defensiv zu tuple.
    """

    if value is None:
        return tuple()

    if isinstance(value, tuple):
        return value

    if isinstance(value, str):
        return (value,)

    if isinstance(value, Iterable):
        try:
            return tuple(value)
        except Exception:
            return tuple()

    return (value,)


def dataclass_to_dict_safe(value: Any) -> dict[str, Any]:
    """
    Defensive Dataclass-Serialisierung.
    """

    try:
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)
    except Exception:
        pass

    if isinstance(value, Mapping):
        return dict(value)

    return {"value": str(value)}


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _safe_get_logger(app: Flask):
    """
    Liefert den Flask-Logger robust zurück.
    """

    try:
        return app.logger
    except Exception:
        return None


def _safe_log_debug(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)

    if logger is None:
        return

    try:
        logger.debug(message)
    except Exception:
        pass


def _safe_log_info(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)

    if logger is None:
        return

    try:
        logger.info(message)
    except Exception:
        pass


def _safe_log_warning(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)

    if logger is None:
        return

    try:
        logger.warning(message)
    except Exception:
        pass


def _safe_log_error(app: Flask, message: str) -> None:
    logger = _safe_get_logger(app)

    if logger is None:
        return

    try:
        logger.error(message)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Flask app / registry helpers
# ---------------------------------------------------------------------------

def _is_flask_app(app: object) -> bool:
    """
    Prüft defensiv, ob das übergebene Objekt wie eine Flask-App verwendbar ist.
    """

    if isinstance(app, Flask):
        return True

    required_attributes = ("register_blueprint", "blueprints", "extensions")

    for attribute_name in required_attributes:
        if not hasattr(app, attribute_name):
            return False

    return True


def _ensure_extension_registry(app: Flask) -> dict[str, Any]:
    """
    Stellt sicher, dass ein gemeinsamer Extension-Bereich für vectoplan-library existiert.
    """

    try:
        app.extensions.setdefault(EXTENSION_REGISTRY_KEY, {})
        registry = app.extensions[EXTENSION_REGISTRY_KEY]

        if not isinstance(registry, dict):
            raise TypeError(
                f"app.extensions[{EXTENSION_REGISTRY_KEY!r}] is not a dictionary."
            )

        return registry

    except Exception as exc:
        raise RouteRegistryError(
            f"The Flask extension registry area {EXTENSION_REGISTRY_KEY!r} could not be initialized."
        ) from exc


def _ensure_blueprint_tracking(app: Flask) -> set[str]:
    """
    Erstellt robust ein Tracking-Set für bereits registrierte Blueprints.
    """

    registry = _ensure_extension_registry(app)

    try:
        existing = registry.get("registered_blueprint_names")

        if isinstance(existing, set):
            return existing

        if isinstance(existing, (list, tuple)):
            restored = {str(item) for item in existing}
            registry["registered_blueprint_names"] = restored
            return restored

        tracking: set[str] = set()
        registry["registered_blueprint_names"] = tracking
        return tracking

    except Exception as exc:
        raise RouteRegistryError("Blueprint tracking could not be initialized.") from exc


def _ensure_registration_results(app: Flask) -> list[dict[str, Any]]:
    """
    Erstellt robust eine Ergebnisliste im Registry-Bereich.
    """

    registry = _ensure_extension_registry(app)
    existing = registry.get("blueprint_registration_results")

    if isinstance(existing, list):
        return existing

    results: list[dict[str, Any]] = []
    registry["blueprint_registration_results"] = results
    return results


def _get_app_blueprint_names(app: Flask) -> tuple[str, ...]:
    """
    Liefert Namen aller bereits an der Flask-App registrierten Blueprints.
    """

    try:
        return tuple(sorted(str(name) for name in app.blueprints.keys()))
    except Exception:
        return tuple()


def _get_app_route_count(app: Flask) -> int:
    """
    Liefert Anzahl registrierter URL-Rules.
    """

    try:
        return len(list(app.url_map.iter_rules()))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Blueprint specs
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_blueprint_specs() -> tuple[BlueprintSpec, ...]:
    """
    Liefert die aktuell vorgesehenen Blueprint-Spezifikationen.

    Die Editor-Route wird nicht mehr registriert.

    Reihenfolge ist bewusst:

    1. VPLIB-Kernrouten
    2. neue optionale Library-API für DB-Sync und Published-Read-Pfad
    3. bestehende Creative-Library-Routen
    4. Taxonomie-Routen
    5. Definitions-Test-/Read-Routen
    6. einfacher Create-Screen und Create-API

    routes.api wird vor routes.library_routes registriert, damit seine
    DB-/Sync-Routen bei gleichen URL-Patterns Vorrang haben können. Er bleibt
    optional, damit alte Systeme ohne diese neue Datei weiter starten.

    Taxonomie ist required, weil Backend-Taxonomie ab jetzt die kanonische Quelle
    für Reiter, Kategorien und Subkategorien ist.

    Definitions bleibt vorerst optional, weil die Definitionsroute aktuell als
    isolierte Testkante eingeführt wird. Sie soll registriert werden, wenn sie
    importierbar ist, aber den Containerstart noch nicht blockieren.

    Der Create-Blueprint bleibt optional, weil app.py ihn je nach Projektstand
    zusätzlich defensiv registrieren kann. Dadurch bleibt der Containerstart
    robuster, falls /create in einem Zwischenstand fehlt oder fehlerhaft ist.
    """

    return (
        BlueprintSpec(
            module_name=DEFAULT_VPLIB_ROUTE_MODULE,
            attribute_name=DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE,
            url_prefix=None,
            required=True,
            description="VPLIB creation, dry-run, health and self-test routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_API_ROUTE_MODULE,
            attribute_name=DEFAULT_API_BLUEPRINT_ATTRIBUTE,
            url_prefix=None,
            required=False,
            description="New Creative Library API routes for DB sync, DB health, published reads, inventory and filesystem debug access.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_LIBRARY_ROUTE_MODULE,
            attribute_name=DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE,
            url_prefix=None,
            required=True,
            description="Legacy/primary Creative Library scan, blocks, block detail, variants and tree routes.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_TAXONOMY_ROUTE_MODULE,
            attribute_name=DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE,
            url_prefix=None,
            required=True,
            description="Canonical taxonomy routes for domains, categories, subcategories, Create options and source-path validation.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_DEFINITION_ROUTE_MODULE,
            attribute_name=DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE,
            url_prefix=None,
            required=False,
            description="Definitions routes for object kinds, family profiles, variant profiles, variables, units, materials, document types and profile bindings.",
        ).normalized(),
        BlueprintSpec(
            module_name=DEFAULT_CREATE_ROUTE_MODULE,
            attribute_name=DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE,
            url_prefix=None,
            required=False,
            description="Simple /create frontend and /api/v1/vplib/create/* routes for creating VPLIB source packages.",
        ).normalized(),
    )


def iter_blueprint_specs() -> tuple[BlueprintSpec, ...]:
    """
    Öffentliche read-only Zugriffsfunktion auf die Blueprint-Spezifikation.
    """

    return get_blueprint_specs()


def get_required_blueprint_keys() -> tuple[str, ...]:
    """
    Liefert alle als required markierten Blueprint-Keys.
    """

    return tuple(
        spec.key
        for spec in get_blueprint_specs()
        if spec.required
    )


def get_optional_blueprint_keys() -> tuple[str, ...]:
    """
    Liefert alle als optional markierten Blueprint-Keys.
    """

    return tuple(
        spec.key
        for spec in get_blueprint_specs()
        if not spec.required
    )


# ---------------------------------------------------------------------------
# Module / blueprint resolution
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _import_module(module_name: str) -> ModuleType:
    """
    Importiert ein Modul gecacht und defensiv.
    """

    normalized_module_name = clean_required_string(module_name, "module_name")

    try:
        return importlib.import_module(normalized_module_name)
    except Exception as exc:
        raise RouteRegistryError(
            f"Route module {normalized_module_name!r} could not be imported."
        ) from exc


def _get_module_health(module: ModuleType) -> dict[str, Any]:
    """
    Ruft eine optionale Health-/Info-Funktion eines Route-Moduls auf.

    Unterstützte Namen:

    - get_api_routes_health
    - get_library_routes_health
    - get_vplib_routes_health
    - get_create_routes_health
    - get_taxonomy_routes_health
    - get_taxonomy_routes_info
    - get_library_definition_routes_health
    - get_routes_health
    - get_route_health
    - get_routes_info
    - get_route_info
    """

    health_function_names = (
        "get_api_routes_health",
        "get_library_routes_health",
        "get_vplib_routes_health",
        "get_create_routes_health",
        "get_taxonomy_routes_health",
        "get_taxonomy_routes_info",
        "get_library_definition_routes_health",
        "get_routes_health",
        "get_route_health",
        "get_routes_info",
        "get_route_info",
    )

    for function_name in health_function_names:
        try:
            function = getattr(module, function_name, None)

            if callable(function):
                health = function()
                normalized = normalize_metadata_value(health)

                if isinstance(normalized, Mapping):
                    return dict(normalized)

                return {"value": str(normalized)}

        except Exception as exc:
            return {
                "ok": False,
                "healthy": False,
                "status": "health_error",
                "function": function_name,
                "error": exception_to_dict(exc),
            }

    return {
        "ok": True,
        "healthy": True,
        "status": "no_route_health_function",
    }


def _resolve_blueprint(spec: BlueprintSpec) -> Blueprint:
    """
    Löst anhand einer BlueprintSpec das tatsächliche Blueprint-Objekt auf.
    """

    normalized_spec = spec.normalized()
    module = _import_module(normalized_spec.module_name)

    try:
        candidate = getattr(module, normalized_spec.attribute_name)
    except AttributeError as exc:
        raise RouteRegistryError(
            f"Route module {normalized_spec.module_name!r} does not export "
            f"{normalized_spec.attribute_name!r}."
        ) from exc

    if candidate is None:
        raise RouteRegistryError(
            f"Attribute {normalized_spec.attribute_name!r} from "
            f"{normalized_spec.module_name!r} is None."
        )

    if not isinstance(candidate, Blueprint):
        raise RouteRegistryError(
            f"Attribute {normalized_spec.attribute_name!r} from "
            f"{normalized_spec.module_name!r} is not a Flask Blueprint."
        )

    return candidate


def resolve_blueprint_spec(spec: BlueprintSpec) -> BlueprintResolutionResult:
    """
    Öffentliche, JSON-kompatible Blueprint-Auflösung ohne Registrierung.
    """

    normalized_spec = spec.normalized()

    try:
        module = _import_module(normalized_spec.module_name)
        blueprint = _resolve_blueprint(normalized_spec)
        blueprint_name = getattr(blueprint, "name", None)
        module_health = _get_module_health(module)

        return BlueprintResolutionResult(
            spec=normalized_spec,
            resolved=True,
            blueprint_name=blueprint_name,
            error=None,
            health=module_health,
        ).normalized()

    except Exception as exc:
        return BlueprintResolutionResult(
            spec=normalized_spec,
            resolved=False,
            blueprint_name=None,
            error=str(exc),
            health={
                "ok": False,
                "healthy": False,
                "error": exception_to_dict(exc),
            },
        ).normalized()


def resolve_all_blueprint_specs() -> tuple[BlueprintResolutionResult, ...]:
    """
    Löst alle Blueprint-Spezifikationen ohne Registrierung auf.
    """

    results: list[BlueprintResolutionResult] = []

    for spec in get_blueprint_specs():
        results.append(resolve_blueprint_spec(spec))

    return tuple(results)


# ---------------------------------------------------------------------------
# Blueprint registration
# ---------------------------------------------------------------------------

def _register_single_blueprint(
    app: Flask,
    spec: BlueprintSpec,
) -> BlueprintRegistrationResult:
    """
    Registriert genau einen Blueprint defensiv an der App.

    Doppelregistrierung wird verhindert durch:

    - Tracking in app.extensions["vectoplan_library"]
    - Prüfung der bereits vorhandenen app.blueprints
    """

    normalized_spec = spec.normalized()
    blueprint = _resolve_blueprint(normalized_spec)
    blueprint_name = getattr(blueprint, "name", None)

    if not blueprint_name or not isinstance(blueprint_name, str):
        raise RouteRegistryError("A Blueprint without a valid name cannot be registered.")

    tracked_names = _ensure_blueprint_tracking(app)

    if blueprint_name in tracked_names:
        _safe_log_debug(
            app,
            f"Blueprint {blueprint_name!r} is already tracked and will be skipped.",
        )

        return BlueprintRegistrationResult(
            blueprint_name=blueprint_name,
            module_name=normalized_spec.module_name,
            attribute_name=normalized_spec.attribute_name,
            registered=False,
            skipped=True,
            url_prefix=normalized_spec.url_prefix,
            required=normalized_spec.required,
            description=normalized_spec.description,
        ).normalized()

    try:
        if blueprint_name in app.blueprints:
            tracked_names.add(blueprint_name)
            _safe_log_debug(
                app,
                f"Blueprint {blueprint_name!r} already exists on app and was added to tracking.",
            )

            return BlueprintRegistrationResult(
                blueprint_name=blueprint_name,
                module_name=normalized_spec.module_name,
                attribute_name=normalized_spec.attribute_name,
                registered=False,
                skipped=True,
                url_prefix=normalized_spec.url_prefix,
                required=normalized_spec.required,
                description=normalized_spec.description,
            ).normalized()

    except Exception:
        pass

    try:
        if normalized_spec.url_prefix:
            app.register_blueprint(blueprint, url_prefix=normalized_spec.url_prefix)
        else:
            app.register_blueprint(blueprint)

    except Exception as exc:
        raise RouteRegistryError(
            f"Blueprint {blueprint_name!r} could not be registered."
        ) from exc

    tracked_names.add(blueprint_name)
    _safe_log_info(app, f"Blueprint {blueprint_name!r} was registered successfully.")

    return BlueprintRegistrationResult(
        blueprint_name=blueprint_name,
        module_name=normalized_spec.module_name,
        attribute_name=normalized_spec.attribute_name,
        registered=True,
        skipped=False,
        url_prefix=normalized_spec.url_prefix,
        required=normalized_spec.required,
        description=normalized_spec.description,
    ).normalized()


def _store_registration_metadata(
    app: Flask,
    *,
    results: Iterable[BlueprintRegistrationResult],
) -> None:
    """
    Speichert Routing-Metadaten im Extension-Bereich.
    """

    registry = _ensure_extension_registry(app)

    try:
        normalized_results = tuple(result.normalized() for result in results or ())
        specs = get_blueprint_specs()
        resolution_results = resolve_all_blueprint_specs()

        registry["route_module"] = "routes"
        registry["routes_component"] = ROUTES_COMPONENT_NAME
        registry["routes_version"] = ROUTES_PACKAGE_VERSION
        registry["schema_version"] = ROUTES_PACKAGE_SCHEMA_VERSION
        registry["blueprint_specs"] = [spec.to_dict() for spec in specs]
        registry["blueprint_resolution_results"] = [
            result.to_dict()
            for result in resolution_results
        ]
        registry["blueprint_registration_results"] = [
            result.to_dict()
            for result in normalized_results
        ]
        registry["registered_blueprint_names_list"] = get_registered_blueprint_names(app)
        registry["app_blueprint_names"] = list(_get_app_blueprint_names(app))
        registry["route_count"] = _get_app_route_count(app)
        registry["routing_initialized"] = True
        registry["routing_initialized_at"] = utc_now_iso()

    except Exception as exc:
        raise RouteRegistryError("Routing metadata could not be stored.") from exc


def register_blueprints(app: Flask) -> Flask:
    """
    Registriert alle vorgesehenen Blueprints an der Flask-App.

    Ablauf:

    1. App-Objekt validieren
    2. Blueprint-Spezifikationen laden
    3. Blueprints einzeln importieren und registrieren
    4. Routing-Metadaten speichern

    Rückgabe:

    - dieselbe Flask-App, damit die Funktion fluenter nutzbar bleibt
    """

    if not _is_flask_app(app):
        raise TypeError(
            "register_blueprints(app) expects a Flask app or a compatible object."
        )

    specs = get_blueprint_specs()

    if not specs:
        _safe_log_warning(app, "No Blueprint specs found; no routes were registered.")
        _store_registration_metadata(app, results=tuple())
        return app

    results: list[BlueprintRegistrationResult] = []

    for spec in specs:
        normalized_spec = spec.normalized()

        try:
            result = _register_single_blueprint(app, normalized_spec)
            results.append(result)
            _ensure_registration_results(app).append(result.to_dict())

        except Exception as exc:
            if normalized_spec.required:
                _safe_log_error(
                    app,
                    f"Required Blueprint {normalized_spec.key!r} could not be registered: {exc}",
                )
                raise

            _safe_log_warning(
                app,
                f"Optional Blueprint {normalized_spec.key!r} could not be registered: {exc}",
            )

            result = BlueprintRegistrationResult(
                blueprint_name=normalized_spec.attribute_name,
                module_name=normalized_spec.module_name,
                attribute_name=normalized_spec.attribute_name,
                registered=False,
                skipped=False,
                url_prefix=normalized_spec.url_prefix,
                error=str(exc),
                required=normalized_spec.required,
                description=normalized_spec.description,
            ).normalized()

            results.append(result)
            _ensure_registration_results(app).append(result.to_dict())

    _store_registration_metadata(app, results=tuple(results))
    return app


# ---------------------------------------------------------------------------
# Snapshot / public registry access
# ---------------------------------------------------------------------------

def get_registered_blueprint_names(app: Flask) -> list[str]:
    """
    Liefert die durch dieses Modul getrackten Blueprint-Namen sortiert zurück.
    """

    tracked_names = _ensure_blueprint_tracking(app)

    try:
        return sorted(tracked_names)
    except Exception:
        return list(tracked_names)


def get_blueprint_registry_snapshot(app: Flask) -> dict[str, Any]:
    """
    Gibt einen JSON-kompatiblen Snapshot der Blueprint-Registry zurück.
    """

    try:
        registry = _ensure_extension_registry(app)
        tracked_names = _ensure_blueprint_tracking(app)

        raw_results = registry.get("blueprint_registration_results", [])
        results: list[BlueprintRegistrationResult] = []

        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, Mapping):
                    continue

                results.append(
                    BlueprintRegistrationResult(
                        blueprint_name=item.get("blueprint_name", "unknown"),
                        module_name=item.get("module_name", "unknown"),
                        attribute_name=item.get("attribute_name", "unknown"),
                        registered=bool(item.get("registered", False)),
                        skipped=bool(item.get("skipped", False)),
                        url_prefix=item.get("url_prefix"),
                        error=item.get("error"),
                        required=bool(item.get("required", True)),
                        description=item.get("description") or "",
                    ).normalized()
                )

        snapshot = BlueprintRegistrySnapshot(
            initialized=bool(registry.get("routing_initialized", False)),
            registered_blueprint_names=tuple(tracked_names),
            specs=get_blueprint_specs(),
            results=tuple(results),
            app_blueprint_names=_get_app_blueprint_names(app),
            route_count=_get_app_route_count(app),
            errors=tuple(),
            warnings=tuple(),
        )

        return snapshot.to_dict()

    except Exception as exc:
        return BlueprintRegistrySnapshot(
            initialized=False,
            registered_blueprint_names=tuple(),
            specs=get_blueprint_specs(),
            results=tuple(),
            app_blueprint_names=tuple(),
            route_count=0,
            errors=(str(exc),),
            warnings=tuple(),
        ).to_dict()


def get_routes_health(app: Flask | None = None) -> dict[str, Any]:
    """
    Liefert einen Health-Status der Route-Registry.

    Wenn `app` übergeben wird, enthält die Antwort zusätzlich App-/Registry-
    Informationen. Ohne `app` werden nur Spec-/Importdaten geprüft.
    """

    errors: list[str] = []
    warnings: list[str] = []

    resolution_results = resolve_all_blueprint_specs()

    for result in resolution_results:
        if not result.ok:
            if result.spec.required:
                errors.append(
                    f"required blueprint could not be resolved: {result.spec.key}"
                )
            else:
                warnings.append(
                    f"optional blueprint could not be resolved: {result.spec.key}"
                )

    app_snapshot: dict[str, Any] | None = None

    if app is not None:
        try:
            app_snapshot = get_blueprint_registry_snapshot(app)

            if not app_snapshot.get("ok", False):
                warnings.append("app blueprint registry snapshot is not ok")
        except Exception as exc:
            errors.append(f"could not build app route snapshot: {exc}")

    healthy = len(errors) == 0

    return {
        "ok": healthy,
        "healthy": healthy,
        "component": ROUTES_COMPONENT_NAME,
        "version": ROUTES_PACKAGE_VERSION,
        "schema_version": ROUTES_PACKAGE_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "spec_count": len(get_blueprint_specs()),
        "required_blueprint_keys": list(get_required_blueprint_keys()),
        "optional_blueprint_keys": list(get_optional_blueprint_keys()),
        "resolution_results": [result.to_dict() for result in resolution_results],
        "app_snapshot": app_snapshot,
        "warnings": warnings,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Cache / reset helpers
# ---------------------------------------------------------------------------

def clear_route_registry_caches() -> None:
    """
    Leert interne Route-Registry-Caches.
    """

    get_blueprint_specs.cache_clear()
    _import_module.cache_clear()


def reset_route_registry_state(app: Flask) -> None:
    """
    Entfernt nur dieses Modul betreffende Registry-Metadaten aus app.extensions.

    Diese Funktion deregistriert keine Flask-Blueprints. Flask selbst erlaubt
    nachträgliches Entfernen registrierter Blueprints nicht sauber. Sie dient
    nur Test-/Debug-Zwecken für Metadaten.
    """

    registry = _ensure_extension_registry(app)

    for key in (
        "registered_blueprint_names",
        "registered_blueprint_names_list",
        "blueprint_registration_results",
        "blueprint_resolution_results",
        "blueprint_specs",
        "app_blueprint_names",
        "route_count",
        "routing_initialized",
        "routing_initialized_at",
    ):
        registry.pop(key, None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__: Final[list[str]] = [
    "DEFAULT_API_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_API_ROUTE_MODULE",
    "DEFAULT_CREATE_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_CREATE_ROUTE_MODULE",
    "DEFAULT_DEFINITION_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_DEFINITION_ROUTE_MODULE",
    "DEFAULT_LIBRARY_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_LIBRARY_ROUTE_MODULE",
    "DEFAULT_OPTIONAL_BLUEPRINTS",
    "DEFAULT_REQUIRED_BLUEPRINTS",
    "DEFAULT_TAXONOMY_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_TAXONOMY_ROUTE_MODULE",
    "DEFAULT_VPLIB_BLUEPRINT_ATTRIBUTE",
    "DEFAULT_VPLIB_ROUTE_MODULE",
    "EXTENSION_REGISTRY_KEY",
    "ROUTES_COMPONENT_NAME",
    "ROUTES_PACKAGE_SCHEMA_VERSION",
    "ROUTES_PACKAGE_VERSION",
    "BlueprintRegistrationResult",
    "BlueprintRegistrySnapshot",
    "BlueprintResolutionResult",
    "BlueprintSpec",
    "RouteRegistryError",
    "clean_optional_string",
    "clean_required_string",
    "clear_route_registry_caches",
    "dataclass_to_dict_safe",
    "exception_to_dict",
    "get_blueprint_registry_snapshot",
    "get_blueprint_specs",
    "get_optional_blueprint_keys",
    "get_registered_blueprint_names",
    "get_required_blueprint_keys",
    "get_routes_health",
    "iter_blueprint_specs",
    "normalize_metadata",
    "normalize_metadata_value",
    "register_blueprints",
    "reset_route_registry_state",
    "resolve_all_blueprint_specs",
    "resolve_blueprint_spec",
    "safe_tuple",
    "utc_now_iso",
]