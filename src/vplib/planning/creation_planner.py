# services/vectoplan-library/src/vplib/planning/creation_planner.py
"""
Creation planner for the VPLIB package engine.

Diese Datei orchestriert den ersten fachlichen Planungsschritt:

    raw request / dict
    -> CreateRequest
    -> PackageContext
    -> ObjectKindProfile
    -> ModulePlan
    -> PackagePlan
    -> CreationPlan

Wichtig:
Diese Datei schreibt keine Dateien. Sie erzeugt nur einen vollständigen Plan,
der später von creators/* ausgeführt wird.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Final, Iterable, Mapping


CREATION_PLANNER_SCHEMA_VERSION: Final[str] = "vplib.creation_planner.v1"


class CreationPlannerError(ValueError):
    """Wird ausgelöst, wenn die Erstellung nicht geplant werden kann."""


class CreationPlanStatus(str, Enum):
    """Status eines CreationPlan."""

    CREATED = "created"
    NORMALIZED = "normalized"
    PROFILE_RESOLVED = "profile_resolved"
    MODULES_PLANNED = "modules_planned"
    PACKAGE_PLANNED = "package_planned"
    VALIDATED = "validated"
    FAILED = "failed"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CreationPlan:
    """
    Vollständiger VPLIB-Erstellplan.

    Der Plan ist immutable und enthält:
    - normalized CreateRequest
    - PackageContext
    - ObjectKindProfile
    - ModulePlan
    - PackagePlan
    - optional ValidationResult

    Er schreibt keine Dateien.
    """

    request: Any
    context: Any
    profile: Any
    module_plan: Any
    package_plan: Any
    validation_result: Any | None = None
    status: str = CreationPlanStatus.PACKAGE_PLANNED.value
    schema_version: str = CREATION_PLANNER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CreationPlan":
        request = normalize_create_request(self.request)
        context = normalize_package_context(self.context)
        profile = normalize_profile(self.profile)
        module_plan = normalize_module_plan(self.module_plan)
        package_plan = normalize_package_plan(self.package_plan)
        validation_result = normalize_validation_result(self.validation_result)
        status = parse_creation_plan_status_value(self.status)
        metadata = normalize_metadata(self.metadata)

        valid, messages = validate_creation_plan_parts(
            request=request,
            context=context,
            profile=profile,
            module_plan=module_plan,
            package_plan=package_plan,
        )
        if not valid:
            raise CreationPlannerError(" ".join(messages))

        return CreationPlan(
            request=request,
            context=context,
            profile=profile,
            module_plan=module_plan,
            package_plan=package_plan,
            validation_result=validation_result,
            status=status,
            schema_version=self.schema_version or CREATION_PLANNER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def package_id(self) -> str:
        return self.normalized().context.identity.package_id

    @property
    def family_id(self) -> str:
        return self.normalized().context.identity.family_id

    @property
    def object_kind(self) -> str:
        return self.normalized().context.object_kind

    @property
    def package_dir(self) -> Path:
        return self.normalized().context.package_dir

    @property
    def active_module_names(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.active_module_names)

    @property
    def required_files(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.required_files)

    @property
    def is_valid(self) -> bool:
        normalized = self.normalized()
        if normalized.validation_result is None:
            return True

        if hasattr(normalized.validation_result, "is_valid"):
            return bool(normalized.validation_result.is_valid)

        if hasattr(normalized.validation_result, "valid"):
            return bool(normalized.validation_result.valid)

        if isinstance(normalized.validation_result, Mapping):
            return bool(normalized.validation_result.get("valid", False))

        return False

    def with_status(self, status: str) -> "CreationPlan":
        normalized = self.normalized()

        return CreationPlan(
            request=normalized.request,
            context=normalized.context,
            profile=normalized.profile,
            module_plan=normalized.module_plan,
            package_plan=normalized.package_plan,
            validation_result=normalized.validation_result,
            status=parse_creation_plan_status_value(status),
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_validation_result(self, validation_result: Any) -> "CreationPlan":
        normalized = self.normalized()

        return CreationPlan(
            request=normalized.request,
            context=normalized.context,
            profile=normalized.profile,
            module_plan=normalized.module_plan,
            package_plan=normalized.package_plan,
            validation_result=normalize_validation_result(validation_result),
            status=CreationPlanStatus.VALIDATED.value,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_metadata(self, metadata: Mapping[str, Any]) -> "CreationPlan":
        normalized = self.normalized()
        merged = dict(normalized.metadata)
        merged.update(normalize_metadata(metadata))

        return CreationPlan(
            request=normalized.request,
            context=normalized.context,
            profile=normalized.profile,
            module_plan=normalized.module_plan,
            package_plan=normalized.package_plan,
            validation_result=normalized.validation_result,
            status=normalized.status,
            schema_version=normalized.schema_version,
            metadata=merged,
        ).normalized()

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
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "object_kind": normalized.object_kind,
            "package_dir": str(normalized.package_dir),
            "request": normalized.request.to_dict() if hasattr(normalized.request, "to_dict") else None,
            "context": normalized.context.to_dict(),
            "profile": normalized.profile.to_dict(),
            "module_plan": normalized.module_plan.to_dict(),
            "package_plan": normalized.package_plan.to_dict(),
            "validation_result": validation_payload,
            "metadata": dict(normalized.metadata),
        }

    def to_summary_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "status": normalized.status,
            "package_id": normalized.package_id,
            "family_id": normalized.family_id,
            "object_kind": normalized.object_kind,
            "package_dir": str(normalized.package_dir),
            "profile_key": normalized.profile.profile_key,
            "active_modules": list(normalized.module_plan.active_module_names),
            "required_file_count": len(normalized.module_plan.required_files),
            "planned_directory_count": len(normalized.package_plan.directories),
            "planned_file_count": len(normalized.package_plan.files),
            "asset_copy_count": len(normalized.package_plan.asset_copies),
            "archive_path": str(normalized.package_plan.archive_path) if normalized.package_plan.archive_path else None,
            "valid": normalized.is_valid,
        }


def plan_vplib_creation(
    *,
    request: Any,
    service_root: str | Path,
    library_catalog_root: str | Path | None = None,
    source_root: str | Path | None = None,
    generated_root: str | Path | None = None,
    archive_root: str | Path | None = None,
    write_mode: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> CreationPlan:
    """
    Hauptfunktion für die VPLIB-Erstellplanung.

    Diese Funktion ist der stabile Einstieg für spätere Routen, Admin-UI und
    Tests. Sie schreibt keine Dateien.
    """
    try:
        normalized_request = normalize_create_request(request)

        context = build_context_for_request(
            request=normalized_request,
            service_root=service_root,
            library_catalog_root=library_catalog_root,
            source_root=source_root,
            generated_root=generated_root,
            archive_root=archive_root,
            write_mode=write_mode,
            metadata=metadata,
        )

        profile = resolve_profile_for_request(normalized_request)
        module_plan = build_module_plan_for_request(
            request=normalized_request,
            context=context,
            profile=profile,
        )
        package_plan = build_package_plan_for_request(
            request=normalized_request,
            context=context,
            module_plan=module_plan,
        )

        return CreationPlan(
            request=normalized_request,
            context=context,
            profile=profile,
            module_plan=module_plan,
            package_plan=package_plan,
            status=CreationPlanStatus.PACKAGE_PLANNED.value,
            metadata=dict(metadata or {}),
        ).normalized()
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Could not plan VPLIB creation: {exc}") from exc


def build_context_for_request(
    *,
    request: Any,
    service_root: str | Path,
    library_catalog_root: str | Path | None = None,
    source_root: str | Path | None = None,
    generated_root: str | Path | None = None,
    archive_root: str | Path | None = None,
    write_mode: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Baut den PackageContext für einen normalisierten Request."""
    try:
        from ..models.package_context import create_package_context

        return create_package_context(
            request=request,
            service_root=service_root,
            library_catalog_root=library_catalog_root,
            source_root=source_root,
            generated_root=generated_root,
            archive_root=archive_root,
            write_mode=write_mode,
            metadata=metadata,
        ).normalized()
    except Exception as exc:
        raise CreationPlannerError(f"Could not build package context: {exc}") from exc


