# services/vectoplan-library/src/vplib/models/asset_reference.py
"""
AssetReference model for the VPLIB package engine.

Diese Datei beschreibt Asset-Referenzen für modulare VPLIB-Packages.

Rolle dieser Datei:

    CreateRequest.assets / render metadata
    -> AssetReference
    -> asset planning
    -> asset copy plan
    -> asset validation
    -> render document generation

Diese Datei kopiert keine Dateien und liest keine GLB-Geometrie. Sie definiert
nur robuste, normalisierte Asset-Metadaten.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable, Mapping
from urllib.parse import urlparse


ASSET_REFERENCE_SCHEMA_VERSION: Final[str] = "vplib.asset_reference.v1"

DEFAULT_RENDER_MODULE_NAME: Final[str] = "render"

SAFE_ASSET_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_HEX_COLOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)

URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class AssetReferenceError(ValueError):
    """Wird ausgelöst, wenn eine Asset-Referenz ungültig ist."""


class AssetRole(str, Enum):
    """Fachliche Rolle eines Assets im VPLIB-Package."""

    ICON = "icon"
    PREVIEW = "preview"
    TEXTURE = "texture"
    MATERIAL_TEXTURE = "material_texture"
    GLB_MODEL = "glb_model"
    GLTF_MODEL = "gltf_model"
    LOD_MODEL = "lod_model"
    DOCUMENTATION = "documentation"
    TEST_FIXTURE = "test_fixture"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetType(str, Enum):
    """Technischer Asset-Typ."""

    IMAGE = "image"
    TEXTURE = "texture"
    MODEL = "model"
    DOCUMENT = "document"
    DATA = "data"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetOrigin(str, Enum):
    """Herkunft eines Assets."""

    LOCAL_FILE = "local_file"
    PACKAGE_INTERNAL = "package_internal"
    GENERATED = "generated"
    EXTERNAL_URI = "external_uri"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetReferenceStatus(str, Enum):
    """Status einer Asset-Referenz im Planungsprozess."""

    PLANNED = "planned"
    AVAILABLE = "available"
    MISSING = "missing"
    COPIED = "copied"
    SKIPPED = "skipped"
    INVALID = "invalid"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AssetBounds3D:
    """Deklarierte 3D-Bounds eines Assets in Metern."""

    width_m: float
    height_m: float
    depth_m: float

    def normalized(self) -> "AssetBounds3D":
        return AssetBounds3D(
            width_m=normalize_positive_float(self.width_m, "width_m"),
            height_m=normalize_positive_float(self.height_m, "height_m"),
            depth_m=normalize_positive_float(self.depth_m, "depth_m"),
        )

    def fits_inside_size_m(self, size_m: tuple[float, float, float]) -> bool:
        """Prüft, ob die Bounds in eine gegebene Metergröße passen."""
        normalized = self.normalized()

        try:
            max_width, max_height, max_depth = (
                float(size_m[0]),
                float(size_m[1]),
                float(size_m[2]),
            )
        except Exception as exc:
            raise AssetReferenceError(f"Invalid size_m tuple {size_m!r}.") from exc

        return (
            normalized.width_m <= max_width
            and normalized.height_m <= max_height
            and normalized.depth_m <= max_depth
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "width_m": normalized.width_m,
            "height_m": normalized.height_m,
            "depth_m": normalized.depth_m,
        }


@dataclass(frozen=True, slots=True)
class AssetSource:
    """Quelle eines Assets."""

    origin: str
    path: str
    exists: bool | None = None
    allow_external_uri: bool = False

    def normalized(self) -> "AssetSource":
        origin = parse_asset_origin_value(self.origin)
        path = clean_required_string(self.path, "path")
        exists = self.exists if self.exists is None else bool(self.exists)
        allow_external_uri = bool(self.allow_external_uri)

        if origin == AssetOrigin.EXTERNAL_URI.value:
            if not allow_external_uri:
                raise AssetReferenceError("External asset URIs are disabled for this source.")

            if not is_safe_external_uri(path):
                raise AssetReferenceError(f"Unsafe external asset URI {path!r}.")

        if origin in {
            AssetOrigin.LOCAL_FILE.value,
            AssetOrigin.PACKAGE_INTERNAL.value,
            AssetOrigin.GENERATED.value,
        }:
            validate_not_external_uri(path)

        return AssetSource(
            origin=origin,
            path=path,
            exists=exists,
            allow_external_uri=allow_external_uri,
        )

    @property
    def is_external(self) -> bool:
        return self.normalized().origin == AssetOrigin.EXTERNAL_URI.value

    @property
    def is_local_file(self) -> bool:
        return self.normalized().origin == AssetOrigin.LOCAL_FILE.value

    @property
    def path_obj(self) -> Path | None:
        normalized = self.normalized()

        if normalized.is_external:
            return None

        return Path(normalized.path).expanduser()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "origin": normalized.origin,
            "path": normalized.path,
            "exists": normalized.exists,
            "allow_external_uri": normalized.allow_external_uri,
        }


@dataclass(frozen=True, slots=True)
class AssetTarget:
    """Ziel eines Assets innerhalb des VPLIB-Packages."""

    package_path: str
    module_name: str = DEFAULT_RENDER_MODULE_NAME
    overwrite_allowed: bool = False

    def normalized(self) -> "AssetTarget":
        package_path = normalize_package_asset_path(self.package_path)
        module_name = normalize_module_name(self.module_name)
        overwrite_allowed = bool(self.overwrite_allowed)

        if not is_path_under_module_safe(package_path, module_name):
            raise AssetReferenceError(
                f"Asset target path {package_path!r} is not under module {module_name!r}."
            )

        return AssetTarget(
            package_path=package_path,
            module_name=module_name,
            overwrite_allowed=overwrite_allowed,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "package_path": normalized.package_path,
            "module_name": normalized.module_name,
            "overwrite_allowed": normalized.overwrite_allowed,
        }


@dataclass(frozen=True, slots=True)
class AssetReference:
    """
    Vollständige Asset-Referenz.

    target ist optional, weil eine Referenz auch auf ein bereits internes Package-
    Asset zeigen kann. Für geplante Kopien sollte target gesetzt sein.
    """

    asset_id: str
    role: str
    asset_type: str
    source: AssetSource | None = None
    target: AssetTarget | None = None
    label: str | None = None
    mime_type: str | None = None
    file_extension: str | None = None
    file_size_bytes: int | None = None
    checksum: str | None = None
    bounds_m: AssetBounds3D | None = None
    fallback_color: str | None = None
    required: bool = False
    status: str = AssetReferenceStatus.PLANNED.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AssetReference":
        asset_id = normalize_asset_id(self.asset_id)
        role = parse_asset_role_value(self.role)
        asset_type = parse_asset_type_value(self.asset_type)
        source = self.source.normalized() if self.source is not None else None
        target = self.target.normalized() if self.target is not None else None
        label = clean_optional_string(self.label)
        mime_type = clean_optional_string(self.mime_type)
        file_extension = normalize_file_extension(
            self.file_extension
            or infer_extension_from_reference(source=source, target=target)
        )
        file_size_bytes = normalize_optional_non_negative_int(
            self.file_size_bytes,
            "file_size_bytes",
        )
        checksum = clean_optional_string(self.checksum)
        bounds_m = self.bounds_m.normalized() if self.bounds_m is not None else None
        fallback_color = normalize_optional_color(self.fallback_color)
        required = bool(self.required)
        status = parse_asset_reference_status_value(self.status)
        metadata = dict(self.metadata or {})

        inferred_type = infer_asset_type_from_extension(file_extension, default=asset_type)
        if asset_type == AssetType.UNKNOWN.value and inferred_type != AssetType.UNKNOWN.value:
            asset_type = inferred_type

        validate_role_type_compatibility(role=role, asset_type=asset_type)
        validate_asset_extension_for_type(file_extension=file_extension, asset_type=asset_type)

        if role in {AssetRole.TEXTURE.value, AssetRole.MATERIAL_TEXTURE.value} and not target and not source:
            raise AssetReferenceError(f"Asset role {role!r} requires a source or target.")

        if role in {AssetRole.GLB_MODEL.value, AssetRole.GLTF_MODEL.value, AssetRole.LOD_MODEL.value}:
            if bounds_m is None:
                raise AssetReferenceError(f"Model asset {asset_id!r} requires declared bounds_m.")
            if file_extension not in {".glb", ".gltf"}:
                raise AssetReferenceError(
                    f"Model asset {asset_id!r} must use .glb or .gltf, got {file_extension!r}."
                )

        return AssetReference(
            asset_id=asset_id,
            role=role,
            asset_type=asset_type,
            source=source,
            target=target,
            label=label,
            mime_type=mime_type or infer_mime_type(file_extension),
            file_extension=file_extension,
            file_size_bytes=file_size_bytes,
            checksum=checksum,
            bounds_m=bounds_m,
            fallback_color=fallback_color,
            required=required,
            status=status,
            metadata=metadata,
        )

    @property
    def is_model(self) -> bool:
        return self.normalized().asset_type == AssetType.MODEL.value

    @property
    def is_image(self) -> bool:
        return self.normalized().asset_type == AssetType.IMAGE.value

    @property
    def is_texture(self) -> bool:
        return self.normalized().asset_type == AssetType.TEXTURE.value

    @property
    def is_required(self) -> bool:
        return self.normalized().required

    @property
    def package_path(self) -> str | None:
        normalized = self.normalized()
        return normalized.target.package_path if normalized.target else None

    def with_status(self, status: str) -> "AssetReference":
        normalized = self.normalized()

        return AssetReference(
            asset_id=normalized.asset_id,
            role=normalized.role,
            asset_type=normalized.asset_type,
            source=normalized.source,
            target=normalized.target,
            label=normalized.label,
            mime_type=normalized.mime_type,
            file_extension=normalized.file_extension,
            file_size_bytes=normalized.file_size_bytes,
            checksum=normalized.checksum,
            bounds_m=normalized.bounds_m,
            fallback_color=normalized.fallback_color,
            required=normalized.required,
            status=parse_asset_reference_status_value(status),
            metadata=dict(normalized.metadata),
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": ASSET_REFERENCE_SCHEMA_VERSION,
            "asset_id": normalized.asset_id,
            "role": normalized.role,
            "asset_type": normalized.asset_type,
            "source": normalized.source.to_dict() if normalized.source else None,
            "target": normalized.target.to_dict() if normalized.target else None,
            "label": normalized.label,
            "mime_type": normalized.mime_type,
            "file_extension": normalized.file_extension,
            "file_size_bytes": normalized.file_size_bytes,
            "checksum": normalized.checksum,
            "bounds_m": normalized.bounds_m.to_dict() if normalized.bounds_m else None,
            "fallback_color": normalized.fallback_color,
            "required": normalized.required,
            "status": normalized.status,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class AssetReferenceCollection:
    """Sammlung von Asset-Referenzen."""

    assets: tuple[AssetReference, ...] = field(default_factory=tuple)

    def normalized(self) -> "AssetReferenceCollection":
        normalized_assets = tuple(asset.normalized() for asset in self.assets or ())
        by_id: dict[str, AssetReference] = {}

        for asset in normalized_assets:
            existing = by_id.get(asset.asset_id)
            if existing is not None:
                raise AssetReferenceError(f"Duplicate asset_id {asset.asset_id!r}.")
            by_id[asset.asset_id] = asset

        return AssetReferenceCollection(
            assets=tuple(by_id[asset_id] for asset_id in sorted(by_id.keys()))
        )

    def by_role(self, role: Any) -> tuple[AssetReference, ...]:
        role_value = parse_asset_role_value(role)

        return tuple(
            asset
            for asset in self.normalized().assets
            if asset.role == role_value
        )

    def by_type(self, asset_type: Any) -> tuple[AssetReference, ...]:
        type_value = parse_asset_type_value(asset_type)

        return tuple(
            asset
            for asset in self.normalized().assets
            if asset.asset_type == type_value
        )

    def required_assets(self) -> tuple[AssetReference, ...]:
        return tuple(asset for asset in self.normalized().assets if asset.required)

    def optional_assets(self) -> tuple[AssetReference, ...]:
        return tuple(asset for asset in self.normalized().assets if not asset.required)

    def target_paths(self) -> tuple[str, ...]:
        return tuple(
            asset.package_path
            for asset in self.normalized().assets
            if asset.package_path is not None
        )

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        messages: list[str] = []

        try:
            normalized = self.normalized()
            target_paths: set[str] = set()

            for asset in normalized.assets:
                if asset.target:
                    if asset.target.package_path in target_paths:
                        messages.append(
                            f"Duplicate asset target path {asset.target.package_path!r}."
                        )
                    target_paths.add(asset.target.package_path)

                if asset.required and asset.status in {
                    AssetReferenceStatus.MISSING.value,
                    AssetReferenceStatus.INVALID.value,
                }:
                    messages.append(
                        f"Required asset {asset.asset_id!r} has invalid status {asset.status!r}."
                    )
        except AssetReferenceError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate asset collection: {exc}")

        return len(messages) == 0, tuple(messages)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": ASSET_REFERENCE_SCHEMA_VERSION,
            "assets": [asset.to_dict() for asset in normalized.assets],
        }


def asset_reference_from_mapping(data: Mapping[str, Any]) -> AssetReference:
    """Baut eine AssetReference aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise AssetReferenceError("AssetReference data must be a mapping.")

        source_data = data.get("source")
        target_data = data.get("target")
        bounds_data = data.get("bounds_m") or data.get("model_bounds_m")

        source = asset_source_from_mapping(source_data) if isinstance(source_data, Mapping) else None
        target = asset_target_from_mapping(target_data) if isinstance(target_data, Mapping) else None
        bounds_m = asset_bounds_from_mapping(bounds_data) if isinstance(bounds_data, Mapping) else None

        return AssetReference(
            asset_id=data.get("asset_id") or data.get("id") or infer_asset_id_from_mapping(data),
            role=data.get("role") or infer_role_from_mapping(data),
            asset_type=data.get("asset_type") or data.get("type") or infer_asset_type_from_mapping(data),
            source=source,
            target=target,
            label=data.get("label"),
            mime_type=data.get("mime_type"),
            file_extension=data.get("file_extension"),
            file_size_bytes=data.get("file_size_bytes"),
            checksum=data.get("checksum"),
            bounds_m=bounds_m,
            fallback_color=data.get("fallback_color"),
            required=bool(data.get("required", False)),
            status=data.get("status", AssetReferenceStatus.PLANNED.value),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"Could not build AssetReference from mapping: {exc}") from exc


