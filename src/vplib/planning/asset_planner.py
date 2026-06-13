# services/vectoplan-library/src/vplib/planning/asset_planner.py
"""
Asset planner for the VPLIB package engine.

Diese Datei plant Asset-Referenzen und Asset-Copy-Ziele für ein modulares
VPLIB-Package.

Rolle dieser Datei:

    CreateRequest.visual
    + CreateRequest.assets
    + PackageContext
    + ObjectKindProfile
    -> AssetPlanningResult
    -> AssetReferenceCollection
    -> PlannedAssetCopy entries for PackagePlan

Diese Datei kopiert keine Dateien, liest keine Bildgrößen und analysiert keine
GLB-Geometrie. Sie plant nur:
- welche Assets bekannt sind
- welche Assets kopiert werden müssen
- welche Package-Zielpfade verwendet werden
- welche Asset-Regeln aus dem Profil relevant sind

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping
from urllib.parse import urlparse


ASSET_PLANNER_SCHEMA_VERSION: Final[str] = "vplib.asset_planner.v1"

DEFAULT_RENDER_MODULE_NAME: Final[str] = "render"
DEFAULT_ASSET_TARGET_ROOT: Final[str] = "render"

ROLE_TARGET_DIRECTORIES: Final[dict[str, str]] = {
    "icon": "render/icons",
    "preview": "render/previews",
    "texture": "render/textures",
    "material_texture": "render/textures",
    "glb_model": "render/models",
    "gltf_model": "render/models",
    "lod_model": "render/models",
    "documentation": "docs/assets",
    "test_fixture": "tests/fixtures",
    "other": "render/assets",
}

ROLE_DEFAULT_FILENAMES: Final[dict[str, str]] = {
    "icon": "icon.svg",
    "preview": "preview.webp",
    "texture": "texture.webp",
    "material_texture": "material_texture.webp",
    "glb_model": "mesh.glb",
    "gltf_model": "mesh.gltf",
    "lod_model": "lod.glb",
    "documentation": "asset.md",
    "test_fixture": "fixture.json",
    "other": "asset.bin",
}


class AssetPlannerError(ValueError):
    """Wird ausgelöst, wenn Assets nicht geplant werden können."""


class AssetPlanningSource(str, Enum):
    """Quelle einer Asset-Planung."""

    REQUEST_ASSET = "request_asset"
    REQUEST_VISUAL = "request_visual"
    PROFILE_RULE = "profile_rule"
    PACKAGE_INTERNAL = "package_internal"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetPlanningAction(str, Enum):
    """Aktion einer Asset-Planung."""

    REGISTER = "register"
    COPY = "copy"
    KEEP_INTERNAL = "keep_internal"
    SKIP = "skip"
    REQUIRE = "require"
    WARN = "warn"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetTargetStrategy(str, Enum):
    """Strategie für Zielpfade."""

    PRESERVE_FILENAME = "preserve_filename"
    CANONICAL_ROLE_PATH = "canonical_role_path"
    KEEP_INTERNAL_PATH = "keep_internal_path"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AssetPlanningOptions:
    """Optionen für die Assetplanung."""

    target_strategy: str = AssetTargetStrategy.CANONICAL_ROLE_PATH.value
    allow_external_uri: bool = False
    allow_package_internal_refs: bool = True
    require_declared_model_bounds: bool = True
    plan_copy_for_local_assets: bool = True
    validate_profile_rules: bool = True
    strict: bool = True

    def normalized(self) -> "AssetPlanningOptions":
        return AssetPlanningOptions(
            target_strategy=parse_target_strategy_value(self.target_strategy),
            allow_external_uri=bool(self.allow_external_uri),
            allow_package_internal_refs=bool(self.allow_package_internal_refs),
            require_declared_model_bounds=bool(self.require_declared_model_bounds),
            plan_copy_for_local_assets=bool(self.plan_copy_for_local_assets),
            validate_profile_rules=bool(self.validate_profile_rules),
            strict=bool(self.strict),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "target_strategy": normalized.target_strategy,
            "allow_external_uri": normalized.allow_external_uri,
            "allow_package_internal_refs": normalized.allow_package_internal_refs,
            "require_declared_model_bounds": normalized.require_declared_model_bounds,
            "plan_copy_for_local_assets": normalized.plan_copy_for_local_assets,
            "validate_profile_rules": normalized.validate_profile_rules,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class AssetPlanningDecision:
    """Einzelne Asset-Planungsentscheidung."""

    action: str
    source: str
    role: str
    asset_id: str | None = None
    source_path: str | None = None
    target_path: str | None = None
    message: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AssetPlanningDecision":
        action = parse_asset_planning_action_value(self.action)
        source = parse_asset_planning_source_value(self.source)
        role = normalize_asset_role_value(self.role)
        asset_id = normalize_optional_asset_id(self.asset_id)
        source_path = clean_optional_string(self.source_path)
        target_path = clean_optional_string(self.target_path)
        message = clean_optional_string(self.message) or ""
        metadata = normalize_metadata(self.metadata)

        return AssetPlanningDecision(
            action=action,
            source=source,
            role=role,
            asset_id=asset_id,
            source_path=source_path,
            target_path=target_path,
            message=message,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "action": normalized.action,
            "source": normalized.source,
            "role": normalized.role,
            "asset_id": normalized.asset_id,
            "source_path": normalized.source_path,
            "target_path": normalized.target_path,
            "message": normalized.message,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class AssetPlanningResult:
    """Ergebnis der Assetplanung."""

    asset_collection: Any
    asset_copies: tuple[Any, ...] = field(default_factory=tuple)
    decisions: tuple[AssetPlanningDecision, ...] = field(default_factory=tuple)
    options: AssetPlanningOptions = field(default_factory=AssetPlanningOptions)
    schema_version: str = ASSET_PLANNER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AssetPlanningResult":
        asset_collection = normalize_asset_collection(self.asset_collection)
        asset_copies = tuple(normalize_planned_asset_copy(copy) for copy in self.asset_copies or ())
        decisions = tuple(decision.normalized() for decision in self.decisions or ())
        options = self.options.normalized()
        metadata = normalize_metadata(self.metadata)

        valid, messages = validate_asset_planning_parts(
            asset_collection=asset_collection,
            asset_copies=asset_copies,
            decisions=decisions,
            options=options,
        )
        if not valid:
            raise AssetPlannerError(" ".join(messages))

        return AssetPlanningResult(
            asset_collection=asset_collection,
            asset_copies=asset_copies,
            decisions=dedupe_decisions(decisions),
            options=options,
            schema_version=self.schema_version or ASSET_PLANNER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def assets(self) -> tuple[Any, ...]:
        return tuple(self.normalized().asset_collection.assets)

    @property
    def required_assets(self) -> tuple[Any, ...]:
        return tuple(self.normalized().asset_collection.required_assets())

    @property
    def optional_assets(self) -> tuple[Any, ...]:
        return tuple(self.normalized().asset_collection.optional_assets())

    @property
    def copy_count(self) -> int:
        return len(self.normalized().asset_copies)

    @property
    def asset_count(self) -> int:
        return len(self.normalized().assets)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "asset_count": normalized.asset_count,
            "required_asset_count": len(normalized.required_assets),
            "optional_asset_count": len(normalized.optional_assets),
            "copy_count": normalized.copy_count,
            "asset_collection": normalized.asset_collection.to_dict(),
            "asset_copies": [
                copy.to_dict() if hasattr(copy, "to_dict") else copy
                for copy in normalized.asset_copies
            ],
            "decisions": [decision.to_dict() for decision in normalized.decisions],
            "options": normalized.options.to_dict(),
            "metadata": dict(normalized.metadata),
        }


def plan_assets_for_request(
    *,
    request: Any,
    context: Any,
    profile: Any | None = None,
    options: AssetPlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetPlanningResult:
    """
    Plant Assets aus einem CreateRequest.

    Dies ist der bevorzugte Einstieg für spätere Creator und PackagePlanner.
    """
    try:
        normalized_request = normalize_create_request(request)
        normalized_context = normalize_package_context(context)
        normalized_profile = normalize_profile(profile) if profile is not None else None
        normalized_options = normalize_options(options)

        assets: list[Any] = []
        decisions: list[AssetPlanningDecision] = []

        visual_assets, visual_decisions = collect_visual_assets_from_request(
            request=normalized_request,
            context=normalized_context,
            options=normalized_options,
        )
        assets.extend(visual_assets)
        decisions.extend(visual_decisions)

        explicit_assets, explicit_decisions = collect_explicit_assets_from_request(
            request=normalized_request,
            context=normalized_context,
            options=normalized_options,
        )
        assets.extend(explicit_assets)
        decisions.extend(explicit_decisions)

        if normalized_profile is not None and normalized_options.validate_profile_rules:
            profile_decisions = collect_profile_asset_decisions(
                profile=normalized_profile,
                assets=assets,
            )
            decisions.extend(profile_decisions)

        asset_collection = build_asset_collection(assets)
        asset_copies = build_asset_copy_plans(
            asset_collection=asset_collection,
            context=normalized_context,
            options=normalized_options,
        )

        return AssetPlanningResult(
            asset_collection=asset_collection,
            asset_copies=asset_copies,
            decisions=tuple(decisions),
            options=normalized_options,
            metadata={
                "planned_by": "asset_planner",
                "profile_key": getattr(normalized_profile, "profile_key", None),
                **dict(metadata or {}),
            },
        ).normalized()
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not plan assets for request: {exc}") from exc


def plan_assets_from_references(
    *,
    asset_references: Iterable[Any],
    context: Any,
    options: AssetPlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AssetPlanningResult:
    """Plant AssetCopies aus vorhandenen AssetReference-Werten."""
    try:
        normalized_context = normalize_package_context(context)
        normalized_options = normalize_options(options)
        asset_collection = build_asset_collection(asset_references)
        asset_copies = build_asset_copy_plans(
            asset_collection=asset_collection,
            context=normalized_context,
            options=normalized_options,
        )

        decisions = tuple(
            AssetPlanningDecision(
                action="copy" if asset.source and asset.target else "register",
                source=AssetPlanningSource.SYSTEM.value,
                role=asset.role,
                asset_id=asset.asset_id,
                source_path=asset.source.path if asset.source else None,
                target_path=asset.target.package_path if asset.target else None,
                message="Asset planned from existing AssetReference.",
            ).normalized()
            for asset in asset_collection.assets
        )

        return AssetPlanningResult(
            asset_collection=asset_collection,
            asset_copies=asset_copies,
            decisions=decisions,
            options=normalized_options,
            metadata={
                "planned_by": "asset_planner",
                **dict(metadata or {}),
            },
        ).normalized()
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not plan assets from references: {exc}") from exc


def collect_visual_assets_from_request(
    *,
    request: Any,
    context: Any,
    options: AssetPlanningOptions,
) -> tuple[tuple[Any, ...], tuple[AssetPlanningDecision, ...]]:
    """Sammelt Assets aus request.visual."""
    try:
        visual = request.visual.normalized()
        assets: list[Any] = []
        decisions: list[AssetPlanningDecision] = []

        visual_refs = (
            ("icon", visual.icon_ref),
            ("preview", visual.preview_ref),
            ("texture", visual.texture_ref),
            ("glb_model", visual.glb_ref or visual.model_ref),
        )

        for role, reference in visual_refs:
            if not reference:
                continue

            asset = build_asset_reference_from_visual_ref(
                role=role,
                reference=reference,
                request=request,
                context=context,
                options=options,
            )
            assets.append(asset)

            decisions.append(
                AssetPlanningDecision(
                    action=AssetPlanningAction.COPY.value if asset.source and asset.target else AssetPlanningAction.REGISTER.value,
                    source=AssetPlanningSource.REQUEST_VISUAL.value,
                    role=role,
                    asset_id=asset.asset_id,
                    source_path=asset.source.path if asset.source else None,
                    target_path=asset.target.package_path if asset.target else None,
                    message="Asset planned from visual request reference.",
                ).normalized()
            )

        return tuple(assets), tuple(decisions)
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not collect visual assets: {exc}") from exc


def collect_explicit_assets_from_request(
    *,
    request: Any,
    context: Any,
    options: AssetPlanningOptions,
) -> tuple[tuple[Any, ...], tuple[AssetPlanningDecision, ...]]:
    """Sammelt explizite Assets aus request.assets."""
    assets: list[Any] = []
    decisions: list[AssetPlanningDecision] = []

    try:
        for asset_request in request.assets or ():
            asset_reference = build_asset_reference_from_request_asset(
                asset_request=asset_request,
                request=request,
                context=context,
                options=options,
            )
            assets.append(asset_reference)

            decisions.append(
                AssetPlanningDecision(
                    action=AssetPlanningAction.COPY.value if asset_reference.source and asset_reference.target else AssetPlanningAction.REGISTER.value,
                    source=AssetPlanningSource.REQUEST_ASSET.value,
                    role=asset_reference.role,
                    asset_id=asset_reference.asset_id,
                    source_path=asset_reference.source.path if asset_reference.source else None,
                    target_path=asset_reference.target.package_path if asset_reference.target else None,
                    message="Asset planned from explicit request asset.",
                ).normalized()
            )

        return tuple(assets), tuple(decisions)
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not collect explicit assets: {exc}") from exc


def collect_profile_asset_decisions(
    *,
    profile: Any,
    assets: Iterable[Any],
) -> tuple[AssetPlanningDecision, ...]:
    """Sammelt Hinweise aus Profil-Assetregeln."""
    normalized_profile = normalize_profile(profile)
    assets_tuple = tuple(asset.normalized() if hasattr(asset, "normalized") else asset for asset in assets or ())
    roles_present = {asset.role for asset in assets_tuple if hasattr(asset, "role")}

    decisions: list[AssetPlanningDecision] = []

    for rule in normalized_profile.asset_rules:
        if rule.role in roles_present:
            continue

        if rule.policy == "required":
            decisions.append(
                AssetPlanningDecision(
                    action=AssetPlanningAction.REQUIRE.value,
                    source=AssetPlanningSource.PROFILE_RULE.value,
                    role=rule.role,
                    message=f"Profile requires asset role {rule.role}.",
                    metadata={
                        "profile_key": normalized_profile.profile_key,
                        "policy": rule.policy,
                    },
                ).normalized()
            )
        elif rule.policy == "recommended":
            decisions.append(
                AssetPlanningDecision(
                    action=AssetPlanningAction.WARN.value,
                    source=AssetPlanningSource.PROFILE_RULE.value,
                    role=rule.role,
                    message=f"Profile recommends asset role {rule.role}.",
                    metadata={
                        "profile_key": normalized_profile.profile_key,
                        "policy": rule.policy,
                    },
                ).normalized()
            )

    return tuple(decisions)


def build_asset_reference_from_visual_ref(
    *,
    role: str,
    reference: str,
    request: Any,
    context: Any,
    options: AssetPlanningOptions,
) -> Any:
    """Baut AssetReference aus einer Visual-Referenz."""
    try:
        from ..models.asset_reference import AssetBounds3D, AssetReference, AssetSource, AssetTarget

        role_value = normalize_asset_role_value(role)
        reference_value = clean_required_string(reference, "reference")
        source = build_asset_source(reference_value, options=options)
        target = build_asset_target(
            role=role_value,
            reference=reference_value,
            options=options,
        )

        bounds = None
        if role_value in {"glb_model", "gltf_model", "lod_model"}:
            visual_bounds = getattr(request.visual, "model_bounds_m", None)
            if visual_bounds is None and options.require_declared_model_bounds:
                raise AssetPlannerError(f"Model asset {reference_value!r} requires declared model bounds.")

            if visual_bounds is not None:
                normalized_bounds = visual_bounds.normalized()
                bounds = AssetBounds3D(
                    width_m=normalized_bounds.width_m,
                    height_m=normalized_bounds.height_m,
                    depth_m=normalized_bounds.depth_m,
                ).normalized()

        return AssetReference(
            asset_id=infer_asset_id_from_path_safe(reference_value),
            role=role_value,
            asset_type=infer_asset_type_for_role(role_value, reference_value),
            source=source,
            target=target,
            bounds_m=bounds,
            required=False,
        ).normalized()
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not build visual asset reference: {exc}") from exc


def build_asset_reference_from_request_asset(
    *,
    asset_request: Any,
    request: Any,
    context: Any,
    options: AssetPlanningOptions,
) -> Any:
    """Baut AssetReference aus einem expliziten CreateRequest-Asset."""
    try:
        from ..models.asset_reference import AssetReference, AssetSource, AssetTarget

        normalized_request_asset = (
            asset_request.normalized()
            if hasattr(asset_request, "normalized")
            else asset_request
        )

        role = getattr(normalized_request_asset, "role", None)
        source_path = getattr(normalized_request_asset, "source_path", None)
        target_path = getattr(normalized_request_asset, "target_path", None)
        asset_id = getattr(normalized_request_asset, "asset_id", None)
        mime_type = getattr(normalized_request_asset, "mime_type", None)

        role_value = normalize_asset_role_value(role)
        source_path_value = clean_required_string(source_path, "source_path")
        source = build_asset_source(source_path_value, options=options)

        target = (
            AssetTarget(
                package_path=target_path,
                module_name=infer_target_module_for_role(role_value),
                overwrite_allowed=options.target_strategy == AssetTargetStrategy.CANONICAL_ROLE_PATH.value,
            ).normalized()
            if target_path
            else build_asset_target(
                role=role_value,
                reference=source_path_value,
                options=options,
            )
        )

        return AssetReference(
            asset_id=asset_id or infer_asset_id_from_path_safe(source_path_value),
            role=role_value,
            asset_type=infer_asset_type_for_role(role_value, source_path_value),
            source=source,
            target=target,
            mime_type=mime_type,
            required=False,
        ).normalized()
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not build request asset reference: {exc}") from exc


def build_asset_source(reference: str, *, options: AssetPlanningOptions) -> Any:
    """Baut AssetSource aus einer Referenz."""
    try:
        from ..models.asset_reference import AssetOrigin, AssetSource

        reference_value = clean_required_string(reference, "reference")

        if is_external_uri(reference_value):
            return AssetSource(
                origin=AssetOrigin.EXTERNAL_URI.value,
                path=reference_value,
                allow_external_uri=options.allow_external_uri,
            ).normalized()

        if is_package_internal_path(reference_value):
            if not options.allow_package_internal_refs:
                raise AssetPlannerError(f"Package-internal asset references are disabled: {reference_value!r}.")
            return AssetSource(
                origin=AssetOrigin.PACKAGE_INTERNAL.value,
                path=reference_value,
            ).normalized()

        return AssetSource(
            origin=AssetOrigin.LOCAL_FILE.value,
            path=reference_value,
        ).normalized()
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not build asset source: {exc}") from exc


def build_asset_target(
    *,
    role: str,
    reference: str,
    options: AssetPlanningOptions,
) -> Any:
    """Baut AssetTarget anhand von Rolle, Referenz und Zielstrategie."""
    try:
        from ..models.asset_reference import AssetTarget

        role_value = normalize_asset_role_value(role)
        reference_value = clean_required_string(reference, "reference")

        if options.target_strategy == AssetTargetStrategy.KEEP_INTERNAL_PATH.value and is_package_internal_path(reference_value):
            target_path = reference_value
        elif options.target_strategy == AssetTargetStrategy.PRESERVE_FILENAME.value:
            target_path = build_target_path_preserve_filename(role=role_value, reference=reference_value)
        else:
            target_path = build_target_path_canonical(role=role_value, reference=reference_value)

        return AssetTarget(
            package_path=target_path,
            module_name=infer_target_module_for_role(role_value),
            overwrite_allowed=options.target_strategy == AssetTargetStrategy.CANONICAL_ROLE_PATH.value,
        ).normalized()
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Could not build asset target: {exc}") from exc


def build_target_path_canonical(*, role: str, reference: str) -> str:
    """Baut kanonischen Zielpfad für eine Assetrolle."""
    role_value = normalize_asset_role_value(role)
    directory = ROLE_TARGET_DIRECTORIES.get(role_value, f"{DEFAULT_ASSET_TARGET_ROOT}/assets")
    filename = canonical_filename_for_role(role=role_value, reference=reference)
    return normalize_package_asset_path_safe(f"{directory}/{filename}")


def build_target_path_preserve_filename(*, role: str, reference: str) -> str:
    """Baut Zielpfad unter Rollenordner, erhält aber den Dateinamen."""
    role_value = normalize_asset_role_value(role)
    directory = ROLE_TARGET_DIRECTORIES.get(role_value, f"{DEFAULT_ASSET_TARGET_ROOT}/assets")
    filename = safe_filename_from_reference(reference) or ROLE_DEFAULT_FILENAMES.get(role_value, "asset.bin")
    return normalize_package_asset_path_safe(f"{directory}/{filename}")


def canonical_filename_for_role(*, role: str, reference: str) -> str:
    """Erzeugt kanonischen Dateinamen für eine Rolle."""
    role_value = normalize_asset_role_value(role)
    fallback = ROLE_DEFAULT_FILENAMES.get(role_value, "asset.bin")
    reference_extension = extension_from_reference(reference)
    fallback_extension = PurePosixPath(fallback).suffix

    if reference_extension and fallback_extension and reference_extension != fallback_extension:
        return f"{PurePosixPath(fallback).stem}{reference_extension}"

    return fallback


def safe_filename_from_reference(reference: str) -> str | None:
    """Extrahiert sicheren Dateinamen aus Referenz."""
    try:
        parsed = urlparse(str(reference).strip())
        path_value = parsed.path if parsed.scheme else str(reference).replace("\\", "/")
        filename = PurePosixPath(path_value).name

        if not filename or filename in {".", ".."}:
            return None

        return filename.replace(" ", "_")
    except Exception:
        return None


def extension_from_reference(reference: str) -> str:
    """Extrahiert Dateiendung aus Referenz."""
    filename = safe_filename_from_reference(reference)
    if not filename:
        return ""

    return PurePosixPath(filename).suffix.lower()


def build_asset_collection(assets: Iterable[Any]) -> Any:
    """Baut AssetReferenceCollection aus AssetReference-Werten."""
    try:
        from ..models.asset_reference import AssetReference, AssetReferenceCollection, asset_references_from_iterable

        asset_tuple = tuple(assets or ())
        if all(isinstance(asset, AssetReference) for asset in asset_tuple):
            return AssetReferenceCollection(assets=asset_tuple).normalized()

        return asset_references_from_iterable(asset_tuple).normalized()
    except Exception as exc:
        raise AssetPlannerError(f"Could not build asset collection: {exc}") from exc


def build_asset_copy_plans(
    *,
    asset_collection: Any,
    context: Any,
    options: AssetPlanningOptions,
) -> tuple[Any, ...]:
    """Baut PlannedAssetCopy-Einträge aus AssetReferences."""
    try:
        from ..models.package_plan import PlannedAssetCopy

        normalized_collection = normalize_asset_collection(asset_collection)
        normalized_context = normalize_package_context(context)
        normalized_options = options.normalized()

        if not normalized_options.plan_copy_for_local_assets:
            return tuple()

        copies: list[Any] = []

        for asset in normalized_collection.assets:
            if asset.source is None or asset.target is None:
                continue

            if asset.source.is_external:
                continue

            if asset.source.origin == "package_internal":
                continue

            copies.append(
                PlannedAssetCopy(
                    role=asset.role,
                    source_path=asset.source.path,
                    target_relative_path=asset.target.package_path,
                    target_absolute_path=normalized_context.package_dir / asset.target.package_path,
                    module_name=asset.target.module_name,
                    required=asset.required,
                    overwrite_allowed=asset.target.overwrite_allowed or normalized_context.may_overwrite,
                    asset_id=asset.asset_id,
                    mime_type=asset.mime_type,
                    reason="Asset copy planned by asset_planner.",
                ).normalized()
            )

        return tuple(copies)
    except Exception as exc:
        raise AssetPlannerError(f"Could not build asset copy plans: {exc}") from exc


def validate_asset_planning_parts(
    *,
    asset_collection: Any,
    asset_copies: Iterable[Any],
    decisions: Iterable[AssetPlanningDecision],
    options: AssetPlanningOptions,
) -> tuple[bool, tuple[str, ...]]:
    """Validiert AssetPlanningResult-Bestandteile."""
    messages: list[str] = []

    try:
        normalized_collection = normalize_asset_collection(asset_collection)
        collection_valid, collection_messages = normalized_collection.validate()
        if not collection_valid:
            messages.extend(collection_messages)

        asset_target_paths = set(normalized_collection.target_paths())

        for copy in asset_copies or ():
            normalized_copy = normalize_planned_asset_copy(copy)
            if normalized_copy.target_relative_path not in asset_target_paths:
                messages.append(
                    f"Asset copy target {normalized_copy.target_relative_path!r} "
                    "does not exist in asset collection targets."
                )

        for decision in decisions or ():
            decision.normalized()

        for decision in decisions or ():
            normalized_decision = decision.normalized()
            if normalized_decision.action == AssetPlanningAction.REQUIRE.value and options.strict:
                role_present = any(asset.role == normalized_decision.role for asset in normalized_collection.assets)
                if not role_present:
                    messages.append(f"Required asset role {normalized_decision.role!r} is missing.")

    except AssetPlannerError as exc:
        messages.append(str(exc))
    except Exception as exc:
        messages.append(f"Could not validate asset planning result: {exc}")

    return len(messages) == 0, tuple(messages)


def dedupe_decisions(
    decisions: Iterable[AssetPlanningDecision],
) -> tuple[AssetPlanningDecision, ...]:
    """Dedupliziert Entscheidungen."""
    result: list[AssetPlanningDecision] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()

    for decision in decisions or ():
        normalized = decision.normalized()
        key = (
            normalized.action,
            normalized.role,
            normalized.asset_id,
            normalized.target_path,
        )
        if key in seen:
            continue
        result.append(normalized)
        seen.add(key)

    return tuple(result)


def normalize_options(
    options: AssetPlanningOptions | Mapping[str, Any] | None,
) -> AssetPlanningOptions:
    """Normalisiert AssetPlanningOptions."""
    if options is None:
        return AssetPlanningOptions().normalized()

    if isinstance(options, AssetPlanningOptions):
        return options.normalized()

    if isinstance(options, Mapping):
        return AssetPlanningOptions(
            target_strategy=options.get("target_strategy", AssetTargetStrategy.CANONICAL_ROLE_PATH.value),
            allow_external_uri=bool(options.get("allow_external_uri", False)),
            allow_package_internal_refs=bool(options.get("allow_package_internal_refs", True)),
            require_declared_model_bounds=bool(options.get("require_declared_model_bounds", True)),
            plan_copy_for_local_assets=bool(options.get("plan_copy_for_local_assets", True)),
            validate_profile_rules=bool(options.get("validate_profile_rules", True)),
            strict=bool(options.get("strict", True)),
        ).normalized()

    raise AssetPlannerError("options must be AssetPlanningOptions, mapping or None.")


def normalize_create_request(value: Any) -> Any:
    """Normalisiert CreateRequest."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise AssetPlannerError("CreateRequest value is required.")
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Invalid CreateRequest: {exc}") from exc


