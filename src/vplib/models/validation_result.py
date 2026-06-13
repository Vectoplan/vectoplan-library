# services/vectoplan-library/src/vplib/models/validation_result.py
"""
ValidationResult model for the VPLIB package engine.

Diese Datei beschreibt einheitliche Validierungsergebnisse für:
- CreateRequest
- PackageContext
- ModulePlan
- PackagePlan
- Package paths
- Assets
- Variants
- Module documents
- Package validation
- Archive validation

Diese Datei validiert selbst keine fachlichen Inhalte. Sie stellt nur robuste
Ergebnis- und Issue-Modelle bereit.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


VALIDATION_RESULT_SCHEMA_VERSION: Final[str] = "vplib.validation_result.v1"


class ValidationResultError(ValueError):
    """Wird ausgelöst, wenn ein ValidationResult oder ValidationIssue ungültig ist."""


class ValidationSeverity(str, Enum):
    """Schweregrad einer Validierungsmeldung."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class ValidationScope(str, Enum):
    """Validierungsbereich."""

    UNKNOWN = "unknown"
    REQUEST = "request"
    CONTEXT = "context"
    MODULE_PLAN = "module_plan"
    PACKAGE_PLAN = "package_plan"
    PACKAGE = "package"
    PATH = "path"
    FILE = "file"
    JSON = "json"
    MODULE = "module"
    VARIANT = "variant"
    ASSET = "asset"
    PLACEMENT = "placement"
    RENDER = "render"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    ANALYSIS = "analysis"
    DYNAMIC = "dynamic"
    MANUFACTURER = "manufacturer"
    ARCHIVE = "archive"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class ValidationIssueCode(str, Enum):
    """Generische Validierungscodes für die erste robuste Engine-Stufe."""

    UNKNOWN = "VPLIB_UNKNOWN"
    INVALID_INPUT = "VPLIB_INVALID_INPUT"
    INVALID_VALUE = "VPLIB_INVALID_VALUE"
    INVALID_TYPE = "VPLIB_INVALID_TYPE"
    MISSING_REQUIRED_VALUE = "VPLIB_MISSING_REQUIRED_VALUE"
    MISSING_REQUIRED_FIELD = "VPLIB_MISSING_REQUIRED_FIELD"
    MISSING_REQUIRED_MODULE = "VPLIB_MISSING_REQUIRED_MODULE"
    MISSING_REQUIRED_FILE = "VPLIB_MISSING_REQUIRED_FILE"
    INVALID_PATH = "VPLIB_INVALID_PATH"
    FORBIDDEN_PATH = "VPLIB_FORBIDDEN_PATH"
    FORBIDDEN_FILE_TYPE = "VPLIB_FORBIDDEN_FILE_TYPE"
    DUPLICATE_VALUE = "VPLIB_DUPLICATE_VALUE"
    DUPLICATE_PATH = "VPLIB_DUPLICATE_PATH"
    INVALID_OBJECT_KIND = "VPLIB_INVALID_OBJECT_KIND"
    INVALID_CLASSIFICATION = "VPLIB_INVALID_CLASSIFICATION"
    INVALID_MODULE_SET = "VPLIB_INVALID_MODULE_SET"
    INVALID_DEPENDENCY = "VPLIB_INVALID_DEPENDENCY"
    INVALID_VARIANT = "VPLIB_INVALID_VARIANT"
    INVALID_VARIANT_OVERRIDE = "VPLIB_INVALID_VARIANT_OVERRIDE"
    INVALID_PLACEMENT = "VPLIB_INVALID_PLACEMENT"
    INVALID_ASSET = "VPLIB_INVALID_ASSET"
    ASSET_NOT_FOUND = "VPLIB_ASSET_NOT_FOUND"
    MODEL_OUT_OF_BOUNDS = "VPLIB_MODEL_OUT_OF_BOUNDS"
    INVALID_RENDER_DATA = "VPLIB_INVALID_RENDER_DATA"
    INVALID_PHYSICAL_DATA = "VPLIB_INVALID_PHYSICAL_DATA"
    INVALID_MATERIAL_DATA = "VPLIB_INVALID_MATERIAL_DATA"
    INVALID_CALCULATION_DATA = "VPLIB_INVALID_CALCULATION_DATA"
    INVALID_DYNAMIC_DATA = "VPLIB_INVALID_DYNAMIC_DATA"
    INVALID_MANUFACTURER_DATA = "VPLIB_INVALID_MANUFACTURER_DATA"
    ARCHIVE_ERROR = "VPLIB_ARCHIVE_ERROR"
    INTERNAL_ERROR = "VPLIB_INTERNAL_ERROR"

    @property
    def key(self) -> str:
        return str(self.value)


