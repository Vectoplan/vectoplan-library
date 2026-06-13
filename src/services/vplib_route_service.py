# services/vectoplan-library/src/services/vplib_route_service.py
"""
VPLIB route service for the vectoplan-library microservice.

Diese Datei enthält die fachliche Service-Logik für die VPLIB-Flask-Routen.

Sie hat bewusst keine harte Flask-Abhängigkeit. Die Route-Datei ruft nur diese
Funktionen auf und gibt deren JSON-kompatible Antwort zurück.

Aufgaben:
- Self-Test für /api/v1/vplib/test
- Payload-Normalisierung für /api/v1/vplib/create
- Dry-Run-Erstellung testen
- VPLIB-Health, Settings, Defaults, Validators, Creators und Sources prüfen
- minimale Test-Dokumente erzeugen
- Validierung und Dry-Run-Schreiben ausführen
- Exceptions robust in JSON-kompatible Fehlerstrukturen wandeln

Wichtig:
- VPLIB-Settings werden bevorzugt direkt aus src/config/vplib_settings.py geladen.
- Dadurch blockiert ein root config.py nicht mehr den Import config.vplib_settings.
- Keine Editor-Begriffe.
- Keine Flask-Abhängigkeit.
- Der Self-Test erzeugt schema-kompatible Minimaldokumente.
- Der Dry-Run-Schreibtest nutzt den normalen Creator-Pfad inklusive
  Package-Root-Erstellung, weil file_writer.py den "."-Directory-Fall korrekt
  unterstützt.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
import importlib.util as importlib_util
import sys
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final, Mapping


VPLIB_ROUTE_SERVICE_SCHEMA_VERSION: Final[str] = "vplib.route_service.v1"

DEFAULT_SELF_TEST_FAMILY_ID: Final[str] = "self_test_block"
DEFAULT_SELF_TEST_PACKAGE_ID: Final[str] = "vplib.self_test_block"
DEFAULT_SELF_TEST_VARIANT_ID: Final[str] = "default"
DEFAULT_SELF_TEST_OBJECT_KIND: Final[str] = "cell_block"
DEFAULT_SELF_TEST_ROUTE_NAME: Final[str] = "vplib_self_test"

SETTINGS_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "src.config.vplib_settings",
    "config.vplib_settings",
)

VPLIB_MODULE_CANDIDATES: Final[tuple[str, ...]] = (
    "vplib",
    "src.vplib",
)

SERVICE_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SRC_ROOT: Final[Path] = SERVICE_ROOT / "src"
VPLIB_SETTINGS_FILE: Final[Path] = SRC_ROOT / "config" / "vplib_settings.py"


class VplibRouteServiceError(RuntimeError):
    """Wird ausgelöst, wenn die VPLIB-Route-Service-Logik fehlschlägt."""


class VplibRouteAction(str, Enum):
    """Route-Service-Aktion."""

    SELF_TEST = "self_test"
    CREATE = "create"
    CREATE_DRY_RUN = "create_dry_run"
    HEALTH = "health"

    @property
    def key(self) -> str:
        return str(self.value)


class VplibCheckStatus(str, Enum):
    """Status eines einzelnen Checks."""

    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class VplibRouteError:
    """JSON-kompatibler Fehler für Routen-Antworten."""

    code: str
    message: str
    source: str = "vplib_route_service"
    details: Mapping[str, Any] = field(default_factory=dict)
    traceback_text: str | None = None

    def normalized(self) -> "VplibRouteError":
        return VplibRouteError(
            code=clean_required_string(self.code, "code"),
            message=clean_required_string(self.message, "message"),
            source=clean_required_string(self.source or "vplib_route_service", "source"),
            details=normalize_json_mapping(self.details),
            traceback_text=clean_optional_string(self.traceback_text),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        payload = {
            "code": normalized.code,
            "message": normalized.message,
            "source": normalized.source,
            "details": dict(normalized.details),
        }

        if normalized.traceback_text:
            payload["traceback"] = normalized.traceback_text

        return payload


@dataclass(frozen=True, slots=True)
class VplibRouteCheck:
    """Ein einzelner Check innerhalb der Test-Route."""

    name: str
    status: str
    ok: bool
    payload: Mapping[str, Any] = field(default_factory=dict)
    errors: tuple[VplibRouteError, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "VplibRouteCheck":
        errors = tuple(error.normalized() for error in self.errors or ())
        warnings = normalize_string_tuple(self.warnings)

        status = parse_check_status_value(self.status)
        ok = bool(self.ok)

        if errors:
            status = VplibCheckStatus.FAILED.value
            ok = False
        elif warnings and ok:
            status = VplibCheckStatus.WARNING.value

        return VplibRouteCheck(
            name=clean_required_string(self.name, "name"),
            status=status,
            ok=ok,
            payload=normalize_json_mapping(self.payload),
            errors=errors,
            warnings=warnings,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "name": normalized.name,
            "status": normalized.status,
            "ok": normalized.ok,
            "payload": dict(normalized.payload),
            "errors": [error.to_dict() for error in normalized.errors],
            "warnings": list(normalized.warnings),
        }


@dataclass(frozen=True, slots=True)
class VplibRouteResult:
    """JSON-kompatibles Ergebnis einer Route-Service-Aktion."""

    action: str
    ok: bool
    status: str
    checks: Mapping[str, Any] = field(default_factory=dict)
    result: Any = None
    errors: tuple[VplibRouteError, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = VPLIB_ROUTE_SERVICE_SCHEMA_VERSION

    def normalized(self) -> "VplibRouteResult":
        action = parse_route_action_value(self.action)
        errors = tuple(error.normalized() for error in self.errors or ())
        warnings = normalize_string_tuple(self.warnings)
        status = clean_required_string(self.status, "status")
        ok = bool(self.ok)

        if errors:
            ok = False
            status = "failed"

        return VplibRouteResult(
            action=action,
            ok=ok,
            status=status,
            checks=normalize_json_mapping(self.checks),
            result=normalize_json_value(self.result),
            errors=errors,
            warnings=warnings,
            metadata=normalize_json_mapping(self.metadata),
            schema_version=self.schema_version or VPLIB_ROUTE_SERVICE_SCHEMA_VERSION,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "action": normalized.action,
            "ok": normalized.ok,
            "status": normalized.status,
            "checks": dict(normalized.checks),
            "result": normalized.result,
            "errors": [error.to_dict() for error in normalized.errors],
            "warnings": list(normalized.warnings),
            "metadata": dict(normalized.metadata),
        }


def run_vplib_self_test(
    *,
    settings: Any | None = None,
    include_traceback: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Führt den JSON-diagnosefähigen VPLIB-Self-Test aus.

    Diese Funktion ist für GET /api/v1/vplib/test gedacht.
    """
    checks: dict[str, Any] = {}
    errors: list[VplibRouteError] = []
    warnings: list[str] = []

    resolved_settings = None

    try:
        resolved_settings = normalize_settings(settings)
        checks["settings"] = run_settings_check(resolved_settings, dry_run=dry_run).to_dict()
    except Exception as exc:
        error = error_from_exception(
            exc,
            code="VPLIB_ROUTE_SETTINGS_FAILED",
            source="settings",
            include_traceback=include_traceback,
        )
        errors.append(error)
        checks["settings"] = failed_check("settings", error).to_dict()

    try:
        checks["imports"] = run_import_check().to_dict()
    except Exception as exc:
        error = error_from_exception(
            exc,
            code="VPLIB_ROUTE_IMPORT_CHECK_FAILED",
            source="imports",
            include_traceback=include_traceback,
        )
        errors.append(error)
        checks["imports"] = failed_check("imports", error).to_dict()

    try:
        checks["vplib_health"] = run_vplib_health_check().to_dict()
    except Exception as exc:
        error = error_from_exception(
            exc,
            code="VPLIB_ROUTE_HEALTH_FAILED",
            source="vplib_health",
            include_traceback=include_traceback,
        )
        errors.append(error)
        checks["vplib_health"] = failed_check("vplib_health", error).to_dict()

    test_documents: dict[str, dict[str, Any]] = {}

    try:
        test_documents = build_minimal_test_documents(settings=resolved_settings)
        checks["minimal_documents"] = VplibRouteCheck(
            name="minimal_documents",
            status=VplibCheckStatus.OK.value,
            ok=True,
            payload={
                "document_count": len(test_documents),
                "document_paths": sorted(test_documents.keys()),
            },
        ).to_dict()
    except Exception as exc:
        error = error_from_exception(
            exc,
            code="VPLIB_ROUTE_TEST_DOCUMENTS_FAILED",
            source="minimal_documents",
            include_traceback=include_traceback,
        )
        errors.append(error)
        checks["minimal_documents"] = failed_check("minimal_documents", error).to_dict()

    validation_result = None
    if test_documents:
        try:
            validation_result = validate_test_documents(
                test_documents,
                settings=resolved_settings,
            )
            validation_ok = is_result_ok(validation_result)

            if not validation_ok:
                warnings.append("Minimal test documents were generated but validation reported problems.")

            checks["validation"] = VplibRouteCheck(
                name="validation",
                status=VplibCheckStatus.OK.value if validation_ok else VplibCheckStatus.WARNING.value,
                ok=True,
                payload={
                    "valid": validation_ok,
                    "validation_result": object_to_dict(validation_result),
                },
                warnings=tuple() if validation_ok else ("Validation result is not valid.",),
            ).to_dict()
        except Exception as exc:
            error = error_from_exception(
                exc,
                code="VPLIB_ROUTE_VALIDATION_FAILED",
                source="validation",
                include_traceback=include_traceback,
            )
            errors.append(error)
            checks["validation"] = failed_check("validation", error).to_dict()

    if test_documents and resolved_settings is not None:
        try:
            dry_run_write_result = dry_run_write_test_documents(
                test_documents,
                settings=resolved_settings,
            )
            dry_run_ok = is_result_ok(dry_run_write_result)

            checks["dry_run_write"] = VplibRouteCheck(
                name="dry_run_write",
                status=VplibCheckStatus.OK.value if dry_run_ok else VplibCheckStatus.WARNING.value,
                ok=True,
                payload={
                    "valid": dry_run_ok,
                    "write_result": object_to_dict(dry_run_write_result),
                },
                warnings=tuple() if dry_run_ok else ("Dry-run write result is not ok.",),
            ).to_dict()
        except Exception as exc:
            error = error_from_exception(
                exc,
                code="VPLIB_ROUTE_DRY_RUN_WRITE_FAILED",
                source="dry_run_write",
                include_traceback=include_traceback,
            )
            errors.append(error)
            checks["dry_run_write"] = failed_check("dry_run_write", error).to_dict()

    ok = not errors and all(
        bool(check.get("ok", False))
        for check in checks.values()
        if isinstance(check, Mapping)
    )

    return VplibRouteResult(
        action=VplibRouteAction.SELF_TEST.value,
        ok=ok,
        status="ok" if ok else "failed",
        checks=checks,
        result={
            "message": "VPLIB self-test completed.",
            "test_documents_available": bool(test_documents),
            "validation_valid": is_result_ok(validation_result) if validation_result is not None else None,
        },
        errors=tuple(errors),
        warnings=tuple(warnings),
        metadata={
            "route": "/api/v1/vplib/test",
            "dry_run": dry_run,
            "settings_available": resolved_settings is not None,
            "settings_file": str(VPLIB_SETTINGS_FILE),
        },
    ).to_dict()


