# services/vectoplan-library/src/vplib/validators/package_validator.py
"""
Package validator for the VPLIB package engine.

Diese Datei orchestriert die vollständige VPLIB-Package-Validierung.

Rolle dieser Datei:

    CreationPlan / DocumentBundle / documents mapping / PackagePlan
    -> PackageValidationResult
    -> ValidationResult

Diese Datei kombiniert:
- schema_validator
- semantic_validator
- asset_validator
- package plan consistency checks
- path/document consistency checks
- module/document consistency checks
- archive/package metadata checks
- VPLIB package identity checks

Diese Datei schreibt keine Dateien und liest keine Dateien vom Dateisystem.
Sie validiert nur bereits vorhandene Plan-, Bundle- und Dokumentdaten.

Wichtig für die neue VPLIB-ID-Architektur:
- `vplib.manifest.json` muss eine gültige `vplib_uid` enthalten.
- Fehlende oder ungültige `vplib_uid` blockiert die Package-Validierung.
- Die Datenbank erzeugt später keine eigene fachliche Block-ID.
- Die Datenbank übernimmt `vplib_uid` nur aus dem validierten VPLIB-Manifest.
- `package_id`, `family_id` und `family_slug` bleiben semantische IDs, sind aber
  nicht die unveränderliche technische Package-ID.
- Bei direkter Dokumentvalidierung wird eine fehlende `vplib_uid` nicht erzeugt,
  sondern als Fehler gemeldet. Erzeugung passiert im Manifest-/Bundle-/Create-Flow.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


PACKAGE_VALIDATOR_SCHEMA_VERSION: Final[str] = "vplib.package_validator.v1"

MANIFEST_DOCUMENT_PATH: Final[str] = "vplib.manifest.json"
MODULES_DOCUMENT_PATH: Final[str] = "vplib.modules.json"
MANIFEST_VPLIB_UID_FIELD: Final[str] = "vplib_uid"

ROOT_REQUIRED_DOCUMENTS: Final[tuple[str, ...]] = (
    MANIFEST_DOCUMENT_PATH,
    MODULES_DOCUMENT_PATH,
)

CORE_REQUIRED_DOCUMENTS: Final[tuple[str, ...]] = (
    MANIFEST_DOCUMENT_PATH,
    MODULES_DOCUMENT_PATH,
    "family/identity.json",
    "family/classification.json",
    "variants/index.json",
    "variants/default.json",
    "editor/inventory.json",
    "editor/placement.json",
    "manufacturer/contract.json",
)

PACKAGE_ARCHIVE_EXTENSION: Final[str] = ".vplib"

KNOWN_MODULE_ORDER: Final[dict[str, int]] = {
    "manifest": 10,
    "modules": 20,
    "family": 30,
    "variants": 40,
    "editor": 50,
    "render": 60,
    "physical": 70,
    "material": 80,
    "calculation": 90,
    "analysis": 100,
    "dynamic": 110,
    "manufacturer": 120,
    "docs": 130,
    "tests": 140,
}


class PackageValidatorError(ValueError):
    """Wird ausgelöst, wenn die Package-Validierung selbst fehlschlägt."""


class PackageValidationStatus(str, Enum):
    """Status einer Package-Validierung."""

    VALID = "valid"
    INVALID = "invalid"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class PackageValidationMode(str, Enum):
    """Validierungsmodus."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