def normalize_package_context(value: Any) -> Any:
    """Normalisiert PackageContext."""
    try:
        from ..models.package_context import PackageContext

        if isinstance(value, PackageContext):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise AssetPlannerError("PackageContext value is required.")
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Invalid PackageContext: {exc}") from exc


def normalize_profile(value: Any) -> Any:
    """Normalisiert ObjectKindProfile."""
    try:
        from ..profiles.base_profiles import ObjectKindProfile

        if isinstance(value, ObjectKindProfile):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise AssetPlannerError("ObjectKindProfile value is required.")
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Invalid ObjectKindProfile: {exc}") from exc


def normalize_asset_collection(value: Any) -> Any:
    """Normalisiert AssetReferenceCollection."""
    try:
        from ..models.asset_reference import AssetReferenceCollection, asset_references_from_iterable

        if isinstance(value, AssetReferenceCollection):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping)):
            return asset_references_from_iterable(value).normalized()

        raise AssetPlannerError("AssetReferenceCollection value is required.")
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Invalid AssetReferenceCollection: {exc}") from exc


def normalize_planned_asset_copy(value: Any) -> Any:
    """Normalisiert PlannedAssetCopy."""
    try:
        from ..models.package_plan import PlannedAssetCopy, planned_asset_copy_from_mapping

        if isinstance(value, PlannedAssetCopy):
            return value.normalized()

        if isinstance(value, Mapping):
            return planned_asset_copy_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise AssetPlannerError("PlannedAssetCopy value is required.")
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Invalid PlannedAssetCopy: {exc}") from exc