_SEVERITY_RANK: Final[dict[str, int]] = {
    ValidationSeverity.INFO.value: 10,
    ValidationSeverity.WARNING.value: 20,
    ValidationSeverity.ERROR.value: 30,
    ValidationSeverity.FATAL.value: 40,
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """
    Einzelne Validierungsmeldung.

    path ist ein Package-Pfad oder lokaler Kontextpfad.
    field_path ist ein JSON-/Objektfeldpfad.
    module_name ist optional und verweist auf ein VPLIB-Modul.
    details bleibt JSON-kompatibel.
    """

    code: str
    message: str
    severity: str = ValidationSeverity.ERROR.value
    scope: str = ValidationScope.UNKNOWN.value
    path: str | None = None
    field_path: str | None = None
    module_name: str | None = None
    hint: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ValidationIssue":
        code = parse_issue_code_value(self.code)
        message = clean_required_string(self.message, "message")
        severity = parse_severity_value(self.severity)
        scope = parse_scope_value(self.scope)
        path = clean_optional_string(self.path)
        field_path = normalize_optional_field_path(self.field_path)
        module_name = normalize_optional_module_name(self.module_name)
        hint = clean_optional_string(self.hint)
        details = normalize_details_mapping(self.details)

        return ValidationIssue(
            code=code,
            message=message,
            severity=severity,
            scope=scope,
            path=path,
            field_path=field_path,
            module_name=module_name,
            hint=hint,
            details=details,
        )

    @property
    def is_info(self) -> bool:
        return self.normalized().severity == ValidationSeverity.INFO.value

    @property
    def is_warning(self) -> bool:
        return self.normalized().severity == ValidationSeverity.WARNING.value

    @property
    def is_error(self) -> bool:
        return self.normalized().severity == ValidationSeverity.ERROR.value

    @property
    def is_fatal(self) -> bool:
        return self.normalized().severity == ValidationSeverity.FATAL.value

    @property
    def blocks_success(self) -> bool:
        return self.normalized().severity in {
            ValidationSeverity.ERROR.value,
            ValidationSeverity.FATAL.value,
        }

    def with_severity(self, severity: str) -> "ValidationIssue":
        normalized = self.normalized()

        return ValidationIssue(
            code=normalized.code,
            message=normalized.message,
            severity=parse_severity_value(severity),
            scope=normalized.scope,
            path=normalized.path,
            field_path=normalized.field_path,
            module_name=normalized.module_name,
            hint=normalized.hint,
            details=dict(normalized.details),
        ).normalized()

    def with_detail(self, key: str, value: Any) -> "ValidationIssue":
        normalized = self.normalized()
        details = dict(normalized.details)
        details[clean_required_string(key, "detail key")] = normalize_detail_value(value)

        return ValidationIssue(
            code=normalized.code,
            message=normalized.message,
            severity=normalized.severity,
            scope=normalized.scope,
            path=normalized.path,
            field_path=normalized.field_path,
            module_name=normalized.module_name,
            hint=normalized.hint,
            details=details,
        ).normalized()

    def fingerprint(self) -> str:
        """Erzeugt einen stabilen Fingerprint zur Deduplizierung."""
        normalized = self.normalized()

        return "|".join(
            (
                normalized.code,
                normalized.severity,
                normalized.scope,
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
            "scope": normalized.scope,
            "path": normalized.path,
            "field_path": normalized.field_path,
            "module_name": normalized.module_name,
            "hint": normalized.hint,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """
    Vollständiges Validierungsergebnis.

    Ein Ergebnis ist erfolgreich, wenn keine ERROR- oder FATAL-Issues vorhanden sind.
    WARNING und INFO blockieren Erfolg nicht.
    """

    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    target: str | None = None
    valid: bool | None = None
    schema_version: str = VALIDATION_RESULT_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ValidationResult":
        target = clean_optional_string(self.target)
        metadata = normalize_details_mapping(self.metadata)

        normalized_issues = tuple(
            issue.normalized()
            for issue in self.issues or ()
        )
        normalized_issues = dedupe_issues(normalized_issues)
        normalized_issues = sort_issues(normalized_issues)

        computed_valid = not any(issue.blocks_success for issue in normalized_issues)
        valid = computed_valid if self.valid is None else bool(self.valid)

        if valid and any(issue.blocks_success for issue in normalized_issues):
            valid = False

        return ValidationResult(
            issues=normalized_issues,
            target=target,
            valid=valid,
            schema_version=self.schema_version or VALIDATION_RESULT_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def is_valid(self) -> bool:
        return bool(self.normalized().valid)

    @property
    def has_issues(self) -> bool:
        return bool(self.normalized().issues)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    @property
    def info(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == ValidationSeverity.INFO.value
        )

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == ValidationSeverity.WARNING.value
        )

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == ValidationSeverity.ERROR.value
        )

    @property
    def fatal_errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == ValidationSeverity.FATAL.value
        )

    @property
    def blocking_issues(self) -> tuple[ValidationIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.blocks_success
        )

    @property
    def issue_count(self) -> int:
        return len(self.normalized().issues)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def fatal_count(self) -> int:
        return len(self.fatal_errors)

    def with_issue(self, issue: ValidationIssue) -> "ValidationResult":
        normalized = self.normalized()

        return ValidationResult(
            issues=(*normalized.issues, issue.normalized()),
            target=normalized.target,
            valid=None,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_issues(self, issues: Iterable[ValidationIssue]) -> "ValidationResult":
        result = self.normalized()

        for issue in issues or ():
            result = result.with_issue(issue)

        return result.normalized()

    def with_metadata(self, metadata: Mapping[str, Any]) -> "ValidationResult":
        normalized = self.normalized()
        merged = dict(normalized.metadata)
        merged.update(normalize_details_mapping(metadata))

        return ValidationResult(
            issues=normalized.issues,
            target=normalized.target,
            valid=normalized.valid,
            schema_version=normalized.schema_version,
            metadata=merged,
        ).normalized()

    def for_target(self, target: str | None) -> "ValidationResult":
        normalized = self.normalized()

        return ValidationResult(
            issues=normalized.issues,
            target=target,
            valid=normalized.valid,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def issues_by_scope(self, scope: str) -> tuple[ValidationIssue, ...]:
        scope_value = parse_scope_value(scope)

        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.scope == scope_value
        )

    def issues_by_module(self, module_name: str) -> tuple[ValidationIssue, ...]:
        module_value = normalize_optional_module_name(module_name)

        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.module_name == module_value
        )

    def issues_by_path(self, path: str) -> tuple[ValidationIssue, ...]:
        path_value = clean_required_string(path, "path")

        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.path == path_value
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "valid": normalized.valid,
            "target": normalized.target,
            "issue_count": normalized.issue_count,
            "warning_count": normalized.warning_count,
            "error_count": normalized.error_count,
            "fatal_count": normalized.fatal_count,
            "issues": [issue.to_dict() for issue in normalized.issues],
            "metadata": dict(normalized.metadata),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "valid": normalized.valid,
            "target": normalized.target,
            "issue_count": normalized.issue_count,
            "warning_count": normalized.warning_count,
            "error_count": normalized.error_count,
            "fatal_count": normalized.fatal_count,
            "blocking_issue_count": len(normalized.blocking_issues),
        }