class PackageValidationPhase(str, Enum):
    """Phase der Package-Validierung."""

    INPUT = "input"
    PLAN = "plan"
    DOCUMENTS = "documents"
    SCHEMA = "schema"
    SEMANTIC = "semantic"
    ASSET = "asset"
    PACKAGE = "package"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class PackageIssueSeverity(str, Enum):
    """Schweregrad eines Package-Issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class PackageIssueCode(str, Enum):
    """Package-Issue-Codes."""

    UNKNOWN = "VPLIB_PACKAGE_UNKNOWN"
    INVALID_INPUT = "VPLIB_PACKAGE_INVALID_INPUT"
    INVALID_PLAN = "VPLIB_PACKAGE_INVALID_PLAN"
    INVALID_PACKAGE_PATH = "VPLIB_PACKAGE_INVALID_PACKAGE_PATH"
    INVALID_ARCHIVE_PATH = "VPLIB_PACKAGE_INVALID_ARCHIVE_PATH"
    MISSING_DOCUMENT = "VPLIB_PACKAGE_MISSING_DOCUMENT"
    UNPLANNED_DOCUMENT = "VPLIB_PACKAGE_UNPLANNED_DOCUMENT"
    PLANNED_DOCUMENT_MISSING = "VPLIB_PACKAGE_PLANNED_DOCUMENT_MISSING"
    DUPLICATE_PATH = "VPLIB_PACKAGE_DUPLICATE_PATH"
    MODULE_MISMATCH = "VPLIB_PACKAGE_MODULE_MISMATCH"
    PROFILE_MISMATCH = "VPLIB_PACKAGE_PROFILE_MISMATCH"
    OBJECT_KIND_MISMATCH = "VPLIB_PACKAGE_OBJECT_KIND_MISMATCH"
    PACKAGE_ID_MISMATCH = "VPLIB_PACKAGE_ID_MISMATCH"
    MISSING_VPLIB_UID = "VPLIB_PACKAGE_MISSING_VPLIB_UID"
    INVALID_VPLIB_UID = "VPLIB_PACKAGE_INVALID_VPLIB_UID"
    VPLIB_UID_MISMATCH = "VPLIB_PACKAGE_VPLIB_UID_MISMATCH"
    VALIDATION_FAILED = "VPLIB_PACKAGE_VALIDATION_FAILED"
    SCHEMA_VALIDATION_FAILED = "VPLIB_PACKAGE_SCHEMA_VALIDATION_FAILED"
    SEMANTIC_VALIDATION_FAILED = "VPLIB_PACKAGE_SEMANTIC_VALIDATION_FAILED"
    ASSET_VALIDATION_FAILED = "VPLIB_PACKAGE_ASSET_VALIDATION_FAILED"
    INTERNAL_ERROR = "VPLIB_PACKAGE_INTERNAL_ERROR"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PackageValidationOptions:
    """Optionen für die vollständige Package-Validierung."""

    mode: str = PackageValidationMode.STRICT.value
    validate_schema: bool = True
    validate_semantics: bool = True
    validate_assets: bool = True
    validate_package_plan: bool = True
    validate_document_paths: bool = True
    validate_required_documents: bool = True
    validate_vplib_uid: bool = True
    validate_profile_consistency: bool = True
    validate_archive_path: bool = True
    allow_unplanned_documents: bool = True
    require_documents_for_planned_files: bool = True
    collect_all_errors: bool = True
    strict: bool = True
    schema_options: Mapping[str, Any] = field(default_factory=dict)
    semantic_options: Mapping[str, Any] = field(default_factory=dict)
    asset_options: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageValidationOptions":
        mode = parse_validation_mode_value(self.mode)

        return PackageValidationOptions(
            mode=mode,
            validate_schema=bool(self.validate_schema),
            validate_semantics=bool(self.validate_semantics),
            validate_assets=bool(self.validate_assets),
            validate_package_plan=bool(self.validate_package_plan),
            validate_document_paths=bool(self.validate_document_paths),
            validate_required_documents=bool(self.validate_required_documents),
            validate_vplib_uid=bool(self.validate_vplib_uid),
            validate_profile_consistency=bool(self.validate_profile_consistency),
            validate_archive_path=bool(self.validate_archive_path),
            allow_unplanned_documents=bool(self.allow_unplanned_documents),
            require_documents_for_planned_files=bool(self.require_documents_for_planned_files),
            collect_all_errors=bool(self.collect_all_errors),
            strict=bool(self.strict),
            schema_options=normalize_metadata(self.schema_options),
            semantic_options=normalize_metadata(self.semantic_options),
            asset_options=normalize_metadata(self.asset_options),
        )

    @property
    def is_strict(self) -> bool:
        return self.normalized().mode == PackageValidationMode.STRICT.value

    @property
    def is_permissive(self) -> bool:
        return self.normalized().mode == PackageValidationMode.PERMISSIVE.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "mode": normalized.mode,
            "validate_schema": normalized.validate_schema,
            "validate_semantics": normalized.validate_semantics,
            "validate_assets": normalized.validate_assets,
            "validate_package_plan": normalized.validate_package_plan,
            "validate_document_paths": normalized.validate_document_paths,
            "validate_required_documents": normalized.validate_required_documents,
            "validate_vplib_uid": normalized.validate_vplib_uid,
            "validate_profile_consistency": normalized.validate_profile_consistency,
            "validate_archive_path": normalized.validate_archive_path,
            "allow_unplanned_documents": normalized.allow_unplanned_documents,
            "require_documents_for_planned_files": normalized.require_documents_for_planned_files,
            "collect_all_errors": normalized.collect_all_errors,
            "strict": normalized.strict,
            "schema_options": dict(normalized.schema_options),
            "semantic_options": dict(normalized.semantic_options),
            "asset_options": dict(normalized.asset_options),
        }


@dataclass(frozen=True, slots=True)
class PackageIssue:
    """Ein einzelnes Package-Issue."""

    code: str
    message: str
    severity: str = PackageIssueSeverity.ERROR.value
    phase: str = PackageValidationPhase.PACKAGE.value
    path: str | None = None
    field_path: str | None = None
    module_name: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageIssue":
        code = parse_issue_code_value(self.code)
        message = clean_required_string(self.message, "message")
        severity = parse_issue_severity_value(self.severity)
        phase = parse_validation_phase_value(self.phase)
        path = clean_optional_string(self.path)
        field_path = clean_optional_string(self.field_path)
        module_name = normalize_optional_module_name(self.module_name)
        details = normalize_metadata(self.details)

        return PackageIssue(
            code=code,
            message=message,
            severity=severity,
            phase=phase,
            path=path,
            field_path=field_path,
            module_name=module_name,
            details=details,
        )

    @property
    def blocks_success(self) -> bool:
        return self.normalized().severity in {
            PackageIssueSeverity.ERROR.value,
            PackageIssueSeverity.FATAL.value,
        }

    def fingerprint(self) -> str:
        normalized = self.normalized()

        return "|".join(
            (
                normalized.code,
                normalized.severity,
                normalized.phase,
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
            "phase": normalized.phase,
            "path": normalized.path,
            "field_path": normalized.field_path,
            "module_name": normalized.module_name,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class PackageValidationResult:
    """Ergebnis der vollständigen Package-Validierung."""

    issues: tuple[PackageIssue, ...] = field(default_factory=tuple)
    schema_result: Any | None = None
    semantic_result: Any | None = None
    asset_result: Any | None = None
    validation_result: Any | None = None
    status: str = PackageValidationStatus.VALID.value
    schema_version: str = PACKAGE_VALIDATOR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "PackageValidationResult":
        issues = sort_issues(dedupe_issues(tuple(issue.normalized() for issue in self.issues or ())))
        schema_result = normalize_sub_result(self.schema_result)
        semantic_result = normalize_sub_result(self.semantic_result)
        asset_result = normalize_sub_result(self.asset_result)
        validation_result = normalize_validation_result(self.validation_result)
        status = parse_validation_status_value(self.status)
        metadata = normalize_metadata(self.metadata)

        valid = not any(issue.blocks_success for issue in issues)
        valid = valid and sub_result_is_valid(schema_result)
        valid = valid and sub_result_is_valid(semantic_result)
        valid = valid and sub_result_is_valid(asset_result)

        if not valid:
            status = PackageValidationStatus.INVALID.value

        if validation_result is None:
            validation_result = build_validation_result_from_package_result(
                issues=issues,
                schema_result=schema_result,
                semantic_result=semantic_result,
                asset_result=asset_result,
                metadata=metadata,
            )

        return PackageValidationResult(
            issues=issues,
            schema_result=schema_result,
            semantic_result=semantic_result,
            asset_result=asset_result,
            validation_result=validation_result,
            status=status,
            schema_version=self.schema_version or PACKAGE_VALIDATOR_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def valid(self) -> bool:
        normalized = self.normalized()
        return normalized.status == PackageValidationStatus.VALID.value

    @property
    def issue_count(self) -> int:
        return len(self.normalized().issues)

    @property
    def warnings(self) -> tuple[PackageIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == PackageIssueSeverity.WARNING.value
        )

    @property
    def errors(self) -> tuple[PackageIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == PackageIssueSeverity.ERROR.value
        )

    @property
    def fatal_errors(self) -> tuple[PackageIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == PackageIssueSeverity.FATAL.value
        )

    @property
    def vplib_uid(self) -> str | None:
        """Liest `vplib_uid` aus den Result-Metadaten."""
        try:
            return normalize_vplib_uid_safe(self.normalized().metadata.get(MANIFEST_VPLIB_UID_FIELD))
        except Exception:
            return None

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()
        uid = normalize_vplib_uid_safe(normalized.metadata.get(MANIFEST_VPLIB_UID_FIELD))

        return {
            "schema_version": normalized.schema_version,
            "status": normalized.status,
            "valid": normalized.valid,
            "vplib_uid": uid,
            "issue_count": normalized.issue_count,
            "warning_count": len(normalized.warnings),
            "error_count": len(normalized.errors),
            "fatal_count": len(normalized.fatal_errors),
            "issues": [issue.to_dict() for issue in normalized.issues],
            "schema_result": sub_result_to_dict(normalized.schema_result),
            "semantic_result": sub_result_to_dict(normalized.semantic_result),
            "asset_result": sub_result_to_dict(normalized.asset_result),
            "validation_result": sub_result_to_dict(normalized.validation_result),
            "metadata": {
                **dict(normalized.metadata),
                **({MANIFEST_VPLIB_UID_FIELD: uid} if uid else {}),
            },
        }


def validate_package_creation_plan(
    creation_plan: Any,
    *,
    options: PackageValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageValidationResult:
    """Validiert einen vollständigen CreationPlan."""
    try:
        normalized_options = normalize_options(options)
        normalized_plan = normalize_creation_plan(creation_plan)
        issues: list[PackageIssue] = []

        documents = build_documents_from_creation_plan_safe(normalized_plan)
        profile = getattr(normalized_plan, "profile", None)
        uid = get_vplib_uid_from_documents_safe(documents)
        result_metadata = {
            "source": "creation_plan",
            "package_id": get_creation_plan_package_id(normalized_plan),
            "object_kind": get_creation_plan_object_kind(normalized_plan),
            **dict(metadata or {}),
        }
        if uid:
            result_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

        if normalized_options.validate_package_plan:
            issues.extend(
                validate_package_plan_consistency(
                    package_plan=getattr(normalized_plan, "package_plan", None),
                    module_plan=getattr(normalized_plan, "module_plan", None),
                    context=getattr(normalized_plan, "context", None),
                    documents=documents,
                    options=normalized_options,
                    metadata=result_metadata,
                )
            )

        if normalized_options.validate_profile_consistency:
            issues.extend(
                validate_creation_plan_profile_consistency(
                    normalized_plan,
                    options=normalized_options,
                )
            )

        if normalized_options.validate_vplib_uid:
            issues.extend(
                validate_vplib_uid_consistency(
                    documents=documents,
                    context=getattr(normalized_plan, "context", None),
                    package_plan=getattr(normalized_plan, "package_plan", None),
                    metadata=result_metadata,
                )
            )

        sub_results = run_sub_validators(
            documents=documents,
            profile=profile,
            options=normalized_options,
            metadata=result_metadata,
        )

        return PackageValidationResult(
            issues=tuple(issues),
            schema_result=sub_results.get("schema_result"),
            semantic_result=sub_results.get("semantic_result"),
            asset_result=sub_results.get("asset_result"),
            status=PackageValidationStatus.VALID.value,
            metadata=result_metadata,
        ).normalized()
    except PackageValidatorError:
        raise
    except Exception as exc:
        return PackageValidationResult(
            issues=(
                package_issue(
                    code=PackageIssueCode.INTERNAL_ERROR.value,
                    severity=PackageIssueSeverity.FATAL.value,
                    phase=PackageValidationPhase.SYSTEM.value,
                    message=f"Package creation plan validation failed: {exc}",
                    module_name="system",
                ),
            ),
            status=PackageValidationStatus.ERROR.value,
            metadata=dict(metadata or {}),
        ).normalized()


def validate_package_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    profile: Any | None = None,
    package_plan: Any | None = None,
    module_plan: Any | None = None,
    context: Any | None = None,
    options: PackageValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageValidationResult:
    """Validiert ein path -> document Mapping als vollständiges Package."""
    try:
        normalized_options = normalize_options(options)
        normalized_documents = normalize_documents_mapping(documents)
        issues: list[PackageIssue] = []
        uid = get_vplib_uid_from_documents_safe(normalized_documents)

        result_metadata = {
            "source": "documents",
            "document_count": len(normalized_documents),
            **dict(metadata or {}),
        }
        if uid:
            result_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

        if normalized_options.validate_document_paths:
            issues.extend(validate_document_path_consistency(normalized_documents, options=normalized_options))

        if normalized_options.validate_required_documents:
            issues.extend(validate_required_package_documents(normalized_documents, options=normalized_options))

        if normalized_options.validate_vplib_uid:
            issues.extend(
                validate_vplib_uid_consistency(
                    documents=normalized_documents,
                    context=context,
                    package_plan=package_plan,
                    metadata=result_metadata,
                )
            )

        if package_plan is not None and normalized_options.validate_package_plan:
            issues.extend(
                validate_package_plan_consistency(
                    package_plan=package_plan,
                    module_plan=module_plan,
                    context=context,
                    documents=normalized_documents,
                    options=normalized_options,
                    metadata=result_metadata,
                )
            )

        sub_results = run_sub_validators(
            documents=normalized_documents,
            profile=profile,
            options=normalized_options,
            metadata=result_metadata,
        )

        return PackageValidationResult(
            issues=tuple(issues),
            schema_result=sub_results.get("schema_result"),
            semantic_result=sub_results.get("semantic_result"),
            asset_result=sub_results.get("asset_result"),
            status=PackageValidationStatus.VALID.value,
            metadata=result_metadata,
        ).normalized()
    except PackageValidatorError:
        raise
    except Exception as exc:
        return PackageValidationResult(
            issues=(
                package_issue(
                    code=PackageIssueCode.INTERNAL_ERROR.value,
                    severity=PackageIssueSeverity.FATAL.value,
                    phase=PackageValidationPhase.SYSTEM.value,
                    message=f"Package document validation failed: {exc}",
                    module_name="system",
                ),
            ),
            status=PackageValidationStatus.ERROR.value,
            metadata=dict(metadata or {}),
        ).normalized()


def validate_package_document_bundle(
    bundle: Any,
    *,
    profile: Any | None = None,
    package_plan: Any | None = None,
    module_plan: Any | None = None,
    context: Any | None = None,
    options: PackageValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageValidationResult:
    """Validiert ein DocumentBundle-ähnliches Objekt."""
    try:
        normalized_bundle = normalize_document_bundle(bundle)
        documents = (
            normalized_bundle.to_documents()
            if hasattr(normalized_bundle, "to_documents")
            else normalized_bundle.documents
        )
        uid = get_vplib_uid_from_bundle_safe(normalized_bundle) or get_vplib_uid_from_documents_safe(documents)

        result_metadata = {
            "source": "document_bundle",
            "bundle_schema_version": getattr(normalized_bundle, "schema_version", None),
            **dict(metadata or {}),
        }
        if uid:
            result_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

        return validate_package_documents(
            documents,
            profile=profile,
            package_plan=package_plan,
            module_plan=module_plan,
            context=context,
            options=options,
            metadata=result_metadata,
        ).normalized()
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"Could not validate package document bundle: {exc}") from exc


def validate_package_plan_only(
    package_plan: Any,
    *,
    module_plan: Any | None = None,
    context: Any | None = None,
    documents: Mapping[str, Mapping[str, Any]] | None = None,
    options: PackageValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PackageValidationResult:
    """Validiert nur PackagePlan-/Path-Konsistenz ohne Subvalidatoren."""
    try:
        normalized_options = normalize_options(options)
        normalized_documents = normalize_documents_mapping(documents or {}) if documents is not None else {}
        uid = get_vplib_uid_from_documents_safe(normalized_documents) if normalized_documents else None
        result_metadata = {
            "source": "package_plan",
            **dict(metadata or {}),
        }
        if uid:
            result_metadata[MANIFEST_VPLIB_UID_FIELD] = uid

        issues = validate_package_plan_consistency(
            package_plan=package_plan,
            module_plan=module_plan,
            context=context,
            documents=normalized_documents,
            options=normalized_options,
            metadata=result_metadata,
        )

        if normalized_documents and normalized_options.validate_vplib_uid:
            issues = (
                *tuple(issues),
                *validate_vplib_uid_consistency(
                    documents=normalized_documents,
                    context=context,
                    package_plan=package_plan,
                    metadata=result_metadata,
                ),
            )

        return PackageValidationResult(
            issues=tuple(issues),
            status=PackageValidationStatus.VALID.value,
            metadata=result_metadata,
        ).normalized()
    except PackageValidatorError:
        raise
    except Exception as exc:
        return PackageValidationResult(
            issues=(
                package_issue(
                    code=PackageIssueCode.INTERNAL_ERROR.value,
                    severity=PackageIssueSeverity.FATAL.value,
                    phase=PackageValidationPhase.SYSTEM.value,
                    message=f"Package plan validation failed: {exc}",
                    module_name="system",
                ),
            ),
            status=PackageValidationStatus.ERROR.value,
            metadata=dict(metadata or {}),
        ).normalized()


def run_sub_validators(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    profile: Any | None,
    options: PackageValidationOptions,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Führt Schema-, Semantic- und Asset-Validatoren defensiv aus."""
    normalized_options = options.normalized()
    results: dict[str, Any] = {}

    if normalized_options.validate_schema:
        try:
            from .schema_validator import validate_documents_schema

            results["schema_result"] = validate_documents_schema(
                documents,
                options={
                    "mode": normalized_options.mode,
                    **dict(normalized_options.schema_options),
                },
                metadata=metadata,
            ).normalized()
        except Exception as exc:
            results["schema_result"] = fallback_subvalidator_error_result(
                phase=PackageValidationPhase.SCHEMA.value,
                message=f"Schema validation failed: {exc}",
            )

    if normalized_options.validate_semantics:
        try:
            from .semantic_validator import validate_documents_semantics

            results["semantic_result"] = validate_documents_semantics(
                documents,
                options={
                    "mode": normalized_options.mode,
                    **dict(normalized_options.semantic_options),
                },
                metadata=metadata,
            ).normalized()
        except Exception as exc:
            results["semantic_result"] = fallback_subvalidator_error_result(
                phase=PackageValidationPhase.SEMANTIC.value,
                message=f"Semantic validation failed: {exc}",
            )

    if normalized_options.validate_assets:
        try:
            from .asset_validator import validate_documents_assets

            results["asset_result"] = validate_documents_assets(
                documents,
                profile=profile,
                options={
                    "mode": normalized_options.mode,
                    **dict(normalized_options.asset_options),
                },
                metadata=metadata,
            ).normalized()
        except Exception as exc:
            results["asset_result"] = fallback_subvalidator_error_result(
                phase=PackageValidationPhase.ASSET.value,
                message=f"Asset validation failed: {exc}",
            )

    return results