def resolve_profile_for_request(request: Any) -> Any:
    """Löst das ObjectKindProfile für einen Request."""
    try:
        from ..profiles.profile_resolver import resolve_profile

        normalized_request = normalize_create_request(request)
        return resolve_profile(normalized_request.object_kind).normalized()
    except Exception as exc:
        raise CreationPlannerError(f"Could not resolve profile for request: {exc}") from exc


def build_module_plan_for_request(
    *,
    request: Any,
    context: Any,
    profile: Any,
) -> Any:
    """
    Baut den ModulePlan für einen Request.

    Der Profile-Plan ist führend. Request-Optionen wie include_docs/include_tests
    werden zusätzlich berücksichtigt.
    """
    try:
        from ..models.module_plan import ModulePlan, build_module_plan

        normalized_request = normalize_create_request(request)
        normalized_profile = normalize_profile(profile)

        base_plan = build_module_plan(
            object_kind=normalized_request.object_kind,
            active_modules=normalized_profile.active_module_names,
            required_modules=normalized_profile.required_module_names,
            recommended_modules=normalized_profile.recommended_module_names,
            optional_modules=normalized_profile.optional_module_names,
            excluded_modules=normalized_profile.excluded_module_names,
            include_docs=normalized_request.options.include_docs,
            include_tests=normalized_request.options.include_tests,
            profile_key=normalized_profile.profile_key,
            metadata={
                "planned_by": "creation_planner",
                "profile_key": normalized_profile.profile_key,
            },
        ).normalized()

        profile_entries = normalized_profile.to_module_plan_entries()
        final_plan = ModulePlan(
            entries=(*base_plan.entries, *profile_entries),
            object_kind=normalized_request.object_kind,
            profile_key=normalized_profile.profile_key,
            metadata={
                **dict(base_plan.metadata),
                "context_package_id": context.identity.package_id,
            },
        ).normalized()

        return final_plan
    except Exception as exc:
        raise CreationPlannerError(f"Could not build module plan: {exc}") from exc


