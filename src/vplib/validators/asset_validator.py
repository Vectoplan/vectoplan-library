# services/vectoplan-library/src/vplib/validators/asset_validator.py
"""
Asset validator for the VPLIB package engine.

Diese Datei validiert Asset-Referenzen für VPLIB-Packages.

Rolle dieser Datei:

    AssetReferenceCollection / DocumentBundle / documents mapping / CreationPlan
    -> AssetValidationResult
    -> ValidationResult

Diese Datei prüft:
- Asset-Rollen
- Asset-Typen
- erlaubte Dateiendungen
- Zielpfade im Package
- externe URLs
- package-interne Referenzen
- verbotene ausführbare Dateien
- GLB/glTF-Modell-Bounds
- Render-Bounds gegen Grid-Footprint
- Profile-Asset-Regeln, soweit verfügbar
- Duplikate von asset_id, source_ref und target_path

Diese Datei kopiert keine Dateien, liest keine Dateien vom Dateisystem und
analysiert keine GLB-Geometrie. Sie validiert nur deklarierte Metadaten.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any, Final, Iterable, Mapping
from urllib.parse import urlparse


ASSET_VALIDATOR_SCHEMA_VERSION: Final[str] = "vplib.asset_validator.v1"

MODEL_EXTENSIONS: Final[tuple[str, ...]] = (
    ".glb",
    ".gltf",
)

IMAGE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
)

TEXTURE_EXTENSIONS: Final[tuple[str, ...]] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".ktx2",
    ".basis",
)

DOCUMENT_EXTENSIONS: Final[tuple[str, ...]] = (
    ".md",
    ".txt",
    ".pdf",
    ".json",
)

DATA_EXTENSIONS: Final[tuple[str, ...]] = (
    ".json",
    ".csv",
    ".txt",
)

FORBIDDEN_ASSET_EXTENSIONS: Final[tuple[str, ...]] = (
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
    ".wasm",
)

PACKAGE_INTERNAL_ROOTS: Final[tuple[str, ...]] = (
    "render",
    "docs",
    "tests",
    "family",
    "variants",
    "editor",
    "physical",
    "material",
    "calculation",
    "analysis",
    "dynamic",
    "manufacturer",
)

ROLE_ALLOWED_EXTENSIONS: Final[dict[str, tuple[str, ...]]] = {
    "icon": (".svg", ".png", ".webp"),
    "preview": (".png", ".jpg", ".jpeg", ".webp"),
    "texture": TEXTURE_EXTENSIONS,
    "material_texture": TEXTURE_EXTENSIONS,
    "glb_model": (".glb",),
    "gltf_model": (".gltf",),
    "lod_model": MODEL_EXTENSIONS,
    "documentation": DOCUMENT_EXTENSIONS,
    "test_fixture": DATA_EXTENSIONS,
    "other": IMAGE_EXTENSIONS + TEXTURE_EXTENSIONS + MODEL_EXTENSIONS + DOCUMENT_EXTENSIONS + DATA_EXTENSIONS,
}

ROLE_EXPECTED_MODULE: Final[dict[str, str]] = {
    "icon": "render",
    "preview": "render",
    "texture": "render",
    "material_texture": "render",
    "glb_model": "render",
    "gltf_model": "render",
    "lod_model": "render",
    "documentation": "docs",
    "test_fixture": "tests",
    "other": "render",
}

DEFAULT_MAX_MODEL_SIZE_MB: Final[float] = 100.0
DEFAULT_MAX_TEXTURE_SIZE_MB: Final[float] = 35.0
DEFAULT_MAX_IMAGE_SIZE_MB: Final[float] = 10.0
DEFAULT_MAX_DOCUMENT_SIZE_MB: Final[float] = 25.0


class AssetValidatorError(ValueError):
    """Wird ausgelöst, wenn die Asset-Validierung selbst fehlschlägt."""


class AssetValidationStatus(str, Enum):
    """Status einer Asset-Validierung."""

    VALID = "valid"
    INVALID = "invalid"
    ERROR = "error"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetValidationMode(str, Enum):
    """Validierungsmodus."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetIssueSeverity(str, Enum):
    """Schweregrad eines Asset-Issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetIssueCode(str, Enum):
    """Asset-Issue-Codes."""

    UNKNOWN = "VPLIB_ASSET_UNKNOWN"
    MISSING_ASSET = "VPLIB_ASSET_MISSING_ASSET"
    INVALID_ROLE = "VPLIB_ASSET_INVALID_ROLE"
    INVALID_TYPE = "VPLIB_ASSET_INVALID_TYPE"
    INVALID_EXTENSION = "VPLIB_ASSET_INVALID_EXTENSION"
    FORBIDDEN_EXTENSION = "VPLIB_ASSET_FORBIDDEN_EXTENSION"
    INVALID_SOURCE = "VPLIB_ASSET_INVALID_SOURCE"
    INVALID_TARGET = "VPLIB_ASSET_INVALID_TARGET"
    INVALID_EXTERNAL_URI = "VPLIB_ASSET_INVALID_EXTERNAL_URI"
    INVALID_PACKAGE_PATH = "VPLIB_ASSET_INVALID_PACKAGE_PATH"
    INVALID_MODULE_TARGET = "VPLIB_ASSET_INVALID_MODULE_TARGET"
    DUPLICATE_ASSET_ID = "VPLIB_ASSET_DUPLICATE_ASSET_ID"
    DUPLICATE_TARGET_PATH = "VPLIB_ASSET_DUPLICATE_TARGET_PATH"
    MISSING_MODEL_BOUNDS = "VPLIB_ASSET_MISSING_MODEL_BOUNDS"
    MODEL_EXCEEDS_FOOTPRINT = "VPLIB_ASSET_MODEL_EXCEEDS_FOOTPRINT"
    ASSET_TOO_LARGE = "VPLIB_ASSET_TOO_LARGE"
    PROFILE_RULE_VIOLATION = "VPLIB_ASSET_PROFILE_RULE_VIOLATION"
    EXECUTABLE_CONTENT = "VPLIB_ASSET_EXECUTABLE_CONTENT"
    INTERNAL_ERROR = "VPLIB_ASSET_INTERNAL_ERROR"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetSourceKind(str, Enum):
    """Quelle einer Asset-Referenz."""

    LOCAL_FILE = "local_file"
    PACKAGE_INTERNAL = "package_internal"
    EXTERNAL_URI = "external_uri"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetReferenceKind(str, Enum):
    """Grobe Asset-Art."""

    IMAGE = "image"
    TEXTURE = "texture"
    MODEL = "model"
    DOCUMENT = "document"
    DATA = "data"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AssetValidationOptions:
    """Optionen für die Asset-Validierung."""

    mode: str = AssetValidationMode.STRICT.value
    allow_external_uri: bool = False
    allow_package_internal_refs: bool = True
    require_source_ref: bool = True
    require_target_path_for_local_assets: bool = True
    require_model_bounds: bool = True
    require_model_inside_footprint: bool = True
    validate_extensions: bool = True
    validate_target_paths: bool = True
    validate_role_target_module: bool = True
    validate_profile_rules: bool = True
    validate_duplicates: bool = True
    validate_declared_size: bool = True
    validate_declarative_safety: bool = True
    max_model_size_mb: float = DEFAULT_MAX_MODEL_SIZE_MB
    max_texture_size_mb: float = DEFAULT_MAX_TEXTURE_SIZE_MB
    max_image_size_mb: float = DEFAULT_MAX_IMAGE_SIZE_MB
    max_document_size_mb: float = DEFAULT_MAX_DOCUMENT_SIZE_MB
    collect_all_errors: bool = True
    strict: bool = True

    def normalized(self) -> "AssetValidationOptions":
        mode = parse_validation_mode_value(self.mode)

        return AssetValidationOptions(
            mode=mode,
            allow_external_uri=bool(self.allow_external_uri),
            allow_package_internal_refs=bool(self.allow_package_internal_refs),
            require_source_ref=bool(self.require_source_ref),
            require_target_path_for_local_assets=bool(self.require_target_path_for_local_assets),
            require_model_bounds=bool(self.require_model_bounds),
            require_model_inside_footprint=bool(self.require_model_inside_footprint),
            validate_extensions=bool(self.validate_extensions),
            validate_target_paths=bool(self.validate_target_paths),
            validate_role_target_module=bool(self.validate_role_target_module),
            validate_profile_rules=bool(self.validate_profile_rules),
            validate_duplicates=bool(self.validate_duplicates),
            validate_declared_size=bool(self.validate_declared_size),
            validate_declarative_safety=bool(self.validate_declarative_safety),
            max_model_size_mb=normalize_positive_float(self.max_model_size_mb, "max_model_size_mb"),
            max_texture_size_mb=normalize_positive_float(self.max_texture_size_mb, "max_texture_size_mb"),
            max_image_size_mb=normalize_positive_float(self.max_image_size_mb, "max_image_size_mb"),
            max_document_size_mb=normalize_positive_float(self.max_document_size_mb, "max_document_size_mb"),
            collect_all_errors=bool(self.collect_all_errors),
            strict=bool(self.strict),
        )

    @property
    def is_strict(self) -> bool:
        return self.normalized().mode == AssetValidationMode.STRICT.value

    @property
    def is_permissive(self) -> bool:
        return self.normalized().mode == AssetValidationMode.PERMISSIVE.value

    def max_size_mb_for_kind(self, asset_kind: str) -> float | None:
        kind = parse_asset_reference_kind_value(asset_kind)

        if kind == AssetReferenceKind.MODEL.value:
            return self.normalized().max_model_size_mb

        if kind == AssetReferenceKind.TEXTURE.value:
            return self.normalized().max_texture_size_mb

        if kind == AssetReferenceKind.IMAGE.value:
            return self.normalized().max_image_size_mb

        if kind == AssetReferenceKind.DOCUMENT.value:
            return self.normalized().max_document_size_mb

        return None

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "mode": normalized.mode,
            "allow_external_uri": normalized.allow_external_uri,
            "allow_package_internal_refs": normalized.allow_package_internal_refs,
            "require_source_ref": normalized.require_source_ref,
            "require_target_path_for_local_assets": normalized.require_target_path_for_local_assets,
            "require_model_bounds": normalized.require_model_bounds,
            "require_model_inside_footprint": normalized.require_model_inside_footprint,
            "validate_extensions": normalized.validate_extensions,
            "validate_target_paths": normalized.validate_target_paths,
            "validate_role_target_module": normalized.validate_role_target_module,
            "validate_profile_rules": normalized.validate_profile_rules,
            "validate_duplicates": normalized.validate_duplicates,
            "validate_declared_size": normalized.validate_declared_size,
            "validate_declarative_safety": normalized.validate_declarative_safety,
            "max_model_size_mb": normalized.max_model_size_mb,
            "max_texture_size_mb": normalized.max_texture_size_mb,
            "max_image_size_mb": normalized.max_image_size_mb,
            "max_document_size_mb": normalized.max_document_size_mb,
            "collect_all_errors": normalized.collect_all_errors,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class AssetBounds:
    """Deklarierte Asset-Bounds in Metern."""

    width_m: float
    height_m: float
    depth_m: float

    def normalized(self) -> "AssetBounds":
        return AssetBounds(
            width_m=normalize_positive_float(self.width_m, "width_m"),
            height_m=normalize_positive_float(self.height_m, "height_m"),
            depth_m=normalize_positive_float(self.depth_m, "depth_m"),
        )

    @property
    def size_m(self) -> tuple[float, float, float]:
        normalized = self.normalized()
        return (normalized.width_m, normalized.height_m, normalized.depth_m)

    def fits_inside(self, footprint_size_m: tuple[float, float, float]) -> bool:
        normalized = self.normalized()
        return (
            normalized.width_m <= footprint_size_m[0]
            and normalized.height_m <= footprint_size_m[1]
            and normalized.depth_m <= footprint_size_m[2]
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "width_m": normalized.width_m,
            "height_m": normalized.height_m,
            "depth_m": normalized.depth_m,
            "size_m": {
                "x": normalized.width_m,
                "y": normalized.height_m,
                "z": normalized.depth_m,
            },
        }


@dataclass(frozen=True, slots=True)
class AssetValidationTarget:
    """Eine normalisierte Asset-Referenz für die Validierung."""

    asset_id: str | None
    role: str
    asset_kind: str
    source_ref: str | None = None
    source_kind: str = AssetSourceKind.UNKNOWN.value
    target_path: str | None = None
    module_name: str | None = None
    extension: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    bounds_m: AssetBounds | None = None
    required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AssetValidationTarget":
        role = normalize_asset_role_value(self.role)
        source_ref = clean_optional_string(self.source_ref)
        source_kind = parse_source_kind_value(self.source_kind)
        target_path = normalize_optional_package_path(self.target_path)
        module_name = normalize_optional_module_name(self.module_name) or infer_target_module_for_role(role)
        extension = normalize_optional_extension(self.extension) or infer_extension(source_ref or target_path)
        asset_kind = parse_asset_reference_kind_value(self.asset_kind or infer_asset_kind(role=role, extension=extension))
        mime_type = clean_optional_string(self.mime_type) or infer_mime_type(extension)
        size_bytes = normalize_optional_non_negative_int(self.size_bytes, "size_bytes")
        bounds_m = self.bounds_m.normalized() if self.bounds_m is not None else None
        asset_id = normalize_optional_asset_id(self.asset_id) or infer_asset_id(source_ref or target_path, role=role)
        metadata = normalize_metadata(self.metadata)

        if source_ref and source_kind == AssetSourceKind.UNKNOWN.value:
            source_kind = infer_source_kind(source_ref)

        return AssetValidationTarget(
            asset_id=asset_id,
            role=role,
            asset_kind=asset_kind,
            source_ref=source_ref,
            source_kind=source_kind,
            target_path=target_path,
            module_name=module_name,
            extension=extension,
            mime_type=mime_type,
            size_bytes=size_bytes,
            bounds_m=bounds_m,
            required=bool(self.required),
            metadata=metadata,
        )

    @property
    def is_model(self) -> bool:
        return self.normalized().asset_kind == AssetReferenceKind.MODEL.value

    @property
    def is_external(self) -> bool:
        return self.normalized().source_kind == AssetSourceKind.EXTERNAL_URI.value

    @property
    def is_package_internal(self) -> bool:
        return self.normalized().source_kind == AssetSourceKind.PACKAGE_INTERNAL.value

    @property
    def size_mb(self) -> float | None:
        normalized = self.normalized()

        if normalized.size_bytes is None:
            return None

        return normalized.size_bytes / (1024 * 1024)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "asset_id": normalized.asset_id,
            "role": normalized.role,
            "asset_kind": normalized.asset_kind,
            "source_ref": normalized.source_ref,
            "source_kind": normalized.source_kind,
            "target_path": normalized.target_path,
            "module_name": normalized.module_name,
            "extension": normalized.extension,
            "mime_type": normalized.mime_type,
            "size_bytes": normalized.size_bytes,
            "size_mb": normalized.size_mb,
            "bounds_m": normalized.bounds_m.to_dict() if normalized.bounds_m else None,
            "required": normalized.required,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class AssetIssue:
    """Ein einzelnes Asset-Issue."""

    code: str
    message: str
    severity: str = AssetIssueSeverity.ERROR.value
    asset_id: str | None = None
    role: str | None = None
    path: str | None = None
    field_path: str | None = None
    module_name: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AssetIssue":
        code = parse_issue_code_value(self.code)
        message = clean_required_string(self.message, "message")
        severity = parse_issue_severity_value(self.severity)
        asset_id = normalize_optional_asset_id(self.asset_id)
        role = normalize_optional_asset_role_value(self.role)
        path = clean_optional_string(self.path)
        field_path = clean_optional_string(self.field_path)
        module_name = normalize_optional_module_name(self.module_name)
        details = normalize_metadata(self.details)

        return AssetIssue(
            code=code,
            message=message,
            severity=severity,
            asset_id=asset_id,
            role=role,
            path=path,
            field_path=field_path,
            module_name=module_name,
            details=details,
        )

    @property
    def blocks_success(self) -> bool:
        return self.normalized().severity in {
            AssetIssueSeverity.ERROR.value,
            AssetIssueSeverity.FATAL.value,
        }

    def fingerprint(self) -> str:
        normalized = self.normalized()

        return "|".join(
            (
                normalized.code,
                normalized.severity,
                normalized.asset_id or "",
                normalized.role or "",
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
            "asset_id": normalized.asset_id,
            "role": normalized.role,
            "path": normalized.path,
            "field_path": normalized.field_path,
            "module_name": normalized.module_name,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class AssetValidationResult:
    """Ergebnis der Asset-Validierung."""

    issues: tuple[AssetIssue, ...] = field(default_factory=tuple)
    targets: tuple[AssetValidationTarget, ...] = field(default_factory=tuple)
    validation_result: Any | None = None
    status: str = AssetValidationStatus.VALID.value
    schema_version: str = ASSET_VALIDATOR_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AssetValidationResult":
        issues = sort_issues(dedupe_issues(tuple(issue.normalized() for issue in self.issues or ())))
        targets = sort_targets(dedupe_targets(tuple(target.normalized() for target in self.targets or ())))
        validation_result = normalize_validation_result(self.validation_result)
        status = parse_validation_status_value(self.status)
        metadata = normalize_metadata(self.metadata)

        valid = not any(issue.blocks_success for issue in issues)
        if not valid:
            status = AssetValidationStatus.INVALID.value

        if validation_result is None:
            validation_result = build_validation_result_from_asset_issues(issues)

        return AssetValidationResult(
            issues=issues,
            targets=targets,
            validation_result=validation_result,
            status=status,
            schema_version=self.schema_version or ASSET_VALIDATOR_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def valid(self) -> bool:
        return not any(issue.blocks_success for issue in self.normalized().issues)

    @property
    def issue_count(self) -> int:
        return len(self.normalized().issues)

    @property
    def target_count(self) -> int:
        return len(self.normalized().targets)

    @property
    def warnings(self) -> tuple[AssetIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == AssetIssueSeverity.WARNING.value
        )

    @property
    def errors(self) -> tuple[AssetIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == AssetIssueSeverity.ERROR.value
        )

    @property
    def fatal_errors(self) -> tuple[AssetIssue, ...]:
        return tuple(
            issue
            for issue in self.normalized().issues
            if issue.severity == AssetIssueSeverity.FATAL.value
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
            "target_count": normalized.target_count,
            "issue_count": normalized.issue_count,
            "warning_count": len(normalized.warnings),
            "error_count": len(normalized.errors),
            "fatal_count": len(normalized.fatal_errors),
            "targets": [target.to_dict() for target in normalized.targets],
            "issues": [issue.to_dict() for issue in normalized.issues],
            "validation_result": validation_payload,
            "metadata": dict(normalized.metadata),
        }


def validate_asset_targets(
    targets: Iterable[AssetValidationTarget],
    *,
    footprint_size_m: tuple[float, float, float] | None = None,
    profile: Any | None = None,
    options: AssetValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetValidationResult:
    """Validiert bereits normalisierte AssetValidationTargets."""
    try:
        normalized_options = normalize_options(options)
        normalized_targets = tuple(target.normalized() for target in targets or ())
        issues: list[AssetIssue] = []

        for target in normalized_targets:
            issues.extend(validate_single_asset_target(target, options=normalized_options, footprint_size_m=footprint_size_m))

        if normalized_options.validate_duplicates:
            issues.extend(validate_asset_duplicates(normalized_targets))

        if normalized_options.validate_profile_rules and profile is not None:
            issues.extend(validate_profile_asset_rules(normalized_targets, profile=profile, options=normalized_options))

        return AssetValidationResult(
            issues=tuple(issues),
            targets=normalized_targets,
            status=AssetValidationStatus.VALID.value,
            metadata={
                "source": "asset_targets",
                **dict(metadata or {}),
            },
        ).normalized()
    except AssetValidatorError:
        raise
    except Exception as exc:
        return AssetValidationResult(
            issues=(
                asset_issue(
                    code=AssetIssueCode.INTERNAL_ERROR.value,
                    severity=AssetIssueSeverity.FATAL.value,
                    message=f"Asset validation failed: {exc}",
                    module_name="system",
                ),
            ),
            targets=tuple(),
            status=AssetValidationStatus.ERROR.value,
            metadata=dict(metadata or {}),
        ).normalized()


def validate_asset_collection(
    asset_collection: Any,
    *,
    footprint_size_m: tuple[float, float, float] | None = None,
    profile: Any | None = None,
    options: AssetValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetValidationResult:
    """Validiert eine AssetReferenceCollection oder Iterable von AssetReferences."""
    try:
        collection = normalize_asset_collection(asset_collection)
        targets = tuple(asset_target_from_asset_reference(asset) for asset in collection.assets)

        return validate_asset_targets(
            targets,
            footprint_size_m=footprint_size_m,
            profile=profile,
            options=options,
            metadata={
                "source": "asset_collection",
                **dict(metadata or {}),
            },
        ).normalized()
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Could not validate asset collection: {exc}") from exc


def validate_documents_assets(
    documents: Mapping[str, Mapping[str, Any]],
    *,
    profile: Any | None = None,
    options: AssetValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetValidationResult:
    """Extrahiert und validiert Assets aus einem path -> document Mapping."""
    try:
        normalized_documents = normalize_documents_mapping(documents)
        footprint_size_m = extract_footprint_size_m(normalized_documents)
        targets = extract_asset_targets_from_documents(normalized_documents)

        return validate_asset_targets(
            targets,
            footprint_size_m=footprint_size_m,
            profile=profile,
            options=options,
            metadata={
                "source": "documents",
                "document_count": len(normalized_documents),
                **dict(metadata or {}),
            },
        ).normalized()
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Could not validate document assets: {exc}") from exc


def validate_document_bundle_assets(
    bundle: Any,
    *,
    profile: Any | None = None,
    options: AssetValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetValidationResult:
    """Validiert Assets aus einem DocumentBundle-ähnlichen Objekt."""
    try:
        normalized_bundle = normalize_document_bundle(bundle)
        documents = (
            normalized_bundle.to_documents()
            if hasattr(normalized_bundle, "to_documents")
            else normalized_bundle.documents
        )

        return validate_documents_assets(
            documents,
            profile=profile,
            options=options,
            metadata={
                "source": "document_bundle",
                "bundle_schema_version": getattr(normalized_bundle, "schema_version", None),
                **dict(metadata or {}),
            },
        ).normalized()
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Could not validate document bundle assets: {exc}") from exc


def validate_creation_plan_assets(
    creation_plan: Any,
    *,
    options: AssetValidationOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetValidationResult:
    """Validiert Assets eines CreationPlan über AssetPlanningResult und DocumentBundle."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        profile = getattr(normalized_plan, "profile", None)
        request = getattr(normalized_plan, "request", None)
        context = getattr(normalized_plan, "context", None)

        targets: list[AssetValidationTarget] = []
        footprint_size_m = None

        try:
            from ..planning.asset_planner import plan_assets_for_request

            if request is not None and context is not None:
                asset_plan = plan_assets_for_request(
                    request=request,
                    context=context,
                    profile=profile,
                )
                targets.extend(asset_target_from_asset_reference(asset) for asset in asset_plan.asset_collection.assets)
        except Exception:
            pass

        try:
            from ..defaults.document_bundle import build_document_bundle_from_creation_plan

            bundle = build_document_bundle_from_creation_plan(normalized_plan)
            documents = bundle.to_documents()
            footprint_size_m = extract_footprint_size_m(documents)
            targets.extend(extract_asset_targets_from_documents(documents))
        except Exception:
            pass

        return validate_asset_targets(
            targets,
            footprint_size_m=footprint_size_m,
            profile=profile,
            options=options,
            metadata={
                "source": "creation_plan",
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        raise AssetValidatorError(f"Could not validate creation plan assets: {exc}") from exc


def validate_single_asset_target(
    target: AssetValidationTarget,
    *,
    options: AssetValidationOptions,
    footprint_size_m: tuple[float, float, float] | None,
) -> tuple[AssetIssue, ...]:
    """Validiert ein einzelnes AssetTarget."""
    normalized = target.normalized()
    normalized_options = options.normalized()
    issues: list[AssetIssue] = []

    if normalized_options.require_source_ref and not normalized.source_ref:
        issues.append(
            issue_for_target(
                normalized,
                code=AssetIssueCode.INVALID_SOURCE.value,
                message="Asset source_ref is required.",
            )
        )

    if normalized.source_ref:
        if normalized.source_kind == AssetSourceKind.EXTERNAL_URI.value and not normalized_options.allow_external_uri:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.INVALID_EXTERNAL_URI.value,
                    message="External asset URI is not allowed.",
                    severity=AssetIssueSeverity.ERROR.value,
                    details={"source_ref": normalized.source_ref},
                )
            )

        if normalized.source_kind == AssetSourceKind.PACKAGE_INTERNAL.value and not normalized_options.allow_package_internal_refs:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.INVALID_SOURCE.value,
                    message="Package-internal asset references are not allowed by options.",
                    details={"source_ref": normalized.source_ref},
                )
            )

    if normalized_options.require_target_path_for_local_assets:
        if normalized.source_kind == AssetSourceKind.LOCAL_FILE.value and not normalized.target_path:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.INVALID_TARGET.value,
                    message="Local file assets require target_path.",
                )
            )

    if normalized_options.validate_target_paths and normalized.target_path:
        target_valid, target_messages = validate_package_asset_path(normalized.target_path)
        for message in target_messages:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.INVALID_PACKAGE_PATH.value,
                    message=message,
                    path=normalized.target_path,
                )
            )

    if normalized_options.validate_role_target_module and normalized.target_path:
        expected_module = infer_target_module_for_role(normalized.role)
        actual_module = infer_module_from_path_safe(normalized.target_path)

        if expected_module and actual_module and expected_module != actual_module:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.INVALID_MODULE_TARGET.value,
                    severity=AssetIssueSeverity.ERROR if normalized_options.is_strict else AssetIssueSeverity.WARNING,
                    message=f"Asset role {normalized.role!r} should target module {expected_module!r}, not {actual_module!r}.",
                    path=normalized.target_path,
                    details={
                        "expected_module": expected_module,
                        "actual_module": actual_module,
                    },
                )
            )

    if normalized_options.validate_extensions:
        issues.extend(validate_asset_extension(normalized, options=normalized_options))

    if normalized_options.validate_declared_size:
        issues.extend(validate_asset_declared_size(normalized, options=normalized_options))

    if normalized_options.require_model_bounds and normalized.is_model and normalized.bounds_m is None:
        issues.append(
            issue_for_target(
                normalized,
                code=AssetIssueCode.MISSING_MODEL_BOUNDS.value,
                message="Model assets require declared bounds_m.",
                severity=AssetIssueSeverity.ERROR if normalized_options.is_strict else AssetIssueSeverity.WARNING,
            )
        )

    if normalized_options.require_model_inside_footprint and normalized.is_model and normalized.bounds_m and footprint_size_m:
        if not normalized.bounds_m.fits_inside(footprint_size_m):
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.MODEL_EXCEEDS_FOOTPRINT.value,
                    message="Model asset bounds exceed the editor grid footprint.",
                    details={
                        "bounds_m": normalized.bounds_m.to_dict(),
                        "footprint_size_m": {
                            "x": footprint_size_m[0],
                            "y": footprint_size_m[1],
                            "z": footprint_size_m[2],
                        },
                    },
                )
            )

    if normalized_options.validate_declarative_safety:
        issues.extend(validate_asset_declarative_safety(normalized))

    return tuple(issues)