def validate_package_plan_consistency(
    *,
    package_plan: Any,
    module_plan: Any | None,
    context: Any | None,
    documents: Mapping[str, Mapping[str, Any]],
    options: PackageValidationOptions,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[PackageIssue, ...]:
    """Prüft PackagePlan gegen ModulePlan, Context und Dokumente."""
    issues: list[PackageIssue] = []

    if package_plan is None:
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_PLAN.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.PLAN.value,
                message="PackagePlan is required for package plan consistency validation.",
                module_name="package",
            )
        )
        return tuple(issues)

    try:
        normalized_plan = package_plan.normalized() if hasattr(package_plan, "normalized") else package_plan
    except Exception as exc:
        return (
            package_issue(
                code=PackageIssueCode.INVALID_PLAN.value,
                severity=PackageIssueSeverity.FATAL.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"PackagePlan cannot be normalized: {exc}",
                module_name="package",
            ),
        )

    try:
        if hasattr(normalized_plan, "validate"):
            valid, messages = normalized_plan.validate()
            if not valid:
                for message in messages or ():
                    issues.append(
                        package_issue(
                            code=PackageIssueCode.INVALID_PLAN.value,
                            severity=PackageIssueSeverity.ERROR.value,
                            phase=PackageValidationPhase.PLAN.value,
                            message=str(message),
                            module_name="package",
                        )
                    )
    except Exception as exc:
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_PLAN.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"PackagePlan.validate() failed: {exc}",
                module_name="package",
            )
        )

    issues.extend(validate_planned_path_duplicates(normalized_plan))
    issues.extend(validate_planned_documents_against_bundle(normalized_plan, documents, options=options))

    if context is not None:
        issues.extend(validate_plan_context_consistency(normalized_plan, context))

    if module_plan is not None:
        issues.extend(validate_plan_module_consistency(normalized_plan, module_plan))

    if options.validate_archive_path:
        issues.extend(validate_archive_path_consistency(normalized_plan))

    return tuple(issues)


