# services/vectoplan-library/src/vplib/validators/semantic_validator.py
"""
Semantic validator for the VPLIB package engine.

Diese Datei validiert VPLIB-Dokumente auf fachlicher und paketübergreifender Ebene.

Rolle dieser Datei:

    DocumentBundle / documents mapping / CreationPlan
    -> SemanticValidationResult
    -> ValidationResult

Diese Datei prüft dokumentübergreifend:
- Manifest, Modules, Family und Editor-Klassifikation
- Family-Identität gegen Manifest
- active_modules gegen vorhandene Dokumente
- Variantenindex gegen Varianten-Dokumente
- Placement/Grid-Footprint gegen Render-/Physical-Bounds
- object_kind-spezifische Regeln
- Render-Fallback/Textur/Modell-Regeln
- Physical-Dimensionen und Occupancy
- Material-/Physical-Konsistenz
- Calculation-Referenzen
- Manufacturer-Override-Slots
- Dynamic-Regeln für adaptive_system
- verbotene ausführbare Referenzen in deklarativen Dokumenten

Diese Datei schreibt keine Dateien und liest keine Dateien vom Dateisystem.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


SEMANTIC_VALIDATOR_SCHEMA_VERSION: Final[str] = "vplib.semantic_validator.v1"

ROOT_REQUIRED_DOCUMENTS: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
    "vplib.modules.json",
    "family/identity.json",
    "family/classification.json",
    "variants/index.json",
    "variants/default.json",
    "editor/inventory.json",
    "editor/placement.json",
    "manufacturer/contract.json",
)

OBJECT_KIND_ALLOWED_VALUES: Final[tuple[str, ...]] = (
    "cell_block",
    "multi_cell_module",
    "catalog_object",
    "adaptive_system",
)

CORE_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "manufacturer",
)

MODULE_ROOT_DOCUMENTS: Final[dict[str, tuple[str, ...]]] = {
    "manifest": ("vplib.manifest.json",),
    "modules": ("vplib.modules.json",),
    "family": ("family/identity.json", "family/classification.json"),
    "variants": ("variants/index.json",),
    "editor": ("editor/inventory.json", "editor/placement.json"),
    "render": ("render/render_variants.json",),
    "physical": ("physical/base.json", "physical/dimensions.json", "physical/collision.json"),
    "material": ("material/base.json",),
    "calculation": (
        "calculation/variables.json",
        "calculation/formulas.json",
        "calculation/quantities.json",
        "calculation/measure_logic.json",
    ),
    "analysis": (
        "analysis/statics/profile.json",
        "analysis/routing/profile.json",
        "analysis/reinforcement/profile.json",
    ),
    "dynamic": (
        "dynamic/context_rules.json",
        "dynamic/bindings.json",
        "dynamic/generator.json",
    ),
    "manufacturer": ("manufacturer/contract.json",),
    "docs": tuple(),
    "tests": tuple(),
}

NON_ADAPTIVE_OBJECT_KINDS: Final[tuple[str, ...]] = (
    "cell_block",
    "multi_cell_module",
    "catalog_object",
)

DECLARATIVE_FORBIDDEN_TOKENS: Final[tuple[str, ...]] = (
    "__",
    "import ",
    "exec(",
    "eval(",
    "open(",
    "read(",
    "write(",
    "delete",
    "remove",
    "subprocess",
    "socket",
    "os.",
    "sys.",
    "lambda",
    "class ",
    "def ",
)

EXECUTABLE_FILE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".py",
    ".pyc",
    ".pyo",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".sh",
    ".bash",
    ".bat",
    ".cmd",
    ".ps1",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".jar",
)

SAFE_FIELD_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$"
)


class SemanticValidatorError(ValueError):
    """Wird ausgelöst, wenn die semantische Validierung selbst fehlschlägt."""


class SemanticValidationStatus(str, Enum):
    """Status einer semantischen Validierung."""

    VALID = "valid"
    INVALID = "invalid"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class SemanticValidationMode(str, Enum):
    """Validierungsmodus."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