def validate_asset_extension(
    target: AssetValidationTarget,
    *,
    options: AssetValidationOptions,
) -> tuple[AssetIssue, ...]:
    """Validiert Dateiendungen."""
    normalized = target.normalized()
    issues: list[AssetIssue] = []

    extension = normalized.extension
    if not extension:
        if normalized.source_ref or normalized.target_path:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.INVALID_EXTENSION.value,
                    severity=AssetIssueSeverity.WARNING if options.is_permissive else AssetIssueSeverity.ERROR,
                    message="Asset extension could not be inferred.",
                )
            )
        return tuple(issues)

    if extension in FORBIDDEN_ASSET_EXTENSIONS:
        issues.append(
            issue_for_target(
                normalized,
                code=AssetIssueCode.FORBIDDEN_EXTENSION.value,
                severity=AssetIssueSeverity.FATAL.value,
                message=f"Asset extension {extension!r} is forbidden.",
            )
        )
        return tuple(issues)

    allowed = ROLE_ALLOWED_EXTENSIONS.get(normalized.role)
    if allowed and extension not in allowed:
        issues.append(
            issue_for_target(
                normalized,
                code=AssetIssueCode.INVALID_EXTENSION.value,
                severity=AssetIssueSeverity.ERROR if options.is_strict else AssetIssueSeverity.WARNING,
                message=f"Asset role {normalized.role!r} does not allow extension {extension!r}.",
                details={
                    "allowed_extensions": list(allowed),
                    "extension": extension,
                },
            )
        )

    return tuple(issues)


