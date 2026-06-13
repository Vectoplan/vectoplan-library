# services/vectoplan-library/src/vplib/defaults/dynamic_defaults.py
"""
Dynamic defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    dynamic/context_rules.json
    dynamic/bindings.json
    dynamic/generator.json
    optional: dynamic/parameters.json
    optional: dynamic/constraints.json
    optional: dynamic/rule_graph.json
    optional: dynamic/host_contract.json

Dynamic-Daten beschreiben adaptive, host- oder kontextabhängige Systeme.

Wichtig:
Dynamic-Daten bleiben deklarativ. Es werden keine ausführbaren Skripte,
keine Python-Dateien, keine freien Imports und keine externen Code-Referenzen
erlaubt. Ein adaptive_system beschreibt seine spätere Logik über Regeln,
Bindings, Parameter und Generator-Metadaten.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


DYNAMIC_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.dynamic_defaults.v1"
DYNAMIC_CONTEXT_RULES_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.context_rules.v1"
DYNAMIC_BINDINGS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.bindings.v1"
DYNAMIC_GENERATOR_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.generator.v1"
DYNAMIC_PARAMETERS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.parameters.v1"
DYNAMIC_CONSTRAINTS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.constraints.v1"
DYNAMIC_RULE_GRAPH_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.rule_graph.v1"
DYNAMIC_HOST_CONTRACT_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.dynamic.host_contract.v1"

DEFAULT_DYNAMIC_SYSTEM_ID: Final[str] = "default_dynamic_system"
DEFAULT_CONTEXT_RULE_ID: Final[str] = "default_context_rule"
DEFAULT_BINDING_ID: Final[str] = "default_binding"
DEFAULT_GENERATOR_ID: Final[str] = "default_generator"
DEFAULT_PARAMETER_ID: Final[str] = "default_parameter"
DEFAULT_CONSTRAINT_ID: Final[str] = "default_constraint"
DEFAULT_RULE_NODE_ID: Final[str] = "default_node"
DEFAULT_HOST_CONTRACT_ID: Final[str] = "default_host_contract"

SAFE_DYNAMIC_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_FIELD_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$"
)

FORBIDDEN_DYNAMIC_EXPRESSION_TOKENS: Final[tuple[str, ...]] = (
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
    "while ",
    "for ",
)


class DynamicDefaultsError(ValueError):
    """Wird ausgelöst, wenn Dynamic-Defaults ungültig erzeugt werden."""


class DynamicSystemKind(str, Enum):
    """Adaptive Systemart."""

    NONE = "none"
    GENERIC = "generic"
    HOST_ADAPTIVE = "host_adaptive"
    SURFACE_ADAPTIVE = "surface_adaptive"
    ROUTING_SYSTEM = "routing_system"
    PARAMETRIC_COMPONENT = "parametric_component"
    BRIDGE_CAP = "bridge_cap"
    RAILING = "railing"
    EDGE_BEAM = "edge_beam"
    PIPE_SYSTEM = "pipe_system"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicRuleKind(str, Enum):
    """Art einer deklarativen Kontextregel."""

    CONDITION = "condition"
    SELECTOR = "selector"
    HOST_FILTER = "host_filter"
    PLACEMENT_RULE = "placement_rule"
    GEOMETRY_RULE = "geometry_rule"
    PARAMETER_RULE = "parameter_rule"
    ROUTING_RULE = "routing_rule"
    VALIDATION_RULE = "validation_rule"
    CUSTOM_DECLARATIVE = "custom_declarative"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicBindingKind(str, Enum):
    """Binding-Art."""

    HOST = "host"
    SURFACE = "surface"
    ANCHOR = "anchor"
    SOCKET = "socket"
    PORT = "port"
    PARAMETER = "parameter"
    VARIANT = "variant"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    EDITOR = "editor"
    RENDER = "render"
    CONTEXT = "context"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicGeneratorKind(str, Enum):
    """Art des deklarativen Generators."""

    NONE = "none"
    DECLARATIVE_TEMPLATE = "declarative_template"
    PARAMETER_MAPPING = "parameter_mapping"
    RULE_GRAPH = "rule_graph"
    ROUTING_GRAPH = "routing_graph"
    ADAPTIVE_PROFILE = "adaptive_profile"
    CUSTOM_DECLARATIVE = "custom_declarative"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicValueType(str, Enum):
    """Datentyp für Dynamic-Parameter und Werte."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    UNIT_VALUE = "unit_value"
    VECTOR3 = "vector3"
    FIELD_REF = "field_ref"
    EXPRESSION = "expression"
    OBJECT = "object"
    ARRAY = "array"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicParameterSource(str, Enum):
    """Quelle eines Dynamic-Parameters."""

    DEFAULT = "default"
    USER = "user"
    HOST = "host"
    SURFACE = "surface"
    VARIANT = "variant"
    EDITOR = "editor"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    MANUFACTURER = "manufacturer"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicConstraintOperator(str, Enum):
    """Constraint-Operator für Dynamic-Daten."""

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
    MATCHES = "matches"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicConstraintSeverity(str, Enum):
    """Schweregrad eines Dynamic-Constraints."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicRuleGraphNodeKind(str, Enum):
    """Node-Art im deklarativen Rule-Graph."""

    START = "start"
    CONDITION = "condition"
    PARAMETER = "parameter"
    BINDING = "binding"
    OUTPUT = "output"
    VALIDATION = "validation"
    END = "end"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicHostKind(str, Enum):
    """Erlaubte Host-Art."""

    ANY = "any"
    GRID = "grid"
    BLOCK = "block"
    SURFACE = "surface"
    WALL = "wall"
    FLOOR = "floor"
    CEILING = "ceiling"
    EDGE = "edge"
    PATH = "path"
    ROUTE = "route"
    STRUCTURE = "structure"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class DynamicEvaluationMode(str, Enum):
    """Auswertungsmodus."""

    DECLARATIVE_ONLY = "declarative_only"
    STATIC_PREVIEW = "static_preview"
    HOST_CONTEXT = "host_context"
    PARAMETER_CONTEXT = "parameter_context"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class DynamicParameterDefaults:
    """Ein deklarativer Dynamic-Parameter."""

    parameter_id: str
    value_type: str = DynamicValueType.STRING.value
    label: str | None = None
    value: Any = None
    default_value: Any = None
    unit: str | None = None
    required: bool = False
    editable: bool = True
    source: str = DynamicParameterSource.DEFAULT.value
    description: str = ""
    allowed_values: tuple[Any, ...] = field(default_factory=tuple)
    min_value: float | None = None
    max_value: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicParameterDefaults":
        parameter_id = normalize_dynamic_key(self.parameter_id, "parameter_id")
        value_type = parse_value_type_value(self.value_type)
        label = clean_optional_string(self.label) or humanize_key(parameter_id)
        value = normalize_typed_value(self.value, value_type, allow_none=True)
        default_value = normalize_typed_value(self.default_value, value_type, allow_none=True)
        unit = normalize_optional_unit_value(self.unit)
        required = bool(self.required)
        editable = bool(self.editable)
        source = parse_parameter_source_value(self.source)
        description = clean_optional_string(self.description) or ""
        allowed_values = tuple(
            normalize_typed_value(item, value_type, allow_none=False)
            for item in self.allowed_values or ()
        )
        min_value = normalize_optional_float(self.min_value, "min_value")
        max_value = normalize_optional_float(self.max_value, "max_value")
        metadata = normalize_metadata(self.metadata)

        if value is None and default_value is not None:
            value = default_value

        if required and value is None and default_value is None:
            raise DynamicDefaultsError(f"Required dynamic parameter {parameter_id!r} needs value or default_value.")

        if min_value is not None and max_value is not None and min_value > max_value:
            raise DynamicDefaultsError(f"Dynamic parameter {parameter_id!r} has min_value greater than max_value.")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if min_value is not None and float(value) < min_value:
                raise DynamicDefaultsError(f"Dynamic parameter {parameter_id!r} value is below min_value.")
            if max_value is not None and float(value) > max_value:
                raise DynamicDefaultsError(f"Dynamic parameter {parameter_id!r} value is above max_value.")

        if allowed_values and value is not None and value not in allowed_values:
            raise DynamicDefaultsError(f"Dynamic parameter {parameter_id!r} value is not in allowed_values.")

        return DynamicParameterDefaults(
            parameter_id=parameter_id,
            value_type=value_type,
            label=label,
            value=value,
            default_value=default_value,
            unit=unit,
            required=required,
            editable=editable,
            source=source,
            description=description,
            allowed_values=allowed_values,
            min_value=min_value,
            max_value=max_value,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "parameter_id": normalized.parameter_id,
            "label": normalized.label,
            "value_type": normalized.value_type,
            "value": normalized.value,
            "default_value": normalized.default_value,
            "unit": normalized.unit,
            "required": normalized.required,
            "editable": normalized.editable,
            "source": normalized.source,
            "description": normalized.description,
            "allowed_values": list(normalized.allowed_values),
            "min_value": normalized.min_value,
            "max_value": normalized.max_value,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class DynamicParametersDefaults:
    """Defaults für dynamic/parameters.json."""

    parameters: tuple[DynamicParameterDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicParametersDefaults":
        parameters = tuple(parameter.normalized() for parameter in self.parameters or ())
        assert_unique_values([parameter.parameter_id for parameter in parameters], "parameter_id")

        return DynamicParametersDefaults(
            parameters=tuple(sorted(parameters, key=lambda item: item.parameter_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/parameters.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_PARAMETERS_DOCUMENT_SCHEMA_VERSION,
            "parameter_ids": [parameter.parameter_id for parameter in normalized.parameters],
            "parameters": [parameter.to_dict() for parameter in normalized.parameters],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicContextRuleDefaults:
    """Eine deklarative Kontextregel."""

    rule_id: str
    rule_kind: str = DynamicRuleKind.CONDITION.value
    label: str | None = None
    expression: str | None = None
    field_path: str | None = None
    operator: str | None = None
    value: Any = None
    priority: int = 100
    enabled: bool = True
    required: bool = False
    description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicContextRuleDefaults":
        rule_id = normalize_dynamic_key(self.rule_id, "rule_id")
        rule_kind = parse_rule_kind_value(self.rule_kind)
        label = clean_optional_string(self.label) or humanize_key(rule_id)
        expression = normalize_optional_expression(self.expression, "expression")
        field_path = normalize_optional_field_path(self.field_path)
        operator = clean_optional_string(self.operator)
        value = normalize_json_value(self.value)
        priority = normalize_int(self.priority, "priority")
        enabled = bool(self.enabled)
        required = bool(self.required)
        description = clean_optional_string(self.description) or ""
        metadata = normalize_metadata(self.metadata)

        if not expression and not field_path and rule_kind != DynamicRuleKind.CUSTOM_DECLARATIVE.value:
            raise DynamicDefaultsError(
                f"Dynamic context rule {rule_id!r} requires expression or field_path."
            )

        if field_path and operator is None and expression is None:
            operator = DynamicConstraintOperator.EXISTS.value

        if operator is not None:
            parse_constraint_operator_value(operator)

        return DynamicContextRuleDefaults(
            rule_id=rule_id,
            rule_kind=rule_kind,
            label=label,
            expression=expression,
            field_path=field_path,
            operator=operator,
            value=value,
            priority=priority,
            enabled=enabled,
            required=required,
            description=description,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "rule_id": normalized.rule_id,
            "rule_kind": normalized.rule_kind,
            "label": normalized.label,
            "expression": normalized.expression,
            "field_path": normalized.field_path,
            "operator": normalized.operator,
            "value": normalized.value,
            "priority": normalized.priority,
            "enabled": normalized.enabled,
            "required": normalized.required,
            "description": normalized.description,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class DynamicContextRulesDefaults:
    """Defaults für dynamic/context_rules.json."""

    system_kind: str = DynamicSystemKind.GENERIC.value
    context_rules: tuple[DynamicContextRuleDefaults, ...] = field(default_factory=tuple)
    evaluation_mode: str = DynamicEvaluationMode.DECLARATIVE_ONLY.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicContextRulesDefaults":
        system_kind = parse_system_kind_value(self.system_kind)
        context_rules = tuple(rule.normalized() for rule in self.context_rules or ())
        evaluation_mode = parse_evaluation_mode_value(self.evaluation_mode)
        metadata = normalize_metadata(self.metadata)

        if system_kind != DynamicSystemKind.NONE.value and not context_rules:
            context_rules = (
                DynamicContextRuleDefaults(
                    rule_id=DEFAULT_CONTEXT_RULE_ID,
                    rule_kind=DynamicRuleKind.CONDITION.value,
                    label="Default Context Rule",
                    expression="true",
                    priority=100,
                    enabled=True,
                    required=False,
                    description="Default permissive context rule.",
                ).normalized(),
            )

        assert_unique_values([rule.rule_id for rule in context_rules], "rule_id")

        return DynamicContextRulesDefaults(
            system_kind=system_kind,
            context_rules=tuple(sorted(context_rules, key=lambda item: (item.priority, item.rule_id))),
            evaluation_mode=evaluation_mode,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/context_rules.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_CONTEXT_RULES_DOCUMENT_SCHEMA_VERSION,
            "system_kind": normalized.system_kind,
            "evaluation_mode": normalized.evaluation_mode,
            "rule_ids": [rule.rule_id for rule in normalized.context_rules],
            "context_rules": [rule.to_dict() for rule in normalized.context_rules],
            "declarative_only": True,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicBindingDefaults:
    """Ein deklaratives Binding."""

    binding_id: str
    binding_kind: str
    source_path: str
    target_path: str
    label: str | None = None
    required: bool = False
    bidirectional: bool = False
    transform_expression: str | None = None
    fallback_value: Any = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicBindingDefaults":
        binding_id = normalize_dynamic_key(self.binding_id, "binding_id")
        binding_kind = parse_binding_kind_value(self.binding_kind)
        source_path = normalize_field_path(self.source_path)
        target_path = normalize_field_path(self.target_path)
        label = clean_optional_string(self.label) or humanize_key(binding_id)
        required = bool(self.required)
        bidirectional = bool(self.bidirectional)
        transform_expression = normalize_optional_expression(self.transform_expression, "transform_expression")
        fallback_value = normalize_json_value(self.fallback_value)
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        return DynamicBindingDefaults(
            binding_id=binding_id,
            binding_kind=binding_kind,
            source_path=source_path,
            target_path=target_path,
            label=label,
            required=required,
            bidirectional=bidirectional,
            transform_expression=transform_expression,
            fallback_value=fallback_value,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "binding_id": normalized.binding_id,
            "binding_kind": normalized.binding_kind,
            "label": normalized.label,
            "source_path": normalized.source_path,
            "target_path": normalized.target_path,
            "required": normalized.required,
            "bidirectional": normalized.bidirectional,
            "transform_expression": normalized.transform_expression,
            "fallback_value": normalized.fallback_value,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class DynamicBindingsDefaults:
    """Defaults für dynamic/bindings.json."""

    bindings: tuple[DynamicBindingDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicBindingsDefaults":
        bindings = tuple(binding.normalized() for binding in self.bindings or ())

        if not bindings:
            bindings = (
                DynamicBindingDefaults(
                    binding_id=DEFAULT_BINDING_ID,
                    binding_kind=DynamicBindingKind.CONTEXT.value,
                    source_path="context.host",
                    target_path="dynamic.host",
                    label="Default Context Binding",
                    required=False,
                ).normalized(),
            )

        assert_unique_values([binding.binding_id for binding in bindings], "binding_id")

        return DynamicBindingsDefaults(
            bindings=tuple(sorted(bindings, key=lambda item: item.binding_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/bindings.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_BINDINGS_DOCUMENT_SCHEMA_VERSION,
            "binding_ids": [binding.binding_id for binding in normalized.bindings],
            "bindings": [binding.to_dict() for binding in normalized.bindings],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicGeneratorDefaults:
    """Defaults für dynamic/generator.json."""

    generator_id: str = DEFAULT_GENERATOR_ID
    generator_kind: str = DynamicGeneratorKind.DECLARATIVE_TEMPLATE.value
    label: str | None = None
    description: str = ""
    input_parameters: tuple[str, ...] = field(default_factory=tuple)
    output_fields: tuple[str, ...] = field(default_factory=tuple)
    template_ref: str | None = None
    rule_graph_ref: str | None = "dynamic/rule_graph.json"
    deterministic: bool = True
    declarative_only: bool = True
    requires_host_context: bool = True
    supports_preview_without_host: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicGeneratorDefaults":
        generator_id = normalize_dynamic_key(self.generator_id, "generator_id")
        generator_kind = parse_generator_kind_value(self.generator_kind)
        label = clean_optional_string(self.label) or humanize_key(generator_id)
        description = clean_optional_string(self.description) or ""
        input_parameters = normalize_dynamic_key_tuple(self.input_parameters, "input_parameters")
        output_fields = normalize_field_tuple(self.output_fields)
        template_ref = clean_optional_string(self.template_ref)
        rule_graph_ref = clean_optional_string(self.rule_graph_ref)
        deterministic = bool(self.deterministic)
        declarative_only = bool(self.declarative_only)
        requires_host_context = bool(self.requires_host_context)
        supports_preview_without_host = bool(self.supports_preview_without_host)
        metadata = normalize_metadata(self.metadata)

        if not declarative_only:
            raise DynamicDefaultsError("Dynamic generator must be declarative_only.")

        if generator_kind == DynamicGeneratorKind.NONE.value:
            rule_graph_ref = None
            template_ref = None
            requires_host_context = False

        return DynamicGeneratorDefaults(
            generator_id=generator_id,
            generator_kind=generator_kind,
            label=label,
            description=description,
            input_parameters=input_parameters,
            output_fields=output_fields,
            template_ref=template_ref,
            rule_graph_ref=rule_graph_ref,
            deterministic=deterministic,
            declarative_only=True,
            requires_host_context=requires_host_context,
            supports_preview_without_host=supports_preview_without_host,
            metadata=metadata,
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/generator.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_GENERATOR_DOCUMENT_SCHEMA_VERSION,
            "generator_id": normalized.generator_id,
            "generator_kind": normalized.generator_kind,
            "label": normalized.label,
            "description": normalized.description,
            "input_parameters": list(normalized.input_parameters),
            "output_fields": list(normalized.output_fields),
            "template_ref": normalized.template_ref,
            "rule_graph_ref": normalized.rule_graph_ref,
            "deterministic": normalized.deterministic,
            "declarative_only": normalized.declarative_only,
            "requires_host_context": normalized.requires_host_context,
            "supports_preview_without_host": normalized.supports_preview_without_host,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicConstraintDefaults:
    """Ein Constraint für Dynamic-Daten."""

    constraint_id: str
    field_path: str
    operator: str
    value: Any = None
    severity: str = DynamicConstraintSeverity.ERROR.value
    message: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicConstraintDefaults":
        constraint_id = normalize_dynamic_key(self.constraint_id, "constraint_id")
        field_path = normalize_field_path(self.field_path)
        operator = parse_constraint_operator_value(self.operator)
        value = normalize_json_value(self.value)
        severity = parse_constraint_severity_value(self.severity)
        message = clean_optional_string(self.message) or f"Dynamic constraint {constraint_id} failed."
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        if operator in {
            DynamicConstraintOperator.IN.value,
            DynamicConstraintOperator.NOT_IN.value,
            DynamicConstraintOperator.BETWEEN.value,
        } and not isinstance(value, list):
            raise DynamicDefaultsError(
                f"Dynamic constraint {constraint_id!r} operator {operator!r} requires list value."
            )

        return DynamicConstraintDefaults(
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
class DynamicConstraintsDefaults:
    """Defaults für dynamic/constraints.json."""

    constraints: tuple[DynamicConstraintDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicConstraintsDefaults":
        constraints = tuple(constraint.normalized() for constraint in self.constraints or ())
        assert_unique_values([constraint.constraint_id for constraint in constraints], "constraint_id")

        return DynamicConstraintsDefaults(
            constraints=tuple(sorted(constraints, key=lambda item: item.constraint_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/constraints.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_CONSTRAINTS_DOCUMENT_SCHEMA_VERSION,
            "constraint_ids": [constraint.constraint_id for constraint in normalized.constraints],
            "constraints": [constraint.to_dict() for constraint in normalized.constraints],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicRuleGraphNodeDefaults:
    """Ein Node im deklarativen Dynamic Rule Graph."""

    node_id: str
    node_kind: str
    label: str | None = None
    rule_ref: str | None = None
    parameter_ref: str | None = None
    binding_ref: str | None = None
    expression: str | None = None
    output_path: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicRuleGraphNodeDefaults":
        node_id = normalize_dynamic_key(self.node_id, "node_id")
        node_kind = parse_rule_graph_node_kind_value(self.node_kind)
        label = clean_optional_string(self.label) or humanize_key(node_id)
        rule_ref = normalize_optional_dynamic_key(self.rule_ref, "rule_ref")
        parameter_ref = normalize_optional_dynamic_key(self.parameter_ref, "parameter_ref")
        binding_ref = normalize_optional_dynamic_key(self.binding_ref, "binding_ref")
        expression = normalize_optional_expression(self.expression, "expression")
        output_path = normalize_optional_field_path(self.output_path)
        enabled = bool(self.enabled)
        metadata = normalize_metadata(self.metadata)

        if node_kind == DynamicRuleGraphNodeKind.CONDITION.value and not rule_ref and not expression:
            raise DynamicDefaultsError(f"Condition node {node_id!r} requires rule_ref or expression.")

        if node_kind == DynamicRuleGraphNodeKind.OUTPUT.value and not output_path:
            raise DynamicDefaultsError(f"Output node {node_id!r} requires output_path.")

        return DynamicRuleGraphNodeDefaults(
            node_id=node_id,
            node_kind=node_kind,
            label=label,
            rule_ref=rule_ref,
            parameter_ref=parameter_ref,
            binding_ref=binding_ref,
            expression=expression,
            output_path=output_path,
            enabled=enabled,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "node_id": normalized.node_id,
            "node_kind": normalized.node_kind,
            "label": normalized.label,
            "rule_ref": normalized.rule_ref,
            "parameter_ref": normalized.parameter_ref,
            "binding_ref": normalized.binding_ref,
            "expression": normalized.expression,
            "output_path": normalized.output_path,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class DynamicRuleGraphEdgeDefaults:
    """Eine gerichtete Kante im Dynamic Rule Graph."""

    edge_id: str
    from_node_id: str
    to_node_id: str
    condition_expression: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicRuleGraphEdgeDefaults":
        edge_id = normalize_dynamic_key(self.edge_id, "edge_id")
        from_node_id = normalize_dynamic_key(self.from_node_id, "from_node_id")
        to_node_id = normalize_dynamic_key(self.to_node_id, "to_node_id")
        condition_expression = normalize_optional_expression(self.condition_expression, "condition_expression")
        enabled = bool(self.enabled)

        if from_node_id == to_node_id:
            raise DynamicDefaultsError(f"Rule graph edge {edge_id!r} cannot point to the same node.")

        return DynamicRuleGraphEdgeDefaults(
            edge_id=edge_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            condition_expression=condition_expression,
            enabled=enabled,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "edge_id": normalized.edge_id,
            "from_node_id": normalized.from_node_id,
            "to_node_id": normalized.to_node_id,
            "condition_expression": normalized.condition_expression,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class DynamicRuleGraphDefaults:
    """Defaults für dynamic/rule_graph.json."""

    graph_id: str = "default_rule_graph"
    nodes: tuple[DynamicRuleGraphNodeDefaults, ...] = field(default_factory=tuple)
    edges: tuple[DynamicRuleGraphEdgeDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicRuleGraphDefaults":
        graph_id = normalize_dynamic_key(self.graph_id, "graph_id")
        nodes = tuple(node.normalized() for node in self.nodes or ())
        edges = tuple(edge.normalized() for edge in self.edges or ())

        if not nodes:
            nodes = (
                DynamicRuleGraphNodeDefaults(
                    node_id="start",
                    node_kind=DynamicRuleGraphNodeKind.START.value,
                    label="Start",
                ).normalized(),
                DynamicRuleGraphNodeDefaults(
                    node_id="output",
                    node_kind=DynamicRuleGraphNodeKind.OUTPUT.value,
                    label="Output",
                    output_path="dynamic.output",
                ).normalized(),
            )
            edges = (
                DynamicRuleGraphEdgeDefaults(
                    edge_id="start_to_output",
                    from_node_id="start",
                    to_node_id="output",
                ).normalized(),
            )

        node_ids = [node.node_id for node in nodes]
        assert_unique_values(node_ids, "node_id")
        assert_unique_values([edge.edge_id for edge in edges], "edge_id")

        node_id_set = set(node_ids)
        for edge in edges:
            if edge.from_node_id not in node_id_set:
                raise DynamicDefaultsError(f"Rule graph edge {edge.edge_id!r} references unknown from_node_id.")
            if edge.to_node_id not in node_id_set:
                raise DynamicDefaultsError(f"Rule graph edge {edge.edge_id!r} references unknown to_node_id.")

        return DynamicRuleGraphDefaults(
            graph_id=graph_id,
            nodes=tuple(sorted(nodes, key=lambda item: item.node_id)),
            edges=tuple(sorted(edges, key=lambda item: item.edge_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/rule_graph.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_RULE_GRAPH_DOCUMENT_SCHEMA_VERSION,
            "graph_id": normalized.graph_id,
            "node_ids": [node.node_id for node in normalized.nodes],
            "edge_ids": [edge.edge_id for edge in normalized.edges],
            "nodes": [node.to_dict() for node in normalized.nodes],
            "edges": [edge.to_dict() for edge in normalized.edges],
            "declarative_only": True,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicHostContractDefaults:
    """Defaults für dynamic/host_contract.json."""

    host_contract_id: str = DEFAULT_HOST_CONTRACT_ID
    allowed_host_kinds: tuple[str, ...] = field(default_factory=lambda: (DynamicHostKind.ANY.value,))
    required_host_fields: tuple[str, ...] = field(default_factory=tuple)
    optional_host_fields: tuple[str, ...] = field(default_factory=tuple)
    requires_surface_normal: bool = False
    requires_anchor: bool = False
    requires_socket: bool = False
    allow_hostless_preview: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "DynamicHostContractDefaults":
        host_contract_id = normalize_dynamic_key(self.host_contract_id, "host_contract_id")
        allowed_host_kinds = normalize_host_kind_tuple(self.allowed_host_kinds or (DynamicHostKind.ANY.value,))
        required_host_fields = normalize_field_tuple(self.required_host_fields)
        optional_host_fields = normalize_field_tuple(self.optional_host_fields)

        return DynamicHostContractDefaults(
            host_contract_id=host_contract_id,
            allowed_host_kinds=allowed_host_kinds,
            required_host_fields=required_host_fields,
            optional_host_fields=optional_host_fields,
            requires_surface_normal=bool(self.requires_surface_normal),
            requires_anchor=bool(self.requires_anchor),
            requires_socket=bool(self.requires_socket),
            allow_hostless_preview=bool(self.allow_hostless_preview),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt dynamic/host_contract.json."""
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_HOST_CONTRACT_DOCUMENT_SCHEMA_VERSION,
            "host_contract_id": normalized.host_contract_id,
            "allowed_host_kinds": list(normalized.allowed_host_kinds),
            "required_host_fields": list(normalized.required_host_fields),
            "optional_host_fields": list(normalized.optional_host_fields),
            "requires_surface_normal": normalized.requires_surface_normal,
            "requires_anchor": normalized.requires_anchor,
            "requires_socket": normalized.requires_socket,
            "allow_hostless_preview": normalized.allow_hostless_preview,
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class DynamicDefaults:
    """Vollständige Defaults für alle dynamic/*.json-Dokumente."""

    context_rules: DynamicContextRulesDefaults = field(default_factory=DynamicContextRulesDefaults)
    bindings: DynamicBindingsDefaults = field(default_factory=DynamicBindingsDefaults)
    generator: DynamicGeneratorDefaults = field(default_factory=DynamicGeneratorDefaults)
    parameters: DynamicParametersDefaults = field(default_factory=DynamicParametersDefaults)
    constraints: DynamicConstraintsDefaults = field(default_factory=DynamicConstraintsDefaults)
    rule_graph: DynamicRuleGraphDefaults = field(default_factory=DynamicRuleGraphDefaults)
    host_contract: DynamicHostContractDefaults = field(default_factory=DynamicHostContractDefaults)

    def normalized(self) -> "DynamicDefaults":
        context_rules = self.context_rules.normalized()
        bindings = self.bindings.normalized()
        parameters = self.parameters.normalized()
        constraints = self.constraints.normalized()
        rule_graph = self.rule_graph.normalized()
        host_contract = self.host_contract.normalized()

        generator = DynamicGeneratorDefaults(
            generator_id=self.generator.generator_id,
            generator_kind=self.generator.generator_kind,
            label=self.generator.label,
            description=self.generator.description,
            input_parameters=self.generator.input_parameters
            or tuple(parameter.parameter_id for parameter in parameters.parameters),
            output_fields=self.generator.output_fields,
            template_ref=self.generator.template_ref,
            rule_graph_ref=self.generator.rule_graph_ref,
            deterministic=self.generator.deterministic,
            declarative_only=self.generator.declarative_only,
            requires_host_context=self.generator.requires_host_context,
            supports_preview_without_host=self.generator.supports_preview_without_host,
            metadata=self.generator.metadata,
        ).normalized()

        validate_dynamic_references(
            context_rules=context_rules,
            bindings=bindings,
            generator=generator,
            parameters=parameters,
            constraints=constraints,
            rule_graph=rule_graph,
        )

        return DynamicDefaults(
            context_rules=context_rules,
            bindings=bindings,
            generator=generator,
            parameters=parameters,
            constraints=constraints,
            rule_graph=rule_graph,
            host_contract=host_contract,
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Dynamic-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "dynamic/context_rules.json": normalized.context_rules.to_document(),
            "dynamic/bindings.json": normalized.bindings.to_document(),
            "dynamic/generator.json": normalized.generator.to_document(),
        }

        if include_optional:
            documents["dynamic/parameters.json"] = normalized.parameters.to_document()
            documents["dynamic/constraints.json"] = normalized.constraints.to_document()
            documents["dynamic/rule_graph.json"] = normalized.rule_graph.to_document()
            documents["dynamic/host_contract.json"] = normalized.host_contract.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": DYNAMIC_DEFAULTS_SCHEMA_VERSION,
            "context_rules": normalized.context_rules.to_dict(),
            "bindings": normalized.bindings.to_dict(),
            "generator": normalized.generator.to_dict(),
            "parameters": normalized.parameters.to_dict(),
            "constraints": normalized.constraints.to_dict(),
            "rule_graph": normalized.rule_graph.to_dict(),
            "host_contract": normalized.host_contract.to_dict(),
        }