def create_vplib_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    settings: Any | None = None,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """
    Erstellt ein VPLIB-Package aus einem Route-Payload.

    Diese Funktion ist für POST /api/v1/vplib/create gedacht.
    """
    try:
        resolved_settings = normalize_settings(settings)
        normalized_payload = normalize_create_payload(payload)
        route_options = extract_create_options(normalized_payload, settings=resolved_settings)

        request_payload = normalized_payload.get("request")
        if not isinstance(request_payload, Mapping):
            raise VplibRouteServiceError("Payload must contain object field 'request'.")

        result = execute_create_request(
            request_payload,
            settings=resolved_settings,
            options=route_options,
        )

        ok = is_result_ok(result)

        return VplibRouteResult(
            action=VplibRouteAction.CREATE.value,
            ok=ok,
            status="ok" if ok else "failed",
            result=object_to_dict(result),
            errors=tuple(),
            warnings=tuple() if ok else ("VPLIB creation result is not ok.",),
            metadata={
                "dry_run": bool(route_options.get("dry_run", False)),
                "write_mode": route_options.get("write_mode"),
                "create_archive": route_options.get("create_archive"),
            },
        ).to_dict()
    except Exception as exc:
        error = error_from_exception(
            exc,
            code="VPLIB_ROUTE_CREATE_FAILED",
            source="create",
            include_traceback=include_traceback,
        )

        return VplibRouteResult(
            action=VplibRouteAction.CREATE.value,
            ok=False,
            status="failed",
            errors=(error,),
            metadata={
                "payload_present": payload is not None,
            },
        ).to_dict()