def validate_asset_declared_size(
    target: AssetValidationTarget,
    *,
    options: AssetValidationOptions,
) -> tuple[AssetIssue, ...]:
    """Validiert deklarierte Assetgröße, sofern vorhanden."""
    normalized = target.normalized()

    if normalized.size_mb is None:
        return tuple()

    max_size_mb = options.max_size_mb_for_kind(normalized.asset_kind)
    if max_size_mb is None:
        return tuple()

    if normalized.size_mb > max_size_mb:
        return (
            issue_for_target(
                normalized,
                code=AssetIssueCode.ASSET_TOO_LARGE.value,
                message=f"Asset size {normalized.size_mb:.2f} MB exceeds allowed {max_size_mb:.2f} MB.",
                details={
                    "size_mb": normalized.size_mb,
                    "max_size_mb": max_size_mb,
                },
            ),
        )

    return tuple()


def validate_asset_declarative_safety(target: AssetValidationTarget) -> tuple[AssetIssue, ...]:
    """Prüft Asset-Referenzen auf ausführbare Inhalte."""
    normalized = target.normalized()
    issues: list[AssetIssue] = []

    refs = tuple(ref for ref in (normalized.source_ref, normalized.target_path) if ref)

    for ref in refs:
        extension = infer_extension(ref)
        if extension in FORBIDDEN_ASSET_EXTENSIONS:
            issues.append(
                issue_for_target(
                    normalized,
                    code=AssetIssueCode.EXECUTABLE_CONTENT.value,
                    severity=AssetIssueSeverity.FATAL.value,
                    message=f"Executable asset reference is forbidden: {ref!r}.",
                    path=ref,
                )
            )

    return tuple(issues)


