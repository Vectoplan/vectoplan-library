# services/vectoplan-library/src/vplib/defaults/render_defaults.py
"""
Render defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    render/render_variants.json
    optional: render/bounds.json
    optional: render/materials.json
    optional: render/lod.json

Render-Daten beschreiben die sichtbare Repräsentation einer VPLIB-Family im
Editor oder in Preview-/Runtime-Kontexten.

Wichtig:
Der Render-Layer ist nicht die fachliche Platzierungswahrheit. Die
Platzierungswahrheit bleibt der Grid-Footprint aus editor/placement.json.
GLB-, Textur- oder Fallback-Geometrie muss innerhalb dieses Footprints bleiben.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


RENDER_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.render_defaults.v1"
RENDER_VARIANTS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.render.variants.v1"
RENDER_BOUNDS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.render.bounds.v1"
RENDER_MATERIALS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.render.materials.v1"
RENDER_LOD_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.render.lod.v1"

DEFAULT_RENDER_VARIANT_ID: Final[str] = "default"
DEFAULT_RENDER_MATERIAL_ID: Final[str] = "default_material"
DEFAULT_FALLBACK_COLOR: Final[str] = "#9CA3AF"

SAFE_RENDER_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_HEX_COLOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)


class RenderDefaultsError(ValueError):
    """Wird ausgelöst, wenn Render-Defaults ungültig erzeugt werden."""


class RenderShape(str, Enum):
    """Grundform der sichtbaren Repräsentation."""

    CUBE = "cube"
    CUBOID = "cuboid"
    CUSTOM_GLB = "custom_glb"
    PLACEHOLDER = "placeholder"

    @property
    def key(self) -> str:
        return str(self.value)


class RenderFitMode(str, Enum):
    """Einpassung der sichtbaren Repräsentation in den Footprint."""

    STRICT_INSIDE = "strict_inside"
    SCALE_TO_FIT = "scale_to_fit"
    FILL_FOOTPRINT = "fill_footprint"

    @property
    def key(self) -> str:
        return str(self.value)


class RenderAlignment(str, Enum):
    """Visuelle Ausrichtung innerhalb des belegten Footprints."""

    CENTERED = "centered"
    BOTTOM_ALIGNED = "bottom_aligned"
    TOP_ALIGNED = "top_aligned"
    SURFACE_ALIGNED = "surface_aligned"
    FILL_BLOCK = "fill_block"

    @property
    def key(self) -> str:
        return str(self.value)


class RenderAssetRole(str, Enum):
    """Render-Asset-Rolle."""

    ICON = "icon"
    PREVIEW = "preview"
    TEXTURE = "texture"
    MATERIAL_TEXTURE = "material_texture"
    GLB_MODEL = "glb_model"
    GLTF_MODEL = "gltf_model"
    LOD_MODEL = "lod_model"

    @property
    def key(self) -> str:
        return str(self.value)


class RenderMaterialKind(str, Enum):
    """Render-Material-Art."""

    PBR = "pbr"
    BASIC = "basic"
    LAMBERT = "lambert"
    PHONG = "phong"
    UNLIT = "unlit"

    @property
    def key(self) -> str:
        return str(self.value)


class TextureWrapMode(str, Enum):
    """Texture-Wrap-Modus."""

    REPEAT = "repeat"
    CLAMP_TO_EDGE = "clamp_to_edge"
    MIRRORED_REPEAT = "mirrored_repeat"

    @property
    def key(self) -> str:
        return str(self.value)


class TextureFilterMode(str, Enum):
    """Texture-Filter-Modus."""

    LINEAR = "linear"
    NEAREST = "nearest"
    LINEAR_MIPMAP_LINEAR = "linear_mipmap_linear"

    @property
    def key(self) -> str:
        return str(self.value)


class LodStrategy(str, Enum):
    """LOD-Strategie."""

    NONE = "none"
    DISTANCE = "distance"
    SCREEN_SIZE = "screen_size"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Vector3Defaults:
    """Ein einfacher 3D-Vektor."""

    x: float
    y: float
    z: float

    def normalized(self) -> "Vector3Defaults":
        return Vector3Defaults(
            x=normalize_float(self.x, "x"),
            y=normalize_float(self.y, "y"),
            z=normalize_float(self.z, "z"),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "x": normalized.x,
            "y": normalized.y,
            "z": normalized.z,
        }


@dataclass(frozen=True, slots=True)
class RenderBoundsDefaults:
    """Bounds der sichtbaren Repräsentation in Metern."""

    width_m: float
    height_m: float
    depth_m: float
    offset_m: Vector3Defaults = field(default_factory=lambda: Vector3Defaults(0.0, 0.0, 0.0))
    origin_m: Vector3Defaults = field(default_factory=lambda: Vector3Defaults(0.0, 0.0, 0.0))
    must_fit_grid_footprint: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderBoundsDefaults":
        width_m = normalize_positive_float(self.width_m, "width_m")
        height_m = normalize_positive_float(self.height_m, "height_m")
        depth_m = normalize_positive_float(self.depth_m, "depth_m")

        return RenderBoundsDefaults(
            width_m=width_m,
            height_m=height_m,
            depth_m=depth_m,
            offset_m=self.offset_m.normalized(),
            origin_m=self.origin_m.normalized(),
            must_fit_grid_footprint=bool(self.must_fit_grid_footprint),
            metadata=normalize_metadata(self.metadata),
        )

    @property
    def size_m(self) -> tuple[float, float, float]:
        normalized = self.normalized()
        return (normalized.width_m, normalized.height_m, normalized.depth_m)

    def fits_inside(self, size_m: Sequence[Any]) -> bool:
        """Prüft, ob die Bounds in eine gegebene Metergröße passen."""
        normalized = self.normalized()

        try:
            max_width = float(size_m[0])
            max_height = float(size_m[1])
            max_depth = float(size_m[2])
        except Exception as exc:
            raise RenderDefaultsError(f"Invalid size_m value {size_m!r}.") from exc

        return (
            normalized.width_m <= max_width
            and normalized.height_m <= max_height
            and normalized.depth_m <= max_depth
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt render/bounds.json."""
        normalized = self.normalized()

        return {
            "schema_version": RENDER_BOUNDS_DOCUMENT_SCHEMA_VERSION,
            "width_m": normalized.width_m,
            "height_m": normalized.height_m,
            "depth_m": normalized.depth_m,
            "size_m": {
                "x": normalized.width_m,
                "y": normalized.height_m,
                "z": normalized.depth_m,
            },
            "offset_m": normalized.offset_m.to_dict(),
            "origin_m": normalized.origin_m.to_dict(),
            "must_fit_grid_footprint": normalized.must_fit_grid_footprint,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class RenderAssetRefDefaults:
    """Render-Asset-Referenz."""

    role: str
    ref: str
    asset_id: str | None = None
    mime_type: str | None = None
    required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderAssetRefDefaults":
        role = parse_render_asset_role_value(self.role)
        ref = clean_required_string(self.ref, "ref")
        asset_id = normalize_optional_render_id(self.asset_id, "asset_id")
        mime_type = clean_optional_string(self.mime_type) or infer_mime_type(ref)
        required = bool(self.required)
        metadata = normalize_metadata(self.metadata)

        return RenderAssetRefDefaults(
            role=role,
            ref=ref,
            asset_id=asset_id,
            mime_type=mime_type,
            required=required,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "role": normalized.role,
            "ref": normalized.ref,
            "asset_id": normalized.asset_id,
            "mime_type": normalized.mime_type,
            "required": normalized.required,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class RenderMaterialDefaults:
    """Ein Render-Material."""

    material_id: str = DEFAULT_RENDER_MATERIAL_ID
    material_kind: str = RenderMaterialKind.PBR.value
    label: str | None = None
    fallback_color: str = DEFAULT_FALLBACK_COLOR
    base_color_texture_ref: str | None = None
    normal_texture_ref: str | None = None
    roughness_texture_ref: str | None = None
    metallic_texture_ref: str | None = None
    opacity: float = 1.0
    metallic: float = 0.0
    roughness: float = 0.8
    double_sided: bool = False
    texture_wrap_mode: str = TextureWrapMode.REPEAT.value
    texture_filter_mode: str = TextureFilterMode.LINEAR_MIPMAP_LINEAR.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderMaterialDefaults":
        material_id = normalize_render_id(self.material_id, "material_id")
        material_kind = parse_render_material_kind_value(self.material_kind)
        label = clean_optional_string(self.label) or material_id
        fallback_color = normalize_color(self.fallback_color)
        base_color_texture_ref = clean_optional_string(self.base_color_texture_ref)
        normal_texture_ref = clean_optional_string(self.normal_texture_ref)
        roughness_texture_ref = clean_optional_string(self.roughness_texture_ref)
        metallic_texture_ref = clean_optional_string(self.metallic_texture_ref)
        opacity = normalize_unit_interval_float(self.opacity, "opacity")
        metallic = normalize_unit_interval_float(self.metallic, "metallic")
        roughness = normalize_unit_interval_float(self.roughness, "roughness")
        double_sided = bool(self.double_sided)
        texture_wrap_mode = parse_texture_wrap_mode_value(self.texture_wrap_mode)
        texture_filter_mode = parse_texture_filter_mode_value(self.texture_filter_mode)
        metadata = normalize_metadata(self.metadata)

        return RenderMaterialDefaults(
            material_id=material_id,
            material_kind=material_kind,
            label=label,
            fallback_color=fallback_color,
            base_color_texture_ref=base_color_texture_ref,
            normal_texture_ref=normal_texture_ref,
            roughness_texture_ref=roughness_texture_ref,
            metallic_texture_ref=metallic_texture_ref,
            opacity=opacity,
            metallic=metallic,
            roughness=roughness,
            double_sided=double_sided,
            texture_wrap_mode=texture_wrap_mode,
            texture_filter_mode=texture_filter_mode,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "material_id": normalized.material_id,
            "material_kind": normalized.material_kind,
            "label": normalized.label,
            "fallback_color": normalized.fallback_color,
            "base_color_texture_ref": normalized.base_color_texture_ref,
            "normal_texture_ref": normalized.normal_texture_ref,
            "roughness_texture_ref": normalized.roughness_texture_ref,
            "metallic_texture_ref": normalized.metallic_texture_ref,
            "opacity": normalized.opacity,
            "metallic": normalized.metallic,
            "roughness": normalized.roughness,
            "double_sided": normalized.double_sided,
            "texture_wrap_mode": normalized.texture_wrap_mode,
            "texture_filter_mode": normalized.texture_filter_mode,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class RenderMaterialsDefaults:
    """Defaults für render/materials.json."""

    materials: tuple[RenderMaterialDefaults, ...] = field(default_factory=tuple)
    default_material_id: str = DEFAULT_RENDER_MATERIAL_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderMaterialsDefaults":
        default_material_id = normalize_render_id(self.default_material_id, "default_material_id")
        materials = tuple(material.normalized() for material in self.materials or ())

        if not materials:
            materials = (
                RenderMaterialDefaults(
                    material_id=default_material_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
            )

        material_ids = [material.material_id for material in materials]
        assert_unique_values(material_ids, "material_id")

        if default_material_id not in set(material_ids):
            materials = (
                RenderMaterialDefaults(
                    material_id=default_material_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
                *materials,
            )

        return RenderMaterialsDefaults(
            materials=tuple(materials),
            default_material_id=default_material_id,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt render/materials.json."""
        normalized = self.normalized()

        return {
            "schema_version": RENDER_MATERIALS_DOCUMENT_SCHEMA_VERSION,
            "default_material_id": normalized.default_material_id,
            "materials": [material.to_dict() for material in normalized.materials],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class RenderVariantDefaults:
    """Eine Render-Variante innerhalb von render/render_variants.json."""

    render_variant_id: str = DEFAULT_RENDER_VARIANT_ID
    variant_id: str | None = None
    shape: str = RenderShape.CUBE.value
    fit_mode: str = RenderFitMode.STRICT_INSIDE.value
    visual_alignment: str = RenderAlignment.CENTERED.value
    fallback_color: str = DEFAULT_FALLBACK_COLOR
    material_id: str = DEFAULT_RENDER_MATERIAL_ID
    icon_ref: str | None = None
    preview_ref: str | None = None
    texture_ref: str | None = None
    glb_ref: str | None = None
    model_ref: str | None = None
    bounds_m: RenderBoundsDefaults | None = None
    asset_refs: tuple[RenderAssetRefDefaults, ...] = field(default_factory=tuple)
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderVariantDefaults":
        render_variant_id = normalize_render_id(self.render_variant_id, "render_variant_id")
        variant_id = normalize_optional_render_id(self.variant_id, "variant_id")
        shape = parse_render_shape_value(self.shape)
        fit_mode = parse_render_fit_mode_value(self.fit_mode)
        visual_alignment = parse_render_alignment_value(self.visual_alignment)
        fallback_color = normalize_color(self.fallback_color)
        material_id = normalize_render_id(self.material_id, "material_id")
        icon_ref = clean_optional_string(self.icon_ref)
        preview_ref = clean_optional_string(self.preview_ref)
        texture_ref = clean_optional_string(self.texture_ref)
        glb_ref = clean_optional_string(self.glb_ref)
        model_ref = clean_optional_string(self.model_ref)
        bounds_m = self.bounds_m.normalized() if self.bounds_m is not None else None
        asset_refs = tuple(asset.normalized() for asset in self.asset_refs or ())
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        if shape == RenderShape.CUSTOM_GLB.value and not glb_ref and not model_ref:
            raise RenderDefaultsError("Render shape 'custom_glb' requires glb_ref or model_ref.")

        if glb_ref or model_ref:
            if bounds_m is None:
                raise RenderDefaultsError("Render model references require bounds_m.")

        if not texture_ref and not glb_ref and not model_ref and not fallback_color:
            raise RenderDefaultsError(
                "Render variant requires texture_ref, glb_ref, model_ref or fallback_color."
            )

        asset_refs = merge_asset_refs(
            asset_refs,
            auto_asset_refs_from_render_variant(
                icon_ref=icon_ref,
                preview_ref=preview_ref,
                texture_ref=texture_ref,
                glb_ref=glb_ref,
                model_ref=model_ref,
            ),
        )

        return RenderVariantDefaults(
            render_variant_id=render_variant_id,
            variant_id=variant_id,
            shape=shape,
            fit_mode=fit_mode,
            visual_alignment=visual_alignment,
            fallback_color=fallback_color,
            material_id=material_id,
            icon_ref=icon_ref,
            preview_ref=preview_ref,
            texture_ref=texture_ref,
            glb_ref=glb_ref,
            model_ref=model_ref,
            bounds_m=bounds_m,
            asset_refs=asset_refs,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "render_variant_id": normalized.render_variant_id,
            "variant_id": normalized.variant_id,
            "shape": normalized.shape,
            "fit_mode": normalized.fit_mode,
            "visual_alignment": normalized.visual_alignment,
            "fallback_color": normalized.fallback_color,
            "material_id": normalized.material_id,
            "icon_ref": normalized.icon_ref,
            "preview_ref": normalized.preview_ref,
            "texture_ref": normalized.texture_ref,
            "glb_ref": normalized.glb_ref,
            "model_ref": normalized.model_ref,
            "bounds_m": normalized.bounds_m.to_dict() if normalized.bounds_m else None,
            "asset_refs": [asset.to_dict() for asset in normalized.asset_refs],
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class RenderVariantsDefaults:
    """Defaults für render/render_variants.json."""

    render_variants: tuple[RenderVariantDefaults, ...] = field(default_factory=tuple)
    default_render_variant_id: str = DEFAULT_RENDER_VARIANT_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderVariantsDefaults":
        default_render_variant_id = normalize_render_id(
            self.default_render_variant_id,
            "default_render_variant_id",
        )
        render_variants = tuple(variant.normalized() for variant in self.render_variants or ())

        if not render_variants:
            render_variants = (
                RenderVariantDefaults(
                    render_variant_id=default_render_variant_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
            )

        render_variant_ids = [variant.render_variant_id for variant in render_variants]
        assert_unique_values(render_variant_ids, "render_variant_id")

        if default_render_variant_id not in set(render_variant_ids):
            render_variants = (
                RenderVariantDefaults(
                    render_variant_id=default_render_variant_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
                *render_variants,
            )

        return RenderVariantsDefaults(
            render_variants=render_variants,
            default_render_variant_id=default_render_variant_id,
            metadata=normalize_metadata(self.metadata),
        )

    @property
    def default_render_variant(self) -> RenderVariantDefaults:
        normalized = self.normalized()

        for variant in normalized.render_variants:
            if variant.render_variant_id == normalized.default_render_variant_id:
                return variant

        raise RenderDefaultsError(
            f"Default render variant {normalized.default_render_variant_id!r} does not exist."
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt render/render_variants.json."""
        normalized = self.normalized()

        return {
            "schema_version": RENDER_VARIANTS_DOCUMENT_SCHEMA_VERSION,
            "default_render_variant_id": normalized.default_render_variant_id,
            "render_variant_ids": [
                variant.render_variant_id
                for variant in normalized.render_variants
            ],
            "render_variants": [variant.to_dict() for variant in normalized.render_variants],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class LodLevelDefaults:
    """Eine LOD-Stufe."""

    lod_id: str
    min_distance_m: float = 0.0
    max_distance_m: float | None = None
    model_ref: str | None = None
    texture_ref: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "LodLevelDefaults":
        lod_id = normalize_render_id(self.lod_id, "lod_id")
        min_distance_m = normalize_non_negative_float(self.min_distance_m, "min_distance_m")
        max_distance_m = (
            normalize_positive_float(self.max_distance_m, "max_distance_m")
            if self.max_distance_m is not None
            else None
        )
        model_ref = clean_optional_string(self.model_ref)
        texture_ref = clean_optional_string(self.texture_ref)
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        if max_distance_m is not None and max_distance_m <= min_distance_m:
            raise RenderDefaultsError("max_distance_m must be greater than min_distance_m.")

        return LodLevelDefaults(
            lod_id=lod_id,
            min_distance_m=min_distance_m,
            max_distance_m=max_distance_m,
            model_ref=model_ref,
            texture_ref=texture_ref,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "lod_id": normalized.lod_id,
            "min_distance_m": normalized.min_distance_m,
            "max_distance_m": normalized.max_distance_m,
            "model_ref": normalized.model_ref,
            "texture_ref": normalized.texture_ref,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class RenderLodDefaults:
    """Defaults für render/lod.json."""

    strategy: str = LodStrategy.NONE.value
    levels: tuple[LodLevelDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RenderLodDefaults":
        strategy = parse_lod_strategy_value(self.strategy)
        levels = tuple(level.normalized() for level in self.levels or ())
        metadata = normalize_metadata(self.metadata)

        if strategy != LodStrategy.NONE.value and not levels:
            levels = (
                LodLevelDefaults(
                    lod_id="lod0",
                    min_distance_m=0.0,
                    max_distance_m=None,
                ).normalized(),
            )

        assert_unique_values([level.lod_id for level in levels], "lod_id")

        return RenderLodDefaults(
            strategy=strategy,
            levels=levels,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt render/lod.json."""
        normalized = self.normalized()

        return {
            "schema_version": RENDER_LOD_DOCUMENT_SCHEMA_VERSION,
            "strategy": normalized.strategy,
            "levels": [level.to_dict() for level in normalized.levels],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class RenderDefaults:
    """Vollständige Defaults für alle render/*.json-Dokumente."""

    render_variants: RenderVariantsDefaults
    bounds: RenderBoundsDefaults | None = None
    materials: RenderMaterialsDefaults = field(default_factory=RenderMaterialsDefaults)
    lod: RenderLodDefaults = field(default_factory=RenderLodDefaults)

    def normalized(self) -> "RenderDefaults":
        render_variants = self.render_variants.normalized()
        default_variant = render_variants.default_render_variant
        bounds = self.bounds.normalized() if self.bounds is not None else default_variant.bounds_m
        materials = self.materials.normalized()
        lod = self.lod.normalized()

        return RenderDefaults(
            render_variants=render_variants,
            bounds=bounds,
            materials=materials,
            lod=lod,
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Render-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "render/render_variants.json": normalized.render_variants.to_document(),
        }

        if include_optional:
            if normalized.bounds is not None:
                documents["render/bounds.json"] = normalized.bounds.to_document()
            documents["render/materials.json"] = normalized.materials.to_document()
            documents["render/lod.json"] = normalized.lod.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": RENDER_DEFAULTS_SCHEMA_VERSION,
            "render_variants": normalized.render_variants.to_dict(),
            "bounds": normalized.bounds.to_dict() if normalized.bounds else None,
            "materials": normalized.materials.to_dict(),
            "lod": normalized.lod.to_dict(),
        }


def build_render_defaults(
    *,
    shape: str = RenderShape.CUBE.value,
    fit_mode: str = RenderFitMode.STRICT_INSIDE.value,
    visual_alignment: str = RenderAlignment.CENTERED.value,
    fallback_color: str = DEFAULT_FALLBACK_COLOR,
    variant_id: str | None = None,
    render_variant_id: str = DEFAULT_RENDER_VARIANT_ID,
    material_id: str = DEFAULT_RENDER_MATERIAL_ID,
    texture_ref: str | None = None,
    glb_ref: str | None = None,
    model_ref: str | None = None,
    icon_ref: str | None = None,
    preview_ref: str | None = None,
    bounds_m: RenderBoundsDefaults | Mapping[str, Any] | None = None,
    grid_size_m: Sequence[Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RenderDefaults:
    """Baut RenderDefaults aus expliziten Werten."""
    try:
        normalized_bounds = normalize_bounds(bounds_m)

        if normalized_bounds and grid_size_m is not None and not normalized_bounds.fits_inside(grid_size_m):
            raise RenderDefaultsError("Render bounds must not exceed the grid footprint size.")

        variant = RenderVariantDefaults(
            render_variant_id=render_variant_id,
            variant_id=variant_id,
            shape=shape,
            fit_mode=fit_mode,
            visual_alignment=visual_alignment,
            fallback_color=fallback_color,
            material_id=material_id,
            icon_ref=icon_ref,
            preview_ref=preview_ref,
            texture_ref=texture_ref,
            glb_ref=glb_ref,
            model_ref=model_ref,
            bounds_m=normalized_bounds,
            metadata={
                "source": "build_render_defaults",
                **dict(metadata or {}),
            },
        ).normalized()

        material = RenderMaterialDefaults(
            material_id=material_id,
            fallback_color=fallback_color,
            base_color_texture_ref=texture_ref,
            metadata=dict(metadata or {}),
        ).normalized()

        return RenderDefaults(
            render_variants=RenderVariantsDefaults(
                render_variants=(variant,),
                default_render_variant_id=render_variant_id,
                metadata=dict(metadata or {}),
            ),
            bounds=normalized_bounds,
            materials=RenderMaterialsDefaults(
                materials=(material,),
                default_material_id=material_id,
                metadata=dict(metadata or {}),
            ),
            lod=RenderLodDefaults(),
        ).normalized()
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Could not build render defaults: {exc}") from exc


def render_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> RenderDefaults:
    """Baut RenderDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        visual = normalized_request.visual.normalized()
        grid = normalized_request.grid.normalized()
        placement = normalized_request.placement.normalized(object_kind=normalized_request.object_kind)
        variants = normalized_request.variants.normalized()

        return build_render_defaults(
            shape=visual.shape,
            fit_mode=visual.fit_mode,
            visual_alignment=placement.placement_mode,
            fallback_color=visual.fallback_color,
            variant_id=variants.default_variant_id,
            render_variant_id=DEFAULT_RENDER_VARIANT_ID,
            texture_ref=visual.texture_ref,
            glb_ref=visual.glb_ref,
            model_ref=visual.model_ref,
            icon_ref=visual.icon_ref,
            preview_ref=visual.preview_ref,
            bounds_m=visual.model_bounds_m.to_dict() if visual.model_bounds_m else None,
            grid_size_m=grid.size_m,
            metadata={
                "source": "create_request",
                "object_kind": normalized_request.object_kind,
                **dict(metadata or {}),
            },
        )
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Could not build render defaults from CreateRequest: {exc}") from exc


def render_defaults_from_context(
    context: Any,
    *,
    fallback_color: str = DEFAULT_FALLBACK_COLOR,
    placement_mode: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> RenderDefaults:
    """Baut RenderDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        object_kind = normalized_context.object_kind
        resolved_alignment = placement_mode or get_default_placement_mode_for_object_kind_safe(object_kind)

        return build_render_defaults(
            shape=RenderShape.CUBE.value,
            fit_mode=RenderFitMode.STRICT_INSIDE.value,
            visual_alignment=resolved_alignment,
            fallback_color=fallback_color,
            metadata={
                "source": "package_context",
                "object_kind": object_kind,
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Could not build render defaults from PackageContext: {exc}") from exc


def render_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> RenderDefaults:
    """Baut RenderDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return render_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Could not build render defaults from CreationPlan: {exc}") from exc


def render_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle render/*.json-Dokumente aus CreateRequest."""
    return render_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def render_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle render/*.json-Dokumente aus PackageContext."""
    return render_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def render_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle render/*.json-Dokumente aus CreationPlan."""
    return render_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def validate_render_variants_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob render/render_variants.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("render/render_variants.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "default_render_variant_id",
            "render_variant_ids",
            "render_variants",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing render variants field {field_name!r}.")

        render_variants = document.get("render_variants", ())
        if not isinstance(render_variants, list):
            messages.append("render_variants must be a list.")
        else:
            ids: list[str] = []
            for item in render_variants:
                if not isinstance(item, Mapping):
                    messages.append("Each render variant must be an object.")
                    continue
                try:
                    variant = render_variant_defaults_from_mapping(item)
                    ids.append(variant.render_variant_id)
                except Exception as exc:
                    messages.append(str(exc))

            if len(ids) != len(set(ids)):
                messages.append("Duplicate render_variant_id values found.")

    except Exception as exc:
        messages.append(f"Could not validate render variants document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_render_bounds_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob render/bounds.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("render/bounds.json must be a mapping.",)

        for field_name in ("schema_version", "width_m", "height_m", "depth_m"):
            if field_name not in document:
                messages.append(f"Missing bounds field {field_name!r}.")

        try:
            RenderBoundsDefaults(
                width_m=document.get("width_m"),
                height_m=document.get("height_m"),
                depth_m=document.get("depth_m"),
                offset_m=vector3_from_mapping(document.get("offset_m", {"x": 0, "y": 0, "z": 0})),
                origin_m=vector3_from_mapping(document.get("origin_m", {"x": 0, "y": 0, "z": 0})),
                must_fit_grid_footprint=bool(document.get("must_fit_grid_footprint", True)),
                metadata=dict(document.get("metadata", {}) or {}),
            ).normalized()
        except Exception as exc:
            messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate render bounds document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_render_variants_document(document: Mapping[str, Any]) -> None:
    """Wirft RenderDefaultsError, wenn render/render_variants.json ungültig ist."""
    valid, messages = validate_render_variants_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid render variants document."
        raise RenderDefaultsError(joined)


def assert_valid_render_bounds_document(document: Mapping[str, Any]) -> None:
    """Wirft RenderDefaultsError, wenn render/bounds.json ungültig ist."""
    valid, messages = validate_render_bounds_document(document)

    if not valid:
        joined = " ".join(messages) if messages else "Invalid render bounds document."
        raise RenderDefaultsError(joined)


def render_variant_defaults_from_mapping(data: Mapping[str, Any]) -> RenderVariantDefaults:
    """Baut RenderVariantDefaults aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise RenderDefaultsError("Render variant data must be a mapping.")

        bounds_data = data.get("bounds_m")
        bounds = normalize_bounds(bounds_data) if isinstance(bounds_data, Mapping) else None

        asset_refs = tuple(
            render_asset_ref_from_mapping(item)
            for item in data.get("asset_refs", ()) or ()
            if isinstance(item, Mapping)
        )

        return RenderVariantDefaults(
            render_variant_id=data.get("render_variant_id", DEFAULT_RENDER_VARIANT_ID),
            variant_id=data.get("variant_id"),
            shape=data.get("shape", RenderShape.CUBE.value),
            fit_mode=data.get("fit_mode", RenderFitMode.STRICT_INSIDE.value),
            visual_alignment=data.get("visual_alignment", RenderAlignment.CENTERED.value),
            fallback_color=data.get("fallback_color", DEFAULT_FALLBACK_COLOR),
            material_id=data.get("material_id", DEFAULT_RENDER_MATERIAL_ID),
            icon_ref=data.get("icon_ref"),
            preview_ref=data.get("preview_ref"),
            texture_ref=data.get("texture_ref"),
            glb_ref=data.get("glb_ref"),
            model_ref=data.get("model_ref"),
            bounds_m=bounds,
            asset_refs=asset_refs,
            enabled=bool(data.get("enabled", True)),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Could not build RenderVariantDefaults from mapping: {exc}") from exc


def render_asset_ref_from_mapping(data: Mapping[str, Any]) -> RenderAssetRefDefaults:
    """Baut RenderAssetRefDefaults aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise RenderDefaultsError("Render asset ref data must be a mapping.")

        return RenderAssetRefDefaults(
            role=data.get("role"),
            ref=data.get("ref"),
            asset_id=data.get("asset_id"),
            mime_type=data.get("mime_type"),
            required=bool(data.get("required", False)),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Could not build RenderAssetRefDefaults from mapping: {exc}") from exc


def normalize_bounds(value: RenderBoundsDefaults | Mapping[str, Any] | None) -> RenderBoundsDefaults | None:
    """Normalisiert optionale RenderBounds."""
    if value is None:
        return None

    if isinstance(value, RenderBoundsDefaults):
        return value.normalized()

    if isinstance(value, Mapping):
        return RenderBoundsDefaults(
            width_m=value.get("width_m", value.get("width")),
            height_m=value.get("height_m", value.get("height")),
            depth_m=value.get("depth_m", value.get("depth")),
            offset_m=vector3_from_mapping(value.get("offset_m", {"x": 0, "y": 0, "z": 0})),
            origin_m=vector3_from_mapping(value.get("origin_m", {"x": 0, "y": 0, "z": 0})),
            must_fit_grid_footprint=bool(value.get("must_fit_grid_footprint", True)),
            metadata=dict(value.get("metadata", {}) or {}),
        ).normalized()

    raise RenderDefaultsError("bounds_m must be RenderBoundsDefaults, mapping or None.")


def vector3_from_mapping(value: Mapping[str, Any]) -> Vector3Defaults:
    """Baut Vector3Defaults aus Mapping."""
    if not isinstance(value, Mapping):
        raise RenderDefaultsError("Vector3 value must be a mapping.")

    return Vector3Defaults(
        x=value.get("x", 0.0),
        y=value.get("y", 0.0),
        z=value.get("z", 0.0),
    ).normalized()


def auto_asset_refs_from_render_variant(
    *,
    icon_ref: str | None,
    preview_ref: str | None,
    texture_ref: str | None,
    glb_ref: str | None,
    model_ref: str | None,
) -> tuple[RenderAssetRefDefaults, ...]:
    """Erzeugt AssetRefs automatisch aus Render-Referenzen."""
    refs: list[RenderAssetRefDefaults] = []

    if icon_ref:
        refs.append(RenderAssetRefDefaults(role="icon", ref=icon_ref).normalized())

    if preview_ref:
        refs.append(RenderAssetRefDefaults(role="preview", ref=preview_ref).normalized())

    if texture_ref:
        refs.append(RenderAssetRefDefaults(role="texture", ref=texture_ref).normalized())

    model = glb_ref or model_ref
    if model:
        role = "gltf_model" if str(model).lower().endswith(".gltf") else "glb_model"
        refs.append(RenderAssetRefDefaults(role=role, ref=model).normalized())

    return tuple(refs)


def merge_asset_refs(
    left: Iterable[RenderAssetRefDefaults],
    right: Iterable[RenderAssetRefDefaults],
) -> tuple[RenderAssetRefDefaults, ...]:
    """Merged AssetRefs ohne doppelte role/ref-Kombinationen."""
    result: list[RenderAssetRefDefaults] = []
    seen: set[tuple[str, str]] = set()

    for value in (*tuple(left or ()), *tuple(right or ())):
        ref = value.normalized()
        key = (ref.role, ref.ref)

        if key in seen:
            continue

        result.append(ref)
        seen.add(key)

    return tuple(result)


def normalize_create_request(value: Any) -> Any:
    """Normalisiert CreateRequest-ähnliche Werte."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise RenderDefaultsError("CreateRequest value is required.")
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def get_default_placement_mode_for_object_kind_safe(object_kind: Any) -> str:
    """Liest Default-Placement-Mode für object_kind."""
    try:
        from ..domain.placement_modes import get_default_placement_mode_for_object_kind

        return get_default_placement_mode_for_object_kind(object_kind).value
    except Exception:
        return RenderAlignment.CENTERED.value


def normalize_render_id(value: Any, field_name: str) -> str:
    """Normalisiert Render-IDs."""
    raw = clean_required_string(value, field_name)
    render_id = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_RENDER_ID_RE.match(render_id):
        raise RenderDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return render_id


def normalize_optional_render_id(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Render-IDs."""
    if value is None:
        return None

    return normalize_render_id(value, field_name)


def normalize_color(value: Any) -> str:
    """Normalisiert Hex-Farbe."""
    color = clean_required_string(value or DEFAULT_FALLBACK_COLOR, "fallback_color")

    if not SAFE_HEX_COLOR_RE.match(color):
        raise RenderDefaultsError(f"Invalid color {value!r}.")

    return color


def assert_unique_values(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige Werte."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise RenderDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def infer_mime_type(ref: str) -> str | None:
    """Leitet MIME-Type aus Dateiendung ab."""
    value = str(ref).lower()

    if value.endswith(".svg"):
        return "image/svg+xml"
    if value.endswith(".png"):
        return "image/png"
    if value.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if value.endswith(".webp"):
        return "image/webp"
    if value.endswith(".ktx2"):
        return "image/ktx2"
    if value.endswith(".basis"):
        return "image/ktx2"
    if value.endswith(".glb"):
        return "model/gltf-binary"
    if value.endswith(".gltf"):
        return "model/gltf+json"

    return None


@lru_cache(maxsize=128)
def parse_render_shape_value(value: Any) -> str:
    """Parst RenderShape."""
    try:
        if isinstance(value, RenderShape):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "cube": RenderShape.CUBE.value,
            "block": RenderShape.CUBE.value,
            "cuboid": RenderShape.CUBOID.value,
            "box": RenderShape.CUBOID.value,
            "custom_glb": RenderShape.CUSTOM_GLB.value,
            "glb": RenderShape.CUSTOM_GLB.value,
            "model": RenderShape.CUSTOM_GLB.value,
            "placeholder": RenderShape.PLACEHOLDER.value,
        }

        if raw in aliases:
            return aliases[raw]

        return RenderShape(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid render shape {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_render_fit_mode_value(value: Any) -> str:
    """Parst RenderFitMode."""
    try:
        if isinstance(value, RenderFitMode):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "strict": RenderFitMode.STRICT_INSIDE.value,
            "strict_inside": RenderFitMode.STRICT_INSIDE.value,
            "inside": RenderFitMode.STRICT_INSIDE.value,
            "scale": RenderFitMode.SCALE_TO_FIT.value,
            "scale_to_fit": RenderFitMode.SCALE_TO_FIT.value,
            "fit": RenderFitMode.SCALE_TO_FIT.value,
            "fill": RenderFitMode.FILL_FOOTPRINT.value,
            "fill_footprint": RenderFitMode.FILL_FOOTPRINT.value,
        }

        if raw in aliases:
            return aliases[raw]

        return RenderFitMode(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid render fit mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_render_alignment_value(value: Any) -> str:
    """Parst RenderAlignment."""
    try:
        if isinstance(value, RenderAlignment):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "center": RenderAlignment.CENTERED.value,
            "centered": RenderAlignment.CENTERED.value,
            "bottom": RenderAlignment.BOTTOM_ALIGNED.value,
            "bottom_aligned": RenderAlignment.BOTTOM_ALIGNED.value,
            "top": RenderAlignment.TOP_ALIGNED.value,
            "top_aligned": RenderAlignment.TOP_ALIGNED.value,
            "surface": RenderAlignment.SURFACE_ALIGNED.value,
            "surface_aligned": RenderAlignment.SURFACE_ALIGNED.value,
            "fill": RenderAlignment.FILL_BLOCK.value,
            "fill_block": RenderAlignment.FILL_BLOCK.value,
        }

        if raw in aliases:
            return aliases[raw]

        return RenderAlignment(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid render alignment {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_render_asset_role_value(value: Any) -> str:
    """Parst RenderAssetRole."""
    try:
        if isinstance(value, RenderAssetRole):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "icon": RenderAssetRole.ICON.value,
            "preview": RenderAssetRole.PREVIEW.value,
            "thumbnail": RenderAssetRole.PREVIEW.value,
            "texture": RenderAssetRole.TEXTURE.value,
            "material_texture": RenderAssetRole.MATERIAL_TEXTURE.value,
            "glb": RenderAssetRole.GLB_MODEL.value,
            "glb_model": RenderAssetRole.GLB_MODEL.value,
            "model": RenderAssetRole.GLB_MODEL.value,
            "gltf": RenderAssetRole.GLTF_MODEL.value,
            "gltf_model": RenderAssetRole.GLTF_MODEL.value,
            "lod": RenderAssetRole.LOD_MODEL.value,
            "lod_model": RenderAssetRole.LOD_MODEL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return RenderAssetRole(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid render asset role {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_render_material_kind_value(value: Any) -> str:
    """Parst RenderMaterialKind."""
    try:
        if isinstance(value, RenderMaterialKind):
            return value.value

        raw = normalize_enum_key(value)
        return RenderMaterialKind(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid render material kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_texture_wrap_mode_value(value: Any) -> str:
    """Parst TextureWrapMode."""
    try:
        if isinstance(value, TextureWrapMode):
            return value.value

        raw = normalize_enum_key(value)
        return TextureWrapMode(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid texture wrap mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_texture_filter_mode_value(value: Any) -> str:
    """Parst TextureFilterMode."""
    try:
        if isinstance(value, TextureFilterMode):
            return value.value

        raw = normalize_enum_key(value)
        return TextureFilterMode(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid texture filter mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_lod_strategy_value(value: Any) -> str:
    """Parst LodStrategy."""
    try:
        if isinstance(value, LodStrategy):
            return value.value

        raw = normalize_enum_key(value)
        return LodStrategy(raw).value
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid LOD strategy {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise RenderDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise RenderDefaultsError(f"{field_name} must be a number.")

        return float(value)
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"{field_name} must be a number.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Float-Werte."""
    try:
        number = normalize_float(value, field_name)

        if number <= 0:
            raise RenderDefaultsError(f"{field_name} must be > 0.")

        return number
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"{field_name} must be a positive number.") from exc


def normalize_non_negative_float(value: Any, field_name: str) -> float:
    """Normalisiert nicht-negative Float-Werte."""
    try:
        number = normalize_float(value, field_name)

        if number < 0:
            raise RenderDefaultsError(f"{field_name} must be >= 0.")

        return number
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"{field_name} must be a non-negative number.") from exc


def normalize_unit_interval_float(value: Any, field_name: str) -> float:
    """Normalisiert Float im Bereich 0..1."""
    number = normalize_float(value, field_name)

    if number < 0 or number > 1:
        raise RenderDefaultsError(f"{field_name} must be in range 0..1.")

    return number


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise RenderDefaultsError("metadata must be a mapping.")

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


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise RenderDefaultsError(f"{field_name} is required.")

        return cleaned
    except RenderDefaultsError:
        raise
    except Exception as exc:
        raise RenderDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_render_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_render_shape_value.cache_clear()
    parse_render_fit_mode_value.cache_clear()
    parse_render_alignment_value.cache_clear()
    parse_render_asset_role_value.cache_clear()
    parse_render_material_kind_value.cache_clear()
    parse_texture_wrap_mode_value.cache_clear()
    parse_texture_filter_mode_value.cache_clear()
    parse_lod_strategy_value.cache_clear()


__all__ = [
    "DEFAULT_FALLBACK_COLOR",
    "DEFAULT_RENDER_MATERIAL_ID",
    "DEFAULT_RENDER_VARIANT_ID",
    "RENDER_BOUNDS_DOCUMENT_SCHEMA_VERSION",
    "RENDER_DEFAULTS_SCHEMA_VERSION",
    "RENDER_LOD_DOCUMENT_SCHEMA_VERSION",
    "RENDER_MATERIALS_DOCUMENT_SCHEMA_VERSION",
    "RENDER_VARIANTS_DOCUMENT_SCHEMA_VERSION",
    "SAFE_HEX_COLOR_RE",
    "SAFE_RENDER_ID_RE",
    "LodLevelDefaults",
    "LodStrategy",
    "RenderAlignment",
    "RenderAssetRefDefaults",
    "RenderAssetRole",
    "RenderBoundsDefaults",
    "RenderDefaults",
    "RenderDefaultsError",
    "RenderFitMode",
    "RenderLodDefaults",
    "RenderMaterialDefaults",
    "RenderMaterialKind",
    "RenderMaterialsDefaults",
    "RenderShape",
    "RenderVariantDefaults",
    "RenderVariantsDefaults",
    "TextureFilterMode",
    "TextureWrapMode",
    "Vector3Defaults",
    "assert_unique_values",
    "assert_valid_render_bounds_document",
    "assert_valid_render_variants_document",
    "auto_asset_refs_from_render_variant",
    "build_render_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_render_defaults_caches",
    "get_default_placement_mode_for_object_kind_safe",
    "infer_mime_type",
    "merge_asset_refs",
    "normalize_bounds",
    "normalize_color",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_float",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_float",
    "normalize_optional_render_id",
    "normalize_positive_float",
    "normalize_render_id",
    "normalize_unit_interval_float",
    "parse_lod_strategy_value",
    "parse_render_alignment_value",
    "parse_render_asset_role_value",
    "parse_render_fit_mode_value",
    "parse_render_material_kind_value",
    "parse_render_shape_value",
    "parse_texture_filter_mode_value",
    "parse_texture_wrap_mode_value",
    "render_asset_ref_from_mapping",
    "render_defaults_from_context",
    "render_defaults_from_create_request",
    "render_defaults_from_creation_plan",
    "render_documents_from_context",
    "render_documents_from_create_request",
    "render_documents_from_creation_plan",
    "render_variant_defaults_from_mapping",
    "validate_render_bounds_document",
    "validate_render_variants_document",
    "vector3_from_mapping",
]