def normalize_asset_role_value(value: Any) -> str:
    """Normalisiert AssetRole."""
    try:
        from ..models.asset_reference import parse_asset_role_value

        return parse_asset_role_value(value)
    except Exception as exc:
        raise AssetPlannerError(f"Invalid asset role {value!r}: {exc}") from exc


def normalize_optional_asset_id(value: Any) -> str | None:
    """Normalisiert optionale Asset-ID."""
    if value is None:
        return None

    try:
        from ..models.asset_reference import normalize_asset_id

        return normalize_asset_id(value)
    except Exception:
        return clean_optional_string(value)


def infer_asset_id_from_path_safe(value: Any) -> str:
    """Leitet Asset-ID aus Pfad ab."""
    try:
        from ..models.asset_reference import infer_asset_id_from_path

        return infer_asset_id_from_path(value)
    except Exception:
        filename = safe_filename_from_reference(str(value)) or "asset"
        return PurePosixPath(filename).stem.lower().replace(" ", "_").replace("-", "_")


def infer_asset_type_for_role(role: Any, reference: Any) -> str:
    """Leitet AssetType aus Rolle und Referenz ab."""
    role_value = normalize_asset_role_value(role)

    if role_value in {"glb_model", "gltf_model", "lod_model"}:
        return "model"

    if role_value in {"texture", "material_texture"}:
        return "texture"

    if role_value in {"icon", "preview"}:
        return "image"

    if role_value == "documentation":
        return "document"

    if role_value == "test_fixture":
        return "data"

    try:
        from ..models.asset_reference import infer_asset_type_from_extension

        return infer_asset_type_from_extension(extension_from_reference(str(reference)), default="unknown")
    except Exception:
        return "unknown"