def validate_asset_duplicates(targets: Iterable[AssetValidationTarget]) -> tuple[AssetIssue, ...]:
    """Prüft doppelte asset_id und target_path."""
    normalized_targets = tuple(target.normalized() for target in targets or ())
    issues: list[AssetIssue] = []

    by_asset_id: dict[str, list[AssetValidationTarget]] = {}
    by_target_path: dict[str, list[AssetValidationTarget]] = {}

    for target in normalized_targets:
        if target.asset_id:
            by_asset_id.setdefault(target.asset_id, []).append(target)

        if target.target_path:
            by_target_path.setdefault(target.target_path, []).append(target)

    for asset_id, grouped in by_asset_id.items():
        if len(grouped) <= 1:
            continue

        issues.append(
            asset_issue(
                code=AssetIssueCode.DUPLICATE_ASSET_ID.value,
                message=f"Duplicate asset_id {asset_id!r}.",
                severity=AssetIssueSeverity.ERROR.value,
                asset_id=asset_id,
                role=grouped[0].role,
                path=grouped[0].target_path,
                module_name=grouped[0].module_name,
                details={
                    "count": len(grouped),
                    "target_paths": [item.target_path for item in grouped],
                },
            )
        )

    for target_path, grouped in by_target_path.items():
        if len(grouped) <= 1:
            continue

        issues.append(
            asset_issue(
                code=AssetIssueCode.DUPLICATE_TARGET_PATH.value,
                message=f"Duplicate asset target_path {target_path!r}.",
                severity=AssetIssueSeverity.ERROR.value,
                asset_id=grouped[0].asset_id,
                role=grouped[0].role,
                path=target_path,
                module_name=grouped[0].module_name,
                details={
                    "count": len(grouped),
                    "asset_ids": [item.asset_id for item in grouped],
                },
            )
        )

    return tuple(issues)


def validate_profile_asset_rules(
    targets: Iterable[AssetValidationTarget],
    *,
    profile: Any,
    options: AssetValidationOptions,
) -> tuple[AssetIssue, ...]:
    """Validiert Assets gegen ObjectKindProfile.asset_rules."""
    issues: list[AssetIssue] = []

    try:
        normalized_profile = profile.normalized() if hasattr(profile, "normalized") else profile
        normalized_targets = tuple(target.normalized() for target in targets or ())
        roles_present = {target.role for target in normalized_targets}

        for rule in getattr(normalized_profile, "asset_rules", ()) or ():
            normalized_rule = rule.normalized() if hasattr(rule, "normalized") else rule
            role = normalize_asset_role_value(getattr(normalized_rule, "role", None))
            policy = clean_optional_string(getattr(normalized_rule, "policy", None)) or "optional"
            allowed_extensions = tuple(getattr(normalized_rule, "allowed_extensions", ()) or ())
            max_size_mb = getattr(normalized_rule, "max_size_mb", None)
            requires_bounds = bool(getattr(normalized_rule, "requires_bounds", False))
            must_fit_grid_footprint = bool(getattr(normalized_rule, "must_fit_grid_footprint", False))

            if policy == "required" and role not in roles_present:
                issues.append(
                    asset_issue(
                        code=AssetIssueCode.PROFILE_RULE_VIOLATION.value,
                        message=f"Profile requires asset role {role!r}.",
                        severity=AssetIssueSeverity.ERROR.value,
                        role=role,
                        module_name=getattr(normalized_rule, "module_name", None),
                        details={
                            "profile_key": getattr(normalized_profile, "profile_key", None),
                            "policy": policy,
                        },
                    )
                )

            matching_targets = [target for target in normalized_targets if target.role == role]

            for target in matching_targets:
                if policy == "not_allowed":
                    issues.append(
                        issue_for_target(
                            target,
                            code=AssetIssueCode.PROFILE_RULE_VIOLATION.value,
                            message=f"Profile does not allow asset role {role!r}.",
                            details={
                                "profile_key": getattr(normalized_profile, "profile_key", None),
                                "policy": policy,
                            },
                        )
                    )

                if allowed_extensions and target.extension and target.extension not in allowed_extensions:
                    issues.append(
                        issue_for_target(
                            target,
                            code=AssetIssueCode.PROFILE_RULE_VIOLATION.value,
                            message=f"Profile asset rule for {role!r} does not allow extension {target.extension!r}.",
                            details={
                                "allowed_extensions": list(allowed_extensions),
                                "extension": target.extension,
                            },
                        )
                    )

                if max_size_mb is not None and target.size_mb is not None and target.size_mb > float(max_size_mb):
                    issues.append(
                        issue_for_target(
                            target,
                            code=AssetIssueCode.ASSET_TOO_LARGE.value,
                            message=f"Asset exceeds profile max_size_mb {float(max_size_mb):.2f}.",
                            details={
                                "size_mb": target.size_mb,
                                "max_size_mb": float(max_size_mb),
                            },
                        )
                    )

                if requires_bounds and target.bounds_m is None:
                    issues.append(
                        issue_for_target(
                            target,
                            code=AssetIssueCode.MISSING_MODEL_BOUNDS.value,
                            message=f"Profile requires bounds for asset role {role!r}.",
                        )
                    )

                if must_fit_grid_footprint and target.is_model and not options.require_model_inside_footprint:
                    issues.append(
                        issue_for_target(
                            target,
                            code=AssetIssueCode.PROFILE_RULE_VIOLATION.value,
                            severity=AssetIssueSeverity.WARNING.value,
                            message=f"Profile expects asset role {role!r} to fit grid footprint, but footprint validation is disabled.",
                        )
                    )

    except Exception as exc:
        issues.append(
            asset_issue(
                code=AssetIssueCode.INTERNAL_ERROR.value,
                severity=AssetIssueSeverity.ERROR.value,
                message=f"Could not validate profile asset rules: {exc}",
                module_name="system",
            )
        )

    return tuple(issues)