def asset_source_from_mapping(data: Mapping[str, Any]) -> AssetSource:
    """Baut eine AssetSource aus einem Mapping."""
    try:
        return AssetSource(
            origin=data.get("origin", AssetOrigin.LOCAL_FILE.value),
            path=data.get("path") or data.get("source_path"),
            exists=data.get("exists"),
            allow_external_uri=bool(data.get("allow_external_uri", False)),
        ).normalized()
    except Exception as exc:
        raise AssetReferenceError(f"Could not build AssetSource: {exc}") from exc


def asset_target_from_mapping(data: Mapping[str, Any]) -> AssetTarget:
    """Baut ein AssetTarget aus einem Mapping."""
    try:
        return AssetTarget(
            package_path=data.get("package_path") or data.get("target_path"),
            module_name=data.get("module_name", DEFAULT_RENDER_MODULE_NAME),
            overwrite_allowed=bool(data.get("overwrite_allowed", False)),
        ).normalized()
    except Exception as exc:
        raise AssetReferenceError(f"Could not build AssetTarget: {exc}") from exc


def asset_bounds_from_mapping(data: Mapping[str, Any]) -> AssetBounds3D:
    """Baut AssetBounds3D aus einem Mapping."""
    try:
        return AssetBounds3D(
            width_m=data.get("width_m", data.get("width")),
            height_m=data.get("height_m", data.get("height")),
            depth_m=data.get("depth_m", data.get("depth")),
        ).normalized()
    except Exception as exc:
        raise AssetReferenceError(f"Could not build AssetBounds3D: {exc}") from exc


