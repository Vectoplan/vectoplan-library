# services/vectoplan-library/src/library/services/library_create_service.py
"""
VECTOPLAN Library – Create Service

Purpose:
    Backend service for creating simple, scanner-readable VPLIB packages.

Scope:
    - No Flask dependency.
    - No direct database dependency.
    - No automatic publishing.
    - No Three.js / model upload handling.
    - No executable package content.
    - Produces scanner-readable directory packages and downloadable .vplib archives.
    - Uses the backend taxonomy as canonical source for domain/category/subcategory.
    - Creates or preserves stable `vplib_uid` for every package.
    - Optionally reads Definition Catalog/Create Context through a service adapter.
    - Optionally builds CreativeLibraryDraftService-compatible payloads.

Main public functions:
    - get_service_health()
    - get_create_options()
    - get_create_context(payload)
    - build_draft(payload)
    - validate_draft(payload)
    - build_package_plan(payload)
    - build_vplib_archive(payload)
    - save_package(payload)
    - build_persistent_draft_payload(payload)
    - build_publish_bundle_from_create_payload(payload)

Important:
    Saving is disabled by default and must be explicitly enabled with:
        VPLIB_CREATE_WRITE_ENABLED=true

Taxonomy:
    Domain, category and subcategory are required.
    No fallback to hochbau/bloecke/basis is allowed for new packages.

Canonical source path:
    src/library/source/{domain}/{category}/{subcategory}/{family_slug}

Canonical family_id:
    vp.{domain}.{category}.{subcategory}.{family_slug}

Canonical package_id:
    vplib.vp.{domain}.{category}.{subcategory}.{family_slug}

Canonical VPLIB UID:
    - field: vplib_uid
    - created before package documents are built
    - stored in vplib.manifest.json
    - preserved if provided by route/frontend
    - never silently replaced when invalid
    - later database layer only adopts this ID
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Mapping, Optional, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIBRARY_CREATE_SERVICE_VERSION = "0.4.0"
LIBRARY_CREATE_SERVICE_COMPONENT = "library-create-service"

CREATE_API_PREFIX = "/api/v1/vplib/create"

DEFAULT_SCHEMA_VERSION = "0.1.0"
DEFAULT_PACKAGE_VERSION = "0.1.0"

ENV_SOURCE_ROOT_PRIMARY = "VECTOPLAN_LIBRARY_SOURCE_ROOT"
ENV_SOURCE_ROOT_SECONDARY = "VPLIB_CREATE_SOURCE_ROOT"
ENV_WRITE_ENABLED = "VPLIB_CREATE_WRITE_ENABLED"
ENV_OVERWRITE_ENABLED = "VPLIB_CREATE_OVERWRITE_ENABLED"
ENV_DEBUG = "VPLIB_CREATE_DEBUG"

VPLIB_UID_FIELD = "vplib_uid"
VPLIB_UID_KEYS = (
    "vplib_uid",
    "vplibUid",
    "vplib_uid_v1",
)

MANIFEST_DOCUMENT_PATH = "vplib.manifest.json"

DEFAULT_OBJECT_KIND = "cell_block"
DEFAULT_PRIMITIVE_SHAPE = "block"
DEFAULT_UNIT = "m"

REQUIRED_TAXONOMY_FIELDS = ("domain", "category", "subcategory")

ALLOWED_OBJECT_KINDS = {
    "cell_block",
    "multi_cell_module",
    "catalog_object",
    "adaptive_system",
}

ALLOWED_PRIMITIVE_SHAPES = {
    "block",
    "wall",
    "slab",
    "cylinder",
    "pipe",
}

ALLOWED_UNITS = {
    "m",
    "cm",
    "mm",
}

EXECUTABLE_EXTENSIONS_BLOCKLIST = {
    ".py",
    ".pyc",
    ".pyo",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".bat",
    ".cmd",
    ".ps1",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".jar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".com",
    ".scr",
    ".msi",
}

MAX_TEXT_LENGTH = 2400
MAX_SLUG_LENGTH = 96
MAX_VARIANTS = 50
MAX_VARIABLES = 120


# ---------------------------------------------------------------------------
# Lazy optional service imports
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _load_taxonomy_module() -> ModuleType:
    """Load canonical taxonomy service module defensively."""
    errors: list[str] = []

    for module_name in (
        "library.taxonomy",
        "src.library.taxonomy",
        "vectoplan_library.library.taxonomy",
        "vectoplan_library.src.library.taxonomy",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError("Could not import taxonomy service. " + " | ".join(errors))


@lru_cache(maxsize=1)
def _load_definition_catalog_service_module() -> ModuleType:
    """Load optional DB-backed Definition Catalog service.

    This is an adapter dependency, not a direct DB dependency. If unavailable,
    the create service continues to work with static/taxonomy-backed options.
    """
    errors: list[str] = []

    for module_name in (
        "library.services.library_definition_catalog_service",
        "src.library.services.library_definition_catalog_service",
        "vectoplan_library.library.services.library_definition_catalog_service",
        "vectoplan_library.src.library.services.library_definition_catalog_service",
    ):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {type(exc).__name__}: {exc}")

    raise ImportError("Could not import definition catalog service. " + " | ".join(errors))


def _get_taxonomy_import_error() -> BaseException | None:
    try:
        _load_taxonomy_module()
        return None
    except Exception as exc:
        return exc


def _taxonomy_normalize_slug(value: Any, *, default: str = "") -> str:
    try:
        module = _load_taxonomy_module()
        normalizer = getattr(module, "normalize_slug", None)
        if callable(normalizer):
            return str(normalizer(value, default=default))
    except Exception:
        pass

    return _slugify(value) or default


def _taxonomy_json_safe(value: Any) -> Any:
    try:
        module = _load_taxonomy_module()
        helper = getattr(module, "make_json_safe", None)
        if callable(helper):
            return helper(value)
    except Exception:
        pass

    return _json_safe_fallback(value)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CreateIssue:
    """Structured issue for errors, warnings and info messages."""

    code: str
    message: str
    field: str = ""
    severity: str = "error"
    details: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }

        if self.field:
            result["field"] = self.field

        if self.details:
            result["details"] = _json_safe(self.details)

        return result


@dataclass(frozen=True)
class CreateResult:
    """Public result envelope used by route services and tests."""

    ok: bool
    status: str
    data: dict[str, Any] = dataclass_field(default_factory=dict)
    errors: list[CreateIssue] = dataclass_field(default_factory=list)
    warnings: list[CreateIssue] = dataclass_field(default_factory=list)
    info: list[CreateIssue] = dataclass_field(default_factory=list)
    http_status: int = 200

    @property
    def vplib_uid(self) -> str | None:
        return _extract_vplib_uid_from_any(self.data)

    def to_dict(self, *, include_http_status: bool = False) -> dict[str, Any]:
        uid = self.vplib_uid

        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "version": LIBRARY_CREATE_SERVICE_VERSION,
            "component": LIBRARY_CREATE_SERVICE_COMPONENT,
            "vplib_uid": uid,
            "data": _json_safe(self.data),
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
            "info": [issue.to_dict() for issue in self.info],
        }

        if include_http_status:
            payload["_http_status"] = self.http_status

        return payload


@dataclass(frozen=True)
class NormalizedCreateDraft:
    """Internal normalized VPLIB-create draft."""

    vplib_uid: str

    family_name: str
    family_slug: str
    family_description: str

    domain: str
    category: str
    subcategory: str
    object_kind: str

    taxonomy_version: str
    classification_path: str
    taxonomy_labels: dict[str, str]
    source_parts: tuple[str, ...]
    source_path: str

    family_id: str
    package_id: str
    package_version: str

    default_variant_id: str
    variants: list[dict[str, Any]]

    primitive_shape: str
    geometry_width: float
    geometry_height: float
    geometry_depth: float
    geometry_unit: str

    editor_cells_x: int
    editor_cells_y: int
    editor_cells_z: int
    editor_cell_size_x: float
    editor_cell_size_y: float
    editor_cell_size_z: float

    material_class: str
    material_classes: list[str]
    variables: list[dict[str, Any]]

    created_at: str
    source: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "vplib_uid": self.vplib_uid,
            "family_name": self.family_name,
            "family_slug": self.family_slug,
            "family_description": self.family_description,
            "domain": self.domain,
            "category": self.category,
            "subcategory": self.subcategory,
            "object_kind": self.object_kind,
            "taxonomy": {
                "version": self.taxonomy_version,
                "classification_path": self.classification_path,
                "labels": dict(self.taxonomy_labels),
                "source_parts": list(self.source_parts),
                "source_path": self.source_path,
            },
            "classification": {
                "taxonomy_version": self.taxonomy_version,
                "domain": self.domain,
                "category": self.category,
                "subcategory": self.subcategory,
                "classification_path": self.classification_path,
                "labels": dict(self.taxonomy_labels),
                "object_kind": self.object_kind,
            },
            "source_path": self.source_path,
            "source_parts": list(self.source_parts),
            "family_id": self.family_id,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "default_variant_id": self.default_variant_id,
            "variants": _json_safe(self.variants),
            "primitive_shape": self.primitive_shape,
            "geometry": {
                "mode": "primitive",
                "primitive_shape": self.primitive_shape,
                "dimensions": {
                    "width": self.geometry_width,
                    "height": self.geometry_height,
                    "depth": self.geometry_depth,
                    "unit": self.geometry_unit,
                },
            },
            "editor_block": {
                "cells": {
                    "x": self.editor_cells_x,
                    "y": self.editor_cells_y,
                    "z": self.editor_cells_z,
                },
                "cell_size": {
                    "x": self.editor_cell_size_x,
                    "y": self.editor_cell_size_y,
                    "z": self.editor_cell_size_z,
                    "unit": self.geometry_unit,
                },
            },
            "technical": {
                "material_class": self.material_class,
                "material_classes": list(self.material_classes),
                "variables": _json_safe(self.variables),
            },
            "created_at": self.created_at,
            "source": _json_safe(self.source),
        }


class CreateDraftNormalizationError(ValueError):
    """Raised when a payload cannot be normalized into a valid create draft."""

    def __init__(
        self,
        message: str,
        *,
        errors: Optional[list[CreateIssue]] = None,
        warnings: Optional[list[CreateIssue]] = None,
    ) -> None:
        super().__init__(message)
        self.errors = list(errors or [])
        self.warnings = list(warnings or [])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_service_health() -> CreateResult:
    """Return a defensive health payload for the create service."""
    warnings: list[CreateIssue] = []
    errors: list[CreateIssue] = []
    info: list[CreateIssue] = []

    source_root = None
    source_root_exists = False
    source_root_is_directory = False

    try:
        source_root = get_source_root()
        source_root_exists = source_root.exists()
        source_root_is_directory = source_root.is_dir()

        if not source_root_exists:
            warnings.append(
                _warning(
                    "source_root_missing",
                    "Der Create-Source-Root existiert noch nicht. Er wird erst beim Speichern benötigt.",
                    field="source_root",
                    details={"source_root": str(source_root)},
                )
            )
        elif not source_root_is_directory:
            errors.append(
                _error(
                    "source_root_not_directory",
                    "Der konfigurierte Source-Root ist kein Verzeichnis.",
                    field="source_root",
                    details={"source_root": str(source_root)},
                )
            )
    except Exception as exc:
        errors.append(_exception_issue("source_root_error", exc, field="source_root"))

    taxonomy_health: dict[str, Any] = {}
    taxonomy_available = _is_taxonomy_available()

    if not taxonomy_available:
        errors.append(
            _exception_issue(
                "taxonomy_service_unavailable",
                _get_taxonomy_import_error(),
                field="library.taxonomy",
                fallback_message="Taxonomie-Service ist nicht verfügbar.",
            )
        )
    else:
        try:
            taxonomy_health = _call_taxonomy_health()

            if not bool(taxonomy_health.get("healthy") or taxonomy_health.get("ok")):
                errors.append(
                    _error(
                        "taxonomy_service_unhealthy",
                        "Taxonomie-Service ist verfügbar, aber nicht healthy.",
                        field="library.taxonomy",
                        details=taxonomy_health,
                    )
                )
            else:
                info.append(
                    _info(
                        "taxonomy_service_available",
                        "Taxonomie-Service ist verfügbar und healthy.",
                    )
                )
        except Exception as exc:
            errors.append(
                _exception_issue(
                    "taxonomy_health_failed",
                    exc,
                    field="library.taxonomy.health",
                )
            )

    definition_health = _get_definition_catalog_service_health()
    definition_available = bool(definition_health.get("available", False))

    if definition_available:
        info.append(
            _info(
                "definition_catalog_available",
                "Definition-Catalog-Service ist verfügbar.",
                field="definitions",
                details=definition_health,
            )
        )
    else:
        warnings.append(
            _warning(
                "definition_catalog_unavailable",
                "Definition-Catalog-Service ist nicht verfügbar. Create fällt auf Taxonomy/Static Options zurück.",
                field="definitions",
                details=definition_health,
            )
        )

    write_enabled = _env_bool(ENV_WRITE_ENABLED, default=False)
    overwrite_enabled = _env_bool(ENV_OVERWRITE_ENABLED, default=False)
    debug_enabled = _env_bool(ENV_DEBUG, default=False)

    uid_health = _get_vplib_uid_service_health()

    if not uid_health.get("available", False):
        errors.append(
            _error(
                "vplib_uid_service_unavailable",
                "VPLIB-ID-Service ist nicht verfügbar.",
                field="vplib_uid",
                details=uid_health,
            )
        )
    else:
        info.append(
            _info(
                "vplib_uid_service_available",
                "VPLIB-ID-Service ist verfügbar.",
                field="vplib_uid",
                details=uid_health,
            )
        )

    ok = len(errors) == 0

    return CreateResult(
        ok=ok,
        status="healthy" if ok else "unhealthy",
        data={
            "service": LIBRARY_CREATE_SERVICE_COMPONENT,
            "version": LIBRARY_CREATE_SERVICE_VERSION,
            "source_root": str(source_root) if source_root else "",
            "source_root_exists": source_root_exists,
            "source_root_is_directory": source_root_is_directory,
            "write_enabled": write_enabled,
            "overwrite_enabled": overwrite_enabled,
            "debug_enabled": debug_enabled,
            "vplib_uid": {
                "field": VPLIB_UID_FIELD,
                "stored_in": MANIFEST_DOCUMENT_PATH,
                "created_by": "vplib_id_service",
                "database_creates_id": False,
                "service_health": uid_health,
            },
            "taxonomy": {
                "available": taxonomy_available,
                "required_fields": list(REQUIRED_TAXONOMY_FIELDS),
                "health": taxonomy_health,
            },
            "definitions": {
                "available": definition_available,
                "health": definition_health,
            },
            "routes_expected": {
                "page": "/create",
                "health": f"{CREATE_API_PREFIX}/health",
                "options": f"{CREATE_API_PREFIX}/options",
                "create_context": f"{CREATE_API_PREFIX}/create-context",
                "draft": f"{CREATE_API_PREFIX}/draft",
                "validate": f"{CREATE_API_PREFIX}/validate",
                "package_plan": f"{CREATE_API_PREFIX}/package-plan",
                "download": f"{CREATE_API_PREFIX}/download",
                "save": f"{CREATE_API_PREFIX}/save",
            },
            "capabilities": {
                "build_directory_package": True,
                "build_archive": True,
                "save_to_source_root": write_enabled,
                "definition_catalog_options": definition_available,
                "persistent_draft_payload": True,
                "automatic_publish": False,
                "direct_database_dependency": False,
            },
        },
        errors=errors,
        warnings=warnings,
        info=info,
        http_status=200 if ok else 503,
    )


def get_create_options(*, include_definitions: bool = True, user_id: Any = 1) -> CreateResult:
    """Return create options for the create frontend."""
    try:
        taxonomy_payload = _get_taxonomy_create_options_payload()
        flattened = _flatten_taxonomy_options(taxonomy_payload)

        definition_options = {}
        definition_warnings: list[CreateIssue] = []

        if include_definitions:
            definition_options = _get_definition_create_options_payload(user_id=user_id)
            if not definition_options.get("available", False):
                definition_warnings.append(
                    _warning(
                        "definition_options_unavailable",
                        "Definition-Catalog-Optionen sind nicht verfügbar. Statische Create-Optionen bleiben aktiv.",
                        field="definitions",
                        details=definition_options,
                    )
                )

        static_options = _static_create_options()

        data = {
            "service": LIBRARY_CREATE_SERVICE_COMPONENT,
            "version": LIBRARY_CREATE_SERVICE_VERSION,
            "write_enabled": _env_bool(ENV_WRITE_ENABLED, default=False),
            "overwrite_enabled": _env_bool(ENV_OVERWRITE_ENABLED, default=False),
            "source_root": str(get_source_root()),
            "vplib_uid": "",
            "vplib_uid_field": VPLIB_UID_FIELD,
            "create_payload_normalization": {
                "enabled": True,
                "vplib_uid_field": VPLIB_UID_FIELD,
                "uid_created_by": "vplib_id_service",
                "uid_persisted_in": MANIFEST_DOCUMENT_PATH,
                "existing_valid_uid_is_preserved": True,
                "invalid_uid_is_rejected": True,
                "database_creates_id": False,
            },
            "taxonomy_source": "backend_taxonomy_service",
            "taxonomy_version": taxonomy_payload.get("taxonomy_version", ""),
            "taxonomy_schema_version": taxonomy_payload.get("taxonomy_schema_version", ""),
            "required_taxonomy_fields": list(REQUIRED_TAXONOMY_FIELDS),
            "taxonomy": taxonomy_payload.get("taxonomy", {}),
            "domains": taxonomy_payload.get("domains", []),
            "categories_by_domain": taxonomy_payload.get("categories_by_domain", {}),
            "subcategories_by_category": taxonomy_payload.get("subcategories_by_category", {}),
            "subcategories_by_category_path": taxonomy_payload.get(
                "subcategories_by_category_path",
                taxonomy_payload.get("subcategories_by_category", {}),
            ),
            "categories": flattened["categories"],
            "subcategories": flattened["subcategories"],
            "object_kinds": static_options["object_kinds"],
            "primitive_shapes": static_options["primitive_shapes"],
            "units": static_options["units"],
            "material_classes": static_options["material_classes"],
            "limits": {
                "max_text_length": MAX_TEXT_LENGTH,
                "max_slug_length": MAX_SLUG_LENGTH,
                "max_variants": MAX_VARIANTS,
                "max_variables": MAX_VARIABLES,
            },
            "definitions": definition_options,
        }

        data = _merge_definition_options_into_create_options(data, definition_options)

        return CreateResult(
            ok=True,
            status="ok",
            data=data,
            warnings=definition_warnings,
            info=[
                _info(
                    "taxonomy_options_loaded",
                    "Create-Optionen verwenden die kanonische Backend-Taxonomie.",
                    details={
                        "taxonomy_version": taxonomy_payload.get("taxonomy_version", ""),
                        "required_fields": list(REQUIRED_TAXONOMY_FIELDS),
                    },
                ),
                _info(
                    "vplib_uid_enabled",
                    "Neue Packages erhalten eine stabile vplib_uid im Manifest.",
                    field=VPLIB_UID_FIELD,
                ),
            ],
            http_status=200,
        )
    except Exception as exc:
        return _failure(
            "options_failed",
            "Create-Optionen konnten nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )


def get_create_context(payload: Any | None = None, **kwargs: Any) -> CreateResult:
    """Return definition-backed create context when Definition Catalog is available."""
    try:
        mapping = _coerce_payload_mapping(payload)
        mapping.update({key: value for key, value in kwargs.items() if value is not None})

        service = _get_definition_catalog_service()
        method = getattr(service, "get_create_context", None)

        if not callable(method):
            return CreateResult(
                ok=False,
                status="definition_context_unavailable",
                data={
                    "available": False,
                    "reason": "Definition service does not expose get_create_context.",
                },
                errors=[
                    _error(
                        "definition_context_unavailable",
                        "Definition-Catalog-Service stellt get_create_context nicht bereit.",
                        field="definitions",
                    )
                ],
                http_status=503,
            )

        result = _call_method_flex(
            method,
            {
                "user_id": mapping.get("user_id"),
                "domain": mapping.get("domain"),
                "category": mapping.get("category"),
                "subcategory": mapping.get("subcategory"),
                "object_kind": mapping.get("object_kind") or mapping.get("objectKind"),
                "family_profile_id": mapping.get("family_profile_id") or mapping.get("familyProfileId"),
                "variant_profile_id": mapping.get("variant_profile_id") or mapping.get("variantProfileId"),
                "include_catalog": _safe_bool(mapping.get("include_catalog"), default=False),
            },
        )

        payload_data = _service_result_payload(result)

        return CreateResult(
            ok=bool(payload_data.get("ok", True)),
            status=str(payload_data.get("status") or "ok"),
            data={
                "available": True,
                "definition_context": payload_data,
            },
            http_status=200 if bool(payload_data.get("ok", True)) else 422,
        )

    except Exception as exc:
        return _failure(
            "definition_context_failed",
            "Definition-backed Create Context konnte nicht erzeugt werden.",
            exc=exc,
            http_status=503,
        )


def build_draft(payload: Any) -> CreateResult:
    """Normalize user input into a stable draft object."""
    try:
        mapping = _coerce_payload_mapping(payload)
        draft, warnings = _normalize_draft(mapping)

        return CreateResult(
            ok=True,
            status="draft_ready",
            data={
                "vplib_uid": draft.vplib_uid,
                "draft": draft.to_dict(),
            },
            warnings=warnings,
            http_status=200,
        )
    except CreateDraftNormalizationError as exc:
        return CreateResult(
            ok=False,
            status="draft_invalid",
            data={},
            errors=exc.errors or [
                _error(
                    "draft_normalization_failed",
                    str(exc),
                    field="draft",
                )
            ],
            warnings=exc.warnings,
            http_status=422,
        )
    except Exception as exc:
        return _failure(
            "draft_failed",
            "Der Create-Draft konnte nicht normalisiert werden.",
            exc=exc,
            http_status=422,
        )


def validate_draft(payload: Any) -> CreateResult:
    """Validate a create draft and generated VPLIB documents."""
    warnings: list[CreateIssue] = []
    errors: list[CreateIssue] = []
    info: list[CreateIssue] = []

    try:
        mapping = _coerce_payload_mapping(payload)
        draft, normalize_warnings = _normalize_draft(mapping)
        warnings.extend(normalize_warnings)

        errors.extend(_validate_normalized_draft(draft))

        try:
            documents = build_package_documents(draft)
            errors.extend(_validate_package_documents(documents))
        except Exception as exc:
            errors.append(_exception_issue("document_build_failed", exc, field="documents"))

        valid = len(errors) == 0

        if valid:
            info.append(
                _info(
                    "draft_valid",
                    "Der Draft ist für ein einfaches VPLIB-Source-Package gültig.",
                )
            )

        return CreateResult(
            ok=valid,
            status="valid" if valid else "invalid",
            data={
                "valid": valid,
                "vplib_uid": draft.vplib_uid,
                "draft": draft.to_dict(),
                "summary": {
                    "vplib_uid": draft.vplib_uid,
                    "family_id": draft.family_id,
                    "package_id": draft.package_id,
                    "taxonomy_version": draft.taxonomy_version,
                    "classification_path": draft.classification_path,
                    "source_path": draft.source_path,
                    "object_kind": draft.object_kind,
                    "variant_count": len(draft.variants),
                    "variable_count": len(draft.variables),
                },
            },
            errors=errors,
            warnings=warnings,
            info=info,
            http_status=200 if valid else 422,
        )
    except CreateDraftNormalizationError as exc:
        uid = _extract_vplib_uid_from_any(payload)
        return CreateResult(
            ok=False,
            status="invalid",
            data={
                "valid": False,
                "vplib_uid": uid,
                "required_taxonomy_fields": list(REQUIRED_TAXONOMY_FIELDS),
            },
            errors=exc.errors or [
                _error(
                    "draft_normalization_failed",
                    str(exc),
                    field="draft",
                )
            ],
            warnings=exc.warnings,
            http_status=422,
        )
    except Exception as exc:
        return _failure(
            "validation_failed",
            "Die Draft-Validierung konnte nicht abgeschlossen werden.",
            exc=exc,
            http_status=422,
        )


def build_package_plan(payload: Any, *, include_documents: bool = True) -> CreateResult:
    """Build a scanner-compatible package plan without writing files."""
    try:
        validation = validate_draft(payload)
        if not validation.ok:
            return validation

        draft_data = validation.data.get("draft", {})
        draft, normalize_warnings = _normalize_draft(draft_data)
        documents = build_package_documents(draft)

        package_relative_path = draft.source_path
        source_root = get_source_root()
        target_dir = _safe_join(source_root, *draft.source_parts)

        file_entries = []
        directory_set: set[str] = set()

        for relative_path, content in documents.items():
            directory = str(Path(relative_path).parent).replace("\\", "/")
            if directory != ".":
                directory_set.add(directory)

            serialized = _serialize_document(relative_path, content)
            file_entries.append(
                {
                    "path": relative_path,
                    "directory": "" if directory == "." else directory,
                    "size_bytes": len(serialized.encode("utf-8")),
                    "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                }
            )

        data: dict[str, Any] = {
            "vplib_uid": draft.vplib_uid,
            "package_path": package_relative_path,
            "source_path": package_relative_path,
            "source_parts": list(draft.source_parts),
            "target_dir": str(target_dir),
            "source_root": str(source_root),
            "write_enabled": _env_bool(ENV_WRITE_ENABLED, default=False),
            "overwrite_enabled": _env_bool(ENV_OVERWRITE_ENABLED, default=False),
            "already_exists": target_dir.exists(),
            "draft": draft.to_dict(),
            "directories": sorted(directory_set),
            "files": sorted(file_entries, key=lambda item: item["path"]),
            "file_count": len(file_entries),
            "directory_count": len(directory_set),
        }

        if include_documents:
            data["documents"] = _json_safe(documents)

        warnings = list(validation.warnings) + normalize_warnings
        if target_dir.exists():
            warnings.append(
                _warning(
                    "target_exists",
                    "Der Zielordner existiert bereits. Speichern wird ohne expliziten Overwrite blockiert.",
                    field="target_dir",
                    details={
                        "target_dir": str(target_dir),
                        "vplib_uid": draft.vplib_uid,
                    },
                )
            )

        return CreateResult(
            ok=True,
            status="ok",
            data=data,
            warnings=warnings,
            info=validation.info,
            http_status=200,
        )
    except Exception as exc:
        return _failure(
            "package_plan_failed",
            "Der Package-Plan konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )


def build_vplib_archive(payload: Any) -> tuple[str, bytes, CreateResult]:
    """
    Build a .vplib archive in memory.

    Returns:
        (filename, archive_bytes, result)
    """
    try:
        plan = build_package_plan(payload, include_documents=True)
        if not plan.ok:
            return "invalid.vplib", b"", plan

        draft = plan.data.get("draft") or {}
        documents = plan.data.get("documents") or {}
        family_slug = _safe_segment(str(draft.get("family_slug") or "package"))
        uid = _extract_vplib_uid_from_any(plan.data) or _extract_vplib_uid_from_any(draft)
        filename = f"{family_slug}.vplib"

        archive_buffer = io.BytesIO()

        with zipfile.ZipFile(
            archive_buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for relative_path in sorted(documents.keys()):
                _assert_safe_relative_file(relative_path)
                content = documents[relative_path]
                archive.writestr(
                    relative_path,
                    _serialize_document(relative_path, content),
                )

        archive_bytes = archive_buffer.getvalue()

        result = CreateResult(
            ok=True,
            status="archive_ready",
            data={
                "vplib_uid": uid,
                "filename": filename,
                "size_bytes": len(archive_bytes),
                "sha256": hashlib.sha256(archive_bytes).hexdigest(),
                "package_path": plan.data.get("package_path", ""),
                "source_path": plan.data.get("source_path", ""),
                "file_count": plan.data.get("file_count", 0),
            },
            warnings=plan.warnings,
            info=plan.info,
            http_status=200,
        )

        return filename, archive_bytes, result
    except Exception as exc:
        result = _failure(
            "archive_failed",
            "Das VPLIB-Archiv konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )
        return "invalid.vplib", b"", result


def save_package(payload: Any, *, overwrite: bool | None = None) -> CreateResult:
    """
    Write a validated directory package into src/library/source.

    Writing is disabled by default. Enable explicitly with:
        VPLIB_CREATE_WRITE_ENABLED=true
    """
    try:
        uid = _extract_vplib_uid_from_any(payload)

        write_enabled = _env_bool(ENV_WRITE_ENABLED, default=False)
        if not write_enabled:
            if not uid:
                try:
                    mapping = _coerce_payload_mapping(payload)
                    uid = _ensure_payload_vplib_uid(mapping)
                except Exception:
                    uid = None

            return CreateResult(
                ok=False,
                status="write_disabled",
                data={
                    "vplib_uid": uid,
                    "write_enabled": False,
                    "required_env": ENV_WRITE_ENABLED,
                },
                errors=[
                    _error(
                        "write_disabled",
                        "Package-Schreiben ist deaktiviert. Setze VPLIB_CREATE_WRITE_ENABLED=true für lokale Schreibtests.",
                        field="write_enabled",
                    )
                ],
                http_status=403,
            )

        plan = build_package_plan(payload, include_documents=True)
        if not plan.ok:
            return plan

        draft = plan.data.get("draft") or {}
        documents = plan.data.get("documents") or {}
        source_parts = draft.get("source_parts") or []
        uid = _extract_vplib_uid_from_any(plan.data) or _extract_vplib_uid_from_any(draft)

        if not isinstance(source_parts, list) or len(source_parts) < 4:
            return CreateResult(
                ok=False,
                status="invalid_source_path",
                data={
                    "vplib_uid": uid,
                    "source_parts": source_parts,
                },
                errors=[
                    _error(
                        "invalid_source_parts",
                        "Source-Pfad muss domain/category/subcategory/family_slug enthalten.",
                        field="source_parts",
                        details={"source_parts": source_parts},
                    )
                ],
                http_status=422,
            )

        source_root = get_source_root()
        target_dir = _safe_join(source_root, *[str(part) for part in source_parts])

        if overwrite is None:
            overwrite = _env_bool(ENV_OVERWRITE_ENABLED, default=False)

        if target_dir.exists() and not overwrite:
            return CreateResult(
                ok=False,
                status="target_exists",
                data={
                    "vplib_uid": uid,
                    "target_dir": str(target_dir),
                    "overwrite_enabled": False,
                    "overwrite_env": ENV_OVERWRITE_ENABLED,
                },
                errors=[
                    _error(
                        "target_exists",
                        "Der Zielordner existiert bereits. Speichern wurde blockiert.",
                        field="target_dir",
                        details={
                            "target_dir": str(target_dir),
                            "vplib_uid": uid,
                        },
                    )
                ],
                warnings=plan.warnings,
                http_status=409,
            )

        source_root.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        written_files: list[dict[str, Any]] = []

        for relative_path, content in sorted(documents.items()):
            _assert_safe_relative_file(relative_path)
            target_file = _safe_join(target_dir, relative_path)
            serialized = _serialize_document(relative_path, content)

            if _is_blocked_executable_path(target_file):
                return CreateResult(
                    ok=False,
                    status="blocked_file_type",
                    data={
                        "vplib_uid": uid,
                        "blocked_path": str(target_file),
                    },
                    errors=[
                        _error(
                            "blocked_file_type",
                            "Ausführbare Dateitypen dürfen nicht in VPLIB-Packages geschrieben werden.",
                            field="relative_path",
                            details={"relative_path": relative_path},
                        )
                    ],
                    http_status=422,
                )

            target_file.parent.mkdir(parents=True, exist_ok=True)
            _write_text_atomic(target_file, serialized)

            written_files.append(
                {
                    "path": relative_path,
                    "absolute_path": str(target_file),
                    "size_bytes": len(serialized.encode("utf-8")),
                    "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                }
            )

        return CreateResult(
            ok=True,
            status="saved",
            data={
                "vplib_uid": uid,
                "family_id": draft.get("family_id", ""),
                "package_id": draft.get("package_id", ""),
                "package_path": plan.data.get("package_path", ""),
                "source_path": plan.data.get("source_path", ""),
                "source_parts": source_parts,
                "target_dir": str(target_dir),
                "source_root": str(source_root),
                "written_file_count": len(written_files),
                "written_files": written_files,
                "next_scan_route": "/api/v1/vplib/library/scan",
                "next_blocks_route": "/api/v1/vplib/library/blocks",
            },
            warnings=plan.warnings,
            info=plan.info
            + [
                _info(
                    "scan_required",
                    "Das Package wurde in den Source-Bereich geschrieben. Die Library-Sicht entsteht erst nach Scan/Validierung.",
                    details={"vplib_uid": uid},
                )
            ],
            http_status=200,
        )
    except Exception as exc:
        return _failure(
            "save_failed",
            "Das VPLIB-Package konnte nicht gespeichert werden.",
            exc=exc,
            http_status=500,
        )


def build_persistent_draft_payload(payload: Any) -> CreateResult:
    """Build CreativeLibraryDraftService-compatible payload from create input."""
    try:
        validation = validate_draft(payload)
        if not validation.ok:
            return validation

        draft = validation.data.get("draft") or {}
        documents = build_package_documents(draft)

        draft_payload = _build_draft_service_payload(
            draft=draft,
            documents=documents,
            original_payload=_coerce_payload_mapping(payload),
            validation=validation,
        )

        return CreateResult(
            ok=True,
            status="persistent_draft_payload_ready",
            data={
                "vplib_uid": _extract_vplib_uid_from_any(draft_payload),
                "draft_service_payload": draft_payload,
                "draft": draft,
            },
            warnings=validation.warnings,
            info=validation.info
            + [
                _info(
                    "persistent_draft_payload_ready",
                    "Payload ist kompatibel mit CreativeLibraryDraftService.create_draft().",
                )
            ],
            http_status=200,
        )
    except Exception as exc:
        return _failure(
            "persistent_draft_payload_failed",
            "Persistent-Draft-Payload konnte nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )


def build_publish_bundle_from_create_payload(payload: Any) -> CreateResult:
    """Build publish-bundle-like payload from simple create input."""
    try:
        persistent_payload_result = build_persistent_draft_payload(payload)
        if not persistent_payload_result.ok:
            return persistent_payload_result

        draft_service_payload = persistent_payload_result.data.get("draft_service_payload") or {}
        manifest = draft_service_payload.get("manifest_payload") or {}
        family = draft_service_payload.get("family_payload") or {}
        classification = draft_service_payload.get("classification_payload") or {}
        modules = draft_service_payload.get("modules_payload") or {}
        documents = draft_service_payload.get("documents") or []
        variants = draft_service_payload.get("variants") or []

        publish_payload = {
            "schema_version": LIBRARY_CREATE_SERVICE_VERSION,
            "source": LIBRARY_CREATE_SERVICE_COMPONENT,
            "vplib_uid": draft_service_payload.get("vplib_uid"),
            "family_id": draft_service_payload.get("family_id"),
            "package_id": draft_service_payload.get("package_id"),
            "title": draft_service_payload.get("title"),
            "description": draft_service_payload.get("description"),
            "family_payload": family,
            "classification_payload": classification,
            "manifest_payload": manifest,
            "modules_payload": modules,
            "generator_payload": draft_service_payload.get("generator_payload") or {},
            "variants": variants,
            "documents": documents,
            "assets": [],
            "document_bundle": {
                "manifest": manifest,
                "family": family,
                "classification": classification,
                "modules": modules,
                "variants": variants,
                "documents": documents,
                "assets": [],
            },
        }

        return CreateResult(
            ok=True,
            status="publish_bundle_ready",
            data={
                "vplib_uid": _extract_vplib_uid_from_any(publish_payload),
                "publish": publish_payload,
            },
            warnings=persistent_payload_result.warnings,
            info=persistent_payload_result.info,
            http_status=200,
        )
    except Exception as exc:
        return _failure(
            "publish_bundle_failed",
            "Publish-Bundle konnte aus Create-Payload nicht erzeugt werden.",
            exc=exc,
            http_status=500,
        )


def build_package_documents(draft: NormalizedCreateDraft | Mapping[str, Any]) -> dict[str, Any]:
    """
    Build all phase-1 package documents.

    Accepts either a NormalizedCreateDraft or its dict representation.
    """
    normalized = _ensure_normalized_draft(draft)

    family_id = normalized.family_id
    package_id = normalized.package_id
    classification_path = normalized.classification_path
    vplib_uid = normalized.vplib_uid

    documents: dict[str, Any] = {
        "vplib.manifest.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "package_format": "vplib",
            "vplib_uid": vplib_uid,
            "package_id": package_id,
            "family_id": family_id,
            "family_slug": normalized.family_slug,
            "family_name": normalized.family_name,
            "package_version": normalized.package_version,
            "object_kind": normalized.object_kind,
            "taxonomy_version": normalized.taxonomy_version,
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "classification": {
                "domain": normalized.domain,
                "category": normalized.category,
                "subcategory": normalized.subcategory,
                "classification_path": classification_path,
                "labels": dict(normalized.taxonomy_labels),
                "object_kind": normalized.object_kind,
            },
            "classification_path": classification_path,
            "source_path": normalized.source_path,
            "default_variant_id": normalized.default_variant_id,
            "created_at": normalized.created_at,
            "created_by": LIBRARY_CREATE_SERVICE_COMPONENT,
            "generator": {
                "component": LIBRARY_CREATE_SERVICE_COMPONENT,
                "version": LIBRARY_CREATE_SERVICE_VERSION,
                "mode": "simple_create",
            },
        },
        "vplib.modules.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "modules": {
                "family": True,
                "variants": True,
                "editor": True,
                "render": True,
                "physical": True,
                "material": bool(normalized.material_classes),
                "calculation": bool(normalized.variables),
                "analysis": False,
                "dynamic": normalized.object_kind == "adaptive_system",
                "manufacturer": True,
                "docs": True,
                "definitions": bool(normalized.source.get("definition_context")),
                "tests": False,
            },
            "active_modules": [
                module_name
                for module_name, enabled in {
                    "family": True,
                    "variants": True,
                    "editor": True,
                    "render": True,
                    "physical": True,
                    "material": bool(normalized.material_classes),
                    "calculation": bool(normalized.variables),
                    "analysis": False,
                    "dynamic": normalized.object_kind == "adaptive_system",
                    "manufacturer": True,
                    "docs": True,
                    "definitions": bool(normalized.source.get("definition_context")),
                    "tests": False,
                }.items()
                if enabled
            ],
            "required_documents": [
                "vplib.manifest.json",
                "vplib.modules.json",
                "family/identity.json",
                "family/classification.json",
                "variants/index.json",
                "variants/default.json",
                "editor/inventory.json",
                "editor/placement.json",
                "manufacturer/contract.json",
            ],
        },
        "family/identity.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "family_id": family_id,
            "slug": normalized.family_slug,
            "label": normalized.family_name,
            "description": normalized.family_description,
            "status": "draft",
            "language": "de",
        },
        "family/classification.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "taxonomy_version": normalized.taxonomy_version,
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "classification_path": classification_path,
            "source_path": normalized.source_path,
            "labels": dict(normalized.taxonomy_labels),
            "object_kind": normalized.object_kind,
        },
        "variants/index.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "default_variant_id": normalized.default_variant_id,
            "variant_count": len(normalized.variants),
            "variants": [
                {
                    "variant_id": str(variant.get("variant_id") or ""),
                    "label": str(variant.get("label") or ""),
                    "description": str(variant.get("description") or ""),
                    "is_default": bool(variant.get("variant_id") == normalized.default_variant_id),
                }
                for variant in normalized.variants
            ],
        },
        "variants/default.json": _build_default_variant_document(normalized),
        "editor/inventory.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "enabled": True,
            "visible": True,
            "vplib_uid": vplib_uid,
            "family_id": family_id,
            "default_variant_id": normalized.default_variant_id,
            "label": normalized.family_name,
            "description": normalized.family_description,
            "taxonomy_version": normalized.taxonomy_version,
            "domain": normalized.domain,
            "category": normalized.category,
            "subcategory": normalized.subcategory,
            "classification_path": classification_path,
            "source_path": normalized.source_path,
            "labels": dict(normalized.taxonomy_labels),
            "object_kind": normalized.object_kind,
            "tags": [],
        },
        "editor/placement.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "placement_mode": _default_placement_mode(normalized.object_kind),
            "snap_mode": "grid",
            "rotation_mode": "orthogonal",
            "scale_policy": "fixed",
            "editor_block": {
                "placement_truth": "editor_block",
                "cells": {
                    "x": normalized.editor_cells_x,
                    "y": normalized.editor_cells_y,
                    "z": normalized.editor_cells_z,
                },
                "cell_size": {
                    "x": normalized.editor_cell_size_x,
                    "y": normalized.editor_cell_size_y,
                    "z": normalized.editor_cell_size_z,
                    "unit": normalized.geometry_unit,
                },
            },
            "anchors": [
                {"anchor_id": "center", "type": "center", "enabled": True},
                {"anchor_id": "bottom_center", "type": "bottom_center", "enabled": True},
            ],
            "host_rules": _default_host_rules(normalized),
        },
        "render/render_variants.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "default_render_variant_id": "default",
            "render_variants": [
                {
                    "render_variant_id": "default",
                    "mode": "primitive",
                    "primitive_shape": normalized.primitive_shape,
                    "label": "Default primitive preview",
                    "source": "generated",
                }
            ],
        },
        "physical/base.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "family_id": family_id,
            "object_kind": normalized.object_kind,
            "unit": normalized.geometry_unit,
            "physical_model": "simple_box",
            "material_classes": normalized.material_classes,
        },
        "physical/dimensions.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "width": normalized.geometry_width,
            "height": normalized.geometry_height,
            "depth": normalized.geometry_depth,
            "unit": normalized.geometry_unit,
            "source": "create_form",
        },
        "physical/collision.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "collision_enabled": True,
            "type": "box",
            "width": normalized.geometry_width,
            "height": normalized.geometry_height,
            "depth": normalized.geometry_depth,
            "unit": normalized.geometry_unit,
        },
        "manufacturer/contract.json": {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "manufacturer_products_allowed": False,
            "overlay_level": "none",
            "allowed_overlay_levels": [],
            "required_fields": [],
            "override_slots": [],
            "notes": "Generated by simple create flow. Manufacturer overlays are intentionally disabled in phase 1.",
        },
        "docs/notes.md": _build_notes_markdown(normalized),
    }

    if normalized.material_classes:
        documents["material/base.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "material_classes": normalized.material_classes,
            "primary_material_class": normalized.material_class,
            "source": "create_form",
        }

    if normalized.variables:
        documents["calculation/variables.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "variables": normalized.variables,
        }
        documents["calculation/formulas.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "formulas": [],
            "executable": False,
        }
        documents["calculation/quantities.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "quantities": [],
        }
        documents["calculation/measure_logic.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "mode": "simple_dimensions",
            "unit": normalized.geometry_unit,
            "rules": [],
        }

    if normalized.object_kind == "adaptive_system":
        documents["dynamic/context_rules.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "enabled": False,
            "rules": [],
            "placeholder": True,
        }
        documents["dynamic/bindings.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "bindings": [],
            "placeholder": True,
        }
        documents["dynamic/generator.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "generator_type": "declarative_placeholder",
            "enabled": False,
            "parameters": {},
        }

    if normalized.source.get("definition_context"):
        documents["definitions/create_context.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "source": "definition_catalog_service",
            "context": _json_safe(normalized.source.get("definition_context")),
        }

    for variant in normalized.variants:
        variant_id = str(variant.get("variant_id") or "").strip()
        if not variant_id or variant_id == "default":
            continue
        documents[f"variants/{variant_id}.json"] = {
            "schema_version": DEFAULT_SCHEMA_VERSION,
            "variant_id": variant_id,
            "label": str(variant.get("label") or variant_id),
            "description": str(variant.get("description") or ""),
            "kind": str(variant.get("kind") or "other"),
            "overrides": _json_safe(variant.get("overrides") or {}),
        }

    return documents


# Backward-compatible public aliases expected by route services/tests.
health = get_service_health
get_options = get_create_options
create_draft = build_draft
package_plan = build_package_plan


# ---------------------------------------------------------------------------
# Source root
# ---------------------------------------------------------------------------

def get_source_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """
    Return the configured library source root.

    Priority:
        1. explicit argument
        2. VECTOPLAN_LIBRARY_SOURCE_ROOT
        3. VPLIB_CREATE_SOURCE_ROOT
        4. src/library/source relative to this file
    """
    if explicit:
        return Path(explicit).expanduser().resolve()

    env_primary = os.getenv(ENV_SOURCE_ROOT_PRIMARY, "").strip()
    if env_primary:
        return Path(env_primary).expanduser().resolve()

    env_secondary = os.getenv(ENV_SOURCE_ROOT_SECONDARY, "").strip()
    if env_secondary:
        return Path(env_secondary).expanduser().resolve()

    try:
        current_file = Path(__file__).resolve()
        return (current_file.parents[1] / "source").resolve()
    except Exception:
        return (Path.cwd() / "src" / "library" / "source").resolve()


def _utc_now() -> str:
    """Return a stable UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_draft(payload: Mapping[str, Any]) -> tuple[NormalizedCreateDraft, list[CreateIssue]]:
    warnings: list[CreateIssue] = []
    now = _utc_now()

    payload = _maybe_apply_definition_context_defaults(payload, warnings=warnings)

    vplib_uid = _ensure_payload_vplib_uid(payload)

    family_name = _clean_text(
        _first_value(
            payload,
            [
                "family_name",
                "name",
                "label",
                ("identity", "family_name"),
                ("identity", "name"),
                ("family", "label"),
                ("family", "name"),
            ],
            "",
        ),
        max_length=160,
    )

    family_description = _clean_text(
        _first_value(
            payload,
            [
                "family_description",
                "description",
                ("identity", "family_description"),
                ("identity", "description"),
                ("family", "description"),
            ],
            "",
        ),
        max_length=MAX_TEXT_LENGTH,
    )

    family_slug_raw = _first_value(
        payload,
        [
            "family_slug",
            "slug",
            ("identity", "family_slug"),
            ("identity", "slug"),
            ("family", "slug"),
        ],
        "",
    )
    family_slug = _safe_segment(
        _slugify(str(family_slug_raw or family_name or "unnamed"))[:MAX_SLUG_LENGTH]
    )

    domain = _taxonomy_normalize_slug(
        _first_value(
            payload,
            ["domain", ("taxonomy", "domain"), ("classification", "domain")],
            "",
        ),
        default="",
    )
    category = _taxonomy_normalize_slug(
        _first_value(
            payload,
            ["category", ("taxonomy", "category"), ("classification", "category")],
            "",
        ),
        default="",
    )
    subcategory = _taxonomy_normalize_slug(
        _first_value(
            payload,
            ["subcategory", ("taxonomy", "subcategory"), ("classification", "subcategory")],
            "",
        ),
        default="",
    )

    object_kind = _normalize_object_kind(
        _first_value(
            payload,
            [
                "object_kind",
                "object_class",
                ("family", "object_kind"),
                ("family", "object_class"),
                ("classification", "object_kind"),
            ],
            DEFAULT_OBJECT_KIND,
        )
    )
    if object_kind not in ALLOWED_OBJECT_KINDS:
        warnings.append(
            _warning(
                "unknown_object_kind_fallback",
                f"Unbekannte Objektart wurde auf {DEFAULT_OBJECT_KIND} zurückgesetzt.",
                field="object_kind",
                details={"received": object_kind},
            )
        )
        object_kind = DEFAULT_OBJECT_KIND

    taxonomy_reference, taxonomy_warnings = _build_taxonomy_reference(
        domain=domain,
        category=category,
        subcategory=subcategory,
        family_slug=family_slug,
        object_kind=object_kind,
    )
    warnings.extend(taxonomy_warnings)

    primitive_shape = _normalize_slug_token(
        _first_value(
            payload,
            [
                "primitive_shape",
                "shape",
                ("geometry", "primitive_shape"),
                ("geometry", "shape"),
            ],
            DEFAULT_PRIMITIVE_SHAPE,
        )
    )
    if primitive_shape not in ALLOWED_PRIMITIVE_SHAPES:
        warnings.append(
            _warning(
                "unknown_primitive_shape_fallback",
                f"Unbekannte Form wurde auf {DEFAULT_PRIMITIVE_SHAPE} zurückgesetzt.",
                field="primitive_shape",
                details={"received": primitive_shape},
            )
        )
        primitive_shape = DEFAULT_PRIMITIVE_SHAPE

    geometry_width = _safe_float(
        _first_value(
            payload,
            [
                "geometry_width",
                "width",
                ("geometry", "width"),
                ("geometry", "dimensions", "width"),
                ("dimensions", "width"),
            ],
            1.0,
        ),
        default=1.0,
        minimum=0.0001,
        maximum=1_000_000.0,
    )
    geometry_height = _safe_float(
        _first_value(
            payload,
            [
                "geometry_height",
                "height",
                ("geometry", "height"),
                ("geometry", "dimensions", "height"),
                ("dimensions", "height"),
            ],
            1.0,
        ),
        default=1.0,
        minimum=0.0001,
        maximum=1_000_000.0,
    )
    geometry_depth = _safe_float(
        _first_value(
            payload,
            [
                "geometry_depth",
                "depth",
                ("geometry", "depth"),
                ("geometry", "dimensions", "depth"),
                ("dimensions", "depth"),
            ],
            1.0,
        ),
        default=1.0,
        minimum=0.0001,
        maximum=1_000_000.0,
    )

    geometry_unit = _normalize_unit(
        _first_value(
            payload,
            [
                "geometry_unit",
                "unit",
                ("geometry", "unit"),
                ("geometry", "dimensions", "unit"),
                ("dimensions", "unit"),
            ],
            DEFAULT_UNIT,
        )
    )
    if geometry_unit not in ALLOWED_UNITS:
        warnings.append(
            _warning(
                "unknown_unit_fallback",
                f"Unbekannte Einheit wurde auf {DEFAULT_UNIT} zurückgesetzt.",
                field="geometry_unit",
                details={"received": geometry_unit},
            )
        )
        geometry_unit = DEFAULT_UNIT

    block_count_locked = object_kind in {"cell_block", "adaptive_system"}

    editor_cells_x = _safe_int(
        _first_value(payload, ["editor_cells_x", ("editor_block", "cells", "x")], 1),
        default=1,
        minimum=1,
        maximum=1000,
    )
    editor_cells_y = _safe_int(
        _first_value(payload, ["editor_cells_y", ("editor_block", "cells", "y")], 1),
        default=1,
        minimum=1,
        maximum=1000,
    )
    editor_cells_z = _safe_int(
        _first_value(payload, ["editor_cells_z", ("editor_block", "cells", "z")], 1),
        default=1,
        minimum=1,
        maximum=1000,
    )

    if block_count_locked:
        editor_cells_x = 1
        editor_cells_y = 1
        editor_cells_z = 1

    editor_cell_size_x = _safe_float(
        _first_value(payload, ["editor_cell_size_x", ("editor_block", "cell_size", "x")], 1.0),
        default=1.0,
        minimum=0.0001,
        maximum=10_000.0,
    )
    editor_cell_size_y = _safe_float(
        _first_value(payload, ["editor_cell_size_y", ("editor_block", "cell_size", "y")], 1.0),
        default=1.0,
        minimum=0.0001,
        maximum=10_000.0,
    )
    editor_cell_size_z = _safe_float(
        _first_value(payload, ["editor_cell_size_z", ("editor_block", "cell_size", "z")], 1.0),
        default=1.0,
        minimum=0.0001,
        maximum=10_000.0,
    )

    material_class_raw = _first_value(
        payload,
        [
            "material_class",
            ("technical", "material_class"),
            ("technical", "profile", "material_class"),
            ("technical_profile", "material_class"),
        ],
        "",
    )
    material_classes_raw = _first_value(
        payload,
        [
            "material_classes",
            ("technical", "material_classes"),
            ("technical", "profile", "material_classes"),
            ("technical_profile", "material_classes"),
        ],
        "",
    )
    material_classes = _normalize_material_classes(material_classes_raw)
    material_class = _normalize_slug_token(material_class_raw)
    if material_class and material_class not in material_classes:
        material_classes.insert(0, material_class)
    if not material_class and material_classes:
        material_class = material_classes[0]

    variants, variant_warnings = _normalize_variants(payload)
    warnings.extend(variant_warnings)

    default_variant_id = _clean_text(
        _first_value(
            payload,
            ["default_variant_id", "defaultVariantId", "default_variant", ("variants", "default_variant_id")],
            "",
        ),
        max_length=160,
    )

    if not default_variant_id:
        default_variant_id = "default"
        for variant in variants:
            if variant.get("is_default"):
                default_variant_id = str(variant.get("variant_id") or "default")
                break

    variables, variable_warnings = _normalize_variables(payload)
    warnings.extend(variable_warnings)

    labels = _extract_taxonomy_labels(taxonomy_reference)
    source_metadata = {
        "mode": "create_form",
        "taxonomy_source": "backend_taxonomy_service",
        "vplib_uid_source": "payload_or_generated",
    }

    definition_context = payload.get("definition_context")
    if isinstance(definition_context, Mapping):
        source_metadata["definition_context"] = _json_safe(dict(definition_context))

    return (
        NormalizedCreateDraft(
            vplib_uid=vplib_uid,
            family_name=family_name,
            family_slug=family_slug,
            family_description=family_description,
            domain=_reference_value(taxonomy_reference, "domain", fallback=domain),
            category=_reference_value(taxonomy_reference, "category", fallback=category),
            subcategory=_reference_value(taxonomy_reference, "subcategory", fallback=subcategory),
            object_kind=object_kind,
            taxonomy_version=_reference_attr(taxonomy_reference, "taxonomy_version", fallback=""),
            classification_path=_reference_attr(taxonomy_reference, "classification_path", fallback=f"{domain}/{category}/{subcategory}"),
            taxonomy_labels=labels,
            source_parts=tuple(_reference_attr(taxonomy_reference, "source_parts", fallback=[domain, category, subcategory, family_slug])),
            source_path=_reference_attr(taxonomy_reference, "source_path", fallback=f"{domain}/{category}/{subcategory}/{family_slug}"),
            family_id=_reference_attr(taxonomy_reference, "family_id", fallback=f"vp.{domain}.{category}.{subcategory}.{family_slug}"),
            package_id=_reference_attr(taxonomy_reference, "package_id", fallback=f"vplib.vp.{domain}.{category}.{subcategory}.{family_slug}"),
            package_version=DEFAULT_PACKAGE_VERSION,
            default_variant_id=default_variant_id,
            variants=variants,
            primitive_shape=primitive_shape,
            geometry_width=geometry_width,
            geometry_height=geometry_height,
            geometry_depth=geometry_depth,
            geometry_unit=geometry_unit,
            editor_cells_x=editor_cells_x,
            editor_cells_y=editor_cells_y,
            editor_cells_z=editor_cells_z,
            editor_cell_size_x=editor_cell_size_x,
            editor_cell_size_y=editor_cell_size_y,
            editor_cell_size_z=editor_cell_size_z,
            material_class=material_class,
            material_classes=material_classes,
            variables=variables,
            created_at=now,
            source=source_metadata,
        ),
        warnings,
    )