def create_vplib_dry_run_from_payload(
    payload: Mapping[str, Any] | None,
    *,
    settings: Any | None = None,
    include_traceback: bool = False,
) -> dict[str, Any]:
    """Erzwingt dry_run=true und führt create_vplib_from_payload aus."""
    normalized_payload = dict(payload or {})
    options = dict(normalized_payload.get("options", {}) or {})
    options["dry_run"] = True
    normalized_payload["options"] = options

    return create_vplib_from_payload(
        normalized_payload,
        settings=settings,
        include_traceback=include_traceback,
    )


def run_settings_check(settings: Any, *, dry_run: bool = True) -> VplibRouteCheck:
    """Prüft VPLIB-Settings und Directory-Plan."""
    resolved_settings = normalize_settings(settings)

    try:
        ensure_result = resolved_settings.ensure_directories(
            dry_run=dry_run,
            include_source_root=True,
            strict=False,
        )
    except Exception as exc:
        return failed_check(
            "settings",
            error_from_exception(
                exc,
                code="VPLIB_ROUTE_SETTINGS_DIRECTORY_FAILED",
                source="settings",
                include_traceback=False,
            ),
        )

    return VplibRouteCheck(
        name="settings",
        status=VplibCheckStatus.OK.value if ensure_result.ok else VplibCheckStatus.WARNING.value,
        ok=True,
        payload={
            "settings": resolved_settings.to_dict() if hasattr(resolved_settings, "to_dict") else str(resolved_settings),
            "directory_ensure": ensure_result.to_dict() if hasattr(ensure_result, "to_dict") else str(ensure_result),
        },
        warnings=tuple() if ensure_result.ok else ("One or more configured directories could not be ensured.",),
    ).normalized()


