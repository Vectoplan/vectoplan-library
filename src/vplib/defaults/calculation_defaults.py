# services/vectoplan-library/src/vplib/defaults/calculation_defaults.py
"""
Calculation defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    calculation/variables.json
    calculation/formulas.json
    calculation/quantities.json
    calculation/measure_logic.json
    optional: calculation/constraints.json
    optional: calculation/units.json
    optional: calculation/cost_factors.json

Calculation-Daten bleiben deklarativ. Es werden keine ausführbaren Skripte,
keine Python-Ausdrücke mit Seiteneffekten und keine externen Code-Referenzen
erlaubt. Formeln und Expressions sind reine deklarative Strings, die später von
einer sicheren Engine interpretiert werden können.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


CALCULATION_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.calculation_defaults.v1"
CALCULATION_VARIABLES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.variables.v1"
CALCULATION_FORMULAS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.formulas.v1"
CALCULATION_QUANTITIES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.quantities.v1"
CALCULATION_MEASURE_LOGIC_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.measure_logic.v1"
CALCULATION_CONSTRAINTS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.constraints.v1"
CALCULATION_UNITS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.units.v1"
CALCULATION_COST_FACTORS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.calculation.cost_factors.v1"

DEFAULT_PRIMARY_QUANTITY_ID: Final[str] = "count"
DEFAULT_COUNT_VARIABLE_ID: Final[str] = "count"
DEFAULT_COUNT_UNIT: Final[str] = "count"
DEFAULT_CURRENCY_UNIT: Final[str] = "EUR"
DEFAULT_COST_FACTOR_ID: Final[str] = "base_cost"

SAFE_CALCULATION_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_FIELD_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$"
)

FORBIDDEN_EXPRESSION_TOKENS: Final[tuple[str, ...]] = (
    "__",
    "import",
    "exec",
    "eval",
    "open(",
    "read(",
    "write(",
    "delete",
    "remove",
    "subprocess",
    "socket",
    "os.",
    "sys.",
    "lambda",
    "class ",
    "def ",
)


class CalculationDefaultsError(ValueError):
    """Wird ausgelöst, wenn Calculation-Defaults ungültig erzeugt werden."""


class VariableValueType(str, Enum):
    """Datentyp einer Calculation-Variable."""

    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    STRING = "string"
    ENUM = "enum"

    @property
    def key(self) -> str:
        return str(self.value)


class VariableSource(str, Enum):
    """Quelle einer Calculation-Variable."""

    USER = "user"
    DEFAULT = "default"
    PHYSICAL = "physical"
    MATERIAL = "material"
    GRID = "grid"
    VARIANT = "variant"
    COMPUTED = "computed"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class FormulaKind(str, Enum):
    """Formeltyp."""

    ARITHMETIC = "arithmetic"
    CONDITIONAL = "conditional"
    AGGREGATION = "aggregation"
    MEASURE = "measure"
    COST = "cost"
    CUSTOM_DECLARATIVE = "custom_declarative"

    @property
    def key(self) -> str:
        return str(self.value)


class QuantityKind(str, Enum):
    """Mengenart."""

    COUNT = "count"
    LENGTH = "length"
    AREA = "area"
    VOLUME = "volume"
    MASS = "mass"
    COST = "cost"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class MeasureMode(str, Enum):
    """Messlogik-Modus."""

    COUNT = "count"
    GRID_FOOTPRINT = "grid_footprint"
    PHYSICAL_DIMENSIONS = "physical_dimensions"
    CUSTOM_FORMULAS = "custom_formulas"

    @property
    def key(self) -> str:
        return str(self.value)


class ConstraintOperator(str, Enum):
    """Constraint-Operator."""

    EXISTS = "exists"
    NOT_EMPTY = "not_empty"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    IN = "in"
    NOT_IN = "not_in"
    BETWEEN = "between"

    @property
    def key(self) -> str:
        return str(self.value)


class ConstraintSeverity(str, Enum):
    """Constraint-Schweregrad."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class CostFactorKind(str, Enum):
    """Kostenfaktor-Art."""

    FIXED = "fixed"
    PER_PIECE = "per_piece"
    PER_LENGTH = "per_length"
    PER_AREA = "per_area"
    PER_VOLUME = "per_volume"
    PER_MASS = "per_mass"
    FORMULA = "formula"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CalculationVariableDefaults:
    """Eine deklarative Variable für calculation/variables.json."""

    variable_id: str
    label: str | None = None
    value_type: str = VariableValueType.NUMBER.value
    unit: str = "none"
    value: Any = None
    default_value: Any = None
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: tuple[Any, ...] = field(default_factory=tuple)
    editable: bool = True
    required: bool = False
    source: str = VariableSource.DEFAULT.value
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationVariableDefaults":
        variable_id = normalize_calculation_key(self.variable_id, "variable_id")
        label = clean_optional_string(self.label) or humanize_key(variable_id)
        value_type = parse_variable_value_type_value(self.value_type)
        unit = normalize_unit_value(self.unit)
        value = normalize_typed_value(self.value, value_type, allow_none=True)
        default_value = normalize_typed_value(self.default_value, value_type, allow_none=True)
        min_value = normalize_optional_float(self.min_value, "min_value")
        max_value = normalize_optional_float(self.max_value, "max_value")
        allowed_values = tuple(
            normalize_typed_value(item, value_type, allow_none=False)
            for item in self.allowed_values or ()
        )
        editable = bool(self.editable)
        required = bool(self.required)
        source = parse_variable_source_value(self.source)
        description = clean_optional_string(self.description) or ""
        metadata = normalize_metadata(self.metadata)

        if value is None and default_value is not None:
            value = default_value

        if required and value is None and default_value is None:
            raise CalculationDefaultsError(f"Required variable {variable_id!r} needs a value or default_value.")

        if min_value is not None and max_value is not None and min_value > max_value:
            raise CalculationDefaultsError(f"Variable {variable_id!r} has min_value greater than max_value.")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if min_value is not None and float(value) < min_value:
                raise CalculationDefaultsError(f"Variable {variable_id!r} value is below min_value.")
            if max_value is not None and float(value) > max_value:
                raise CalculationDefaultsError(f"Variable {variable_id!r} value is above max_value.")

        if allowed_values and value is not None and value not in allowed_values:
            raise CalculationDefaultsError(f"Variable {variable_id!r} value is not in allowed_values.")

        return CalculationVariableDefaults(
            variable_id=variable_id,
            label=label,
            value_type=value_type,
            unit=unit,
            value=value,
            default_value=default_value,
            min_value=min_value,
            max_value=max_value,
            allowed_values=allowed_values,
            editable=editable,
            required=required,
            source=source,
            description=description,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "variable_id": normalized.variable_id,
            "label": normalized.label,
            "value_type": normalized.value_type,
            "unit": normalized.unit,
            "value": normalized.value,
            "default_value": normalized.default_value,
            "min_value": normalized.min_value,
            "max_value": normalized.max_value,
            "allowed_values": list(normalized.allowed_values),
            "editable": normalized.editable,
            "required": normalized.required,
            "source": normalized.source,
            "description": normalized.description,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class CalculationVariablesDefaults:
    """Defaults für calculation/variables.json."""

    variables: tuple[CalculationVariableDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationVariablesDefaults":
        variables = tuple(variable.normalized() for variable in self.variables or ())

        if not variables:
            variables = (
                CalculationVariableDefaults(
                    variable_id=DEFAULT_COUNT_VARIABLE_ID,
                    label="Count",
                    value_type=VariableValueType.INTEGER.value,
                    unit=DEFAULT_COUNT_UNIT,
                    value=1,
                    default_value=1,
                    min_value=1,
                    editable=True,
                    required=True,
                    source=VariableSource.SYSTEM.value,
                ).normalized(),
            )

        assert_unique_values([variable.variable_id for variable in variables], "variable_id")

        return CalculationVariablesDefaults(
            variables=tuple(sorted(variables, key=lambda item: item.variable_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/variables.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_VARIABLES_DOCUMENT_SCHEMA_VERSION,
            "variable_ids": [variable.variable_id for variable in normalized.variables],
            "variables": [variable.to_dict() for variable in normalized.variables],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationFormulaDefaults:
    """Eine deklarative Formel für calculation/formulas.json."""

    formula_id: str
    expression: str
    label: str | None = None
    formula_kind: str = FormulaKind.ARITHMETIC.value
    inputs: tuple[str, ...] = field(default_factory=tuple)
    outputs: tuple[str, ...] = field(default_factory=tuple)
    unit: str = "none"
    enabled: bool = True
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationFormulaDefaults":
        formula_id = normalize_calculation_key(self.formula_id, "formula_id")
        expression = normalize_expression(self.expression, "expression")
        label = clean_optional_string(self.label) or humanize_key(formula_id)
        formula_kind = parse_formula_kind_value(self.formula_kind)
        inputs = normalize_field_tuple(self.inputs)
        outputs = normalize_field_tuple(self.outputs)
        unit = normalize_unit_value(self.unit)
        enabled = bool(self.enabled)
        description = clean_optional_string(self.description) or ""
        metadata = normalize_metadata(self.metadata)

        if not outputs:
            raise CalculationDefaultsError(f"Formula {formula_id!r} requires at least one output.")

        return CalculationFormulaDefaults(
            formula_id=formula_id,
            expression=expression,
            label=label,
            formula_kind=formula_kind,
            inputs=inputs,
            outputs=outputs,
            unit=unit,
            enabled=enabled,
            description=description,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "formula_id": normalized.formula_id,
            "label": normalized.label,
            "formula_kind": normalized.formula_kind,
            "expression": normalized.expression,
            "inputs": list(normalized.inputs),
            "outputs": list(normalized.outputs),
            "unit": normalized.unit,
            "enabled": normalized.enabled,
            "description": normalized.description,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class CalculationFormulasDefaults:
    """Defaults für calculation/formulas.json."""

    formulas: tuple[CalculationFormulaDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationFormulasDefaults":
        formulas = tuple(formula.normalized() for formula in self.formulas or ())
        assert_unique_values([formula.formula_id for formula in formulas], "formula_id")

        return CalculationFormulasDefaults(
            formulas=tuple(sorted(formulas, key=lambda item: item.formula_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/formulas.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_FORMULAS_DOCUMENT_SCHEMA_VERSION,
            "formula_ids": [formula.formula_id for formula in normalized.formulas],
            "formulas": [formula.to_dict() for formula in normalized.formulas],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationQuantityDefaults:
    """Eine auswertbare Quantity für calculation/quantities.json."""

    quantity_id: str
    quantity_kind: str
    label: str | None = None
    unit: str = "none"
    expression: str | None = None
    source_variable_id: str | None = None
    source_formula_id: str | None = None
    enabled: bool = True
    is_primary: bool = False
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationQuantityDefaults":
        quantity_id = normalize_calculation_key(self.quantity_id, "quantity_id")
        quantity_kind = parse_quantity_kind_value(self.quantity_kind)
        label = clean_optional_string(self.label) or humanize_key(quantity_id)
        unit = normalize_unit_value(self.unit)
        expression = normalize_optional_expression(self.expression, "expression")
        source_variable_id = normalize_optional_calculation_key(self.source_variable_id, "source_variable_id")
        source_formula_id = normalize_optional_calculation_key(self.source_formula_id, "source_formula_id")
        enabled = bool(self.enabled)
        is_primary = bool(self.is_primary)
        description = clean_optional_string(self.description) or ""
        metadata = normalize_metadata(self.metadata)

        if not expression and not source_variable_id and not source_formula_id:
            raise CalculationDefaultsError(
                f"Quantity {quantity_id!r} requires expression, source_variable_id or source_formula_id."
            )

        return CalculationQuantityDefaults(
            quantity_id=quantity_id,
            quantity_kind=quantity_kind,
            label=label,
            unit=unit,
            expression=expression,
            source_variable_id=source_variable_id,
            source_formula_id=source_formula_id,
            enabled=enabled,
            is_primary=is_primary,
            description=description,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "quantity_id": normalized.quantity_id,
            "quantity_kind": normalized.quantity_kind,
            "label": normalized.label,
            "unit": normalized.unit,
            "expression": normalized.expression,
            "source_variable_id": normalized.source_variable_id,
            "source_formula_id": normalized.source_formula_id,
            "enabled": normalized.enabled,
            "is_primary": normalized.is_primary,
            "description": normalized.description,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class CalculationQuantitiesDefaults:
    """Defaults für calculation/quantities.json."""

    quantities: tuple[CalculationQuantityDefaults, ...] = field(default_factory=tuple)
    primary_quantity_id: str = DEFAULT_PRIMARY_QUANTITY_ID
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationQuantitiesDefaults":
        primary_quantity_id = normalize_calculation_key(self.primary_quantity_id, "primary_quantity_id")
        quantities = tuple(quantity.normalized() for quantity in self.quantities or ())

        if not quantities:
            quantities = (
                CalculationQuantityDefaults(
                    quantity_id=primary_quantity_id,
                    quantity_kind=QuantityKind.COUNT.value,
                    label="Count",
                    unit=DEFAULT_COUNT_UNIT,
                    source_variable_id=DEFAULT_COUNT_VARIABLE_ID,
                    enabled=True,
                    is_primary=True,
                ).normalized(),
            )

        quantity_ids = [quantity.quantity_id for quantity in quantities]
        assert_unique_values(quantity_ids, "quantity_id")

        if primary_quantity_id not in set(quantity_ids):
            quantities = (
                CalculationQuantityDefaults(
                    quantity_id=primary_quantity_id,
                    quantity_kind=QuantityKind.COUNT.value,
                    label="Count",
                    unit=DEFAULT_COUNT_UNIT,
                    source_variable_id=DEFAULT_COUNT_VARIABLE_ID,
                    enabled=True,
                    is_primary=True,
                ).normalized(),
                *quantities,
            )

        normalized_quantities = []
        for quantity in quantities:
            normalized_quantities.append(
                CalculationQuantityDefaults(
                    quantity_id=quantity.quantity_id,
                    quantity_kind=quantity.quantity_kind,
                    label=quantity.label,
                    unit=quantity.unit,
                    expression=quantity.expression,
                    source_variable_id=quantity.source_variable_id,
                    source_formula_id=quantity.source_formula_id,
                    enabled=quantity.enabled,
                    is_primary=quantity.quantity_id == primary_quantity_id,
                    description=quantity.description,
                    metadata=quantity.metadata,
                ).normalized()
            )

        return CalculationQuantitiesDefaults(
            quantities=tuple(sorted(normalized_quantities, key=lambda item: (not item.is_primary, item.quantity_id))),
            primary_quantity_id=primary_quantity_id,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/quantities.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_QUANTITIES_DOCUMENT_SCHEMA_VERSION,
            "primary_quantity_id": normalized.primary_quantity_id,
            "quantity_ids": [quantity.quantity_id for quantity in normalized.quantities],
            "quantities": [quantity.to_dict() for quantity in normalized.quantities],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationConstraintDefaults:
    """Ein Constraint für calculation/constraints.json."""

    constraint_id: str
    field_path: str
    operator: str
    value: Any = None
    severity: str = ConstraintSeverity.ERROR.value
    message: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationConstraintDefaults":
        constraint_id = normalize_calculation_key(self.constraint_id, "constraint_id")
        field_path = normalize_field_path(self.field_path)
        operator = parse_constraint_operator_value(self.operator)
        value = normalize_json_value(self.value)
        severity = parse_constraint_severity_value(self.severity)
        message = clean_optional_string(self.message) or f"Constraint {constraint_id} failed."
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        if operator in {ConstraintOperator.IN.value, ConstraintOperator.NOT_IN.value, ConstraintOperator.BETWEEN.value}:
            if not isinstance(value, list):
                raise CalculationDefaultsError(f"Constraint {constraint_id!r} operator {operator!r} requires a list value.")

        return CalculationConstraintDefaults(
            constraint_id=constraint_id,
            field_path=field_path,
            operator=operator,
            value=value,
            severity=severity,
            message=message,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "constraint_id": normalized.constraint_id,
            "field_path": normalized.field_path,
            "operator": normalized.operator,
            "value": normalized.value,
            "severity": normalized.severity,
            "message": normalized.message,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class CalculationConstraintsDefaults:
    """Defaults für calculation/constraints.json."""

    constraints: tuple[CalculationConstraintDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationConstraintsDefaults":
        constraints = tuple(constraint.normalized() for constraint in self.constraints or ())
        assert_unique_values([constraint.constraint_id for constraint in constraints], "constraint_id")

        return CalculationConstraintsDefaults(
            constraints=tuple(sorted(constraints, key=lambda item: item.constraint_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/constraints.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_CONSTRAINTS_DOCUMENT_SCHEMA_VERSION,
            "constraint_ids": [constraint.constraint_id for constraint in normalized.constraints],
            "constraints": [constraint.to_dict() for constraint in normalized.constraints],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationMeasureLogicDefaults:
    """Defaults für calculation/measure_logic.json."""

    measure_mode: str = MeasureMode.COUNT.value
    primary_quantity_id: str = DEFAULT_PRIMARY_QUANTITY_ID
    count_expression: str = "count"
    length_expression: str | None = None
    area_expression: str | None = None
    volume_expression: str | None = None
    mass_expression: str | None = None
    cost_expression: str | None = None
    use_grid_footprint: bool = True
    use_physical_dimensions: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationMeasureLogicDefaults":
        measure_mode = parse_measure_mode_value(self.measure_mode)
        primary_quantity_id = normalize_calculation_key(self.primary_quantity_id, "primary_quantity_id")
        count_expression = normalize_expression(self.count_expression, "count_expression")
        length_expression = normalize_optional_expression(self.length_expression, "length_expression")
        area_expression = normalize_optional_expression(self.area_expression, "area_expression")
        volume_expression = normalize_optional_expression(self.volume_expression, "volume_expression")
        mass_expression = normalize_optional_expression(self.mass_expression, "mass_expression")
        cost_expression = normalize_optional_expression(self.cost_expression, "cost_expression")
        use_grid_footprint = bool(self.use_grid_footprint)
        use_physical_dimensions = bool(self.use_physical_dimensions)
        metadata = normalize_metadata(self.metadata)

        if measure_mode == MeasureMode.CUSTOM_FORMULAS.value:
            if not any((length_expression, area_expression, volume_expression, mass_expression, cost_expression)):
                raise CalculationDefaultsError("custom_formulas measure mode requires at least one custom expression.")

        return CalculationMeasureLogicDefaults(
            measure_mode=measure_mode,
            primary_quantity_id=primary_quantity_id,
            count_expression=count_expression,
            length_expression=length_expression,
            area_expression=area_expression,
            volume_expression=volume_expression,
            mass_expression=mass_expression,
            cost_expression=cost_expression,
            use_grid_footprint=use_grid_footprint,
            use_physical_dimensions=use_physical_dimensions,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/measure_logic.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_MEASURE_LOGIC_DOCUMENT_SCHEMA_VERSION,
            "measure_mode": normalized.measure_mode,
            "primary_quantity_id": normalized.primary_quantity_id,
            "expressions": {
                "count": normalized.count_expression,
                "length": normalized.length_expression,
                "area": normalized.area_expression,
                "volume": normalized.volume_expression,
                "mass": normalized.mass_expression,
                "cost": normalized.cost_expression,
            },
            "use_grid_footprint": normalized.use_grid_footprint,
            "use_physical_dimensions": normalized.use_physical_dimensions,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationUnitsDefaults:
    """Defaults für calculation/units.json."""

    units: tuple[str, ...] = field(default_factory=tuple)
    default_unit: str = "none"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationUnitsDefaults":
        units = normalize_unit_tuple(self.units or ("none", DEFAULT_COUNT_UNIT, "m", "m2", "m3", "kg", DEFAULT_CURRENCY_UNIT))
        default_unit = normalize_unit_value(self.default_unit)

        if default_unit not in units:
            units = (*units, default_unit)

        return CalculationUnitsDefaults(
            units=tuple(sorted(set(units))),
            default_unit=default_unit,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/units.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_UNITS_DOCUMENT_SCHEMA_VERSION,
            "default_unit": normalized.default_unit,
            "units": list(normalized.units),
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationCostFactorDefaults:
    """Ein Kostenfaktor für calculation/cost_factors.json."""

    cost_factor_id: str = DEFAULT_COST_FACTOR_ID
    label: str | None = None
    cost_factor_kind: str = CostFactorKind.FIXED.value
    value: float | None = None
    unit: str = DEFAULT_CURRENCY_UNIT
    expression: str | None = None
    currency: str = DEFAULT_CURRENCY_UNIT
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationCostFactorDefaults":
        cost_factor_id = normalize_calculation_key(self.cost_factor_id, "cost_factor_id")
        label = clean_optional_string(self.label) or humanize_key(cost_factor_id)
        cost_factor_kind = parse_cost_factor_kind_value(self.cost_factor_kind)
        value = normalize_optional_non_negative_float(self.value, "value")
        unit = normalize_unit_value(self.unit)
        expression = normalize_optional_expression(self.expression, "expression")
        currency = clean_required_string(self.currency or DEFAULT_CURRENCY_UNIT, "currency").upper()
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        if cost_factor_kind == CostFactorKind.FORMULA.value and not expression:
            raise CalculationDefaultsError(f"Cost factor {cost_factor_id!r} requires expression for formula kind.")

        if cost_factor_kind != CostFactorKind.FORMULA.value and value is None:
            value = 0.0

        return CalculationCostFactorDefaults(
            cost_factor_id=cost_factor_id,
            label=label,
            cost_factor_kind=cost_factor_kind,
            value=value,
            unit=unit,
            expression=expression,
            currency=currency,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "cost_factor_id": normalized.cost_factor_id,
            "label": normalized.label,
            "cost_factor_kind": normalized.cost_factor_kind,
            "value": normalized.value,
            "unit": normalized.unit,
            "expression": normalized.expression,
            "currency": normalized.currency,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class CalculationCostFactorsDefaults:
    """Defaults für calculation/cost_factors.json."""

    cost_factors: tuple[CalculationCostFactorDefaults, ...] = field(default_factory=tuple)
    currency: str = DEFAULT_CURRENCY_UNIT
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "CalculationCostFactorsDefaults":
        currency = clean_required_string(self.currency or DEFAULT_CURRENCY_UNIT, "currency").upper()
        cost_factors = tuple(factor.normalized() for factor in self.cost_factors or ())

        if not cost_factors:
            cost_factors = (
                CalculationCostFactorDefaults(
                    cost_factor_id=DEFAULT_COST_FACTOR_ID,
                    label="Base Cost",
                    cost_factor_kind=CostFactorKind.FIXED.value,
                    value=0.0,
                    unit=currency,
                    currency=currency,
                ).normalized(),
            )

        assert_unique_values([factor.cost_factor_id for factor in cost_factors], "cost_factor_id")

        return CalculationCostFactorsDefaults(
            cost_factors=tuple(sorted(cost_factors, key=lambda item: item.cost_factor_id)),
            currency=currency,
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt calculation/cost_factors.json."""
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_COST_FACTORS_DOCUMENT_SCHEMA_VERSION,
            "currency": normalized.currency,
            "cost_factor_ids": [factor.cost_factor_id for factor in normalized.cost_factors],
            "cost_factors": [factor.to_dict() for factor in normalized.cost_factors],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class CalculationDefaults:
    """Vollständige Defaults für alle calculation/*.json-Dokumente."""

    variables: CalculationVariablesDefaults = field(default_factory=CalculationVariablesDefaults)
    formulas: CalculationFormulasDefaults = field(default_factory=CalculationFormulasDefaults)
    quantities: CalculationQuantitiesDefaults = field(default_factory=CalculationQuantitiesDefaults)
    measure_logic: CalculationMeasureLogicDefaults = field(default_factory=CalculationMeasureLogicDefaults)
    constraints: CalculationConstraintsDefaults = field(default_factory=CalculationConstraintsDefaults)
    units: CalculationUnitsDefaults = field(default_factory=CalculationUnitsDefaults)
    cost_factors: CalculationCostFactorsDefaults = field(default_factory=CalculationCostFactorsDefaults)

    def normalized(self) -> "CalculationDefaults":
        variables = self.variables.normalized()
        formulas = self.formulas.normalized()
        quantities = self.quantities.normalized()
        measure_logic = self.measure_logic.normalized()
        constraints = self.constraints.normalized()

        units_from_content = collect_units_from_calculation_content(
            variables=variables,
            formulas=formulas,
            quantities=quantities,
            cost_factors=self.cost_factors,
        )

        units = CalculationUnitsDefaults(
            units=(*self.units.units, *units_from_content),
            default_unit=self.units.default_unit,
            metadata=self.units.metadata,
        ).normalized()

        cost_factors = self.cost_factors.normalized()

        validate_references(
            variables=variables,
            formulas=formulas,
            quantities=quantities,
            measure_logic=measure_logic,
        )

        return CalculationDefaults(
            variables=variables,
            formulas=formulas,
            quantities=quantities,
            measure_logic=measure_logic,
            constraints=constraints,
            units=units,
            cost_factors=cost_factors,
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Calculation-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "calculation/variables.json": normalized.variables.to_document(),
            "calculation/formulas.json": normalized.formulas.to_document(),
            "calculation/quantities.json": normalized.quantities.to_document(),
            "calculation/measure_logic.json": normalized.measure_logic.to_document(),
        }

        if include_optional:
            documents["calculation/constraints.json"] = normalized.constraints.to_document()
            documents["calculation/units.json"] = normalized.units.to_document()
            documents["calculation/cost_factors.json"] = normalized.cost_factors.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": CALCULATION_DEFAULTS_SCHEMA_VERSION,
            "variables": normalized.variables.to_dict(),
            "formulas": normalized.formulas.to_dict(),
            "quantities": normalized.quantities.to_dict(),
            "measure_logic": normalized.measure_logic.to_dict(),
            "constraints": normalized.constraints.to_dict(),
            "units": normalized.units.to_dict(),
            "cost_factors": normalized.cost_factors.to_dict(),
        }


def build_calculation_defaults(
    *,
    variables: Iterable[CalculationVariableDefaults | Mapping[str, Any]] = (),
    formulas: Iterable[CalculationFormulaDefaults | Mapping[str, Any]] = (),
    quantities: Iterable[CalculationQuantityDefaults | Mapping[str, Any]] = (),
    constraints: Iterable[CalculationConstraintDefaults | Mapping[str, Any]] = (),
    measure_mode: str = MeasureMode.COUNT.value,
    primary_quantity_id: str = DEFAULT_PRIMARY_QUANTITY_ID,
    cost_factors: Iterable[CalculationCostFactorDefaults | Mapping[str, Any]] = (),
    metadata: Mapping[str, Any] | None = None,
) -> CalculationDefaults:
    """Baut CalculationDefaults aus expliziten Werten."""
    try:
        parsed_variables = tuple(
            variable if isinstance(variable, CalculationVariableDefaults) else variable_defaults_from_mapping(variable)
            for variable in variables or ()
        )
        parsed_formulas = tuple(
            formula if isinstance(formula, CalculationFormulaDefaults) else formula_defaults_from_mapping(formula)
            for formula in formulas or ()
        )
        parsed_quantities = tuple(
            quantity if isinstance(quantity, CalculationQuantityDefaults) else quantity_defaults_from_mapping(quantity)
            for quantity in quantities or ()
        )
        parsed_constraints = tuple(
            constraint if isinstance(constraint, CalculationConstraintDefaults) else constraint_defaults_from_mapping(constraint)
            for constraint in constraints or ()
        )
        parsed_cost_factors = tuple(
            factor if isinstance(factor, CalculationCostFactorDefaults) else cost_factor_defaults_from_mapping(factor)
            for factor in cost_factors or ()
        )

        return CalculationDefaults(
            variables=CalculationVariablesDefaults(
                variables=parsed_variables,
                metadata=dict(metadata or {}),
            ),
            formulas=CalculationFormulasDefaults(
                formulas=parsed_formulas,
                metadata=dict(metadata or {}),
            ),
            quantities=CalculationQuantitiesDefaults(
                quantities=parsed_quantities,
                primary_quantity_id=primary_quantity_id,
                metadata=dict(metadata or {}),
            ),
            measure_logic=CalculationMeasureLogicDefaults(
                measure_mode=measure_mode,
                primary_quantity_id=primary_quantity_id,
                metadata=dict(metadata or {}),
            ),
            constraints=CalculationConstraintsDefaults(
                constraints=parsed_constraints,
                metadata=dict(metadata or {}),
            ),
            cost_factors=CalculationCostFactorsDefaults(
                cost_factors=parsed_cost_factors,
                metadata=dict(metadata or {}),
            ),
        ).normalized()
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Could not build calculation defaults: {exc}") from exc


def calculation_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> CalculationDefaults:
    """Baut CalculationDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        calculation = normalized_request.calculation.normalized()
        physical = normalized_request.physical.normalized()
        grid = normalized_request.grid.normalized()

        variables = list(default_variables_from_request(normalized_request))
        variables.extend(variable_defaults_from_mapping(item) for item in calculation.variables)

        formulas = list(default_formulas_from_request(normalized_request))
        formulas.extend(formula_defaults_from_mapping(item) for item in calculation.formulas)

        quantities = list(default_quantities_from_request(normalized_request))
        quantities.extend(quantity_defaults_from_mapping(item) for item in calculation.quantities)

        constraints = tuple(constraint_defaults_from_mapping(item) for item in calculation.constraints)

        measure_logic = measure_logic_from_mapping(calculation.measure_logic) if calculation.measure_logic else default_measure_logic_from_request(normalized_request)

        return CalculationDefaults(
            variables=CalculationVariablesDefaults(
                variables=tuple(variables),
                metadata={
                    "source": "create_request",
                    **dict(metadata or {}),
                },
            ),
            formulas=CalculationFormulasDefaults(
                formulas=tuple(formulas),
                metadata=dict(metadata or {}),
            ),
            quantities=CalculationQuantitiesDefaults(
                quantities=tuple(quantities),
                primary_quantity_id=measure_logic.primary_quantity_id,
                metadata=dict(metadata or {}),
            ),
            measure_logic=measure_logic,
            constraints=CalculationConstraintsDefaults(
                constraints=constraints,
                metadata=dict(metadata or {}),
            ),
            units=CalculationUnitsDefaults(
                units=("none", "count", "m", "m2", "m3", "kg", "kg/m3", "EUR"),
                metadata=dict(metadata or {}),
            ),
            cost_factors=CalculationCostFactorsDefaults(metadata=dict(metadata or {})),
        ).normalized()
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Could not build calculation defaults from CreateRequest: {exc}") from exc


def calculation_defaults_from_context(
    context: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> CalculationDefaults:
    """Baut CalculationDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context

        return build_calculation_defaults(
            metadata={
                "source": "package_context",
                "object_kind": normalized_context.object_kind,
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Could not build calculation defaults from PackageContext: {exc}") from exc


def calculation_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> CalculationDefaults:
    """Baut CalculationDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return calculation_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Could not build calculation defaults from CreationPlan: {exc}") from exc


def calculation_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle calculation/*.json-Dokumente aus CreateRequest."""
    return calculation_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def calculation_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle calculation/*.json-Dokumente aus PackageContext."""
    return calculation_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def calculation_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle calculation/*.json-Dokumente aus CreationPlan."""
    return calculation_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def default_variables_from_request(request: Any) -> tuple[CalculationVariableDefaults, ...]:
    """Erzeugt Baseline-Variablen aus Request-Daten."""
    normalized_request = normalize_create_request(request)
    grid = normalized_request.grid.normalized()
    physical = normalized_request.physical.normalized()

    variables = [
        CalculationVariableDefaults(
            variable_id="count",
            label="Count",
            value_type=VariableValueType.INTEGER.value,
            unit="count",
            value=1,
            default_value=1,
            min_value=1,
            editable=True,
            required=True,
            source=VariableSource.SYSTEM.value,
        ),
        CalculationVariableDefaults(
            variable_id="grid_size_x",
            label="Grid Size X",
            value_type=VariableValueType.INTEGER.value,
            unit="count",
            value=grid.size_cells_x,
            editable=False,
            source=VariableSource.GRID.value,
        ),
        CalculationVariableDefaults(
            variable_id="grid_size_y",
            label="Grid Size Y",
            value_type=VariableValueType.INTEGER.value,
            unit="count",
            value=grid.size_cells_y,
            editable=False,
            source=VariableSource.GRID.value,
        ),
        CalculationVariableDefaults(
            variable_id="grid_size_z",
            label="Grid Size Z",
            value_type=VariableValueType.INTEGER.value,
            unit="count",
            value=grid.size_cells_z,
            editable=False,
            source=VariableSource.GRID.value,
        ),
        CalculationVariableDefaults(
            variable_id="cell_size_m",
            label="Cell Size",
            value_type=VariableValueType.NUMBER.value,
            unit="m",
            value=grid.cell_size_m,
            editable=False,
            source=VariableSource.GRID.value,
        ),
    ]

    optional_physical_values = (
        ("real_width_m", physical.real_width_m, "m", VariableSource.PHYSICAL.value),
        ("real_height_m", physical.real_height_m, "m", VariableSource.PHYSICAL.value),
        ("real_depth_m", physical.real_depth_m, "m", VariableSource.PHYSICAL.value),
        ("wall_thickness_m", physical.wall_thickness_m, "m", VariableSource.PHYSICAL.value),
        ("volume_m3", physical.volume_m3, "m3", VariableSource.PHYSICAL.value),
        ("mass_kg", physical.mass_kg, "kg", VariableSource.PHYSICAL.value),
        ("density_kg_m3", physical.density_kg_m3, "kg/m3", VariableSource.PHYSICAL.value),
        ("raw_density_kg_m3", physical.raw_density_kg_m3, "kg/m3", VariableSource.PHYSICAL.value),
    )

    for variable_id, value, unit, source in optional_physical_values:
        if value is None:
            continue
        variables.append(
            CalculationVariableDefaults(
                variable_id=variable_id,
                label=humanize_key(variable_id),
                value_type=VariableValueType.NUMBER.value,
                unit=unit,
                value=value,
                editable=False,
                source=source,
            )
        )

    return tuple(variable.normalized() for variable in variables)


def default_formulas_from_request(request: Any) -> tuple[CalculationFormulaDefaults, ...]:
    """Erzeugt Baseline-Formeln aus Request-Daten."""
    normalized_request = normalize_create_request(request)
    grid = normalized_request.grid.normalized()

    formulas: list[CalculationFormulaDefaults] = [
        CalculationFormulaDefaults(
            formula_id="grid_volume_m3",
            label="Grid Volume",
            formula_kind=FormulaKind.MEASURE.value,
            expression="grid_size_x * grid_size_y * grid_size_z * cell_size_m * cell_size_m * cell_size_m",
            inputs=("grid_size_x", "grid_size_y", "grid_size_z", "cell_size_m"),
            outputs=("grid_volume_m3",),
            unit="m3",
        )
    ]

    if grid.size_cells_x > 0 and grid.size_cells_z > 0:
        formulas.append(
            CalculationFormulaDefaults(
                formula_id="grid_footprint_area_m2",
                label="Grid Footprint Area",
                formula_kind=FormulaKind.MEASURE.value,
                expression="grid_size_x * grid_size_z * cell_size_m * cell_size_m",
                inputs=("grid_size_x", "grid_size_z", "cell_size_m"),
                outputs=("grid_footprint_area_m2",),
                unit="m2",
            )
        )

    return tuple(formula.normalized() for formula in formulas)


def default_quantities_from_request(request: Any) -> tuple[CalculationQuantityDefaults, ...]:
    """Erzeugt Baseline-Quantities aus Request-Daten."""
    return (
        CalculationQuantityDefaults(
            quantity_id="count",
            quantity_kind=QuantityKind.COUNT.value,
            label="Count",
            unit="count",
            source_variable_id="count",
            enabled=True,
            is_primary=True,
        ).normalized(),
        CalculationQuantityDefaults(
            quantity_id="grid_volume_m3",
            quantity_kind=QuantityKind.VOLUME.value,
            label="Grid Volume",
            unit="m3",
            source_formula_id="grid_volume_m3",
            enabled=True,
            is_primary=False,
        ).normalized(),
        CalculationQuantityDefaults(
            quantity_id="grid_footprint_area_m2",
            quantity_kind=QuantityKind.AREA.value,
            label="Grid Footprint Area",
            unit="m2",
            source_formula_id="grid_footprint_area_m2",
            enabled=True,
            is_primary=False,
        ).normalized(),
    )


def default_measure_logic_from_request(request: Any) -> CalculationMeasureLogicDefaults:
    """Erzeugt MeasureLogic aus object_kind und vorhandenen Daten."""
    normalized_request = normalize_create_request(request)
    object_kind = normalized_request.object_kind

    if object_kind in {"cell_block", "multi_cell_module"}:
        return CalculationMeasureLogicDefaults(
            measure_mode=MeasureMode.GRID_FOOTPRINT.value,
            primary_quantity_id="grid_volume_m3",
            count_expression="count",
            area_expression="grid_footprint_area_m2",
            volume_expression="grid_volume_m3",
            use_grid_footprint=True,
            use_physical_dimensions=True,
        ).normalized()

    return CalculationMeasureLogicDefaults(
        measure_mode=MeasureMode.COUNT.value,
        primary_quantity_id="count",
        count_expression="count",
        use_grid_footprint=True,
        use_physical_dimensions=True,
    ).normalized()


def variable_defaults_from_mapping(data: Mapping[str, Any]) -> CalculationVariableDefaults:
    """Baut CalculationVariableDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise CalculationDefaultsError("Variable data must be a mapping.")

    return CalculationVariableDefaults(
        variable_id=data.get("variable_id") or data.get("id"),
        label=data.get("label") or data.get("name"),
        value_type=data.get("value_type", VariableValueType.NUMBER.value),
        unit=data.get("unit", "none"),
        value=data.get("value"),
        default_value=data.get("default_value"),
        min_value=data.get("min_value"),
        max_value=data.get("max_value"),
        allowed_values=tuple(data.get("allowed_values", ()) or ()),
        editable=bool(data.get("editable", True)),
        required=bool(data.get("required", False)),
        source=data.get("source", VariableSource.DEFAULT.value),
        description=data.get("description", ""),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def formula_defaults_from_mapping(data: Mapping[str, Any]) -> CalculationFormulaDefaults:
    """Baut CalculationFormulaDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise CalculationDefaultsError("Formula data must be a mapping.")

    return CalculationFormulaDefaults(
        formula_id=data.get("formula_id") or data.get("id"),
        label=data.get("label") or data.get("name"),
        formula_kind=data.get("formula_kind", FormulaKind.ARITHMETIC.value),
        expression=data.get("expression"),
        inputs=tuple(data.get("inputs", ()) or ()),
        outputs=tuple(data.get("outputs", ()) or ()),
        unit=data.get("unit", "none"),
        enabled=bool(data.get("enabled", True)),
        description=data.get("description", ""),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def quantity_defaults_from_mapping(data: Mapping[str, Any]) -> CalculationQuantityDefaults:
    """Baut CalculationQuantityDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise CalculationDefaultsError("Quantity data must be a mapping.")

    return CalculationQuantityDefaults(
        quantity_id=data.get("quantity_id") or data.get("id"),
        quantity_kind=data.get("quantity_kind", QuantityKind.CUSTOM.value),
        label=data.get("label") or data.get("name"),
        unit=data.get("unit", "none"),
        expression=data.get("expression"),
        source_variable_id=data.get("source_variable_id"),
        source_formula_id=data.get("source_formula_id"),
        enabled=bool(data.get("enabled", True)),
        is_primary=bool(data.get("is_primary", False)),
        description=data.get("description", ""),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def constraint_defaults_from_mapping(data: Mapping[str, Any]) -> CalculationConstraintDefaults:
    """Baut CalculationConstraintDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise CalculationDefaultsError("Constraint data must be a mapping.")

    return CalculationConstraintDefaults(
        constraint_id=data.get("constraint_id") or data.get("id"),
        field_path=data.get("field_path") or data.get("field"),
        operator=data.get("operator"),
        value=data.get("value"),
        severity=data.get("severity", ConstraintSeverity.ERROR.value),
        message=data.get("message"),
        enabled=bool(data.get("enabled", True)),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def measure_logic_from_mapping(data: Mapping[str, Any]) -> CalculationMeasureLogicDefaults:
    """Baut CalculationMeasureLogicDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise CalculationDefaultsError("Measure logic data must be a mapping.")

    expressions = data.get("expressions", {}) if isinstance(data.get("expressions"), Mapping) else {}

    return CalculationMeasureLogicDefaults(
        measure_mode=data.get("measure_mode", MeasureMode.COUNT.value),
        primary_quantity_id=data.get("primary_quantity_id", DEFAULT_PRIMARY_QUANTITY_ID),
        count_expression=data.get("count_expression", expressions.get("count", "count")),
        length_expression=data.get("length_expression", expressions.get("length")),
        area_expression=data.get("area_expression", expressions.get("area")),
        volume_expression=data.get("volume_expression", expressions.get("volume")),
        mass_expression=data.get("mass_expression", expressions.get("mass")),
        cost_expression=data.get("cost_expression", expressions.get("cost")),
        use_grid_footprint=bool(data.get("use_grid_footprint", True)),
        use_physical_dimensions=bool(data.get("use_physical_dimensions", True)),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def cost_factor_defaults_from_mapping(data: Mapping[str, Any]) -> CalculationCostFactorDefaults:
    """Baut CalculationCostFactorDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise CalculationDefaultsError("Cost factor data must be a mapping.")

    return CalculationCostFactorDefaults(
        cost_factor_id=data.get("cost_factor_id") or data.get("id"),
        label=data.get("label") or data.get("name"),
        cost_factor_kind=data.get("cost_factor_kind", CostFactorKind.FIXED.value),
        value=data.get("value"),
        unit=data.get("unit", DEFAULT_CURRENCY_UNIT),
        expression=data.get("expression"),
        currency=data.get("currency", DEFAULT_CURRENCY_UNIT),
        enabled=bool(data.get("enabled", True)),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def validate_references(
    *,
    variables: CalculationVariablesDefaults,
    formulas: CalculationFormulasDefaults,
    quantities: CalculationQuantitiesDefaults,
    measure_logic: CalculationMeasureLogicDefaults,
) -> None:
    """Prüft einfache Referenzen zwischen Variablen, Formeln, Quantities und MeasureLogic."""
    variable_ids = {variable.variable_id for variable in variables.variables}
    formula_ids = {formula.formula_id for formula in formulas.formulas}
    quantity_ids = {quantity.quantity_id for quantity in quantities.quantities}

    for formula in formulas.formulas:
        missing_inputs = [item for item in formula.inputs if item not in variable_ids and item not in quantity_ids]
        if missing_inputs:
            raise CalculationDefaultsError(
                f"Formula {formula.formula_id!r} references missing inputs: {', '.join(missing_inputs)}."
            )

    for quantity in quantities.quantities:
        if quantity.source_variable_id and quantity.source_variable_id not in variable_ids:
            raise CalculationDefaultsError(
                f"Quantity {quantity.quantity_id!r} references missing variable {quantity.source_variable_id!r}."
            )
        if quantity.source_formula_id and quantity.source_formula_id not in formula_ids:
            raise CalculationDefaultsError(
                f"Quantity {quantity.quantity_id!r} references missing formula {quantity.source_formula_id!r}."
            )

    if measure_logic.primary_quantity_id not in quantity_ids:
        raise CalculationDefaultsError(
            f"Measure logic references missing primary_quantity_id {measure_logic.primary_quantity_id!r}."
        )


def collect_units_from_calculation_content(
    *,
    variables: CalculationVariablesDefaults,
    formulas: CalculationFormulasDefaults,
    quantities: CalculationQuantitiesDefaults,
    cost_factors: CalculationCostFactorsDefaults,
) -> tuple[str, ...]:
    """Sammelt verwendete Units aus Calculation-Inhalten."""
    units: list[str] = []

    for variable in variables.variables:
        units.append(variable.unit)

    for formula in formulas.formulas:
        units.append(formula.unit)

    for quantity in quantities.quantities:
        units.append(quantity.unit)

    for factor in cost_factors.cost_factors:
        units.append(factor.unit)

    return normalize_unit_tuple(units)


def validate_variables_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob calculation/variables.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("calculation/variables.json must be a mapping.",)

        if "variables" not in document:
            messages.append("Missing variables field 'variables'.")
        elif not isinstance(document["variables"], list):
            messages.append("variables must be a list.")
        else:
            for item in document["variables"]:
                try:
                    variable_defaults_from_mapping(item)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate variables document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_formulas_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob calculation/formulas.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("calculation/formulas.json must be a mapping.",)

        if "formulas" not in document:
            messages.append("Missing formulas field 'formulas'.")
        elif not isinstance(document["formulas"], list):
            messages.append("formulas must be a list.")
        else:
            for item in document["formulas"]:
                try:
                    formula_defaults_from_mapping(item)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate formulas document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_quantities_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob calculation/quantities.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("calculation/quantities.json must be a mapping.",)

        if "quantities" not in document:
            messages.append("Missing quantities field 'quantities'.")
        elif not isinstance(document["quantities"], list):
            messages.append("quantities must be a list.")
        else:
            for item in document["quantities"]:
                try:
                    quantity_defaults_from_mapping(item)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate quantities document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_measure_logic_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob calculation/measure_logic.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("calculation/measure_logic.json must be a mapping.",)

        try:
            measure_logic_from_mapping(document)
        except Exception as exc:
            messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate measure_logic document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_variables_document(document: Mapping[str, Any]) -> None:
    """Wirft CalculationDefaultsError, wenn calculation/variables.json ungültig ist."""
    valid, messages = validate_variables_document(document)
    if not valid:
        raise CalculationDefaultsError(" ".join(messages) if messages else "Invalid variables document.")


def assert_valid_formulas_document(document: Mapping[str, Any]) -> None:
    """Wirft CalculationDefaultsError, wenn calculation/formulas.json ungültig ist."""
    valid, messages = validate_formulas_document(document)
    if not valid:
        raise CalculationDefaultsError(" ".join(messages) if messages else "Invalid formulas document.")


def assert_valid_quantities_document(document: Mapping[str, Any]) -> None:
    """Wirft CalculationDefaultsError, wenn calculation/quantities.json ungültig ist."""
    valid, messages = validate_quantities_document(document)
    if not valid:
        raise CalculationDefaultsError(" ".join(messages) if messages else "Invalid quantities document.")


def assert_valid_measure_logic_document(document: Mapping[str, Any]) -> None:
    """Wirft CalculationDefaultsError, wenn calculation/measure_logic.json ungültig ist."""
    valid, messages = validate_measure_logic_document(document)
    if not valid:
        raise CalculationDefaultsError(" ".join(messages) if messages else "Invalid measure_logic document.")


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

        raise CalculationDefaultsError("CreateRequest value is required.")
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_unit_value(value: Any) -> str:
    """Normalisiert Unit-Werte über domain.units."""
    try:
        from ..domain.units import ensure_unit_value

        return ensure_unit_value(value)
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid unit {value!r}: {exc}") from exc


def normalize_unit_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Unit-Liste ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        unit = normalize_unit_value(value)
        if unit in seen:
            continue
        result.append(unit)
        seen.add(unit)

    return tuple(result)


def normalize_calculation_key(value: Any, field_name: str) -> str:
    """Normalisiert technische Calculation-Keys."""
    raw = clean_required_string(value, field_name)
    key = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_CALCULATION_KEY_RE.match(key):
        raise CalculationDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return key


def normalize_optional_calculation_key(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Calculation-Keys."""
    if value is None:
        return None

    return normalize_calculation_key(value, field_name)


def normalize_field_path(value: Any) -> str:
    """Normalisiert Field-Path."""
    raw = clean_required_string(value, "field_path")
    field_path = (
        raw.strip()
        .replace(" ", "_")
        .replace("/", ".")
        .replace("\\", ".")
    )

    if not SAFE_FIELD_PATH_RE.match(field_path):
        raise CalculationDefaultsError(f"Unsafe field_path {value!r}.")

    return field_path


def normalize_field_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Feldreferenzen."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        field = normalize_field_path(value)
        if field in seen:
            continue
        result.append(field)
        seen.add(field)

    return tuple(result)


def normalize_expression(value: Any, field_name: str) -> str:
    """Normalisiert deklarative Expression und blockiert offensichtlich ausführbare Muster."""
    expression = clean_required_string(value, field_name)

    lowered = expression.lower()
    for token in FORBIDDEN_EXPRESSION_TOKENS:
        if token in lowered:
            raise CalculationDefaultsError(
                f"{field_name} contains forbidden expression token {token!r}."
            )

    return expression


def normalize_optional_expression(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Expression."""
    if value is None:
        return None

    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    return normalize_expression(cleaned, field_name)


def normalize_typed_value(value: Any, value_type: str, *, allow_none: bool) -> Any:
    """Normalisiert Werte anhand des VariableValueType."""
    if value is None:
        if allow_none:
            return None
        raise CalculationDefaultsError("Value must not be None.")

    type_value = parse_variable_value_type_value(value_type)

    try:
        if type_value == VariableValueType.NUMBER.value:
            if isinstance(value, bool):
                raise CalculationDefaultsError("Number value must not be boolean.")
            number = float(value)
            return int(number) if number.is_integer() else number

        if type_value == VariableValueType.INTEGER.value:
            if isinstance(value, bool):
                raise CalculationDefaultsError("Integer value must not be boolean.")
            return int(value)

        if type_value == VariableValueType.BOOLEAN.value:
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"true", "1", "yes", "on"}:
                return True
            if raw in {"false", "0", "no", "off"}:
                return False
            raise CalculationDefaultsError(f"Invalid boolean value {value!r}.")

        if type_value in {VariableValueType.STRING.value, VariableValueType.ENUM.value}:
            return str(value).strip()

        return normalize_json_value(value)
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid value {value!r} for type {value_type!r}.") from exc


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


@lru_cache(maxsize=128)
def parse_variable_value_type_value(value: Any) -> str:
    """Parst VariableValueType."""
    try:
        if isinstance(value, VariableValueType):
            return value.value

        raw = normalize_enum_key(value)
        return VariableValueType(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid variable value type {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_variable_source_value(value: Any) -> str:
    """Parst VariableSource."""
    try:
        if isinstance(value, VariableSource):
            return value.value

        raw = normalize_enum_key(value)
        return VariableSource(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid variable source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_formula_kind_value(value: Any) -> str:
    """Parst FormulaKind."""
    try:
        if isinstance(value, FormulaKind):
            return value.value

        raw = normalize_enum_key(value)
        return FormulaKind(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid formula kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_quantity_kind_value(value: Any) -> str:
    """Parst QuantityKind."""
    try:
        if isinstance(value, QuantityKind):
            return value.value

        raw = normalize_enum_key(value)
        return QuantityKind(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid quantity kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_measure_mode_value(value: Any) -> str:
    """Parst MeasureMode."""
    try:
        if isinstance(value, MeasureMode):
            return value.value

        raw = normalize_enum_key(value)
        return MeasureMode(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid measure mode {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_constraint_operator_value(value: Any) -> str:
    """Parst ConstraintOperator."""
    try:
        if isinstance(value, ConstraintOperator):
            return value.value

        raw = normalize_enum_key(value)
        return ConstraintOperator(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid constraint operator {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_constraint_severity_value(value: Any) -> str:
    """Parst ConstraintSeverity."""
    try:
        if isinstance(value, ConstraintSeverity):
            return value.value

        raw = normalize_enum_key(value)
        return ConstraintSeverity(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid constraint severity {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_cost_factor_kind_value(value: Any) -> str:
    """Parst CostFactorKind."""
    try:
        if isinstance(value, CostFactorKind):
            return value.value

        raw = normalize_enum_key(value)
        return CostFactorKind(raw).value
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid cost factor kind {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise CalculationDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise CalculationDefaultsError(f"{field_name} must be a number.")
        return float(value)
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"{field_name} must be a number.") from exc


def normalize_optional_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionalen Float."""
    if value is None:
        return None
    return normalize_float(value, field_name)


def normalize_non_negative_float(value: Any, field_name: str) -> float:
    """Normalisiert nicht-negative Float-Werte."""
    number = normalize_float(value, field_name)
    if number < 0:
        raise CalculationDefaultsError(f"{field_name} must be >= 0.")
    return number


def normalize_optional_non_negative_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionale nicht-negative Float-Werte."""
    if value is None:
        return None
    return normalize_non_negative_float(value, field_name)


def assert_unique_values(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige Werte."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise CalculationDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def humanize_key(value: Any) -> str:
    """Erzeugt einfaches Label aus technischem Key."""
    return str(value).replace("_", " ").replace(".", " ").title()


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise CalculationDefaultsError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise CalculationDefaultsError(f"{field_name} is required.")

        return cleaned
    except CalculationDefaultsError:
        raise
    except Exception as exc:
        raise CalculationDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_calculation_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_variable_value_type_value.cache_clear()
    parse_variable_source_value.cache_clear()
    parse_formula_kind_value.cache_clear()
    parse_quantity_kind_value.cache_clear()
    parse_measure_mode_value.cache_clear()
    parse_constraint_operator_value.cache_clear()
    parse_constraint_severity_value.cache_clear()
    parse_cost_factor_kind_value.cache_clear()


__all__ = [
    "CALCULATION_CONSTRAINTS_DOCUMENT_SCHEMA_VERSION",
    "CALCULATION_COST_FACTORS_DOCUMENT_SCHEMA_VERSION",
    "CALCULATION_DEFAULTS_SCHEMA_VERSION",
    "CALCULATION_FORMULAS_DOCUMENT_SCHEMA_VERSION",
    "CALCULATION_MEASURE_LOGIC_DOCUMENT_SCHEMA_VERSION",
    "CALCULATION_QUANTITIES_DOCUMENT_SCHEMA_VERSION",
    "CALCULATION_UNITS_DOCUMENT_SCHEMA_VERSION",
    "CALCULATION_VARIABLES_DOCUMENT_SCHEMA_VERSION",
    "DEFAULT_COST_FACTOR_ID",
    "DEFAULT_COUNT_UNIT",
    "DEFAULT_COUNT_VARIABLE_ID",
    "DEFAULT_CURRENCY_UNIT",
    "DEFAULT_PRIMARY_QUANTITY_ID",
    "FORBIDDEN_EXPRESSION_TOKENS",
    "SAFE_CALCULATION_KEY_RE",
    "SAFE_FIELD_PATH_RE",
    "CalculationConstraintDefaults",
    "CalculationConstraintsDefaults",
    "CalculationCostFactorDefaults",
    "CalculationCostFactorsDefaults",
    "CalculationDefaults",
    "CalculationDefaultsError",
    "CalculationFormulaDefaults",
    "CalculationFormulasDefaults",
    "CalculationMeasureLogicDefaults",
    "CalculationQuantitiesDefaults",
    "CalculationQuantityDefaults",
    "CalculationUnitsDefaults",
    "CalculationVariableDefaults",
    "CalculationVariablesDefaults",
    "ConstraintOperator",
    "ConstraintSeverity",
    "CostFactorKind",
    "FormulaKind",
    "MeasureMode",
    "QuantityKind",
    "VariableSource",
    "VariableValueType",
    "assert_unique_values",
    "assert_valid_formulas_document",
    "assert_valid_measure_logic_document",
    "assert_valid_quantities_document",
    "assert_valid_variables_document",
    "build_calculation_defaults",
    "calculation_defaults_from_context",
    "calculation_defaults_from_create_request",
    "calculation_defaults_from_creation_plan",
    "calculation_documents_from_context",
    "calculation_documents_from_create_request",
    "calculation_documents_from_creation_plan",
    "clean_optional_string",
    "clean_required_string",
    "clear_calculation_defaults_caches",
    "collect_units_from_calculation_content",
    "constraint_defaults_from_mapping",
    "cost_factor_defaults_from_mapping",
    "default_formulas_from_request",
    "default_measure_logic_from_request",
    "default_quantities_from_request",
    "default_variables_from_request",
    "formula_defaults_from_mapping",
    "humanize_key",
    "measure_logic_from_mapping",
    "normalize_calculation_key",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_expression",
    "normalize_field_path",
    "normalize_field_tuple",
    "normalize_float",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_non_negative_float",
    "normalize_optional_calculation_key",
    "normalize_optional_expression",
    "normalize_optional_float",
    "normalize_optional_non_negative_float",
    "normalize_typed_value",
    "normalize_unit_tuple",
    "normalize_unit_value",
    "parse_constraint_operator_value",
    "parse_constraint_severity_value",
    "parse_cost_factor_kind_value",
    "parse_formula_kind_value",
    "parse_measure_mode_value",
    "parse_quantity_kind_value",
    "parse_variable_source_value",
    "parse_variable_value_type_value",
    "quantity_defaults_from_mapping",
    "validate_formulas_document",
    "validate_measure_logic_document",
    "validate_quantities_document",
    "validate_references",
    "validate_variables_document",
    "variable_defaults_from_mapping",
]