def infer_target_module_for_role(role: Any) -> str:
    """Leitet Zielmodul aus AssetRole ab."""
    role_value = normalize_asset_role_value(role)

    if role_value in {
        "icon",
        "preview",
        "texture",
        "material_texture",
        "glb_model",
        "gltf_model",
        "lod_model",
        "other",
    }:
        return "render"

    if role_value == "documentation":
        return "docs"

    if role_value == "test_fixture":
        return "tests"

    return DEFAULT_RENDER_MODULE_NAME


def normalize_package_asset_path_safe(value: Any) -> str:
    """Normalisiert package-internen Assetpfad."""
    try:
        from ..models.asset_reference import normalize_package_asset_path

        return normalize_package_asset_path(value)
    except Exception as exc:
        raise AssetPlannerError(f"Invalid package asset path {value!r}: {exc}") from exc


def is_package_internal_path(value: Any) -> bool:
    """Prüft, ob ein Pfad bereits package-intern wirkt."""
    try:
        raw = str(value).strip().replace("\\", "/")
        if is_external_uri(raw):
            return False
        return raw.startswith(
            (
                "render/",
                "docs/",
                "tests/",
                "family/",
                "variants/",
                "editor/",
                "physical/",
                "material/",
                "calculation/",
                "analysis/",
                "dynamic/",
                "manufacturer/",
            )
        )
    except Exception:
        return False