def validation_issue(
    *,
    code: str = ValidationIssueCode.UNKNOWN.value,
    message: str,
    severity: str = ValidationSeverity.ERROR.value,
    scope: str = ValidationScope.UNKNOWN.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    """Factory für eine ValidationIssue."""
    return ValidationIssue(
        code=code,
        message=message,
        severity=severity,
        scope=scope,
        path=path,
        field_path=field_path,
        module_name=module_name,
        hint=hint,
        details=dict(details or {}),
    ).normalized()


def validation_info(
    message: str,
    *,
    code: str = ValidationIssueCode.UNKNOWN.value,
    scope: str = ValidationScope.UNKNOWN.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    """Factory für eine INFO-Meldung."""
    return validation_issue(
        code=code,
        message=message,
        severity=ValidationSeverity.INFO.value,
        scope=scope,
        path=path,
        field_path=field_path,
        module_name=module_name,
        hint=hint,
        details=details,
    )


def validation_warning(
    message: str,
    *,
    code: str = ValidationIssueCode.UNKNOWN.value,
    scope: str = ValidationScope.UNKNOWN.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    """Factory für eine WARNING-Meldung."""
    return validation_issue(
        code=code,
        message=message,
        severity=ValidationSeverity.WARNING.value,
        scope=scope,
        path=path,
        field_path=field_path,
        module_name=module_name,
        hint=hint,
        details=details,
    )


def validation_error(
    message: str,
    *,
    code: str = ValidationIssueCode.UNKNOWN.value,
    scope: str = ValidationScope.UNKNOWN.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    """Factory für eine ERROR-Meldung."""
    return validation_issue(
        code=code,
        message=message,
        severity=ValidationSeverity.ERROR.value,
        scope=scope,
        path=path,
        field_path=field_path,
        module_name=module_name,
        hint=hint,
        details=details,
    )


def validation_fatal(
    message: str,
    *,
    code: str = ValidationIssueCode.INTERNAL_ERROR.value,
    scope: str = ValidationScope.SYSTEM.value,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    """Factory für eine FATAL-Meldung."""
    return validation_issue(
        code=code,
        message=message,
        severity=ValidationSeverity.FATAL.value,
        scope=scope,
        path=path,
        field_path=field_path,
        module_name=module_name,
        hint=hint,
        details=details,
    )


def valid_result(
    *,
    target: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ValidationResult:
    """Erzeugt ein gültiges Ergebnis ohne Issues."""
    return ValidationResult(
        issues=tuple(),
        target=target,
        valid=True,
        metadata=dict(metadata or {}),
    ).normalized()


def invalid_result(
    issues: Iterable[ValidationIssue],
    *,
    target: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ValidationResult:
    """Erzeugt ein ungültiges Ergebnis aus Issues."""
    return ValidationResult(
        issues=tuple(issue.normalized() for issue in issues or ()),
        target=target,
        valid=False,
        metadata=dict(metadata or {}),
    ).normalized()


def result_from_exception(
    exception: BaseException,
    *,
    target: str | None = None,
    scope: str = ValidationScope.SYSTEM.value,
    code: str = ValidationIssueCode.INTERNAL_ERROR.value,
    include_traceback: bool = False,
) -> ValidationResult:
    """Erzeugt ein ValidationResult aus einer Exception."""
    details: dict[str, Any] = {
        "exception_type": type(exception).__name__,
    }

    if include_traceback:
        details["traceback"] = "".join(
            traceback.format_exception(
                type(exception),
                exception,
                exception.__traceback__,
            )
        )

    return invalid_result(
        (
            validation_fatal(
                message=str(exception) or type(exception).__name__,
                code=code,
                scope=scope,
                details=details,
            ),
        ),
        target=target,
    )


def merge_validation_results(
    *results: ValidationResult,
    target: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ValidationResult:
    """Merged mehrere ValidationResults."""
    issues: list[ValidationIssue] = []
    merged_metadata: dict[str, Any] = {}

    for result in results or ():
        normalized = result.normalized()
        issues.extend(normalized.issues)
        merged_metadata.update(dict(normalized.metadata))

    merged_metadata.update(dict(metadata or {}))

    return ValidationResult(
        issues=tuple(issues),
        target=target,
        valid=None,
        metadata=merged_metadata,
    ).normalized()


def validation_result_from_mapping(data: Mapping[str, Any]) -> ValidationResult:
    """Baut ein ValidationResult aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise ValidationResultError("ValidationResult data must be a mapping.")

        issues = tuple(
            validation_issue_from_mapping(item)
            for item in data.get("issues", ()) or ()
            if isinstance(item, Mapping)
        )

        return ValidationResult(
            issues=issues,
            target=data.get("target"),
            valid=data.get("valid"),
            schema_version=data.get("schema_version", VALIDATION_RESULT_SCHEMA_VERSION),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except ValidationResultError:
        raise
    except Exception as exc:
        raise ValidationResultError(f"Could not build ValidationResult from mapping: {exc}") from exc


def validation_issue_from_mapping(data: Mapping[str, Any]) -> ValidationIssue:
    """Baut eine ValidationIssue aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise ValidationResultError("ValidationIssue data must be a mapping.")

        return ValidationIssue(
            code=data.get("code", ValidationIssueCode.UNKNOWN.value),
            message=data.get("message", "Validation issue."),
            severity=data.get("severity", ValidationSeverity.ERROR.value),
            scope=data.get("scope", ValidationScope.UNKNOWN.value),
            path=data.get("path"),
            field_path=data.get("field_path") or data.get("field"),
            module_name=data.get("module_name") or data.get("module"),
            hint=data.get("hint"),
            details=dict(data.get("details", {}) or {}),
        ).normalized()
    except ValidationResultError:
        raise
    except Exception as exc:
        raise ValidationResultError(f"Could not build ValidationIssue from mapping: {exc}") from exc


def dedupe_issues(issues: Iterable[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    """Entfernt doppelte Issues anhand ihres Fingerprints."""
    result: list[ValidationIssue] = []
    seen: set[str] = set()

    for issue in issues or ():
        normalized = issue.normalized()
        fingerprint = normalized.fingerprint()

        if fingerprint in seen:
            continue

        result.append(normalized)
        seen.add(fingerprint)

    return tuple(result)


def sort_issues(issues: Iterable[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    """Sortiert Issues stabil nach Schweregrad und Kontext."""
    return tuple(
        sorted(
            (issue.normalized() for issue in issues or ()),
            key=lambda issue: (
                -_SEVERITY_RANK.get(issue.severity, 0),
                issue.scope,
                issue.module_name or "",
                issue.path or "",
                issue.field_path or "",
                issue.code,
                issue.message,
            ),
        )
    )


@lru_cache(maxsize=128)
def parse_severity_value(value: Any) -> str:
    """Parst ValidationSeverity."""
    try:
        if isinstance(value, ValidationSeverity):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "info": ValidationSeverity.INFO.value,
            "information": ValidationSeverity.INFO.value,
            "notice": ValidationSeverity.INFO.value,
            "warn": ValidationSeverity.WARNING.value,
            "warning": ValidationSeverity.WARNING.value,
            "error": ValidationSeverity.ERROR.value,
            "err": ValidationSeverity.ERROR.value,
            "fatal": ValidationSeverity.FATAL.value,
            "critical": ValidationSeverity.FATAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ValidationSeverity(raw).value
    except Exception as exc:
        raise ValidationResultError(f"Invalid validation severity {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_scope_value(value: Any) -> str:
    """Parst ValidationScope."""
    try:
        if isinstance(value, ValidationScope):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "unknown": ValidationScope.UNKNOWN.value,
            "request": ValidationScope.REQUEST.value,
            "create_request": ValidationScope.REQUEST.value,
            "context": ValidationScope.CONTEXT.value,
            "package_context": ValidationScope.CONTEXT.value,
            "module_plan": ValidationScope.MODULE_PLAN.value,
            "package_plan": ValidationScope.PACKAGE_PLAN.value,
            "package": ValidationScope.PACKAGE.value,
            "path": ValidationScope.PATH.value,
            "file": ValidationScope.FILE.value,
            "json": ValidationScope.JSON.value,
            "module": ValidationScope.MODULE.value,
            "variant": ValidationScope.VARIANT.value,
            "asset": ValidationScope.ASSET.value,
            "placement": ValidationScope.PLACEMENT.value,
            "render": ValidationScope.RENDER.value,
            "physical": ValidationScope.PHYSICAL.value,
            "material": ValidationScope.MATERIAL.value,
            "calculation": ValidationScope.CALCULATION.value,
            "analysis": ValidationScope.ANALYSIS.value,
            "dynamic": ValidationScope.DYNAMIC.value,
            "manufacturer": ValidationScope.MANUFACTURER.value,
            "archive": ValidationScope.ARCHIVE.value,
            "system": ValidationScope.SYSTEM.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ValidationScope(raw).value
    except Exception as exc:
        raise ValidationResultError(f"Invalid validation scope {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_issue_code_value(value: Any) -> str:
    """Parst einen Issue-Code."""
    try:
        if isinstance(value, ValidationIssueCode):
            return value.value

        raw = str(value).strip()

        if not raw:
            raise ValidationResultError("Validation issue code is required.")

        upper = raw.upper().replace(" ", "_").replace("-", "_")

        if not upper.startswith("VPLIB_"):
            upper = f"VPLIB_{upper}"

        try:
            return ValidationIssueCode(upper).value
        except ValueError:
            return upper
    except ValidationResultError:
        raise
    except Exception as exc:
        raise ValidationResultError(f"Invalid validation issue code {value!r}.") from exc


def normalize_optional_module_name(value: Any) -> str | None:
    """Normalisiert optionalen Modulnamen."""
    if value is None:
        return None

    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception:
        return clean_optional_string(value)


def normalize_optional_field_path(value: Any) -> str | None:
    """Normalisiert optionalen Field-Path."""
    if value is None:
        return None

    try:
        raw = str(value).strip()
        if not raw:
            return None

        return (
            raw.replace(" ", "_")
            .replace("-", "_")
            .replace("/", ".")
            .replace("\\", ".")
        )
    except Exception:
        return None


def normalize_details_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Details/Metadata rekursiv JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ValidationResultError("details must be a mapping.")

    return {
        str(key): normalize_detail_value(child_value)
        for key, child_value in value.items()
    }


def normalize_detail_value(value: Any) -> Any:
    """Normalisiert einen Details-Wert JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_details_mapping(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_detail_value(item) for item in value]

    return str(value)


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ValidationResultError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ValidationResultError:
        raise
    except Exception as exc:
        raise ValidationResultError(f"Invalid enum value {value!r}.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ValidationResultError(f"{field_name} is required.")

        return cleaned
    except ValidationResultError:
        raise
    except Exception as exc:
        raise ValidationResultError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_validation_result_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_severity_value.cache_clear()
    parse_scope_value.cache_clear()
    parse_issue_code_value.cache_clear()


__all__ = [
    "VALIDATION_RESULT_SCHEMA_VERSION",
    "ValidationIssue",
    "ValidationIssueCode",
    "ValidationResult",
    "ValidationResultError",
    "ValidationScope",
    "ValidationSeverity",
    "clean_optional_string",
    "clean_required_string",
    "clear_validation_result_caches",
    "dedupe_issues",
    "invalid_result",
    "merge_validation_results",
    "normalize_detail_value",
    "normalize_details_mapping",
    "normalize_enum_key",
    "normalize_optional_field_path",
    "normalize_optional_module_name",
    "parse_issue_code_value",
    "parse_scope_value",
    "parse_severity_value",
    "result_from_exception",
    "sort_issues",
    "valid_result",
    "validation_error",
    "validation_fatal",
    "validation_info",
    "validation_issue",
    "validation_issue_from_mapping",
    "validation_result_from_mapping",
    "validation_warning",
]