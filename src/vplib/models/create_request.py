# services/vectoplan-library/src/vplib/models/create_request.py
"""
CreateRequest model for the VPLIB package engine.

Diese Datei beschreibt den strukturierten Erstellwunsch für ein neues modulares
VPLIB-Package. Sie schreibt keine Dateien und erzeugt noch kein Package.

Rolle dieser Datei:

    raw input / dict
    -> CreateRequest
    -> normalized request
    -> later: planning, creation, validation

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
Kommentare und Docstrings dürfen Deutsch sein.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Mapping, Sequence


CREATE_REQUEST_SCHEMA_VERSION: Final[str] = "vplib.create_request.v1"

DEFAULT_PACKAGE_VERSION: Final[str] = "0.1.0"
DEFAULT_CELL_SIZE_M: Final[float] = 1.0
DEFAULT_VARIANT_ID: Final[str] = "default"
DEFAULT_FALLBACK_COLOR: Final[str] = "#9CA3AF"

SAFE_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_COLOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)


class CreateRequestError(ValueError):
    """Wird ausgelöst, wenn ein CreateRequest ungültig ist."""


class VariantMode(str, Enum):
    """Variantenmodus für neue VPLIB-Packages."""

    SINGLE = "single"
    MULTIPLE = "multiple"

    @property
    def key(self) -> str:
        return str(self.value)


class RenderShape(str, Enum):
    """Grundform der sichtbaren Repräsentation."""

    CUBE = "cube"
    CUBOID = "cuboid"
    CUSTOM_GLB = "custom_glb"

    @property
    def key(self) -> str:
        return str(self.value)


class FitMode(str, Enum):
    """Beschreibt, wie ein sichtbares Modell in den Footprint eingepasst wird."""

    STRICT_INSIDE = "strict_inside"
    SCALE_TO_FIT = "scale_to_fit"
    FILL_FOOTPRINT = "fill_footprint"

    @property
    def key(self) -> str:
        return str(self.value)


class SnapMode(str, Enum):
    """Platzierungs-Snap-Modus."""

    GRID = "grid"
    SURFACE = "surface"
    ANCHOR = "anchor"
    SOCKET = "socket"
    FREE = "free"

    @property
    def key(self) -> str:
        return str(self.value)


class AssetRole(str, Enum):
    """Rolle eines Assets innerhalb des Packages."""

    ICON = "icon"
    PREVIEW = "preview"
    TEXTURE = "texture"
    GLB_MODEL = "glb_model"
    MATERIAL_TEXTURE = "material_texture"
    DOCUMENTATION = "documentation"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class IdentityRequest:
    """Identitätsdaten für ein neues Family-Package."""

    family_id: str
    family_name: str
    package_id: str | None = None
    family_slug: str | None = None
    display_name: str | None = None
    short_name: str | None = None
    description: str = ""
    version: str = DEFAULT_PACKAGE_VERSION
    author: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "IdentityRequest":
        family_id = normalize_identifier(self.family_id, field_name="family_id")
        family_slug = (
            normalize_slug(self.family_slug, field_name="family_slug")
            if self.family_slug
            else family_id.split(".")[-1]
        )
        package_id = (
            normalize_identifier(self.package_id, field_name="package_id")
            if self.package_id
            else family_id
        )

        family_name = clean_required_string(self.family_name, "family_name")
        display_name = clean_optional_string(self.display_name) or family_name
        short_name = clean_optional_string(self.short_name) or display_name
        description = clean_optional_string(self.description) or ""
        version = clean_required_string(self.version or DEFAULT_PACKAGE_VERSION, "version")
        author = clean_optional_string(self.author)
        tags = normalize_string_tuple(self.tags)

        return IdentityRequest(
            family_id=family_id,
            family_name=family_name,
            package_id=package_id,
            family_slug=family_slug,
            display_name=display_name,
            short_name=short_name,
            description=description,
            version=version,
            author=author,
            tags=tags,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "family_id": normalized.family_id,
            "family_name": normalized.family_name,
            "package_id": normalized.package_id,
            "family_slug": normalized.family_slug,
            "display_name": normalized.display_name,
            "short_name": normalized.short_name,
            "description": normalized.description,
            "version": normalized.version,
            "author": normalized.author,
            "tags": list(normalized.tags),
        }


@dataclass(frozen=True, slots=True)
class ClassificationRequest:
    """Klassifikation: domain/tab -> category -> subcategory."""

    domain: str
    category: str
    subcategory: str

    def normalized(self) -> "ClassificationRequest":
        try:
            from ..domain.classification import build_classification_path

            classification_path = build_classification_path(
                domain=self.domain,
                category=self.category,
                subcategory=self.subcategory,
            )

            return ClassificationRequest(
                domain=classification_path.domain.value,
                category=classification_path.category,
                subcategory=classification_path.subcategory,
            )
        except Exception as exc:
            raise CreateRequestError(f"Invalid classification request: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        try:
            from ..domain.classification import build_classification_payload

            normalized = self.normalized()
            return build_classification_payload(
                domain=normalized.domain,
                category=normalized.category,
                subcategory=normalized.subcategory,
            )
        except Exception as exc:
            raise CreateRequestError(f"Could not serialize classification request: {exc}") from exc


@dataclass(frozen=True, slots=True)
class GridFootprintRequest:
    """Raster-Footprint des Packages."""

    size_cells_x: int = 1
    size_cells_y: int = 1
    size_cells_z: int = 1
    cell_size_m: float = DEFAULT_CELL_SIZE_M

    def normalized(self) -> "GridFootprintRequest":
        size_cells_x = normalize_positive_int(self.size_cells_x, "size_cells_x")
        size_cells_y = normalize_positive_int(self.size_cells_y, "size_cells_y")
        size_cells_z = normalize_positive_int(self.size_cells_z, "size_cells_z")
        cell_size_m = normalize_positive_float(self.cell_size_m, "cell_size_m")

        return GridFootprintRequest(
            size_cells_x=size_cells_x,
            size_cells_y=size_cells_y,
            size_cells_z=size_cells_z,
            cell_size_m=cell_size_m,
        )

    @property
    def size_cells(self) -> tuple[int, int, int]:
        normalized = self.normalized()
        return (
            normalized.size_cells_x,
            normalized.size_cells_y,
            normalized.size_cells_z,
        )

    @property
    def size_m(self) -> tuple[float, float, float]:
        normalized = self.normalized()
        return (
            normalized.size_cells_x * normalized.cell_size_m,
            normalized.size_cells_y * normalized.cell_size_m,
            normalized.size_cells_z * normalized.cell_size_m,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "size_cells": {
                "x": normalized.size_cells_x,
                "y": normalized.size_cells_y,
                "z": normalized.size_cells_z,
            },
            "size_cells_x": normalized.size_cells_x,
            "size_cells_y": normalized.size_cells_y,
            "size_cells_z": normalized.size_cells_z,
            "cell_size_m": normalized.cell_size_m,
            "size_m": {
                "x": normalized.size_m[0],
                "y": normalized.size_m[1],
                "z": normalized.size_m[2],
            },
        }


@dataclass(frozen=True, slots=True)
class ModelBoundsRequest:
    """Sichtbare Modellgrenzen in Metern."""

    width_m: float
    height_m: float
    depth_m: float

    def normalized(self) -> "ModelBoundsRequest":
        return ModelBoundsRequest(
            width_m=normalize_positive_float(self.width_m, "width_m"),
            height_m=normalize_positive_float(self.height_m, "height_m"),
            depth_m=normalize_positive_float(self.depth_m, "depth_m"),
        )

    def fits_inside(self, footprint: GridFootprintRequest) -> bool:
        normalized = self.normalized()
        max_width, max_height, max_depth = footprint.size_m

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
class AssetRequest:
    """Asset-Referenz für Renderdaten, Vorschau, Textur oder Dokumentation."""

    role: str
    source_path: str
    target_path: str | None = None
    asset_id: str | None = None
    mime_type: str | None = None

    def normalized(self) -> "AssetRequest":
        role = parse_asset_role_value(self.role)
        source_path = clean_required_string(self.source_path, "source_path")
        target_path = clean_optional_string(self.target_path)
        asset_id = (
            normalize_slug(self.asset_id, field_name="asset_id")
            if self.asset_id
            else None
        )
        mime_type = clean_optional_string(self.mime_type)

        return AssetRequest(
            role=role,
            source_path=source_path,
            target_path=target_path,
            asset_id=asset_id,
            mime_type=mime_type,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "role": normalized.role,
            "source_path": normalized.source_path,
            "target_path": normalized.target_path,
            "asset_id": normalized.asset_id,
            "mime_type": normalized.mime_type,
        }


@dataclass(frozen=True, slots=True)
class VisualRequest:
    """Beschreibung der sichtbaren Repräsentation."""

    shape: str = RenderShape.CUBE.value
    fit_mode: str = FitMode.STRICT_INSIDE.value
    fallback_color: str = DEFAULT_FALLBACK_COLOR
    texture_ref: str | None = None
    glb_ref: str | None = None
    model_ref: str | None = None
    icon_ref: str | None = None
    preview_ref: str | None = None
    model_bounds_m: ModelBoundsRequest | None = None

    def normalized(self) -> "VisualRequest":
        shape = parse_render_shape_value(self.shape)
        fit_mode = parse_fit_mode_value(self.fit_mode)
        fallback_color = normalize_color(self.fallback_color)
        texture_ref = clean_optional_string(self.texture_ref)
        glb_ref = clean_optional_string(self.glb_ref)
        model_ref = clean_optional_string(self.model_ref)
        icon_ref = clean_optional_string(self.icon_ref)
        preview_ref = clean_optional_string(self.preview_ref)
        model_bounds_m = (
            self.model_bounds_m.normalized()
            if self.model_bounds_m is not None
            else None
        )

        if not texture_ref and not glb_ref and not model_ref and not fallback_color:
            raise CreateRequestError(
                "Visual request requires at least a texture, a model reference, a GLB reference or a fallback color."
            )

        if shape == RenderShape.CUSTOM_GLB.value and not glb_ref and not model_ref:
            raise CreateRequestError(
                "Visual shape 'custom_glb' requires glb_ref or model_ref."
            )

        return VisualRequest(
            shape=shape,
            fit_mode=fit_mode,
            fallback_color=fallback_color,
            texture_ref=texture_ref,
            glb_ref=glb_ref,
            model_ref=model_ref,
            icon_ref=icon_ref,
            preview_ref=preview_ref,
            model_bounds_m=model_bounds_m,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "shape": normalized.shape,
            "fit_mode": normalized.fit_mode,
            "fallback_color": normalized.fallback_color,
            "texture_ref": normalized.texture_ref,
            "glb_ref": normalized.glb_ref,
            "model_ref": normalized.model_ref,
            "icon_ref": normalized.icon_ref,
            "preview_ref": normalized.preview_ref,
            "model_bounds_m": (
                normalized.model_bounds_m.to_dict()
                if normalized.model_bounds_m is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PlacementRequest:
    """Platzierungsanforderungen für editor/placement.json."""

    placement_mode: str
    allowed_surfaces: tuple[str, ...] = field(default_factory=tuple)
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    rotation_allowed: bool = True
    rotation_steps: tuple[int, ...] = (0, 90, 180, 270)
    snap_mode: str = SnapMode.GRID.value
    requires_support: bool | None = None

    def normalized(self, *, object_kind: str | None = None) -> "PlacementRequest":
        placement_mode = parse_placement_mode_value(self.placement_mode)
        snap_mode = parse_snap_mode_value(self.snap_mode)
        allowed_surfaces = normalize_string_tuple(self.allowed_surfaces)
        allowed_hosts = normalize_string_tuple(self.allowed_hosts)
        rotation_allowed = bool(self.rotation_allowed)
        rotation_steps = normalize_rotation_steps(self.rotation_steps)
        requires_support = (
            None if self.requires_support is None else bool(self.requires_support)
        )

        if object_kind:
            try:
                from ..domain.placement_modes import validate_placement_mode_for_object_kind

                is_valid, messages = validate_placement_mode_for_object_kind(
                    placement_mode=placement_mode,
                    object_kind=object_kind,
                )
                if not is_valid:
                    raise CreateRequestError(" ".join(messages))
            except CreateRequestError:
                raise
            except Exception as exc:
                raise CreateRequestError(
                    f"Could not validate placement mode for object kind: {exc}"
                ) from exc

        return PlacementRequest(
            placement_mode=placement_mode,
            allowed_surfaces=allowed_surfaces,
            allowed_hosts=allowed_hosts,
            rotation_allowed=rotation_allowed,
            rotation_steps=rotation_steps,
            snap_mode=snap_mode,
            requires_support=requires_support,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "placement_mode": normalized.placement_mode,
            "allowed_surfaces": list(normalized.allowed_surfaces),
            "allowed_hosts": list(normalized.allowed_hosts),
            "rotation_allowed": normalized.rotation_allowed,
            "rotation_steps": list(normalized.rotation_steps),
            "snap_mode": normalized.snap_mode,
            "requires_support": normalized.requires_support,
            "grid_footprint_is_placement_truth": True,
            "visual_model_must_remain_inside_footprint": True,
        }


@dataclass(frozen=True, slots=True)
class VariantRequest:
    """Eine auswählbare Variante derselben Family."""

    variant_id: str
    label: str | None = None
    description: str = ""
    overrides: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "VariantRequest":
        variant_id = normalize_slug(self.variant_id, field_name="variant_id")
        label = clean_optional_string(self.label) or variant_id
        description = clean_optional_string(self.description) or ""
        overrides = dict(self.overrides or {})

        return VariantRequest(
            variant_id=variant_id,
            label=label,
            description=description,
            overrides=overrides,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "variant_id": normalized.variant_id,
            "label": normalized.label,
            "description": normalized.description,
            "overrides": dict(normalized.overrides),
        }


@dataclass(frozen=True, slots=True)
class VariantsRequest:
    """Variantenkonfiguration eines VPLIB-Packages."""

    mode: str = VariantMode.SINGLE.value
    default_variant_id: str = DEFAULT_VARIANT_ID
    variants: tuple[VariantRequest, ...] = field(default_factory=tuple)

    def normalized(self) -> "VariantsRequest":
        mode = parse_variant_mode_value(self.mode)
        default_variant_id = normalize_slug(
            self.default_variant_id or DEFAULT_VARIANT_ID,
            field_name="default_variant_id",
        )

        variants = tuple(variant.normalized() for variant in self.variants)

        if not variants:
            variants = (
                VariantRequest(
                    variant_id=default_variant_id,
                    label="Default",
                    description="Default variant.",
                    overrides={},
                ).normalized(),
            )

        variant_ids = {variant.variant_id for variant in variants}
        if default_variant_id not in variant_ids:
            variants = (
                VariantRequest(
                    variant_id=default_variant_id,
                    label="Default",
                    description="Default variant.",
                    overrides={},
                ).normalized(),
                *variants,
            )

        if mode == VariantMode.SINGLE.value and len(variants) > 1:
            mode = VariantMode.MULTIPLE.value

        return VariantsRequest(
            mode=mode,
            default_variant_id=default_variant_id,
            variants=variants,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "mode": normalized.mode,
            "default_variant_id": normalized.default_variant_id,
            "variants": [variant.to_dict() for variant in normalized.variants],
        }


@dataclass(frozen=True, slots=True)
class PhysicalRequest:
    """Optionale physische Daten für physical/*.json."""

    real_width_m: float | None = None
    real_height_m: float | None = None
    real_depth_m: float | None = None
    wall_thickness_m: float | None = None
    volume_m3: float | None = None
    mass_kg: float | None = None
    density_kg_m3: float | None = None
    raw_density_kg_m3: float | None = None
    load_bearing: bool | None = None
    fire_class: str | None = None

    def normalized(self) -> "PhysicalRequest":
        return PhysicalRequest(
            real_width_m=normalize_optional_positive_float(self.real_width_m, "real_width_m"),
            real_height_m=normalize_optional_positive_float(self.real_height_m, "real_height_m"),
            real_depth_m=normalize_optional_positive_float(self.real_depth_m, "real_depth_m"),
            wall_thickness_m=normalize_optional_positive_float(self.wall_thickness_m, "wall_thickness_m"),
            volume_m3=normalize_optional_positive_float(self.volume_m3, "volume_m3"),
            mass_kg=normalize_optional_positive_float(self.mass_kg, "mass_kg"),
            density_kg_m3=normalize_optional_positive_float(self.density_kg_m3, "density_kg_m3"),
            raw_density_kg_m3=normalize_optional_positive_float(self.raw_density_kg_m3, "raw_density_kg_m3"),
            load_bearing=None if self.load_bearing is None else bool(self.load_bearing),
            fire_class=clean_optional_string(self.fire_class),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "real_width_m": normalized.real_width_m,
            "real_height_m": normalized.real_height_m,
            "real_depth_m": normalized.real_depth_m,
            "wall_thickness_m": normalized.wall_thickness_m,
            "volume_m3": normalized.volume_m3,
            "mass_kg": normalized.mass_kg,
            "density_kg_m3": normalized.density_kg_m3,
            "raw_density_kg_m3": normalized.raw_density_kg_m3,
            "load_bearing": normalized.load_bearing,
            "fire_class": normalized.fire_class,
        }


@dataclass(frozen=True, slots=True)
class MaterialRequest:
    """Optionale Materialdaten für material/*.json."""

    material_id: str | None = None
    material_class: str | None = None
    material_name: str | None = None
    surface_finish: str | None = None
    thermal_conductivity: float | None = None
    u_value: float | None = None
    compressive_strength: float | None = None

    def normalized(self) -> "MaterialRequest":
        return MaterialRequest(
            material_id=(
                normalize_slug(self.material_id, field_name="material_id")
                if self.material_id
                else None
            ),
            material_class=clean_optional_string(self.material_class),
            material_name=clean_optional_string(self.material_name),
            surface_finish=clean_optional_string(self.surface_finish),
            thermal_conductivity=normalize_optional_positive_float(
                self.thermal_conductivity,
                "thermal_conductivity",
            ),
            u_value=normalize_optional_positive_float(self.u_value, "u_value"),
            compressive_strength=normalize_optional_positive_float(
                self.compressive_strength,
                "compressive_strength",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "material_id": normalized.material_id,
            "material_class": normalized.material_class,
            "material_name": normalized.material_name,
            "surface_finish": normalized.surface_finish,
            "thermal_conductivity": normalized.thermal_conductivity,
            "u_value": normalized.u_value,
            "compressive_strength": normalized.compressive_strength,
        }


@dataclass(frozen=True, slots=True)
class CalculationRequest:
    """Deklarative Berechnungsdaten."""

    variables: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    formulas: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    quantities: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    constraints: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    measure_logic: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationRequest":
        return CalculationRequest(
            variables=tuple(dict(item) for item in self.variables or ()),
            formulas=tuple(dict(item) for item in self.formulas or ()),
            quantities=tuple(dict(item) for item in self.quantities or ()),
            constraints=tuple(dict(item) for item in self.constraints or ()),
            measure_logic=dict(self.measure_logic or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "variables": [dict(item) for item in normalized.variables],
            "formulas": [dict(item) for item in normalized.formulas],
            "quantities": [dict(item) for item in normalized.quantities],
            "constraints": [dict(item) for item in normalized.constraints],
            "measure_logic": dict(normalized.measure_logic),
        }


@dataclass(frozen=True, slots=True)
class DynamicRequest:
    """Deklarative Daten für adaptive Systeme."""

    context_rules: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    bindings: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    generator: Mapping[str, Any] = field(default_factory=dict)
    parameters: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)

    def normalized(self) -> "DynamicRequest":
        return DynamicRequest(
            context_rules=tuple(dict(item) for item in self.context_rules or ()),
            bindings=tuple(dict(item) for item in self.bindings or ()),
            generator=dict(self.generator or {}),
            parameters=tuple(dict(item) for item in self.parameters or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "context_rules": [dict(item) for item in normalized.context_rules],
            "bindings": [dict(item) for item in normalized.bindings],
            "generator": dict(normalized.generator),
            "parameters": [dict(item) for item in normalized.parameters],
        }


@dataclass(frozen=True, slots=True)
class ManufacturerRequest:
    """Hersteller-Overlay-Vorbereitung."""

    manufacturer_allowed: bool = False
    overlay_level: str = "none"
    override_slots: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    required_product_fields: tuple[str, ...] = field(default_factory=tuple)
    product_categories: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "ManufacturerRequest":
        return ManufacturerRequest(
            manufacturer_allowed=bool(self.manufacturer_allowed),
            overlay_level=clean_required_string(self.overlay_level or "none", "overlay_level"),
            override_slots=tuple(dict(item) for item in self.override_slots or ()),
            required_product_fields=normalize_string_tuple(self.required_product_fields),
            product_categories=normalize_string_tuple(self.product_categories),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "manufacturer_allowed": normalized.manufacturer_allowed,
            "overlay_level": normalized.overlay_level,
            "override_slots": [dict(item) for item in normalized.override_slots],
            "required_product_fields": list(normalized.required_product_fields),
            "product_categories": list(normalized.product_categories),
        }


@dataclass(frozen=True, slots=True)
class CreateOptions:
    """Optionen für den Erstellvorgang."""

    overwrite_existing: bool = False
    create_archive: bool = False
    validate_after_create: bool = True
    include_docs: bool = False
    include_tests: bool = False
    strict: bool = True

    def normalized(self) -> "CreateOptions":
        return CreateOptions(
            overwrite_existing=bool(self.overwrite_existing),
            create_archive=bool(self.create_archive),
            validate_after_create=bool(self.validate_after_create),
            include_docs=bool(self.include_docs),
            include_tests=bool(self.include_tests),
            strict=bool(self.strict),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "overwrite_existing": normalized.overwrite_existing,
            "create_archive": normalized.create_archive,
            "validate_after_create": normalized.validate_after_create,
            "include_docs": normalized.include_docs,
            "include_tests": normalized.include_tests,
            "strict": normalized.strict,
        }


@dataclass(frozen=True, slots=True)
class CreateRequest:
    """
    Zentraler Erstellwunsch für ein neues VPLIB-Package.

    Diese Struktur ist der spätere Eingang für planning/creation_planner.py.
    """

    identity: IdentityRequest
    classification: ClassificationRequest
    object_kind: str
    grid: GridFootprintRequest = field(default_factory=GridFootprintRequest)
    variants: VariantsRequest = field(default_factory=VariantsRequest)
    visual: VisualRequest = field(default_factory=VisualRequest)
    placement: PlacementRequest | None = None
    assets: tuple[AssetRequest, ...] = field(default_factory=tuple)
    physical: PhysicalRequest = field(default_factory=PhysicalRequest)
    material: MaterialRequest = field(default_factory=MaterialRequest)
    calculation: CalculationRequest = field(default_factory=CalculationRequest)
    dynamic: DynamicRequest = field(default_factory=DynamicRequest)
    manufacturer: ManufacturerRequest = field(default_factory=ManufacturerRequest)
    options: CreateOptions = field(default_factory=CreateOptions)

    def normalized(self) -> "CreateRequest":
        identity = self.identity.normalized()
        classification = self.classification.normalized()
        object_kind = parse_object_kind_value(self.object_kind)
        grid = self.grid.normalized()

        try:
            from ..domain.object_kinds import assert_valid_grid_footprint_for_object_kind

            assert_valid_grid_footprint_for_object_kind(object_kind, grid.size_cells)
        except Exception as exc:
            raise CreateRequestError(f"Invalid grid footprint for object kind: {exc}") from exc

        visual = self.visual.normalized()
        if visual.model_bounds_m and not visual.model_bounds_m.fits_inside(grid):
            raise CreateRequestError(
                "Visual model bounds must not exceed the occupied grid footprint."
            )

        placement = (
            self.placement.normalized(object_kind=object_kind)
            if self.placement is not None
            else default_placement_for_object_kind(object_kind)
        )

        variants = self.variants.normalized()
        assets = tuple(asset.normalized() for asset in self.assets)
        physical = self.physical.normalized()
        material = self.material.normalized()
        calculation = self.calculation.normalized()
        dynamic = self.dynamic.normalized()
        manufacturer = self.manufacturer.normalized()
        options = self.options.normalized()

        if object_kind == "adaptive_system":
            if not dynamic.context_rules and not dynamic.generator:
                raise CreateRequestError(
                    "Adaptive systems require dynamic context rules or generator metadata."
                )

        return CreateRequest(
            identity=identity,
            classification=classification,
            object_kind=object_kind,
            grid=grid,
            variants=variants,
            visual=visual,
            placement=placement,
            assets=assets,
            physical=physical,
            material=material,
            calculation=calculation,
            dynamic=dynamic,
            manufacturer=manufacturer,
            options=options,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": CREATE_REQUEST_SCHEMA_VERSION,
            "identity": normalized.identity.to_dict(),
            "classification": normalized.classification.to_dict(),
            "object_kind": normalized.object_kind,
            "grid": normalized.grid.to_dict(),
            "variants": normalized.variants.to_dict(),
            "visual": normalized.visual.to_dict(),
            "placement": normalized.placement.to_dict() if normalized.placement else None,
            "assets": [asset.to_dict() for asset in normalized.assets],
            "physical": normalized.physical.to_dict(),
            "material": normalized.material.to_dict(),
            "calculation": normalized.calculation.to_dict(),
            "dynamic": normalized.dynamic.to_dict(),
            "manufacturer": normalized.manufacturer.to_dict(),
            "options": normalized.options.to_dict(),
        }


def create_request_from_mapping(data: Mapping[str, Any]) -> CreateRequest:
    """
    Baut einen CreateRequest aus einem Mapping.

    Diese Funktion ist bewusst tolerant gegenüber fehlenden optionalen Bereichen.
    """
    try:
        if not isinstance(data, Mapping):
            raise CreateRequestError("CreateRequest input must be a mapping.")

        identity = identity_request_from_mapping(require_mapping(data, "identity"))
        classification = classification_request_from_mapping(require_mapping(data, "classification"))
        object_kind = clean_required_string(data.get("object_kind"), "object_kind")

        grid = grid_request_from_mapping(optional_mapping(data, "grid"))
        variants = variants_request_from_mapping(optional_mapping(data, "variants"))
        visual = visual_request_from_mapping(optional_mapping(data, "visual"))
        placement_data = optional_mapping_or_none(data, "placement")
        placement = (
            placement_request_from_mapping(placement_data)
            if placement_data is not None
            else None
        )

        assets = tuple(
            asset_request_from_mapping(item)
            for item in data.get("assets", ()) or ()
            if isinstance(item, Mapping)
        )

        physical = physical_request_from_mapping(optional_mapping(data, "physical"))
        material = material_request_from_mapping(optional_mapping(data, "material"))
        calculation = calculation_request_from_mapping(optional_mapping(data, "calculation"))
        dynamic = dynamic_request_from_mapping(optional_mapping(data, "dynamic"))
        manufacturer = manufacturer_request_from_mapping(optional_mapping(data, "manufacturer"))
        options = create_options_from_mapping(optional_mapping(data, "options"))

        return CreateRequest(
            identity=identity,
            classification=classification,
            object_kind=object_kind,
            grid=grid,
            variants=variants,
            visual=visual,
            placement=placement,
            assets=assets,
            physical=physical,
            material=material,
            calculation=calculation,
            dynamic=dynamic,
            manufacturer=manufacturer,
            options=options,
        ).normalized()
    except CreateRequestError:
        raise
    except Exception as exc:
        raise CreateRequestError(f"Could not build CreateRequest: {exc}") from exc


def identity_request_from_mapping(data: Mapping[str, Any]) -> IdentityRequest:
    return IdentityRequest(
        family_id=clean_required_string(data.get("family_id"), "family_id"),
        family_name=clean_required_string(
            data.get("family_name") or data.get("name") or data.get("display_name"),
            "family_name",
        ),
        package_id=clean_optional_string(data.get("package_id")),
        family_slug=clean_optional_string(data.get("family_slug") or data.get("slug")),
        display_name=clean_optional_string(data.get("display_name")),
        short_name=clean_optional_string(data.get("short_name")),
        description=clean_optional_string(data.get("description")) or "",
        version=clean_optional_string(data.get("version")) or DEFAULT_PACKAGE_VERSION,
        author=clean_optional_string(data.get("author")),
        tags=tuple(data.get("tags", ()) or ()),
    )


def classification_request_from_mapping(data: Mapping[str, Any]) -> ClassificationRequest:
    return ClassificationRequest(
        domain=clean_required_string(data.get("domain") or data.get("tab"), "domain"),
        category=clean_required_string(data.get("category"), "category"),
        subcategory=clean_required_string(data.get("subcategory"), "subcategory"),
    )


def grid_request_from_mapping(data: Mapping[str, Any]) -> GridFootprintRequest:
    size_cells = data.get("size_cells") if isinstance(data.get("size_cells"), Mapping) else {}

    return GridFootprintRequest(
        size_cells_x=data.get("size_cells_x", size_cells.get("x", 1)),
        size_cells_y=data.get("size_cells_y", size_cells.get("y", 1)),
        size_cells_z=data.get("size_cells_z", size_cells.get("z", 1)),
        cell_size_m=data.get("cell_size_m", DEFAULT_CELL_SIZE_M),
    )


def visual_request_from_mapping(data: Mapping[str, Any]) -> VisualRequest:
    bounds_data = data.get("model_bounds_m")
    model_bounds_m = (
        ModelBoundsRequest(
            width_m=bounds_data.get("width_m", bounds_data.get("width", 1.0)),
            height_m=bounds_data.get("height_m", bounds_data.get("height", 1.0)),
            depth_m=bounds_data.get("depth_m", bounds_data.get("depth", 1.0)),
        )
        if isinstance(bounds_data, Mapping)
        else None
    )

    return VisualRequest(
        shape=data.get("shape", RenderShape.CUBE.value),
        fit_mode=data.get("fit_mode", FitMode.STRICT_INSIDE.value),
        fallback_color=data.get("fallback_color", DEFAULT_FALLBACK_COLOR),
        texture_ref=clean_optional_string(data.get("texture_ref")),
        glb_ref=clean_optional_string(data.get("glb_ref")),
        model_ref=clean_optional_string(data.get("model_ref")),
        icon_ref=clean_optional_string(data.get("icon_ref")),
        preview_ref=clean_optional_string(data.get("preview_ref")),
        model_bounds_m=model_bounds_m,
    )


def placement_request_from_mapping(data: Mapping[str, Any]) -> PlacementRequest:
    return PlacementRequest(
        placement_mode=clean_required_string(data.get("placement_mode"), "placement_mode"),
        allowed_surfaces=tuple(data.get("allowed_surfaces", ()) or ()),
        allowed_hosts=tuple(data.get("allowed_hosts", ()) or ()),
        rotation_allowed=bool(data.get("rotation_allowed", True)),
        rotation_steps=tuple(data.get("rotation_steps", (0, 90, 180, 270)) or ()),
        snap_mode=data.get("snap_mode", SnapMode.GRID.value),
        requires_support=data.get("requires_support"),
    )


def variants_request_from_mapping(data: Mapping[str, Any]) -> VariantsRequest:
    variants_data = data.get("variants", ()) or ()

    variants = tuple(
        VariantRequest(
            variant_id=clean_required_string(item.get("variant_id") or item.get("id"), "variant_id"),
            label=clean_optional_string(item.get("label") or item.get("name")),
            description=clean_optional_string(item.get("description")) or "",
            overrides=dict(item.get("overrides", {}) or {}),
        )
        for item in variants_data
        if isinstance(item, Mapping)
    )

    return VariantsRequest(
        mode=data.get("mode", VariantMode.SINGLE.value),
        default_variant_id=data.get("default_variant_id", DEFAULT_VARIANT_ID),
        variants=variants,
    )


def asset_request_from_mapping(data: Mapping[str, Any]) -> AssetRequest:
    return AssetRequest(
        role=clean_required_string(data.get("role"), "role"),
        source_path=clean_required_string(data.get("source_path") or data.get("path"), "source_path"),
        target_path=clean_optional_string(data.get("target_path")),
        asset_id=clean_optional_string(data.get("asset_id")),
        mime_type=clean_optional_string(data.get("mime_type")),
    )


def physical_request_from_mapping(data: Mapping[str, Any]) -> PhysicalRequest:
    return PhysicalRequest(
        real_width_m=data.get("real_width_m"),
        real_height_m=data.get("real_height_m"),
        real_depth_m=data.get("real_depth_m"),
        wall_thickness_m=data.get("wall_thickness_m"),
        volume_m3=data.get("volume_m3"),
        mass_kg=data.get("mass_kg"),
        density_kg_m3=data.get("density_kg_m3"),
        raw_density_kg_m3=data.get("raw_density_kg_m3"),
        load_bearing=data.get("load_bearing"),
        fire_class=clean_optional_string(data.get("fire_class")),
    )


def material_request_from_mapping(data: Mapping[str, Any]) -> MaterialRequest:
    return MaterialRequest(
        material_id=clean_optional_string(data.get("material_id")),
        material_class=clean_optional_string(data.get("material_class")),
        material_name=clean_optional_string(data.get("material_name")),
        surface_finish=clean_optional_string(data.get("surface_finish")),
        thermal_conductivity=data.get("thermal_conductivity"),
        u_value=data.get("u_value"),
        compressive_strength=data.get("compressive_strength"),
    )


def calculation_request_from_mapping(data: Mapping[str, Any]) -> CalculationRequest:
    return CalculationRequest(
        variables=tuple(item for item in data.get("variables", ()) or () if isinstance(item, Mapping)),
        formulas=tuple(item for item in data.get("formulas", ()) or () if isinstance(item, Mapping)),
        quantities=tuple(item for item in data.get("quantities", ()) or () if isinstance(item, Mapping)),
        constraints=tuple(item for item in data.get("constraints", ()) or () if isinstance(item, Mapping)),
        measure_logic=dict(data.get("measure_logic", {}) or {}),
    )


def dynamic_request_from_mapping(data: Mapping[str, Any]) -> DynamicRequest:
    return DynamicRequest(
        context_rules=tuple(item for item in data.get("context_rules", ()) or () if isinstance(item, Mapping)),
        bindings=tuple(item for item in data.get("bindings", ()) or () if isinstance(item, Mapping)),
        generator=dict(data.get("generator", {}) or {}),
        parameters=tuple(item for item in data.get("parameters", ()) or () if isinstance(item, Mapping)),
    )


def manufacturer_request_from_mapping(data: Mapping[str, Any]) -> ManufacturerRequest:
    return ManufacturerRequest(
        manufacturer_allowed=bool(data.get("manufacturer_allowed", False)),
        overlay_level=data.get("overlay_level", "none"),
        override_slots=tuple(item for item in data.get("override_slots", ()) or () if isinstance(item, Mapping)),
        required_product_fields=tuple(data.get("required_product_fields", ()) or ()),
        product_categories=tuple(data.get("product_categories", ()) or ()),
    )


def create_options_from_mapping(data: Mapping[str, Any]) -> CreateOptions:
    return CreateOptions(
        overwrite_existing=bool(data.get("overwrite_existing", False)),
        create_archive=bool(data.get("create_archive", False)),
        validate_after_create=bool(data.get("validate_after_create", True)),
        include_docs=bool(data.get("include_docs", False)),
        include_tests=bool(data.get("include_tests", False)),
        strict=bool(data.get("strict", True)),
    )


def default_placement_for_object_kind(object_kind: str) -> PlacementRequest:
    try:
        from ..domain.placement_modes import get_default_placement_mode_for_object_kind

        placement_mode = get_default_placement_mode_for_object_kind(object_kind).value
    except Exception:
        placement_mode = "centered"

    return PlacementRequest(placement_mode=placement_mode).normalized(object_kind=object_kind)


@lru_cache(maxsize=128)
def parse_object_kind_value(value: Any) -> str:
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise CreateRequestError(f"Invalid object_kind {value!r}: {exc}") from exc


@lru_cache(maxsize=128)
def parse_placement_mode_value(value: Any) -> str:
    try:
        from ..domain.placement_modes import ensure_placement_mode_value

        return ensure_placement_mode_value(value)
    except Exception as exc:
        raise CreateRequestError(f"Invalid placement_mode {value!r}: {exc}") from exc


@lru_cache(maxsize=128)
def parse_variant_mode_value(value: Any) -> str:
    try:
        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return VariantMode(raw).value
    except Exception as exc:
        raise CreateRequestError(f"Invalid variant mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_render_shape_value(value: Any) -> str:
    try:
        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return RenderShape(raw).value
    except Exception as exc:
        raise CreateRequestError(f"Invalid render shape {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_fit_mode_value(value: Any) -> str:
    try:
        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return FitMode(raw).value
    except Exception as exc:
        raise CreateRequestError(f"Invalid fit mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_snap_mode_value(value: Any) -> str:
    try:
        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return SnapMode(raw).value
    except Exception as exc:
        raise CreateRequestError(f"Invalid snap mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_asset_role_value(value: Any) -> str:
    try:
        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return AssetRole(raw).value
    except Exception as exc:
        raise CreateRequestError(f"Invalid asset role {value!r}.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    try:
        cleaned = str(value).strip()
        if not cleaned:
            raise CreateRequestError(f"{field_name} is required.")
        return cleaned
    except CreateRequestError:
        raise
    except Exception as exc:
        raise CreateRequestError(f"{field_name} must be a string-like value.") from exc


def clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def normalize_identifier(value: Any, *, field_name: str) -> str:
    identifier = clean_required_string(value, field_name).lower().replace(" ", "_")

    if not all(part for part in identifier.split(".")):
        raise CreateRequestError(f"{field_name} must not contain empty dot segments.")

    for part in identifier.split("."):
        normalize_slug(part, field_name=field_name)

    return identifier


def normalize_slug(value: Any, *, field_name: str) -> str:
    slug = (
        clean_required_string(value, field_name)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    if not SAFE_ID_RE.match(slug):
        raise CreateRequestError(f"{field_name} contains unsafe characters: {value!r}.")

    return slug


def normalize_color(value: Any) -> str:
    color = clean_optional_string(value) or DEFAULT_FALLBACK_COLOR

    if not SAFE_COLOR_RE.match(color):
        raise CreateRequestError(f"Invalid fallback color {value!r}.")

    return color


def normalize_string_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_positive_int(value: Any, field_name: str) -> int:
    try:
        if isinstance(value, bool):
            raise CreateRequestError(f"{field_name} must be an integer.")

        number = int(value)
        if number < 1:
            raise CreateRequestError(f"{field_name} must be >= 1.")

        return number
    except CreateRequestError:
        raise
    except Exception as exc:
        raise CreateRequestError(f"{field_name} must be a positive integer.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    try:
        if isinstance(value, bool):
            raise CreateRequestError(f"{field_name} must be a number.")

        number = float(value)
        if number <= 0:
            raise CreateRequestError(f"{field_name} must be > 0.")

        return number
    except CreateRequestError:
        raise
    except Exception as exc:
        raise CreateRequestError(f"{field_name} must be a positive number.") from exc


def normalize_optional_positive_float(value: Any, field_name: str) -> float | None:
    if value is None:
        return None

    return normalize_positive_float(value, field_name)


def normalize_rotation_steps(values: Sequence[Any]) -> tuple[int, ...]:
    if not values:
        return (0, 90, 180, 270)

    result: list[int] = []
    seen: set[int] = set()

    for value in values:
        try:
            step = int(value)
        except Exception as exc:
            raise CreateRequestError(f"Invalid rotation step {value!r}.") from exc

        if step < 0 or step >= 360:
            raise CreateRequestError("Rotation steps must be in range 0 <= step < 360.")

        if step not in seen:
            result.append(step)
            seen.add(step)

    if 0 not in seen:
        result.insert(0, 0)

    return tuple(sorted(result))


def require_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)

    if not isinstance(value, Mapping):
        raise CreateRequestError(f"{key} must be an object.")

    return value


def optional_mapping(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})

    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise CreateRequestError(f"{key} must be an object.")

    return value


def optional_mapping_or_none(
    data: Mapping[str, Any],
    key: str,
) -> Mapping[str, Any] | None:
    value = data.get(key)

    if value is None:
        return None

    if not isinstance(value, Mapping):
        raise CreateRequestError(f"{key} must be an object.")

    return value


def clear_create_request_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_object_kind_value.cache_clear()
    parse_placement_mode_value.cache_clear()
    parse_variant_mode_value.cache_clear()
    parse_render_shape_value.cache_clear()
    parse_fit_mode_value.cache_clear()
    parse_snap_mode_value.cache_clear()
    parse_asset_role_value.cache_clear()


__all__ = [
    "CREATE_REQUEST_SCHEMA_VERSION",
    "DEFAULT_CELL_SIZE_M",
    "DEFAULT_FALLBACK_COLOR",
    "DEFAULT_PACKAGE_VERSION",
    "DEFAULT_VARIANT_ID",
    "SAFE_COLOR_RE",
    "SAFE_ID_RE",
    "AssetRequest",
    "AssetRole",
    "CalculationRequest",
    "ClassificationRequest",
    "CreateOptions",
    "CreateRequest",
    "CreateRequestError",
    "DynamicRequest",
    "FitMode",
    "GridFootprintRequest",
    "IdentityRequest",
    "ManufacturerRequest",
    "MaterialRequest",
    "ModelBoundsRequest",
    "PhysicalRequest",
    "PlacementRequest",
    "RenderShape",
    "SnapMode",
    "VariantMode",
    "VariantRequest",
    "VariantsRequest",
    "asset_request_from_mapping",
    "calculation_request_from_mapping",
    "classification_request_from_mapping",
    "clear_create_request_caches",
    "clean_optional_string",
    "clean_required_string",
    "create_options_from_mapping",
    "create_request_from_mapping",
    "default_placement_for_object_kind",
    "dynamic_request_from_mapping",
    "grid_request_from_mapping",
    "identity_request_from_mapping",
    "manufacturer_request_from_mapping",
    "material_request_from_mapping",
    "normalize_color",
    "normalize_identifier",
    "normalize_optional_positive_float",
    "normalize_positive_float",
    "normalize_positive_int",
    "normalize_rotation_steps",
    "normalize_slug",
    "normalize_string_tuple",
    "optional_mapping",
    "optional_mapping_or_none",
    "parse_asset_role_value",
    "parse_fit_mode_value",
    "parse_object_kind_value",
    "parse_placement_mode_value",
    "parse_render_shape_value",
    "parse_snap_mode_value",
    "parse_variant_mode_value",
    "physical_request_from_mapping",
    "placement_request_from_mapping",
    "require_mapping",
    "variants_request_from_mapping",
    "visual_request_from_mapping",
]