class SemanticIssueSeverity(str, Enum):
    """Schweregrad semantischer Issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class SemanticIssueCode(str, Enum):
    """Semantische Issue-Codes."""

    UNKNOWN = "VPLIB_SEMANTIC_UNKNOWN"
    MISSING_DOCUMENT = "VPLIB_SEMANTIC_MISSING_DOCUMENT"
    MODULE_DOCUMENT_MISSING = "VPLIB_SEMANTIC_MODULE_DOCUMENT_MISSING"
    INCONSISTENT_IDENTITY = "VPLIB_SEMANTIC_INCONSISTENT_IDENTITY"
    INCONSISTENT_CLASSIFICATION = "VPLIB_SEMANTIC_INCONSISTENT_CLASSIFICATION"
    INCONSISTENT_OBJECT_KIND = "VPLIB_SEMANTIC_INCONSISTENT_OBJECT_KIND"
    INCONSISTENT_MODULES = "VPLIB_SEMANTIC_INCONSISTENT_MODULES"
    INVALID_VARIANT_GRAPH = "VPLIB_SEMANTIC_INVALID_VARIANT_GRAPH"
    INVALID_PLACEMENT = "VPLIB_SEMANTIC_INVALID_PLACEMENT"
    INVALID_RENDER = "VPLIB_SEMANTIC_INVALID_RENDER"
    INVALID_PHYSICAL = "VPLIB_SEMANTIC_INVALID_PHYSICAL"
    INVALID_MATERIAL = "VPLIB_SEMANTIC_INVALID_MATERIAL"
    INVALID_CALCULATION = "VPLIB_SEMANTIC_INVALID_CALCULATION"
    INVALID_MANUFACTURER = "VPLIB_SEMANTIC_INVALID_MANUFACTURER"
    INVALID_DYNAMIC = "VPLIB_SEMANTIC_INVALID_DYNAMIC"
    EXECUTABLE_CONTENT = "VPLIB_SEMANTIC_EXECUTABLE_CONTENT"
    INTERNAL_ERROR = "VPLIB_SEMANTIC_INTERNAL_ERROR"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SemanticValidationOptions:
    """Optionen für die semantische Validierung."""

    mode: str = SemanticValidationMode.STRICT.value
    require_core_documents: bool = True
    require_active_module_documents: bool = True
    validate_identity_consistency: bool = True
    validate_classification_consistency: bool = True
    validate_object_kind_rules: bool = True
    validate_variant_consistency: bool = True
    validate_placement_consistency: bool = True
    validate_render_physical_consistency: bool = True
    validate_material_consistency: bool = True
    validate_calculation_references: bool = True
    validate_manufacturer_rules: bool = True
    validate_dynamic_rules: bool = True
    validate_declarative_safety: bool = True
    collect_all_errors: bool = True
    strict: bool = True

    def normalized(self) -> "SemanticValidationOptions":
        mode = parse_validation_mode_value(self.mode)

        return SemanticValidationOptions(
            mode=mode,
            require_core_documents=bool(self.require_core_documents),
            require_active_module_documents=bool(self.require_active_module_documents),
            validate_identity_consistency=bool(self.validate_identity_consistency),
            validate_classification_consistency=bool(self.validate_classification_consistency),
            validate_object_kind_rules=bool(self.validate_object_kind_rules),
            validate_variant_consistency=bool(self.validate_variant_consistency),
            validate_placement_consistency=bool(self.validate_placement_consistency),
            validate_render_physical_consistency=bool(self.validate_render_physical_consistency),
            validate_material_consistency=bool(self.validate_material_consistency),
            validate_calculation_references=bool(self.validate_calculation_references),
            validate_manufacturer_rules=bool(self.validate_manufacturer_rules),
            validate_dynamic_rules=bool(self.validate_dynamic_rules),
            validate_declarative_safety=bool(self.validate_declarative_safety),
            collect_all_errors=bool(self.collect_all_errors),
            strict=bool(self.strict),
        )

    @property
    def is_strict(self) -> bool:
        return self.normalized().mode == SemanticValidationMode.STRICT.value

    @property
    def is_permissive(self) -> bool:
        return self.normalized().mode == SemanticValidationMode.PERMISSIVE.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "mode": normalized.mode,
            "require_core_documents": normalized.require_core_documents,
            "require_active_module_documents": normalized.require_active_module_documents,
            "validate_identity_consistency": normalized.validate_identity_consistency,
            "validate_classification_consistency": normalized.validate_classification_consistency,
            "validate_object_kind_rules": normalized.validate_object_kind_rules,
            "validate_variant_consistency": normalized.validate_variant_consistency,
            "validate_placement_consistency": normalized.validate_placement_consistency,
            "validate_render_physical_consistency": normalized.validate_render_physical_consistency,
            "validate_material_consistency": normalized.validate_material_consistency,
            "validate_calculation_references": normalized.validate_calculation_references,
            "validate_manufacturer_rules": normalized.validate_manufacturer_rules,
            "validate_dynamic_rules": normalized.validate_dynamic_rules,
            "validate_declarative_safety": normalized.validate_declarative_safety,
            "collect_all_errors": normalized.collect_all_errors,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class SemanticIssue:
    """Ein einzelnes semantisches Issue."""

    code: str
    message: str
    severity: str = SemanticIssueSeverity.ERROR.value
    path: str | None = None
    field_path: str | None = None
    module_name: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SemanticIssue":
        code = parse_issue_code_value(self.code)
        message = clean_required_string(self.message, "message")
        severity = parse_issue_severity_value(self.severity)
        path = clean_optional_string(self.path)
        field_path = normalize_optional_field_path(self.field_path)
        module_name = normalize_optional_module_name(self.module_name)
        details = normalize_metadata(self.details)

        return SemanticIssue(
            code=code,
            message=message,
            severity=severity,
            path=path,
            field_path=field_path,
            module_name=module_name,
            details=details,
        )

    @property
    def blocks_success(self) -> bool:
        return self.normalized().severity in {
            SemanticIssueSeverity.ERROR.value,
            SemanticIssueSeverity.FATAL.value,
        }

    def fingerprint(self) -> str:
        normalized = self.normalized()

        return "|".join(
            (
                normalized.code,
                normalized.severity,
                normalized.path or "",
                normalized.field_path or "",
                normalized.module_name or "",
                normalized.message,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "code": normalized.code,
            "message": normalized.message,
            "severity": normalized.severity,
            "path": normalized.path,
            "field_path": normalized.field_path,
            "module_name": normalized.module_name,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class SemanticValidationResult:
    """Ergebnis der semantischen Validierung."""

    issues: tuple[SemanticIssue, ...] = field(default_factory=tuple)
    validation_result: Any | None = None
    status: str = SemanticValidationStatus.VALID.value
    schema_version: str = SEMANTIC_VALIDATOR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SemanticValidationResult":
        issues = dedupe_issues(tuple(issue.normalized() for issue in self.issues or ()))
        status = parse_validation_status_value(self.status)
        metadata = normalize_metadata(self.metadata)
        validation_result = normalize_validation_result(self.validation_result)

        valid = not any(issue.blocks_success for issue in issues)
        if not valid:
            status = SemanticValidationStatus.INVALID.value

        if validation_result is None:
            validation_result = build_validation_result_from_semantic_issues(issues)

        return SemanticValidationResult(
            issues=sort_issues(issues),
            validation_result=validation_result,
            status=status,
            schema_version=self.schema_version or SEMANTIC_VALIDATOR_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def valid(self) -> bool:
        return not any(issue.blocks_success for issue in self.normalized().issues)

    @property
    def issue_count(self) -> int:
        return len(self.normalized().issues)

    @property
    def warnings(self) -> tuple[SemanticIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == SemanticIssueSeverity.WARNING.value
        )

    @property
    def errors(self) -> tuple[SemanticIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == SemanticIssueSeverity.ERROR.value
        )

    @property
    def fatal_errors(self) -> tuple[SemanticIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == SemanticIssueSeverity.FATAL.value
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        validation_payload = (
            normalized.validation_result.to_dict()
            if hasattr(normalized.validation_result, "to_dict")
            else normalized.validation_result
        )

        return {
            "schema_version": normalized.schema_version,
            "status": normalized.status,
            "valid": normalized.valid,
            "issue_count": normalized.issue_count,
            "warning_count": len(normalized.warnings),
            "error_count": len(normalized.errors),
            "fatal_count": len(normalized.fatal_errors),
            "issues": [issue.to_dict() for issue in normalized.issues],
            "validation_result": validation_payload,
            "metadata": dict(normalized.metadata),
        }


def validate_documents_semantics(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SemanticValidationResult:
    """Validiert ein path -> document Mapping semantisch."""
    try:
        normalized_documents = normalize_documents_mapping(documents)
        normalized_options = normalize_options(options)
        issues: list[SemanticIssue] = []

        if normalized_options.require_core_documents:
            issues.extend(validate_required_documents(normalized_documents))

        if normalized_options.validate_identity_consistency:
            issues.extend(validate_identity_consistency(normalized_documents))

        if normalized_options.validate_classification_consistency:
            issues.extend(validate_classification_consistency(normalized_documents))

        if normalized_options.require_active_module_documents:
            issues.extend(validate_module_document_consistency(normalized_documents, options=normalized_options))

        if normalized_options.validate_variant_consistency:
            issues.extend(validate_variant_consistency(normalized_documents))

        if normalized_options.validate_placement_consistency:
            issues.extend(validate_placement_consistency(normalized_documents, options=normalized_options))

        if normalized_options.validate_render_physical_consistency:
            issues.extend(validate_render_physical_consistency(normalized_documents, options=normalized_options))

        if normalized_options.validate_object_kind_rules:
            issues.extend(validate_object_kind_rules(normalized_documents, options=normalized_options))

        if normalized_options.validate_material_consistency:
            issues.extend(validate_material_consistency(normalized_documents, options=normalized_options))

        if normalized_options.validate_calculation_references:
            issues.extend(validate_calculation_references(normalized_documents, options=normalized_options))

        if normalized_options.validate_manufacturer_rules:
            issues.extend(validate_manufacturer_rules(normalized_documents, options=normalized_options))

        if normalized_options.validate_dynamic_rules:
            issues.extend(validate_dynamic_rules(normalized_documents, options=normalized_options))

        if normalized_options.validate_declarative_safety:
            issues.extend(validate_declarative_safety(normalized_documents, options=normalized_options))

        return SemanticValidationResult(
            issues=tuple(issues),
            status=SemanticValidationStatus.VALID.value,
            metadata={
                "source": "documents",
                "document_count": len(normalized_documents),
                **dict(metadata or {}),
            },
        ).normalized()
    except SemanticValidatorError:
        raise
    except Exception as exc:
        return SemanticValidationResult(
            issues=(
                semantic_issue(
                    code=SemanticIssueCode.INTERNAL_ERROR.value,
                    severity=SemanticIssueSeverity.FATAL.value,
                    message=f"Semantic validation failed: {exc}",
                    module_name="system",
                ),
            ),
            status=SemanticValidationStatus.ERROR.value,
            metadata=dict(metadata or {}),
        ).normalized()


def validate_document_bundle_semantics(
    bundle: Any,
    *,
    options: SemanticValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SemanticValidationResult:
    """Validiert ein DocumentBundle-ähnliches Objekt semantisch."""
    try:
        normalized_bundle = normalize_document_bundle(bundle)
        documents = (
            normalized_bundle.to_documents()
            if hasattr(normalized_bundle, "to_documents")
            else normalized_bundle.documents
        )

        return validate_documents_semantics(
            documents,
            options=options,
            metadata={
                "source": "document_bundle",
                "bundle_schema_version": getattr(normalized_bundle, "schema_version", None),
                **dict(metadata or {}),
            },
        ).normalized()
    except SemanticValidatorError:
        raise
    except Exception as exc:
        raise SemanticValidatorError(f"Could not validate document bundle semantics: {exc}") from exc


def validate_creation_plan_semantics(
    creation_plan: Any,
    *,
    options: SemanticValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SemanticValidationResult:
    """Baut ein DocumentBundle aus einem CreationPlan und validiert es semantisch."""
    try:
        from ..defaults.document_bundle import build_document_bundle_from_creation_plan

        bundle = build_document_bundle_from_creation_plan(creation_plan)

        return validate_document_bundle_semantics(
            bundle,
            options=options,
            metadata={
                "source": "creation_plan",
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        raise SemanticValidatorError(f"Could not validate creation plan semantics: {exc}") from exc


def validate_required_documents(documents: Mapping[str, Mapping[str, Any]]) -> tuple[SemanticIssue, ...]:
    """Prüft required Basisdokumente."""
    issues: list[SemanticIssue] = []
    paths = set(documents.keys())

    for path in ROOT_REQUIRED_DOCUMENTS:
        if path not in paths:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.MISSING_DOCUMENT.value,
                    severity=SemanticIssueSeverity.ERROR.value,
                    message=f"Required document {path!r} is missing.",
                    path=path,
                    module_name=infer_module_from_path_safe(path),
                )
            )

    return tuple(issues)


def validate_identity_consistency(documents: Mapping[str, Mapping[str, Any]]) -> tuple[SemanticIssue, ...]:
    """Prüft Manifest/Family/Editor-Identität."""
    issues: list[SemanticIssue] = []

    manifest = documents.get("vplib.manifest.json", {})
    family_identity = documents.get("family/identity.json", {})
    editor_inventory = documents.get("editor/inventory.json", {})

    manifest_family_id = clean_optional_string(manifest.get("family_id"))
    family_id = clean_optional_string(family_identity.get("family_id"))
    inventory_family_id = clean_optional_string(editor_inventory.get("family_id"))

    if manifest_family_id and family_id and manifest_family_id != family_id:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INCONSISTENT_IDENTITY.value,
                message="Manifest family_id does not match family/identity.json family_id.",
                path="family/identity.json",
                field_path="family_id",
                module_name="family",
                details={
                    "manifest_family_id": manifest_family_id,
                    "family_identity_family_id": family_id,
                },
            )
        )

    if family_id and inventory_family_id and family_id != inventory_family_id:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INCONSISTENT_IDENTITY.value,
                message="editor/inventory.json family_id does not match family/identity.json family_id.",
                path="editor/inventory.json",
                field_path="family_id",
                module_name="editor",
                details={
                    "family_identity_family_id": family_id,
                    "inventory_family_id": inventory_family_id,
                },
            )
        )

    manifest_slug = clean_optional_string(manifest.get("family_slug"))
    family_slug = clean_optional_string(family_identity.get("family_slug"))

    if manifest_slug and family_slug and manifest_slug != family_slug:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INCONSISTENT_IDENTITY.value,
                severity=SemanticIssueSeverity.WARNING.value,
                message="Manifest family_slug does not match family/identity.json family_slug.",
                path="family/identity.json",
                field_path="family_slug",
                module_name="family",
                details={
                    "manifest_family_slug": manifest_slug,
                    "family_identity_family_slug": family_slug,
                },
            )
        )

    return tuple(issues)


def validate_classification_consistency(documents: Mapping[str, Mapping[str, Any]]) -> tuple[SemanticIssue, ...]:
    """Prüft Klassifikation über Manifest, Family und Editor."""
    issues: list[SemanticIssue] = []

    manifest = documents.get("vplib.manifest.json", {})
    manifest_classification = manifest.get("classification", {}) if isinstance(manifest.get("classification"), Mapping) else {}
    family_classification = documents.get("family/classification.json", {})
    editor_inventory = documents.get("editor/inventory.json", {})

    manifest_object_kind = clean_optional_string(manifest.get("object_kind"))
    family_object_kind = clean_optional_string(family_classification.get("object_kind"))
    editor_object_kind = clean_optional_string(editor_inventory.get("object_kind"))

    for path, value in (
        ("vplib.manifest.json", manifest_object_kind),
        ("family/classification.json", family_object_kind),
        ("editor/inventory.json", editor_object_kind),
    ):
        if value and value not in OBJECT_KIND_ALLOWED_VALUES:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INCONSISTENT_OBJECT_KIND.value,
                    message=f"Unknown object_kind {value!r}.",
                    path=path,
                    field_path="object_kind",
                    module_name=infer_module_from_path_safe(path),
                )
            )

    if manifest_object_kind and family_object_kind and manifest_object_kind != family_object_kind:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INCONSISTENT_OBJECT_KIND.value,
                message="Manifest object_kind does not match family/classification.json object_kind.",
                path="family/classification.json",
                field_path="object_kind",
                module_name="family",
                details={
                    "manifest_object_kind": manifest_object_kind,
                    "family_object_kind": family_object_kind,
                },
            )
        )

    if family_object_kind and editor_object_kind and family_object_kind != editor_object_kind:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INCONSISTENT_OBJECT_KIND.value,
                message="editor/inventory.json object_kind does not match family/classification.json object_kind.",
                path="editor/inventory.json",
                field_path="object_kind",
                module_name="editor",
                details={
                    "family_object_kind": family_object_kind,
                    "editor_object_kind": editor_object_kind,
                },
            )
        )

    for field_name in ("domain", "category", "subcategory"):
        manifest_value = clean_optional_string(manifest_classification.get(field_name))
        family_value = clean_optional_string(family_classification.get(field_name))
        editor_value = clean_optional_string(editor_inventory.get(field_name))

        if manifest_value and family_value and manifest_value != family_value:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INCONSISTENT_CLASSIFICATION.value,
                    message=f"Manifest classification {field_name} does not match family/classification.json.",
                    path="family/classification.json",
                    field_path=field_name,
                    module_name="family",
                    details={
                        "manifest_value": manifest_value,
                        "family_value": family_value,
                    },
                )
            )

        if family_value and editor_value and family_value != editor_value:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INCONSISTENT_CLASSIFICATION.value,
                    severity=SemanticIssueSeverity.WARNING.value,
                    message=f"editor/inventory.json {field_name} does not match family/classification.json.",
                    path="editor/inventory.json",
                    field_path=field_name,
                    module_name="editor",
                    details={
                        "family_value": family_value,
                        "editor_value": editor_value,
                    },
                )
            )

    return tuple(issues)


def validate_module_document_consistency(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft active_modules gegen vorhandene Modul-Dokumente."""
    issues: list[SemanticIssue] = []
    modules_document = documents.get("vplib.modules.json", {})
    active_modules = normalize_string_tuple(modules_document.get("active_modules", ()) or ())
    required_modules = normalize_string_tuple(modules_document.get("required_modules", ()) or ())
    excluded_modules = set(normalize_string_tuple(modules_document.get("excluded_modules", ()) or ()))

    for module_name in CORE_MODULES:
        if required_modules and module_name not in required_modules:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INCONSISTENT_MODULES.value,
                    severity=SemanticIssueSeverity.ERROR.value,
                    message=f"Core module {module_name!r} must be listed in required_modules.",
                    path="vplib.modules.json",
                    field_path="required_modules",
                    module_name="modules",
                )
            )

    for module_name in required_modules:
        if module_name in excluded_modules:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INCONSISTENT_MODULES.value,
                    message=f"Module {module_name!r} cannot be both required and excluded.",
                    path="vplib.modules.json",
                    field_path="excluded_modules",
                    module_name="modules",
                )
            )

        if module_name not in active_modules:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INCONSISTENT_MODULES.value,
                    message=f"Required module {module_name!r} must also be active.",
                    path="vplib.modules.json",
                    field_path="active_modules",
                    module_name="modules",
                )
            )

    if options.require_active_module_documents:
        for module_name in active_modules:
            for required_path in MODULE_ROOT_DOCUMENTS.get(module_name, tuple()):
                if required_path not in documents:
                    issues.append(
                        semantic_issue(
                            code=SemanticIssueCode.MODULE_DOCUMENT_MISSING.value,
                            severity=SemanticIssueSeverity.ERROR.value,
                            message=f"Active module {module_name!r} is missing required document {required_path!r}.",
                            path=required_path,
                            module_name=module_name,
                        )
                    )

    return tuple(issues)