def asset_references_from_iterable(values: Iterable[Any]) -> AssetReferenceCollection:
    """Baut eine AssetReferenceCollection aus mehreren Mapping-/Asset-Werten."""
    assets: list[AssetReference] = []

    for value in values or ():
        if isinstance(value, AssetReference):
            assets.append(value.normalized())
            continue

        if isinstance(value, Mapping):
            assets.append(asset_reference_from_mapping(value))
            continue

        raise AssetReferenceError(f"Unsupported asset reference value {value!r}.")

    return AssetReferenceCollection(assets=tuple(assets)).normalized()


def asset_reference_from_create_asset_request(value: Any) -> AssetReference:
    """
    Baut eine AssetReference aus einem CreateRequest.AssetRequest-ähnlichen Objekt.

    Diese Funktion nutzt Duck-Typing, damit kein harter Importzyklus entsteht.
    """
    try:
        normalized = value.normalized() if hasattr(value, "normalized") else value

        role = getattr(normalized, "role", None)
        source_path = getattr(normalized, "source_path", None)
        target_path = getattr(normalized, "target_path", None)
        asset_id = getattr(normalized, "asset_id", None)
        mime_type = getattr(normalized, "mime_type", None)

        if not role or not source_path:
            raise AssetReferenceError("Create asset request requires role and source_path.")

        inferred_type = infer_asset_type_from_extension(
            normalize_file_extension(PurePosixPath(str(source_path)).suffix),
            default=AssetType.UNKNOWN.value,
        )

        source = AssetSource(
            origin=AssetOrigin.LOCAL_FILE.value,
            path=str(source_path),
        ).normalized()

        target = (
            AssetTarget(
                package_path=target_path,
                module_name=infer_target_module_from_role(role),
            ).normalized()
            if target_path
            else None
        )

        return AssetReference(
            asset_id=asset_id or infer_asset_id_from_path(source_path),
            role=role,
            asset_type=inferred_type,
            source=source,
            target=target,
            mime_type=mime_type,
        ).normalized()
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"Could not build asset reference from create request: {exc}") from exc