def extract_asset_targets_from_documents(
    documents: Mapping[str, Mapping[str, Any]],
) -> tuple[AssetValidationTarget, ...]:
    """Extrahiert AssetValidationTargets aus bekannten VPLIB-Dokumenten."""
    targets: list[AssetValidationTarget] = []

    render_variants = documents.get("render/render_variants.json", {})
    if isinstance(render_variants, Mapping):
        for index, variant in enumerate(render_variants.get("render_variants", ()) or ()):
            if not isinstance(variant, Mapping):
                continue

            render_variant_id = clean_optional_string(variant.get("render_variant_id")) or f"render_variant_{index}"
            bounds = bounds_from_mapping(variant.get("bounds_m"))

            for role, key in (
                ("icon", "icon_ref"),
                ("preview", "preview_ref"),
                ("texture", "texture_ref"),
                ("glb_model", "glb_ref"),
                ("glb_model", "model_ref"),
            ):
                ref = clean_optional_string(variant.get(key))
                if not ref:
                    continue

                targets.append(
                    AssetValidationTarget(
                        asset_id=f"{render_variant_id}_{role}",
                        role=role,
                        asset_kind=infer_asset_kind(role=role, extension=infer_extension(ref)),
                        source_ref=ref,
                        source_kind=infer_source_kind(ref),
                        target_path=ref if is_package_internal_path(ref) else None,
                        module_name="render",
                        extension=infer_extension(ref),
                        bounds_m=bounds if role == "glb_model" else None,
                        required=False,
                        metadata={
                            "source_document": "render/render_variants.json",
                            "render_variant_id": render_variant_id,
                            "field": key,
                        },
                    )
                )

            asset_refs = variant.get("asset_refs", ()) or ()
            if isinstance(asset_refs, list):
                for asset_index, asset_ref in enumerate(asset_refs):
                    if not isinstance(asset_ref, Mapping):
                        continue
                    targets.append(asset_target_from_mapping_asset_ref(
                        asset_ref,
                        source_document="render/render_variants.json",
                        field_path=f"render_variants[{index}].asset_refs[{asset_index}]",
                        default_module="render",
                    ))

    render_materials = documents.get("render/materials.json", {})
    if isinstance(render_materials, Mapping):
        for index, material in enumerate(render_materials.get("materials", ()) or ()):
            if not isinstance(material, Mapping):
                continue
            material_id = clean_optional_string(material.get("material_id")) or f"material_{index}"

            for role, key in (
                ("material_texture", "base_color_texture_ref"),
                ("material_texture", "normal_texture_ref"),
                ("material_texture", "roughness_texture_ref"),
                ("material_texture", "metallic_texture_ref"),
            ):
                ref = clean_optional_string(material.get(key))
                if not ref:
                    continue

                targets.append(
                    AssetValidationTarget(
                        asset_id=f"{material_id}_{key}",
                        role=role,
                        asset_kind=AssetReferenceKind.TEXTURE.value,
                        source_ref=ref,
                        source_kind=infer_source_kind(ref),
                        target_path=ref if is_package_internal_path(ref) else None,
                        module_name="render",
                        extension=infer_extension(ref),
                        metadata={
                            "source_document": "render/materials.json",
                            "material_id": material_id,
                            "field": key,
                        },
                    )
                )

    material_surfaces = documents.get("material/surfaces.json", {})
    if isinstance(material_surfaces, Mapping):
        for index, surface in enumerate(material_surfaces.get("surfaces", ()) or ()):
            if not isinstance(surface, Mapping):
                continue
            ref = clean_optional_string(surface.get("texture_ref"))
            if not ref:
                continue
            surface_id = clean_optional_string(surface.get("surface_id")) or f"surface_{index}"
            targets.append(
                AssetValidationTarget(
                    asset_id=f"{surface_id}_texture",
                    role="material_texture",
                    asset_kind=AssetReferenceKind.TEXTURE.value,
                    source_ref=ref,
                    source_kind=infer_source_kind(ref),
                    target_path=ref if is_package_internal_path(ref) else None,
                    module_name="material",
                    extension=infer_extension(ref),
                    metadata={
                        "source_document": "material/surfaces.json",
                        "surface_id": surface_id,
                        "field": "texture_ref",
                    },
                )
            )

    editor_inventory = documents.get("editor/inventory.json", {})
    if isinstance(editor_inventory, Mapping):
        for role, key in (("icon", "icon_ref"), ("preview", "preview_ref")):
            ref = clean_optional_string(editor_inventory.get(key))
            if not ref:
                continue
            targets.append(
                AssetValidationTarget(
                    asset_id=f"inventory_{role}",
                    role=role,
                    asset_kind=AssetReferenceKind.IMAGE.value,
                    source_ref=ref,
                    source_kind=infer_source_kind(ref),
                    target_path=ref if is_package_internal_path(ref) else None,
                    module_name="editor",
                    extension=infer_extension(ref),
                    metadata={
                        "source_document": "editor/inventory.json",
                        "field": key,
                    },
                )
            )

    manufacturer_assets = documents.get("manufacturer/assets.json", {})
    if isinstance(manufacturer_assets, Mapping):
        for index, item in enumerate(manufacturer_assets.get("assets", ()) or ()):
            if not isinstance(item, Mapping):
                continue
            targets.append(asset_target_from_mapping_asset_ref(
                item,
                source_document="manufacturer/assets.json",
                field_path=f"assets[{index}]",
                default_module="manufacturer",
            ))

    manufacturer_branding = documents.get("manufacturer/branding.json", {})
    if isinstance(manufacturer_branding, Mapping):
        logo_ref = clean_optional_string(manufacturer_branding.get("logo_ref"))
        if logo_ref:
            targets.append(
                AssetValidationTarget(
                    asset_id="manufacturer_logo",
                    role="icon",
                    asset_kind=AssetReferenceKind.IMAGE.value,
                    source_ref=logo_ref,
                    source_kind=infer_source_kind(logo_ref),
                    target_path=logo_ref if is_package_internal_path(logo_ref) else None,
                    module_name="manufacturer",
                    extension=infer_extension(logo_ref),
                    metadata={
                        "source_document": "manufacturer/branding.json",
                        "field": "logo_ref",
                    },
                )
            )

    return tuple(targets)


def asset_target_from_mapping_asset_ref(
    data: Mapping[str, Any],
    *,
    source_document: str,
    field_path: str,
    default_module: str,
) -> AssetValidationTarget:
    """Baut AssetValidationTarget aus einem AssetRef-ähnlichen Mapping."""
    role = data.get("role") or data.get("asset_role") or "other"
    ref = data.get("ref") or data.get("source_ref") or data.get("path")
    target_path = data.get("target_path") or data.get("package_path")
    extension = infer_extension(ref or target_path)
    role_value = normalize_asset_role_value(role)

    return AssetValidationTarget(
        asset_id=data.get("asset_id") or infer_asset_id(ref or target_path, role=role_value),
        role=role_value,
        asset_kind=data.get("asset_kind") or data.get("asset_type") or infer_asset_kind(role=role_value, extension=extension),
        source_ref=ref,
        source_kind=infer_source_kind(ref) if ref else AssetSourceKind.UNKNOWN.value,
        target_path=target_path,
        module_name=data.get("module_name") or default_module,
        extension=extension,
        mime_type=data.get("mime_type"),
        size_bytes=data.get("size_bytes"),
        bounds_m=bounds_from_mapping(data.get("bounds_m")),
        required=bool(data.get("required", False)),
        metadata={
            "source_document": source_document,
            "field_path": field_path,
            **dict(data.get("metadata", {}) or {}),
        },
    ).normalized()