def validate_variant_consistency(documents: Mapping[str, Mapping[str, Any]]) -> tuple[SemanticIssue, ...]:
    """Prüft variants/index.json gegen Varianten-Dokumente."""
    issues: list[SemanticIssue] = []
    index = documents.get("variants/index.json", {})

    if not index:
        return tuple(issues)

    variant_ids = normalize_string_tuple(index.get("variant_ids", ()) or ())
    default_variant_id = clean_optional_string(index.get("default_variant_id")) or "default"
    variants_entries = index.get("variants", ()) or ()

    if default_variant_id not in variant_ids:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                message="variants/index.json default_variant_id is not listed in variant_ids.",
                path="variants/index.json",
                field_path="default_variant_id",
                module_name="variants",
                details={
                    "default_variant_id": default_variant_id,
                    "variant_ids": list(variant_ids),
                },
            )
        )

    for variant_id in variant_ids:
        variant_path = f"variants/{variant_id}.json"
        if variant_path not in documents:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                    message=f"Variant document {variant_path!r} is missing.",
                    path=variant_path,
                    field_path="variant_id",
                    module_name="variants",
                )
            )
            continue

        variant_doc = documents[variant_path]
        document_variant_id = clean_optional_string(variant_doc.get("variant_id"))
        if document_variant_id != variant_id:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                    message=f"Variant document {variant_path!r} has mismatching variant_id.",
                    path=variant_path,
                    field_path="variant_id",
                    module_name="variants",
                    details={
                        "path_variant_id": variant_id,
                        "document_variant_id": document_variant_id,
                    },
                )
            )

        inherits_from = clean_optional_string(variant_doc.get("inherits_from"))
        if variant_id == default_variant_id and inherits_from:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                    severity=SemanticIssueSeverity.WARNING.value,
                    message="Default variant should not inherit from another variant.",
                    path=variant_path,
                    field_path="inherits_from",
                    module_name="variants",
                )
            )

        if inherits_from and inherits_from not in variant_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                    message=f"Variant {variant_id!r} inherits from unknown variant {inherits_from!r}.",
                    path=variant_path,
                    field_path="inherits_from",
                    module_name="variants",
                )
            )

        overrides = variant_doc.get("overrides", {})
        if not isinstance(overrides, Mapping):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                    message=f"Variant {variant_id!r} overrides must be an object.",
                    path=variant_path,
                    field_path="overrides",
                    module_name="variants",
                )
            )

    seen_entry_ids: set[str] = set()
    for entry in variants_entries:
        if not isinstance(entry, Mapping):
            continue
        entry_id = clean_optional_string(entry.get("variant_id"))
        if not entry_id:
            continue
        if entry_id in seen_entry_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_VARIANT_GRAPH.value,
                    message=f"Duplicate variant entry {entry_id!r} in variants/index.json.",
                    path="variants/index.json",
                    field_path="variants",
                    module_name="variants",
                )
            )
        seen_entry_ids.add(entry_id)

    return tuple(issues)