def run_import_check() -> VplibRouteCheck:
    """Prüft, ob zentrale VPLIB-Module importiert werden können."""
    module_names = (
        "vplib",
        "vplib.defaults",
        "vplib.validators",
        "vplib.creators",
        "vplib.sources",
    )

    imports: dict[str, Any] = {}
    errors: list[VplibRouteError] = []

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
            imports[module_name] = {
                "ok": True,
                "module": getattr(module, "__name__", module_name),
                "version": getattr(module, "__version__", None),
            }
        except Exception as exc:
            error = error_from_exception(
                exc,
                code="VPLIB_ROUTE_IMPORT_FAILED",
                source=module_name,
                include_traceback=False,
            )
            errors.append(error)
            imports[module_name] = {
                "ok": False,
                "error": error.to_dict(),
            }

    return VplibRouteCheck(
        name="imports",
        status=VplibCheckStatus.OK.value,
        ok=not errors,
        payload={"imports": imports},
        errors=tuple(errors),
    ).normalized()


def run_vplib_health_check() -> VplibRouteCheck:
    """Prüft VPLIB-Health-Funktionen."""
    health_payload: dict[str, Any] = {}
    errors: list[VplibRouteError] = []

    health_functions: tuple[tuple[str, str, str], ...] = (
        ("vplib", "vplib", "get_vplib_health"),
        ("defaults", "vplib.defaults", "get_defaults_health"),
        ("validators", "vplib.validators", "get_validators_health"),
        ("creators", "vplib.creators", "get_creators_health"),
        ("sources", "vplib.sources", "get_sources_health"),
    )

    for key, module_name, function_name in health_functions:
        try:
            module = importlib.import_module(module_name)
            function = getattr(module, function_name)
            health_payload[key] = normalize_json_value(function())
        except Exception as exc:
            error = error_from_exception(
                exc,
                code="VPLIB_ROUTE_HEALTH_FUNCTION_FAILED",
                source=f"{module_name}.{function_name}",
                include_traceback=False,
            )
            errors.append(error)
            health_payload[key] = {
                "healthy": False,
                "error": error.to_dict(),
            }

    healthy = all(
        bool(payload.get("healthy", False))
        for payload in health_payload.values()
        if isinstance(payload, Mapping)
    )

    return VplibRouteCheck(
        name="vplib_health",
        status=VplibCheckStatus.OK.value if healthy else VplibCheckStatus.WARNING.value,
        ok=not errors,
        payload=health_payload,
        errors=tuple(errors),
        warnings=tuple() if healthy else ("One or more VPLIB health checks reported unhealthy state.",),
    ).normalized()