def asset_target_from_asset_reference(asset: Any) -> AssetValidationTarget:
    """Baut AssetValidationTarget aus AssetReference-ähnlichem Objekt."""
    try:
        normalized = asset.normalized() if hasattr(asset, "normalized") else asset

        source = getattr(normalized, "source", None)
        target = getattr(normalized, "target", None)

        source_ref = getattr(source, "path", None) if source is not None else None
        source_kind = getattr(source, "origin", None) if source is not None else None
        target_path = getattr(target, "package_path", None) if target is not None else None
        module_name = getattr(target, "module_name", None) if target is not None else None

        bounds = getattr(normalized, "bounds_m", None)
        bounds_target = None
        if bounds is not None:
            bounds_normalized = bounds.normalized() if hasattr(bounds, "normalized") else bounds
            bounds_target = AssetBounds(
                width_m=getattr(bounds_normalized, "width_m"),
                height_m=getattr(bounds_normalized, "height_m"),
                depth_m=getattr(bounds_normalized, "depth_m"),
            ).normalized()

        role = getattr(normalized, "role", None)
        extension = infer_extension(source_ref or target_path)

        return AssetValidationTarget(
            asset_id=getattr(normalized, "asset_id", None),
            role=role,
            asset_kind=getattr(normalized, "asset_type", None) or infer_asset_kind(role=role, extension=extension),
            source_ref=source_ref,
            source_kind=source_kind or infer_source_kind(source_ref),
            target_path=target_path,
            module_name=module_name,
            extension=extension,
            mime_type=getattr(normalized, "mime_type", None),
            size_bytes=getattr(normalized, "size_bytes", None),
            bounds_m=bounds_target,
            required=bool(getattr(normalized, "required", False)),
            metadata=getattr(normalized, "metadata", {}) or {},
        ).normalized()
    except Exception as exc:
        raise AssetValidatorError(f"Could not build asset validation target from AssetReference: {exc}") from exc


def bounds_from_mapping(value: Any) -> AssetBounds | None:
    """Normalisiert Bounds aus Mapping oder AssetBounds."""
    if value is None:
        return None

    if isinstance(value, AssetBounds):
        return value.normalized()

    if not isinstance(value, Mapping):
        return None

    try:
        size_m = value.get("size_m")
        if isinstance(size_m, Mapping):
            return AssetBounds(
                width_m=size_m.get("x"),
                height_m=size_m.get("y"),
                depth_m=size_m.get("z"),
            ).normalized()

        return AssetBounds(
            width_m=value.get("width_m", value.get("width")),
            height_m=value.get("height_m", value.get("height")),
            depth_m=value.get("depth_m", value.get("depth")),
        ).normalized()
    except Exception:
        return None


def extract_footprint_size_m(documents: Mapping[str, Mapping[str, Any]]) -> tuple[float, float, float] | None:
    """Extrahiert Grid-Footprint-Größe aus editor/placement.json."""
    try:
        placement = documents.get("editor/placement.json", {})
        grid = placement.get("grid_footprint") if isinstance(placement, Mapping) else None

        if not isinstance(grid, Mapping):
            return None

        size_cells = grid.get("size_cells", {})
        if not isinstance(size_cells, Mapping):
            size_cells = {}

        x = int(grid.get("size_cells_x", size_cells.get("x", 1)))
        y = int(grid.get("size_cells_y", size_cells.get("y", 1)))
        z = int(grid.get("size_cells_z", size_cells.get("z", 1)))
        cell_size_m = float(grid.get("cell_size_m", 1.0))

        return (x * cell_size_m, y * cell_size_m, z * cell_size_m)
    except Exception:
        return None


def validate_package_asset_path(path: Any) -> tuple[bool, tuple[str, ...]]:
    """Validiert einen package-relativen Assetpfad."""
    messages: list[str] = []

    try:
        normalized_path = normalize_package_path(path)

        if normalized_path.startswith("../") or "/../" in normalized_path:
            messages.append(f"Asset target path {normalized_path!r} contains parent traversal.")

        if normalized_path.startswith("/") or "\\" in normalized_path:
            messages.append(f"Asset target path {normalized_path!r} must be package-relative POSIX style.")

        root = normalized_path.split("/", 1)[0]
        if root not in PACKAGE_INTERNAL_ROOTS:
            messages.append(f"Asset target path {normalized_path!r} starts with unknown package root {root!r}.")

        extension = infer_extension(normalized_path)
        if extension in FORBIDDEN_ASSET_EXTENSIONS:
            messages.append(f"Asset target path {normalized_path!r} uses forbidden extension {extension!r}.")

    except Exception as exc:
        messages.append(str(exc))

    return len(messages) == 0, tuple(messages)


def issue_for_target(
    target: AssetValidationTarget,
    *,
    code: str,
    message: str,
    severity: str = AssetIssueSeverity.ERROR.value,
    path: str | None = None,
    field_path: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> AssetIssue:
    """Factory für target-bezogenes AssetIssue."""
    normalized = target.normalized()

    return asset_issue(
        code=code,
        message=message,
        severity=severity,
        asset_id=normalized.asset_id,
        role=normalized.role,
        path=path or normalized.target_path or normalized.source_ref,
        field_path=field_path,
        module_name=normalized.module_name,
        details={
            "asset": normalized.to_dict(),
            **dict(details or {}),
        },
    )


def asset_issue(
    *,
    code: str,
    message: str,
    severity: str = AssetIssueSeverity.ERROR.value,
    asset_id: str | None = None,
    role: str | None = None,
    path: str | None = None,
    field_path: str | None = None,
    module_name: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> AssetIssue:
    """Factory für AssetIssue."""
    return AssetIssue(
        code=code,
        message=message,
        severity=severity,
        asset_id=asset_id,
        role=role,
        path=path,
        field_path=field_path,
        module_name=module_name,
        details=dict(details or {}),
    ).normalized()


def build_validation_result_from_asset_issues(issues: Iterable[AssetIssue]) -> Any:
    """Baut ein ValidationResult aus AssetIssues."""
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
                    "source": "asset_validator",
                    "schema_version": ASSET_VALIDATOR_SCHEMA_VERSION,
                }
            )

        validation_issues = tuple(
            ValidationIssue(
                code=issue.code,
                message=issue.message,
                severity=issue.severity,
                scope=ValidationScope.ASSET.value,
                path=issue.path,
                field_path=issue.field_path,
                module_name=issue.module_name,
                details={
                    "asset_id": issue.asset_id,
                    "role": issue.role,
                    **dict(issue.details),
                },
            ).normalized()
            for issue in normalized_issues
        )

        return invalid_result(
            validation_issues,
            metadata={
                "source": "asset_validator",
                "schema_version": ASSET_VALIDATOR_SCHEMA_VERSION,
            },
        )
    except Exception:
        normalized_issues = tuple(issue.normalized() for issue in issues or ())
        return {
            "schema_version": ASSET_VALIDATOR_SCHEMA_VERSION,
            "valid": not any(issue.blocks_success for issue in normalized_issues),
            "issues": [issue.to_dict() for issue in normalized_issues],
        }


def normalize_asset_collection(value: Any) -> Any:
    """Normalisiert AssetReferenceCollection-ähnliche Werte."""
    try:
        from ..models.asset_reference import AssetReferenceCollection, asset_references_from_iterable

        if isinstance(value, AssetReferenceCollection):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            return asset_references_from_iterable(value).normalized()

        raise AssetValidatorError("AssetReferenceCollection value is required.")
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Invalid AssetReferenceCollection: {exc}") from exc


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

        raise AssetValidatorError("DocumentBundle value is required.")
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Invalid DocumentBundle: {exc}") from exc


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
        raise AssetValidatorError(f"Invalid ValidationResult: {exc}") from exc


