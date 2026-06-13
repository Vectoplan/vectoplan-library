# services/vectoplan-library/src/vplib/defaults/material_defaults.py
"""
Material defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    material/base.json
    optional: material/performance.json
    optional: material/surfaces.json
    optional: material/layers.json
    optional: material/finishes.json

Material-Daten beschreiben Materialidentität, technische Materialwerte,
Oberflächen, Schichten und einfache Finish-Informationen.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


MATERIAL_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.material_defaults.v1"
MATERIAL_BASE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.material.base.v1"
MATERIAL_PERFORMANCE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.material.performance.v1"
MATERIAL_SURFACES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.material.surfaces.v1"
MATERIAL_LAYERS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.material.layers.v1"
MATERIAL_FINISHES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.material.finishes.v1"

DEFAULT_MATERIAL_ID: Final[str] = "default_material"
DEFAULT_MATERIAL_NAME: Final[str] = "Default Material"
DEFAULT_SURFACE_ID: Final[str] = "default_surface"
DEFAULT_LAYER_ID: Final[str] = "default_layer"
DEFAULT_FINISH_ID: Final[str] = "default_finish"
DEFAULT_FALLBACK_COLOR: Final[str] = "#9CA3AF"

SAFE_MATERIAL_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)
SAFE_HEX_COLOR_RE: Final[re.Pattern[str]] = re.compile(
    r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$"
)


class MaterialDefaultsError(ValueError):
    """Wird ausgelöst, wenn Material-Defaults ungültig erzeugt werden."""


class MaterialClass(str, Enum):
    """Kanonische Materialklassen."""

    GENERIC = "generic"
    CONCRETE = "concrete"
    MASONRY = "masonry"
    DRYWALL = "drywall"
    TIMBER = "timber"
    STEEL = "steel"
    ALUMINUM = "aluminum"
    GLASS = "glass"
    PLASTIC = "plastic"
    INSULATION = "insulation"
    COMPOSITE = "composite"
    FINISH = "finish"
    EQUIPMENT = "equipment"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


class MaterialRole(str, Enum):
    """Fachliche Rolle eines Materials."""

    PRIMARY = "primary"
    STRUCTURAL = "structural"
    FINISH = "finish"
    INSULATION = "insulation"
    SURFACE = "surface"
    CORE = "core"
    AUXILIARY = "auxiliary"
    UNKNOWN = "unknown"

    @property
    def key(self) -> str:
        return str(self.value)


class SurfaceSide(str, Enum):
    """Seite/Oberfläche eines Materials oder Elements."""

    ALL = "all"
    FRONT = "front"
    BACK = "back"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    INNER = "inner"
    OUTER = "outer"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class SurfaceFinish(str, Enum):
    """Oberflächenfinish."""

    NONE = "none"
    RAW = "raw"
    SMOOTH = "smooth"
    ROUGH = "rough"
    PAINTED = "painted"
    COATED = "coated"
    PLASTERED = "plastered"
    POLISHED = "polished"
    BRUSHED = "brushed"
    TEXTURED = "textured"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class LayerFunction(str, Enum):
    """Funktion einer Materialschicht."""

    CORE = "core"
    STRUCTURAL = "structural"
    FINISH = "finish"
    INSULATION = "insulation"
    AIR_GAP = "air_gap"
    MEMBRANE = "membrane"
    SURFACE = "surface"
    OTHER = "other"

    @property
    def key(self) -> str:
        return str(self.value)


class FireReactionClass(str, Enum):
    """Vereinfachte Brandverhaltensklasse."""

    UNKNOWN = "unknown"
    A1 = "a1"
    A2 = "a2"
    B = "b"
    C = "c"
    D = "d"
    E = "e"
    F = "f"

    @property
    def key(self) -> str:
        return str(self.value)


class PerformanceValueSource(str, Enum):
    """Quelle technischer Materialwerte."""

    UNKNOWN = "unknown"
    EXPLICIT = "explicit"
    COMPUTED = "computed"
    ESTIMATED = "estimated"
    MANUFACTURER = "manufacturer"
    STANDARD = "standard"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class MaterialBaseDefaults:
    """Defaults für material/base.json."""

    material_id: str = DEFAULT_MATERIAL_ID
    material_name: str = DEFAULT_MATERIAL_NAME
    material_class: str = MaterialClass.GENERIC.value
    material_role: str = MaterialRole.PRIMARY.value
    description: str = ""
    manufacturer_id: str | None = None
    product_id: str | None = None
    standard_refs: tuple[str, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialBaseDefaults":
        return MaterialBaseDefaults(
            material_id=normalize_material_key(self.material_id, "material_id"),
            material_name=clean_required_string(self.material_name, "material_name"),
            material_class=parse_material_class_value(self.material_class),
            material_role=parse_material_role_value(self.material_role),
            description=clean_optional_string(self.description) or "",
            manufacturer_id=clean_optional_string(self.manufacturer_id),
            product_id=clean_optional_string(self.product_id),
            standard_refs=normalize_string_tuple(self.standard_refs),
            tags=normalize_string_tuple(self.tags),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MATERIAL_BASE_DOCUMENT_SCHEMA_VERSION,
            "material_id": normalized.material_id,
            "material_name": normalized.material_name,
            "material_class": normalized.material_class,
            "material_role": normalized.material_role,
            "description": normalized.description,
            "manufacturer_id": normalized.manufacturer_id,
            "product_id": normalized.product_id,
            "standard_refs": list(normalized.standard_refs),
            "tags": list(normalized.tags),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class MaterialPerformanceDefaults:
    """Defaults für material/performance.json."""

    density_kg_m3: float | None = None
    raw_density_kg_m3: float | None = None
    thermal_conductivity_w_mk: float | None = None
    thermal_transmittance_w_m2k: float | None = None
    compressive_strength_mpa: float | None = None
    tensile_strength_mpa: float | None = None
    bending_strength_mpa: float | None = None
    elastic_modulus_gpa: float | None = None
    acoustic_rating_db: float | None = None
    fire_reaction_class: str = FireReactionClass.UNKNOWN.value
    value_source: str = PerformanceValueSource.UNKNOWN.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialPerformanceDefaults":
        return MaterialPerformanceDefaults(
            density_kg_m3=normalize_optional_non_negative_float(self.density_kg_m3, "density_kg_m3"),
            raw_density_kg_m3=normalize_optional_non_negative_float(self.raw_density_kg_m3, "raw_density_kg_m3"),
            thermal_conductivity_w_mk=normalize_optional_non_negative_float(
                self.thermal_conductivity_w_mk,
                "thermal_conductivity_w_mk",
            ),
            thermal_transmittance_w_m2k=normalize_optional_non_negative_float(
                self.thermal_transmittance_w_m2k,
                "thermal_transmittance_w_m2k",
            ),
            compressive_strength_mpa=normalize_optional_non_negative_float(
                self.compressive_strength_mpa,
                "compressive_strength_mpa",
            ),
            tensile_strength_mpa=normalize_optional_non_negative_float(
                self.tensile_strength_mpa,
                "tensile_strength_mpa",
            ),
            bending_strength_mpa=normalize_optional_non_negative_float(
                self.bending_strength_mpa,
                "bending_strength_mpa",
            ),
            elastic_modulus_gpa=normalize_optional_non_negative_float(
                self.elastic_modulus_gpa,
                "elastic_modulus_gpa",
            ),
            acoustic_rating_db=normalize_optional_non_negative_float(
                self.acoustic_rating_db,
                "acoustic_rating_db",
            ),
            fire_reaction_class=parse_fire_reaction_class_value(self.fire_reaction_class),
            value_source=parse_performance_value_source_value(self.value_source),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MATERIAL_PERFORMANCE_DOCUMENT_SCHEMA_VERSION,
            "density_kg_m3": normalized.density_kg_m3,
            "raw_density_kg_m3": normalized.raw_density_kg_m3,
            "thermal_conductivity_w_mk": normalized.thermal_conductivity_w_mk,
            "thermal_transmittance_w_m2k": normalized.thermal_transmittance_w_m2k,
            "compressive_strength_mpa": normalized.compressive_strength_mpa,
            "tensile_strength_mpa": normalized.tensile_strength_mpa,
            "bending_strength_mpa": normalized.bending_strength_mpa,
            "elastic_modulus_gpa": normalized.elastic_modulus_gpa,
            "acoustic_rating_db": normalized.acoustic_rating_db,
            "fire_reaction_class": normalized.fire_reaction_class,
            "value_source": normalized.value_source,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class MaterialSurfaceDefaults:
    """Eine Oberfläche für material/surfaces.json."""

    surface_id: str = DEFAULT_SURFACE_ID
    side: str = SurfaceSide.ALL.value
    label: str | None = None
    surface_finish: str = SurfaceFinish.NONE.value
    fallback_color: str = DEFAULT_FALLBACK_COLOR
    texture_ref: str | None = None
    roughness: float | None = None
    metallic: float | None = None
    opacity: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialSurfaceDefaults":
        surface_id = normalize_material_key(self.surface_id, "surface_id")

        return MaterialSurfaceDefaults(
            surface_id=surface_id,
            side=parse_surface_side_value(self.side),
            label=clean_optional_string(self.label) or surface_id,
            surface_finish=parse_surface_finish_value(self.surface_finish),
            fallback_color=normalize_color(self.fallback_color),
            texture_ref=clean_optional_string(self.texture_ref),
            roughness=normalize_optional_unit_interval_float(self.roughness, "roughness"),
            metallic=normalize_optional_unit_interval_float(self.metallic, "metallic"),
            opacity=normalize_optional_unit_interval_float(self.opacity, "opacity"),
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "surface_id": normalized.surface_id,
            "side": normalized.side,
            "label": normalized.label,
            "surface_finish": normalized.surface_finish,
            "fallback_color": normalized.fallback_color,
            "texture_ref": normalized.texture_ref,
            "roughness": normalized.roughness,
            "metallic": normalized.metallic,
            "opacity": normalized.opacity,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class MaterialSurfacesDefaults:
    """Defaults für material/surfaces.json."""

    surfaces: tuple[MaterialSurfaceDefaults, ...] = field(default_factory=tuple)
    default_surface_id: str = DEFAULT_SURFACE_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialSurfacesDefaults":
        default_surface_id = normalize_material_key(self.default_surface_id, "default_surface_id")
        surfaces = tuple(surface.normalized() for surface in self.surfaces or ())

        if not surfaces:
            surfaces = (
                MaterialSurfaceDefaults(
                    surface_id=default_surface_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
            )

        surface_ids = [surface.surface_id for surface in surfaces]
        assert_unique_values(surface_ids, "surface_id")

        if default_surface_id not in set(surface_ids):
            surfaces = (
                MaterialSurfaceDefaults(
                    surface_id=default_surface_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
                *surfaces,
            )

        return MaterialSurfacesDefaults(
            surfaces=tuple(sorted(surfaces, key=lambda item: item.surface_id)),
            default_surface_id=default_surface_id,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MATERIAL_SURFACES_DOCUMENT_SCHEMA_VERSION,
            "default_surface_id": normalized.default_surface_id,
            "surfaces": [surface.to_dict() for surface in normalized.surfaces],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class MaterialLayerDefaults:
    """Eine Materialschicht für material/layers.json."""

    layer_id: str = DEFAULT_LAYER_ID
    material_id: str = DEFAULT_MATERIAL_ID
    label: str | None = None
    layer_function: str = LayerFunction.CORE.value
    thickness_m: float | None = None
    density_kg_m3: float | None = None
    thermal_conductivity_w_mk: float | None = None
    sort_order: int = 100
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialLayerDefaults":
        layer_id = normalize_material_key(self.layer_id, "layer_id")

        return MaterialLayerDefaults(
            layer_id=layer_id,
            material_id=normalize_material_key(self.material_id, "material_id"),
            label=clean_optional_string(self.label) or layer_id,
            layer_function=parse_layer_function_value(self.layer_function),
            thickness_m=normalize_optional_positive_float(self.thickness_m, "thickness_m"),
            density_kg_m3=normalize_optional_non_negative_float(self.density_kg_m3, "density_kg_m3"),
            thermal_conductivity_w_mk=normalize_optional_non_negative_float(
                self.thermal_conductivity_w_mk,
                "thermal_conductivity_w_mk",
            ),
            sort_order=normalize_int(self.sort_order, "sort_order"),
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "layer_id": normalized.layer_id,
            "material_id": normalized.material_id,
            "label": normalized.label,
            "layer_function": normalized.layer_function,
            "thickness_m": normalized.thickness_m,
            "density_kg_m3": normalized.density_kg_m3,
            "thermal_conductivity_w_mk": normalized.thermal_conductivity_w_mk,
            "sort_order": normalized.sort_order,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class MaterialLayersDefaults:
    """Defaults für material/layers.json."""

    layers: tuple[MaterialLayerDefaults, ...] = field(default_factory=tuple)
    total_thickness_m: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialLayersDefaults":
        layers = tuple(layer.normalized() for layer in self.layers or ())
        assert_unique_values([layer.layer_id for layer in layers], "layer_id")

        total_thickness_m = normalize_optional_positive_float(self.total_thickness_m, "total_thickness_m")
        if total_thickness_m is None:
            thicknesses = [layer.thickness_m for layer in layers if layer.thickness_m is not None]
            total_thickness_m = sum(thicknesses) if thicknesses else None

        return MaterialLayersDefaults(
            layers=tuple(sorted(layers, key=lambda item: (item.sort_order, item.layer_id))),
            total_thickness_m=total_thickness_m,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MATERIAL_LAYERS_DOCUMENT_SCHEMA_VERSION,
            "total_thickness_m": normalized.total_thickness_m,
            "layers": [layer.to_dict() for layer in normalized.layers],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class MaterialFinishDefaults:
    """Ein Finish für material/finishes.json."""

    finish_id: str = DEFAULT_FINISH_ID
    label: str | None = None
    surface_finish: str = SurfaceFinish.NONE.value
    fallback_color: str = DEFAULT_FALLBACK_COLOR
    texture_ref: str | None = None
    roughness: float | None = None
    gloss: float | None = None
    opacity: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialFinishDefaults":
        finish_id = normalize_material_key(self.finish_id, "finish_id")

        return MaterialFinishDefaults(
            finish_id=finish_id,
            label=clean_optional_string(self.label) or finish_id,
            surface_finish=parse_surface_finish_value(self.surface_finish),
            fallback_color=normalize_color(self.fallback_color),
            texture_ref=clean_optional_string(self.texture_ref),
            roughness=normalize_optional_unit_interval_float(self.roughness, "roughness"),
            gloss=normalize_optional_unit_interval_float(self.gloss, "gloss"),
            opacity=normalize_optional_unit_interval_float(self.opacity, "opacity"),
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "finish_id": normalized.finish_id,
            "label": normalized.label,
            "surface_finish": normalized.surface_finish,
            "fallback_color": normalized.fallback_color,
            "texture_ref": normalized.texture_ref,
            "roughness": normalized.roughness,
            "gloss": normalized.gloss,
            "opacity": normalized.opacity,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class MaterialFinishesDefaults:
    """Defaults für material/finishes.json."""

    finishes: tuple[MaterialFinishDefaults, ...] = field(default_factory=tuple)
    default_finish_id: str = DEFAULT_FINISH_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "MaterialFinishesDefaults":
        default_finish_id = normalize_material_key(self.default_finish_id, "default_finish_id")
        finishes = tuple(finish.normalized() for finish in self.finishes or ())

        if not finishes:
            finishes = (
                MaterialFinishDefaults(
                    finish_id=default_finish_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
            )

        finish_ids = [finish.finish_id for finish in finishes]
        assert_unique_values(finish_ids, "finish_id")

        if default_finish_id not in set(finish_ids):
            finishes = (
                MaterialFinishDefaults(
                    finish_id=default_finish_id,
                    fallback_color=DEFAULT_FALLBACK_COLOR,
                ).normalized(),
                *finishes,
            )

        return MaterialFinishesDefaults(
            finishes=tuple(sorted(finishes, key=lambda item: item.finish_id)),
            default_finish_id=default_finish_id,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MATERIAL_FINISHES_DOCUMENT_SCHEMA_VERSION,
            "default_finish_id": normalized.default_finish_id,
            "finishes": [finish.to_dict() for finish in normalized.finishes],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class MaterialDefaults:
    """Vollständige Defaults für alle material/*.json-Dokumente."""

    base: MaterialBaseDefaults
    performance: MaterialPerformanceDefaults = field(default_factory=MaterialPerformanceDefaults)
    surfaces: MaterialSurfacesDefaults = field(default_factory=MaterialSurfacesDefaults)
    layers: MaterialLayersDefaults = field(default_factory=MaterialLayersDefaults)
    finishes: MaterialFinishesDefaults = field(default_factory=MaterialFinishesDefaults)

    def normalized(self) -> "MaterialDefaults":
        return MaterialDefaults(
            base=self.base.normalized(),
            performance=self.performance.normalized(),
            surfaces=self.surfaces.normalized(),
            layers=self.layers.normalized(),
            finishes=self.finishes.normalized(),
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "material/base.json": normalized.base.to_document(),
        }

        if include_optional:
            documents["material/performance.json"] = normalized.performance.to_document()
            documents["material/surfaces.json"] = normalized.surfaces.to_document()
            documents["material/layers.json"] = normalized.layers.to_document()
            documents["material/finishes.json"] = normalized.finishes.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": MATERIAL_DEFAULTS_SCHEMA_VERSION,
            "base": normalized.base.to_dict(),
            "performance": normalized.performance.to_dict(),
            "surfaces": normalized.surfaces.to_dict(),
            "layers": normalized.layers.to_dict(),
            "finishes": normalized.finishes.to_dict(),
        }


def build_material_defaults(
    *,
    material_id: str = DEFAULT_MATERIAL_ID,
    material_name: str = DEFAULT_MATERIAL_NAME,
    material_class: str = MaterialClass.GENERIC.value,
    material_role: str = MaterialRole.PRIMARY.value,
    description: str = "",
    surface_finish: str = SurfaceFinish.NONE.value,
    fallback_color: str = DEFAULT_FALLBACK_COLOR,
    texture_ref: str | None = None,
    density_kg_m3: float | None = None,
    raw_density_kg_m3: float | None = None,
    thermal_conductivity_w_mk: float | None = None,
    thermal_transmittance_w_m2k: float | None = None,
    compressive_strength_mpa: float | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> MaterialDefaults:
    """Baut MaterialDefaults aus expliziten Werten."""
    try:
        material_key = normalize_material_key(material_id, "material_id")
        metadata_payload = dict(metadata or {})

        has_explicit_performance_values = any(
            value is not None
            for value in (
                density_kg_m3,
                raw_density_kg_m3,
                thermal_conductivity_w_mk,
                thermal_transmittance_w_m2k,
                compressive_strength_mpa,
            )
        )

        return MaterialDefaults(
            base=MaterialBaseDefaults(
                material_id=material_key,
                material_name=material_name,
                material_class=material_class,
                material_role=material_role,
                description=description,
                metadata=metadata_payload,
            ),
            performance=MaterialPerformanceDefaults(
                density_kg_m3=density_kg_m3,
                raw_density_kg_m3=raw_density_kg_m3,
                thermal_conductivity_w_mk=thermal_conductivity_w_mk,
                thermal_transmittance_w_m2k=thermal_transmittance_w_m2k,
                compressive_strength_mpa=compressive_strength_mpa,
                value_source=PerformanceValueSource.EXPLICIT.value
                if has_explicit_performance_values
                else PerformanceValueSource.UNKNOWN.value,
                metadata=metadata_payload,
            ),
            surfaces=MaterialSurfacesDefaults(
                surfaces=(
                    MaterialSurfaceDefaults(
                        surface_id=DEFAULT_SURFACE_ID,
                        side=SurfaceSide.ALL.value,
                        surface_finish=surface_finish,
                        fallback_color=fallback_color,
                        texture_ref=texture_ref,
                        metadata=metadata_payload,
                    ),
                ),
                metadata=metadata_payload,
            ),
            layers=MaterialLayersDefaults(
                layers=(
                    MaterialLayerDefaults(
                        layer_id=DEFAULT_LAYER_ID,
                        material_id=material_key,
                        layer_function=LayerFunction.CORE.value,
                        density_kg_m3=density_kg_m3,
                        thermal_conductivity_w_mk=thermal_conductivity_w_mk,
                        metadata=metadata_payload,
                    ),
                ),
                metadata=metadata_payload,
            ),
            finishes=MaterialFinishesDefaults(
                finishes=(
                    MaterialFinishDefaults(
                        finish_id=DEFAULT_FINISH_ID,
                        surface_finish=surface_finish,
                        fallback_color=fallback_color,
                        texture_ref=texture_ref,
                        metadata=metadata_payload,
                    ),
                ),
                metadata=metadata_payload,
            ),
        ).normalized()
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"Could not build material defaults: {exc}") from exc


def material_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> MaterialDefaults:
    """Baut MaterialDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        material = normalize_optional_model(getattr(normalized_request, "material", None))
        physical = normalize_optional_model(getattr(normalized_request, "physical", None))
        visual = normalize_optional_model(getattr(normalized_request, "visual", None))

        return build_material_defaults(
            material_id=getattr(material, "material_id", None) or DEFAULT_MATERIAL_ID,
            material_name=getattr(material, "material_name", None) or DEFAULT_MATERIAL_NAME,
            material_class=getattr(material, "material_class", None) or infer_material_class_from_request(normalized_request),
            material_role=infer_material_role_from_request(normalized_request),
            surface_finish=getattr(material, "surface_finish", None) or SurfaceFinish.NONE.value,
            fallback_color=getattr(visual, "fallback_color", None) or DEFAULT_FALLBACK_COLOR,
            texture_ref=getattr(visual, "texture_ref", None),
            density_kg_m3=getattr(physical, "density_kg_m3", None),
            raw_density_kg_m3=getattr(physical, "raw_density_kg_m3", None),
            thermal_conductivity_w_mk=getattr(material, "thermal_conductivity", None),
            thermal_transmittance_w_m2k=getattr(material, "u_value", None),
            compressive_strength_mpa=getattr(material, "compressive_strength", None),
            metadata={
                "source": "create_request",
                "object_kind": getattr(normalized_request, "object_kind", None),
                **dict(metadata or {}),
            },
        )
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"Could not build material defaults from CreateRequest: {exc}") from exc


def material_defaults_from_context(
    context: Any,
    *,
    material_id: str = DEFAULT_MATERIAL_ID,
    material_name: str = DEFAULT_MATERIAL_NAME,
    metadata: Mapping[str, Any] | None = None,
) -> MaterialDefaults:
    """Baut MaterialDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context
        object_kind = getattr(normalized_context, "object_kind", None)

        return build_material_defaults(
            material_id=material_id,
            material_name=material_name,
            material_class=infer_material_class_from_object_kind(object_kind),
            material_role=infer_material_role_from_object_kind(object_kind),
            metadata={
                "source": "package_context",
                "object_kind": object_kind,
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"Could not build material defaults from PackageContext: {exc}") from exc


def material_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> MaterialDefaults:
    """Baut MaterialDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return material_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"Could not build material defaults from CreationPlan: {exc}") from exc


def material_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle material/*.json-Dokumente aus CreateRequest."""
    return material_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def material_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle material/*.json-Dokumente aus PackageContext."""
    return material_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def material_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle material/*.json-Dokumente aus CreationPlan."""
    return material_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def validate_material_base_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob material/base.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("material/base.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "material_id",
            "material_name",
            "material_class",
            "material_role",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing material base field {field_name!r}.")

        if "material_id" in document:
            try:
                normalize_material_key(document["material_id"], "material_id")
            except Exception as exc:
                messages.append(str(exc))

        if "material_class" in document:
            try:
                parse_material_class_value(document["material_class"])
            except Exception as exc:
                messages.append(str(exc))

        if "material_role" in document:
            try:
                parse_material_role_value(document["material_role"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate material base document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_material_performance_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob material/performance.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("material/performance.json must be a mapping.",)

        if "schema_version" not in document:
            messages.append("Missing material performance field 'schema_version'.")

        numeric_fields = (
            "density_kg_m3",
            "raw_density_kg_m3",
            "thermal_conductivity_w_mk",
            "thermal_transmittance_w_m2k",
            "compressive_strength_mpa",
            "tensile_strength_mpa",
            "bending_strength_mpa",
            "elastic_modulus_gpa",
            "acoustic_rating_db",
        )

        for field_name in numeric_fields:
            if document.get(field_name) is not None:
                try:
                    normalize_non_negative_float(document[field_name], field_name)
                except Exception as exc:
                    messages.append(str(exc))

        if "fire_reaction_class" in document:
            try:
                parse_fire_reaction_class_value(document["fire_reaction_class"])
            except Exception as exc:
                messages.append(str(exc))

        if "value_source" in document:
            try:
                parse_performance_value_source_value(document["value_source"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate material performance document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_material_base_document(document: Mapping[str, Any]) -> None:
    """Wirft MaterialDefaultsError, wenn material/base.json ungültig ist."""
    valid, messages = validate_material_base_document(document)
    if not valid:
        raise MaterialDefaultsError(" ".join(messages) if messages else "Invalid material base document.")


def assert_valid_material_performance_document(document: Mapping[str, Any]) -> None:
    """Wirft MaterialDefaultsError, wenn material/performance.json ungültig ist."""
    valid, messages = validate_material_performance_document(document)
    if not valid:
        raise MaterialDefaultsError(" ".join(messages) if messages else "Invalid material performance document.")


def infer_material_class_from_request(request: Any) -> str:
    """Leitet MaterialClass aus Request-Klassifikation ab."""
    try:
        classification = request.classification.normalized()
        category = str(getattr(classification, "category", "")).lower()
        subcategory = str(getattr(classification, "subcategory", "")).lower()

        if "mauerwerk" in subcategory or "brick" in subcategory:
            return MaterialClass.MASONRY.value
        if "trockenbau" in subcategory or "drywall" in subcategory:
            return MaterialClass.DRYWALL.value
        if "beton" in subcategory or "concrete" in subcategory or "massiv" in subcategory:
            return MaterialClass.CONCRETE.value
        if "holz" in subcategory or "timber" in subcategory or "wood" in subcategory:
            return MaterialClass.TIMBER.value
        if category in {"moebel", "furniture"}:
            return MaterialClass.COMPOSITE.value
        if category in {"technik", "equipment"}:
            return MaterialClass.EQUIPMENT.value

        return infer_material_class_from_object_kind(request.object_kind)
    except Exception:
        return MaterialClass.GENERIC.value


def infer_material_class_from_object_kind(object_kind: Any) -> str:
    """Leitet MaterialClass aus object_kind ab."""
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
    except Exception:
        return MaterialClass.GENERIC.value

    if object_kind_value == "catalog_object":
        return MaterialClass.EQUIPMENT.value

    if object_kind_value == "adaptive_system":
        return MaterialClass.COMPOSITE.value

    return MaterialClass.GENERIC.value


def infer_material_role_from_request(request: Any) -> str:
    """Leitet MaterialRole aus Request-Daten ab."""
    try:
        return infer_material_role_from_object_kind(request.object_kind)
    except Exception:
        return MaterialRole.PRIMARY.value


def infer_material_role_from_object_kind(object_kind: Any) -> str:
    """Leitet MaterialRole aus object_kind ab."""
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
    except Exception:
        return MaterialRole.PRIMARY.value

    if object_kind_value in {"cell_block", "multi_cell_module"}:
        return MaterialRole.STRUCTURAL.value
    if object_kind_value == "adaptive_system":
        return MaterialRole.AUXILIARY.value
    return MaterialRole.PRIMARY.value


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

        raise MaterialDefaultsError("CreateRequest value is required.")
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_optional_model(value: Any) -> Any:
    """Normalisiert optionales Model-ähnliches Objekt."""
    if value is None:
        return EmptyObject()

    try:
        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()
    except Exception:
        return value

    return value


class EmptyObject:
    """Leeres Objekt für optionale verschachtelte Request-Modelle."""

    __slots__ = ()

    def __getattr__(self, _name: str) -> None:
        return None


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_material_key(value: Any, field_name: str) -> str:
    """Normalisiert technische Material-Keys."""
    raw = clean_required_string(value, field_name)
    key = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_MATERIAL_KEY_RE.match(key):
        raise MaterialDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return key


def normalize_color(value: Any) -> str:
    """Normalisiert Hex-Farbe."""
    color = clean_required_string(value or DEFAULT_FALLBACK_COLOR, "fallback_color")

    if not SAFE_HEX_COLOR_RE.match(color):
        raise MaterialDefaultsError(f"Invalid color {value!r}.")

    return color


@lru_cache(maxsize=128)
def parse_material_class_value(value: Any) -> str:
    """Parst MaterialClass."""
    try:
        if isinstance(value, MaterialClass):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "generic": MaterialClass.GENERIC.value,
            "concrete": MaterialClass.CONCRETE.value,
            "beton": MaterialClass.CONCRETE.value,
            "masonry": MaterialClass.MASONRY.value,
            "brick": MaterialClass.MASONRY.value,
            "drywall": MaterialClass.DRYWALL.value,
            "timber": MaterialClass.TIMBER.value,
            "wood": MaterialClass.TIMBER.value,
            "steel": MaterialClass.STEEL.value,
            "aluminium": MaterialClass.ALUMINUM.value,
            "aluminum": MaterialClass.ALUMINUM.value,
            "glass": MaterialClass.GLASS.value,
            "plastic": MaterialClass.PLASTIC.value,
            "insulation": MaterialClass.INSULATION.value,
            "composite": MaterialClass.COMPOSITE.value,
            "finish": MaterialClass.FINISH.value,
            "equipment": MaterialClass.EQUIPMENT.value,
            "unknown": MaterialClass.UNKNOWN.value,
        }

        if raw in aliases:
            return aliases[raw]

        return MaterialClass(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid material class {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_material_role_value(value: Any) -> str:
    """Parst MaterialRole."""
    try:
        if isinstance(value, MaterialRole):
            return value.value

        raw = normalize_enum_key(value)
        return MaterialRole(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid material role {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_surface_side_value(value: Any) -> str:
    """Parst SurfaceSide."""
    try:
        if isinstance(value, SurfaceSide):
            return value.value

        raw = normalize_enum_key(value)
        return SurfaceSide(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid surface side {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_surface_finish_value(value: Any) -> str:
    """Parst SurfaceFinish."""
    try:
        if isinstance(value, SurfaceFinish):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "none": SurfaceFinish.NONE.value,
            "raw": SurfaceFinish.RAW.value,
            "smooth": SurfaceFinish.SMOOTH.value,
            "rough": SurfaceFinish.ROUGH.value,
            "painted": SurfaceFinish.PAINTED.value,
            "coated": SurfaceFinish.COATED.value,
            "plastered": SurfaceFinish.PLASTERED.value,
            "polished": SurfaceFinish.POLISHED.value,
            "brushed": SurfaceFinish.BRUSHED.value,
            "textured": SurfaceFinish.TEXTURED.value,
            "custom": SurfaceFinish.CUSTOM.value,
        }

        if raw in aliases:
            return aliases[raw]

        return SurfaceFinish(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid surface finish {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_layer_function_value(value: Any) -> str:
    """Parst LayerFunction."""
    try:
        if isinstance(value, LayerFunction):
            return value.value

        raw = normalize_enum_key(value)
        return LayerFunction(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid layer function {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_fire_reaction_class_value(value: Any) -> str:
    """Parst FireReactionClass."""
    try:
        if isinstance(value, FireReactionClass):
            return value.value

        raw = normalize_enum_key(value)
        return FireReactionClass(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid fire reaction class {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_performance_value_source_value(value: Any) -> str:
    """Parst PerformanceValueSource."""
    try:
        if isinstance(value, PerformanceValueSource):
            return value.value

        raw = normalize_enum_key(value)
        return PerformanceValueSource(raw).value
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid performance value source {value!r}.") from exc


def assert_unique_values(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige Werte."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise MaterialDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise MaterialDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise MaterialDefaultsError(f"{field_name} must be a number.")
        return float(value)
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"{field_name} must be a number.") from exc


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Float-Werte."""
    number = normalize_float(value, field_name)
    if number <= 0:
        raise MaterialDefaultsError(f"{field_name} must be > 0.")
    return number


def normalize_non_negative_float(value: Any, field_name: str) -> float:
    """Normalisiert nicht-negative Float-Werte."""
    number = normalize_float(value, field_name)
    if number < 0:
        raise MaterialDefaultsError(f"{field_name} must be >= 0.")
    return number


def normalize_optional_positive_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionale positive Float-Werte."""
    if value is None:
        return None
    return normalize_positive_float(value, field_name)


def normalize_optional_non_negative_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionale nicht-negative Float-Werte."""
    if value is None:
        return None
    return normalize_non_negative_float(value, field_name)


def normalize_unit_interval_float(value: Any, field_name: str) -> float:
    """Normalisiert Float im Bereich 0..1."""
    number = normalize_float(value, field_name)

    if number < 0 or number > 1:
        raise MaterialDefaultsError(f"{field_name} must be in range 0..1.")

    return number


def normalize_optional_unit_interval_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionalen Float im Bereich 0..1."""
    if value is None:
        return None
    return normalize_unit_interval_float(value, field_name)


def normalize_int(value: Any, field_name: str) -> int:
    """Normalisiert Integer."""
    try:
        if isinstance(value, bool):
            raise MaterialDefaultsError(f"{field_name} must be an integer.")
        return int(value)
    except Exception as exc:
        raise MaterialDefaultsError(f"{field_name} must be an integer.") from exc


def normalize_string_tuple(values: Iterable[Any] | Any) -> tuple[str, ...]:
    """Normalisiert Stringlisten ohne Duplikate."""
    if values is None:
        return tuple()

    if isinstance(values, str):
        values = (values,)

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
        raise MaterialDefaultsError("metadata must be a mapping.")

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
            raise MaterialDefaultsError(f"{field_name} is required.")
        return cleaned
    except MaterialDefaultsError:
        raise
    except Exception as exc:
        raise MaterialDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_material_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_material_class_value.cache_clear()
    parse_material_role_value.cache_clear()
    parse_surface_side_value.cache_clear()
    parse_surface_finish_value.cache_clear()
    parse_layer_function_value.cache_clear()
    parse_fire_reaction_class_value.cache_clear()
    parse_performance_value_source_value.cache_clear()


__all__ = [
    "DEFAULT_FALLBACK_COLOR",
    "DEFAULT_FINISH_ID",
    "DEFAULT_LAYER_ID",
    "DEFAULT_MATERIAL_ID",
    "DEFAULT_MATERIAL_NAME",
    "DEFAULT_SURFACE_ID",
    "MATERIAL_BASE_DOCUMENT_SCHEMA_VERSION",
    "MATERIAL_DEFAULTS_SCHEMA_VERSION",
    "MATERIAL_FINISHES_DOCUMENT_SCHEMA_VERSION",
    "MATERIAL_LAYERS_DOCUMENT_SCHEMA_VERSION",
    "MATERIAL_PERFORMANCE_DOCUMENT_SCHEMA_VERSION",
    "MATERIAL_SURFACES_DOCUMENT_SCHEMA_VERSION",
    "SAFE_HEX_COLOR_RE",
    "SAFE_MATERIAL_KEY_RE",
    "EmptyObject",
    "FireReactionClass",
    "LayerFunction",
    "MaterialBaseDefaults",
    "MaterialClass",
    "MaterialDefaults",
    "MaterialDefaultsError",
    "MaterialFinishDefaults",
    "MaterialFinishesDefaults",
    "MaterialLayerDefaults",
    "MaterialLayersDefaults",
    "MaterialPerformanceDefaults",
    "MaterialRole",
    "MaterialSurfaceDefaults",
    "MaterialSurfacesDefaults",
    "PerformanceValueSource",
    "SurfaceFinish",
    "SurfaceSide",
    "assert_unique_values",
    "assert_valid_material_base_document",
    "assert_valid_material_performance_document",
    "build_material_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_material_defaults_caches",
    "infer_material_class_from_object_kind",
    "infer_material_class_from_request",
    "infer_material_role_from_object_kind",
    "infer_material_role_from_request",
    "material_defaults_from_context",
    "material_defaults_from_create_request",
    "material_defaults_from_creation_plan",
    "material_documents_from_context",
    "material_documents_from_create_request",
    "material_documents_from_creation_plan",
    "normalize_color",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_float",
    "normalize_int",
    "normalize_material_key",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_non_negative_float",
    "normalize_object_kind_value",
    "normalize_optional_model",
    "normalize_optional_non_negative_float",
    "normalize_optional_positive_float",
    "normalize_optional_unit_interval_float",
    "normalize_positive_float",
    "normalize_string_tuple",
    "normalize_unit_interval_float",
    "parse_fire_reaction_class_value",
    "parse_layer_function_value",
    "parse_material_class_value",
    "parse_material_role_value",
    "parse_performance_value_source_value",
    "parse_surface_finish_value",
    "parse_surface_side_value",
    "validate_material_base_document",
    "validate_material_performance_document",
]