def _maybe_apply_definition_context_defaults(
    payload: Mapping[str, Any],
    *,
    warnings: list[CreateIssue],
) -> dict[str, Any]:
    """Optionally merges Definition Catalog create context into payload.

    This is opt-in to preserve the no-DB-direct/no-service-side-surprise behavior.
    """
    mapping = dict(payload)

    use_context = (
        _safe_bool(mapping.get("use_definition_context"), default=False)
        or _safe_bool(mapping.get("use_definitions"), default=False)
        or _safe_bool(mapping.get("definition_context_enabled"), default=False)
    )

    if not use_context:
        return mapping

    try:
        context_result = get_create_context(mapping)
        if not context_result.ok:
            warnings.append(
                _warning(
                    "definition_context_not_applied",
                    "Definition Context konnte nicht angewendet werden.",
                    field="definition_context",
                    details=context_result.to_dict(),
                )
            )
            return mapping

        context_payload = context_result.data.get("definition_context") or {}
        context_payload = _service_result_payload(context_payload)
        inner_payload = context_payload.get("payload") if isinstance(context_payload.get("payload"), Mapping) else context_payload

        if isinstance(inner_payload, Mapping):
            mapping["definition_context"] = dict(inner_payload)
            defaults = _extract_create_context_defaults(inner_payload)
            merged = dict(defaults)
            merged.update(mapping)
            return merged

    except Exception as exc:
        warnings.append(
            _exception_issue(
                "definition_context_failed",
                exc,
                field="definition_context",
                fallback_message="Definition Context konnte nicht geladen werden.",
            )
        )

    return mapping