def normalize_options(
    options: AssetValidationOptions | Mapping[str, Any] | None,
) -> AssetValidationOptions:
    """Normalisiert AssetValidationOptions."""
    if options is None:
        return AssetValidationOptions().normalized()

    if isinstance(options, AssetValidationOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return AssetValidationOptions(
            mode=options.get("mode", AssetValidationMode.STRICT.value),
            allow_external_uri=bool(options.get("allow_external_uri", False)),
            allow_package_internal_refs=bool(options.get("allow_package_internal_refs", True)),
            require_source_ref=bool(options.get("require_source_ref", True)),
            require_target_path_for_local_assets=bool(options.get("require_target_path_for_local_assets", True)),
            require_model_bounds=bool(options.get("require_model_bounds", True)),
            require_model_inside_footprint=bool(options.get("require_model_inside_footprint", True)),
            validate_extensions=bool(options.get("validate_extensions", True)),
            validate_target_paths=bool(options.get("validate_target_paths", True)),
            validate_role_target_module=bool(options.get("validate_role_target_module", True)),
            validate_profile_rules=bool(options.get("validate_profile_rules", True)),
            validate_duplicates=bool(options.get("validate_duplicates", True)),
            validate_declared_size=bool(options.get("validate_declared_size", True)),
            validate_declarative_safety=bool(options.get("validate_declarative_safety", True)),
            max_model_size_mb=options.get("max_model_size_mb", DEFAULT_MAX_MODEL_SIZE_MB),
            max_texture_size_mb=options.get("max_texture_size_mb", DEFAULT_MAX_TEXTURE_SIZE_MB),
            max_image_size_mb=options.get("max_image_size_mb", DEFAULT_MAX_IMAGE_SIZE_MB),
            max_document_size_mb=options.get("max_document_size_mb", DEFAULT_MAX_DOCUMENT_SIZE_MB),
            collect_all_errors=bool(options.get("collect_all_errors", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise AssetValidatorError("options must be AssetValidationOptions, mapping or None.")


def normalize_documents_mapping(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Normalisiert path -> document Mapping."""
    if not isinstance(documents, Mapping):
        raise AssetValidatorError("documents must be a mapping.")

    return {
        normalize_package_path(path): normalize_document_mapping(document)
        for path, document in documents.items()
    }


def normalize_document_mapping(document: Mapping[str, Any]) -> dict[str, Any]:
    """Normalisiert ein Dokument-Mapping JSON-kompatibel."""
    if not isinstance(document, Mapping):
        raise AssetValidatorError("document must be a mapping.")

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
    raw = clean_required_string(value, "path").replace("\\", "/").strip().strip("/")

    if not raw:
        raise AssetValidatorError("path is required.")

    if raw.startswith("../") or "/../" in raw:
        raise AssetValidatorError(f"Unsafe package path {value!r}.")

    return raw


def normalize_optional_package_path(value: Any) -> str | None:
    """Normalisiert optionalen package-relativen Pfad."""
    if value is None:
        return None

    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    return normalize_package_path(cleaned)


def normalize_asset_role_value(value: Any) -> str:
    """Normalisiert Asset-Rolle."""
    try:
        from ..models.asset_reference import parse_asset_role_value

        return parse_asset_role_value(value)
    except Exception:
        raw = normalize_enum_key(value)
        if raw in ROLE_ALLOWED_EXTENSIONS:
            return raw
        raise AssetValidatorError(f"Invalid asset role {value!r}.")


def normalize_optional_asset_role_value(value: Any) -> str | None:
    """Normalisiert optionale Asset-Rolle."""
    if value is None:
        return None

    return normalize_asset_role_value(value)


def normalize_optional_asset_id(value: Any) -> str | None:
    """Normalisiert optionale Asset-ID."""
    if value is None:
        return None

    raw = clean_optional_string(value)
    if not raw:
        return None

    return (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def normalize_optional_extension(value: Any) -> str | None:
    """Normalisiert optionale Dateiendung."""
    if value is None:
        return None

    raw = clean_optional_string(value)
    if not raw:
        return None

    extension = raw.lower()
    if not extension.startswith("."):
        extension = f".{extension}"

    return extension


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


def infer_module_from_path_safe(path: Any) -> str | None:
    """Leitet Modul aus package-relativem Pfad ab."""
    try:
        raw = normalize_package_path(path)
        first = raw.split("/", 1)[0]
        return first if first in PACKAGE_INTERNAL_ROOTS else None
    except Exception:
        return None


def infer_target_module_for_role(role: Any) -> str:
    """Leitet erwartetes Zielmodul aus Asset-Rolle ab."""
    try:
        role_value = normalize_asset_role_value(role)
        return ROLE_EXPECTED_MODULE.get(role_value, "render")
    except Exception:
        return "render"


def infer_asset_kind(*, role: Any, extension: str | None) -> str:
    """Leitet AssetReferenceKind aus Rolle und Endung ab."""
    role_value = clean_optional_string(role) or "other"
    extension_value = normalize_optional_extension(extension)

    if role_value in {"glb_model", "gltf_model", "lod_model"} or extension_value in MODEL_EXTENSIONS:
        return AssetReferenceKind.MODEL.value

    if role_value in {"texture", "material_texture"} or extension_value in TEXTURE_EXTENSIONS:
        return AssetReferenceKind.TEXTURE.value

    if role_value in {"icon", "preview"} or extension_value in IMAGE_EXTENSIONS:
        return AssetReferenceKind.IMAGE.value

    if role_value == "documentation" or extension_value in DOCUMENT_EXTENSIONS:
        return AssetReferenceKind.DOCUMENT.value

    if role_value == "test_fixture" or extension_value in DATA_EXTENSIONS:
        return AssetReferenceKind.DATA.value

    return AssetReferenceKind.UNKNOWN.value


def infer_source_kind(value: Any) -> str:
    """Leitet SourceKind aus Referenz ab."""
    ref = clean_optional_string(value)

    if not ref:
        return AssetSourceKind.UNKNOWN.value

    if is_external_uri(ref):
        return AssetSourceKind.EXTERNAL_URI.value

    if is_package_internal_path(ref):
        return AssetSourceKind.PACKAGE_INTERNAL.value

    return AssetSourceKind.LOCAL_FILE.value


def infer_extension(value: Any) -> str | None:
    """Leitet Dateiendung aus Pfad/URI ab."""
    ref = clean_optional_string(value)
    if not ref:
        return None

    try:
        parsed = urlparse(ref)
        path = parsed.path if parsed.scheme else ref.replace("\\", "/")
        suffix = PurePosixPath(path).suffix.lower()
        return suffix or None
    except Exception:
        return None


def infer_asset_id(value: Any, *, role: str) -> str | None:
    """Leitet Asset-ID aus Pfad und Rolle ab."""
    ref = clean_optional_string(value)
    role_value = clean_optional_string(role) or "asset"

    if not ref:
        return normalize_optional_asset_id(role_value)

    try:
        parsed = urlparse(ref)
        path = parsed.path if parsed.scheme else ref.replace("\\", "/")
        stem = PurePosixPath(path).stem or role_value
        return normalize_optional_asset_id(f"{role_value}_{stem}")
    except Exception:
        return normalize_optional_asset_id(role_value)


def infer_mime_type(extension: str | None) -> str | None:
    """Leitet MIME-Type aus Dateiendung ab."""
    ext = normalize_optional_extension(extension)

    if ext == ".svg":
        return "image/svg+xml"
    if ext == ".png":
        return "image/png"
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".webp":
        return "image/webp"
    if ext == ".ktx2":
        return "image/ktx2"
    if ext == ".basis":
        return "image/ktx2"
    if ext == ".glb":
        return "model/gltf-binary"
    if ext == ".gltf":
        return "model/gltf+json"
    if ext == ".json":
        return "application/json"
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".md":
        return "text/markdown"
    if ext == ".txt":
        return "text/plain"
    if ext == ".csv":
        return "text/csv"

    return None


def is_external_uri(value: Any) -> bool:
    """Prüft HTTP/HTTPS URI."""
    try:
        parsed = urlparse(str(value).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def is_package_internal_path(value: Any) -> bool:
    """Prüft, ob eine Referenz package-intern wirkt."""
    ref = clean_optional_string(value)
    if not ref or is_external_uri(ref):
        return False

    normalized = ref.replace("\\", "/").strip().strip("/")
    root = normalized.split("/", 1)[0]

    return root in PACKAGE_INTERNAL_ROOTS


@lru_cache(maxsize=128)
def parse_validation_status_value(value: Any) -> str:
    """Parst AssetValidationStatus."""
    try:
        if isinstance(value, AssetValidationStatus):
            return value.value

        raw = normalize_enum_key(value)
        return AssetValidationStatus(raw).value
    except Exception as exc:
        raise AssetValidatorError(f"Invalid asset validation status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_mode_value(value: Any) -> str:
    """Parst AssetValidationMode."""
    try:
        if isinstance(value, AssetValidationMode):
            return value.value

        raw = normalize_enum_key(value)
        return AssetValidationMode(raw).value
    except Exception as exc:
        raise AssetValidatorError(f"Invalid asset validation mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_issue_severity_value(value: Any) -> str:
    """Parst AssetIssueSeverity."""
    try:
        if isinstance(value, AssetIssueSeverity):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "info": AssetIssueSeverity.INFO.value,
            "warning": AssetIssueSeverity.WARNING.value,
            "warn": AssetIssueSeverity.WARNING.value,
            "error": AssetIssueSeverity.ERROR.value,
            "fatal": AssetIssueSeverity.FATAL.value,
            "critical": AssetIssueSeverity.FATAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetIssueSeverity(raw).value
    except Exception as exc:
        raise AssetValidatorError(f"Invalid asset issue severity {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_issue_code_value(value: Any) -> str:
    """Parst AssetIssueCode."""
    try:
        if isinstance(value, AssetIssueCode):
            return value.value

        raw = str(value).strip().upper().replace(" ", "_").replace("-", "_")

        if not raw:
            raise AssetValidatorError("Asset issue code is required.")

        if not raw.startswith("VPLIB_"):
            raw = f"VPLIB_ASSET_{raw}"

        try:
            return AssetIssueCode(raw).value
        except ValueError:
            return raw
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Invalid asset issue code {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_source_kind_value(value: Any) -> str:
    """Parst AssetSourceKind."""
    try:
        if isinstance(value, AssetSourceKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "local": AssetSourceKind.LOCAL_FILE.value,
            "local_file": AssetSourceKind.LOCAL_FILE.value,
            "file": AssetSourceKind.LOCAL_FILE.value,
            "package": AssetSourceKind.PACKAGE_INTERNAL.value,
            "package_internal": AssetSourceKind.PACKAGE_INTERNAL.value,
            "internal": AssetSourceKind.PACKAGE_INTERNAL.value,
            "external": AssetSourceKind.EXTERNAL_URI.value,
            "external_uri": AssetSourceKind.EXTERNAL_URI.value,
            "uri": AssetSourceKind.EXTERNAL_URI.value,
            "url": AssetSourceKind.EXTERNAL_URI.value,
            "unknown": AssetSourceKind.UNKNOWN.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetSourceKind(raw).value
    except Exception as exc:
        raise AssetValidatorError(f"Invalid asset source kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_asset_reference_kind_value(value: Any) -> str:
    """Parst AssetReferenceKind."""
    try:
        if isinstance(value, AssetReferenceKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "image": AssetReferenceKind.IMAGE.value,
            "texture": AssetReferenceKind.TEXTURE.value,
            "model": AssetReferenceKind.MODEL.value,
            "document": AssetReferenceKind.DOCUMENT.value,
            "doc": AssetReferenceKind.DOCUMENT.value,
            "data": AssetReferenceKind.DATA.value,
            "unknown": AssetReferenceKind.UNKNOWN.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetReferenceKind(raw).value
    except Exception as exc:
        raise AssetValidatorError(f"Invalid asset reference kind {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise AssetValidatorError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"Invalid enum value {value!r}.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Float-Werte."""
    try:
        if isinstance(value, bool):
            raise AssetValidatorError(f"{field_name} must be a number.")

        number = float(value)
        if number <= 0:
            raise AssetValidatorError(f"{field_name} must be > 0.")

        return number
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"{field_name} must be a positive number.") from exc


def normalize_optional_non_negative_int(value: Any, field_name: str) -> int | None:
    """Normalisiert optionale nicht-negative Integer."""
    if value is None:
        return None

    try:
        if isinstance(value, bool):
            raise AssetValidatorError(f"{field_name} must be an integer.")

        number = int(value)
        if number < 0:
            raise AssetValidatorError(f"{field_name} must be >= 0.")

        return number
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"{field_name} must be a non-negative integer.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise AssetValidatorError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def dedupe_targets(targets: Iterable[AssetValidationTarget]) -> tuple[AssetValidationTarget, ...]:
    """Dedupliziert Targets konservativ."""
    result: list[AssetValidationTarget] = []
    seen: set[tuple[str | None, str | None, str]] = set()

    for target in targets or ():
        normalized = target.normalized()
        key = (normalized.asset_id, normalized.target_path, normalized.role)

        if key in seen:
            continue

        result.append(normalized)
        seen.add(key)

    return tuple(result)


def sort_targets(targets: Iterable[AssetValidationTarget]) -> tuple[AssetValidationTarget, ...]:
    """Sortiert Targets stabil."""
    return tuple(
        sorted(
            (target.normalized() for target in targets or ()),
            key=lambda target: (
                target.module_name or "",
                target.role,
                target.asset_id or "",
                target.target_path or "",
                target.source_ref or "",
            ),
        )
    )


def dedupe_issues(issues: Iterable[AssetIssue]) -> tuple[AssetIssue, ...]:
    """Dedupliziert Issues."""
    result: list[AssetIssue] = []
    seen: set[str] = set()

    for issue in issues or ():
        normalized = issue.normalized()
        fingerprint = normalized.fingerprint()

        if fingerprint in seen:
            continue

        result.append(normalized)
        seen.add(fingerprint)

    return tuple(result)


def sort_issues(issues: Iterable[AssetIssue]) -> tuple[AssetIssue, ...]:
    """Sortiert Issues stabil."""
    severity_order = {
        AssetIssueSeverity.FATAL.value: 10,
        AssetIssueSeverity.ERROR.value: 20,
        AssetIssueSeverity.WARNING.value: 30,
        AssetIssueSeverity.INFO.value: 40,
    }

    return tuple(
        sorted(
            (issue.normalized() for issue in issues or ()),
            key=lambda issue: (
                severity_order.get(issue.severity, 99),
                issue.module_name or "",
                issue.path or "",
                issue.role or "",
                issue.asset_id or "",
                issue.code,
            ),
        )
    )


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise AssetValidatorError(f"{field_name} is required.")

        return cleaned
    except AssetValidatorError:
        raise
    except Exception as exc:
        raise AssetValidatorError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_asset_validator_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_validation_status_value.cache_clear()
    parse_validation_mode_value.cache_clear()
    parse_issue_severity_value.cache_clear()
    parse_issue_code_value.cache_clear()
    parse_source_kind_value.cache_clear()
    parse_asset_reference_kind_value.cache_clear()


__all__ = [
    "ASSET_VALIDATOR_SCHEMA_VERSION",
    "DATA_EXTENSIONS",
    "DEFAULT_MAX_DOCUMENT_SIZE_MB",
    "DEFAULT_MAX_IMAGE_SIZE_MB",
    "DEFAULT_MAX_MODEL_SIZE_MB",
    "DEFAULT_MAX_TEXTURE_SIZE_MB",
    "DOCUMENT_EXTENSIONS",
    "FORBIDDEN_ASSET_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "MODEL_EXTENSIONS",
    "PACKAGE_INTERNAL_ROOTS",
    "ROLE_ALLOWED_EXTENSIONS",
    "ROLE_EXPECTED_MODULE",
    "TEXTURE_EXTENSIONS",
    "AssetBounds",
    "AssetIssue",
    "AssetIssueCode",
    "AssetIssueSeverity",
    "AssetReferenceKind",
    "AssetSourceKind",
    "AssetValidationMode",
    "AssetValidationOptions",
    "AssetValidationResult",
    "AssetValidationStatus",
    "AssetValidationTarget",
    "AssetValidatorError",
    "asset_issue",
    "asset_target_from_asset_reference",
    "asset_target_from_mapping_asset_ref",
    "bounds_from_mapping",
    "build_validation_result_from_asset_issues",
    "clean_optional_string",
    "clean_required_string",
    "clear_asset_validator_caches",
    "dedupe_issues",
    "dedupe_targets",
    "extract_asset_targets_from_documents",
    "extract_footprint_size_m",
    "infer_asset_id",
    "infer_asset_kind",
    "infer_extension",
    "infer_mime_type",
    "infer_module_from_path_safe",
    "infer_source_kind",
    "infer_target_module_for_role",
    "is_external_uri",
    "is_package_internal_path",
    "issue_for_target",
    "normalize_asset_collection",
    "normalize_asset_role_value",
    "normalize_document_bundle",
    "normalize_document_mapping",
    "normalize_documents_mapping",
    "normalize_enum_key",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_optional_asset_id",
    "normalize_optional_asset_role_value",
    "normalize_optional_extension",
    "normalize_optional_module_name",
    "normalize_optional_non_negative_int",
    "normalize_optional_package_path",
    "normalize_options",
    "normalize_package_path",
    "normalize_positive_float",
    "normalize_validation_result",
    "parse_asset_reference_kind_value",
    "parse_issue_code_value",
    "parse_issue_severity_value",
    "parse_source_kind_value",
    "parse_validation_mode_value",
    "parse_validation_status_value",
    "sort_issues",
    "sort_targets",
    "validate_asset_collection",
    "validate_asset_declared_size",
    "validate_asset_declarative_safety",
    "validate_asset_duplicates",
    "validate_asset_extension",
    "validate_asset_targets",
    "validate_creation_plan_assets",
    "validate_document_bundle_assets",
    "validate_documents_assets",
    "validate_package_asset_path",
    "validate_profile_asset_rules",
    "validate_single_asset_target",
]