def validate_placement_consistency(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft editor/placement.json gegen object_kind und Footprint."""
    issues: list[SemanticIssue] = []
    placement = documents.get("editor/placement.json", {})
    family_classification = documents.get("family/classification.json", {})
    manifest = documents.get("vplib.manifest.json", {})

    if not placement:
        return tuple(issues)

    placement_object_kind = clean_optional_string(placement.get("object_kind"))
    expected_object_kind = clean_optional_string(family_classification.get("object_kind")) or clean_optional_string(manifest.get("object_kind"))

    if expected_object_kind and placement_object_kind and expected_object_kind != placement_object_kind:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_PLACEMENT.value,
                message="editor/placement.json object_kind does not match package object_kind.",
                path="editor/placement.json",
                field_path="object_kind",
                module_name="editor",
                details={
                    "expected_object_kind": expected_object_kind,
                    "placement_object_kind": placement_object_kind,
                },
            )
        )

    grid = extract_grid_footprint(placement)
    if grid is None:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_PLACEMENT.value,
                message="editor/placement.json has no valid grid_footprint.",
                path="editor/placement.json",
                field_path="grid_footprint",
                module_name="editor",
            )
        )
        return tuple(issues)

    size_cells_x, size_cells_y, size_cells_z, _cell_size_m = grid

    if min(size_cells_x, size_cells_y, size_cells_z) < 1:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_PLACEMENT.value,
                message="grid_footprint dimensions must be positive.",
                path="editor/placement.json",
                field_path="grid_footprint.size_cells",
                module_name="editor",
            )
        )

    object_kind = expected_object_kind or placement_object_kind
    if object_kind == "cell_block":
        if max(size_cells_x, size_cells_y, size_cells_z) > 1:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_PLACEMENT.value,
                    severity=SemanticIssueSeverity.WARNING.value,
                    message="cell_block should normally use a 1x1x1 grid footprint. Use multi_cell_module for larger footprints.",
                    path="editor/placement.json",
                    field_path="grid_footprint.size_cells",
                    module_name="editor",
                    details={"size_cells": [size_cells_x, size_cells_y, size_cells_z]},
                )
            )

    if object_kind == "multi_cell_module":
        if max(size_cells_x, size_cells_y, size_cells_z) <= 1:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_PLACEMENT.value,
                    message="multi_cell_module must occupy more than one grid cell in at least one dimension.",
                    path="editor/placement.json",
                    field_path="grid_footprint.size_cells",
                    module_name="editor",
                    details={"size_cells": [size_cells_x, size_cells_y, size_cells_z]},
                )
            )

    placement_mode = clean_optional_string(placement.get("placement_mode"))
    if object_kind == "adaptive_system" and placement_mode not in {"surface_aligned", "centered"}:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_PLACEMENT.value,
                severity=SemanticIssueSeverity.WARNING.value,
                message="adaptive_system should use surface_aligned or centered placement.",
                path="editor/placement.json",
                field_path="placement_mode",
                module_name="editor",
                details={"placement_mode": placement_mode},
            )
        )

    if placement.get("grid_footprint_is_placement_truth") is not True:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_PLACEMENT.value,
                severity=SemanticIssueSeverity.ERROR if options.is_strict else SemanticIssueSeverity.WARNING,
                message="editor/placement.json must keep grid_footprint_is_placement_truth=true.",
                path="editor/placement.json",
                field_path="grid_footprint_is_placement_truth",
                module_name="editor",
            )
        )

    return tuple(issues)


def validate_render_physical_consistency(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft Render- und Physical-Bounds gegen Grid-Footprint."""
    issues: list[SemanticIssue] = []
    placement = documents.get("editor/placement.json", {})
    render_bounds = documents.get("render/bounds.json", {})
    physical_bounds = documents.get("physical/bounds.json", {})
    render_variants = documents.get("render/render_variants.json", {})
    physical_dimensions = documents.get("physical/dimensions.json", {})

    grid = extract_grid_footprint(placement)
    if grid is None:
        return tuple(issues)

    max_size_m = grid_size_m(grid)

    if render_bounds:
        bounds = extract_bounds(render_bounds)
        if bounds and not bounds_fit_inside(bounds, max_size_m):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_RENDER.value,
                    message="render/bounds.json exceeds editor grid footprint.",
                    path="render/bounds.json",
                    field_path="size_m",
                    module_name="render",
                    details={
                        "bounds_m": list(bounds),
                        "grid_size_m": list(max_size_m),
                    },
                )
            )

    if physical_bounds:
        bounds = extract_bounds(physical_bounds)
        if bounds and not bounds_fit_inside(bounds, max_size_m):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_PHYSICAL.value,
                    severity=SemanticIssueSeverity.ERROR if options.is_strict else SemanticIssueSeverity.WARNING,
                    message="physical/bounds.json exceeds editor grid footprint.",
                    path="physical/bounds.json",
                    field_path="size_m",
                    module_name="physical",
                    details={
                        "bounds_m": list(bounds),
                        "grid_size_m": list(max_size_m),
                    },
                )
            )

    if physical_dimensions:
        real_dims = extract_real_dimensions(physical_dimensions)
        if real_dims and not bounds_fit_inside(real_dims, max_size_m):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_PHYSICAL.value,
                    severity=SemanticIssueSeverity.WARNING,
                    message="physical/dimensions.json real dimensions exceed editor grid footprint.",
                    path="physical/dimensions.json",
                    field_path="real_dimensions",
                    module_name="physical",
                    details={
                        "real_dimensions_m": list(real_dims),
                        "grid_size_m": list(max_size_m),
                    },
                )
            )

    render_variant_entries = render_variants.get("render_variants", ()) if isinstance(render_variants, Mapping) else ()
    if isinstance(render_variant_entries, list):
        for index, variant in enumerate(render_variant_entries):
            if not isinstance(variant, Mapping):
                continue

            has_texture = bool(clean_optional_string(variant.get("texture_ref")))
            has_model = bool(clean_optional_string(variant.get("glb_ref")) or clean_optional_string(variant.get("model_ref")))
            has_color = bool(clean_optional_string(variant.get("fallback_color")))

            if not has_texture and not has_model and not has_color:
                issues.append(
                    semantic_issue(
                        code=SemanticIssueCode.INVALID_RENDER.value,
                        message="Render variant must define texture_ref, model/glb_ref or fallback_color.",
                        path="render/render_variants.json",
                        field_path=f"render_variants[{index}]",
                        module_name="render",
                    )
                )

            if has_model:
                bounds_data = variant.get("bounds_m")
                if not isinstance(bounds_data, Mapping):
                    issues.append(
                        semantic_issue(
                            code=SemanticIssueCode.INVALID_RENDER.value,
                            message="Render variant with model/glb_ref must define bounds_m.",
                            path="render/render_variants.json",
                            field_path=f"render_variants[{index}].bounds_m",
                            module_name="render",
                        )
                    )
                else:
                    variant_bounds = extract_bounds(bounds_data)
                    if variant_bounds and not bounds_fit_inside(variant_bounds, max_size_m):
                        issues.append(
                            semantic_issue(
                                code=SemanticIssueCode.INVALID_RENDER.value,
                                message="Render variant bounds exceed editor grid footprint.",
                                path="render/render_variants.json",
                                field_path=f"render_variants[{index}].bounds_m",
                                module_name="render",
                                details={
                                    "bounds_m": list(variant_bounds),
                                    "grid_size_m": list(max_size_m),
                                },
                            )
                        )

    return tuple(issues)