def validate_planned_path_duplicates(package_plan: Any) -> tuple[PackageIssue, ...]:
    """Prüft doppelte geplante Pfade."""
    issues: list[PackageIssue] = []

    files = tuple(extract_planned_file_paths(package_plan))
    directories = tuple(extract_planned_directory_paths(package_plan))
    asset_targets = tuple(extract_planned_asset_target_paths(package_plan))

    for duplicate in find_duplicates(files):
        issues.append(
            package_issue(
                code=PackageIssueCode.DUPLICATE_PATH.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Duplicate planned file path {duplicate!r}.",
                path=duplicate,
                module_name=infer_module_from_path_safe(duplicate),
            )
        )

    for duplicate in find_duplicates(asset_targets):
        issues.append(
            package_issue(
                code=PackageIssueCode.DUPLICATE_PATH.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Duplicate planned asset target path {duplicate!r}.",
                path=duplicate,
                module_name=infer_module_from_path_safe(duplicate),
            )
        )

    file_set = set(files)
    directory_set = set(directories)

    for path in file_set.intersection(directory_set):
        issues.append(
            package_issue(
                code=PackageIssueCode.DUPLICATE_PATH.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Path {path!r} is planned both as file and directory.",
                path=path,
                module_name=infer_module_from_path_safe(path),
            )
        )

    return tuple(issues)


def validate_planned_documents_against_bundle(
    package_plan: Any,
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: PackageValidationOptions,
) -> tuple[PackageIssue, ...]:
    """Prüft geplante JSON-Dateien gegen vorhandene Dokumente."""
    issues: list[PackageIssue] = []

    if not documents:
        return tuple(issues)

    planned_files = set(extract_planned_file_paths(package_plan))
    document_paths = set(documents.keys())

    planned_json_files = {
        path
        for path in planned_files
        if path.endswith(".json")
    }

    if options.require_documents_for_planned_files:
        for path in sorted(planned_json_files - document_paths):
            issues.append(
                package_issue(
                    code=PackageIssueCode.PLANNED_DOCUMENT_MISSING.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.DOCUMENTS.value,
                    message=f"Planned JSON document {path!r} is missing from document bundle.",
                    path=path,
                    module_name=infer_module_from_path_safe(path),
                )
            )

    if not options.allow_unplanned_documents:
        for path in sorted(document_paths - planned_json_files):
            if path in ROOT_REQUIRED_DOCUMENTS:
                continue
            issues.append(
                package_issue(
                    code=PackageIssueCode.UNPLANNED_DOCUMENT.value,
                    severity=PackageIssueSeverity.WARNING.value,
                    phase=PackageValidationPhase.DOCUMENTS.value,
                    message=f"Document {path!r} exists in bundle but is not planned by PackagePlan.",
                    path=path,
                    module_name=infer_module_from_path_safe(path),
                )
            )

    return tuple(issues)


def validate_plan_context_consistency(package_plan: Any, context: Any) -> tuple[PackageIssue, ...]:
    """Prüft PackagePlan gegen PackageContext."""
    issues: list[PackageIssue] = []

    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        plan_context = getattr(package_plan, "context", None)

        if plan_context is None:
            return tuple(issues)

        normalized_plan_context = plan_context.normalized() if hasattr(plan_context, "normalized") else plan_context

        context_package_id = getattr(getattr(normalized_context, "identity", None), "package_id", None)
        plan_package_id = getattr(getattr(normalized_plan_context, "identity", None), "package_id", None)

        if context_package_id and plan_package_id and context_package_id != plan_package_id:
            issues.append(
                package_issue(
                    code=PackageIssueCode.PACKAGE_ID_MISMATCH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message="PackagePlan context package_id does not match supplied context.",
                    module_name="package",
                    details={
                        "context_package_id": context_package_id,
                        "plan_package_id": plan_package_id,
                    },
                )
            )

        context_object_kind = getattr(normalized_context, "object_kind", None)
        plan_object_kind = getattr(normalized_plan_context, "object_kind", None)

        if context_object_kind and plan_object_kind and context_object_kind != plan_object_kind:
            issues.append(
                package_issue(
                    code=PackageIssueCode.OBJECT_KIND_MISMATCH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message="PackagePlan context object_kind does not match supplied context.",
                    module_name="package",
                    details={
                        "context_object_kind": context_object_kind,
                        "plan_object_kind": plan_object_kind,
                    },
                )
            )

        context_uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(normalized_context))
        plan_uid = normalize_vplib_uid_safe(extract_raw_vplib_uid_from_any(normalized_plan_context))

        if context_uid and plan_uid and context_uid != plan_uid:
            issues.append(
                package_issue(
                    code=PackageIssueCode.VPLIB_UID_MISMATCH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message="PackagePlan context vplib_uid does not match supplied context.",
                    field_path=MANIFEST_VPLIB_UID_FIELD,
                    module_name="package",
                    details={
                        "context_vplib_uid": context_uid,
                        "plan_vplib_uid": plan_uid,
                    },
                )
            )

    except Exception as exc:
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_PLAN.value,
                severity=PackageIssueSeverity.WARNING.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Could not validate context consistency: {exc}",
                module_name="package",
            )
        )

    return tuple(issues)


def validate_plan_module_consistency(package_plan: Any, module_plan: Any) -> tuple[PackageIssue, ...]:
    """Prüft PackagePlan gegen ModulePlan."""
    issues: list[PackageIssue] = []

    try:
        normalized_module_plan = module_plan.normalized() if hasattr(module_plan, "normalized") else module_plan

        active_modules = set(normalize_string_tuple(getattr(normalized_module_plan, "active_module_names", ()) or ()))
        planned_files = extract_planned_file_paths(package_plan)

        for path in planned_files:
            module_name = infer_module_from_path_safe(path)
            if module_name and active_modules and module_name not in active_modules:
                issues.append(
                    package_issue(
                        code=PackageIssueCode.MODULE_MISMATCH.value,
                        severity=PackageIssueSeverity.WARNING.value,
                        phase=PackageValidationPhase.PLAN.value,
                        message=f"PackagePlan contains file {path!r} for inactive module {module_name!r}.",
                        path=path,
                        module_name=module_name,
                    )
                )

    except Exception as exc:
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_PLAN.value,
                severity=PackageIssueSeverity.WARNING.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Could not validate module consistency: {exc}",
                module_name="package",
            )
        )

    return tuple(issues)


def validate_archive_path_consistency(package_plan: Any) -> tuple[PackageIssue, ...]:
    """Prüft .vplib Archive-Zielpfad."""
    issues: list[PackageIssue] = []

    archive_path = getattr(package_plan, "archive_path", None)
    if archive_path is None:
        return tuple(issues)

    try:
        archive_name = Path(str(archive_path)).name

        if not archive_name.endswith(PACKAGE_ARCHIVE_EXTENSION):
            issues.append(
                package_issue(
                    code=PackageIssueCode.INVALID_ARCHIVE_PATH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message=f"Package archive path must end with {PACKAGE_ARCHIVE_EXTENSION!r}.",
                    path=str(archive_path),
                    module_name="package",
                )
            )

        if not archive_name or archive_name in {".", ".."}:
            issues.append(
                package_issue(
                    code=PackageIssueCode.INVALID_ARCHIVE_PATH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message="Package archive path has invalid file name.",
                    path=str(archive_path),
                    module_name="package",
                )
            )
    except Exception as exc:
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_ARCHIVE_PATH.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Could not validate archive path: {exc}",
                path=str(archive_path),
                module_name="package",
            )
        )

    return tuple(issues)