def build_package_plan_for_request(
    *,
    request: Any,
    context: Any,
    module_plan: Any,
) -> Any:
    """Baut den PackagePlan inklusive einfacher Asset-Copy-Pläne."""
    try:
        from ..models.package_plan import build_package_plan

        normalized_request = normalize_create_request(request)
        normalized_context = normalize_package_context(context)
        normalized_module_plan = normalize_module_plan(module_plan)
        asset_copies = build_asset_copies_for_request(
            request=normalized_request,
            context=normalized_context,
        )

        return build_package_plan(
            context=normalized_context,
            module_plan=normalized_module_plan,
            asset_copies=asset_copies,
            metadata={
                "planned_by": "creation_planner",
                "asset_copy_count": len(asset_copies),
            },
        ).normalized()
    except Exception as exc:
        raise CreationPlannerError(f"Could not build package plan: {exc}") from exc


def build_asset_copies_for_request(
    *,
    request: Any,
    context: Any,
) -> tuple[Any, ...]:
    """
    Baut einfache Asset-Copy-Pläne aus Request-Assets.

    Wenn target_path fehlt, wird das Asset hier noch nicht kopierbar geplant.
    Später kann asset_planner.py bessere Zielpfade ableiten.
    """
    try:
        from ..models.asset_reference import asset_reference_from_create_asset_request
        from ..models.package_plan import PlannedAssetCopy

        normalized_request = normalize_create_request(request)
        normalized_context = normalize_package_context(context)

        planned: list[Any] = []

        for asset_request in normalized_request.assets or ():
            try:
                asset_reference = asset_reference_from_create_asset_request(asset_request)
            except Exception:
                continue

            if asset_reference.source is None or asset_reference.target is None:
                continue

            planned.append(
                PlannedAssetCopy(
                    role=asset_reference.role,
                    source_path=asset_reference.source.path,
                    target_relative_path=asset_reference.target.package_path,
                    target_absolute_path=normalized_context.package_dir / asset_reference.target.package_path,
                    module_name=asset_reference.target.module_name,
                    required=asset_reference.required,
                    overwrite_allowed=asset_reference.target.overwrite_allowed or normalized_context.may_overwrite,
                    asset_id=asset_reference.asset_id,
                    mime_type=asset_reference.mime_type,
                    reason="Asset copy planned from CreateRequest.",
                ).normalized()
            )

        return tuple(planned)
    except Exception as exc:
        raise CreationPlannerError(f"Could not build asset copy plans: {exc}") from exc