def validate_object_kind_rules(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft object_kind-spezifische Regeln."""
    issues: list[SemanticIssue] = []

    object_kind = get_package_object_kind(documents)
    active_modules = get_active_modules(documents)

    if not object_kind:
        return tuple(issues)

    if object_kind in NON_ADAPTIVE_OBJECT_KINDS and "dynamic" in active_modules:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_DYNAMIC.value,
                severity=SemanticIssueSeverity.ERROR if options.is_strict else SemanticIssueSeverity.WARNING,
                message=f"{object_kind} packages should not enable the dynamic module.",
                path="vplib.modules.json",
                field_path="active_modules",
                module_name="modules",
            )
        )

    if object_kind == "adaptive_system" and "dynamic" not in active_modules:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_DYNAMIC.value,
                message="adaptive_system packages must enable the dynamic module.",
                path="vplib.modules.json",
                field_path="active_modules",
                module_name="modules",
            )
        )

    if object_kind in {"cell_block", "multi_cell_module", "catalog_object"}:
        if "render" not in active_modules:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_RENDER.value,
                    message=f"{object_kind} packages should enable the render module.",
                    path="vplib.modules.json",
                    field_path="active_modules",
                    module_name="modules",
                )
            )

        if "physical" not in active_modules:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_PHYSICAL.value,
                    message=f"{object_kind} packages should enable the physical module.",
                    path="vplib.modules.json",
                    field_path="active_modules",
                    module_name="modules",
                )
            )

    return tuple(issues)


def validate_material_consistency(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft Material-/Physical-Konsistenz."""
    issues: list[SemanticIssue] = []
    material_base = documents.get("material/base.json", {})
    material_performance = documents.get("material/performance.json", {})
    physical_mass = documents.get("physical/mass.json", {})
    physical_dimensions = documents.get("physical/dimensions.json", {})

    if not material_base and not material_performance:
        return tuple(issues)

    material_id = clean_optional_string(material_base.get("material_id"))
    material_class = clean_optional_string(material_base.get("material_class"))

    if material_base and not material_id:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_MATERIAL.value,
                message="material/base.json must define material_id.",
                path="material/base.json",
                field_path="material_id",
                module_name="material",
            )
        )

    if material_base and not material_class:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_MATERIAL.value,
                severity=SemanticIssueSeverity.WARNING,
                message="material/base.json should define material_class.",
                path="material/base.json",
                field_path="material_class",
                module_name="material",
            )
        )

    material_density = optional_float(material_performance.get("density_kg_m3"))
    physical_density = optional_float(physical_mass.get("density_kg_m3"))

    if material_density is not None and physical_density is not None:
        if abs(material_density - physical_density) > 1e-9:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_MATERIAL.value,
                    severity=SemanticIssueSeverity.WARNING,
                    message="material/performance.json density_kg_m3 differs from physical/mass.json density_kg_m3.",
                    path="material/performance.json",
                    field_path="density_kg_m3",
                    module_name="material",
                    details={
                        "material_density_kg_m3": material_density,
                        "physical_density_kg_m3": physical_density,
                    },
                )
            )

    mass_kg = optional_float(physical_mass.get("mass_kg"))
    volume_m3 = optional_float(physical_mass.get("volume_m3")) or optional_float(physical_dimensions.get("volume_m3"))

    if mass_kg is not None and volume_m3 is not None and material_density is not None and volume_m3 > 0:
        computed_mass = volume_m3 * material_density
        if abs(computed_mass - mass_kg) > max(0.01, computed_mass * 0.05):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_MATERIAL.value,
                    severity=SemanticIssueSeverity.WARNING,
                    message="physical mass differs significantly from volume * material density.",
                    path="physical/mass.json",
                    field_path="mass_kg",
                    module_name="physical",
                    details={
                        "mass_kg": mass_kg,
                        "volume_m3": volume_m3,
                        "density_kg_m3": material_density,
                        "computed_mass_kg": computed_mass,
                    },
                )
            )

    return tuple(issues)