def build_dynamic_defaults(
    *,
    object_kind: str = "adaptive_system",
    system_kind: str | None = None,
    context_rules: Iterable[DynamicContextRuleDefaults | Mapping[str, Any]] = (),
    bindings: Iterable[DynamicBindingDefaults | Mapping[str, Any]] = (),
    parameters: Iterable[DynamicParameterDefaults | Mapping[str, Any]] = (),
    constraints: Iterable[DynamicConstraintDefaults | Mapping[str, Any]] = (),
    generator_kind: str = DynamicGeneratorKind.DECLARATIVE_TEMPLATE.value,
    allowed_host_kinds: Iterable[Any] = (DynamicHostKind.ANY.value,),
    metadata: Mapping[str, Any] | None = None,
) -> DynamicDefaults:
    """Baut DynamicDefaults aus expliziten Werten."""
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
        resolved_system_kind = system_kind or infer_system_kind_from_object_kind(object_kind_value)
        metadata_payload = {
            "source": "build_dynamic_defaults",
            "object_kind": object_kind_value,
            **dict(metadata or {}),
        }

        parsed_context_rules = tuple(
            rule if isinstance(rule, DynamicContextRuleDefaults) else context_rule_from_mapping(rule)
            for rule in context_rules or ()
        )
        parsed_bindings = tuple(
            binding if isinstance(binding, DynamicBindingDefaults) else binding_from_mapping(binding)
            for binding in bindings or ()
        )
        parsed_parameters = tuple(
            parameter if isinstance(parameter, DynamicParameterDefaults) else parameter_from_mapping(parameter)
            for parameter in parameters or ()
        )
        parsed_constraints = tuple(
            constraint if isinstance(constraint, DynamicConstraintDefaults) else constraint_from_mapping(constraint)
            for constraint in constraints or ()
        )

        return DynamicDefaults(
            context_rules=DynamicContextRulesDefaults(
                system_kind=resolved_system_kind,
                context_rules=parsed_context_rules,
                metadata=metadata_payload,
            ),
            bindings=DynamicBindingsDefaults(
                bindings=parsed_bindings,
                metadata=metadata_payload,
            ),
            generator=DynamicGeneratorDefaults(
                generator_kind=generator_kind,
                metadata=metadata_payload,
            ),
            parameters=DynamicParametersDefaults(
                parameters=parsed_parameters,
                metadata=metadata_payload,
            ),
            constraints=DynamicConstraintsDefaults(
                constraints=parsed_constraints,
                metadata=metadata_payload,
            ),
            rule_graph=DynamicRuleGraphDefaults(metadata=metadata_payload),
            host_contract=DynamicHostContractDefaults(
                allowed_host_kinds=tuple(allowed_host_kinds or (DynamicHostKind.ANY.value,)),
                requires_surface_normal=resolved_system_kind
                in {
                    DynamicSystemKind.SURFACE_ADAPTIVE.value,
                    DynamicSystemKind.BRIDGE_CAP.value,
                    DynamicSystemKind.RAILING.value,
                    DynamicSystemKind.EDGE_BEAM.value,
                },
                metadata=metadata_payload,
            ),
        ).normalized()
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Could not build dynamic defaults: {exc}") from exc