def infer_asset_id_from_mapping(data: Mapping[str, Any]) -> str:
    """Leitet eine Asset-ID aus Mappingdaten ab."""
    for key in ("target_path", "package_path", "source_path", "path", "glb_ref", "texture_ref", "icon_ref", "preview_ref"):
        value = data.get(key)
        if value:
            return infer_asset_id_from_path(value)

    return "asset"


def infer_asset_id_from_path(value: Any) -> str:
    """Leitet eine sichere Asset-ID aus einem Pfad ab."""
    raw_name = PurePosixPath(str(value).replace("\\", "/")).stem or "asset"
    candidate = (
        raw_name.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
    )
    return normalize_asset_id(candidate)


def infer_role_from_mapping(data: Mapping[str, Any]) -> str:
    """Leitet eine Asset-Rolle aus Mappingdaten ab."""
    for key, role in (
        ("icon_ref", AssetRole.ICON.value),
        ("preview_ref", AssetRole.PREVIEW.value),
        ("texture_ref", AssetRole.TEXTURE.value),
        ("glb_ref", AssetRole.GLB_MODEL.value),
        ("model_ref", AssetRole.GLB_MODEL.value),
    ):
        if data.get(key):
            return role

    return AssetRole.OTHER.value


def infer_asset_type_from_mapping(data: Mapping[str, Any]) -> str:
    """Leitet einen Asset-Typ aus Mappingdaten ab."""
    for key in ("file_extension", "target_path", "package_path", "source_path", "path", "glb_ref", "texture_ref", "icon_ref", "preview_ref"):
        value = data.get(key)
        if not value:
            continue

        extension = normalize_file_extension(PurePosixPath(str(value).replace("\\", "/")).suffix)
        inferred = infer_asset_type_from_extension(extension, default=AssetType.UNKNOWN.value)
        if inferred != AssetType.UNKNOWN.value:
            return inferred

    return AssetType.UNKNOWN.value