def validate_calculation_references(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft Calculation-Referenzen."""
    issues: list[SemanticIssue] = []

    variables_doc = documents.get("calculation/variables.json", {})
    formulas_doc = documents.get("calculation/formulas.json", {})
    quantities_doc = documents.get("calculation/quantities.json", {})
    measure_logic_doc = documents.get("calculation/measure_logic.json", {})

    if not variables_doc and not formulas_doc and not quantities_doc:
        return tuple(issues)

    variable_ids = collect_ids(variables_doc.get("variables", ()), "variable_id")
    formula_ids = collect_ids(formulas_doc.get("formulas", ()), "formula_id")
    quantity_ids = collect_ids(quantities_doc.get("quantities", ()), "quantity_id")

    for index, formula in enumerate(formulas_doc.get("formulas", ()) or ()):
        if not isinstance(formula, Mapping):
            continue

        formula_id = clean_optional_string(formula.get("formula_id")) or f"formula_{index}"
        inputs = normalize_string_tuple(formula.get("inputs", ()) or ())
        outputs = normalize_string_tuple(formula.get("outputs", ()) or ())

        for input_id in inputs:
            if input_id not in variable_ids and input_id not in quantity_ids:
                issues.append(
                    semantic_issue(
                        code=SemanticIssueCode.INVALID_CALCULATION.value,
                        message=f"Formula {formula_id!r} references unknown input {input_id!r}.",
                        path="calculation/formulas.json",
                        field_path=f"formulas[{index}].inputs",
                        module_name="calculation",
                    )
                )

        if not outputs:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_CALCULATION.value,
                    message=f"Formula {formula_id!r} must define at least one output.",
                    path="calculation/formulas.json",
                    field_path=f"formulas[{index}].outputs",
                    module_name="calculation",
                )
            )

    for index, quantity in enumerate(quantities_doc.get("quantities", ()) or ()):
        if not isinstance(quantity, Mapping):
            continue

        quantity_id = clean_optional_string(quantity.get("quantity_id")) or f"quantity_{index}"
        source_variable_id = clean_optional_string(quantity.get("source_variable_id"))
        source_formula_id = clean_optional_string(quantity.get("source_formula_id"))
        expression = clean_optional_string(quantity.get("expression"))

        if source_variable_id and source_variable_id not in variable_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_CALCULATION.value,
                    message=f"Quantity {quantity_id!r} references unknown source_variable_id {source_variable_id!r}.",
                    path="calculation/quantities.json",
                    field_path=f"quantities[{index}].source_variable_id",
                    module_name="calculation",
                )
            )

        if source_formula_id and source_formula_id not in formula_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_CALCULATION.value,
                    message=f"Quantity {quantity_id!r} references unknown source_formula_id {source_formula_id!r}.",
                    path="calculation/quantities.json",
                    field_path=f"quantities[{index}].source_formula_id",
                    module_name="calculation",
                )
            )

        if not source_variable_id and not source_formula_id and not expression:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_CALCULATION.value,
                    message=f"Quantity {quantity_id!r} needs expression, source_variable_id or source_formula_id.",
                    path="calculation/quantities.json",
                    field_path=f"quantities[{index}]",
                    module_name="calculation",
                )
            )

    primary_quantity_id = clean_optional_string(measure_logic_doc.get("primary_quantity_id"))
    if primary_quantity_id and primary_quantity_id not in quantity_ids:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_CALCULATION.value,
                message="calculation/measure_logic.json primary_quantity_id references unknown quantity.",
                path="calculation/measure_logic.json",
                field_path="primary_quantity_id",
                module_name="calculation",
                details={"primary_quantity_id": primary_quantity_id},
            )
        )

    return tuple(issues)


def validate_manufacturer_rules(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft Manufacturer-Kontrakt und Override-Slots."""
    issues: list[SemanticIssue] = []
    contract = documents.get("manufacturer/contract.json", {})
    override_slots_doc = documents.get("manufacturer/override_slots.json", {})
    product_fields_doc = documents.get("manufacturer/product_fields.json", {})

    if not contract:
        return tuple(issues)

    manufacturer_allowed = bool(contract.get("manufacturer_allowed", False))
    contract_mode = clean_optional_string(contract.get("contract_mode")) or "disabled"
    allowed_prefixes = normalize_string_tuple(contract.get("allowed_override_prefixes", ()) or ())
    forbidden_prefixes = normalize_string_tuple(contract.get("forbidden_override_prefixes", ()) or ())

    if not manufacturer_allowed and contract_mode != "disabled":
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_MANUFACTURER.value,
                message="manufacturer_allowed=false requires contract_mode='disabled'.",
                path="manufacturer/contract.json",
                field_path="contract_mode",
                module_name="manufacturer",
            )
        )

    override_slots = override_slots_doc.get("override_slots", ()) or ()
    if not manufacturer_allowed and override_slots:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_MANUFACTURER.value,
                message="manufacturer override_slots are defined although manufacturer_allowed=false.",
                path="manufacturer/override_slots.json",
                field_path="override_slots",
                module_name="manufacturer",
            )
        )

    for index, slot in enumerate(override_slots):
        if not isinstance(slot, Mapping):
            continue

        field_path = clean_optional_string(slot.get("field_path"))
        if not field_path:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_MANUFACTURER.value,
                    message="Manufacturer override slot is missing field_path.",
                    path="manufacturer/override_slots.json",
                    field_path=f"override_slots[{index}].field_path",
                    module_name="manufacturer",
                )
            )
            continue

        normalized_field = normalize_field_path(field_path)

        if any(normalized_field == prefix or normalized_field.startswith(f"{prefix}.") for prefix in forbidden_prefixes):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_MANUFACTURER.value,
                    message=f"Manufacturer override field {normalized_field!r} is forbidden by contract.",
                    path="manufacturer/override_slots.json",
                    field_path=f"override_slots[{index}].field_path",
                    module_name="manufacturer",
                )
            )

        if allowed_prefixes and not any(normalized_field == prefix or normalized_field.startswith(f"{prefix}.") for prefix in allowed_prefixes):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_MANUFACTURER.value,
                    message=f"Manufacturer override field {normalized_field!r} is not allowed by contract.",
                    path="manufacturer/override_slots.json",
                    field_path=f"override_slots[{index}].field_path",
                    module_name="manufacturer",
                )
            )

    if contract_mode == "required":
        product_fields = product_fields_doc.get("product_fields", ()) or ()
        required_field_ids = {
            clean_optional_string(item.get("field_id"))
            for item in product_fields
            if isinstance(item, Mapping) and bool(item.get("required", False))
        }
        required_field_ids.discard(None)

        for required_field in ("manufacturer_id", "product_id", "product_name"):
            if required_field not in required_field_ids:
                issues.append(
                    semantic_issue(
                        code=SemanticIssueCode.INVALID_MANUFACTURER.value,
                        message=f"Required manufacturer contract should require product field {required_field!r}.",
                        path="manufacturer/product_fields.json",
                        field_path="product_fields",
                        module_name="manufacturer",
                    )
                )

    return tuple(issues)