def dynamic_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> DynamicDefaults:
    """Baut DynamicDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        dynamic = normalized_request.dynamic.normalized()

        return build_dynamic_defaults(
            object_kind=normalized_request.object_kind,
            system_kind=infer_system_kind_from_request(normalized_request),
            context_rules=dynamic.context_rules,
            bindings=dynamic.bindings,
            parameters=dynamic.parameters,
            generator_kind=dynamic.generator.get("generator_kind", DynamicGeneratorKind.DECLARATIVE_TEMPLATE.value)
            if isinstance(dynamic.generator, Mapping)
            else DynamicGeneratorKind.DECLARATIVE_TEMPLATE.value,
            metadata={
                "source": "create_request",
                "object_kind": normalized_request.object_kind,
                **dict(metadata or {}),
            },
        )
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Could not build dynamic defaults from CreateRequest: {exc}") from exc


def dynamic_defaults_from_context(
    context: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> DynamicDefaults:
    """Baut DynamicDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context

        return build_dynamic_defaults(
            object_kind=normalized_context.object_kind,
            system_kind=infer_system_kind_from_object_kind(normalized_context.object_kind),
            metadata={
                "source": "package_context",
                "object_kind": normalized_context.object_kind,
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Could not build dynamic defaults from PackageContext: {exc}") from exc


def dynamic_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> DynamicDefaults:
    """Baut DynamicDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return dynamic_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Could not build dynamic defaults from CreationPlan: {exc}") from exc


def dynamic_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle dynamic/*.json-Dokumente aus CreateRequest."""
    return dynamic_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def dynamic_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle dynamic/*.json-Dokumente aus PackageContext."""
    return dynamic_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def dynamic_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle dynamic/*.json-Dokumente aus CreationPlan."""
    return dynamic_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def context_rule_from_mapping(data: Mapping[str, Any]) -> DynamicContextRuleDefaults:
    """Baut DynamicContextRuleDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise DynamicDefaultsError("Context rule data must be a mapping.")

    return DynamicContextRuleDefaults(
        rule_id=data.get("rule_id") or data.get("id"),
        rule_kind=data.get("rule_kind", DynamicRuleKind.CONDITION.value),
        label=data.get("label") or data.get("name"),
        expression=data.get("expression"),
        field_path=data.get("field_path") or data.get("field"),
        operator=data.get("operator"),
        value=data.get("value"),
        priority=data.get("priority", 100),
        enabled=bool(data.get("enabled", True)),
        required=bool(data.get("required", False)),
        description=data.get("description", ""),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def binding_from_mapping(data: Mapping[str, Any]) -> DynamicBindingDefaults:
    """Baut DynamicBindingDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise DynamicDefaultsError("Binding data must be a mapping.")

    return DynamicBindingDefaults(
        binding_id=data.get("binding_id") or data.get("id"),
        binding_kind=data.get("binding_kind", DynamicBindingKind.CONTEXT.value),
        source_path=data.get("source_path") or data.get("source"),
        target_path=data.get("target_path") or data.get("target"),
        label=data.get("label") or data.get("name"),
        required=bool(data.get("required", False)),
        bidirectional=bool(data.get("bidirectional", False)),
        transform_expression=data.get("transform_expression"),
        fallback_value=data.get("fallback_value"),
        enabled=bool(data.get("enabled", True)),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def parameter_from_mapping(data: Mapping[str, Any]) -> DynamicParameterDefaults:
    """Baut DynamicParameterDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise DynamicDefaultsError("Parameter data must be a mapping.")

    return DynamicParameterDefaults(
        parameter_id=data.get("parameter_id") or data.get("id"),
        value_type=data.get("value_type") or data.get("type") or DynamicValueType.STRING.value,
        label=data.get("label") or data.get("name"),
        value=data.get("value"),
        default_value=data.get("default_value"),
        unit=data.get("unit"),
        required=bool(data.get("required", False)),
        editable=bool(data.get("editable", True)),
        source=data.get("source", DynamicParameterSource.DEFAULT.value),
        description=data.get("description", ""),
        allowed_values=tuple(data.get("allowed_values", ()) or ()),
        min_value=data.get("min_value"),
        max_value=data.get("max_value"),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def constraint_from_mapping(data: Mapping[str, Any]) -> DynamicConstraintDefaults:
    """Baut DynamicConstraintDefaults aus Mapping."""
    if not isinstance(data, Mapping):
        raise DynamicDefaultsError("Constraint data must be a mapping.")

    return DynamicConstraintDefaults(
        constraint_id=data.get("constraint_id") or data.get("id"),
        field_path=data.get("field_path") or data.get("field"),
        operator=data.get("operator"),
        value=data.get("value"),
        severity=data.get("severity", DynamicConstraintSeverity.ERROR.value),
        message=data.get("message"),
        enabled=bool(data.get("enabled", True)),
        metadata=dict(data.get("metadata", {}) or {}),
    ).normalized()


def validate_dynamic_references(
    *,
    context_rules: DynamicContextRulesDefaults,
    bindings: DynamicBindingsDefaults,
    generator: DynamicGeneratorDefaults,
    parameters: DynamicParametersDefaults,
    constraints: DynamicConstraintsDefaults,
    rule_graph: DynamicRuleGraphDefaults,
) -> None:
    """Prüft einfache Referenzen zwischen Dynamic-Dokumenten."""
    parameter_ids = {parameter.parameter_id for parameter in parameters.parameters}
    rule_ids = {rule.rule_id for rule in context_rules.context_rules}
    binding_ids = {binding.binding_id for binding in bindings.bindings}

    for parameter_id in generator.input_parameters:
        if parameter_id not in parameter_ids:
            raise DynamicDefaultsError(
                f"Generator references unknown input parameter {parameter_id!r}."
            )

    for node in rule_graph.nodes:
        if node.rule_ref and node.rule_ref not in rule_ids:
            raise DynamicDefaultsError(f"Rule graph node {node.node_id!r} references unknown rule {node.rule_ref!r}.")
        if node.parameter_ref and node.parameter_ref not in parameter_ids:
            raise DynamicDefaultsError(f"Rule graph node {node.node_id!r} references unknown parameter {node.parameter_ref!r}.")
        if node.binding_ref and node.binding_ref not in binding_ids:
            raise DynamicDefaultsError(f"Rule graph node {node.node_id!r} references unknown binding {node.binding_ref!r}.")

    for constraint in constraints.constraints:
        if constraint.field_path.startswith("dynamic.parameters."):
            parameter_ref = constraint.field_path.split(".", 2)[-1]
            if parameter_ref and parameter_ref not in parameter_ids:
                # Nur Warnlogik wäre besser, aber Defaults sollen streng sein.
                continue


def infer_system_kind_from_request(request: Any) -> str:
    """Leitet DynamicSystemKind aus Request-Daten ab."""
    try:
        normalized_request = normalize_create_request(request)
        classification = normalized_request.classification.normalized()

        category = classification.category
        subcategory = classification.subcategory

        if "gelaender" in subcategory or "railing" in subcategory:
            return DynamicSystemKind.RAILING.value
        if "bruecke" in category or "bridge" in category:
            return DynamicSystemKind.BRIDGE_CAP.value
        if "leitung" in category or "pipe" in subcategory:
            return DynamicSystemKind.PIPE_SYSTEM.value
        if "route" in subcategory or "trasse" in subcategory:
            return DynamicSystemKind.ROUTING_SYSTEM.value

        return infer_system_kind_from_object_kind(normalized_request.object_kind)
    except Exception:
        return DynamicSystemKind.GENERIC.value


def infer_system_kind_from_object_kind(object_kind: Any) -> str:
    """Leitet DynamicSystemKind aus object_kind ab."""
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
    except Exception:
        return DynamicSystemKind.GENERIC.value

    if object_kind_value == "adaptive_system":
        return DynamicSystemKind.HOST_ADAPTIVE.value

    return DynamicSystemKind.NONE.value


def validate_context_rules_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob dynamic/context_rules.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("dynamic/context_rules.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "system_kind",
            "evaluation_mode",
            "context_rules",
            "declarative_only",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing dynamic context rules field {field_name!r}.")

        rules = document.get("context_rules", ())
        if not isinstance(rules, list):
            messages.append("context_rules must be a list.")
        else:
            for item in rules:
                try:
                    context_rule_from_mapping(item)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate dynamic context rules document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_bindings_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob dynamic/bindings.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("dynamic/bindings.json must be a mapping.",)

        bindings = document.get("bindings", ())
        if not isinstance(bindings, list):
            messages.append("bindings must be a list.")
        else:
            for item in bindings:
                try:
                    binding_from_mapping(item)
                except Exception as exc:
                    messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate dynamic bindings document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_generator_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob dynamic/generator.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("dynamic/generator.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "generator_id",
            "generator_kind",
            "declarative_only",
            "deterministic",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing dynamic generator field {field_name!r}.")

        if document.get("declarative_only") is not True:
            messages.append("dynamic/generator.json must set declarative_only=true.")

        try:
            DynamicGeneratorDefaults(
                generator_id=document.get("generator_id", DEFAULT_GENERATOR_ID),
                generator_kind=document.get("generator_kind", DynamicGeneratorKind.DECLARATIVE_TEMPLATE.value),
                label=document.get("label"),
                description=document.get("description", ""),
                input_parameters=tuple(document.get("input_parameters", ()) or ()),
                output_fields=tuple(document.get("output_fields", ()) or ()),
                template_ref=document.get("template_ref"),
                rule_graph_ref=document.get("rule_graph_ref"),
                deterministic=bool(document.get("deterministic", True)),
                declarative_only=bool(document.get("declarative_only", True)),
                requires_host_context=bool(document.get("requires_host_context", True)),
                supports_preview_without_host=bool(document.get("supports_preview_without_host", True)),
                metadata=dict(document.get("metadata", {}) or {}),
            ).normalized()
        except Exception as exc:
            messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate dynamic generator document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_context_rules_document(document: Mapping[str, Any]) -> None:
    """Wirft DynamicDefaultsError, wenn dynamic/context_rules.json ungültig ist."""
    valid, messages = validate_context_rules_document(document)
    if not valid:
        raise DynamicDefaultsError(" ".join(messages) if messages else "Invalid dynamic context rules document.")


def assert_valid_bindings_document(document: Mapping[str, Any]) -> None:
    """Wirft DynamicDefaultsError, wenn dynamic/bindings.json ungültig ist."""
    valid, messages = validate_bindings_document(document)
    if not valid:
        raise DynamicDefaultsError(" ".join(messages) if messages else "Invalid dynamic bindings document.")


def assert_valid_generator_document(document: Mapping[str, Any]) -> None:
    """Wirft DynamicDefaultsError, wenn dynamic/generator.json ungültig ist."""
    valid, messages = validate_generator_document(document)
    if not valid:
        raise DynamicDefaultsError(" ".join(messages) if messages else "Invalid dynamic generator document.")


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

        raise DynamicDefaultsError("CreateRequest value is required.")
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_dynamic_key(value: Any, field_name: str) -> str:
    """Normalisiert technische Dynamic-Keys."""
    raw = clean_required_string(value, field_name)
    key = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_DYNAMIC_KEY_RE.match(key):
        raise DynamicDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return key


def normalize_optional_dynamic_key(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Dynamic-Keys."""
    if value is None:
        return None

    return normalize_dynamic_key(value, field_name)


def normalize_dynamic_key_tuple(values: Iterable[Any], field_name: str) -> tuple[str, ...]:
    """Normalisiert mehrere Dynamic-Keys."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        key = normalize_dynamic_key(value, field_name)
        if key in seen:
            continue
        result.append(key)
        seen.add(key)

    return tuple(result)


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
        raise DynamicDefaultsError(f"Unsafe field_path {value!r}.")

    return field_path


def normalize_optional_field_path(value: Any) -> str | None:
    """Normalisiert optionalen Field-Path."""
    if value is None:
        return None

    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    return normalize_field_path(cleaned)


def normalize_field_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert mehrere Field-Paths."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        field_path = normalize_field_path(value)
        if field_path in seen:
            continue
        result.append(field_path)
        seen.add(field_path)

    return tuple(result)


def normalize_optional_unit_value(value: Any) -> str | None:
    """Normalisiert optionale Unit-Werte."""
    if value is None:
        return None

    try:
        from ..domain.units import ensure_unit_value

        return ensure_unit_value(value)
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid unit {value!r}: {exc}") from exc


def normalize_expression(value: Any, field_name: str) -> str:
    """Normalisiert deklarative Expression und blockiert offensichtlich ausführbare Muster."""
    expression = clean_required_string(value, field_name)

    lowered = expression.lower()
    for token in FORBIDDEN_DYNAMIC_EXPRESSION_TOKENS:
        if token in lowered:
            raise DynamicDefaultsError(
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
    """Normalisiert Werte anhand DynamicValueType."""
    if value is None:
        if allow_none:
            return None
        raise DynamicDefaultsError("Value must not be None.")

    type_value = parse_value_type_value(value_type)

    try:
        if type_value == DynamicValueType.STRING.value:
            return str(value).strip()

        if type_value == DynamicValueType.INTEGER.value:
            if isinstance(value, bool):
                raise DynamicDefaultsError("Integer value must not be boolean.")
            return int(value)

        if type_value == DynamicValueType.NUMBER.value:
            if isinstance(value, bool):
                raise DynamicDefaultsError("Number value must not be boolean.")
            number = float(value)
            return int(number) if number.is_integer() else number

        if type_value == DynamicValueType.BOOLEAN.value:
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"true", "1", "yes", "on"}:
                return True
            if raw in {"false", "0", "no", "off"}:
                return False
            raise DynamicDefaultsError(f"Invalid boolean value {value!r}.")

        if type_value in {DynamicValueType.ENUM.value, DynamicValueType.FIELD_REF.value}:
            return str(value).strip()

        if type_value == DynamicValueType.EXPRESSION.value:
            return normalize_expression(value, "value")

        if type_value == DynamicValueType.UNIT_VALUE.value:
            if not isinstance(value, Mapping):
                raise DynamicDefaultsError("unit_value must be an object with value and unit.")
            return {
                "value": normalize_json_value(value.get("value")),
                "unit": normalize_optional_unit_value(value.get("unit")) or "none",
            }

        if type_value == DynamicValueType.VECTOR3.value:
            if not isinstance(value, Mapping):
                raise DynamicDefaultsError("vector3 value must be an object.")
            return normalize_vector3(value, "value")

        if type_value == DynamicValueType.OBJECT.value:
            if not isinstance(value, Mapping):
                raise DynamicDefaultsError("object value must be a mapping.")
            return normalize_json_value(value)

        if type_value == DynamicValueType.ARRAY.value:
            if not isinstance(value, (list, tuple)):
                raise DynamicDefaultsError("array value must be a list.")
            return [normalize_json_value(item) for item in value]

        return normalize_json_value(value)
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid value {value!r} for type {value_type!r}.") from exc


def normalize_vector3(value: Mapping[str, Any], field_name: str) -> dict[str, float]:
    """Normalisiert Vector3-Mapping."""
    if not isinstance(value, Mapping):
        raise DynamicDefaultsError(f"{field_name} must be an object.")

    return {
        "x": normalize_float(value.get("x", 0.0), f"{field_name}.x"),
        "y": normalize_float(value.get("y", 0.0), f"{field_name}.y"),
        "z": normalize_float(value.get("z", 0.0), f"{field_name}.z"),
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


def normalize_host_kind_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Host-Kinds."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        host_kind = parse_host_kind_value(value)
        if host_kind in seen:
            continue
        result.append(host_kind)
        seen.add(host_kind)

    return tuple(result)


@lru_cache(maxsize=128)
def parse_system_kind_value(value: Any) -> str:
    """Parst DynamicSystemKind."""
    try:
        if isinstance(value, DynamicSystemKind):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "none": DynamicSystemKind.NONE.value,
            "generic": DynamicSystemKind.GENERIC.value,
            "host": DynamicSystemKind.HOST_ADAPTIVE.value,
            "host_adaptive": DynamicSystemKind.HOST_ADAPTIVE.value,
            "surface": DynamicSystemKind.SURFACE_ADAPTIVE.value,
            "surface_adaptive": DynamicSystemKind.SURFACE_ADAPTIVE.value,
            "routing": DynamicSystemKind.ROUTING_SYSTEM.value,
            "routing_system": DynamicSystemKind.ROUTING_SYSTEM.value,
            "parametric": DynamicSystemKind.PARAMETRIC_COMPONENT.value,
            "parametric_component": DynamicSystemKind.PARAMETRIC_COMPONENT.value,
            "bridge_cap": DynamicSystemKind.BRIDGE_CAP.value,
            "railing": DynamicSystemKind.RAILING.value,
            "edge_beam": DynamicSystemKind.EDGE_BEAM.value,
            "pipe": DynamicSystemKind.PIPE_SYSTEM.value,
            "pipe_system": DynamicSystemKind.PIPE_SYSTEM.value,
            "custom": DynamicSystemKind.CUSTOM.value,
        }

        if raw in aliases:
            return aliases[raw]

        return DynamicSystemKind(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic system kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_rule_kind_value(value: Any) -> str:
    """Parst DynamicRuleKind."""
    try:
        if isinstance(value, DynamicRuleKind):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicRuleKind(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic rule kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_binding_kind_value(value: Any) -> str:
    """Parst DynamicBindingKind."""
    try:
        if isinstance(value, DynamicBindingKind):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicBindingKind(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic binding kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_generator_kind_value(value: Any) -> str:
    """Parst DynamicGeneratorKind."""
    try:
        if isinstance(value, DynamicGeneratorKind):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicGeneratorKind(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic generator kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_value_type_value(value: Any) -> str:
    """Parst DynamicValueType."""
    try:
        if isinstance(value, DynamicValueType):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicValueType(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic value type {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_parameter_source_value(value: Any) -> str:
    """Parst DynamicParameterSource."""
    try:
        if isinstance(value, DynamicParameterSource):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicParameterSource(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic parameter source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_constraint_operator_value(value: Any) -> str:
    """Parst DynamicConstraintOperator."""
    try:
        if isinstance(value, DynamicConstraintOperator):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicConstraintOperator(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic constraint operator {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_constraint_severity_value(value: Any) -> str:
    """Parst DynamicConstraintSeverity."""
    try:
        if isinstance(value, DynamicConstraintSeverity):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicConstraintSeverity(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic constraint severity {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_rule_graph_node_kind_value(value: Any) -> str:
    """Parst DynamicRuleGraphNodeKind."""
    try:
        if isinstance(value, DynamicRuleGraphNodeKind):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicRuleGraphNodeKind(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic rule graph node kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_host_kind_value(value: Any) -> str:
    """Parst DynamicHostKind."""
    try:
        if isinstance(value, DynamicHostKind):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicHostKind(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic host kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_evaluation_mode_value(value: Any) -> str:
    """Parst DynamicEvaluationMode."""
    try:
        if isinstance(value, DynamicEvaluationMode):
            return value.value

        raw = normalize_enum_key(value)
        return DynamicEvaluationMode(raw).value
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid dynamic evaluation mode {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise DynamicDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise DynamicDefaultsError(f"{field_name} must be a number.")
        return float(value)
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"{field_name} must be a number.") from exc


def normalize_optional_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionalen Float."""
    if value is None:
        return None
    return normalize_float(value, field_name)


def normalize_int(value: Any, field_name: str) -> int:
    """Normalisiert Integer."""
    try:
        if isinstance(value, bool):
            raise DynamicDefaultsError(f"{field_name} must be an integer.")
        return int(value)
    except Exception as exc:
        raise DynamicDefaultsError(f"{field_name} must be an integer.") from exc


def assert_unique_values(values: Iterable[str], field_name: str) -> None:
    """Prüft eindeutige Werte."""
    seen: set[str] = set()

    for value in values or ():
        if value in seen:
            raise DynamicDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def humanize_key(value: Any) -> str:
    """Erzeugt einfaches Label aus technischem Key."""
    return str(value).replace("_", " ").replace(".", " ").title()


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise DynamicDefaultsError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise DynamicDefaultsError(f"{field_name} is required.")

        return cleaned
    except DynamicDefaultsError:
        raise
    except Exception as exc:
        raise DynamicDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_dynamic_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_system_kind_value.cache_clear()
    parse_rule_kind_value.cache_clear()
    parse_binding_kind_value.cache_clear()
    parse_generator_kind_value.cache_clear()
    parse_value_type_value.cache_clear()
    parse_parameter_source_value.cache_clear()
    parse_constraint_operator_value.cache_clear()
    parse_constraint_severity_value.cache_clear()
    parse_rule_graph_node_kind_value.cache_clear()
    parse_host_kind_value.cache_clear()
    parse_evaluation_mode_value.cache_clear()


__all__ = [
    "DEFAULT_BINDING_ID",
    "DEFAULT_CONSTRAINT_ID",
    "DEFAULT_CONTEXT_RULE_ID",
    "DEFAULT_DYNAMIC_SYSTEM_ID",
    "DEFAULT_GENERATOR_ID",
    "DEFAULT_HOST_CONTRACT_ID",
    "DEFAULT_PARAMETER_ID",
    "DEFAULT_RULE_NODE_ID",
    "DYNAMIC_BINDINGS_DOCUMENT_SCHEMA_VERSION",
    "DYNAMIC_CONSTRAINTS_DOCUMENT_SCHEMA_VERSION",
    "DYNAMIC_CONTEXT_RULES_DOCUMENT_SCHEMA_VERSION",
    "DYNAMIC_DEFAULTS_SCHEMA_VERSION",
    "DYNAMIC_GENERATOR_DOCUMENT_SCHEMA_VERSION",
    "DYNAMIC_HOST_CONTRACT_DOCUMENT_SCHEMA_VERSION",
    "DYNAMIC_PARAMETERS_DOCUMENT_SCHEMA_VERSION",
    "DYNAMIC_RULE_GRAPH_DOCUMENT_SCHEMA_VERSION",
    "FORBIDDEN_DYNAMIC_EXPRESSION_TOKENS",
    "SAFE_DYNAMIC_KEY_RE",
    "SAFE_FIELD_PATH_RE",
    "DynamicBindingDefaults",
    "DynamicBindingKind",
    "DynamicBindingsDefaults",
    "DynamicConstraintDefaults",
    "DynamicConstraintOperator",
    "DynamicConstraintSeverity",
    "DynamicConstraintsDefaults",
    "DynamicContextRuleDefaults",
    "DynamicContextRulesDefaults",
    "DynamicDefaults",
    "DynamicDefaultsError",
    "DynamicEvaluationMode",
    "DynamicGeneratorDefaults",
    "DynamicGeneratorKind",
    "DynamicHostContractDefaults",
    "DynamicHostKind",
    "DynamicParameterDefaults",
    "DynamicParameterSource",
    "DynamicParametersDefaults",
    "DynamicRuleGraphDefaults",
    "DynamicRuleGraphEdgeDefaults",
    "DynamicRuleGraphNodeDefaults",
    "DynamicRuleGraphNodeKind",
    "DynamicRuleKind",
    "DynamicSystemKind",
    "DynamicValueType",
    "assert_unique_values",
    "assert_valid_bindings_document",
    "assert_valid_context_rules_document",
    "assert_valid_generator_document",
    "binding_from_mapping",
    "build_dynamic_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_dynamic_defaults_caches",
    "constraint_from_mapping",
    "context_rule_from_mapping",
    "dynamic_defaults_from_context",
    "dynamic_defaults_from_create_request",
    "dynamic_defaults_from_creation_plan",
    "dynamic_documents_from_context",
    "dynamic_documents_from_create_request",
    "dynamic_documents_from_creation_plan",
    "humanize_key",
    "infer_system_kind_from_object_kind",
    "infer_system_kind_from_request",
    "normalize_create_request",
    "normalize_dynamic_key",
    "normalize_dynamic_key_tuple",
    "normalize_enum_key",
    "normalize_expression",
    "normalize_field_path",
    "normalize_field_tuple",
    "normalize_float",
    "normalize_host_kind_tuple",
    "normalize_int",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_object_kind_value",
    "normalize_optional_dynamic_key",
    "normalize_optional_expression",
    "normalize_optional_field_path",
    "normalize_optional_float",
    "normalize_optional_unit_value",
    "normalize_typed_value",
    "normalize_vector3",
    "parameter_from_mapping",
    "parse_binding_kind_value",
    "parse_constraint_operator_value",
    "parse_constraint_severity_value",
    "parse_evaluation_mode_value",
    "parse_generator_kind_value",
    "parse_host_kind_value",
    "parse_parameter_source_value",
    "parse_rule_graph_node_kind_value",
    "parse_rule_kind_value",
    "parse_system_kind_value",
    "parse_value_type_value",
    "validate_bindings_document",
    "validate_context_rules_document",
    "validate_dynamic_references",
    "validate_generator_document",
]