def validate_creation_plan_profile_consistency(
    creation_plan: Any,
    *,
    options: PackageValidationOptions,
) -> tuple[PackageIssue, ...]:
    """Prüft Request/Context/Profile/ObjectKind-Konsistenz eines CreationPlan."""
    issues: list[PackageIssue] = []

    try:
        request = getattr(creation_plan, "request", None)
        context = getattr(creation_plan, "context", None)
        profile = getattr(creation_plan, "profile", None)
        module_plan = getattr(creation_plan, "module_plan", None)

        request_object_kind = getattr(request, "object_kind", None)
        context_object_kind = getattr(context, "object_kind", None)
        profile_object_kind = getattr(profile, "object_kind", None)
        module_plan_object_kind = getattr(module_plan, "object_kind", None)

        object_kind_values = {
            clean_optional_string(value)
            for value in (
                request_object_kind,
                context_object_kind,
                profile_object_kind,
                module_plan_object_kind,
            )
            if clean_optional_string(value)
        }

        if len(object_kind_values) > 1:
            issues.append(
                package_issue(
                    code=PackageIssueCode.OBJECT_KIND_MISMATCH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message="CreationPlan object_kind values are inconsistent.",
                    module_name="package",
                    details={
                        "object_kinds": sorted(object_kind_values),
                    },
                )
            )

        profile_key = clean_optional_string(getattr(profile, "profile_key", None))
        module_plan_profile_key = clean_optional_string(getattr(module_plan, "profile_key", None))

        if profile_key and module_plan_profile_key and profile_key != module_plan_profile_key:
            issues.append(
                package_issue(
                    code=PackageIssueCode.PROFILE_MISMATCH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PLAN.value,
                    message="CreationPlan profile_key does not match ModulePlan profile_key.",
                    module_name="package",
                    details={
                        "profile_key": profile_key,
                        "module_plan_profile_key": module_plan_profile_key,
                    },
                )
            )

        if profile is not None and module_plan is not None:
            required_modules = set(normalize_string_tuple(getattr(profile, "required_module_names", ()) or ()))
            active_modules = set(normalize_string_tuple(getattr(module_plan, "active_module_names", ()) or ()))

            missing_modules = required_modules - active_modules
            for module_name in sorted(missing_modules):
                issues.append(
                    package_issue(
                        code=PackageIssueCode.MODULE_MISMATCH.value,
                        severity=PackageIssueSeverity.ERROR.value,
                        phase=PackageValidationPhase.PLAN.value,
                        message=f"ModulePlan is missing required profile module {module_name!r}.",
                        module_name=module_name,
                    )
                )

    except Exception as exc:
        issues.append(
            package_issue(
                code=PackageIssueCode.PROFILE_MISMATCH.value,
                severity=PackageIssueSeverity.WARNING.value,
                phase=PackageValidationPhase.PLAN.value,
                message=f"Could not validate profile consistency: {exc}",
                module_name="package",
            )
        )

    return tuple(issues)


def validate_document_path_consistency(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: PackageValidationOptions,
) -> tuple[PackageIssue, ...]:
    """Prüft Dokumentpfade auf Sicherheit und Duplikate."""
    issues: list[PackageIssue] = []
    paths = tuple(documents.keys())

    for duplicate in find_duplicates(paths):
        issues.append(
            package_issue(
                code=PackageIssueCode.DUPLICATE_PATH.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.DOCUMENTS.value,
                message=f"Duplicate document path {duplicate!r}.",
                path=duplicate,
                module_name=infer_module_from_path_safe(duplicate),
            )
        )

    for path in paths:
        try:
            normalized_path = normalize_package_path(path)
            if normalized_path != path:
                issues.append(
                    package_issue(
                        code=PackageIssueCode.INVALID_PACKAGE_PATH.value,
                        severity=PackageIssueSeverity.WARNING.value,
                        phase=PackageValidationPhase.DOCUMENTS.value,
                        message=f"Document path {path!r} normalizes to {normalized_path!r}.",
                        path=path,
                        module_name=infer_module_from_path_safe(path),
                    )
                )
        except Exception as exc:
            issues.append(
                package_issue(
                    code=PackageIssueCode.INVALID_PACKAGE_PATH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.DOCUMENTS.value,
                    message=f"Invalid document path {path!r}: {exc}",
                    path=str(path),
                    module_name=infer_module_from_path_safe(path),
                )
            )

    return tuple(issues)


def validate_required_package_documents(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: PackageValidationOptions,
) -> tuple[PackageIssue, ...]:
    """Prüft required Package-Dokumente."""
    issues: list[PackageIssue] = []
    paths = set(documents.keys())

    required_documents = CORE_REQUIRED_DOCUMENTS if options.is_strict else ROOT_REQUIRED_DOCUMENTS

    for path in required_documents:
        if path not in paths:
            issues.append(
                package_issue(
                    code=PackageIssueCode.MISSING_DOCUMENT.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.DOCUMENTS.value,
                    message=f"Required package document {path!r} is missing.",
                    path=path,
                    module_name=infer_module_from_path_safe(path),
                )
            )

    return tuple(issues)


def validate_vplib_uid_consistency(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    context: Any | None = None,
    package_plan: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[PackageIssue, ...]:
    """
    Prüft die technische VPLIB-Paket-ID.

    Regeln:
    - `vplib.manifest.json` muss vorhanden sein.
    - Manifest muss ein Mapping sein.
    - Manifest muss `vplib_uid` enthalten.
    - `vplib_uid` muss gültige UUID-ähnliche VPLIB-ID sein.
    - Wenn Context/PackagePlan/Metadata ebenfalls eine gültige `vplib_uid`
      enthalten, muss sie mit dem Manifest übereinstimmen.
    - Ungültige externe Vergleichs-IDs werden als Fehler gemeldet, wenn sie
      explizit gesetzt wurden.
    """
    issues: list[PackageIssue] = []

    manifest = documents.get(MANIFEST_DOCUMENT_PATH)
    if manifest is None:
        issues.append(
            package_issue(
                code=PackageIssueCode.MISSING_DOCUMENT.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.DOCUMENTS.value,
                path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
                module_name="manifest",
                message=f"Cannot validate {MANIFEST_VPLIB_UID_FIELD!r}: manifest document is missing.",
            )
        )
        return tuple(issues)

    if not isinstance(manifest, Mapping):
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_INPUT.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.DOCUMENTS.value,
                path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
                module_name="manifest",
                message="Manifest document must be a mapping.",
            )
        )
        return tuple(issues)

    raw_uid = manifest.get(MANIFEST_VPLIB_UID_FIELD)
    manifest_uid = normalize_vplib_uid_safe(raw_uid)

    if raw_uid is None or str(raw_uid).strip() == "":
        issues.append(
            package_issue(
                code=PackageIssueCode.MISSING_VPLIB_UID.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.DOCUMENTS.value,
                path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
                module_name="manifest",
                message=f"Manifest is missing required field {MANIFEST_VPLIB_UID_FIELD!r}.",
            )
        )
        return tuple(issues)

    if not manifest_uid:
        issues.append(
            package_issue(
                code=PackageIssueCode.INVALID_VPLIB_UID.value,
                severity=PackageIssueSeverity.ERROR.value,
                phase=PackageValidationPhase.DOCUMENTS.value,
                path=MANIFEST_DOCUMENT_PATH,
                field_path=MANIFEST_VPLIB_UID_FIELD,
                module_name="manifest",
                message=f"Manifest field {MANIFEST_VPLIB_UID_FIELD!r} is invalid. Expected UUID-like VPLIB UID.",
                details={
                    "value": str(raw_uid),
                },
            )
        )
        return tuple(issues)

    candidates = collect_expected_vplib_uid_candidates(
        context=context,
        package_plan=package_plan,
        metadata=metadata,
    )

    for source_name, raw_candidate in candidates:
        if raw_candidate is None or str(raw_candidate).strip() == "":
            continue

        candidate_uid = normalize_vplib_uid_safe(raw_candidate)
        if not candidate_uid:
            issues.append(
                package_issue(
                    code=PackageIssueCode.INVALID_VPLIB_UID.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PACKAGE.value,
                    path=MANIFEST_DOCUMENT_PATH,
                    field_path=MANIFEST_VPLIB_UID_FIELD,
                    module_name="manifest",
                    message=f"Expected VPLIB UID from {source_name!r} is invalid.",
                    details={
                        "source": source_name,
                        "value": str(raw_candidate),
                    },
                )
            )
            continue

        if candidate_uid != manifest_uid:
            issues.append(
                package_issue(
                    code=PackageIssueCode.VPLIB_UID_MISMATCH.value,
                    severity=PackageIssueSeverity.ERROR.value,
                    phase=PackageValidationPhase.PACKAGE.value,
                    path=MANIFEST_DOCUMENT_PATH,
                    field_path=MANIFEST_VPLIB_UID_FIELD,
                    module_name="manifest",
                    message=f"Manifest {MANIFEST_VPLIB_UID_FIELD!r} does not match {source_name!r}.",
                    details={
                        "manifest_vplib_uid": manifest_uid,
                        "expected_vplib_uid": candidate_uid,
                        "source": source_name,
                    },
                )
            )

    return tuple(issues)


