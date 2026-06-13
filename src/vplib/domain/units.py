# services/vectoplan-library/src/vplib/domain/units.py
"""
Canonical VPLIB unit definitions.

This module defines the stable unit vocabulary used by modular VPLIB packages.
Units are used by physical properties, material properties, calculation variables,
quantity definitions, measure logic, manufacturer override slots and validation.

The goal is not to replace a full scientific unit engine. The goal is to provide
a strict, predictable and dependency-light unit layer for VPLIB authoring.

Important invariants:
- Unit values are stable JSON-facing strings.
- Unit parsing is tolerant through aliases, but serialization is canonical.
- Conversions are only provided where they are unambiguous and safe.
- Currency is represented as a unit category, but exchange-rate conversion is
  intentionally not provided here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


UNIT_SCHEMA_VERSION: Final[str] = "vplib.units.v1"


class UnitError(ValueError):
    """Raised when a VPLIB unit value cannot be normalized, validated or converted."""


class UnitCategory(str, Enum):
    """Canonical unit categories."""

    NONE = "none"
    DIMENSIONLESS = "dimensionless"
    COUNT = "count"
    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    MASS = "mass"
    DENSITY = "density"
    FORCE = "force"
    PRESSURE = "pressure"
    STRESS = "stress"
    POWER = "power"
    ENERGY = "energy"
    TEMPERATURE = "temperature"
    ANGLE = "angle"
    TIME = "time"
    SPEED = "speed"
    THERMAL_CONDUCTIVITY = "thermal_conductivity"
    THERMAL_TRANSMITTANCE = "thermal_transmittance"
    COST = "cost"


class VplibUnit(str, Enum):
    """
    Canonical VPLIB units.

    Keep these values stable. They may appear in:
    - physical/*.json
    - material/*.json
    - calculation/*.json
    - manufacturer/override_slots.json
    - validation reports
    - future database rows
    - API responses
    """

    NONE = "none"

    # Dimensionless / count
    RATIO = "ratio"
    PERCENT = "percent"
    COUNT = "count"

    # Length
    METER = "m"
    CENTIMETER = "cm"
    MILLIMETER = "mm"

    # Area / volume
    SQUARE_METER = "m2"
    SQUARE_CENTIMETER = "cm2"
    SQUARE_MILLIMETER = "mm2"
    CUBIC_METER = "m3"
    CUBIC_CENTIMETER = "cm3"
    CUBIC_MILLIMETER = "mm3"

    # Mass / density
    KILOGRAM = "kg"
    GRAM = "g"
    TONNE = "t"
    KILOGRAM_PER_CUBIC_METER = "kg/m3"
    GRAM_PER_CUBIC_CENTIMETER = "g/cm3"

    # Force / pressure / stress
    NEWTON = "N"
    KILONEWTON = "kN"
    PASCAL = "Pa"
    KILOPASCAL = "kPa"
    MEGAPASCAL = "MPa"
    GIGAPASCAL = "GPa"

    # Power / energy
    WATT = "W"
    KILOWATT = "kW"
    JOULE = "J"
    KILOJOULE = "kJ"
    KILOWATT_HOUR = "kWh"

    # Temperature
    KELVIN = "K"
    CELSIUS = "C"

    # Angle
    DEGREE = "deg"
    RADIAN = "rad"

    # Time / speed
    SECOND = "s"
    MINUTE = "min"
    HOUR = "h"
    METER_PER_SECOND = "m/s"
    KILOMETER_PER_HOUR = "km/h"

    # Building physics
    WATT_PER_METER_KELVIN = "W/(m*K)"
    WATT_PER_SQUARE_METER_KELVIN = "W/(m2*K)"

    # Cost
    EURO = "EUR"
    EURO_PER_SQUARE_METER = "EUR/m2"
    EURO_PER_CUBIC_METER = "EUR/m3"
    EURO_PER_PIECE = "EUR/pcs"


@dataclass(frozen=True, slots=True)
class UnitDefinition:
    """
    Metadata for one canonical unit.

    factor_to_base and offset_to_base are only used for safe linear or affine
    conversions inside the same category. If supports_conversion is False, the
    unit is intentionally not converted by this module.
    """

    unit: VplibUnit
    category: UnitCategory
    title: str
    symbol: str
    base_unit: VplibUnit
    factor_to_base: float
    offset_to_base: float
    supports_conversion: bool
    accepts_float: bool
    accepts_integer: bool
    accepts_negative: bool
    typical_fields: tuple[str, ...]


_UNIT_DEFINITIONS: Final[dict[VplibUnit, UnitDefinition]] = {
    VplibUnit.NONE: UnitDefinition(
        unit=VplibUnit.NONE,
        category=UnitCategory.NONE,
        title="No unit",
        symbol="",
        base_unit=VplibUnit.NONE,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=False,
        accepts_integer=False,
        accepts_negative=False,
        typical_fields=tuple(),
    ),
    VplibUnit.RATIO: UnitDefinition(
        unit=VplibUnit.RATIO,
        category=UnitCategory.DIMENSIONLESS,
        title="Ratio",
        symbol="ratio",
        base_unit=VplibUnit.RATIO,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("factor", "coefficient", "ratio"),
    ),
    VplibUnit.PERCENT: UnitDefinition(
        unit=VplibUnit.PERCENT,
        category=UnitCategory.DIMENSIONLESS,
        title="Percent",
        symbol="%",
        base_unit=VplibUnit.RATIO,
        factor_to_base=0.01,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("percentage", "share", "efficiency"),
    ),
    VplibUnit.COUNT: UnitDefinition(
        unit=VplibUnit.COUNT,
        category=UnitCategory.COUNT,
        title="Count",
        symbol="count",
        base_unit=VplibUnit.COUNT,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=False,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("count", "quantity", "pieces"),
    ),
    VplibUnit.METER: UnitDefinition(
        unit=VplibUnit.METER,
        category=UnitCategory.LENGTH,
        title="Meter",
        symbol="m",
        base_unit=VplibUnit.METER,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("length", "width", "height", "depth", "thickness"),
    ),
    VplibUnit.CENTIMETER: UnitDefinition(
        unit=VplibUnit.CENTIMETER,
        category=UnitCategory.LENGTH,
        title="Centimeter",
        symbol="cm",
        base_unit=VplibUnit.METER,
        factor_to_base=0.01,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("thickness", "width", "height"),
    ),
    VplibUnit.MILLIMETER: UnitDefinition(
        unit=VplibUnit.MILLIMETER,
        category=UnitCategory.LENGTH,
        title="Millimeter",
        symbol="mm",
        base_unit=VplibUnit.METER,
        factor_to_base=0.001,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("thickness", "offset", "tolerance"),
    ),
    VplibUnit.SQUARE_METER: UnitDefinition(
        unit=VplibUnit.SQUARE_METER,
        category=UnitCategory.AREA,
        title="Square meter",
        symbol="m2",
        base_unit=VplibUnit.SQUARE_METER,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("area", "surface_area", "floor_area"),
    ),
    VplibUnit.SQUARE_CENTIMETER: UnitDefinition(
        unit=VplibUnit.SQUARE_CENTIMETER,
        category=UnitCategory.AREA,
        title="Square centimeter",
        symbol="cm2",
        base_unit=VplibUnit.SQUARE_METER,
        factor_to_base=0.0001,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("area", "cross_section"),
    ),
    VplibUnit.SQUARE_MILLIMETER: UnitDefinition(
        unit=VplibUnit.SQUARE_MILLIMETER,
        category=UnitCategory.AREA,
        title="Square millimeter",
        symbol="mm2",
        base_unit=VplibUnit.SQUARE_METER,
        factor_to_base=0.000001,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("cross_section", "reinforcement_area"),
    ),
    VplibUnit.CUBIC_METER: UnitDefinition(
        unit=VplibUnit.CUBIC_METER,
        category=UnitCategory.VOLUME,
        title="Cubic meter",
        symbol="m3",
        base_unit=VplibUnit.CUBIC_METER,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("volume", "gross_volume", "net_volume"),
    ),
    VplibUnit.CUBIC_CENTIMETER: UnitDefinition(
        unit=VplibUnit.CUBIC_CENTIMETER,
        category=UnitCategory.VOLUME,
        title="Cubic centimeter",
        symbol="cm3",
        base_unit=VplibUnit.CUBIC_METER,
        factor_to_base=0.000001,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("volume",),
    ),
    VplibUnit.CUBIC_MILLIMETER: UnitDefinition(
        unit=VplibUnit.CUBIC_MILLIMETER,
        category=UnitCategory.VOLUME,
        title="Cubic millimeter",
        symbol="mm3",
        base_unit=VplibUnit.CUBIC_METER,
        factor_to_base=0.000000001,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("volume",),
    ),
    VplibUnit.KILOGRAM: UnitDefinition(
        unit=VplibUnit.KILOGRAM,
        category=UnitCategory.MASS,
        title="Kilogram",
        symbol="kg",
        base_unit=VplibUnit.KILOGRAM,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("mass", "weight_mass"),
    ),
    VplibUnit.GRAM: UnitDefinition(
        unit=VplibUnit.GRAM,
        category=UnitCategory.MASS,
        title="Gram",
        symbol="g",
        base_unit=VplibUnit.KILOGRAM,
        factor_to_base=0.001,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("mass",),
    ),
    VplibUnit.TONNE: UnitDefinition(
        unit=VplibUnit.TONNE,
        category=UnitCategory.MASS,
        title="Tonne",
        symbol="t",
        base_unit=VplibUnit.KILOGRAM,
        factor_to_base=1000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("mass",),
    ),
    VplibUnit.KILOGRAM_PER_CUBIC_METER: UnitDefinition(
        unit=VplibUnit.KILOGRAM_PER_CUBIC_METER,
        category=UnitCategory.DENSITY,
        title="Kilogram per cubic meter",
        symbol="kg/m3",
        base_unit=VplibUnit.KILOGRAM_PER_CUBIC_METER,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("density", "raw_density", "bulk_density"),
    ),
    VplibUnit.GRAM_PER_CUBIC_CENTIMETER: UnitDefinition(
        unit=VplibUnit.GRAM_PER_CUBIC_CENTIMETER,
        category=UnitCategory.DENSITY,
        title="Gram per cubic centimeter",
        symbol="g/cm3",
        base_unit=VplibUnit.KILOGRAM_PER_CUBIC_METER,
        factor_to_base=1000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("density",),
    ),
    VplibUnit.NEWTON: UnitDefinition(
        unit=VplibUnit.NEWTON,
        category=UnitCategory.FORCE,
        title="Newton",
        symbol="N",
        base_unit=VplibUnit.NEWTON,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("force", "load"),
    ),
    VplibUnit.KILONEWTON: UnitDefinition(
        unit=VplibUnit.KILONEWTON,
        category=UnitCategory.FORCE,
        title="Kilonewton",
        symbol="kN",
        base_unit=VplibUnit.NEWTON,
        factor_to_base=1000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("force", "load", "load_capacity"),
    ),
    VplibUnit.PASCAL: UnitDefinition(
        unit=VplibUnit.PASCAL,
        category=UnitCategory.PRESSURE,
        title="Pascal",
        symbol="Pa",
        base_unit=VplibUnit.PASCAL,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("pressure", "stress"),
    ),
    VplibUnit.KILOPASCAL: UnitDefinition(
        unit=VplibUnit.KILOPASCAL,
        category=UnitCategory.PRESSURE,
        title="Kilopascal",
        symbol="kPa",
        base_unit=VplibUnit.PASCAL,
        factor_to_base=1000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("pressure",),
    ),
    VplibUnit.MEGAPASCAL: UnitDefinition(
        unit=VplibUnit.MEGAPASCAL,
        category=UnitCategory.STRESS,
        title="Megapascal",
        symbol="MPa",
        base_unit=VplibUnit.PASCAL,
        factor_to_base=1_000_000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("compressive_strength", "tensile_strength", "stress"),
    ),
    VplibUnit.GIGAPASCAL: UnitDefinition(
        unit=VplibUnit.GIGAPASCAL,
        category=UnitCategory.STRESS,
        title="Gigapascal",
        symbol="GPa",
        base_unit=VplibUnit.PASCAL,
        factor_to_base=1_000_000_000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("elastic_modulus", "young_modulus"),
    ),
    VplibUnit.WATT: UnitDefinition(
        unit=VplibUnit.WATT,
        category=UnitCategory.POWER,
        title="Watt",
        symbol="W",
        base_unit=VplibUnit.WATT,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("power", "thermal_power", "electric_power"),
    ),
    VplibUnit.KILOWATT: UnitDefinition(
        unit=VplibUnit.KILOWATT,
        category=UnitCategory.POWER,
        title="Kilowatt",
        symbol="kW",
        base_unit=VplibUnit.WATT,
        factor_to_base=1000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("power", "heating_power", "electric_power"),
    ),
    VplibUnit.JOULE: UnitDefinition(
        unit=VplibUnit.JOULE,
        category=UnitCategory.ENERGY,
        title="Joule",
        symbol="J",
        base_unit=VplibUnit.JOULE,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("energy",),
    ),
    VplibUnit.KILOJOULE: UnitDefinition(
        unit=VplibUnit.KILOJOULE,
        category=UnitCategory.ENERGY,
        title="Kilojoule",
        symbol="kJ",
        base_unit=VplibUnit.JOULE,
        factor_to_base=1000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("energy",),
    ),
    VplibUnit.KILOWATT_HOUR: UnitDefinition(
        unit=VplibUnit.KILOWATT_HOUR,
        category=UnitCategory.ENERGY,
        title="Kilowatt hour",
        symbol="kWh",
        base_unit=VplibUnit.JOULE,
        factor_to_base=3_600_000.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("energy", "energy_demand"),
    ),
    VplibUnit.KELVIN: UnitDefinition(
        unit=VplibUnit.KELVIN,
        category=UnitCategory.TEMPERATURE,
        title="Kelvin",
        symbol="K",
        base_unit=VplibUnit.KELVIN,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("temperature",),
    ),
    VplibUnit.CELSIUS: UnitDefinition(
        unit=VplibUnit.CELSIUS,
        category=UnitCategory.TEMPERATURE,
        title="Celsius",
        symbol="C",
        base_unit=VplibUnit.KELVIN,
        factor_to_base=1.0,
        offset_to_base=273.15,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("temperature",),
    ),
    VplibUnit.DEGREE: UnitDefinition(
        unit=VplibUnit.DEGREE,
        category=UnitCategory.ANGLE,
        title="Degree",
        symbol="deg",
        base_unit=VplibUnit.RADIAN,
        factor_to_base=0.017453292519943295,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("angle", "rotation"),
    ),
    VplibUnit.RADIAN: UnitDefinition(
        unit=VplibUnit.RADIAN,
        category=UnitCategory.ANGLE,
        title="Radian",
        symbol="rad",
        base_unit=VplibUnit.RADIAN,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("angle", "rotation"),
    ),
    VplibUnit.SECOND: UnitDefinition(
        unit=VplibUnit.SECOND,
        category=UnitCategory.TIME,
        title="Second",
        symbol="s",
        base_unit=VplibUnit.SECOND,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("duration", "time"),
    ),
    VplibUnit.MINUTE: UnitDefinition(
        unit=VplibUnit.MINUTE,
        category=UnitCategory.TIME,
        title="Minute",
        symbol="min",
        base_unit=VplibUnit.SECOND,
        factor_to_base=60.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("duration", "time"),
    ),
    VplibUnit.HOUR: UnitDefinition(
        unit=VplibUnit.HOUR,
        category=UnitCategory.TIME,
        title="Hour",
        symbol="h",
        base_unit=VplibUnit.SECOND,
        factor_to_base=3600.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("duration", "time"),
    ),
    VplibUnit.METER_PER_SECOND: UnitDefinition(
        unit=VplibUnit.METER_PER_SECOND,
        category=UnitCategory.SPEED,
        title="Meter per second",
        symbol="m/s",
        base_unit=VplibUnit.METER_PER_SECOND,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("speed", "velocity"),
    ),
    VplibUnit.KILOMETER_PER_HOUR: UnitDefinition(
        unit=VplibUnit.KILOMETER_PER_HOUR,
        category=UnitCategory.SPEED,
        title="Kilometer per hour",
        symbol="km/h",
        base_unit=VplibUnit.METER_PER_SECOND,
        factor_to_base=0.2777777777777778,
        offset_to_base=0.0,
        supports_conversion=True,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=True,
        typical_fields=("speed", "velocity"),
    ),
    VplibUnit.WATT_PER_METER_KELVIN: UnitDefinition(
        unit=VplibUnit.WATT_PER_METER_KELVIN,
        category=UnitCategory.THERMAL_CONDUCTIVITY,
        title="Watt per meter Kelvin",
        symbol="W/(m*K)",
        base_unit=VplibUnit.WATT_PER_METER_KELVIN,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("thermal_conductivity", "lambda_value"),
    ),
    VplibUnit.WATT_PER_SQUARE_METER_KELVIN: UnitDefinition(
        unit=VplibUnit.WATT_PER_SQUARE_METER_KELVIN,
        category=UnitCategory.THERMAL_TRANSMITTANCE,
        title="Watt per square meter Kelvin",
        symbol="W/(m2*K)",
        base_unit=VplibUnit.WATT_PER_SQUARE_METER_KELVIN,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("u_value", "thermal_transmittance"),
    ),
    VplibUnit.EURO: UnitDefinition(
        unit=VplibUnit.EURO,
        category=UnitCategory.COST,
        title="Euro",
        symbol="EUR",
        base_unit=VplibUnit.EURO,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("cost", "price"),
    ),
    VplibUnit.EURO_PER_SQUARE_METER: UnitDefinition(
        unit=VplibUnit.EURO_PER_SQUARE_METER,
        category=UnitCategory.COST,
        title="Euro per square meter",
        symbol="EUR/m2",
        base_unit=VplibUnit.EURO_PER_SQUARE_METER,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("cost_per_area", "price_per_area"),
    ),
    VplibUnit.EURO_PER_CUBIC_METER: UnitDefinition(
        unit=VplibUnit.EURO_PER_CUBIC_METER,
        category=UnitCategory.COST,
        title="Euro per cubic meter",
        symbol="EUR/m3",
        base_unit=VplibUnit.EURO_PER_CUBIC_METER,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("cost_per_volume", "price_per_volume"),
    ),
    VplibUnit.EURO_PER_PIECE: UnitDefinition(
        unit=VplibUnit.EURO_PER_PIECE,
        category=UnitCategory.COST,
        title="Euro per piece",
        symbol="EUR/pcs",
        base_unit=VplibUnit.EURO_PER_PIECE,
        factor_to_base=1.0,
        offset_to_base=0.0,
        supports_conversion=False,
        accepts_float=True,
        accepts_integer=True,
        accepts_negative=False,
        typical_fields=("cost_per_piece", "unit_price"),
    ),
}


_ALIAS_MAP: Final[dict[str, VplibUnit]] = {
    "": VplibUnit.NONE,
    "none": VplibUnit.NONE,
    "unitless": VplibUnit.RATIO,
    "dimensionless": VplibUnit.RATIO,
    "ratio": VplibUnit.RATIO,
    "factor": VplibUnit.RATIO,
    "%": VplibUnit.PERCENT,
    "percent": VplibUnit.PERCENT,
    "percentage": VplibUnit.PERCENT,
    "count": VplibUnit.COUNT,
    "piece": VplibUnit.COUNT,
    "pieces": VplibUnit.COUNT,
    "pcs": VplibUnit.COUNT,
    "m": VplibUnit.METER,
    "meter": VplibUnit.METER,
    "meters": VplibUnit.METER,
    "metre": VplibUnit.METER,
    "metres": VplibUnit.METER,
    "cm": VplibUnit.CENTIMETER,
    "centimeter": VplibUnit.CENTIMETER,
    "centimeters": VplibUnit.CENTIMETER,
    "centimetre": VplibUnit.CENTIMETER,
    "centimetres": VplibUnit.CENTIMETER,
    "mm": VplibUnit.MILLIMETER,
    "millimeter": VplibUnit.MILLIMETER,
    "millimeters": VplibUnit.MILLIMETER,
    "millimetre": VplibUnit.MILLIMETER,
    "millimetres": VplibUnit.MILLIMETER,
    "m2": VplibUnit.SQUARE_METER,
    "m^2": VplibUnit.SQUARE_METER,
    "sqm": VplibUnit.SQUARE_METER,
    "square_meter": VplibUnit.SQUARE_METER,
    "square_metre": VplibUnit.SQUARE_METER,
    "cm2": VplibUnit.SQUARE_CENTIMETER,
    "cm^2": VplibUnit.SQUARE_CENTIMETER,
    "mm2": VplibUnit.SQUARE_MILLIMETER,
    "mm^2": VplibUnit.SQUARE_MILLIMETER,
    "m3": VplibUnit.CUBIC_METER,
    "m^3": VplibUnit.CUBIC_METER,
    "cbm": VplibUnit.CUBIC_METER,
    "cubic_meter": VplibUnit.CUBIC_METER,
    "cubic_metre": VplibUnit.CUBIC_METER,
    "cm3": VplibUnit.CUBIC_CENTIMETER,
    "cm^3": VplibUnit.CUBIC_CENTIMETER,
    "mm3": VplibUnit.CUBIC_MILLIMETER,
    "mm^3": VplibUnit.CUBIC_MILLIMETER,
    "kg": VplibUnit.KILOGRAM,
    "kilogram": VplibUnit.KILOGRAM,
    "kilograms": VplibUnit.KILOGRAM,
    "g": VplibUnit.GRAM,
    "gram": VplibUnit.GRAM,
    "grams": VplibUnit.GRAM,
    "t": VplibUnit.TONNE,
    "ton": VplibUnit.TONNE,
    "tons": VplibUnit.TONNE,
    "tonne": VplibUnit.TONNE,
    "tonnes": VplibUnit.TONNE,
    "kg/m3": VplibUnit.KILOGRAM_PER_CUBIC_METER,
    "kg_m3": VplibUnit.KILOGRAM_PER_CUBIC_METER,
    "kg_per_m3": VplibUnit.KILOGRAM_PER_CUBIC_METER,
    "kg_per_cubic_meter": VplibUnit.KILOGRAM_PER_CUBIC_METER,
    "g/cm3": VplibUnit.GRAM_PER_CUBIC_CENTIMETER,
    "g_cm3": VplibUnit.GRAM_PER_CUBIC_CENTIMETER,
    "g_per_cm3": VplibUnit.GRAM_PER_CUBIC_CENTIMETER,
    "n": VplibUnit.NEWTON,
    "newton": VplibUnit.NEWTON,
    "newtons": VplibUnit.NEWTON,
    "kn": VplibUnit.KILONEWTON,
    "kilonewton": VplibUnit.KILONEWTON,
    "kilonewtons": VplibUnit.KILONEWTON,
    "pa": VplibUnit.PASCAL,
    "pascal": VplibUnit.PASCAL,
    "pascals": VplibUnit.PASCAL,
    "kpa": VplibUnit.KILOPASCAL,
    "mpa": VplibUnit.MEGAPASCAL,
    "gpa": VplibUnit.GIGAPASCAL,
    "w": VplibUnit.WATT,
    "watt": VplibUnit.WATT,
    "watts": VplibUnit.WATT,
    "kw": VplibUnit.KILOWATT,
    "kilowatt": VplibUnit.KILOWATT,
    "kilowatts": VplibUnit.KILOWATT,
    "j": VplibUnit.JOULE,
    "joule": VplibUnit.JOULE,
    "joules": VplibUnit.JOULE,
    "kj": VplibUnit.KILOJOULE,
    "kilojoule": VplibUnit.KILOJOULE,
    "kilojoules": VplibUnit.KILOJOULE,
    "kwh": VplibUnit.KILOWATT_HOUR,
    "kilowatt_hour": VplibUnit.KILOWATT_HOUR,
    "kilowatt_hours": VplibUnit.KILOWATT_HOUR,
    "k": VplibUnit.KELVIN,
    "kelvin": VplibUnit.KELVIN,
    "c": VplibUnit.CELSIUS,
    "celsius": VplibUnit.CELSIUS,
    "degc": VplibUnit.CELSIUS,
    "degree_celsius": VplibUnit.CELSIUS,
    "deg": VplibUnit.DEGREE,
    "degree": VplibUnit.DEGREE,
    "degrees": VplibUnit.DEGREE,
    "rad": VplibUnit.RADIAN,
    "radian": VplibUnit.RADIAN,
    "radians": VplibUnit.RADIAN,
    "s": VplibUnit.SECOND,
    "sec": VplibUnit.SECOND,
    "second": VplibUnit.SECOND,
    "seconds": VplibUnit.SECOND,
    "min": VplibUnit.MINUTE,
    "minute": VplibUnit.MINUTE,
    "minutes": VplibUnit.MINUTE,
    "h": VplibUnit.HOUR,
    "hr": VplibUnit.HOUR,
    "hour": VplibUnit.HOUR,
    "hours": VplibUnit.HOUR,
    "m/s": VplibUnit.METER_PER_SECOND,
    "mps": VplibUnit.METER_PER_SECOND,
    "meter_per_second": VplibUnit.METER_PER_SECOND,
    "km/h": VplibUnit.KILOMETER_PER_HOUR,
    "kmh": VplibUnit.KILOMETER_PER_HOUR,
    "kilometer_per_hour": VplibUnit.KILOMETER_PER_HOUR,
    "w/(m*k)": VplibUnit.WATT_PER_METER_KELVIN,
    "w/mk": VplibUnit.WATT_PER_METER_KELVIN,
    "w_per_mk": VplibUnit.WATT_PER_METER_KELVIN,
    "w/(m2*k)": VplibUnit.WATT_PER_SQUARE_METER_KELVIN,
    "w/m2k": VplibUnit.WATT_PER_SQUARE_METER_KELVIN,
    "w_per_m2k": VplibUnit.WATT_PER_SQUARE_METER_KELVIN,
    "eur": VplibUnit.EURO,
    "euro": VplibUnit.EURO,
    "€": VplibUnit.EURO,
    "eur/m2": VplibUnit.EURO_PER_SQUARE_METER,
    "eur_per_m2": VplibUnit.EURO_PER_SQUARE_METER,
    "eur/m3": VplibUnit.EURO_PER_CUBIC_METER,
    "eur_per_m3": VplibUnit.EURO_PER_CUBIC_METER,
    "eur/pcs": VplibUnit.EURO_PER_PIECE,
    "eur_per_piece": VplibUnit.EURO_PER_PIECE,
    "eur_per_pcs": VplibUnit.EURO_PER_PIECE,
}


def _normalize_key(value: Any) -> str:
    """
    Normalize arbitrary input into a comparable unit key.

    Raises:
        UnitError: If the value cannot be converted into a usable key.
    """
    try:
        if isinstance(value, VplibUnit):
            return value.value

        if value is None:
            raise UnitError("Unit is required, got None.")

        raw = str(value).strip()
        if not raw:
            return ""

        return (
            raw.replace("²", "2")
            .replace("³", "3")
            .replace("·", "*")
            .replace(" ", "_")
            .strip()
            .lower()
        )
    except UnitError:
        raise
    except Exception as exc:
        raise UnitError(f"Could not normalize unit {value!r}.") from exc


@lru_cache(maxsize=512)
def parse_unit(value: Any) -> VplibUnit:
    """
    Parse a unit input into a canonical VplibUnit.

    Accepts canonical values and controlled aliases.

    Raises:
        UnitError: If the unit is unknown.
    """
    key = _normalize_key(value)

    try:
        return VplibUnit(key)
    except ValueError:
        pass

    try:
        return _ALIAS_MAP[key]
    except KeyError as exc:
        allowed = ", ".join(get_unit_values())
        raise UnitError(f"Unknown VPLIB unit {value!r}. Allowed values: {allowed}.") from exc


def try_parse_unit(value: Any, default: VplibUnit | None = None) -> VplibUnit | None:
    """
    Safe unit parser.

    Returns default instead of raising UnitError.
    """
    try:
        return parse_unit(value)
    except UnitError:
        return default
    except Exception:
        return default


def is_valid_unit(value: Any) -> bool:
    """Return True if value can be parsed as a canonical VPLIB unit."""
    try:
        parse_unit(value)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_unit_values() -> tuple[str, ...]:
    """Return all canonical unit string values."""
    return tuple(unit.value for unit in VplibUnit)


@lru_cache(maxsize=1)
def get_unit_aliases() -> Mapping[str, str]:
    """Return a read-only-style mapping of supported aliases to canonical values."""
    return {alias: unit.value for alias, unit in _ALIAS_MAP.items()}


@lru_cache(maxsize=1)
def get_unit_definitions() -> Mapping[VplibUnit, UnitDefinition]:
    """Return all canonical unit definitions."""
    return dict(_UNIT_DEFINITIONS)


@lru_cache(maxsize=256)
def get_unit_definition(value: Any) -> UnitDefinition:
    """
    Return the unit definition for a unit input.

    Raises:
        UnitError: If the unit is unknown or the definition is missing.
    """
    unit = parse_unit(value)

    try:
        return _UNIT_DEFINITIONS[unit]
    except KeyError as exc:
        raise UnitError(f"Missing unit definition for {unit.value!r}.") from exc


def ensure_unit(value: Any) -> VplibUnit:
    """Strict parser for call sites that require a valid unit."""
    return parse_unit(value)


def ensure_unit_value(value: Any) -> str:
    """Return the canonical string value for a unit input."""
    return ensure_unit(value).value


def get_unit_category(value: Any) -> UnitCategory:
    """Return the category for a unit."""
    return get_unit_definition(value).category


def get_unit_symbol(value: Any) -> str:
    """Return the display symbol for a unit."""
    return get_unit_definition(value).symbol


def get_base_unit(value: Any) -> VplibUnit:
    """Return the base unit for a unit."""
    return get_unit_definition(value).base_unit


def unit_supports_conversion(value: Any) -> bool:
    """Return whether a unit supports safe conversion in this module."""
    return get_unit_definition(value).supports_conversion


def unit_accepts_float(value: Any) -> bool:
    """Return whether values for this unit may be floats."""
    return get_unit_definition(value).accepts_float


def unit_accepts_integer(value: Any) -> bool:
    """Return whether values for this unit may be integers."""
    return get_unit_definition(value).accepts_integer


def unit_accepts_negative(value: Any) -> bool:
    """Return whether values for this unit may be negative."""
    return get_unit_definition(value).accepts_negative


def are_compatible_units(source_unit: Any, target_unit: Any) -> bool:
    """
    Return whether two units are compatible for conversion.

    Compatibility requires the same base unit and conversion support on both
    units. Some categories intentionally do not support conversion here.
    """
    try:
        source = get_unit_definition(source_unit)
        target = get_unit_definition(target_unit)

        if not source.supports_conversion or not target.supports_conversion:
            return False

        return source.base_unit == target.base_unit
    except Exception:
        return False


def convert_value(value: Any, source_unit: Any, target_unit: Any) -> float:
    """
    Convert a numeric value between compatible units.

    Raises:
        UnitError: If units are incompatible or the value is not numeric.
    """
    try:
        source = get_unit_definition(source_unit)
        target = get_unit_definition(target_unit)

        if not source.supports_conversion or not target.supports_conversion:
            raise UnitError(
                f"Conversion is not supported for {source.unit.value!r} or {target.unit.value!r}."
            )

        if source.base_unit != target.base_unit:
            raise UnitError(
                f"Cannot convert from {source.unit.value!r} to {target.unit.value!r}."
            )

        numeric_value = float(value)

        base_value = (numeric_value * source.factor_to_base) + source.offset_to_base
        return (base_value - target.offset_to_base) / target.factor_to_base
    except UnitError:
        raise
    except Exception as exc:
        raise UnitError(
            f"Could not convert value {value!r} from {source_unit!r} to {target_unit!r}."
        ) from exc


def normalize_numeric_value(value: Any, unit: Any) -> int | float:
    """
    Normalize and validate a numeric value for a unit.

    Returns an int if the unit accepts only integers, otherwise a float when
    needed. Raises UnitError for invalid values.
    """
    try:
        definition = get_unit_definition(unit)

        if isinstance(value, bool):
            raise UnitError("Boolean values are not valid numeric unit values.")

        if definition.accepts_integer and not definition.accepts_float:
            if isinstance(value, float) and not value.is_integer():
                raise UnitError(
                    f"Unit {definition.unit.value!r} requires an integer value."
                )
            numeric_int = int(value)
            if numeric_int < 0 and not definition.accepts_negative:
                raise UnitError(
                    f"Unit {definition.unit.value!r} does not accept negative values."
                )
            return numeric_int

        numeric_float = float(value)

        if numeric_float < 0 and not definition.accepts_negative:
            raise UnitError(
                f"Unit {definition.unit.value!r} does not accept negative values."
            )

        if numeric_float.is_integer():
            return int(numeric_float)

        return numeric_float
    except UnitError:
        raise
    except Exception as exc:
        raise UnitError(f"Invalid numeric value {value!r} for unit {unit!r}.") from exc


def validate_numeric_value(value: Any, unit: Any) -> tuple[bool, tuple[str, ...]]:
    """
    Validate a numeric value for a unit.

    Returns:
        Tuple of (is_valid, messages).
    """
    try:
        normalize_numeric_value(value, unit)
        return True, tuple()
    except UnitError as exc:
        return False, (str(exc),)
    except Exception as exc:
        return False, (f"Could not validate unit value: {exc}",)


def assert_valid_numeric_value(value: Any, unit: Any) -> None:
    """Raise UnitError if a value is invalid for a unit."""
    is_valid, messages = validate_numeric_value(value, unit)
    if not is_valid:
        joined = " ".join(messages) if messages else "Invalid unit value."
        raise UnitError(joined)


def get_units_by_category(category: Any) -> tuple[VplibUnit, ...]:
    """
    Return all units for a category.

    Raises:
        UnitError: If the category is unknown.
    """
    try:
        category_value = (
            category
            if isinstance(category, UnitCategory)
            else UnitCategory(str(category).strip().lower())
        )

        return tuple(
            unit
            for unit, definition in _UNIT_DEFINITIONS.items()
            if definition.category == category_value
        )
    except ValueError as exc:
        raise UnitError(f"Unknown unit category {category!r}.") from exc
    except Exception as exc:
        raise UnitError(f"Could not get units for category {category!r}.") from exc


def filter_valid_units(values: Iterable[Any]) -> tuple[VplibUnit, ...]:
    """
    Parse many values and return only valid units.

    Invalid entries are ignored. Duplicates are removed while preserving order.
    """
    result: list[VplibUnit] = []
    seen: set[VplibUnit] = set()

    for value in values:
        unit = try_parse_unit(value)
        if unit is None or unit in seen:
            continue
        result.append(unit)
        seen.add(unit)

    return tuple(result)


def unit_definition_to_json(value: Any) -> dict[str, Any]:
    """
    Serialize one unit definition into a JSON-compatible dictionary.
    """
    definition = get_unit_definition(value)

    return {
        "schema_version": UNIT_SCHEMA_VERSION,
        "unit": definition.unit.value,
        "category": definition.category.value,
        "title": definition.title,
        "symbol": definition.symbol,
        "base_unit": definition.base_unit.value,
        "factor_to_base": definition.factor_to_base,
        "offset_to_base": definition.offset_to_base,
        "supports_conversion": definition.supports_conversion,
        "accepts_float": definition.accepts_float,
        "accepts_integer": definition.accepts_integer,
        "accepts_negative": definition.accepts_negative,
        "typical_fields": list(definition.typical_fields),
    }


def all_units_to_json() -> list[dict[str, Any]]:
    """Serialize all unit definitions into JSON-compatible dictionaries."""
    return [unit_definition_to_json(unit) for unit in VplibUnit]


def build_unit_value_payload(
    value: Any,
    unit: Any,
    *,
    normalize: bool = True,
    convert_to_base: bool = False,
) -> dict[str, Any]:
    """
    Build a JSON-compatible payload for a value with unit metadata.

    Args:
        value: Numeric value.
        unit: Unit input.
        normalize: Validate and normalize numeric value.
        convert_to_base: Include base-unit value if conversion is supported.
    """
    parsed_unit = parse_unit(unit)
    definition = get_unit_definition(parsed_unit)
    numeric_value = normalize_numeric_value(value, parsed_unit) if normalize else value

    payload: dict[str, Any] = {
        "value": numeric_value,
        "unit": parsed_unit.value,
        "category": definition.category.value,
    }

    if convert_to_base and definition.supports_conversion:
        payload["base_value"] = convert_value(numeric_value, parsed_unit, definition.base_unit)
        payload["base_unit"] = definition.base_unit.value

    return payload


def clear_unit_caches() -> None:
    """
    Clear internal lru_cache state.

    Useful for tests and long-running developer sessions.
    """
    parse_unit.cache_clear()
    get_unit_values.cache_clear()
    get_unit_aliases.cache_clear()
    get_unit_definitions.cache_clear()
    get_unit_definition.cache_clear()


__all__ = [
    "UNIT_SCHEMA_VERSION",
    "UnitCategory",
    "UnitDefinition",
    "UnitError",
    "VplibUnit",
    "all_units_to_json",
    "are_compatible_units",
    "assert_valid_numeric_value",
    "build_unit_value_payload",
    "clear_unit_caches",
    "convert_value",
    "ensure_unit",
    "ensure_unit_value",
    "filter_valid_units",
    "get_base_unit",
    "get_unit_aliases",
    "get_unit_category",
    "get_unit_definition",
    "get_unit_definitions",
    "get_unit_symbol",
    "get_unit_values",
    "get_units_by_category",
    "is_valid_unit",
    "normalize_numeric_value",
    "parse_unit",
    "try_parse_unit",
    "unit_accepts_float",
    "unit_accepts_integer",
    "unit_accepts_negative",
    "unit_definition_to_json",
    "unit_supports_conversion",
    "validate_numeric_value",
]