def validate_creation_plan_parts(
    *,
    request: Any,
    context: Any,
    profile: Any,
    module_plan: Any,
    package_plan: Any,
) -> tuple[bool, tuple[str, ...]]:
    """Validiert die Konsistenz der Hauptbestandteile eines CreationPlan."""
    messages: list[str] = []

    try:
        normalized_request = normalize_create_request(request)
        normalized_context = normalize_package_context(context)
        normalized_profile = normalize_profile(profile)
        normalized_module_plan = normalize_module_plan(module_plan)
        normalized_package_plan = normalize_package_plan(package_plan)

        if normalized_context.object_kind != normalized_request.object_kind:
            messages.append(
                f"Context object_kind {normalized_context.object_kind!r} does not match "
                f"request object_kind {normalized_request.object_kind!r}."
            )

        if normalized_profile.object_kind != normalized_request.object_kind:
            messages.append(
                f"Profile object_kind {normalized_profile.object_kind!r} does not match "
                f"request object_kind {normalized_request.object_kind!r}."
            )

        if normalized_module_plan.object_kind != normalized_request.object_kind:
            messages.append(
                f"ModulePlan object_kind {normalized_module_plan.object_kind!r} does not match "
                f"request object_kind {normalized_request.object_kind!r}."
            )

        if normalized_package_plan.context.identity.package_id != normalized_context.identity.package_id:
            messages.append("PackagePlan context package_id does not match CreationPlan context.")

        missing_profile_required_modules = [
            module_name
            for module_name in normalized_profile.required_module_names
            if module_name not in normalized_module_plan.active_module_names
        ]
        if missing_profile_required_modules:
            messages.append(
                "ModulePlan is missing required profile modules: "
                + ", ".join(missing_profile_required_modules)
            )

        valid_module_plan, module_messages = normalized_module_plan.validate()
        if not valid_module_plan:
            messages.extend(module_messages)

        valid_package_plan, package_messages = normalized_package_plan.validate()
        if not valid_package_plan:
            messages.extend(package_messages)

    except CreationPlannerError as exc:
        messages.append(str(exc))
    except Exception as exc:
        messages.append(f"Could not validate creation plan parts: {exc}")

    return len(messages) == 0, tuple(messages)