@lru_cache(maxsize=256)
def parse_asset_role_value(value: Any) -> str:
    """Parst eine AssetRole."""
    try:
        if isinstance(value, AssetRole):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "icon": AssetRole.ICON.value,
            "thumbnail": AssetRole.PREVIEW.value,
            "preview": AssetRole.PREVIEW.value,
            "texture": AssetRole.TEXTURE.value,
            "material_texture": AssetRole.MATERIAL_TEXTURE.value,
            "material": AssetRole.MATERIAL_TEXTURE.value,
            "glb": AssetRole.GLB_MODEL.value,
            "glb_model": AssetRole.GLB_MODEL.value,
            "model": AssetRole.GLB_MODEL.value,
            "gltf": AssetRole.GLTF_MODEL.value,
            "gltf_model": AssetRole.GLTF_MODEL.value,
            "lod": AssetRole.LOD_MODEL.value,
            "lod_model": AssetRole.LOD_MODEL.value,
            "doc": AssetRole.DOCUMENTATION.value,
            "docs": AssetRole.DOCUMENTATION.value,
            "documentation": AssetRole.DOCUMENTATION.value,
            "fixture": AssetRole.TEST_FIXTURE.value,
            "test_fixture": AssetRole.TEST_FIXTURE.value,
            "other": AssetRole.OTHER.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetRole(raw).value
    except Exception as exc:
        raise AssetReferenceError(f"Invalid asset role {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_asset_type_value(value: Any) -> str:
    """Parst einen AssetType."""
    try:
        if isinstance(value, AssetType):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "image": AssetType.IMAGE.value,
            "img": AssetType.IMAGE.value,
            "texture": AssetType.TEXTURE.value,
            "tex": AssetType.TEXTURE.value,
            "model": AssetType.MODEL.value,
            "mesh": AssetType.MODEL.value,
            "3d": AssetType.MODEL.value,
            "document": AssetType.DOCUMENT.value,
            "doc": AssetType.DOCUMENT.value,
            "data": AssetType.DATA.value,
            "json": AssetType.DATA.value,
            "unknown": AssetType.UNKNOWN.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetType(raw).value
    except Exception as exc:
        raise AssetReferenceError(f"Invalid asset type {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_asset_origin_value(value: Any) -> str:
    """Parst einen AssetOrigin."""
    try:
        if isinstance(value, AssetOrigin):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "local": AssetOrigin.LOCAL_FILE.value,
            "local_file": AssetOrigin.LOCAL_FILE.value,
            "file": AssetOrigin.LOCAL_FILE.value,
            "package": AssetOrigin.PACKAGE_INTERNAL.value,
            "package_internal": AssetOrigin.PACKAGE_INTERNAL.value,
            "internal": AssetOrigin.PACKAGE_INTERNAL.value,
            "generated": AssetOrigin.GENERATED.value,
            "external": AssetOrigin.EXTERNAL_URI.value,
            "external_uri": AssetOrigin.EXTERNAL_URI.value,
            "url": AssetOrigin.EXTERNAL_URI.value,
            "uri": AssetOrigin.EXTERNAL_URI.value,
        }

        if raw in aliases:
            return aliases[raw]

        return AssetOrigin(raw).value
    except Exception as exc:
        raise AssetReferenceError(f"Invalid asset origin {value!r}.") from exc


@lru_cache(maxsize=256)
def parse_asset_reference_status_value(value: Any) -> str:
    """Parst einen AssetReferenceStatus."""
    try:
        if isinstance(value, AssetReferenceStatus):
            return value.value

        raw = normalize_enum_key(value)
        return AssetReferenceStatus(raw).value
    except Exception as exc:
        raise AssetReferenceError(f"Invalid asset reference status {value!r}.") from exc


def validate_role_type_compatibility(*, role: str, asset_type: str) -> None:
    """Prüft grobe Kompatibilität von Asset-Rolle und Asset-Typ."""
    role_value = parse_asset_role_value(role)
    type_value = parse_asset_type_value(asset_type)

    expected_types = {
        AssetRole.ICON.value: {AssetType.IMAGE.value},
        AssetRole.PREVIEW.value: {AssetType.IMAGE.value},
        AssetRole.TEXTURE.value: {AssetType.TEXTURE.value, AssetType.IMAGE.value},
        AssetRole.MATERIAL_TEXTURE.value: {AssetType.TEXTURE.value, AssetType.IMAGE.value},
        AssetRole.GLB_MODEL.value: {AssetType.MODEL.value},
        AssetRole.GLTF_MODEL.value: {AssetType.MODEL.value},
        AssetRole.LOD_MODEL.value: {AssetType.MODEL.value},
        AssetRole.DOCUMENTATION.value: {AssetType.DOCUMENT.value, AssetType.DATA.value},
        AssetRole.TEST_FIXTURE.value: {AssetType.DATA.value, AssetType.DOCUMENT.value},
        AssetRole.OTHER.value: {
            AssetType.IMAGE.value,
            AssetType.TEXTURE.value,
            AssetType.MODEL.value,
            AssetType.DOCUMENT.value,
            AssetType.DATA.value,
            AssetType.UNKNOWN.value,
        },
    }

    allowed = expected_types.get(role_value, {AssetType.UNKNOWN.value})
    if type_value not in allowed and type_value != AssetType.UNKNOWN.value:
        raise AssetReferenceError(
            f"Asset role {role_value!r} is not compatible with asset type {type_value!r}."
        )


def validate_asset_extension_for_type(*, file_extension: str, asset_type: str) -> None:
    """Prüft grobe Kompatibilität von Dateiendung und Asset-Typ."""
    extension = normalize_file_extension(file_extension)
    type_value = parse_asset_type_value(asset_type)

    if not extension:
        raise AssetReferenceError("Asset file extension is required.")

    if extension in get_forbidden_extensions_safe():
        raise AssetReferenceError(f"Forbidden asset file extension {extension!r}.")

    allowed_by_type = {
        AssetType.IMAGE.value: {".svg", ".png", ".jpg", ".jpeg", ".webp"},
        AssetType.TEXTURE.value: {".svg", ".png", ".jpg", ".jpeg", ".webp", ".ktx2", ".basis"},
        AssetType.MODEL.value: {".glb", ".gltf"},
        AssetType.DOCUMENT.value: {".md", ".txt", ".json"},
        AssetType.DATA.value: {".json", ".txt"},
        AssetType.UNKNOWN.value: get_allowed_extensions_safe(),
    }

    allowed = allowed_by_type.get(type_value, set())
    if extension not in allowed:
        raise AssetReferenceError(
            f"Asset extension {extension!r} is not compatible with asset type {type_value!r}."
        )


def infer_asset_type_from_extension(
    extension: str | None,
    *,
    default: str = AssetType.UNKNOWN.value,
) -> str:
    """Leitet AssetType aus Dateiendung ab."""
    normalized = normalize_file_extension(extension)

    if normalized in {".svg", ".png", ".jpg", ".jpeg", ".webp"}:
        return AssetType.IMAGE.value

    if normalized in {".ktx2", ".basis"}:
        return AssetType.TEXTURE.value

    if normalized in {".glb", ".gltf"}:
        return AssetType.MODEL.value

    if normalized in {".md", ".txt"}:
        return AssetType.DOCUMENT.value

    if normalized == ".json":
        return AssetType.DATA.value

    return parse_asset_type_value(default)


def infer_mime_type(extension: str | None) -> str | None:
    """Leitet MIME-Type aus Dateiendung ab."""
    normalized = normalize_file_extension(extension)

    return {
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".ktx2": "image/ktx2",
        ".basis": "image/ktx2",
        ".glb": "model/gltf-binary",
        ".gltf": "model/gltf+json",
        ".json": "application/json",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }.get(normalized)


def infer_target_module_from_role(role: Any) -> str:
    """Leitet Zielmodul aus Asset-Rolle ab."""
    role_value = parse_asset_role_value(role)

    if role_value in {
        AssetRole.ICON.value,
        AssetRole.PREVIEW.value,
        AssetRole.TEXTURE.value,
        AssetRole.MATERIAL_TEXTURE.value,
        AssetRole.GLB_MODEL.value,
        AssetRole.GLTF_MODEL.value,
        AssetRole.LOD_MODEL.value,
    }:
        return "render"

    if role_value == AssetRole.DOCUMENTATION.value:
        return "docs"

    if role_value == AssetRole.TEST_FIXTURE.value:
        return "tests"

    return DEFAULT_RENDER_MODULE_NAME


def infer_extension_from_reference(
    *,
    source: AssetSource | None,
    target: AssetTarget | None,
) -> str:
    """Leitet Dateiendung aus Source oder Target ab."""
    if target is not None:
        extension = PurePosixPath(target.package_path).suffix
        if extension:
            return normalize_file_extension(extension)

    if source is not None:
        parsed_url = urlparse(source.path)
        path_value = parsed_url.path if parsed_url.scheme else source.path
        extension = PurePosixPath(path_value.replace("\\", "/")).suffix
        if extension:
            return normalize_file_extension(extension)

    return ""


def normalize_asset_id(value: Any) -> str:
    """Normalisiert eine Asset-ID."""
    raw = clean_required_string(value, "asset_id")
    asset_id = raw.lower().replace(" ", "_").replace("-", "_")

    if not SAFE_ASSET_ID_RE.match(asset_id):
        raise AssetReferenceError(f"Invalid asset_id {value!r}.")

    return asset_id


def normalize_file_extension(value: Any) -> str:
    """Normalisiert eine Dateiendung."""
    if value is None:
        return ""

    extension = str(value).strip().lower()
    if not extension:
        return ""

    if not extension.startswith("."):
        extension = f".{extension}"

    return extension


def normalize_optional_color(value: Any) -> str | None:
    """Normalisiert eine optionale Hex-Farbe."""
    if value is None:
        return None

    color = str(value).strip()

    if not color:
        return None

    if not SAFE_HEX_COLOR_RE.match(color):
        raise AssetReferenceError(f"Invalid fallback color {value!r}.")

    return color


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert eine positive Zahl."""
    try:
        if isinstance(value, bool):
            raise AssetReferenceError(f"{field_name} must be a number.")

        number = float(value)
        if number <= 0:
            raise AssetReferenceError(f"{field_name} must be > 0.")

        return number
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"{field_name} must be a positive number.") from exc


def normalize_optional_non_negative_int(value: Any, field_name: str) -> int | None:
    """Normalisiert einen optionalen nicht-negativen Integer."""
    if value is None:
        return None

    try:
        if isinstance(value, bool):
            raise AssetReferenceError(f"{field_name} must be an integer.")

        number = int(value)
        if number < 0:
            raise AssetReferenceError(f"{field_name} must be >= 0.")

        return number
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"{field_name} must be a non-negative integer.") from exc


def normalize_package_asset_path(value: Any) -> str:
    """Normalisiert einen Package-internen Assetpfad."""
    try:
        from ..domain.package_paths import assert_safe_package_file_path, normalize_package_path

        path = normalize_package_path(value)
        assert_safe_package_file_path(path)
        return path
    except Exception as exc:
        raise AssetReferenceError(f"Invalid package asset path {value!r}: {exc}") from exc


def normalize_module_name(value: Any) -> str:
    """Normalisiert einen Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise AssetReferenceError(f"Invalid module name {value!r}: {exc}") from exc


def is_path_under_module_safe(path: Any, module_name: Any) -> bool:
    """Prüft, ob ein Pfad unter einem Modul liegt."""
    try:
        from ..domain.package_paths import is_path_under_module

        return is_path_under_module(path, module_name)
    except Exception:
        return False


def get_allowed_extensions_safe() -> set[str]:
    """Liest erlaubte Package-Dateiendungen."""
    try:
        from ..domain.package_paths import ALLOWED_PACKAGE_EXTENSIONS

        return set(ALLOWED_PACKAGE_EXTENSIONS)
    except Exception:
        return {
            ".glb",
            ".gltf",
            ".svg",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".ktx2",
            ".basis",
            ".json",
            ".md",
            ".txt",
        }


def get_forbidden_extensions_safe() -> set[str]:
    """Liest verbotene Dateiendungen."""
    try:
        from ..domain.package_paths import FORBIDDEN_FILE_EXTENSIONS

        return set(FORBIDDEN_FILE_EXTENSIONS)
    except Exception:
        return {
            ".py",
            ".sh",
            ".exe",
            ".bat",
            ".cmd",
            ".ps1",
            ".js",
        }


def is_safe_external_uri(value: Any) -> bool:
    """Prüft eine externe URI grob auf sichere Schemes."""
    try:
        parsed = urlparse(str(value).strip())
        return parsed.scheme in URL_SCHEMES and bool(parsed.netloc)
    except Exception:
        return False


def validate_not_external_uri(value: Any) -> None:
    """Verhindert externe URIs bei lokalen/Package-internen Assets."""
    try:
        parsed = urlparse(str(value).strip())
        if parsed.scheme and parsed.scheme.lower() in URL_SCHEMES:
            raise AssetReferenceError(f"External URI is not allowed here: {value!r}.")
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"Invalid asset path {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()
        if not raw:
            raise AssetReferenceError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace(".", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"Invalid enum value {value!r}.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise AssetReferenceError(f"{field_name} is required.")

        return cleaned
    except AssetReferenceError:
        raise
    except Exception as exc:
        raise AssetReferenceError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_asset_reference_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_asset_role_value.cache_clear()
    parse_asset_type_value.cache_clear()
    parse_asset_origin_value.cache_clear()
    parse_asset_reference_status_value.cache_clear()


__all__ = [
    "ASSET_REFERENCE_SCHEMA_VERSION",
    "DEFAULT_RENDER_MODULE_NAME",
    "SAFE_ASSET_ID_RE",
    "SAFE_HEX_COLOR_RE",
    "URL_SCHEMES",
    "AssetBounds3D",
    "AssetOrigin",
    "AssetReference",
    "AssetReferenceCollection",
    "AssetReferenceError",
    "AssetReferenceStatus",
    "AssetRole",
    "AssetSource",
    "AssetTarget",
    "AssetType",
    "asset_bounds_from_mapping",
    "asset_reference_from_create_asset_request",
    "asset_reference_from_mapping",
    "asset_references_from_iterable",
    "asset_source_from_mapping",
    "asset_target_from_mapping",
    "clean_optional_string",
    "clean_required_string",
    "clear_asset_reference_caches",
    "get_allowed_extensions_safe",
    "get_forbidden_extensions_safe",
    "infer_asset_id_from_mapping",
    "infer_asset_id_from_path",
    "infer_asset_type_from_extension",
    "infer_asset_type_from_mapping",
    "infer_extension_from_reference",
    "infer_mime_type",
    "infer_role_from_mapping",
    "infer_target_module_from_role",
    "is_path_under_module_safe",
    "is_safe_external_uri",
    "normalize_asset_id",
    "normalize_enum_key",
    "normalize_file_extension",
    "normalize_module_name",
    "normalize_optional_color",
    "normalize_optional_non_negative_int",
    "normalize_package_asset_path",
    "normalize_positive_float",
    "parse_asset_origin_value",
    "parse_asset_reference_status_value",
    "parse_asset_role_value",
    "parse_asset_type_value",
    "validate_asset_extension_for_type",
    "validate_not_external_uri",
    "validate_role_type_compatibility",
]