def _extract_create_context_defaults(context_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extracts safe default values from a Definition Catalog create context."""
    payload = dict(context_payload)
    defaults: dict[str, Any] = {}

    for key in ("family_profile", "variant_profile", "resolved_family_profile", "resolved_variant_profile"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            for candidate in ("object_kind", "primitive_shape", "material_class", "material_classes"):
                if candidate in value and candidate not in defaults:
                    defaults[candidate] = value[candidate]

    upload_constraints = payload.get("upload_constraints")
    if isinstance(upload_constraints, Mapping):
        defaults.setdefault("upload_constraints", upload_constraints)

    return defaults


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

def _is_taxonomy_available() -> bool:
    try:
        module = _load_taxonomy_module()
        return getattr(module, "get_default_taxonomy_service", None) is not None
    except Exception:
        return False


def _get_taxonomy_service() -> Any:
    if not _is_taxonomy_available():
        raise RuntimeError("Taxonomie-Service ist nicht verfügbar.")

    module = _load_taxonomy_module()
    factory = getattr(module, "get_default_taxonomy_service", None)
    if not callable(factory):
        raise RuntimeError("Taxonomie-Service-Factory ist nicht verfügbar.")

    return factory()


def _call_taxonomy_health() -> dict[str, Any]:
    service = _get_taxonomy_service()

    for call in (
        lambda: service.health(force_reload=False, include_registry_state=False),
        lambda: service.health(),
        lambda: service.get_health(),
    ):
        try:
            result = call()
            if isinstance(result, Mapping):
                return dict(result)
        except Exception:
            continue

    return {"ok": True, "healthy": True}


def _get_taxonomy_create_options_payload() -> dict[str, Any]:
    service = _get_taxonomy_service()

    for method_name in (
        "get_create_options_payload",
        "get_create_options",
        "create_options",
    ):
        method = getattr(service, method_name, None)
        if not callable(method):
            continue

        result = method()
        payload = _service_result_payload(result)

        if isinstance(payload.get("data"), Mapping):
            return dict(payload["data"])

        if isinstance(payload.get("payload"), Mapping):
            return dict(payload["payload"])

        return payload

    raise RuntimeError("Taxonomie-Service stellt keine Create-Options-Methode bereit.")


def _build_taxonomy_reference(
    *,
    domain: str,
    category: str,
    subcategory: str,
    family_slug: str,
    object_kind: str,
) -> tuple[Any, list[CreateIssue]]:
    if not _is_taxonomy_available():
        raise CreateDraftNormalizationError(
            "Taxonomie-Service ist nicht verfügbar.",
            errors=[
                _exception_issue(
                    "taxonomy_service_unavailable",
                    _get_taxonomy_import_error(),
                    field="library.taxonomy",
                    fallback_message="Taxonomie-Service ist nicht verfügbar.",
                )
            ],
        )

    service = _get_taxonomy_service()

    try:
        if hasattr(service, "build_family_reference") and callable(service.build_family_reference):
            result = service.build_family_reference(
                domain=domain,
                category=category,
                subcategory=subcategory,
                family_slug=family_slug,
                object_kind=object_kind,
            )
        elif hasattr(service, "build_reference") and callable(service.build_reference):
            result = service.build_reference(
                {
                    "domain": domain,
                    "category": category,
                    "subcategory": subcategory,
                    "family_slug": family_slug,
                    "object_kind": object_kind,
                }
            )
        else:
            raise RuntimeError("Taxonomie-Service stellt keine build_family_reference/build_reference-Methode bereit.")
    except Exception as exc:
        raise CreateDraftNormalizationError(
            "Taxonomie-Referenz konnte nicht aufgebaut werden.",
            errors=[
                _exception_issue(
                    "taxonomy_reference_failed",
                    exc,
                    field="taxonomy",
                )
            ],
        ) from exc

    issues = _taxonomy_issues_to_create_issues(result)
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity != "error"]

    valid = bool(getattr(result, "valid", True))
    if isinstance(result, Mapping):
        valid = bool(result.get("valid", result.get("ok", True)))

    if errors or not valid:
        if not errors:
            errors.append(
                _error(
                    "taxonomy_invalid",
                    "Taxonomie-Auswahl ist ungültig.",
                    field="taxonomy",
                    details=result.to_dict() if hasattr(result, "to_dict") else _json_safe(result),
                )
            )
        raise CreateDraftNormalizationError(
            "Taxonomie-Auswahl ist ungültig.",
            errors=errors,
            warnings=warnings,
        )

    return result, warnings


def _reference_attr(reference: Any, name: str, *, fallback: Any = None) -> Any:
    try:
        value = getattr(reference, name)
        if value is not None and value != "":
            return value
    except Exception:
        pass

    try:
        payload = reference.to_dict() if hasattr(reference, "to_dict") else reference
        if isinstance(payload, Mapping):
            value = payload.get(name)
            if value is not None and value != "":
                return value
    except Exception:
        pass

    return fallback


def _reference_value(reference: Any, key: str, *, fallback: str = "") -> str:
    try:
        selection = getattr(reference, "selection", None)
        if selection is not None:
            value = getattr(selection, key, None)
            if value:
                return str(value)
    except Exception:
        pass

    try:
        payload = reference.to_dict() if hasattr(reference, "to_dict") else reference
        if isinstance(payload, Mapping):
            selection_payload = payload.get("selection")
            if isinstance(selection_payload, Mapping) and selection_payload.get(key):
                return str(selection_payload[key])
            if payload.get(key):
                return str(payload[key])
    except Exception:
        pass

    return fallback


def _extract_taxonomy_labels(reference: Any) -> dict[str, str]:
    try:
        resolved = getattr(reference, "resolved", None)
        selection = getattr(reference, "selection", None)
        if resolved is not None and selection is not None:
            return {
                "domain": str(getattr(getattr(resolved, "domain", None), "label", getattr(selection, "domain", ""))),
                "category": str(getattr(getattr(resolved, "category", None), "label", getattr(selection, "category", ""))),
                "subcategory": str(getattr(getattr(resolved, "subcategory", None), "label", getattr(selection, "subcategory", ""))),
            }
    except Exception:
        pass

    try:
        payload = reference.to_dict() if hasattr(reference, "to_dict") else reference
        if isinstance(payload, Mapping):
            resolved_payload = payload.get("resolved", {}) if isinstance(payload.get("resolved"), Mapping) else {}
            path_labels = resolved_payload.get("path_labels", [])
            if isinstance(path_labels, list) and len(path_labels) >= 3:
                return {
                    "domain": str(path_labels[0]),
                    "category": str(path_labels[1]),
                    "subcategory": str(path_labels[2]),
                }

            selection_payload = payload.get("selection", {}) if isinstance(payload.get("selection"), Mapping) else {}
            return {
                "domain": str(selection_payload.get("domain") or payload.get("domain") or ""),
                "category": str(selection_payload.get("category") or payload.get("category") or ""),
                "subcategory": str(selection_payload.get("subcategory") or payload.get("subcategory") or ""),
            }
    except Exception:
        pass

    return {
        "domain": _reference_value(reference, "domain"),
        "category": _reference_value(reference, "category"),
        "subcategory": _reference_value(reference, "subcategory"),
    }


def _taxonomy_issues_to_create_issues(validation_result: Any) -> list[CreateIssue]:
    issues: list[CreateIssue] = []

    if validation_result is None:
        return issues

    if isinstance(validation_result, Mapping):
        raw_issues = validation_result.get("issues") or validation_result.get("errors") or []
    elif isinstance(validation_result, Iterable) and not isinstance(validation_result, (str, bytes, bytearray)):
        raw_issues = list(validation_result)
    else:
        raw_issues = getattr(validation_result, "issues", [])

    try:
        for issue in list(raw_issues or []):
            issues.append(_taxonomy_issue_to_create_issue(issue))
    except Exception:
        return issues

    return issues


def _taxonomy_issue_to_create_issue(issue: Any) -> CreateIssue:
    try:
        payload = issue.to_dict() if hasattr(issue, "to_dict") else issue
        if isinstance(payload, Mapping):
            return CreateIssue(
                severity=str(payload.get("severity") or "error"),
                code=str(payload.get("code") or "taxonomy_issue"),
                message=str(payload.get("message") or "Taxonomie-Problem."),
                field=str(payload.get("field") or "taxonomy"),
                details=dict(payload.get("details") or {}),
            )
    except Exception:
        pass

    return _error(
        "taxonomy_issue",
        str(issue),
        field="taxonomy",
    )


# ---------------------------------------------------------------------------
# Definition catalog adapter
# ---------------------------------------------------------------------------

def _get_definition_catalog_service() -> Any:
    module = _load_definition_catalog_service_module()

    factory = getattr(module, "create_library_definition_catalog_service", None)
    if callable(factory):
        return factory()

    service_class = getattr(module, "LibraryDefinitionCatalogService", None)
    if service_class is not None:
        return service_class()

    raise RuntimeError("LibraryDefinitionCatalogService ist nicht verfügbar.")


def _get_definition_catalog_service_health() -> dict[str, Any]:
    try:
        service = _get_definition_catalog_service()

        if hasattr(service, "get_health") and callable(service.get_health):
            health = service.get_health()
            return {
                "available": True,
                "health": _service_result_payload(health),
            }

        return {
            "available": True,
            "health": {"ok": True},
        }
    except Exception as exc:
        return {
            "available": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def _get_definition_create_options_payload(*, user_id: Any = 1) -> dict[str, Any]:
    try:
        service = _get_definition_catalog_service()

        for method_name in (
            "get_create_options",
            "get_create_context_options",
            "get_current_catalog",
        ):
            method = getattr(service, method_name, None)
            if not callable(method):
                continue

            try:
                result = _call_method_flex(method, {"user_id": user_id})
            except Exception:
                result = method()

            payload = _service_result_payload(result)

            return {
                "available": True,
                "method": method_name,
                "payload": payload,
            }

        return {
            "available": False,
            "error": "Definition service exposes no known create-options method.",
        }
    except Exception as exc:
        return {
            "available": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def _merge_definition_options_into_create_options(
    data: dict[str, Any],
    definition_options: Mapping[str, Any],
) -> dict[str, Any]:
    if not definition_options.get("available"):
        return data

    payload = definition_options.get("payload")
    if not isinstance(payload, Mapping):
        return data

    source_payload = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else payload

    if not isinstance(source_payload, Mapping):
        return data

    for source_key, target_key in (
        ("object_kinds", "object_kinds"),
        ("units", "units"),
        ("materials", "material_classes"),
        ("material_classes", "material_classes"),
    ):
        value = source_payload.get(source_key)
        if isinstance(value, list) and value:
            data[target_key] = _definition_items_to_options(value, existing=data.get(target_key))

    data["definition_catalog"] = source_payload
    return data


def _definition_items_to_options(value: Iterable[Any], *, existing: Any = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in value:
        if isinstance(item, Mapping):
            option = {
                "value": item.get("value") or item.get("key") or item.get("id") or item.get("slug"),
                "id": item.get("id") or item.get("key") or item.get("value") or item.get("slug"),
                "label": item.get("label") or item.get("name") or item.get("key") or item.get("value"),
                "description": item.get("description") or "",
                "enabled": not bool(item.get("disabled", False)),
                "default": bool(item.get("default", False)),
            }
        else:
            option = {
                "value": str(item),
                "id": str(item),
                "label": str(item),
                "description": "",
                "enabled": True,
            }

        key = str(option.get("value") or option.get("id") or "").strip()
        if not key or key in seen:
            continue

        seen.add(key)
        result.append(option)

    if result:
        return result

    return list(existing or [])


def _call_method_flex(method: Any, kwargs: Mapping[str, Any]) -> Any:
    """Call service method with kwargs, dropping unsupported args if necessary."""
    cleaned = {
        key: value
        for key, value in kwargs.items()
        if value is not None
    }

    try:
        return method(**cleaned)
    except TypeError:
        try:
            return method(cleaned)
        except TypeError:
            return method()


def _service_result_payload(result: Any) -> dict[str, Any]:
    if result is None:
        return {}

    if hasattr(result, "to_dict") and callable(result.to_dict):
        try:
            payload = result.to_dict(include_http_status=True)
        except TypeError:
            payload = result.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)

    if isinstance(result, Mapping):
        return dict(result)

    return {"value": _json_safe(result)}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _ensure_normalized_draft(draft: NormalizedCreateDraft | Mapping[str, Any]) -> NormalizedCreateDraft:
    if isinstance(draft, NormalizedCreateDraft):
        return draft
    if isinstance(draft, Mapping):
        normalized, _warnings = _normalize_draft(draft)
        return normalized
    raise TypeError("draft must be NormalizedCreateDraft or mapping")


def _validate_normalized_draft(draft: NormalizedCreateDraft) -> list[CreateIssue]:
    errors: list[CreateIssue] = []

    if not _normalize_vplib_uid_safe(draft.vplib_uid):
        errors.append(
            _error(
                "invalid_vplib_uid",
                "VPLIB UID fehlt oder ist ungültig.",
                field="vplib_uid",
                details={"vplib_uid": draft.vplib_uid},
            )
        )

    if not draft.family_name:
        errors.append(_error("required", "Name ist erforderlich.", field="family_name"))

    if not draft.family_description:
        errors.append(_error("required", "Beschreibung ist erforderlich.", field="family_description"))

    if not draft.family_slug:
        errors.append(_error("required", "Slug konnte nicht erzeugt werden.", field="family_slug"))

    if not draft.domain:
        errors.append(_error("required", "Reiter / Domain ist erforderlich.", field="domain"))

    if not draft.category:
        errors.append(_error("required", "Kategorie ist erforderlich.", field="category"))

    if not draft.subcategory:
        errors.append(_error("required", "Subkategorie ist erforderlich.", field="subcategory"))

    if not draft.classification_path:
        errors.append(
            _error(
                "required",
                "Classification Path konnte nicht erzeugt werden.",
                field="classification_path",
            )
        )

    if not draft.source_path:
        errors.append(
            _error(
                "required",
                "Source-Pfad konnte nicht erzeugt werden.",
                field="source_path",
            )
        )

    if len(draft.source_parts) < 4:
        errors.append(
            _error(
                "invalid_source_path",
                "Source-Pfad muss domain/category/subcategory/family_slug enthalten.",
                field="source_parts",
                details={"source_parts": list(draft.source_parts)},
            )
        )

    if not draft.family_id:
        errors.append(_error("required", "Family-ID konnte nicht erzeugt werden.", field="family_id"))

    if not draft.package_id:
        errors.append(_error("required", "Package-ID konnte nicht erzeugt werden.", field="package_id"))

    if draft.object_kind not in ALLOWED_OBJECT_KINDS:
        errors.append(_error("invalid_choice", "Ungültige Objektart.", field="object_kind"))

    if draft.primitive_shape not in ALLOWED_PRIMITIVE_SHAPES:
        errors.append(_error("invalid_choice", "Ungültige primitive Form.", field="primitive_shape"))

    if draft.geometry_unit not in ALLOWED_UNITS:
        errors.append(_error("invalid_choice", "Ungültige Einheit.", field="geometry_unit"))

    for field_name, value in [
        ("geometry_width", draft.geometry_width),
        ("geometry_height", draft.geometry_height),
        ("geometry_depth", draft.geometry_depth),
    ]:
        if value <= 0:
            errors.append(_error("invalid_number", "Maß muss größer als 0 sein.", field=field_name))

    for field_name, value in [
        ("editor_cells_x", draft.editor_cells_x),
        ("editor_cells_y", draft.editor_cells_y),
        ("editor_cells_z", draft.editor_cells_z),
    ]:
        if value < 1:
            errors.append(_error("invalid_integer", "Rasterbedarf muss mindestens 1 sein.", field=field_name))

    if not draft.variants:
        errors.append(_error("required", "Mindestens eine Variante ist erforderlich.", field="variants"))

    if draft.default_variant_id not in {str(variant.get("variant_id")) for variant in draft.variants}:
        errors.append(
            _error(
                "invalid_default_variant",
                "Die Default-Variante ist nicht in der Variantenliste enthalten.",
                field="default_variant_id",
            )
        )

    return errors


def _validate_package_documents(documents: Mapping[str, Any]) -> list[CreateIssue]:
    errors: list[CreateIssue] = []

    required = {
        "vplib.manifest.json",
        "vplib.modules.json",
        "family/identity.json",
        "family/classification.json",
        "variants/index.json",
        "variants/default.json",
        "editor/inventory.json",
        "editor/placement.json",
        "manufacturer/contract.json",
    }

    for required_file in sorted(required):
        if required_file not in documents:
            errors.append(
                _error(
                    "missing_required_document",
                    f"Pflichtdatei fehlt: {required_file}",
                    field="documents",
                    details={"path": required_file},
                )
            )

    manifest = documents.get(MANIFEST_DOCUMENT_PATH)
    if not isinstance(manifest, Mapping):
        errors.append(
            _error(
                "missing_manifest",
                "vplib.manifest.json fehlt oder ist kein JSON-Objekt.",
                field=MANIFEST_DOCUMENT_PATH,
            )
        )
    else:
        raw_uid = manifest.get(VPLIB_UID_FIELD)
        normalized_uid = _normalize_vplib_uid_safe(raw_uid)
        if not raw_uid:
            errors.append(
                _error(
                    "missing_vplib_uid",
                    "vplib.manifest.json enthält keine vplib_uid.",
                    field=f"{MANIFEST_DOCUMENT_PATH}.{VPLIB_UID_FIELD}",
                )
            )
        elif not normalized_uid:
            errors.append(
                _error(
                    "invalid_vplib_uid",
                    "vplib.manifest.json enthält eine ungültige vplib_uid.",
                    field=f"{MANIFEST_DOCUMENT_PATH}.{VPLIB_UID_FIELD}",
                    details={"value": str(raw_uid)},
                )
            )

    for relative_path, content in documents.items():
        try:
            _assert_safe_relative_file(relative_path)
            if _is_blocked_executable_path(relative_path):
                errors.append(
                    _error(
                        "blocked_file_type",
                        "Ausführbare Dateien sind in VPLIB-Packages nicht erlaubt.",
                        field="documents",
                        details={"path": relative_path},
                    )
                )
            _serialize_document(relative_path, content)
        except Exception as exc:
            errors.append(
                _exception_issue(
                    "invalid_document",
                    exc,
                    field="documents",
                    details={"path": str(relative_path)},
                )
            )

    return errors


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

def _build_default_variant_document(draft: NormalizedCreateDraft) -> dict[str, Any]:
    default_variant = {}
    for variant in draft.variants:
        if variant.get("variant_id") == draft.default_variant_id:
            default_variant = variant
            break

    return {
        "schema_version": DEFAULT_SCHEMA_VERSION,
        "variant_id": draft.default_variant_id,
        "label": str(default_variant.get("label") or "Standard"),
        "description": str(default_variant.get("description") or ""),
        "kind": str(default_variant.get("kind") or "standard"),
        "overrides": _json_safe(default_variant.get("overrides") or {}),
    }


def _default_placement_mode(object_kind: str) -> str:
    if object_kind == "adaptive_system":
        return "host_context"
    if object_kind == "catalog_object":
        return "free_or_grid"
    return "grid"


def _default_host_rules(draft: NormalizedCreateDraft) -> list[dict[str, Any]]:
    if draft.object_kind != "adaptive_system":
        return []
    return [
        {
            "type": "host_compatibility",
            "host_class": "custom_later",
            "host_anchor": "auto",
            "snap_policy": "auto_on_host",
            "required": True,
            "placeholder": True,
        }
    ]


def _build_notes_markdown(draft: NormalizedCreateDraft) -> str:
    return (
        "# VPLIB Create Notes\n\n"
        f"- VPLIB UID: `{draft.vplib_uid}`\n"
        f"- Family: `{draft.family_id}`\n"
        f"- Package: `{draft.package_id}`\n"
        f"- Object kind: `{draft.object_kind}`\n"
        f"- Taxonomy version: `{draft.taxonomy_version}`\n"
        f"- Classification: `{draft.classification_path}`\n"
        f"- Source path: `{draft.source_path}`\n"
        f"- Generated by: `{LIBRARY_CREATE_SERVICE_COMPONENT}` `{LIBRARY_CREATE_SERVICE_VERSION}`\n\n"
        "Dieses Package wurde durch den einfachen `/create`-Flow erzeugt.\n"
        "Es enthält keine ausführbare Logik, keinen Modellupload und keine automatische Veröffentlichung.\n"
    )


# ---------------------------------------------------------------------------
# Persistent draft helpers
# ---------------------------------------------------------------------------

def _build_draft_service_payload(
    *,
    draft: Mapping[str, Any],
    documents: Mapping[str, Any],
    original_payload: Mapping[str, Any],
    validation: CreateResult,
) -> dict[str, Any]:
    draft_payload = dict(draft)
    manifest = documents.get("vplib.manifest.json") if isinstance(documents.get("vplib.manifest.json"), Mapping) else {}
    modules = documents.get("vplib.modules.json") if isinstance(documents.get("vplib.modules.json"), Mapping) else {}
    family = documents.get("family/identity.json") if isinstance(documents.get("family/identity.json"), Mapping) else {}
    classification = documents.get("family/classification.json") if isinstance(documents.get("family/classification.json"), Mapping) else {}

    document_rows = []
    for path, content in sorted(documents.items()):
        document_rows.append(
            {
                "document_kind": "generated_package_document",
                "document_type": "json" if str(path).endswith(".json") else "markdown",
                "field_key": path,
                "title": path,
                "payload": {
                    "path": path,
                    "content": _json_safe(content),
                    "generated_by": LIBRARY_CREATE_SERVICE_COMPONENT,
                },
                "sort_order": len(document_rows),
            }
        )

    variant_rows = []
    for index, variant in enumerate(draft_payload.get("variants") or []):
        if not isinstance(variant, Mapping):
            continue
        variant_rows.append(
            {
                "variant_id": variant.get("variant_id"),
                "variant_key": variant.get("variant_id"),
                "label": variant.get("label"),
                "sort_order": index,
                "definition_values_json": variant.get("overrides") or {},
                "summary_json": {
                    "description": variant.get("description"),
                    "kind": variant.get("kind"),
                    "is_default": variant.get("is_default"),
                },
                "payload": _json_safe(dict(variant)),
            }
        )

    return {
        "user_id": original_payload.get("user_id", 1),
        "mode": original_payload.get("mode") or "create",
        "source_scope": "user",
        "target_vplib_uid": draft_payload.get("vplib_uid"),
        "family_id": draft_payload.get("family_id"),
        "package_id": draft_payload.get("package_id"),
        "vplib_uid": draft_payload.get("vplib_uid"),
        "title": draft_payload.get("family_name") or family.get("label"),
        "label": draft_payload.get("family_name") or family.get("label"),
        "name": draft_payload.get("family_name") or family.get("label"),
        "description": draft_payload.get("family_description") or family.get("description"),
        "family_payload": family or {
            "family_id": draft_payload.get("family_id"),
            "slug": draft_payload.get("family_slug"),
            "label": draft_payload.get("family_name"),
            "description": draft_payload.get("family_description"),
        },
        "classification_payload": classification or draft_payload.get("classification") or {},
        "manifest_payload": manifest,
        "modules_payload": modules,
        "generator_payload": {
            "component": LIBRARY_CREATE_SERVICE_COMPONENT,
            "version": LIBRARY_CREATE_SERVICE_VERSION,
            "original_payload": _json_safe(dict(original_payload)),
            "normalized_draft": _json_safe(draft_payload),
            "package_documents": _json_safe(documents),
        },
        "validation_payload": {
            "valid": validation.ok,
            "status": validation.status,
            "errors": [issue.to_dict() for issue in validation.errors],
            "warnings": [issue.to_dict() for issue in validation.warnings],
            "info": [issue.to_dict() for issue in validation.info],
        },
        "variants": variant_rows,
        "documents": document_rows,
        "assets": [],
        "payload": {
            "source": LIBRARY_CREATE_SERVICE_COMPONENT,
            "normalized_draft": _json_safe(draft_payload),
        },
        "metadata": {
            "source_path": draft_payload.get("source_path"),
            "source_parts": draft_payload.get("source_parts"),
            "package_version": draft_payload.get("package_version"),
            "taxonomy_version": (draft_payload.get("taxonomy") or {}).get("version"),
        },
    }


# ---------------------------------------------------------------------------
# Payload coercion / form normalization
# ---------------------------------------------------------------------------

def _coerce_payload_mapping(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}

    if isinstance(payload, Mapping):
        return _normalize_form_mapping(dict(payload))

    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace").strip()
        return _coerce_payload_mapping(text)

    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return {}
        try:
            loaded = json.loads(text)
            if isinstance(loaded, Mapping):
                return _normalize_form_mapping(dict(loaded))
            raise ValueError("JSON payload must be an object")
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON payload: {exc}") from exc

    raise TypeError(f"Unsupported payload type: {type(payload).__name__}")


def _normalize_form_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize common Flask form shapes and bracket notation.

    Handles:
        {"field": ["value"]} -> {"field": "value"}
        {"variables[0][key]": "x"} -> {"variables": [{"key": "x"}]}
        {"classification[domain]": "hochbau"} -> {"classification": {"domain": "hochbau"}}
    """
    normalized: dict[str, Any] = {}

    for key, value in payload.items():
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            if len(value) == 1:
                normalized[str(key)] = value[0]
            else:
                normalized[str(key)] = list(value)
        else:
            normalized[str(key)] = value

    indexed_prefixes = {
        "variants",
        "variables",
        "host_rules",
        "technical_profile",
        "assets",
        "documents",
        "validation_issues",
    }
    for prefix in indexed_prefixes:
        rows = _extract_indexed_rows(normalized, prefix)
        if rows:
            normalized[prefix] = rows

    nested_object_prefixes = {
        "taxonomy",
        "classification",
        "identity",
        "family",
        "geometry",
        "dimensions",
        "technical",
        "generator",
        "manifest",
        "modules",
        "metadata",
    }
    for prefix in nested_object_prefixes:
        nested = _extract_bracket_object(normalized, prefix)
        if nested:
            existing = normalized.get(prefix)
            if isinstance(existing, Mapping):
                merged = dict(existing)
                merged.update(nested)
                normalized[prefix] = merged
            else:
                normalized[prefix] = nested

    for json_key in [
        "variants_json",
        "definition_variants_json",
        "definitionVariantsJson",
        "variables_json",
        "technical_profile_json",
        "taxonomy_json",
        "classification_json",
        "family_json",
        "manifest_json",
        "modules_json",
        "generator_json",
        "documents_json",
        "assets_json",
        "draft_json",
    ]:
        if json_key in normalized and isinstance(normalized[json_key], str):
            try:
                decoded = json.loads(normalized[json_key])
                if json_key == "draft_json" and isinstance(decoded, Mapping):
                    normalized.update(dict(decoded))
                elif json_key in {"definition_variants_json", "definitionVariantsJson"}:
                    normalized["definition_variants_json"] = decoded
                    normalized.setdefault("variants", decoded)
                elif json_key.endswith("_json"):
                    target_key = json_key[:-5]
                    normalized[target_key] = decoded
            except Exception:
                pass

    return normalized


def _extract_indexed_rows(payload: Mapping[str, Any], prefix: str) -> list[dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    pattern = re.compile(rf"^{re.escape(prefix)}\[(\d+)\]\[([^\]]+)\]$")

    for key, value in payload.items():
        match = pattern.match(str(key))
        if not match:
            continue
        index = int(match.group(1))
        field_name = match.group(2)
        rows.setdefault(index, {})[field_name] = value

    return [rows[index] for index in sorted(rows.keys())]


def _extract_bracket_object(payload: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    pattern = re.compile(rf"^{re.escape(prefix)}\[([^\]]+)\]$")

    for key, value in payload.items():
        match = pattern.match(str(key))
        if not match:
            continue
        result[match.group(1)] = value

    return result


# ---------------------------------------------------------------------------
# Option helpers
# ---------------------------------------------------------------------------

def _static_create_options() -> dict[str, Any]:
    return {
        "object_kinds": [
            {
                "value": "cell_block",
                "id": "cell_block",
                "label": "Raster-Bauteil",
                "description": "Ein einzelner Raster- oder Blockbaustein.",
                "enabled": True,
                "default": True,
            },
            {
                "value": "multi_cell_module",
                "id": "multi_cell_module",
                "label": "Mehrblock-Modul",
                "description": "Ein Modul, das mehrere Rasterblöcke belegen kann.",
                "enabled": True,
            },
            {
                "value": "catalog_object",
                "id": "catalog_object",
                "label": "Katalogobjekt",
                "description": "Ein freies Objekt wie Möbel, Armatur oder Ausstattung.",
                "enabled": True,
            },
            {
                "value": "adaptive_system",
                "id": "adaptive_system",
                "label": "Adaptives System",
                "description": "Ein später kontextabhängiges System.",
                "enabled": True,
            },
        ],
        "primitive_shapes": [
            {"value": "block", "id": "block", "label": "Block / Quader", "enabled": True, "default": True},
            {"value": "wall", "id": "wall", "label": "Wand / Platte stehend", "enabled": True},
            {"value": "slab", "id": "slab", "label": "Decke / Platte liegend", "enabled": True},
            {"value": "cylinder", "id": "cylinder", "label": "Zylinder", "enabled": True},
            {"value": "pipe", "id": "pipe", "label": "Rohr / liegender Zylinder", "enabled": True},
        ],
        "units": [
            {"value": "m", "id": "m", "label": "Meter", "enabled": True, "default": True},
            {"value": "cm", "id": "cm", "label": "Zentimeter", "enabled": True},
            {"value": "mm", "id": "mm", "label": "Millimeter", "enabled": True},
        ],
        "material_classes": [
            {"value": "beton", "id": "beton", "label": "Beton", "enabled": True},
            {"value": "stahlbeton", "id": "stahlbeton", "label": "Stahlbeton", "enabled": True},
            {"value": "ziegel", "id": "ziegel", "label": "Ziegel", "enabled": True},
            {"value": "mauerwerk", "id": "mauerwerk", "label": "Mauerwerk", "enabled": True},
            {"value": "holz", "id": "holz", "label": "Holz", "enabled": True},
            {"value": "stahl", "id": "stahl", "label": "Stahl", "enabled": True},
            {"value": "glas", "id": "glas", "label": "Glas", "enabled": True},
            {"value": "kunststoff", "id": "kunststoff", "label": "Kunststoff", "enabled": True},
            {"value": "sonstiges", "id": "sonstiges", "label": "Sonstiges Material", "enabled": True},
        ],
    }


def _flatten_taxonomy_options(taxonomy_payload: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    categories: list[dict[str, Any]] = []
    subcategories: list[dict[str, Any]] = []

    categories_by_domain = taxonomy_payload.get("categories_by_domain", {})
    if isinstance(categories_by_domain, Mapping):
        for domain, items in categories_by_domain.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                categories.append(
                    {
                        "value": item.get("id") or item.get("value") or item.get("node_key") or "",
                        "id": item.get("id") or item.get("value") or item.get("node_key") or "",
                        "label": item.get("label", item.get("id", "")),
                        "domain": domain,
                        "enabled": not bool(item.get("disabled", False)),
                        "description": item.get("description", ""),
                        "status": item.get("status", "active"),
                    }
                )

    subcategory_maps = [
        taxonomy_payload.get("subcategories_by_category", {}),
        taxonomy_payload.get("subcategories_by_category_path", {}),
    ]
    for subcategories_by_category in subcategory_maps:
        if not isinstance(subcategories_by_category, Mapping):
            continue

        for key, items in subcategories_by_category.items():
            if not isinstance(items, list):
                continue

            parts = str(key).split("/")
            domain = parts[0] if len(parts) > 0 else ""
            category = parts[1] if len(parts) > 1 else ""

            for item in items:
                if not isinstance(item, Mapping):
                    continue
                option_id = item.get("id") or item.get("value") or item.get("node_key") or ""
                subcategories.append(
                    {
                        "value": option_id,
                        "id": option_id,
                        "label": item.get("label", option_id),
                        "domain": domain,
                        "category": category,
                        "enabled": not bool(item.get("disabled", False)),
                        "description": item.get("description", ""),
                        "status": item.get("status", "active"),
                    }
                )

    return {
        "categories": categories,
        "subcategories": subcategories,
    }


# ---------------------------------------------------------------------------
# Variant / variable normalization
# ---------------------------------------------------------------------------

def _normalize_variants(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[CreateIssue]]:
    warnings: list[CreateIssue] = []

    raw_variants = _first_value(
        payload,
        [
            "definition_variants_json",
            "definitionVariantsJson",
            "definition_variants",
            "definitionVariants",
            "variants",
            ("family", "variants"),
        ],
        [],
    )
    variants: list[dict[str, Any]] = []

    if isinstance(raw_variants, str):
        try:
            decoded = json.loads(raw_variants)
            raw_variants = decoded if isinstance(decoded, list) else []
        except Exception:
            raw_variants = []

    if isinstance(raw_variants, Mapping):
        if isinstance(raw_variants.get("variants"), list):
            raw_variants = raw_variants.get("variants")
        elif isinstance(raw_variants.get("items"), list):
            raw_variants = raw_variants.get("items")
        else:
            mapped_variants: list[dict[str, Any]] = []
            for key, item in raw_variants.items():
                if isinstance(item, Mapping):
                    row = dict(item)
                    row.setdefault("variant_id", key)
                    mapped_variants.append(row)
                else:
                    mapped_variants.append(
                        {
                            "variant_id": key,
                            "label": str(key),
                            "overrides": {"value": _json_safe(item)},
                        }
                    )
            raw_variants = mapped_variants

    if not isinstance(raw_variants, Iterable) or isinstance(raw_variants, (str, bytes, Mapping)):
        raw_variants = []

    seen: set[str] = set()

    for index, raw_variant in enumerate(list(raw_variants)[:MAX_VARIANTS]):
        if isinstance(raw_variant, Mapping):
            kind = _normalize_slug_token(
                _first_value(
                    raw_variant,
                    ["kind", "variant_kind", "difference_kind", "type"],
                    "standard" if index == 0 else "other",
                )
            )
            label_raw = _first_value(
                raw_variant,
                ["label", "name", "value"],
                "Standard" if index == 0 else f"Variante {index + 1}",
            )
            label = _clean_text(label_raw, max_length=160)
            description = _clean_text(
                _first_value(raw_variant, ["description", "usage", "note"], ""),
                max_length=600,
            )
            variant_id_raw = _first_value(raw_variant, ["variant_id", "variantId", "slug", "id", "key"], "")
            is_default = _safe_bool(
                _first_value(raw_variant, ["is_default", "isDefault", "default"], index == 0),
                default=index == 0,
            )
            overrides = raw_variant.get("overrides") if isinstance(raw_variant.get("overrides"), Mapping) else {}
            if not overrides and isinstance(raw_variant.get("definition_values"), Mapping):
                overrides = dict(raw_variant.get("definition_values") or {})
        else:
            kind = "standard" if index == 0 else "other"
            label = _clean_text(raw_variant, max_length=160) or (
                "Standard" if index == 0 else f"Variante {index + 1}"
            )
            description = ""
            variant_id_raw = ""
            is_default = index == 0
            overrides = {}

        if index == 0 and not variant_id_raw:
            variant_id = "default"
        else:
            variant_id = _safe_segment(_slugify(str(variant_id_raw or label or f"variant_{index + 1}")))

        if not variant_id:
            variant_id = "default" if index == 0 else f"variant_{index + 1}"

        original_variant_id = variant_id
        duplicate_index = 2
        while variant_id in seen:
            variant_id = f"{original_variant_id}_{duplicate_index}"
            duplicate_index += 1

        if variant_id != original_variant_id:
            warnings.append(
                _warning(
                    "duplicate_variant_id_renamed",
                    "Doppelte Varianten-ID wurde automatisch eindeutig gemacht.",
                    field="variants",
                    details={"from": original_variant_id, "to": variant_id},
                )
            )

        seen.add(variant_id)

        variants.append(
            {
                "variant_id": variant_id,
                "label": label or variant_id,
                "description": description,
                "kind": kind or "other",
                "is_default": bool(is_default),
                "overrides": _json_safe(overrides),
            }
        )

    if not variants:
        variants.append(
            {
                "variant_id": "default",
                "label": "Standard",
                "description": "",
                "kind": "standard",
                "is_default": True,
                "overrides": {},
            }
        )

    if not any(variant.get("is_default") for variant in variants):
        variants[0]["is_default"] = True

    return variants, warnings


def _normalize_variables(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[CreateIssue]]:
    warnings: list[CreateIssue] = []

    raw_variables = _first_value(
        payload,
        ["variables", ("technical", "variables"), ("calculation", "variables")],
        [],
    )

    if isinstance(raw_variables, str):
        try:
            decoded = json.loads(raw_variables)
            raw_variables = decoded if isinstance(decoded, list) else []
        except Exception:
            raw_variables = []

    if not isinstance(raw_variables, Iterable) or isinstance(raw_variables, (str, bytes, Mapping)):
        raw_variables = []

    variables: list[dict[str, Any]] = []

    for raw_variable in list(raw_variables)[:MAX_VARIABLES]:
        if not isinstance(raw_variable, Mapping):
            continue

        key = _normalize_variable_key(_first_value(raw_variable, ["key", "name"], ""))
        if not key:
            continue

        value = _json_safe(_first_value(raw_variable, ["value"], ""))
        unit = _clean_text(_first_value(raw_variable, ["unit"], ""), max_length=80)
        description = _clean_text(_first_value(raw_variable, ["description", "label"], ""), max_length=240)
        value_type = _normalize_slug_token(_first_value(raw_variable, ["value_type", "type"], "auto"))
        scope = _normalize_slug_token(_first_value(raw_variable, ["scope"], "family"))

        variables.append(
            {
                "key": key,
                "value": value,
                "unit": unit,
                "description": description,
                "value_type": value_type or "auto",
                "scope": scope or "family",
            }
        )

    return variables, warnings


def _normalize_material_classes(value: Any) -> list[str]:
    if value is None:
        return []

    raw_items: list[Any]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
                raw_items = decoded if isinstance(decoded, list) else [stripped]
            except Exception:
                raw_items = re.split(r"[,;]", stripped)
        else:
            raw_items = re.split(r"[,;]", stripped)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        raw_items = list(value)
    else:
        raw_items = [value]

    result: list[str] = []
    seen: set[str] = set()

    for item in raw_items:
        token = _normalize_slug_token(item)
        if token and token not in seen:
            seen.add(token)
            result.append(token)

    return result[:20]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _first_value(mapping: Mapping[str, Any], keys: Sequence[str | Sequence[str]], default: Any = None) -> Any:
    for key in keys:
        value = _nested_value(mapping, key)
        if value is not None and value != "":
            return value
    return default


def _nested_value(mapping: Mapping[str, Any], key: str | Sequence[str]) -> Any:
    if isinstance(key, str):
        return mapping.get(key)

    current: Any = mapping
    for part in key:
        if not isinstance(current, Mapping):
            return None
        current = current.get(str(part))
        if current is None:
            return None
    return current


def _safe_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    slug = str(value).strip().lower()
    if slug in {"1", "true", "yes", "ja", "on", "enabled", "active", "default"}:
        return True
    if slug in {"0", "false", "no", "nein", "off", "disabled", "inactive"}:
        return False
    return default


def _env_bool(name: str, *, default: bool = False) -> bool:
    return _safe_bool(os.getenv(name), default=default)


def _safe_int(value: Any, *, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        if value is None or value == "":
            result = default
        else:
            result = int(float(str(value).replace(",", ".").strip()))
    except Exception:
        result = default

    if minimum is not None and result < minimum:
        result = minimum
    if maximum is not None and result > maximum:
        result = maximum
    return result


def _safe_float(
    value: Any,
    *,
    default: float = 0.0,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        if value is None or value == "":
            result = default
        elif isinstance(value, (int, float)):
            result = float(value)
        else:
            result = float(str(value).replace(",", ".").strip())
    except Exception:
        result = default

    if minimum is not None and result < minimum:
        result = minimum
    if maximum is not None and result > maximum:
        result = maximum
    return result


def _clean_text(value: Any, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    text = re.sub(r"\s+", " ", text)
    if max_length > 0:
        text = text[:max_length]
    return text


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "é": "e",
        "è": "e",
        "ê": "e",
        "á": "a",
        "à": "a",
        "â": "a",
        "ó": "o",
        "ò": "o",
        "ô": "o",
        "í": "i",
        "ì": "i",
        "î": "i",
        "ç": "c",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _normalize_slug_token(value: Any) -> str:
    return _slugify(value)


def _normalize_variable_key(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace(" ", "_")
    text = re.sub(r"[^a-zA-Z0-9_.\-]", "", text)
    text = re.sub(r"\.+", ".", text).strip(".")
    return text[:160]


def _normalize_object_kind(value: Any) -> str:
    token = _normalize_slug_token(value)
    mapping = {
        "object": "catalog_object",
        "catalog": "catalog_object",
        "catalogue_object": "catalog_object",
        "block": "cell_block",
        "cell": "cell_block",
        "cellblock": "cell_block",
        "multi_cell": "multi_cell_module",
        "module": "multi_cell_module",
        "adaptive": "adaptive_system",
        "system": "adaptive_system",
    }
    return mapping.get(token, token)


def _normalize_unit(value: Any) -> str:
    text = str(value or "").strip()
    if text in {"m", "cm", "mm"}:
        return text
    return _normalize_slug_token(text)


def _safe_segment(value: Any) -> str:
    token = _slugify(value)
    if not token or token in {".", ".."}:
        raise ValueError(f"Invalid path segment: {value!r}")
    if len(token) > MAX_SLUG_LENGTH:
        token = token[:MAX_SLUG_LENGTH].strip("_")
    if not token:
        raise ValueError(f"Invalid path segment after trimming: {value!r}")
    return token


def _safe_join(root: Path, *parts: str) -> Path:
    root_resolved = Path(root).resolve()
    target = root_resolved

    for part in parts:
        if not part:
            raise ValueError("Empty path part is not allowed")

        sub_parts = str(part).replace("\\", "/").split("/")
        for sub_part in sub_parts:
            if sub_part in {"", ".", ".."}:
                raise ValueError(f"Invalid path part: {part!r}")
            target = target / sub_part

    target_resolved = target.resolve()
    if not _is_relative_to(target_resolved, root_resolved):
        raise ValueError(f"Resolved path escapes root: {target_resolved}")
    return target_resolved


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_safe_relative_file(relative_path: str) -> None:
    if not relative_path or not isinstance(relative_path, str):
        raise ValueError("relative path must be a non-empty string")

    normalized = relative_path.replace("\\", "/")

    if normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
        raise ValueError(f"unsafe relative path: {relative_path}")

    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe relative path part: {relative_path}")

    if normalized != relative_path:
        raise ValueError(f"path must use forward slashes only: {relative_path}")


def _is_blocked_executable_path(path: str | Path) -> bool:
    suffix = Path(str(path)).suffix.lower()
    return suffix in EXECUTABLE_EXTENSIONS_BLOCKLIST


def _serialize_document(relative_path: str, content: Any) -> str:
    if relative_path.endswith(".json"):
        try:
            return json.dumps(_json_safe(content), ensure_ascii=False, indent=2, sort_keys=False) + "\n"
        except TypeError as exc:
            raise ValueError(f"Document is not JSON serializable: {relative_path}") from exc

    if isinstance(content, str):
        return content if content.endswith("\n") else content + "\n"

    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")

    return str(content) + "\n"


def _write_text_atomic(target_file: Path, content: str) -> None:
    temp_file = target_file.with_name(f".{target_file.name}.tmp")
    try:
        temp_file.write_text(content, encoding="utf-8")
        temp_file.replace(target_file)
    except Exception:
        try:
            if temp_file.exists():
                temp_file.unlink()
        except Exception:
            pass
        raise


# ---------------------------------------------------------------------------
# VPLIB UID helpers
# ---------------------------------------------------------------------------

def _ensure_payload_vplib_uid(payload: Mapping[str, Any]) -> str:
    """Return an existing valid VPLIB UID or generate a new one."""
    raw_uid = _extract_vplib_uid_from_any(payload)
    if raw_uid:
        return raw_uid

    explicit_raw = _extract_raw_vplib_uid(payload)
    if explicit_raw is not None and str(explicit_raw).strip():
        raise CreateDraftNormalizationError(
            "VPLIB UID ist ungültig und wird nicht still ersetzt.",
            errors=[
                _error(
                    "invalid_vplib_uid",
                    "VPLIB UID ist ungültig und wird nicht still ersetzt.",
                    field=VPLIB_UID_FIELD,
                    details={"value": str(explicit_raw)},
                )
            ],
        )

    try:
        from vplib.vplib_id_service import generate_vplib_uid

        return generate_vplib_uid()
    except Exception:
        pass

    try:
        from src.vplib.vplib_id_service import generate_vplib_uid  # type: ignore

        return generate_vplib_uid()
    except Exception:
        pass

    return str(uuid.uuid4()).lower()


def _extract_raw_vplib_uid(value: Any, *, _depth: int = 0) -> Any | None:
    if value is None or _depth > 5:
        return None

    if isinstance(value, Mapping):
        for key in VPLIB_UID_KEYS:
            if key in value:
                return value.get(key)

        for nested_key in ("identity", "manifest", "vplib_manifest", "metadata", "data", "payload", "draft"):
            nested = value.get(nested_key)
            nested_uid = _extract_raw_vplib_uid(nested, _depth=_depth + 1)
            if nested_uid is not None:
                return nested_uid
        return None

    for attr_name in VPLIB_UID_KEYS:
        try:
            if hasattr(value, attr_name):
                attr_value = getattr(value, attr_name)
                if attr_value is not None:
                    return attr_value
        except Exception:
            continue

    for nested_attr in ("identity", "manifest", "vplib_manifest", "metadata", "data", "payload", "draft"):
        try:
            nested = getattr(value, nested_attr, None)
            nested_uid = _extract_raw_vplib_uid(nested, _depth=_depth + 1)
            if nested_uid is not None:
                return nested_uid
        except Exception:
            continue

    return None


def _extract_vplib_uid_from_any(value: Any, *, _depth: int = 0) -> str | None:
    if value is None or _depth > 5:
        return None

    normalized = _normalize_vplib_uid_safe(value)
    if normalized:
        return normalized

    raw = _extract_raw_vplib_uid(value, _depth=_depth)
    normalized = _normalize_vplib_uid_safe(raw)
    if normalized:
        return normalized

    if isinstance(value, Mapping):
        if MANIFEST_DOCUMENT_PATH in value:
            normalized = _extract_vplib_uid_from_any(value.get(MANIFEST_DOCUMENT_PATH), _depth=_depth + 1)
            if normalized:
                return normalized

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            payload = value.to_dict()
            normalized = _extract_vplib_uid_from_any(payload, _depth=_depth + 1)
            if normalized:
                return normalized
        except Exception:
            pass

    return None


def _normalize_vplib_uid_safe(value: Any) -> str | None:
    if value is None:
        return None

    try:
        from vplib.vplib_id_service import normalize_vplib_uid

        uid = normalize_vplib_uid(value)
        if uid:
            return uid
    except Exception:
        pass

    try:
        from src.vplib.vplib_id_service import normalize_vplib_uid  # type: ignore

        uid = normalize_vplib_uid(value)
        if uid:
            return uid
    except Exception:
        pass

    try:
        parsed = uuid.UUID(str(value).strip())
        return str(parsed).lower()
    except Exception:
        return None


def _get_vplib_uid_service_health() -> dict[str, Any]:
    try:
        from vplib.vplib_id_service import generate_vplib_uid, normalize_vplib_uid

        generated = generate_vplib_uid()
        return {
            "available": bool(normalize_vplib_uid(generated)),
            "generated_sample_valid": bool(normalize_vplib_uid(generated)),
            "field": VPLIB_UID_FIELD,
        }
    except Exception as first_exc:
        try:
            from src.vplib.vplib_id_service import generate_vplib_uid, normalize_vplib_uid  # type: ignore

            generated = generate_vplib_uid()
            return {
                "available": bool(normalize_vplib_uid(generated)),
                "generated_sample_valid": bool(normalize_vplib_uid(generated)),
                "field": VPLIB_UID_FIELD,
            }
        except Exception as second_exc:
            return {
                "available": False,
                "field": VPLIB_UID_FIELD,
                "errors": [
                    {
                        "type": type(first_exc).__name__,
                        "message": str(first_exc),
                    },
                    {
                        "type": type(second_exc).__name__,
                        "message": str(second_exc),
                    },
                ],
            }


# ---------------------------------------------------------------------------
# JSON / issue helpers
# ---------------------------------------------------------------------------

def _json_safe(value: Any) -> Any:
    try:
        return _taxonomy_json_safe(value)
    except Exception:
        return _json_safe_fallback(value)


def _json_safe_fallback(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, CreateIssue):
        return value.to_dict()

    if isinstance(value, Mapping):
        return {str(key): _json_safe_fallback(inner_value) for key, inner_value in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_json_safe_fallback(item) for item in value]

    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _error(
    code: str,
    message: str,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
) -> CreateIssue:
    return CreateIssue(
        severity="error",
        code=code,
        message=message,
        field=field,
        details=details or {},
    )


def _warning(
    code: str,
    message: str,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
) -> CreateIssue:
    return CreateIssue(
        severity="warning",
        code=code,
        message=message,
        field=field,
        details=details or {},
    )


def _info(
    code: str,
    message: str,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
) -> CreateIssue:
    return CreateIssue(
        severity="info",
        code=code,
        message=message,
        field=field,
        details=details or {},
    )


def _exception_issue(
    code: str,
    exc: BaseException | None,
    *,
    field: str = "",
    details: dict[str, Any] | None = None,
    fallback_message: str = "",
) -> CreateIssue:
    issue_details = dict(details or {})

    if exc is None:
        return _error(
            code,
            fallback_message or "Unbekannter Fehler.",
            field=field,
            details=issue_details,
        )

    issue_details["exception_type"] = type(exc).__name__
    issue_details["exception"] = str(exc)

    if _env_bool(ENV_DEBUG, default=False):
        issue_details["traceback"] = traceback.format_exc()

    return _error(
        code,
        fallback_message or str(exc) or type(exc).__name__,
        field=field,
        details=issue_details,
    )


def _failure(
    code: str,
    message: str,
    *,
    exc: BaseException | None = None,
    http_status: int = 500,
) -> CreateResult:
    if exc:
        details: dict[str, Any] = {
            "exception": str(exc),
            "exception_type": type(exc).__name__,
        }
        if _env_bool(ENV_DEBUG, default=False):
            details["traceback"] = traceback.format_exc()

        errors = [
            CreateIssue(
                severity="error",
                code=code,
                message=message,
                details=details,
            )
        ]
    else:
        errors = [_error(code, message)]

    return CreateResult(
        ok=False,
        status=code,
        data={},
        errors=errors,
        http_status=http_status,
    )


def clear_library_create_service_caches() -> dict[str, Any]:
    """Clear lazy import caches."""
    cleared: list[str] = []

    for cached_func in (
        _load_taxonomy_module,
        _load_definition_catalog_service_module,
    ):
        try:
            cached_func.cache_clear()
            cleared.append(getattr(cached_func, "__name__", str(cached_func)))
        except Exception:
            pass

    return {
        "ok": True,
        "cleared": cleared,
    }


__all__ = [
    "ALLOWED_OBJECT_KINDS",
    "ALLOWED_PRIMITIVE_SHAPES",
    "ALLOWED_UNITS",
    "CREATE_API_PREFIX",
    "CreateDraftNormalizationError",
    "CreateIssue",
    "CreateResult",
    "DEFAULT_OBJECT_KIND",
    "DEFAULT_PACKAGE_VERSION",
    "DEFAULT_PRIMITIVE_SHAPE",
    "DEFAULT_SCHEMA_VERSION",
    "DEFAULT_UNIT",
    "ENV_DEBUG",
    "ENV_OVERWRITE_ENABLED",
    "ENV_SOURCE_ROOT_PRIMARY",
    "ENV_SOURCE_ROOT_SECONDARY",
    "ENV_WRITE_ENABLED",
    "LIBRARY_CREATE_SERVICE_COMPONENT",
    "LIBRARY_CREATE_SERVICE_VERSION",
    "MANIFEST_DOCUMENT_PATH",
    "NormalizedCreateDraft",
    "REQUIRED_TAXONOMY_FIELDS",
    "VPLIB_UID_FIELD",
    "VPLIB_UID_KEYS",
    "build_draft",
    "build_package_documents",
    "build_package_plan",
    "build_persistent_draft_payload",
    "build_publish_bundle_from_create_payload",
    "build_vplib_archive",
    "clear_library_create_service_caches",
    "create_draft",
    "get_create_context",
    "get_create_options",
    "get_options",
    "get_service_health",
    "get_source_root",
    "health",
    "package_plan",
    "save_package",
    "validate_draft",
]