def build_minimal_test_documents(*, settings: Any | None = None) -> dict[str, dict[str, Any]]:
    """
    Baut ein minimales, aber vollständiges VPLIB-Dokumentset.

    Dieses Set ist für die Test-Route und bewusst ohne externe Assets.
    """
    resolved_settings = normalize_settings(settings)

    family_id = DEFAULT_SELF_TEST_FAMILY_ID
    package_id = DEFAULT_SELF_TEST_PACKAGE_ID
    variant_id = DEFAULT_SELF_TEST_VARIANT_ID
    object_kind = DEFAULT_SELF_TEST_OBJECT_KIND
    timestamp = utc_now_iso()

    module_documents = {
        "manifest": ["vplib.manifest.json"],
        "modules": ["vplib.modules.json"],
        "family": [
            "family/identity.json",
            "family/classification.json",
        ],
        "variants": [
            "variants/index.json",
            "variants/default.json",
        ],
        "editor": [
            "editor/inventory.json",
            "editor/placement.json",
        ],
        "render": [
            "render/render_variants.json",
        ],
        "physical": [
            "physical/base.json",
            "physical/dimensions.json",
            "physical/collision.json",
        ],
        "manufacturer": [
            "manufacturer/contract.json",
        ],
    }

    return {
        "vplib.manifest.json": {
            "schema_version": "vplib.manifest.v1",
            "vplib_version": "1.0.0",
            "package_id": package_id,
            "family_id": family_id,
            "family_slug": family_id,
            "family_name": "Self Test Block",
            "package_version": "0.1.0",
            "object_kind": object_kind,
            "classification": {
                "domain": "hochbau",
                "category": "waende",
                "subcategory": "self_test",
                "classification_path": "hochbau/waende/self_test",
            },
            "lifecycle_status": "draft",
            "created_at": timestamp,
            "updated_at": timestamp,
            "source": {
                "source_kind": "system",
                "source_name": DEFAULT_SELF_TEST_ROUTE_NAME,
                "generator": "vectoplan-library.vplib",
                "generator_version": "0.1.0",
            },
            "metadata": {
                "generated_by": "vplib_route_service",
                "service_name": getattr(resolved_settings, "service_name", "vectoplan-library"),
            },
        },
        "vplib.modules.json": {
            "schema_version": "vplib.modules.v1",
            "object_kind": object_kind,
            "module_set_kind": "standard",
            "validation_mode": "strict",
            "active_modules": [
                "manifest",
                "modules",
                "family",
                "variants",
                "editor",
                "render",
                "physical",
                "manufacturer",
            ],
            "required_modules": [
                "manifest",
                "modules",
                "family",
                "variants",
                "editor",
                "manufacturer",
            ],
            "optional_modules": [
                "render",
                "physical",
                "material",
                "calculation",
                "analysis",
                "dynamic",
                "docs",
                "tests",
            ],
            "excluded_modules": [],
            "module_versions": {
                "manifest": "v1",
                "modules": "v1",
                "family": "v1",
                "variants": "v1",
                "editor": "v1",
                "render": "v1",
                "physical": "v1",
                "manufacturer": "v1",
            },
            "module_documents": module_documents,
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "family/identity.json": {
            "schema_version": "vplib.family.identity.v1",
            "package_id": package_id,
            "family_id": family_id,
            "family_slug": family_id,
            "family_name": "Self Test Block",
            "display_name": "Self Test Block",
            "short_name": "Self Test",
            "description": "Minimal VPLIB self-test block.",
            "version": "0.1.0",
            "author": None,
            "language": "en",
            "tags": ["self_test", "route_test"],
            "aliases": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "family/classification.json": {
            "schema_version": "vplib.family.classification.v1",
            "object_kind": object_kind,
            "domain": "hochbau",
            "category": "waende",
            "subcategory": "self_test",
            "classification_path": "hochbau/waende/self_test",
            "tags": ["self_test"],
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "variants/index.json": {
            "schema_version": "vplib.variants.index.v1",
            "mode": "single",
            "default_variant_id": variant_id,
            "variant_ids": [variant_id],
            "variants": [
                {
                    "variant_id": variant_id,
                    "label": "Default",
                    "status": "active",
                    "enabled": True,
                    "sort_order": 0,
                }
            ],
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "variants/default.json": {
            "schema_version": "vplib.variant.v1",
            "variant_id": variant_id,
            "label": "Default",
            "status": "active",
            "enabled": True,
            "sort_order": 0,
            "inherits_from": None,
            "parameters": {},
            "overrides": {},
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "editor/inventory.json": {
            "schema_version": "vplib.editor.inventory.v1",
            "family_id": family_id,
            "default_variant_id": variant_id,
            "label": "Self Test Block",
            "short_label": "Self Test",
            "description": "Minimal VPLIB self-test block.",
            "domain": "hochbau",
            "category": "waende",
            "subcategory": "self_test",
            "object_kind": object_kind,
            "inventory_group": "creative_library",
            "visibility": "visible",
            "creative_library_visible": True,
            "hotbar_eligible": True,
            "icon_ref": None,
            "preview_ref": None,
            "sort_key": "hochbau/waende/self_test/self_test_block",
            "search_text": "Self Test Block self_test route_test",
            "tags": ["self_test", "route_test"],
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "editor/placement.json": {
            "schema_version": "vplib.editor.placement.v1",
            "object_kind": object_kind,
            "placement_mode": "centered",
            "grid_footprint": {
                "size_cells": {
                    "x": 1,
                    "y": 1,
                    "z": 1,
                },
                "size_cells_x": 1,
                "size_cells_y": 1,
                "size_cells_z": 1,
                "cell_size_m": 1.0,
                "size_m": {
                    "x": 1.0,
                    "y": 1.0,
                    "z": 1.0,
                },
            },
            "allowed_surfaces": ["top", "side", "bottom"],
            "allowed_hosts": ["grid"],
            "rotation_allowed": True,
            "rotation_steps": [0, 90, 180, 270],
            "snap_mode": "grid",
            "requires_support": None,
            "requires_surface_normal": False,
            "requires_support_surface": False,
            "can_stack": True,
            "can_attach": False,
            "can_rotate": True,
            "grid_footprint_is_placement_truth": True,
            "visual_model_must_remain_inside_footprint": True,
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "render/render_variants.json": {
            "schema_version": "vplib.render.variants.v1",
            "default_render_variant_id": "default",
            "render_variant_ids": ["default"],
            "render_variants": [
                {
                    "render_variant_id": "default",
                    "variant_id": variant_id,
                    "shape": "cube",
                    "fit_mode": "strict_inside",
                    "visual_alignment": "centered",
                    "fallback_color": "#9CA3AF",
                    "material_id": "default_material",
                    "icon_ref": None,
                    "preview_ref": None,
                    "texture_ref": None,
                    "glb_ref": None,
                    "model_ref": None,
                    "bounds_m": None,
                    "asset_refs": [],
                    "enabled": True,
                    "metadata": {
                        "generated_by": "vplib_route_service",
                    },
                }
            ],
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "physical/base.json": {
            "schema_version": "vplib.physical.base.v1",
            "object_kind": object_kind,
            "physical_role": "generic",
            "physical_shape": "box",
            "load_bearing": None,
            "fire_class": None,
            "has_collision": True,
            "has_occupancy": True,
            "has_mass": False,
            "has_layers": False,
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "physical/dimensions.json": {
            "schema_version": "vplib.physical.dimensions.v1",
            "grid": {
                "size_cells": {
                    "x": 1,
                    "y": 1,
                    "z": 1,
                },
                "size_cells_x": 1,
                "size_cells_y": 1,
                "size_cells_z": 1,
                "cell_size_m": 1.0,
                "cell_count": 1,
                "size_m": {
                    "x": 1.0,
                    "y": 1.0,
                    "z": 1.0,
                },
            },
            "bounds": {
                "schema_version": "vplib.physical.bounds.v1",
                "width_m": 1.0,
                "height_m": 1.0,
                "depth_m": 1.0,
                "size_m": {
                    "x": 1.0,
                    "y": 1.0,
                    "z": 1.0,
                },
                "offset_m": {
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0,
                },
                "origin_m": {
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0,
                },
                "volume_m3": 1.0,
                "must_fit_grid_footprint": True,
                "metadata": {},
            },
            "real_dimensions": {
                "width_m": 1.0,
                "height_m": 1.0,
                "depth_m": 1.0,
            },
            "real_width_m": 1.0,
            "real_height_m": 1.0,
            "real_depth_m": 1.0,
            "wall_thickness_m": None,
            "volume_m3": 1.0,
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "physical/collision.json": {
            "schema_version": "vplib.physical.collision.v1",
            "enabled": True,
            "collision_mode": "solid",
            "shape": "box",
            "bounds": None,
            "collision_group": "default",
            "can_block_placement": True,
            "can_be_selected": True,
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
        "manufacturer/contract.json": {
            "schema_version": "vplib.manufacturer.contract.v1",
            "contract_id": "default_contract",
            "manufacturer_allowed": False,
            "contract_mode": "disabled",
            "overlay_level": "none",
            "validation_policy": "strict",
            "allow_branding": False,
            "allow_product_mapping": False,
            "allow_asset_overrides": False,
            "allow_render_overrides": False,
            "allow_material_overrides": False,
            "allow_physical_overrides": False,
            "allow_calculation_overrides": False,
            "require_product_identity": False,
            "require_datasheet": False,
            "require_validation": True,
            "allowed_override_prefixes": [
                "variant",
                "editor.inventory",
                "render",
                "physical",
                "material",
                "calculation",
                "manufacturer",
            ],
            "forbidden_override_prefixes": [
                "schema_version",
                "vplib_version",
                "package_id",
                "family_id",
                "family_slug",
                "family_name",
                "object_kind",
                "classification",
                "classification_path",
                "domain",
                "tab",
                "category",
                "subcategory",
                "active_modules",
                "required_modules",
                "optional_modules",
                "module_versions",
            ],
            "metadata": {
                "generated_by": "vplib_route_service",
            },
        },
    }


def validate_test_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    settings: Any | None = None,
) -> Any:
    """Validiert Test-Dokumente über die VPLIB-Validatoren."""
    resolved_settings = normalize_settings(settings)

    from vplib.validators import validate_vplib_documents

    return validate_vplib_documents(
        normalize_documents_mapping(documents),
        mode=getattr(resolved_settings, "default_validation_mode", "strict"),
        validate_schema=True,
        validate_semantics=True,
        validate_assets=True,
        metadata={
            "source": "vplib_route_service.self_test",
        },
    )


def dry_run_write_test_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    settings: Any | None = None,
) -> Any:
    """
    Führt Dry-Run-Schreibtest mit Test-Dokumenten aus.

    Nutzt bewusst den öffentlichen Creator-Wrapper, damit der gleiche Pfad wie
    spätere Routen und echte Create-Flows getestet wird.
    """
    resolved_settings = normalize_settings(settings)

    from vplib.creators import write_vplib_documents

    return write_vplib_documents(
        package_root=str(resolved_settings.self_test_package_root),
        documents=normalize_documents_mapping(documents),
        dry_run=True,
        write_mode="overwrite",
        metadata={
            "source": "vplib_route_service.self_test",
        },
    )


def execute_create_request(
    request_payload: Mapping[str, Any],
    *,
    settings: Any,
    options: Mapping[str, Any],
) -> Any:
    """Führt die eigentliche VPLIB-Erstellung über vplib.creators aus."""
    resolved_settings = normalize_settings(settings)

    from vplib.creators import create_vplib

    return create_vplib(
        request=normalize_json_mapping(request_payload),
        service_root=str(resolved_settings.service_root),
        library_catalog_root=str(resolved_settings.library_catalog_root),
        source_root=str(resolved_settings.source_root),
        generated_root=str(resolved_settings.generated_root),
        archive_root=str(resolved_settings.archive_root),
        dry_run=bool(options.get("dry_run", resolved_settings.dry_run_default)),
        write_mode=str(options.get("write_mode", resolved_settings.default_write_mode)),
        create_archive=bool(options.get("create_archive", resolved_settings.create_archive_default)),
        metadata={
            "source": "vplib_route_service.create",
        },
    )


def extract_create_options(
    payload: Mapping[str, Any],
    *,
    settings: Any,
) -> dict[str, Any]:
    """Extrahiert und normalisiert Create-Optionen aus Route-Payload."""
    resolved_settings = normalize_settings(settings)
    options = payload.get("options", {})

    if options is None:
        options = {}

    if not isinstance(options, Mapping):
        raise VplibRouteServiceError("Payload field 'options' must be an object if provided.")

    return {
        "dry_run": parse_bool_value(options.get("dry_run", resolved_settings.dry_run_default)),
        "write_mode": normalize_write_mode(options.get("write_mode", resolved_settings.default_write_mode)),
        "create_archive": parse_bool_value(options.get("create_archive", resolved_settings.create_archive_default)),
    }


def normalize_create_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Route-Payload für Create."""
    if payload is None:
        raise VplibRouteServiceError("JSON payload is required.")

    if not isinstance(payload, Mapping):
        raise VplibRouteServiceError("JSON payload must be an object.")

    return normalize_json_mapping(payload)


def build_route_response(
    *,
    result: Mapping[str, Any] | VplibRouteResult,
    http_status_ok: int = 200,
    http_status_error: int = 500,
) -> tuple[dict[str, Any], int]:
    """Baut eine Flask-kompatible Antwortstruktur."""
    if isinstance(result, VplibRouteResult):
        payload = result.to_dict()
    elif isinstance(result, Mapping):
        payload = normalize_json_mapping(result)
    else:
        payload = {
            "schema_version": VPLIB_ROUTE_SERVICE_SCHEMA_VERSION,
            "ok": False,
            "status": "failed",
            "errors": [
                {
                    "code": "VPLIB_ROUTE_INVALID_RESULT",
                    "message": "Route service result is not JSON-compatible mapping.",
                    "source": "vplib_route_service",
                    "details": {
                        "result_type": type(result).__name__,
                    },
                }
            ],
        }

    return payload, int(http_status_ok) if bool(payload.get("ok", False)) else int(http_status_error)


def failed_check(name: str, error: VplibRouteError) -> VplibRouteCheck:
    """Erzeugt fehlgeschlagenen Check."""
    return VplibRouteCheck(
        name=name,
        status=VplibCheckStatus.FAILED.value,
        ok=False,
        errors=(error,),
    ).normalized()


def error_from_exception(
    exc: BaseException,
    *,
    code: str,
    source: str,
    include_traceback: bool,
    details: Mapping[str, Any] | None = None,
) -> VplibRouteError:
    """Wandelt Exception in VplibRouteError."""
    return VplibRouteError(
        code=code,
        message=str(exc) or exc.__class__.__name__,
        source=source,
        details={
            "exception_type": exc.__class__.__name__,
            **dict(details or {}),
        },
        traceback_text=traceback.format_exc() if include_traceback else None,
    ).normalized()


@lru_cache(maxsize=1)
def load_vplib_settings_module() -> ModuleType:
    """Lädt das VPLIB-Settings-Modul robust."""
    if VPLIB_SETTINGS_FILE.is_file():
        try:
            return load_module_from_file(
                "_vectoplan_library_route_service_vplib_settings",
                VPLIB_SETTINGS_FILE,
            )
        except Exception:
            pass

    errors: list[str] = []

    for module_name in SETTINGS_MODULE_CANDIDATES:
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")

    raise VplibRouteServiceError(
        "Could not load VPLIB settings module. "
        f"settings_file={VPLIB_SETTINGS_FILE}. "
        f"errors={' | '.join(errors)}"
    )


@lru_cache(maxsize=16)
def load_module_from_file(module_name: str, file_path: Path) -> ModuleType:
    """Lädt ein Modul direkt aus einem Dateipfad."""
    path = Path(file_path)

    if not path.is_file():
        raise VplibRouteServiceError(f"Module file does not exist: {path}")

    spec = importlib_util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise VplibRouteServiceError(f"Could not create import spec for {path}")

    module = importlib_util.module_from_spec(spec)
    sys.modules[module_name] = module

    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    return module


def normalize_settings(value: Any | None) -> Any:
    """Normalisiert Settings-Objekt defensiv."""
    if value is not None:
        try:
            return value.normalized() if hasattr(value, "normalized") else value
        except Exception as exc:
            raise VplibRouteServiceError(f"Invalid VPLIB settings object: {exc}") from exc

    try:
        settings_module = load_vplib_settings_module()
        getter = getattr(settings_module, "get_vplib_settings", None)

        if not callable(getter):
            raise VplibRouteServiceError("VPLIB settings module does not export callable get_vplib_settings().")

        settings = getter()
        return settings.normalized() if hasattr(settings, "normalized") else settings
    except Exception as exc:
        raise VplibRouteServiceError(f"Could not load VPLIB settings: {exc}") from exc


@lru_cache(maxsize=128)
def parse_route_action_value(value: Any) -> str:
    """Parst VplibRouteAction."""
    try:
        if isinstance(value, VplibRouteAction):
            return value.value

        raw = normalize_enum_key(value)
        return VplibRouteAction(raw).value
    except Exception as exc:
        raise VplibRouteServiceError(f"Invalid route action {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_check_status_value(value: Any) -> str:
    """Parst VplibCheckStatus."""
    try:
        if isinstance(value, VplibCheckStatus):
            return value.value

        raw = normalize_enum_key(value)
        return VplibCheckStatus(raw).value
    except Exception as exc:
        raise VplibRouteServiceError(f"Invalid check status {value!r}.") from exc


@lru_cache(maxsize=128)
def normalize_write_mode(value: Any) -> str:
    """Normalisiert WriteMode für Route-Payloads."""
    raw = normalize_enum_key(value)

    aliases = {
        "fail": "fail",
        "error": "fail",
        "strict": "fail",
        "skip": "skip",
        "ignore": "skip",
        "overwrite": "overwrite",
        "replace": "overwrite",
        "update": "overwrite",
    }

    if raw in aliases:
        return aliases[raw]

    raise VplibRouteServiceError(f"Invalid write_mode {value!r}.")


@lru_cache(maxsize=128)
def parse_bool_value(value: Any) -> bool:
    """Parst boolesche Werte robust."""
    if isinstance(value, bool):
        return value

    raw = normalize_enum_key(value)

    if raw in {"1", "true", "yes", "y", "on", "enabled"}:
        return True

    if raw in {"0", "false", "no", "n", "off", "disabled"}:
        return False

    raise VplibRouteServiceError(f"Invalid boolean value {value!r}.")


def is_result_ok(value: Any | None) -> bool:
    """Prüft gängige Result-Objekte auf ok/valid."""
    if value is None:
        return False

    try:
        return bool(value.ok)
    except Exception:
        pass

    try:
        return bool(value.valid)
    except Exception:
        pass

    try:
        return bool(value.is_valid)
    except Exception:
        pass

    if isinstance(value, Mapping):
        if "ok" in value:
            return bool(value.get("ok"))
        if "valid" in value:
            return bool(value.get("valid"))
        if "failed" in value:
            return not bool(value.get("failed"))

    return False


def object_to_dict(value: Any | None) -> Any:
    """Serialisiert bekannte Objekte robust und JSON-kompatibel."""
    if value is None:
        return None

    if hasattr(value, "to_dict"):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [object_to_dict(item) for item in value]

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def normalize_documents_mapping(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalisiert path -> document Mapping."""
    if not isinstance(documents, Mapping):
        raise VplibRouteServiceError("documents must be a mapping.")

    return {
        clean_required_string(path, "document_path"): normalize_json_mapping(document)
        for path, document in documents.items()
    }


def normalize_json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert Mapping JSON-kompatibel."""
    if not isinstance(value, Mapping):
        raise VplibRouteServiceError("value must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def normalize_json_value(value: Any) -> Any:
    """Normalisiert Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Mapping):
        return normalize_json_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    if hasattr(value, "to_dict"):
        try:
            return normalize_json_value(value.to_dict())
        except Exception:
            return str(value)

    return str(value)


def normalize_string_tuple(values: Any) -> tuple[str, ...]:
    """Normalisiert Stringlisten ohne Duplikate."""
    if values is None:
        return tuple()

    if isinstance(values, str):
        values = (values,)

    result: list[str] = []
    seen: set[str] = set()

    for value in values:
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise VplibRouteServiceError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except VplibRouteServiceError:
        raise
    except Exception as exc:
        raise VplibRouteServiceError(f"Invalid enum value {value!r}.") from exc


def utc_now_iso() -> str:
    """Liefert einen stabilen UTC-Zeitstempel für Testdokumente."""
    try:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
    except Exception:
        return "1970-01-01T00:00:00+00:00"


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise VplibRouteServiceError(f"{field_name} is required.")

        return cleaned
    except VplibRouteServiceError:
        raise
    except Exception as exc:
        raise VplibRouteServiceError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_vplib_route_service_caches() -> None:
    """Leert interne Route-Service-Caches."""
    load_vplib_settings_module.cache_clear()
    load_module_from_file.cache_clear()
    parse_route_action_value.cache_clear()
    parse_check_status_value.cache_clear()
    normalize_write_mode.cache_clear()
    parse_bool_value.cache_clear()


__all__ = [
    "DEFAULT_SELF_TEST_FAMILY_ID",
    "DEFAULT_SELF_TEST_OBJECT_KIND",
    "DEFAULT_SELF_TEST_PACKAGE_ID",
    "DEFAULT_SELF_TEST_ROUTE_NAME",
    "DEFAULT_SELF_TEST_VARIANT_ID",
    "SERVICE_ROOT",
    "SETTINGS_MODULE_CANDIDATES",
    "SRC_ROOT",
    "VPLIB_ROUTE_SERVICE_SCHEMA_VERSION",
    "VPLIB_SETTINGS_FILE",
    "VplibCheckStatus",
    "VplibRouteAction",
    "VplibRouteCheck",
    "VplibRouteError",
    "VplibRouteResult",
    "VplibRouteServiceError",
    "build_minimal_test_documents",
    "build_route_response",
    "clean_optional_string",
    "clean_required_string",
    "clear_vplib_route_service_caches",
    "create_vplib_dry_run_from_payload",
    "create_vplib_from_payload",
    "dry_run_write_test_documents",
    "error_from_exception",
    "execute_create_request",
    "extract_create_options",
    "failed_check",
    "is_result_ok",
    "load_module_from_file",
    "load_vplib_settings_module",
    "normalize_create_payload",
    "normalize_documents_mapping",
    "normalize_enum_key",
    "normalize_json_mapping",
    "normalize_json_value",
    "normalize_settings",
    "normalize_string_tuple",
    "normalize_write_mode",
    "object_to_dict",
    "parse_bool_value",
    "parse_check_status_value",
    "parse_route_action_value",
    "run_import_check",
    "run_settings_check",
    "run_vplib_health_check",
    "run_vplib_self_test",
    "utc_now_iso",
    "validate_test_documents",
]