def is_external_uri(value: Any) -> bool:
    """Prüft HTTP/HTTPS URI."""
    try:
        parsed = urlparse(str(value).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


@lru_cache(maxsize=128)
def parse_asset_planning_source_value(value: Any) -> str:
    """Parst AssetPlanningSource."""
    try:
        if isinstance(value, AssetPlanningSource):
            return value.value

        raw = normalize_enum_key(value)
        return AssetPlanningSource(raw).value
    except Exception as exc:
        raise AssetPlannerError(f"Invalid asset planning source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_asset_planning_action_value(value: Any) -> str:
    """Parst AssetPlanningAction."""
    try:
        if isinstance(value, AssetPlanningAction):
            return value.value

        raw = normalize_enum_key(value)
        return AssetPlanningAction(raw).value
    except Exception as exc:
        raise AssetPlannerError(f"Invalid asset planning action {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_target_strategy_value(value: Any) -> str:
    """Parst AssetTargetStrategy."""
    try:
        if isinstance(value, AssetTargetStrategy):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "preserve": AssetTargetStrategy.PRESERVE_FILENAME.value,
            "preserve_filename": AssetTargetStrategy.PRESERVE_FILENAME.value,
            "canonical": AssetTargetStrategy.CANONICAL_ROLE_PATH.value,
            "canonical_role_path": AssetTargetStrategy.CANONICAL_ROLE_PATH.value,
            "keep": AssetTargetStrategy.KEEP_INTERNAL_PATH.value,
            "keep_internal": AssetTargetStrategy.KEEP_INTERNAL_PATH.value,
            "keep_internal_path": AssetTargetStrategy.KEEP_INTERNAL_PATH.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetTargetStrategy(raw).value
    except Exception as exc:
        raise AssetPlannerError(f"Invalid asset target strategy {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise AssetPlannerError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"Invalid enum value {value!r}.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise AssetPlannerError(f"{field_name} is required.")

        return cleaned
    except AssetPlannerError:
        raise
    except Exception as exc:
        raise AssetPlannerError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise AssetPlannerError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert Metadata-Werte JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def clear_asset_planner_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_asset_planning_source_value.cache_clear()
    parse_asset_planning_action_value.cache_clear()
    parse_target_strategy_value.cache_clear()


__all__ = [
    "ASSET_PLANNER_SCHEMA_VERSION",
    "DEFAULT_ASSET_TARGET_ROOT",
    "DEFAULT_RENDER_MODULE_NAME",
    "ROLE_DEFAULT_FILENAMES",
    "ROLE_TARGET_DIRECTORIES",
    "AssetPlannerError",
    "AssetPlanningAction",
    "AssetPlanningDecision",
    "AssetPlanningOptions",
    "AssetPlanningResult",
    "AssetPlanningSource",
    "AssetTargetStrategy",
    "build_asset_collection",
    "build_asset_copy_plans",
    "build_asset_reference_from_request_asset",
    "build_asset_reference_from_visual_ref",
    "build_asset_source",
    "build_asset_target",
    "build_target_path_canonical",
    "build_target_path_preserve_filename",
    "canonical_filename_for_role",
    "clean_optional_string",
    "clean_required_string",
    "clear_asset_planner_caches",
    "collect_explicit_assets_from_request",
    "collect_profile_asset_decisions",
    "collect_visual_assets_from_request",
    "dedupe_decisions",
    "extension_from_reference",
    "infer_asset_id_from_path_safe",
    "infer_asset_type_for_role",
    "infer_target_module_for_role",
    "is_external_uri",
    "is_package_internal_path",
    "normalize_asset_collection",
    "normalize_asset_role_value",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_options",
    "normalize_optional_asset_id",
    "normalize_package_asset_path_safe",
    "normalize_package_context",
    "normalize_planned_asset_copy",
    "normalize_profile",
    "parse_asset_planning_action_value",
    "parse_asset_planning_source_value",
    "parse_target_strategy_value",
    "plan_assets_for_request",
    "plan_assets_from_references",
    "safe_filename_from_reference",
    "validate_asset_planning_parts",
]