def validate_dynamic_rules(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft Dynamic-Modul-Semantik."""
    issues: list[SemanticIssue] = []
    object_kind = get_package_object_kind(documents)
    active_modules = get_active_modules(documents)

    context_rules_doc = documents.get("dynamic/context_rules.json", {})
    bindings_doc = documents.get("dynamic/bindings.json", {})
    generator_doc = documents.get("dynamic/generator.json", {})

    if object_kind == "adaptive_system":
        for path in MODULE_ROOT_DOCUMENTS["dynamic"]:
            if path not in documents:
                issues.append(
                    semantic_issue(
                        code=SemanticIssueCode.INVALID_DYNAMIC.value,
                        message=f"adaptive_system package requires dynamic document {path!r}.",
                        path=path,
                        module_name="dynamic",
                    )
                )

    if "dynamic" not in active_modules:
        return tuple(issues)

    if generator_doc and generator_doc.get("declarative_only") is not True:
        issues.append(
            semantic_issue(
                code=SemanticIssueCode.INVALID_DYNAMIC.value,
                message="dynamic/generator.json must set declarative_only=true.",
                path="dynamic/generator.json",
                field_path="declarative_only",
                module_name="dynamic",
            )
        )

    rule_ids = collect_ids(context_rules_doc.get("context_rules", ()) or (), "rule_id")
    binding_ids = collect_ids(bindings_doc.get("bindings", ()) or (), "binding_id")
    parameter_ids = collect_ids(documents.get("dynamic/parameters.json", {}).get("parameters", ()) or (), "parameter_id")

    input_parameters = normalize_string_tuple(generator_doc.get("input_parameters", ()) or ())
    for parameter_id in input_parameters:
        if parameter_ids and parameter_id not in parameter_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_DYNAMIC.value,
                    message=f"Dynamic generator references unknown input parameter {parameter_id!r}.",
                    path="dynamic/generator.json",
                    field_path="input_parameters",
                    module_name="dynamic",
                )
            )

    rule_graph_doc = documents.get("dynamic/rule_graph.json", {})
    for index, node in enumerate(rule_graph_doc.get("nodes", ()) or ()):
        if not isinstance(node, Mapping):
            continue

        rule_ref = clean_optional_string(node.get("rule_ref"))
        binding_ref = clean_optional_string(node.get("binding_ref"))
        parameter_ref = clean_optional_string(node.get("parameter_ref"))

        if rule_ref and rule_ids and rule_ref not in rule_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_DYNAMIC.value,
                    message=f"Rule graph node references unknown rule_ref {rule_ref!r}.",
                    path="dynamic/rule_graph.json",
                    field_path=f"nodes[{index}].rule_ref",
                    module_name="dynamic",
                )
            )

        if binding_ref and binding_ids and binding_ref not in binding_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_DYNAMIC.value,
                    message=f"Rule graph node references unknown binding_ref {binding_ref!r}.",
                    path="dynamic/rule_graph.json",
                    field_path=f"nodes[{index}].binding_ref",
                    module_name="dynamic",
                )
            )

        if parameter_ref and parameter_ids and parameter_ref not in parameter_ids:
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.INVALID_DYNAMIC.value,
                    message=f"Rule graph node references unknown parameter_ref {parameter_ref!r}.",
                    path="dynamic/rule_graph.json",
                    field_path=f"nodes[{index}].parameter_ref",
                    module_name="dynamic",
                )
            )

    return tuple(issues)


def validate_declarative_safety(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SemanticValidationOptions,
) -> tuple[SemanticIssue, ...]:
    """Prüft verbotene ausführbare Referenzen und Expressions."""
    issues: list[SemanticIssue] = []

    for path, document in documents.items():
        issues.extend(scan_document_for_executable_content(path, document))

    return tuple(issues)


def scan_document_for_executable_content(
    path: str,
    value: Any,
    *,
    field_path: str = "",
) -> tuple[SemanticIssue, ...]:
    """Scannt ein Dokument rekursiv auf offensichtliche ausführbare Inhalte."""
    issues: list[SemanticIssue] = []

    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{field_path}.{key}" if field_path else str(key)
            issues.extend(scan_document_for_executable_content(path, child, field_path=child_path))
        return tuple(issues)

    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{field_path}[{index}]"
            issues.extend(scan_document_for_executable_content(path, child, field_path=child_path))
        return tuple(issues)

    if isinstance(value, str):
        lowered = value.lower().strip()

        if any(lowered.endswith(extension) for extension in EXECUTABLE_FILE_EXTENSIONS):
            issues.append(
                semantic_issue(
                    code=SemanticIssueCode.EXECUTABLE_CONTENT.value,
                    message=f"Executable file reference is not allowed: {value!r}.",
                    severity=SemanticIssueSeverity.FATAL.value,
                    path=path,
                    field_path=field_path,
                    module_name=infer_module_from_path_safe(path),
                )
            )

        if field_path.endswith("expression") or ".expression" in field_path or field_path.endswith("_expression"):
            for token in DECLARATIVE_FORBIDDEN_TOKENS:
                if token in lowered:
                    issues.append(
                        semantic_issue(
                            code=SemanticIssueCode.EXECUTABLE_CONTENT.value,
                            message=f"Declarative expression contains forbidden token {token!r}.",
                            severity=SemanticIssueSeverity.FATAL.value,
                            path=path,
                            field_path=field_path,
                            module_name=infer_module_from_path_safe(path),
                        )
                    )

    return tuple(issues)


def build_validation_result_from_semantic_issues(issues: Iterable[SemanticIssue]) -> Any:
    """Baut ein ValidationResult aus semantischen Issues."""
    try:
        from ..models.validation_result import (
            ValidationIssue,
            ValidationScope,
            invalid_result,
            valid_result,
        )

        normalized_issues = tuple(issue.normalized() for issue in issues or ())

        if not normalized_issues:
            return valid_result(
                metadata={
                    "source": "semantic_validator",
                    "schema_version": SEMANTIC_VALIDATOR_SCHEMA_VERSION,
                }
            )

        validation_issues = tuple(
            ValidationIssue(
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
                scope=ValidationScope.PACKAGE.value,
                path=issue.path,
                field_path=issue.field_path,
                module_name=issue.module_name,
                details=issue.details,
            ).normalized()
            for issue in normalized_issues
        )

        return invalid_result(
            validation_issues,
            metadata={
                "source": "semantic_validator",
                "schema_version": SEMANTIC_VALIDATOR_SCHEMA_VERSION,
            },
        )
    except Exception:
        normalized_issues = tuple(issue.normalized() for issue in issues or ())
        return {
            "schema_version": SEMANTIC_VALIDATOR_SCHEMA_VERSION,
            "valid": not any(issue.blocks_success for issue in normalized_issues),
            "issues": [issue.to_dict() for issue in normalized_issues],
        }


def semantic_issue(
    *,
    code: str,
    message: str,
    severity: str = SemanticIssueSeverity.ERROR.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> SemanticIssue:
    """Factory für SemanticIssue."""
    return SemanticIssue(
        code=code,
        message=message,
        severity=severity,
        path=path,
        field_path=field_path,
        module_name=module_name,
        details=dict(details or {}),
    ).normalized()


def get_package_object_kind(documents: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Liest object_kind aus Manifest oder Family."""
    manifest = documents.get("vplib.manifest.json", {})
    family_classification = documents.get("family/classification.json", {})

    return (
        clean_optional_string(manifest.get("object_kind"))
        or clean_optional_string(family_classification.get("object_kind"))
    )


def get_active_modules(documents: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    """Liest active_modules aus vplib.modules.json."""
    modules_document = documents.get("vplib.modules.json", {})
    return normalize_string_tuple(modules_document.get("active_modules", ()) or ())


def extract_grid_footprint(placement_document: Mapping[str, Any]) -> tuple[int, int, int, float] | None:
    """Extrahiert Grid-Footprint als x, y, z, cell_size_m."""
    try:
        grid = placement_document.get("grid_footprint")
        if not isinstance(grid, Mapping):
            return None

        size_cells = grid.get("size_cells", {})
        if not isinstance(size_cells, Mapping):
            size_cells = {}

        x = int(grid.get("size_cells_x", size_cells.get("x", 1)))
        y = int(grid.get("size_cells_y", size_cells.get("y", 1)))
        z = int(grid.get("size_cells_z", size_cells.get("z", 1)))
        cell_size_m = float(grid.get("cell_size_m", 1.0))

        return (x, y, z, cell_size_m)
    except Exception:
        return None


def grid_size_m(grid: tuple[int, int, int, float]) -> tuple[float, float, float]:
    """Wandelt Grid-Footprint in Metergröße."""
    x, y, z, cell_size_m = grid
    return (x * cell_size_m, y * cell_size_m, z * cell_size_m)


def extract_bounds(document: Mapping[str, Any]) -> tuple[float, float, float] | None:
    """Extrahiert Bounds aus Mapping."""
    try:
        size_m = document.get("size_m")
        if isinstance(size_m, Mapping):
            return (
                float(size_m.get("x")),
                float(size_m.get("y")),
                float(size_m.get("z")),
            )

        return (
            float(document.get("width_m")),
            float(document.get("height_m")),
            float(document.get("depth_m")),
        )
    except Exception:
        return None


def extract_real_dimensions(document: Mapping[str, Any]) -> tuple[float, float, float] | None:
    """Extrahiert reale Dimensionen aus physical/dimensions.json."""
    try:
        real_dimensions = document.get("real_dimensions")
        if isinstance(real_dimensions, Mapping):
            return (
                float(real_dimensions.get("width_m")),
                float(real_dimensions.get("height_m")),
                float(real_dimensions.get("depth_m")),
            )

        return (
            float(document.get("real_width_m")),
            float(document.get("real_height_m")),
            float(document.get("real_depth_m")),
        )
    except Exception:
        return None


def bounds_fit_inside(bounds: tuple[float, float, float], max_size: tuple[float, float, float]) -> bool:
    """Prüft, ob Bounds in Maximalgröße passen."""
    return (
        bounds[0] <= max_size[0]
        and bounds[1] <= max_size[1]
        and bounds[2] <= max_size[2]
    )


def collect_ids(values: Any, key: str) -> set[str]:
    """Sammelt IDs aus einer Liste von Mappings."""
    ids: set[str] = set()

    if not isinstance(values, list):
        return ids

    for item in values:
        if not isinstance(item, Mapping):
            continue
        value = clean_optional_string(item.get(key))
        if value:
            ids.add(value)

    return ids


def optional_float(value: Any) -> float | None:
    """Parst optionalen Float."""
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def normalize_documents_mapping(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalisiert documents Mapping JSON-kompatibel."""
    if not isinstance(documents, Mapping):
        raise SemanticValidatorError("documents must be a mapping.")

    return {
        normalize_package_path(path): normalize_document_mapping(document)
        for path, document in documents.items()
    }


def normalize_document_mapping(document: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert ein Dokument-Mapping."""
    if not isinstance(document, Mapping):
        raise SemanticValidatorError("document must be a mapping.")

    return {
        str(key): normalize_json_value(value)
        for key, value in document.items()
    }


def normalize_document_bundle(value: Any) -> Any:
    """Normalisiert DocumentBundle-ähnliche Werte."""
    try:
        from ..defaults.document_bundle import DocumentBundle, build_document_bundle_from_components

        if isinstance(value, DocumentBundle):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping):
            return build_document_bundle_from_components(documents=value).normalized()

        raise SemanticValidatorError("DocumentBundle value is required.")
    except SemanticValidatorError:
        raise
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid DocumentBundle: {exc}") from exc


def normalize_validation_result(value: Any) -> Any | None:
    """Normalisiert optional ein ValidationResult."""
    if value is None:
        return None

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping):
            from ..models.validation_result import validation_result_from_mapping

            return validation_result_from_mapping(value).normalized()

        return value
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid ValidationResult: {exc}") from exc


def normalize_options(
    options: SemanticValidationOptions | Mapping[str, Any] | None,
) -> SemanticValidationOptions:
    """Normalisiert SemanticValidationOptions."""
    if options is None:
        return SemanticValidationOptions().normalized()

    if isinstance(options, SemanticValidationOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return SemanticValidationOptions(
            mode=options.get("mode", SemanticValidationMode.STRICT.value),
            require_core_documents=bool(options.get("require_core_documents", True)),
            require_active_module_documents=bool(options.get("require_active_module_documents", True)),
            validate_identity_consistency=bool(options.get("validate_identity_consistency", True)),
            validate_classification_consistency=bool(options.get("validate_classification_consistency", True)),
            validate_object_kind_rules=bool(options.get("validate_object_kind_rules", True)),
            validate_variant_consistency=bool(options.get("validate_variant_consistency", True)),
            validate_placement_consistency=bool(options.get("validate_placement_consistency", True)),
            validate_render_physical_consistency=bool(options.get("validate_render_physical_consistency", True)),
            validate_material_consistency=bool(options.get("validate_material_consistency", True)),
            validate_calculation_references=bool(options.get("validate_calculation_references", True)),
            validate_manufacturer_rules=bool(options.get("validate_manufacturer_rules", True)),
            validate_dynamic_rules=bool(options.get("validate_dynamic_rules", True)),
            validate_declarative_safety=bool(options.get("validate_declarative_safety", True)),
            collect_all_errors=bool(options.get("collect_all_errors", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise SemanticValidatorError("options must be SemanticValidationOptions, mapping or None.")


def normalize_package_path(value: Any) -> str:
    """Normalisiert package-relative Pfade."""
    try:
        from ..domain.package_paths import normalize_package_path as normalize

        raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

        if raw in ROOT_REQUIRED_DOCUMENTS:
            return raw

        return normalize(raw)
    except Exception:
        raw = clean_required_string(value, "relative_path").replace("\\", "/").strip().strip("/")

        if not raw or raw.startswith("../") or "/../" in raw:
            raise SemanticValidatorError(f"Invalid package path {value!r}.")

        return raw


def infer_module_from_path_safe(path: Any) -> str | None:
    """Leitet Modul aus package-relativem Pfad ab."""
    try:
        raw = normalize_package_path(path)

        if raw == "vplib.manifest.json":
            return "manifest"
        if raw == "vplib.modules.json":
            return "modules"

        from ..domain.package_paths import infer_module_from_path

        return infer_module_from_path(raw)
    except Exception:
        try:
            raw = str(path).replace("\\", "/").strip()
            if raw == "vplib.manifest.json":
                return "manifest"
            if raw == "vplib.modules.json":
                return "modules"
            return raw.split("/", 1)[0] if "/" in raw else None
        except Exception:
            return None


def normalize_optional_module_name(value: Any) -> str | None:
    """Normalisiert optionalen Modulnamen."""
    if value is None:
        return None

    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception:
        return clean_optional_string(value)


def normalize_field_path(value: Any) -> str:
    """Normalisiert Field-Path."""
    raw = clean_required_string(value, "field_path")
    field_path = raw.strip().replace(" ", "_").replace("/", ".").replace("\\", ".")

    if not SAFE_FIELD_PATH_RE.match(field_path):
        raise SemanticValidatorError(f"Unsafe field_path {value!r}.")

    return field_path


def normalize_optional_field_path(value: Any) -> str | None:
    """Normalisiert optionalen Field-Path."""
    if value is None:
        return None

    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    return normalize_field_path(cleaned)


def normalize_json_value(value: Any) -> Any:
    """Normalisiert JSON-kompatible Werte."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return {
            str(key): normalize_json_value(child_value)
            for key, child_value in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [normalize_json_value(item) for item in value]

    return str(value)


@lru_cache(maxsize=128)
def parse_validation_mode_value(value: Any) -> str:
    """Parst SemanticValidationMode."""
    try:
        if isinstance(value, SemanticValidationMode):
            return value.value

        raw = normalize_enum_key(value)
        return SemanticValidationMode(raw).value
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid semantic validation mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_status_value(value: Any) -> str:
    """Parst SemanticValidationStatus."""
    try:
        if isinstance(value, SemanticValidationStatus):
            return value.value

        raw = normalize_enum_key(value)
        return SemanticValidationStatus(raw).value
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid semantic validation status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_issue_severity_value(value: Any) -> str:
    """Parst SemanticIssueSeverity."""
    try:
        if isinstance(value, SemanticIssueSeverity):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "info": SemanticIssueSeverity.INFO.value,
            "warning": SemanticIssueSeverity.WARNING.value,
            "warn": SemanticIssueSeverity.WARNING.value,
            "error": SemanticIssueSeverity.ERROR.value,
            "fatal": SemanticIssueSeverity.FATAL.value,
            "critical": SemanticIssueSeverity.FATAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return SemanticIssueSeverity(raw).value
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid semantic issue severity {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_issue_code_value(value: Any) -> str:
    """Parst SemanticIssueCode."""
    try:
        if isinstance(value, SemanticIssueCode):
            return value.value

        raw = str(value).strip().upper().replace(" ", "_").replace("-", "_")
        if not raw:
            raise SemanticValidatorError("Issue code is required.")

        if not raw.startswith("VPLIB_"):
            raw = f"VPLIB_SEMANTIC_{raw}"

        try:
            return SemanticIssueCode(raw).value
        except ValueError:
            return raw
    except SemanticValidatorError:
        raise
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid semantic issue code {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise SemanticValidatorError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except SemanticValidatorError:
        raise
    except Exception as exc:
        raise SemanticValidatorError(f"Invalid enum value {value!r}.") from exc


def normalize_string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Stringlisten ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise SemanticValidatorError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def dedupe_issues(issues: Iterable[SemanticIssue]) -> tuple[SemanticIssue, ...]:
    """Dedupliziert Issues."""
    result: list[SemanticIssue] = []
    seen: set[str] = set()

    for issue in issues or ():
        normalized = issue.normalized()
        fingerprint = normalized.fingerprint()

        if fingerprint in seen:
            continue

        result.append(normalized)
        seen.add(fingerprint)

    return tuple(result)


def sort_issues(issues: Iterable[SemanticIssue]) -> tuple[SemanticIssue, ...]:
    """Sortiert Issues stabil."""
    severity_order = {
        SemanticIssueSeverity.FATAL.value: 10,
        SemanticIssueSeverity.ERROR.value: 20,
        SemanticIssueSeverity.WARNING.value: 30,
        SemanticIssueSeverity.INFO.value: 40,
    }

    return tuple(
        sorted(
            (issue.normalized() for issue in issues or ()),
            key=lambda issue: (
                severity_order.get(issue.severity, 99),
                issue.module_name or "",
                issue.path or "",
                issue.field_path or "",
                issue.code,
                issue.message,
            ),
        )
    )


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise SemanticValidatorError(f"{field_name} is required.")

        return cleaned
    except SemanticValidatorError:
        raise
    except Exception as exc:
        raise SemanticValidatorError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_semantic_validator_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_validation_mode_value.cache_clear()
    parse_validation_status_value.cache_clear()
    parse_issue_severity_value.cache_clear()
    parse_issue_code_value.cache_clear()


__all__ = [
    "CORE_MODULES",
    "DECLARATIVE_FORBIDDEN_TOKENS",
    "EXECUTABLE_FILE_EXTENSIONS",
    "MODULE_ROOT_DOCUMENTS",
    "NON_ADAPTIVE_OBJECT_KINDS",
    "OBJECT_KIND_ALLOWED_VALUES",
    "ROOT_REQUIRED_DOCUMENTS",
    "SAFE_FIELD_PATH_RE",
    "SEMANTIC_VALIDATOR_SCHEMA_VERSION",
    "SemanticIssue",
    "SemanticIssueCode",
    "SemanticIssueSeverity",
    "SemanticValidationMode",
    "SemanticValidationOptions",
    "SemanticValidationResult",
    "SemanticValidationStatus",
    "SemanticValidatorError",
    "bounds_fit_inside",
    "build_validation_result_from_semantic_issues",
    "clean_optional_string",
    "clean_required_string",
    "clear_semantic_validator_caches",
    "collect_ids",
    "dedupe_issues",
    "extract_bounds",
    "extract_grid_footprint",
    "extract_real_dimensions",
    "get_active_modules",
    "get_package_object_kind",
    "grid_size_m",
    "infer_module_from_path_safe",
    "normalize_document_bundle",
    "normalize_document_mapping",
    "normalize_documents_mapping",
    "normalize_enum_key",
    "normalize_field_path",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_optional_field_path",
    "normalize_optional_module_name",
    "normalize_options",
    "normalize_package_path",
    "normalize_string_tuple",
    "normalize_validation_result",
    "optional_float",
    "parse_issue_code_value",
    "parse_issue_severity_value",
    "parse_validation_mode_value",
    "parse_validation_status_value",
    "scan_document_for_executable_content",
    "semantic_issue",
    "sort_issues",
    "validate_calculation_references",
    "validate_classification_consistency",
    "validate_creation_plan_semantics",
    "validate_declarative_safety",
    "validate_document_bundle_semantics",
    "validate_documents_semantics",
    "validate_dynamic_rules",
    "validate_identity_consistency",
    "validate_manufacturer_rules",
    "validate_material_consistency",
    "validate_module_document_consistency",
    "validate_object_kind_rules",
    "validate_placement_consistency",
    "validate_render_physical_consistency",
    "validate_required_documents",
    "validate_variant_consistency",
]