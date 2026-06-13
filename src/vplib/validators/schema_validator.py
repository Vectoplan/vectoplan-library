# services/vectoplan-library/src/vplib/validators/schema_validator.py
"""
Schema validator for the VPLIB package engine.

Diese Datei validiert JSON-kompatible VPLIB-Dokumente auf struktureller Ebene.

Rolle dieser Datei:

    document payload
    document path
    optional DocumentBundle
    -> SchemaValidationResult / ValidationResult

Diese Datei prüft:
- JSON-Kompatibilität
- schema_version
- bekannte Pflichtfelder pro Dokumenttyp
- bekannte dokumentbezogene Validatoren aus defaults/*
- package-relative Pfadsicherheit
- grobe Modulzuordnung

Diese Datei schreibt keine Dateien und liest keine Dateien vom Dateisystem.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Callable, Final, Iterable, Mapping


SCHEMA_VALIDATOR_SCHEMA_VERSION: Final[str] = "vplib.schema_validator.v1"

ROOT_DOCUMENT_PATHS: Final[tuple[str, ...]] = (
    "vplib.manifest.json",
    "vplib.modules.json",
)

GENERIC_REQUIRED_JSON_FIELDS: Final[tuple[str, ...]] = (
    "schema_version",
)

KNOWN_JSON_DOCUMENT_EXTENSIONS: Final[tuple[str, ...]] = (
    ".json",
)


class SchemaValidatorError(ValueError):
    """Wird ausgelöst, wenn die Schema-Validierung selbst fehlschlägt."""


class SchemaValidationStatus(str, Enum):
    """Status einer Schema-Validierung."""

    VALID = "valid"
    INVALID = "invalid"
    SKIPPED = "skipped"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class SchemaValidationScope(str, Enum):
    """Validierungsbereich."""

    DOCUMENT = "document"
    DOCUMENT_BUNDLE = "document_bundle"
    PACKAGE_PATH = "package_path"
    JSON = "json"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class SchemaValidationMode(str, Enum):
    """Validierungsmodus."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SchemaValidationOptions:
    """Optionen für die Schema-Validierung."""

    mode: str = SchemaValidationMode.STRICT.value
    require_schema_version: bool = True
    require_known_document_validator: bool = False
    validate_json_compatibility: bool = True
    validate_package_path: bool = True
    allow_unknown_documents: bool = True
    collect_all_errors: bool = True
    strict: bool = True

    def normalized(self) -> "SchemaValidationOptions":
        mode = parse_validation_mode_value(self.mode)

        return SchemaValidationOptions(
            mode=mode,
            require_schema_version=bool(self.require_schema_version),
            require_known_document_validator=bool(self.require_known_document_validator),
            validate_json_compatibility=bool(self.validate_json_compatibility),
            validate_package_path=bool(self.validate_package_path),
            allow_unknown_documents=bool(self.allow_unknown_documents),
            collect_all_errors=bool(self.collect_all_errors),
            strict=bool(self.strict),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "mode": normalized.mode,
            "require_schema_version": normalized.require_schema_version,
            "require_known_document_validator": normalized.require_known_document_validator,
            "validate_json_compatibility": normalized.validate_json_compatibility,
            "validate_package_path": normalized.validate_package_path,
            "allow_unknown_documents": normalized.allow_unknown_documents,
            "collect_all_errors": normalized.collect_all_errors,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class SchemaValidationTarget:
    """Ein einzelnes zu validierendes Dokument."""

    relative_path: str
    document: Mapping[str, Any]
    module_name: str | None = None
    schema_version: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SchemaValidationTarget":
        relative_path = normalize_package_path(self.relative_path)
        document = normalize_document_mapping(self.document)
        module_name = normalize_optional_module_name(self.module_name) or infer_module_from_path_safe(relative_path)
        schema_version = clean_optional_string(self.schema_version) or clean_optional_string(document.get("schema_version"))
        metadata = normalize_metadata(self.metadata)

        return SchemaValidationTarget(
            relative_path=relative_path,
            document=document,
            module_name=module_name,
            schema_version=schema_version,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "module_name": normalized.module_name,
            "schema_version": normalized.schema_version,
            "document": dict(normalized.document),
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SchemaValidationReport:
    """Kompakter Bericht für eine einzelne Dokumentvalidierung."""

    relative_path: str
    module_name: str | None
    status: str
    valid: bool
    messages: tuple[str, ...] = field(default_factory=tuple)
    schema_version: str | None = None
    validator_name: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SchemaValidationReport":
        relative_path = normalize_package_path(self.relative_path)
        module_name = normalize_optional_module_name(self.module_name)
        status = parse_validation_status_value(self.status)
        valid = bool(self.valid)
        messages = normalize_string_tuple(self.messages)
        schema_version = clean_optional_string(self.schema_version)
        validator_name = clean_optional_string(self.validator_name)
        metadata = normalize_metadata(self.metadata)

        if status == SchemaValidationStatus.VALID.value and messages:
            status = SchemaValidationStatus.INVALID.value
            valid = False

        if status in {SchemaValidationStatus.INVALID.value, SchemaValidationStatus.ERROR.value}:
            valid = False

        return SchemaValidationReport(
            relative_path=relative_path,
            module_name=module_name,
            status=status,
            valid=valid,
            messages=messages,
            schema_version=schema_version,
            validator_name=validator_name,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "relative_path": normalized.relative_path,
            "module_name": normalized.module_name,
            "status": normalized.status,
            "valid": normalized.valid,
            "messages": list(normalized.messages),
            "schema_version": normalized.schema_version,
            "validator_name": normalized.validator_name,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class SchemaValidationResult:
    """Ergebnis der Schema-Validierung."""

    reports: tuple[SchemaValidationReport, ...] = field(default_factory=tuple)
    validation_result: Any | None = None
    status: str = SchemaValidationStatus.VALID.value
    schema_version: str = SCHEMA_VALIDATOR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "SchemaValidationResult":
        reports = tuple(report.normalized() for report in self.reports or ())
        status = parse_validation_status_value(self.status)
        metadata = normalize_metadata(self.metadata)
        validation_result = normalize_validation_result(self.validation_result)

        valid = all(report.valid for report in reports)

        if not valid:
            status = SchemaValidationStatus.INVALID.value

        if validation_result is None:
            validation_result = build_validation_result_from_reports(reports)

        return SchemaValidationResult(
            reports=reports,
            validation_result=validation_result,
            status=status,
            schema_version=self.schema_version or SCHEMA_VALIDATOR_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def valid(self) -> bool:
        return all(report.valid for report in self.normalized().reports)

    @property
    def report_count(self) -> int:
        return len(self.normalized().reports)

    @property
    def invalid_reports(self) -> tuple[SchemaValidationReport, ...]:
        return tuple(report for report in self.normalized().reports if not report.valid)

    @property
    def messages(self) -> tuple[str, ...]:
        result: list[str] = []

        for report in self.normalized().reports:
            result.extend(report.messages)

        return tuple(result)

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
            "report_count": normalized.report_count,
            "invalid_report_count": len(normalized.invalid_reports),
            "messages": list(normalized.messages),
            "reports": [report.to_dict() for report in normalized.reports],
            "validation_result": validation_payload,
            "metadata": dict(normalized.metadata),
        }


def validate_document_schema(
    *,
    relative_path: str,
    document: Mapping[str, Any],
    options: SchemaValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SchemaValidationReport:
    """Validiert ein einzelnes Dokument anhand seines package-relativen Pfads."""
    normalized_options = normalize_options(options)

    try:
        target = SchemaValidationTarget(
            relative_path=relative_path,
            document=document,
            metadata=dict(metadata or {}),
        ).normalized()

        messages: list[str] = []

        if normalized_options.validate_package_path:
            path_valid, path_messages = validate_package_path(target.relative_path)
            messages.extend(path_messages)
            if not path_valid and not normalized_options.collect_all_errors:
                return invalid_report_from_messages(target, messages, validator_name="package_path")

        if normalized_options.validate_json_compatibility:
            json_valid, json_messages = validate_json_compatible_document(target.document)
            messages.extend(json_messages)
            if not json_valid and not normalized_options.collect_all_errors:
                return invalid_report_from_messages(target, messages, validator_name="json_compatibility")

        if normalized_options.require_schema_version and not target.schema_version:
            messages.append(f"Document {target.relative_path!r} is missing schema_version.")
            if not normalized_options.collect_all_errors:
                return invalid_report_from_messages(target, messages, validator_name="schema_version")

        validator = get_document_validator(target.relative_path)

        if validator is None:
            if normalized_options.require_known_document_validator:
                messages.append(f"No schema validator registered for document {target.relative_path!r}.")
            elif not normalized_options.allow_unknown_documents:
                messages.append(f"Unknown document {target.relative_path!r} is not allowed.")
            else:
                generic_valid, generic_messages = validate_generic_document(target.document)
                messages.extend(generic_messages)

            return SchemaValidationReport(
                relative_path=target.relative_path,
                module_name=target.module_name,
                status=SchemaValidationStatus.VALID.value if not messages else SchemaValidationStatus.INVALID.value,
                valid=not messages,
                messages=tuple(messages),
                schema_version=target.schema_version,
                validator_name=None,
                metadata=dict(target.metadata),
            ).normalized()

        try:
            valid, validator_messages = validator(target.document)
            messages.extend(tuple(str(message) for message in validator_messages or ()))

            return SchemaValidationReport(
                relative_path=target.relative_path,
                module_name=target.module_name,
                status=SchemaValidationStatus.VALID.value if valid and not messages else SchemaValidationStatus.INVALID.value,
                valid=bool(valid) and not messages,
                messages=tuple(messages),
                schema_version=target.schema_version,
                validator_name=get_validator_name(validator),
                metadata=dict(target.metadata),
            ).normalized()
        except Exception as exc:
            messages.append(f"Schema validator failed for {target.relative_path!r}: {exc}")

            return SchemaValidationReport(
                relative_path=target.relative_path,
                module_name=target.module_name,
                status=SchemaValidationStatus.ERROR.value,
                valid=False,
                messages=tuple(messages),
                schema_version=target.schema_version,
                validator_name=get_validator_name(validator),
                metadata=dict(target.metadata),
            ).normalized()

    except Exception as exc:
        path = clean_optional_string(relative_path) or "<unknown>"

        return SchemaValidationReport(
            relative_path=path,
            module_name=infer_module_from_path_safe(path),
            status=SchemaValidationStatus.ERROR.value,
            valid=False,
            messages=(f"Could not validate document schema: {exc}",),
            schema_version=None,
            validator_name=None,
            metadata=dict(metadata or {}),
        ).normalized()


def validate_documents_schema(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    options: SchemaValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SchemaValidationResult:
    """Validiert mehrere Dokumente als path -> document Mapping."""
    try:
        if not isinstance(documents, Mapping):
            raise SchemaValidatorError("documents must be a mapping.")

        normalized_options = normalize_options(options)

        reports = tuple(
            validate_document_schema(
                relative_path=relative_path,
                document=document,
                options=normalized_options,
            )
            for relative_path, document in documents.items()
        )

        return SchemaValidationResult(
            reports=reports,
            status=SchemaValidationStatus.VALID.value if all(report.valid for report in reports) else SchemaValidationStatus.INVALID.value,
            metadata={
                "source": "documents",
                **dict(metadata or {}),
            },
        ).normalized()
    except SchemaValidatorError:
        raise
    except Exception as exc:
        raise SchemaValidatorError(f"Could not validate documents schema: {exc}") from exc


def validate_document_bundle_schema(
    bundle: Any,
    *,
    options: SchemaValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SchemaValidationResult:
    """Validiert ein DocumentBundle-ähnliches Objekt."""
    try:
        normalized_bundle = normalize_document_bundle(bundle)

        return validate_documents_schema(
            normalized_bundle.to_documents()
            if hasattr(normalized_bundle, "to_documents")
            else normalized_bundle.documents,
            options=options,
            metadata={
                "source": "document_bundle",
                "bundle_schema_version": getattr(normalized_bundle, "schema_version", None),
                **dict(metadata or {}),
            },
        ).normalized()
    except SchemaValidatorError:
        raise
    except Exception as exc:
        raise SchemaValidatorError(f"Could not validate document bundle schema: {exc}") from exc


def validate_creation_plan_documents_schema(
    creation_plan: Any,
    *,
    options: SchemaValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> SchemaValidationResult:
    """Baut ein DocumentBundle aus einem CreationPlan und validiert dessen Dokumente."""
    try:
        from ..defaults.document_bundle import build_document_bundle_from_creation_plan

        bundle = build_document_bundle_from_creation_plan(creation_plan)

        return validate_document_bundle_schema(
            bundle,
            options=options,
            metadata={
                "source": "creation_plan",
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        raise SchemaValidatorError(f"Could not validate creation plan documents schema: {exc}") from exc


def get_document_validator(relative_path: Any) -> Callable[[Mapping[str, Any]], tuple[bool, tuple[str, ...]]] | None:
    """Löst einen dokumentbezogenen Validator anhand des Pfads auf."""
    path = normalize_package_path(relative_path)
    registry = get_document_validator_registry()

    if path in registry:
        return registry[path]

    if path.startswith("variants/") and path.endswith(".json") and path != "variants/index.json":
        return registry.get("variants/<variant_id>.json")

    return None


@lru_cache(maxsize=1)
def get_document_validator_registry() -> Mapping[str, Callable[[Mapping[str, Any]], tuple[bool, tuple[str, ...]]]]:
    """Erzeugt die Pfad-zu-Validator-Registry lazy."""
    registry: dict[str, Callable[[Mapping[str, Any]], tuple[bool, tuple[str, ...]]]] = {}

    register_validator_safe(registry, "vplib.manifest.json", ".manifest_defaults", "validate_manifest_document")
    register_validator_safe(registry, "vplib.modules.json", ".module_defaults", "validate_modules_document")

    register_validator_safe(registry, "family/identity.json", ".family_defaults", "validate_family_identity_document")
    register_validator_safe(registry, "family/classification.json", ".family_defaults", "validate_family_classification_document")

    register_validator_safe(registry, "variants/index.json", ".variant_defaults", "validate_variant_index_document")
    register_validator_safe(registry, "variants/<variant_id>.json", ".variant_defaults", "validate_variant_document")

    register_validator_safe(registry, "editor/inventory.json", ".editor_defaults", "validate_inventory_document")
    register_validator_safe(registry, "editor/placement.json", ".editor_defaults", "validate_placement_document")

    register_validator_safe(registry, "render/render_variants.json", ".render_defaults", "validate_render_variants_document")
    register_validator_safe(registry, "render/bounds.json", ".render_defaults", "validate_render_bounds_document")

    register_validator_safe(registry, "physical/base.json", ".physical_defaults", "validate_physical_base_document")
    register_validator_safe(registry, "physical/dimensions.json", ".physical_defaults", "validate_physical_dimensions_document")
    register_validator_safe(registry, "physical/collision.json", ".physical_defaults", "validate_physical_collision_document")

    register_validator_safe(registry, "material/base.json", ".material_defaults", "validate_material_base_document")
    register_validator_safe(registry, "material/performance.json", ".material_defaults", "validate_material_performance_document")

    register_validator_safe(registry, "calculation/variables.json", ".calculation_defaults", "validate_variables_document")
    register_validator_safe(registry, "calculation/formulas.json", ".calculation_defaults", "validate_formulas_document")
    register_validator_safe(registry, "calculation/quantities.json", ".calculation_defaults", "validate_quantities_document")
    register_validator_safe(registry, "calculation/measure_logic.json", ".calculation_defaults", "validate_measure_logic_document")

    register_validator_safe(registry, "manufacturer/contract.json", ".manufacturer_defaults", "validate_manufacturer_contract_document")
    register_validator_safe(registry, "manufacturer/override_slots.json", ".manufacturer_defaults", "validate_override_slots_document")

    register_validator_safe(registry, "analysis/statics/profile.json", ".analysis_defaults", "validate_statics_profile_document")
    register_validator_safe(registry, "analysis/routing/profile.json", ".analysis_defaults", "validate_routing_profile_document")
    register_validator_safe(registry, "analysis/reinforcement/profile.json", ".analysis_defaults", "validate_reinforcement_profile_document")

    register_validator_safe(registry, "dynamic/context_rules.json", ".dynamic_defaults", "validate_context_rules_document")
    register_validator_safe(registry, "dynamic/bindings.json", ".dynamic_defaults", "validate_bindings_document")
    register_validator_safe(registry, "dynamic/generator.json", ".dynamic_defaults", "validate_generator_document")

    return registry


def register_validator_safe(
    registry: dict[str, Callable[[Mapping[str, Any]], tuple[bool, tuple[str, ...]]]],
    relative_path: str,
    module_path: str,
    function_name: str,
) -> None:
    """Registriert einen Validator defensiv."""
    try:
        import importlib

        module = importlib.import_module(module_path, package="vplib.defaults")
        validator = getattr(module, function_name)

        if callable(validator):
            registry[relative_path] = validator
    except Exception:
        return


def validate_package_path(relative_path: Any) -> tuple[bool, tuple[str, ...]]:
    """Validiert package-relative Pfade grob."""
    messages: list[str] = []

    try:
        path = normalize_package_path(relative_path)

        if not path.endswith(KNOWN_JSON_DOCUMENT_EXTENSIONS):
            messages.append(f"Document path {path!r} does not use a supported JSON extension.")

        if path.startswith("../") or "/../" in path or path == "..":
            messages.append(f"Document path {path!r} contains parent traversal.")

        if path.startswith("/") or "\\" in path:
            messages.append(f"Document path {path!r} must be package-relative POSIX style.")

    except Exception as exc:
        messages.append(str(exc))

    return len(messages) == 0, tuple(messages)


def validate_generic_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert unbekannte Dokumente generisch."""
    messages: list[str] = []

    if not isinstance(document, Mapping):
        return False, ("Document must be a mapping.",)

    for field_name in GENERIC_REQUIRED_JSON_FIELDS:
        if field_name not in document:
            messages.append(f"Missing generic document field {field_name!r}.")

    return len(messages) == 0, tuple(messages)


def validate_json_compatible_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Prüft JSON-Kompatibilität rekursiv."""
    messages: list[str] = []

    try:
        normalize_json_value(document)
    except Exception as exc:
        messages.append(f"Document is not JSON compatible: {exc}")

    return len(messages) == 0, tuple(messages)


def build_validation_result_from_reports(reports: Iterable[SchemaValidationReport]) -> Any:
    """Baut ein ValidationResult aus SchemaValidationReports."""
    try:
        from ..models.validation_result import (
            ValidationIssueCode,
            ValidationScope,
            invalid_result,
            valid_result,
            validation_error,
        )

        issues = []

        for report in reports or ():
            normalized = report.normalized()

            for message in normalized.messages:
                issues.append(
                    validation_error(
                        message=message,
                        code=ValidationIssueCode.INVALID_VALUE.value,
                        scope=ValidationScope.JSON.value,
                        path=normalized.relative_path,
                        module_name=normalized.module_name,
                        details={
                            "schema_version": normalized.schema_version,
                            "validator_name": normalized.validator_name,
                            "status": normalized.status,
                        },
                    )
                )

        if not issues:
            return valid_result(
                metadata={
                    "source": "schema_validator",
                    "schema_version": SCHEMA_VALIDATOR_SCHEMA_VERSION,
                }
            )

        return invalid_result(
            issues,
            metadata={
                "source": "schema_validator",
                "schema_version": SCHEMA_VALIDATOR_SCHEMA_VERSION,
            },
        )
    except Exception:
        return {
            "schema_version": SCHEMA_VALIDATOR_SCHEMA_VERSION,
            "valid": all(report.normalized().valid for report in reports or ()),
            "issues": [
                {
                    "path": report.normalized().relative_path,
                    "messages": list(report.normalized().messages),
                }
                for report in reports or ()
                if report.normalized().messages
            ],
        }


def invalid_report_from_messages(
    target: SchemaValidationTarget,
    messages: Iterable[str],
    *,
    validator_name: str | None = None,
) -> SchemaValidationReport:
    """Erzeugt einen invalid report aus Messages."""
    normalized = target.normalized()

    return SchemaValidationReport(
        relative_path=normalized.relative_path,
        module_name=normalized.module_name,
        status=SchemaValidationStatus.INVALID.value,
        valid=False,
        messages=tuple(messages or ()),
        schema_version=normalized.schema_version,
        validator_name=validator_name,
        metadata=dict(normalized.metadata),
    ).normalized()


def get_validator_name(validator: Callable[..., Any] | None) -> str | None:
    """Liest einen stabilen Validator-Namen."""
    if validator is None:
        return None

    return getattr(validator, "__name__", None) or str(validator)


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

        raise SchemaValidatorError("DocumentBundle value is required.")
    except SchemaValidatorError:
        raise
    except Exception as exc:
        raise SchemaValidatorError(f"Invalid DocumentBundle: {exc}") from exc


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
        raise SchemaValidatorError(f"Invalid ValidationResult: {exc}") from exc


def normalize_options(
    options: SchemaValidationOptions | Mapping[str, Any] | None,
) -> SchemaValidationOptions:
    """Normalisiert SchemaValidationOptions."""
    if options is None:
        return SchemaValidationOptions().normalized()

    if isinstance(options, SchemaValidationOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return SchemaValidationOptions(
            mode=options.get("mode", SchemaValidationMode.STRICT.value),
            require_schema_version=bool(options.get("require_schema_version", True)),
            require_known_document_validator=bool(options.get("require_known_document_validator", False)),
            validate_json_compatibility=bool(options.get("validate_json_compatibility", True)),
            validate_package_path=bool(options.get("validate_package_path", True)),
            allow_unknown_documents=bool(options.get("allow_unknown_documents", True)),
            collect_all_errors=bool(options.get("collect_all_errors", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise SchemaValidatorError("options must be SchemaValidationOptions, mapping or None.")


def normalize_package_path(value: Any) -> str:
    """Normalisiert package-relative Pfade."""
    try:
        from ..domain.package_paths import normalize_package_path as normalize

        raw = clean_required_string(value, "relative_path").replace("\\", "/").strip()

        if raw in ROOT_DOCUMENT_PATHS:
            return raw

        return normalize(raw)
    except Exception:
        raw = clean_required_string(value, "relative_path").replace("\\", "/").strip().strip("/")

        if not raw or raw.startswith("../") or "/../" in raw:
            raise SchemaValidatorError(f"Invalid package path {value!r}.")

        return raw


def infer_module_from_path_safe(path: Any) -> str | None:
    """Leitet Modul aus einem package-relativen Pfad ab."""
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


def normalize_document_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert Dokument-Mapping JSON-kompatibel."""
    if not isinstance(value, Mapping):
        raise SchemaValidatorError("document must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
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

    raise SchemaValidatorError(f"Value of type {type(value).__name__!r} is not JSON compatible.")


@lru_cache(maxsize=128)
def parse_validation_status_value(value: Any) -> str:
    """Parst SchemaValidationStatus."""
    try:
        if isinstance(value, SchemaValidationStatus):
            return value.value

        raw = normalize_enum_key(value)
        return SchemaValidationStatus(raw).value
    except Exception as exc:
        raise SchemaValidatorError(f"Invalid schema validation status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_mode_value(value: Any) -> str:
    """Parst SchemaValidationMode."""
    try:
        if isinstance(value, SchemaValidationMode):
            return value.value

        raw = normalize_enum_key(value)
        return SchemaValidationMode(raw).value
    except Exception as exc:
        raise SchemaValidatorError(f"Invalid schema validation mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_scope_value(value: Any) -> str:
    """Parst SchemaValidationScope."""
    try:
        if isinstance(value, SchemaValidationScope):
            return value.value

        raw = normalize_enum_key(value)
        return SchemaValidationScope(raw).value
    except Exception as exc:
        raise SchemaValidatorError(f"Invalid schema validation scope {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise SchemaValidatorError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except SchemaValidatorError:
        raise
    except Exception as exc:
        raise SchemaValidatorError(f"Invalid enum value {value!r}.") from exc


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
        raise SchemaValidatorError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise SchemaValidatorError(f"{field_name} is required.")

        return cleaned
    except SchemaValidatorError:
        raise
    except Exception as exc:
        raise SchemaValidatorError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_schema_validator_caches() -> None:
    """Leert interne Parser- und Registry-Caches."""
    get_document_validator_registry.cache_clear()
    parse_validation_status_value.cache_clear()
    parse_validation_mode_value.cache_clear()
    parse_validation_scope_value.cache_clear()


__all__ = [
    "GENERIC_REQUIRED_JSON_FIELDS",
    "KNOWN_JSON_DOCUMENT_EXTENSIONS",
    "ROOT_DOCUMENT_PATHS",
    "SCHEMA_VALIDATOR_SCHEMA_VERSION",
    "SchemaValidationMode",
    "SchemaValidationOptions",
    "SchemaValidationReport",
    "SchemaValidationResult",
    "SchemaValidationScope",
    "SchemaValidationStatus",
    "SchemaValidationTarget",
    "SchemaValidatorError",
    "build_validation_result_from_reports",
    "clean_optional_string",
    "clean_required_string",
    "clear_schema_validator_caches",
    "get_document_validator",
    "get_document_validator_registry",
    "get_validator_name",
    "infer_module_from_path_safe",
    "invalid_report_from_messages",
    "normalize_document_bundle",
    "normalize_document_mapping",
    "normalize_enum_key",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_options",
    "normalize_optional_module_name",
    "normalize_package_path",
    "normalize_string_tuple",
    "normalize_validation_result",
    "parse_validation_mode_value",
    "parse_validation_scope_value",
    "parse_validation_status_value",
    "register_validator_safe",
    "validate_creation_plan_documents_schema",
    "validate_document_bundle_schema",
    "validate_document_schema",
    "validate_documents_schema",
    "validate_generic_document",
    "validate_json_compatible_document",
    "validate_package_path",
]