def creation_plan_from_mapping(data: Mapping[str, Any]) -> CreationPlan:
    """
    Baut einen CreationPlan aus einem Mapping.

    Diese Funktion ist primär für Tests oder spätere Persistenz gedacht.
    """
    try:
        if not isinstance(data, Mapping):
            raise CreationPlannerError("CreationPlan data must be a mapping.")

        request = normalize_create_request(data.get("request"))
        context = normalize_package_context(data.get("context"))
        profile = normalize_profile(data.get("profile"))
        module_plan = normalize_module_plan(data.get("module_plan"))
        package_plan = normalize_package_plan(data.get("package_plan"))
        validation_result = normalize_validation_result(data.get("validation_result"))

        return CreationPlan(
            request=request,
            context=context,
            profile=profile,
            module_plan=module_plan,
            package_plan=package_plan,
            validation_result=validation_result,
            status=data.get("status", CreationPlanStatus.PACKAGE_PLANNED.value),
            schema_version=data.get("schema_version", CREATION_PLANNER_SCHEMA_VERSION),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Could not build CreationPlan from mapping: {exc}") from exc


def normalize_create_request(value: Any) -> Any:
    """Normalisiert einen CreateRequest oder ein Mapping."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise CreationPlannerError("CreateRequest value is required.")
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Invalid CreateRequest: {exc}") from exc


def normalize_package_context(value: Any) -> Any:
    """Normalisiert einen PackageContext oder ein Mapping."""
    try:
        from ..models.package_context import PackageContext

        if isinstance(value, PackageContext):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise CreationPlannerError("PackageContext value is required.")
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Invalid PackageContext: {exc}") from exc


def normalize_profile(value: Any) -> Any:
    """Normalisiert ein ObjectKindProfile."""
    try:
        from ..profiles.base_profiles import ObjectKindProfile

        if isinstance(value, ObjectKindProfile):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping) and value.get("object_kind"):
            from ..profiles.profile_resolver import resolve_profile

            return resolve_profile(value["object_kind"]).normalized()

        raise CreationPlannerError("ObjectKindProfile value is required.")
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Invalid ObjectKindProfile: {exc}") from exc


def normalize_module_plan(value: Any) -> Any:
    """Normalisiert einen ModulePlan oder ein Mapping."""
    try:
        from ..models.module_plan import ModulePlan, module_plan_from_mapping

        if isinstance(value, ModulePlan):
            return value.normalized()

        if isinstance(value, Mapping):
            return module_plan_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise CreationPlannerError("ModulePlan value is required.")
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Invalid ModulePlan: {exc}") from exc


def normalize_package_plan(value: Any) -> Any:
    """Normalisiert einen PackagePlan."""
    try:
        from ..models.package_plan import PackagePlan

        if isinstance(value, PackagePlan):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise CreationPlannerError("PackagePlan value is required.")
    except CreationPlannerError:
        raise
    except Exception as exc:
        raise CreationPlannerError(f"Invalid PackagePlan: {exc}") from exc


def normalize_validation_result(value: Any) -> Any | None:
    """Normalisiert optional ein ValidationResult."""
    if value is None:
        return None

    try:
        from ..models.validation_result import validation_result_from_mapping

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Mapping):
            return validation_result_from_mapping(value).normalized()

        return value
    except Exception as exc:
        raise CreationPlannerError(f"Invalid ValidationResult: {exc}") from exc


def parse_creation_plan_status_value(value: Any) -> str:
    """Parst CreationPlanStatus."""
    try:
        if isinstance(value, CreationPlanStatus):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return CreationPlanStatus(raw).value
    except Exception as exc:
        raise CreationPlannerError(f"Invalid creation plan status {value!r}.") from exc


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise CreationPlannerError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert einen Metadata-Wert JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clear_creation_planner_caches() -> None:
    """Reserviert für spätere Caches; derzeit keine externen Caches."""
    return None


__all__ = [
    "CREATION_PLANNER_SCHEMA_VERSION",
    "CreationPlan",
    "CreationPlanStatus",
    "CreationPlannerError",
    "build_asset_copies_for_request",
    "build_context_for_request",
    "build_module_plan_for_request",
    "build_package_plan_for_request",
    "clear_creation_planner_caches",
    "creation_plan_from_mapping",
    "normalize_create_request",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_module_plan",
    "normalize_package_context",
    "normalize_package_plan",
    "normalize_profile",
    "normalize_validation_result",
    "parse_creation_plan_status_value",
    "plan_vplib_creation",
    "resolve_profile_for_request",
    "validate_creation_plan_parts",
]