def collect_expected_vplib_uid_candidates(
    *,
    context: Any | None = None,
    package_plan: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> tuple[tuple[str, Any], ...]:
    """Sammelt Vergleichskandidaten für `vplib_uid` aus Plan/Context/Metadata."""
    candidates: list[tuple[str, Any]] = []

    try:
        raw = extract_raw_vplib_uid_from_any(metadata)
        if raw is not None:
            candidates.append(("metadata.vplib_uid", raw))
    except Exception:
        pass

    try:
        raw = extract_raw_vplib_uid_from_any(context)
        if raw is not None:
            candidates.append(("context.vplib_uid", raw))
    except Exception:
        pass

    try:
        raw = extract_raw_vplib_uid_from_any(package_plan)
        if raw is not None:
            candidates.append(("package_plan.vplib_uid", raw))
    except Exception:
        pass

    try:
        plan_context = getattr(package_plan, "context", None)
        raw = extract_raw_vplib_uid_from_any(plan_context)
        if raw is not None:
            candidates.append(("package_plan.context.vplib_uid", raw))
    except Exception:
        pass

    return tuple(candidates)


def build_documents_from_creation_plan_safe(creation_plan: Any) -> dict[str, dict[str, Any]]:
    """Baut DocumentBundle aus CreationPlan und gibt Dokumente zurück."""
    try:
        from ..defaults.document_bundle import build_document_bundle_from_creation_plan

        bundle = build_document_bundle_from_creation_plan(creation_plan)
        return normalize_documents_mapping(bundle.to_documents())
    except Exception as exc:
        raise PackageValidatorError(f"Could not build documents from CreationPlan: {exc}") from exc


def package_issue(
    *,
    code: str,
    message: str,
    severity: str = PackageIssueSeverity.ERROR.value,
    phase: str = PackageValidationPhase.PACKAGE.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> PackageIssue:
    """Factory für PackageIssue."""
    return PackageIssue(
        code=code,
        message=message,
        severity=severity,
        phase=phase,
        path=path,
        field_path=field_path,
        module_name=module_name,
        details=dict(details or {}),
    ).normalized()


def build_validation_result_from_package_result(
    *,
    issues: Iterable[PackageIssue],
    schema_result: Any | None,
    semantic_result: Any | None,
    asset_result: Any | None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Baut ein ValidationResult aus PackageIssues und Subvalidator-Ergebnissen."""
    try:
        from ..models.validation_result import (
            ValidationIssue,
            ValidationScope,
            invalid_result,
            valid_result,
        )

        normalized_metadata = normalize_metadata(metadata)
        normalized_issues = tuple(issue.normalized() for issue in issues or ())
        validation_issues = [
            ValidationIssue(
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
                scope=ValidationScope.PACKAGE.value,
                path=issue.path,
                field_path=issue.field_path,
                module_name=issue.module_name,
                details={
                    "phase": issue.phase,
                    **dict(issue.details),
                },
            ).normalized()
            for issue in normalized_issues
        ]

        for sub_result_name, sub_result in (
            ("schema_result", schema_result),
            ("semantic_result", semantic_result),
            ("asset_result", asset_result),
        ):
            if sub_result is None or sub_result_is_valid(sub_result):
                continue

            validation_issues.append(
                ValidationIssue(
                    code=PackageIssueCode.VALIDATION_FAILED.value,
                    message=f"{sub_result_name} failed.",
                    severity=PackageIssueSeverity.ERROR.value,
                    scope=ValidationScope.PACKAGE.value,
                    details={
                        "sub_result": sub_result_to_dict(sub_result),
                    },
                ).normalized()
            )

        if not validation_issues:
            return valid_result(
                metadata={
                    "source": "package_validator",
                    "schema_version": PACKAGE_VALIDATOR_SCHEMA_VERSION,
                    **normalized_metadata,
                }
            )

        return invalid_result(
            tuple(validation_issues),
            metadata={
                "source": "package_validator",
                "schema_version": PACKAGE_VALIDATOR_SCHEMA_VERSION,
                **normalized_metadata,
            },
        )
    except Exception:
        normalized_metadata = normalize_metadata(metadata)
        normalized_issues = tuple(issue.normalized() for issue in issues or ())
        return {
            "schema_version": PACKAGE_VALIDATOR_SCHEMA_VERSION,
            "valid": not any(issue.blocks_success for issue in normalized_issues)
            and sub_result_is_valid(schema_result)
            and sub_result_is_valid(semantic_result)
            and sub_result_is_valid(asset_result),
            "vplib_uid": normalize_vplib_uid_safe(normalized_metadata.get(MANIFEST_VPLIB_UID_FIELD)),
            "issues": [issue.to_dict() for issue in normalized_issues],
            "schema_result": sub_result_to_dict(schema_result),
            "semantic_result": sub_result_to_dict(semantic_result),
            "asset_result": sub_result_to_dict(asset_result),
            "metadata": normalized_metadata,
        }


def fallback_subvalidator_error_result(*, phase: str, message: str) -> dict[str, Any]:
    """Erzeugt einen einfachen Fehlerpayload, wenn ein Subvalidator abstürzt."""
    return {
        "schema_version": PACKAGE_VALIDATOR_SCHEMA_VERSION,
        "valid": False,
        "status": PackageValidationStatus.ERROR.value,
        "phase": phase,
        "issues": [
            {
                "code": PackageIssueCode.VALIDATION_FAILED.value,
                "message": message,
                "severity": PackageIssueSeverity.ERROR.value,
                "phase": phase,
            }
        ],
    }


def sub_result_is_valid(value: Any | None) -> bool:
    """Prüft, ob ein Subvalidator-Ergebnis gültig ist."""
    if value is None:
        return True

    if hasattr(value, "valid"):
        try:
            return bool(value.valid)
        except Exception:
            return False

    if hasattr(value, "is_valid"):
        try:
            return bool(value.is_valid)
        except Exception:
            return False

    if isinstance(value, Mapping):
        return bool(value.get("valid", False))

    return False


def sub_result_to_dict(value: Any | None) -> Any:
    """Serialisiert Subvalidator-Ergebnisse robust."""
    if value is None:
        return None

    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict()
        except Exception:
            return str(value)

    if isinstance(value, Mapping):
        return normalize_json_value(value)

    return str(value)


def normalize_sub_result(value: Any | None) -> Any | None:
    """Normalisiert ein optionales Subvalidator-Ergebnis."""
    if value is None:
        return None

    if hasattr(value, "normalized") and callable(value.normalized):
        try:
            return value.normalized()
        except Exception:
            return value

    return value


def extract_planned_file_paths(package_plan: Any) -> tuple[str, ...]:
    """Extrahiert geplante Datei-Pfade aus PackagePlan-ähnlichem Objekt."""
    paths: list[str] = []

    for item in getattr(package_plan, "files", ()) or ():
        path = extract_path_from_plan_item(item)
        if path:
            paths.append(path)

    for item in getattr(package_plan, "planned_files", ()) or ():
        path = extract_path_from_plan_item(item)
        if path:
            paths.append(path)

    return tuple(normalize_package_path(path) for path in paths)


def extract_planned_directory_paths(package_plan: Any) -> tuple[str, ...]:
    """Extrahiert geplante Directory-Pfade aus PackagePlan-ähnlichem Objekt."""
    paths: list[str] = []

    for item in getattr(package_plan, "directories", ()) or ():
        path = extract_path_from_plan_item(item)
        if path:
            paths.append(path)

    for item in getattr(package_plan, "planned_directories", ()) or ():
        path = extract_path_from_plan_item(item)
        if path:
            paths.append(path)

    return tuple(normalize_package_path(path) for path in paths if path != ".")


def extract_planned_asset_target_paths(package_plan: Any) -> tuple[str, ...]:
    """Extrahiert geplante Asset-Zielpfade aus PackagePlan-ähnlichem Objekt."""
    paths: list[str] = []

    for item in getattr(package_plan, "asset_copies", ()) or ():
        path = (
            getattr(item, "target_relative_path", None)
            or getattr(item, "target_package_path", None)
            or getattr(item, "package_path", None)
        )
        if path:
            paths.append(str(path))

    return tuple(normalize_package_path(path) for path in paths)


def extract_path_from_plan_item(item: Any) -> str | None:
    """Extrahiert relative_path aus verschiedenen PlanItem-Formen."""
    if isinstance(item, str):
        return item

    if isinstance(item, Mapping):
        return (
            clean_optional_string(item.get("relative_path"))
            or clean_optional_string(item.get("path"))
            or clean_optional_string(item.get("target_relative_path"))
        )

    return (
        clean_optional_string(getattr(item, "relative_path", None))
        or clean_optional_string(getattr(item, "path", None))
        or clean_optional_string(getattr(item, "target_relative_path", None))
    )


def get_creation_plan_package_id(creation_plan: Any) -> str | None:
    """Liest package_id aus CreationPlan."""
    try:
        return clean_optional_string(creation_plan.context.identity.package_id)
    except Exception:
        return None


def get_creation_plan_object_kind(creation_plan: Any) -> str | None:
    """Liest object_kind aus CreationPlan."""
    try:
        return clean_optional_string(creation_plan.object_kind)
    except Exception:
        try:
            return clean_optional_string(creation_plan.context.object_kind)
        except Exception:
            return None


def get_vplib_uid_from_documents_safe(
    documents: Mapping[str, Mapping[str, Any]] | None,
) -> str | None:
    """Liest gültige `vplib_uid` aus Dokument-Mapping."""
    if not isinstance(documents, Mapping):
        return None

    try:
        manifest = documents.get(MANIFEST_DOCUMENT_PATH)
        return get_vplib_uid_from_manifest_safe(manifest)
    except Exception:
        return None


def get_vplib_uid_from_bundle_safe(bundle: Any | None) -> str | None:
    """Liest gültige `vplib_uid` aus DocumentBundle-ähnlichem Objekt."""
    if bundle is None:
        return None

    try:
        normalized_bundle = normalize_document_bundle(bundle)

        uid = normalize_vplib_uid_safe(getattr(normalized_bundle, "vplib_uid", None))
        if uid:
            return uid

        documents = normalized_bundle.to_documents() if hasattr(normalized_bundle, "to_documents") else normalized_bundle.documents
        return get_vplib_uid_from_documents_safe(documents)
    except Exception:
        return None


def get_vplib_uid_from_manifest_safe(manifest: Any | None) -> str | None:
    """Liest gültige `vplib_uid` aus Manifest-Mapping."""
    if not isinstance(manifest, Mapping):
        return None

    try:
        from ..vplib_id_service import get_vplib_uid_from_mapping

        return get_vplib_uid_from_mapping(manifest)
    except Exception:
        return normalize_vplib_uid_safe(manifest.get(MANIFEST_VPLIB_UID_FIELD))


def normalize_vplib_uid_safe(value: Any) -> str | None:
    """Normalisiert `vplib_uid` defensiv."""
    try:
        from ..vplib_id_service import normalize_vplib_uid

        return normalize_vplib_uid(value)
    except Exception:
        return None


def extract_raw_vplib_uid_from_any(value: Any) -> Any | None:
    """Extrahiert rohe `vplib_uid` aus Mapping- oder Objektstrukturen."""
    if value is None:
        return None

    try:
        if isinstance(value, Mapping):
            for key in (MANIFEST_VPLIB_UID_FIELD, "vplibUid", "vplib_uid_v1"):
                if key in value:
                    return value.get(key)

            for nested_key in ("manifest", "vplib_manifest", "identity", "payload", "data", "metadata", "context"):
                nested = value.get(nested_key)
                nested_uid = extract_raw_vplib_uid_from_any(nested)
                if nested_uid is not None:
                    return nested_uid

            return None

        for attr_name in (MANIFEST_VPLIB_UID_FIELD, "vplibUid", "vplib_uid_v1"):
            try:
                if hasattr(value, attr_name):
                    attr_value = getattr(value, attr_name)
                    if attr_value is not None:
                        return attr_value
            except Exception:
                continue

        for nested_attr in ("manifest", "vplib_manifest", "identity", "payload", "data", "metadata", "context"):
            try:
                nested = getattr(value, nested_attr, None)
                nested_uid = extract_raw_vplib_uid_from_any(nested)
                if nested_uid is not None:
                    return nested_uid
            except Exception:
                continue

        return None
    except Exception:
        return None


def normalize_creation_plan(value: Any) -> Any:
    """Normalisiert CreationPlan-ähnliche Werte."""
    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping):
            from ..planning.creation_planner import creation_plan_from_mapping

            return creation_plan_from_mapping(value).normalized()

        raise PackageValidatorError("CreationPlan value is required.")
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"Invalid CreationPlan: {exc}") from exc


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

        raise PackageValidatorError("DocumentBundle value is required.")
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"Invalid DocumentBundle: {exc}") from exc


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
        raise PackageValidatorError(f"Invalid ValidationResult: {exc}") from exc


def normalize_options(
    options: PackageValidationOptions | Mapping[str, Any] | None,
) -> PackageValidationOptions:
    """Normalisiert PackageValidationOptions."""
    if options is None:
        return PackageValidationOptions().normalized()

    if isinstance(options, PackageValidationOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return PackageValidationOptions(
            mode=options.get("mode", PackageValidationMode.STRICT.value),
            validate_schema=bool(options.get("validate_schema", True)),
            validate_semantics=bool(options.get("validate_semantics", True)),
            validate_assets=bool(options.get("validate_assets", True)),
            validate_package_plan=bool(options.get("validate_package_plan", True)),
            validate_document_paths=bool(options.get("validate_document_paths", True)),
            validate_required_documents=bool(options.get("validate_required_documents", True)),
            validate_vplib_uid=bool(options.get("validate_vplib_uid", True)),
            validate_profile_consistency=bool(options.get("validate_profile_consistency", True)),
            validate_archive_path=bool(options.get("validate_archive_path", True)),
            allow_unplanned_documents=bool(options.get("allow_unplanned_documents", True)),
            require_documents_for_planned_files=bool(options.get("require_documents_for_planned_files", True)),
            collect_all_errors=bool(options.get("collect_all_errors", True)),
            strict=bool(options.get("strict", True)),
            schema_options=dict(options.get("schema_options", {}) or {}),
            semantic_options=dict(options.get("semantic_options", {}) or {}),
            asset_options=dict(options.get("asset_options", {}) or {}),
        ).normalized()

    raise PackageValidatorError("options must be PackageValidationOptions, mapping or None.")


def normalize_documents_mapping(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalisiert path -> document Mapping."""
    if not isinstance(documents, Mapping):
        raise PackageValidatorError("documents must be a mapping.")

    return {
        normalize_package_path(path): normalize_document_mapping(document)
        for path, document in documents.items()
    }


def normalize_document_mapping(document: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert ein Dokument-Mapping JSON-kompatibel."""
    if not isinstance(document, Mapping):
        raise PackageValidatorError("document must be a mapping.")

    return {
        str(key): normalize_json_value(value)
        for key, value in document.items()
    }


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


def normalize_package_path(value: Any) -> str:
    """Normalisiert package-relative Pfade."""
    raw = clean_required_string(value, "path").replace("\\", "/").strip()

    if raw in ROOT_REQUIRED_DOCUMENTS:
        return raw

    raw = raw.strip("/")

    if not raw or raw.startswith("../") or "/../" in raw:
        raise PackageValidatorError(f"Unsafe package path {value!r}.")

    return raw


def infer_module_from_path_safe(path: Any) -> str | None:
    """Leitet Modul aus package-relativem Pfad ab."""
    try:
        raw = normalize_package_path(path)

        if raw == MANIFEST_DOCUMENT_PATH:
            return "manifest"

        if raw == MODULES_DOCUMENT_PATH:
            return "modules"

        root = raw.split("/", 1)[0]
        return root if root in KNOWN_MODULE_ORDER else None
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
        raw = clean_optional_string(value)
        if not raw:
            return None
        return raw.lower().replace(" ", "_").replace("-", "_")


@lru_cache(maxsize=128)
def parse_validation_status_value(value: Any) -> str:
    """Parst PackageValidationStatus."""
    try:
        if isinstance(value, PackageValidationStatus):
            return value.value

        raw = normalize_enum_key(value)
        return PackageValidationStatus(raw).value
    except Exception as exc:
        raise PackageValidatorError(f"Invalid package validation status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_mode_value(value: Any) -> str:
    """Parst PackageValidationMode."""
    try:
        if isinstance(value, PackageValidationMode):
            return value.value

        raw = normalize_enum_key(value)
        return PackageValidationMode(raw).value
    except Exception as exc:
        raise PackageValidatorError(f"Invalid package validation mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_phase_value(value: Any) -> str:
    """Parst PackageValidationPhase."""
    try:
        if isinstance(value, PackageValidationPhase):
            return value.value

        raw = normalize_enum_key(value)
        return PackageValidationPhase(raw).value
    except Exception as exc:
        raise PackageValidatorError(f"Invalid package validation phase {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_issue_severity_value(value: Any) -> str:
    """Parst PackageIssueSeverity."""
    try:
        if isinstance(value, PackageIssueSeverity):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "info": PackageIssueSeverity.INFO.value,
            "warning": PackageIssueSeverity.WARNING.value,
            "warn": PackageIssueSeverity.WARNING.value,
            "error": PackageIssueSeverity.ERROR.value,
            "fatal": PackageIssueSeverity.FATAL.value,
            "critical": PackageIssueSeverity.FATAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return PackageIssueSeverity(raw).value
    except Exception as exc:
        raise PackageValidatorError(f"Invalid package issue severity {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_issue_code_value(value: Any) -> str:
    """Parst PackageIssueCode."""
    try:
        if isinstance(value, PackageIssueCode):
            return value.value

        raw = str(value).strip().upper().replace(" ", "_").replace("-", "_")

        if not raw:
            raise PackageValidatorError("Package issue code is required.")

        if not raw.startswith("VPLIB_"):
            raw = f"VPLIB_PACKAGE_{raw}"

        try:
            return PackageIssueCode(raw).value
        except ValueError:
            return raw
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"Invalid package issue code {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise PackageValidatorError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"Invalid enum value {value!r}.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Float-Werte."""
    try:
        if isinstance(value, bool):
            raise PackageValidatorError(f"{field_name} must be a number.")

        number = float(value)
        if number <= 0:
            raise PackageValidatorError(f"{field_name} must be > 0.")

        return number
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"{field_name} must be a positive number.") from exc


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
        raise PackageValidatorError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def find_duplicates(values: Iterable[Any]) -> tuple[str, ...]:
    """Findet doppelte Werte."""
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned:
            continue

        if cleaned in seen:
            duplicates.add(cleaned)

        seen.add(cleaned)

    return tuple(sorted(duplicates))


def dedupe_issues(issues: Iterable[PackageIssue]) -> tuple[PackageIssue, ...]:
    """Dedupliziert Issues."""
    result: list[PackageIssue] = []
    seen: set[str] = set()

    for issue in issues or ():
        normalized = issue.normalized()
        fingerprint = normalized.fingerprint()

        if fingerprint in seen:
            continue

        result.append(normalized)
        seen.add(fingerprint)

    return tuple(result)


def sort_issues(issues: Iterable[PackageIssue]) -> tuple[PackageIssue, ...]:
    """Sortiert Issues stabil."""
    severity_order = {
        PackageIssueSeverity.FATAL.value: 10,
        PackageIssueSeverity.ERROR.value: 20,
        PackageIssueSeverity.WARNING.value: 30,
        PackageIssueSeverity.INFO.value: 40,
    }
    phase_order = {
        PackageValidationPhase.INPUT.value: 10,
        PackageValidationPhase.PLAN.value: 20,
        PackageValidationPhase.DOCUMENTS.value: 30,
        PackageValidationPhase.SCHEMA.value: 40,
        PackageValidationPhase.SEMANTIC.value: 50,
        PackageValidationPhase.ASSET.value: 60,
        PackageValidationPhase.PACKAGE.value: 70,
        PackageValidationPhase.SYSTEM.value: 80,
    }

    return tuple(
        sorted(
            (issue.normalized() for issue in issues or ()),
            key=lambda issue: (
                severity_order.get(issue.severity, 99),
                phase_order.get(issue.phase, 99),
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
            raise PackageValidatorError(f"{field_name} is required.")

        return cleaned
    except PackageValidatorError:
        raise
    except Exception as exc:
        raise PackageValidatorError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_package_validator_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_validation_status_value.cache_clear()
    parse_validation_mode_value.cache_clear()
    parse_validation_phase_value.cache_clear()
    parse_issue_severity_value.cache_clear()
    parse_issue_code_value.cache_clear()


__all__ = [
    "CORE_REQUIRED_DOCUMENTS",
    "KNOWN_MODULE_ORDER",
    "MANIFEST_DOCUMENT_PATH",
    "MANIFEST_VPLIB_UID_FIELD",
    "MODULES_DOCUMENT_PATH",
    "PACKAGE_ARCHIVE_EXTENSION",
    "PACKAGE_VALIDATOR_SCHEMA_VERSION",
    "ROOT_REQUIRED_DOCUMENTS",
    "PackageIssue",
    "PackageIssueCode",
    "PackageIssueSeverity",
    "PackageValidationMode",
    "PackageValidationOptions",
    "PackageValidationPhase",
    "PackageValidationResult",
    "PackageValidationStatus",
    "PackageValidatorError",
    "build_documents_from_creation_plan_safe",
    "build_validation_result_from_package_result",
    "clean_optional_string",
    "clean_required_string",
    "clear_package_validator_caches",
    "collect_expected_vplib_uid_candidates",
    "dedupe_issues",
    "extract_path_from_plan_item",
    "extract_planned_asset_target_paths",
    "extract_planned_directory_paths",
    "extract_planned_file_paths",
    "extract_raw_vplib_uid_from_any",
    "fallback_subvalidator_error_result",
    "find_duplicates",
    "get_creation_plan_object_kind",
    "get_creation_plan_package_id",
    "get_vplib_uid_from_bundle_safe",
    "get_vplib_uid_from_documents_safe",
    "get_vplib_uid_from_manifest_safe",
    "infer_module_from_path_safe",
    "normalize_creation_plan",
    "normalize_document_bundle",
    "normalize_document_mapping",
    "normalize_documents_mapping",
    "normalize_enum_key",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_optional_module_name",
    "normalize_options",
    "normalize_package_path",
    "normalize_positive_float",
    "normalize_string_tuple",
    "normalize_sub_result",
    "normalize_validation_result",
    "normalize_vplib_uid_safe",
    "package_issue",
    "parse_issue_code_value",
    "parse_issue_severity_value",
    "parse_validation_mode_value",
    "parse_validation_phase_value",
    "parse_validation_status_value",
    "run_sub_validators",
    "sort_issues",
    "sub_result_is_valid",
    "sub_result_to_dict",
    "validate_archive_path_consistency",
    "validate_creation_plan_profile_consistency",
    "validate_document_path_consistency",
    "validate_package_creation_plan",
    "validate_package_document_bundle",
    "validate_package_documents",
    "validate_package_plan_consistency",
    "validate_package_plan_only",
    "validate_plan_context_consistency",
    "validate_plan_module_consistency",
    "validate_planned_documents_against_bundle",
    "validate_planned_path_duplicates",
    "validate_required_package_documents",
    "validate_vplib_uid_consistency",
]