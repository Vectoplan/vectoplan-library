# services/vectoplan-library/src/vplib/defaults/analysis_defaults.py
"""
Analysis defaults for the VPLIB package engine.

Diese Datei erzeugt robuste Default-Daten für:

    analysis/statics/profile.json
    analysis/routing/profile.json
    analysis/reinforcement/profile.json
    optional: analysis/checks.json
    optional: analysis/assumptions.json

Analysis-Daten bleiben deklarativ. Sie beschreiben nur Profile, Parameter,
Annahmen, Lastfälle, Routing-Regeln oder Bewehrungs-/Nachweisprofile. Sie
führen keine Berechnungen aus und enthalten keinen ausführbaren Code.

Diese Datei schreibt keine Dateien. Sie erzeugt nur JSON-kompatible Payloads.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


ANALYSIS_DEFAULTS_SCHEMA_VERSION: Final[str] = "vplib.analysis_defaults.v1"
ANALYSIS_STATICS_PROFILE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.analysis.statics.profile.v1"
ANALYSIS_ROUTING_PROFILE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.analysis.routing.profile.v1"
ANALYSIS_REINFORCEMENT_PROFILE_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.analysis.reinforcement.profile.v1"
ANALYSIS_CHECKS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.analysis.checks.v1"
ANALYSIS_ASSUMPTIONS_DOCUMENT_SCHEMA_VERSION: Final[str] = "vplib.analysis.assumptions.v1"

DEFAULT_ANALYSIS_PROFILE_ID: Final[str] = "default_analysis"
DEFAULT_STATICS_PROFILE_ID: Final[str] = "default_statics"
DEFAULT_ROUTING_PROFILE_ID: Final[str] = "default_routing"
DEFAULT_REINFORCEMENT_PROFILE_ID: Final[str] = "default_reinforcement"
DEFAULT_ASSUMPTION_SET_ID: Final[str] = "default_assumptions"

SAFE_ANALYSIS_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$"
)

SAFE_FIELD_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*[a-zA-Z0-9_]$|^[a-zA-Z0-9_]$"
)

FORBIDDEN_ANALYSIS_EXPRESSION_TOKENS: Final[tuple[str, ...]] = (
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


class AnalysisDefaultsError(ValueError):
    """Wird ausgelöst, wenn Analysis-Defaults ungültig erzeugt werden."""


class AnalysisProfileStatus(str, Enum):
    """Status eines Analyseprofils."""

    DISABLED = "disabled"
    DRAFT = "draft"
    ACTIVE = "active"
    RECOMMENDED = "recommended"
    DEPRECATED = "deprecated"

    @property
    def key(self) -> str:
        return str(self.value)


class AnalysisValidationPolicy(str, Enum):
    """Validierungspolitik für Analyseprofile."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


class AnalysisValueType(str, Enum):
    """Datentyp eines Analyseparameters."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    UNIT_VALUE = "unit_value"
    FIELD_REF = "field_ref"
    EXPRESSION = "expression"
    OBJECT = "object"
    ARRAY = "array"

    @property
    def key(self) -> str:
        return str(self.value)


class AnalysisParameterSource(str, Enum):
    """Quelle eines Analyseparameters."""

    DEFAULT = "default"
    USER = "user"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    VARIANT = "variant"
    MANUFACTURER = "manufacturer"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class AnalysisCheckSeverity(str, Enum):
    """Schweregrad eines Analysechecks."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class AnalysisCheckScope(str, Enum):
    """Scope eines Analysechecks."""

    STATICS = "statics"
    ROUTING = "routing"
    REINFORCEMENT = "reinforcement"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    VARIANT = "variant"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


class StaticsSystemKind(str, Enum):
    """Vereinfachte Tragwerks-/Statiksystem-Art."""

    NONE = "none"
    GENERIC = "generic"
    WALL = "wall"
    SLAB = "slab"
    BEAM = "beam"
    COLUMN = "column"
    FOUNDATION = "foundation"
    FRAME = "frame"
    BRIDGE_COMPONENT = "bridge_component"
    RETAINING_STRUCTURE = "retaining_structure"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class LoadCaseKind(str, Enum):
    """Lastfall-Art."""

    SELF_WEIGHT = "self_weight"
    DEAD_LOAD = "dead_load"
    LIVE_LOAD = "live_load"
    WIND = "wind"
    SNOW = "snow"
    EARTH_PRESSURE = "earth_pressure"
    WATER_PRESSURE = "water_pressure"
    TEMPERATURE = "temperature"
    SEISMIC = "seismic"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class RoutingSystemKind(str, Enum):
    """Routing-System-Art."""

    NONE = "none"
    GENERIC = "generic"
    PIPE = "pipe"
    DUCT = "duct"
    CABLE = "cable"
    CONDUIT = "conduit"
    DRAINAGE = "drainage"
    ROAD = "road"
    RAIL = "rail"
    PATH = "path"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class RoutingConnectorKind(str, Enum):
    """Routing-Connector-Art."""

    INPUT = "input"
    OUTPUT = "output"
    BIDIRECTIONAL = "bidirectional"
    JUNCTION = "junction"
    TERMINAL = "terminal"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class ReinforcementSystemKind(str, Enum):
    """Bewehrungsprofil-Art."""

    NONE = "none"
    GENERIC = "generic"
    BAR = "bar"
    MESH = "mesh"
    CAGE = "cage"
    PRESTRESSING = "prestressing"
    FIBER = "fiber"
    ANCHOR = "anchor"
    CUSTOM = "custom"

    @property
    def key(self) -> str:
        return str(self.value)


class ReinforcementPlacementMode(str, Enum):
    """Bewehrungs-Platzierungsmodus."""

    NONE = "none"
    DECLARATIVE_PROFILE = "declarative_profile"
    LAYER_BASED = "layer_based"
    EDGE_BASED = "edge_based"
    GRID_BASED = "grid_based"
    CUSTOM_DECLARATIVE = "custom_declarative"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class AnalysisParameterDefaults:
    """Deklarativer Analyseparameter."""

    parameter_id: str
    value_type: str
    label: str | None = None
    value: Any = None
    default_value: Any = None
    unit: str | None = None
    required: bool = False
    editable: bool = True
    source: str = AnalysisParameterSource.DEFAULT.value
    description: str = ""
    allowed_values: tuple[Any, ...] = field(default_factory=tuple)
    min_value: float | None = None
    max_value: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AnalysisParameterDefaults":
        parameter_id = normalize_analysis_key(self.parameter_id, "parameter_id")
        value_type = parse_value_type_value(self.value_type)
        label = clean_optional_string(self.label) or humanize_key(parameter_id)
        unit = normalize_optional_unit_value(self.unit)
        value = normalize_typed_value(self.value, value_type, allow_none=True)
        default_value = normalize_typed_value(self.default_value, value_type, allow_none=True)
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
            raise AnalysisDefaultsError(f"Required analysis parameter {parameter_id!r} needs a value or default_value.")

        if min_value is not None and max_value is not None and min_value > max_value:
            raise AnalysisDefaultsError(f"Analysis parameter {parameter_id!r} has min_value greater than max_value.")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if min_value is not None and float(value) < min_value:
                raise AnalysisDefaultsError(f"Analysis parameter {parameter_id!r} value is below min_value.")
            if max_value is not None and float(value) > max_value:
                raise AnalysisDefaultsError(f"Analysis parameter {parameter_id!r} value is above max_value.")

        if allowed_values and value is not None and value not in allowed_values:
            raise AnalysisDefaultsError(f"Analysis parameter {parameter_id!r} value is not in allowed_values.")

        return AnalysisParameterDefaults(
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
class AnalysisCheckDefaults:
    """Deklarativer Analysecheck."""

    check_id: str
    scope: str
    severity: str = AnalysisCheckSeverity.WARNING.value
    enabled: bool = True
    field_path: str | None = None
    expression: str | None = None
    message: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AnalysisCheckDefaults":
        check_id = normalize_analysis_key(self.check_id, "check_id")
        scope = parse_check_scope_value(self.scope)
        severity = parse_check_severity_value(self.severity)
        enabled = bool(self.enabled)
        field_path = normalize_optional_field_path(self.field_path)
        expression = normalize_optional_expression(self.expression, "expression")
        message = clean_optional_string(self.message) or f"Analysis check {check_id} failed."
        metadata = normalize_metadata(self.metadata)

        if not field_path and not expression:
            raise AnalysisDefaultsError(f"Analysis check {check_id!r} requires field_path or expression.")

        return AnalysisCheckDefaults(
            check_id=check_id,
            scope=scope,
            severity=severity,
            enabled=enabled,
            field_path=field_path,
            expression=expression,
            message=message,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "check_id": normalized.check_id,
            "scope": normalized.scope,
            "severity": normalized.severity,
            "enabled": normalized.enabled,
            "field_path": normalized.field_path,
            "expression": normalized.expression,
            "message": normalized.message,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class AnalysisChecksDefaults:
    """Defaults für analysis/checks.json."""

    checks: tuple[AnalysisCheckDefaults, ...] = field(default_factory=tuple)
    validation_policy: str = AnalysisValidationPolicy.STRICT.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AnalysisChecksDefaults":
        checks = tuple(check.normalized() for check in self.checks or ())
        assert_unique_values([check.check_id for check in checks], "check_id")

        return AnalysisChecksDefaults(
            checks=tuple(sorted(checks, key=lambda item: (item.scope, item.check_id))),
            validation_policy=parse_validation_policy_value(self.validation_policy),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt analysis/checks.json."""
        normalized = self.normalized()

        return {
            "schema_version": ANALYSIS_CHECKS_DOCUMENT_SCHEMA_VERSION,
            "validation_policy": normalized.validation_policy,
            "check_ids": [check.check_id for check in normalized.checks],
            "checks": [check.to_dict() for check in normalized.checks],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class AnalysisAssumptionDefaults:
    """Eine deklarative Analyseannahme."""

    assumption_id: str
    label: str | None = None
    description: str = ""
    value: Any = None
    unit: str | None = None
    source: str = AnalysisParameterSource.DEFAULT.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AnalysisAssumptionDefaults":
        assumption_id = normalize_analysis_key(self.assumption_id, "assumption_id")
        label = clean_optional_string(self.label) or humanize_key(assumption_id)
        description = clean_optional_string(self.description) or ""
        value = normalize_json_value(self.value)
        unit = normalize_optional_unit_value(self.unit)
        source = parse_parameter_source_value(self.source)

        return AnalysisAssumptionDefaults(
            assumption_id=assumption_id,
            label=label,
            description=description,
            value=value,
            unit=unit,
            source=source,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "assumption_id": normalized.assumption_id,
            "label": normalized.label,
            "description": normalized.description,
            "value": normalized.value,
            "unit": normalized.unit,
            "source": normalized.source,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class AnalysisAssumptionsDefaults:
    """Defaults für analysis/assumptions.json."""

    assumption_set_id: str = DEFAULT_ASSUMPTION_SET_ID
    assumptions: tuple[AnalysisAssumptionDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "AnalysisAssumptionsDefaults":
        assumption_set_id = normalize_analysis_key(self.assumption_set_id, "assumption_set_id")
        assumptions = tuple(assumption.normalized() for assumption in self.assumptions or ())
        assert_unique_values([assumption.assumption_id for assumption in assumptions], "assumption_id")

        return AnalysisAssumptionsDefaults(
            assumption_set_id=assumption_set_id,
            assumptions=tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt analysis/assumptions.json."""
        normalized = self.normalized()

        return {
            "schema_version": ANALYSIS_ASSUMPTIONS_DOCUMENT_SCHEMA_VERSION,
            "assumption_set_id": normalized.assumption_set_id,
            "assumption_ids": [assumption.assumption_id for assumption in normalized.assumptions],
            "assumptions": [assumption.to_dict() for assumption in normalized.assumptions],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class StaticsLoadCaseDefaults:
    """Deklarativer Lastfall für analysis/statics/profile.json."""

    load_case_id: str
    load_case_kind: str
    label: str | None = None
    magnitude: float | None = None
    unit: str | None = None
    direction: Mapping[str, Any] | None = None
    expression: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "StaticsLoadCaseDefaults":
        load_case_id = normalize_analysis_key(self.load_case_id, "load_case_id")
        load_case_kind = parse_load_case_kind_value(self.load_case_kind)
        label = clean_optional_string(self.label) or humanize_key(load_case_id)
        magnitude = normalize_optional_float(self.magnitude, "magnitude")
        unit = normalize_optional_unit_value(self.unit)
        direction = normalize_optional_vector3(self.direction, "direction")
        expression = normalize_optional_expression(self.expression, "expression")
        enabled = bool(self.enabled)

        if magnitude is None and expression is None:
            raise AnalysisDefaultsError(f"Load case {load_case_id!r} requires magnitude or expression.")

        return StaticsLoadCaseDefaults(
            load_case_id=load_case_id,
            load_case_kind=load_case_kind,
            label=label,
            magnitude=magnitude,
            unit=unit,
            direction=direction,
            expression=expression,
            enabled=enabled,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "load_case_id": normalized.load_case_id,
            "load_case_kind": normalized.load_case_kind,
            "label": normalized.label,
            "magnitude": normalized.magnitude,
            "unit": normalized.unit,
            "direction": dict(normalized.direction) if normalized.direction else None,
            "expression": normalized.expression,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class StaticsProfileDefaults:
    """Defaults für analysis/statics/profile.json."""

    profile_id: str = DEFAULT_STATICS_PROFILE_ID
    status: str = AnalysisProfileStatus.DISABLED.value
    system_kind: str = StaticsSystemKind.NONE.value
    load_bearing: bool | None = None
    design_relevant: bool = False
    parameters: tuple[AnalysisParameterDefaults, ...] = field(default_factory=tuple)
    load_cases: tuple[StaticsLoadCaseDefaults, ...] = field(default_factory=tuple)
    checks: tuple[AnalysisCheckDefaults, ...] = field(default_factory=tuple)
    assumptions: tuple[AnalysisAssumptionDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "StaticsProfileDefaults":
        profile_id = normalize_analysis_key(self.profile_id, "profile_id")
        status = parse_profile_status_value(self.status)
        system_kind = parse_statics_system_kind_value(self.system_kind)
        load_bearing = None if self.load_bearing is None else bool(self.load_bearing)
        design_relevant = bool(self.design_relevant)
        parameters = tuple(parameter.normalized() for parameter in self.parameters or ())
        load_cases = tuple(load_case.normalized() for load_case in self.load_cases or ())
        checks = tuple(check.normalized() for check in self.checks or ())
        assumptions = tuple(assumption.normalized() for assumption in self.assumptions or ())

        assert_unique_values([parameter.parameter_id for parameter in parameters], "parameter_id")
        assert_unique_values([load_case.load_case_id for load_case in load_cases], "load_case_id")
        assert_unique_values([check.check_id for check in checks], "check_id")
        assert_unique_values([assumption.assumption_id for assumption in assumptions], "assumption_id")

        if system_kind != StaticsSystemKind.NONE.value and status == AnalysisProfileStatus.DISABLED.value:
            status = AnalysisProfileStatus.DRAFT.value

        if load_bearing is True and system_kind == StaticsSystemKind.NONE.value:
            system_kind = StaticsSystemKind.GENERIC.value
            status = AnalysisProfileStatus.DRAFT.value

        return StaticsProfileDefaults(
            profile_id=profile_id,
            status=status,
            system_kind=system_kind,
            load_bearing=load_bearing,
            design_relevant=design_relevant,
            parameters=tuple(sorted(parameters, key=lambda item: item.parameter_id)),
            load_cases=tuple(sorted(load_cases, key=lambda item: item.load_case_id)),
            checks=tuple(sorted(checks, key=lambda item: item.check_id)),
            assumptions=tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt analysis/statics/profile.json."""
        normalized = self.normalized()

        return {
            "schema_version": ANALYSIS_STATICS_PROFILE_DOCUMENT_SCHEMA_VERSION,
            "profile_id": normalized.profile_id,
            "status": normalized.status,
            "system_kind": normalized.system_kind,
            "load_bearing": normalized.load_bearing,
            "design_relevant": normalized.design_relevant,
            "parameter_ids": [parameter.parameter_id for parameter in normalized.parameters],
            "parameters": [parameter.to_dict() for parameter in normalized.parameters],
            "load_case_ids": [load_case.load_case_id for load_case in normalized.load_cases],
            "load_cases": [load_case.to_dict() for load_case in normalized.load_cases],
            "check_ids": [check.check_id for check in normalized.checks],
            "checks": [check.to_dict() for check in normalized.checks],
            "assumption_ids": [assumption.assumption_id for assumption in normalized.assumptions],
            "assumptions": [assumption.to_dict() for assumption in normalized.assumptions],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class RoutingConnectorDefaults:
    """Routing-Connector für analysis/routing/profile.json."""

    connector_id: str
    connector_kind: str = RoutingConnectorKind.BIDIRECTIONAL.value
    label: str | None = None
    port_ref: str | None = None
    socket_ref: str | None = None
    direction: Mapping[str, Any] | None = None
    nominal_size: float | None = None
    unit: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RoutingConnectorDefaults":
        connector_id = normalize_analysis_key(self.connector_id, "connector_id")
        connector_kind = parse_routing_connector_kind_value(self.connector_kind)
        label = clean_optional_string(self.label) or humanize_key(connector_id)
        port_ref = normalize_optional_analysis_key(self.port_ref, "port_ref")
        socket_ref = normalize_optional_analysis_key(self.socket_ref, "socket_ref")
        direction = normalize_optional_vector3(self.direction, "direction")
        nominal_size = normalize_optional_non_negative_float(self.nominal_size, "nominal_size")
        unit = normalize_optional_unit_value(self.unit)
        enabled = bool(self.enabled)

        return RoutingConnectorDefaults(
            connector_id=connector_id,
            connector_kind=connector_kind,
            label=label,
            port_ref=port_ref,
            socket_ref=socket_ref,
            direction=direction,
            nominal_size=nominal_size,
            unit=unit,
            enabled=enabled,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "connector_id": normalized.connector_id,
            "connector_kind": normalized.connector_kind,
            "label": normalized.label,
            "port_ref": normalized.port_ref,
            "socket_ref": normalized.socket_ref,
            "direction": dict(normalized.direction) if normalized.direction else None,
            "nominal_size": normalized.nominal_size,
            "unit": normalized.unit,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class RoutingProfileDefaults:
    """Defaults für analysis/routing/profile.json."""

    profile_id: str = DEFAULT_ROUTING_PROFILE_ID
    status: str = AnalysisProfileStatus.DISABLED.value
    system_kind: str = RoutingSystemKind.NONE.value
    route_through_allowed: bool = False
    connect_to_hosts: bool = False
    min_bend_radius_m: float | None = None
    slope_percent: float | None = None
    connectors: tuple[RoutingConnectorDefaults, ...] = field(default_factory=tuple)
    parameters: tuple[AnalysisParameterDefaults, ...] = field(default_factory=tuple)
    checks: tuple[AnalysisCheckDefaults, ...] = field(default_factory=tuple)
    assumptions: tuple[AnalysisAssumptionDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "RoutingProfileDefaults":
        profile_id = normalize_analysis_key(self.profile_id, "profile_id")
        status = parse_profile_status_value(self.status)
        system_kind = parse_routing_system_kind_value(self.system_kind)
        route_through_allowed = bool(self.route_through_allowed)
        connect_to_hosts = bool(self.connect_to_hosts)
        min_bend_radius_m = normalize_optional_positive_float(self.min_bend_radius_m, "min_bend_radius_m")
        slope_percent = normalize_optional_float(self.slope_percent, "slope_percent")
        connectors = tuple(connector.normalized() for connector in self.connectors or ())
        parameters = tuple(parameter.normalized() for parameter in self.parameters or ())
        checks = tuple(check.normalized() for check in self.checks or ())
        assumptions = tuple(assumption.normalized() for assumption in self.assumptions or ())

        assert_unique_values([connector.connector_id for connector in connectors], "connector_id")
        assert_unique_values([parameter.parameter_id for parameter in parameters], "parameter_id")
        assert_unique_values([check.check_id for check in checks], "check_id")
        assert_unique_values([assumption.assumption_id for assumption in assumptions], "assumption_id")

        if system_kind != RoutingSystemKind.NONE.value and status == AnalysisProfileStatus.DISABLED.value:
            status = AnalysisProfileStatus.DRAFT.value

        return RoutingProfileDefaults(
            profile_id=profile_id,
            status=status,
            system_kind=system_kind,
            route_through_allowed=route_through_allowed,
            connect_to_hosts=connect_to_hosts,
            min_bend_radius_m=min_bend_radius_m,
            slope_percent=slope_percent,
            connectors=tuple(sorted(connectors, key=lambda item: item.connector_id)),
            parameters=tuple(sorted(parameters, key=lambda item: item.parameter_id)),
            checks=tuple(sorted(checks, key=lambda item: item.check_id)),
            assumptions=tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt analysis/routing/profile.json."""
        normalized = self.normalized()

        return {
            "schema_version": ANALYSIS_ROUTING_PROFILE_DOCUMENT_SCHEMA_VERSION,
            "profile_id": normalized.profile_id,
            "status": normalized.status,
            "system_kind": normalized.system_kind,
            "route_through_allowed": normalized.route_through_allowed,
            "connect_to_hosts": normalized.connect_to_hosts,
            "min_bend_radius_m": normalized.min_bend_radius_m,
            "slope_percent": normalized.slope_percent,
            "connector_ids": [connector.connector_id for connector in normalized.connectors],
            "connectors": [connector.to_dict() for connector in normalized.connectors],
            "parameter_ids": [parameter.parameter_id for parameter in normalized.parameters],
            "parameters": [parameter.to_dict() for parameter in normalized.parameters],
            "check_ids": [check.check_id for check in normalized.checks],
            "checks": [check.to_dict() for check in normalized.checks],
            "assumption_ids": [assumption.assumption_id for assumption in normalized.assumptions],
            "assumptions": [assumption.to_dict() for assumption in normalized.assumptions],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class ReinforcementLayerDefaults:
    """Deklarative Bewehrungslage."""

    layer_id: str
    label: str | None = None
    cover_m: float | None = None
    spacing_m: float | None = None
    diameter_m: float | None = None
    direction: Mapping[str, Any] | None = None
    material_ref: str | None = None
    enabled: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ReinforcementLayerDefaults":
        layer_id = normalize_analysis_key(self.layer_id, "layer_id")
        label = clean_optional_string(self.label) or humanize_key(layer_id)
        cover_m = normalize_optional_non_negative_float(self.cover_m, "cover_m")
        spacing_m = normalize_optional_positive_float(self.spacing_m, "spacing_m")
        diameter_m = normalize_optional_positive_float(self.diameter_m, "diameter_m")
        direction = normalize_optional_vector3(self.direction, "direction")
        material_ref = clean_optional_string(self.material_ref)
        enabled = bool(self.enabled)

        return ReinforcementLayerDefaults(
            layer_id=layer_id,
            label=label,
            cover_m=cover_m,
            spacing_m=spacing_m,
            diameter_m=diameter_m,
            direction=direction,
            material_ref=material_ref,
            enabled=enabled,
            metadata=normalize_metadata(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "layer_id": normalized.layer_id,
            "label": normalized.label,
            "cover_m": normalized.cover_m,
            "spacing_m": normalized.spacing_m,
            "diameter_m": normalized.diameter_m,
            "direction": dict(normalized.direction) if normalized.direction else None,
            "material_ref": normalized.material_ref,
            "enabled": normalized.enabled,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ReinforcementProfileDefaults:
    """Defaults für analysis/reinforcement/profile.json."""

    profile_id: str = DEFAULT_REINFORCEMENT_PROFILE_ID
    status: str = AnalysisProfileStatus.DISABLED.value
    system_kind: str = ReinforcementSystemKind.NONE.value
    placement_mode: str = ReinforcementPlacementMode.NONE.value
    reinforcement_required: bool = False
    layers: tuple[ReinforcementLayerDefaults, ...] = field(default_factory=tuple)
    parameters: tuple[AnalysisParameterDefaults, ...] = field(default_factory=tuple)
    checks: tuple[AnalysisCheckDefaults, ...] = field(default_factory=tuple)
    assumptions: tuple[AnalysisAssumptionDefaults, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ReinforcementProfileDefaults":
        profile_id = normalize_analysis_key(self.profile_id, "profile_id")
        status = parse_profile_status_value(self.status)
        system_kind = parse_reinforcement_system_kind_value(self.system_kind)
        placement_mode = parse_reinforcement_placement_mode_value(self.placement_mode)
        reinforcement_required = bool(self.reinforcement_required)
        layers = tuple(layer.normalized() for layer in self.layers or ())
        parameters = tuple(parameter.normalized() for parameter in self.parameters or ())
        checks = tuple(check.normalized() for check in self.checks or ())
        assumptions = tuple(assumption.normalized() for assumption in self.assumptions or ())

        assert_unique_values([layer.layer_id for layer in layers], "layer_id")
        assert_unique_values([parameter.parameter_id for parameter in parameters], "parameter_id")
        assert_unique_values([check.check_id for check in checks], "check_id")
        assert_unique_values([assumption.assumption_id for assumption in assumptions], "assumption_id")

        if reinforcement_required and system_kind == ReinforcementSystemKind.NONE.value:
            system_kind = ReinforcementSystemKind.GENERIC.value

        if system_kind != ReinforcementSystemKind.NONE.value and placement_mode == ReinforcementPlacementMode.NONE.value:
            placement_mode = ReinforcementPlacementMode.DECLARATIVE_PROFILE.value

        if system_kind != ReinforcementSystemKind.NONE.value and status == AnalysisProfileStatus.DISABLED.value:
            status = AnalysisProfileStatus.DRAFT.value

        return ReinforcementProfileDefaults(
            profile_id=profile_id,
            status=status,
            system_kind=system_kind,
            placement_mode=placement_mode,
            reinforcement_required=reinforcement_required,
            layers=tuple(sorted(layers, key=lambda item: item.layer_id)),
            parameters=tuple(sorted(parameters, key=lambda item: item.parameter_id)),
            checks=tuple(sorted(checks, key=lambda item: item.check_id)),
            assumptions=tuple(sorted(assumptions, key=lambda item: item.assumption_id)),
            metadata=normalize_metadata(self.metadata),
        )

    def to_document(self) -> dict[str, Any]:
        """Erzeugt analysis/reinforcement/profile.json."""
        normalized = self.normalized()

        return {
            "schema_version": ANALYSIS_REINFORCEMENT_PROFILE_DOCUMENT_SCHEMA_VERSION,
            "profile_id": normalized.profile_id,
            "status": normalized.status,
            "system_kind": normalized.system_kind,
            "placement_mode": normalized.placement_mode,
            "reinforcement_required": normalized.reinforcement_required,
            "layer_ids": [layer.layer_id for layer in normalized.layers],
            "layers": [layer.to_dict() for layer in normalized.layers],
            "parameter_ids": [parameter.parameter_id for parameter in normalized.parameters],
            "parameters": [parameter.to_dict() for parameter in normalized.parameters],
            "check_ids": [check.check_id for check in normalized.checks],
            "checks": [check.to_dict() for check in normalized.checks],
            "assumption_ids": [assumption.assumption_id for assumption in normalized.assumptions],
            "assumptions": [assumption.to_dict() for assumption in normalized.assumptions],
            "metadata": dict(normalized.metadata),
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_document()


@dataclass(frozen=True, slots=True)
class AnalysisDefaults:
    """Vollständige Defaults für alle analysis/*.json-Dokumente."""

    statics: StaticsProfileDefaults = field(default_factory=StaticsProfileDefaults)
    routing: RoutingProfileDefaults = field(default_factory=RoutingProfileDefaults)
    reinforcement: ReinforcementProfileDefaults = field(default_factory=ReinforcementProfileDefaults)
    checks: AnalysisChecksDefaults = field(default_factory=AnalysisChecksDefaults)
    assumptions: AnalysisAssumptionsDefaults = field(default_factory=AnalysisAssumptionsDefaults)

    def normalized(self) -> "AnalysisDefaults":
        statics = self.statics.normalized()
        routing = self.routing.normalized()
        reinforcement = self.reinforcement.normalized()

        combined_checks = merge_analysis_checks(
            self.checks.checks,
            statics.checks,
            routing.checks,
            reinforcement.checks,
        )
        combined_assumptions = merge_analysis_assumptions(
            self.assumptions.assumptions,
            statics.assumptions,
            routing.assumptions,
            reinforcement.assumptions,
        )

        return AnalysisDefaults(
            statics=statics,
            routing=routing,
            reinforcement=reinforcement,
            checks=AnalysisChecksDefaults(
                checks=combined_checks,
                validation_policy=self.checks.validation_policy,
                metadata=self.checks.metadata,
            ).normalized(),
            assumptions=AnalysisAssumptionsDefaults(
                assumption_set_id=self.assumptions.assumption_set_id,
                assumptions=combined_assumptions,
                metadata=self.assumptions.metadata,
            ).normalized(),
        )

    def to_documents(self, *, include_optional: bool = True) -> dict[str, dict[str, Any]]:
        """Erzeugt alle Analysis-Dokumente als Pfad -> Payload."""
        normalized = self.normalized()

        documents: dict[str, dict[str, Any]] = {
            "analysis/statics/profile.json": normalized.statics.to_document(),
            "analysis/routing/profile.json": normalized.routing.to_document(),
            "analysis/reinforcement/profile.json": normalized.reinforcement.to_document(),
        }

        if include_optional:
            documents["analysis/checks.json"] = normalized.checks.to_document()
            documents["analysis/assumptions.json"] = normalized.assumptions.to_document()

        return documents

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": ANALYSIS_DEFAULTS_SCHEMA_VERSION,
            "statics": normalized.statics.to_dict(),
            "routing": normalized.routing.to_dict(),
            "reinforcement": normalized.reinforcement.to_dict(),
            "checks": normalized.checks.to_dict(),
            "assumptions": normalized.assumptions.to_dict(),
        }


def build_analysis_defaults(
    *,
    object_kind: str,
    load_bearing: bool | None = None,
    enable_statics: bool | None = None,
    enable_routing: bool | None = None,
    enable_reinforcement: bool | None = None,
    statics_system_kind: str | None = None,
    routing_system_kind: str | None = None,
    reinforcement_system_kind: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> AnalysisDefaults:
    """Baut AnalysisDefaults aus expliziten Werten."""
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
        metadata_payload = {
            "source": "build_analysis_defaults",
            "object_kind": object_kind_value,
            **dict(metadata or {}),
        }

        statics_enabled = bool(enable_statics) if enable_statics is not None else bool(load_bearing)
        routing_enabled = bool(enable_routing) if enable_routing is not None else object_kind_value == "adaptive_system"
        reinforcement_enabled = bool(enable_reinforcement) if enable_reinforcement is not None else False

        statics_kind = statics_system_kind or infer_statics_system_kind(
            object_kind=object_kind_value,
            load_bearing=load_bearing,
        )
        routing_kind = routing_system_kind or infer_routing_system_kind(object_kind_value)
        reinforcement_kind = reinforcement_system_kind or infer_reinforcement_system_kind(
            object_kind=object_kind_value,
            load_bearing=load_bearing,
        )

        statics = StaticsProfileDefaults(
            status=AnalysisProfileStatus.DRAFT.value if statics_enabled else AnalysisProfileStatus.DISABLED.value,
            system_kind=statics_kind if statics_enabled else StaticsSystemKind.NONE.value,
            load_bearing=load_bearing,
            design_relevant=statics_enabled,
            parameters=default_statics_parameters(load_bearing=load_bearing),
            load_cases=default_statics_load_cases() if statics_enabled else tuple(),
            checks=default_statics_checks() if statics_enabled else tuple(),
            assumptions=default_statics_assumptions() if statics_enabled else tuple(),
            metadata=metadata_payload,
        ).normalized()

        routing = RoutingProfileDefaults(
            status=AnalysisProfileStatus.DRAFT.value if routing_enabled else AnalysisProfileStatus.DISABLED.value,
            system_kind=routing_kind if routing_enabled else RoutingSystemKind.NONE.value,
            route_through_allowed=routing_enabled,
            connect_to_hosts=routing_enabled,
            connectors=default_routing_connectors() if routing_enabled else tuple(),
            parameters=default_routing_parameters() if routing_enabled else tuple(),
            checks=default_routing_checks() if routing_enabled else tuple(),
            assumptions=default_routing_assumptions() if routing_enabled else tuple(),
            metadata=metadata_payload,
        ).normalized()

        reinforcement = ReinforcementProfileDefaults(
            status=AnalysisProfileStatus.DRAFT.value if reinforcement_enabled else AnalysisProfileStatus.DISABLED.value,
            system_kind=reinforcement_kind if reinforcement_enabled else ReinforcementSystemKind.NONE.value,
            placement_mode=(
                ReinforcementPlacementMode.DECLARATIVE_PROFILE.value
                if reinforcement_enabled
                else ReinforcementPlacementMode.NONE.value
            ),
            reinforcement_required=reinforcement_enabled,
            layers=default_reinforcement_layers() if reinforcement_enabled else tuple(),
            parameters=default_reinforcement_parameters() if reinforcement_enabled else tuple(),
            checks=default_reinforcement_checks() if reinforcement_enabled else tuple(),
            assumptions=default_reinforcement_assumptions() if reinforcement_enabled else tuple(),
            metadata=metadata_payload,
        ).normalized()

        return AnalysisDefaults(
            statics=statics,
            routing=routing,
            reinforcement=reinforcement,
            checks=AnalysisChecksDefaults(metadata=metadata_payload),
            assumptions=AnalysisAssumptionsDefaults(metadata=metadata_payload),
        ).normalized()
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Could not build analysis defaults: {exc}") from exc


def analysis_defaults_from_create_request(
    request: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AnalysisDefaults:
    """Baut AnalysisDefaults aus einem CreateRequest-ähnlichen Objekt."""
    try:
        normalized_request = normalize_create_request(request)
        physical = normalized_request.physical.normalized()

        enable_statics = bool(physical.load_bearing)
        enable_routing = normalized_request.object_kind == "adaptive_system" or bool(normalized_request.dynamic.context_rules)
        enable_reinforcement = False

        return build_analysis_defaults(
            object_kind=normalized_request.object_kind,
            load_bearing=physical.load_bearing,
            enable_statics=enable_statics,
            enable_routing=enable_routing,
            enable_reinforcement=enable_reinforcement,
            metadata={
                "source": "create_request",
                "object_kind": normalized_request.object_kind,
                **dict(metadata or {}),
            },
        )
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Could not build analysis defaults from CreateRequest: {exc}") from exc


def analysis_defaults_from_context(
    context: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AnalysisDefaults:
    """Baut AnalysisDefaults aus einem PackageContext-ähnlichen Objekt."""
    try:
        normalized_context = context.normalized() if hasattr(context, "normalized") else context

        return build_analysis_defaults(
            object_kind=normalized_context.object_kind,
            load_bearing=None,
            enable_statics=False,
            enable_routing=normalized_context.object_kind == "adaptive_system",
            enable_reinforcement=False,
            metadata={
                "source": "package_context",
                "object_kind": normalized_context.object_kind,
                "correlation_id": getattr(normalized_context, "correlation_id", None),
                **dict(metadata or {}),
            },
        )
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Could not build analysis defaults from PackageContext: {exc}") from exc


def analysis_defaults_from_creation_plan(
    creation_plan: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> AnalysisDefaults:
    """Baut AnalysisDefaults aus einem CreationPlan-ähnlichen Objekt."""
    try:
        normalized_plan = creation_plan.normalized() if hasattr(creation_plan, "normalized") else creation_plan

        return analysis_defaults_from_create_request(
            normalized_plan.request,
            metadata={
                "source": "creation_plan",
                "profile_key": getattr(normalized_plan.profile, "profile_key", None),
                **dict(metadata or {}),
            },
        )
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Could not build analysis defaults from CreationPlan: {exc}") from exc


def analysis_documents_from_create_request(
    request: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle analysis/*.json-Dokumente aus CreateRequest."""
    return analysis_defaults_from_create_request(
        request,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def analysis_documents_from_context(
    context: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle analysis/*.json-Dokumente aus PackageContext."""
    return analysis_defaults_from_context(
        context,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def analysis_documents_from_creation_plan(
    creation_plan: Any,
    *,
    include_optional: bool = True,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Baut alle analysis/*.json-Dokumente aus CreationPlan."""
    return analysis_defaults_from_creation_plan(
        creation_plan,
        metadata=metadata,
    ).to_documents(include_optional=include_optional)


def default_statics_parameters(*, load_bearing: bool | None = None) -> tuple[AnalysisParameterDefaults, ...]:
    """Erzeugt Standardparameter für Statikprofile."""
    return (
        AnalysisParameterDefaults(
            parameter_id="load_bearing",
            label="Load Bearing",
            value_type=AnalysisValueType.BOOLEAN.value,
            value=bool(load_bearing) if load_bearing is not None else False,
            default_value=False,
            editable=True,
            source=AnalysisParameterSource.PHYSICAL.value,
        ).normalized(),
        AnalysisParameterDefaults(
            parameter_id="safety_factor",
            label="Safety Factor",
            value_type=AnalysisValueType.NUMBER.value,
            unit="none",
            value=1.0,
            default_value=1.0,
            min_value=1.0,
            editable=True,
            source=AnalysisParameterSource.DEFAULT.value,
        ).normalized(),
    )


def default_statics_load_cases() -> tuple[StaticsLoadCaseDefaults, ...]:
    """Erzeugt Standardlastfälle."""
    return (
        StaticsLoadCaseDefaults(
            load_case_id="self_weight",
            load_case_kind=LoadCaseKind.SELF_WEIGHT.value,
            label="Self Weight",
            magnitude=1.0,
            unit="none",
            direction={"x": 0.0, "y": -1.0, "z": 0.0},
            enabled=True,
        ).normalized(),
    )


def default_statics_checks() -> tuple[AnalysisCheckDefaults, ...]:
    """Erzeugt Standardchecks für Statikprofile."""
    return (
        AnalysisCheckDefaults(
            check_id="statics_requires_physical_dimensions",
            scope=AnalysisCheckScope.STATICS.value,
            severity=AnalysisCheckSeverity.WARNING.value,
            field_path="physical.dimensions",
            message="Statics profile should reference physical dimensions.",
        ).normalized(),
    )


def default_statics_assumptions() -> tuple[AnalysisAssumptionDefaults, ...]:
    """Erzeugt Standardannahmen für Statikprofile."""
    return (
        AnalysisAssumptionDefaults(
            assumption_id="statics_is_declarative",
            label="Statics Is Declarative",
            description="This profile contains declarative statics metadata only.",
            value=True,
            source=AnalysisParameterSource.SYSTEM.value,
        ).normalized(),
    )


def default_routing_connectors() -> tuple[RoutingConnectorDefaults, ...]:
    """Erzeugt Standard-Routing-Connectoren."""
    return (
        RoutingConnectorDefaults(
            connector_id="input",
            connector_kind=RoutingConnectorKind.INPUT.value,
            label="Input",
            enabled=True,
        ).normalized(),
        RoutingConnectorDefaults(
            connector_id="output",
            connector_kind=RoutingConnectorKind.OUTPUT.value,
            label="Output",
            enabled=True,
        ).normalized(),
    )


def default_routing_parameters() -> tuple[AnalysisParameterDefaults, ...]:
    """Erzeugt Standardparameter für Routingprofile."""
    return (
        AnalysisParameterDefaults(
            parameter_id="allow_connections",
            label="Allow Connections",
            value_type=AnalysisValueType.BOOLEAN.value,
            value=True,
            default_value=True,
            source=AnalysisParameterSource.DEFAULT.value,
        ).normalized(),
    )


def default_routing_checks() -> tuple[AnalysisCheckDefaults, ...]:
    """Erzeugt Standardchecks für Routingprofile."""
    return (
        AnalysisCheckDefaults(
            check_id="routing_connectors_defined",
            scope=AnalysisCheckScope.ROUTING.value,
            severity=AnalysisCheckSeverity.WARNING.value,
            field_path="analysis.routing.connectors",
            message="Routing profiles should define connectors.",
        ).normalized(),
    )


def default_routing_assumptions() -> tuple[AnalysisAssumptionDefaults, ...]:
    """Erzeugt Standardannahmen für Routingprofile."""
    return (
        AnalysisAssumptionDefaults(
            assumption_id="routing_is_declarative",
            label="Routing Is Declarative",
            description="This profile contains declarative routing metadata only.",
            value=True,
            source=AnalysisParameterSource.SYSTEM.value,
        ).normalized(),
    )


def default_reinforcement_layers() -> tuple[ReinforcementLayerDefaults, ...]:
    """Erzeugt Standard-Bewehrungslagen."""
    return (
        ReinforcementLayerDefaults(
            layer_id="main_reinforcement",
            label="Main Reinforcement",
            cover_m=0.03,
            enabled=True,
        ).normalized(),
    )


def default_reinforcement_parameters() -> tuple[AnalysisParameterDefaults, ...]:
    """Erzeugt Standardparameter für Bewehrungsprofile."""
    return (
        AnalysisParameterDefaults(
            parameter_id="nominal_cover_m",
            label="Nominal Cover",
            value_type=AnalysisValueType.NUMBER.value,
            unit="m",
            value=0.03,
            default_value=0.03,
            min_value=0.0,
            source=AnalysisParameterSource.DEFAULT.value,
        ).normalized(),
    )


def default_reinforcement_checks() -> tuple[AnalysisCheckDefaults, ...]:
    """Erzeugt Standardchecks für Bewehrungsprofile."""
    return (
        AnalysisCheckDefaults(
            check_id="reinforcement_layers_defined",
            scope=AnalysisCheckScope.REINFORCEMENT.value,
            severity=AnalysisCheckSeverity.WARNING.value,
            field_path="analysis.reinforcement.layers",
            message="Reinforcement profiles should define at least one layer.",
        ).normalized(),
    )


def default_reinforcement_assumptions() -> tuple[AnalysisAssumptionDefaults, ...]:
    """Erzeugt Standardannahmen für Bewehrungsprofile."""
    return (
        AnalysisAssumptionDefaults(
            assumption_id="reinforcement_is_declarative",
            label="Reinforcement Is Declarative",
            description="This profile contains declarative reinforcement metadata only.",
            value=True,
            source=AnalysisParameterSource.SYSTEM.value,
        ).normalized(),
    )


def merge_analysis_checks(*groups: Iterable[AnalysisCheckDefaults]) -> tuple[AnalysisCheckDefaults, ...]:
    """Merged Analysechecks ohne Duplikate."""
    by_id: dict[str, AnalysisCheckDefaults] = {}

    for group in groups:
        for check in group or ():
            normalized = check.normalized()
            by_id[normalized.check_id] = normalized

    return tuple(sorted(by_id.values(), key=lambda item: (item.scope, item.check_id)))


def merge_analysis_assumptions(*groups: Iterable[AnalysisAssumptionDefaults]) -> tuple[AnalysisAssumptionDefaults, ...]:
    """Merged Analyseannahmen ohne Duplikate."""
    by_id: dict[str, AnalysisAssumptionDefaults] = {}

    for group in groups:
        for assumption in group or ():
            normalized = assumption.normalized()
            by_id[normalized.assumption_id] = normalized

    return tuple(sorted(by_id.values(), key=lambda item: item.assumption_id))


def validate_statics_profile_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob analysis/statics/profile.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("analysis/statics/profile.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "profile_id",
            "status",
            "system_kind",
            "load_bearing",
            "design_relevant",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing statics profile field {field_name!r}.")

        if "status" in document:
            try:
                parse_profile_status_value(document["status"])
            except Exception as exc:
                messages.append(str(exc))

        if "system_kind" in document:
            try:
                parse_statics_system_kind_value(document["system_kind"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate statics profile document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_routing_profile_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob analysis/routing/profile.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("analysis/routing/profile.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "profile_id",
            "status",
            "system_kind",
            "route_through_allowed",
            "connect_to_hosts",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing routing profile field {field_name!r}.")

        if "system_kind" in document:
            try:
                parse_routing_system_kind_value(document["system_kind"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate routing profile document: {exc}")

    return len(messages) == 0, tuple(messages)


def validate_reinforcement_profile_document(document: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert grob analysis/reinforcement/profile.json."""
    messages: list[str] = []

    try:
        if not isinstance(document, Mapping):
            return False, ("analysis/reinforcement/profile.json must be a mapping.",)

        required_fields = (
            "schema_version",
            "profile_id",
            "status",
            "system_kind",
            "placement_mode",
            "reinforcement_required",
        )

        for field_name in required_fields:
            if field_name not in document:
                messages.append(f"Missing reinforcement profile field {field_name!r}.")

        if "system_kind" in document:
            try:
                parse_reinforcement_system_kind_value(document["system_kind"])
            except Exception as exc:
                messages.append(str(exc))

    except Exception as exc:
        messages.append(f"Could not validate reinforcement profile document: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_statics_profile_document(document: Mapping[str, Any]) -> None:
    """Wirft AnalysisDefaultsError, wenn analysis/statics/profile.json ungültig ist."""
    valid, messages = validate_statics_profile_document(document)
    if not valid:
        raise AnalysisDefaultsError(" ".join(messages) if messages else "Invalid statics profile document.")


def assert_valid_routing_profile_document(document: Mapping[str, Any]) -> None:
    """Wirft AnalysisDefaultsError, wenn analysis/routing/profile.json ungültig ist."""
    valid, messages = validate_routing_profile_document(document)
    if not valid:
        raise AnalysisDefaultsError(" ".join(messages) if messages else "Invalid routing profile document.")


def assert_valid_reinforcement_profile_document(document: Mapping[str, Any]) -> None:
    """Wirft AnalysisDefaultsError, wenn analysis/reinforcement/profile.json ungültig ist."""
    valid, messages = validate_reinforcement_profile_document(document)
    if not valid:
        raise AnalysisDefaultsError(" ".join(messages) if messages else "Invalid reinforcement profile document.")


def infer_statics_system_kind(*, object_kind: str, load_bearing: bool | None) -> str:
    """Leitet StaticsSystemKind aus object_kind und load_bearing ab."""
    if not load_bearing:
        return StaticsSystemKind.NONE.value

    if object_kind == "cell_block":
        return StaticsSystemKind.WALL.value
    if object_kind == "multi_cell_module":
        return StaticsSystemKind.GENERIC.value
    if object_kind == "adaptive_system":
        return StaticsSystemKind.CUSTOM.value

    return StaticsSystemKind.GENERIC.value


def infer_routing_system_kind(object_kind: str) -> str:
    """Leitet RoutingSystemKind aus object_kind ab."""
    if object_kind == "adaptive_system":
        return RoutingSystemKind.GENERIC.value

    return RoutingSystemKind.NONE.value


def infer_reinforcement_system_kind(*, object_kind: str, load_bearing: bool | None) -> str:
    """Leitet ReinforcementSystemKind aus object_kind und load_bearing ab."""
    if not load_bearing:
        return ReinforcementSystemKind.NONE.value

    if object_kind in {"cell_block", "multi_cell_module"}:
        return ReinforcementSystemKind.GENERIC.value

    return ReinforcementSystemKind.NONE.value


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

        raise AnalysisDefaultsError("CreateRequest value is required.")
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid CreateRequest: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_analysis_key(value: Any, field_name: str) -> str:
    """Normalisiert technische Analysis-Keys."""
    raw = clean_required_string(value, field_name)
    key = (
        raw.lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )

    if not SAFE_ANALYSIS_KEY_RE.match(key):
        raise AnalysisDefaultsError(f"{field_name} contains unsafe characters: {value!r}.")

    return key


def normalize_optional_analysis_key(value: Any, field_name: str) -> str | None:
    """Normalisiert optionale Analysis-Keys."""
    if value is None:
        return None

    return normalize_analysis_key(value, field_name)


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
        raise AnalysisDefaultsError(f"Unsafe field_path {value!r}.")

    return field_path


def normalize_optional_field_path(value: Any) -> str | None:
    """Normalisiert optionalen Field-Path."""
    if value is None:
        return None

    cleaned = clean_optional_string(value)
    if not cleaned:
        return None

    return normalize_field_path(cleaned)


def normalize_optional_unit_value(value: Any) -> str | None:
    """Normalisiert optionale Unit-Werte."""
    if value is None:
        return None

    try:
        from ..domain.units import ensure_unit_value

        return ensure_unit_value(value)
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid unit {value!r}: {exc}") from exc


def normalize_expression(value: Any, field_name: str) -> str:
    """Normalisiert deklarative Expression und blockiert offensichtlich ausführbare Muster."""
    expression = clean_required_string(value, field_name)

    lowered = expression.lower()
    for token in FORBIDDEN_ANALYSIS_EXPRESSION_TOKENS:
        if token in lowered:
            raise AnalysisDefaultsError(
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


def normalize_vector3(value: Mapping[str, Any], field_name: str) -> dict[str, float]:
    """Normalisiert Vector3-Mapping."""
    if not isinstance(value, Mapping):
        raise AnalysisDefaultsError(f"{field_name} must be an object.")

    return {
        "x": normalize_float(value.get("x", 0.0), f"{field_name}.x"),
        "y": normalize_float(value.get("y", 0.0), f"{field_name}.y"),
        "z": normalize_float(value.get("z", 0.0), f"{field_name}.z"),
    }


def normalize_optional_vector3(value: Mapping[str, Any] | None, field_name: str) -> dict[str, float] | None:
    """Normalisiert optionales Vector3-Mapping."""
    if value is None:
        return None

    return normalize_vector3(value, field_name)


def normalize_typed_value(value: Any, value_type: str, *, allow_none: bool) -> Any:
    """Normalisiert Werte anhand AnalysisValueType."""
    if value is None:
        if allow_none:
            return None
        raise AnalysisDefaultsError("Value must not be None.")

    type_value = parse_value_type_value(value_type)

    try:
        if type_value == AnalysisValueType.STRING.value:
            return str(value).strip()

        if type_value == AnalysisValueType.INTEGER.value:
            if isinstance(value, bool):
                raise AnalysisDefaultsError("Integer value must not be boolean.")
            return int(value)

        if type_value == AnalysisValueType.NUMBER.value:
            if isinstance(value, bool):
                raise AnalysisDefaultsError("Number value must not be boolean.")
            number = float(value)
            return int(number) if number.is_integer() else number

        if type_value == AnalysisValueType.BOOLEAN.value:
            if isinstance(value, bool):
                return value
            raw = str(value).strip().lower()
            if raw in {"true", "1", "yes", "on"}:
                return True
            if raw in {"false", "0", "no", "off"}:
                return False
            raise AnalysisDefaultsError(f"Invalid boolean value {value!r}.")

        if type_value in {AnalysisValueType.ENUM.value, AnalysisValueType.FIELD_REF.value}:
            return str(value).strip()

        if type_value == AnalysisValueType.EXPRESSION.value:
            return normalize_expression(value, "value")

        if type_value == AnalysisValueType.UNIT_VALUE.value:
            if not isinstance(value, Mapping):
                raise AnalysisDefaultsError("unit_value must be an object with value and unit.")
            return {
                "value": normalize_json_value(value.get("value")),
                "unit": normalize_optional_unit_value(value.get("unit")) or "none",
            }

        if type_value == AnalysisValueType.OBJECT.value:
            if not isinstance(value, Mapping):
                raise AnalysisDefaultsError("object value must be a mapping.")
            return normalize_json_value(value)

        if type_value == AnalysisValueType.ARRAY.value:
            if not isinstance(value, (list, tuple)):
                raise AnalysisDefaultsError("array value must be a list.")
            return [normalize_json_value(item) for item in value]

        return normalize_json_value(value)
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid value {value!r} for type {value_type!r}.") from exc


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
def parse_profile_status_value(value: Any) -> str:
    """Parst AnalysisProfileStatus."""
    try:
        if isinstance(value, AnalysisProfileStatus):
            return value.value

        raw = normalize_enum_key(value)
        return AnalysisProfileStatus(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid analysis profile status {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_validation_policy_value(value: Any) -> str:
    """Parst AnalysisValidationPolicy."""
    try:
        if isinstance(value, AnalysisValidationPolicy):
            return value.value

        raw = normalize_enum_key(value)
        return AnalysisValidationPolicy(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid analysis validation policy {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_value_type_value(value: Any) -> str:
    """Parst AnalysisValueType."""
    try:
        if isinstance(value, AnalysisValueType):
            return value.value

        raw = normalize_enum_key(value)
        return AnalysisValueType(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid analysis value type {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_parameter_source_value(value: Any) -> str:
    """Parst AnalysisParameterSource."""
    try:
        if isinstance(value, AnalysisParameterSource):
            return value.value

        raw = normalize_enum_key(value)
        return AnalysisParameterSource(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid analysis parameter source {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_check_severity_value(value: Any) -> str:
    """Parst AnalysisCheckSeverity."""
    try:
        if isinstance(value, AnalysisCheckSeverity):
            return value.value

        raw = normalize_enum_key(value)
        return AnalysisCheckSeverity(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid analysis check severity {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_check_scope_value(value: Any) -> str:
    """Parst AnalysisCheckScope."""
    try:
        if isinstance(value, AnalysisCheckScope):
            return value.value

        raw = normalize_enum_key(value)
        return AnalysisCheckScope(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid analysis check scope {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_statics_system_kind_value(value: Any) -> str:
    """Parst StaticsSystemKind."""
    try:
        if isinstance(value, StaticsSystemKind):
            return value.value

        raw = normalize_enum_key(value)
        return StaticsSystemKind(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid statics system kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_load_case_kind_value(value: Any) -> str:
    """Parst LoadCaseKind."""
    try:
        if isinstance(value, LoadCaseKind):
            return value.value

        raw = normalize_enum_key(value)
        return LoadCaseKind(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid load case kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_routing_system_kind_value(value: Any) -> str:
    """Parst RoutingSystemKind."""
    try:
        if isinstance(value, RoutingSystemKind):
            return value.value

        raw = normalize_enum_key(value)
        return RoutingSystemKind(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid routing system kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_routing_connector_kind_value(value: Any) -> str:
    """Parst RoutingConnectorKind."""
    try:
        if isinstance(value, RoutingConnectorKind):
            return value.value

        raw = normalize_enum_key(value)
        return RoutingConnectorKind(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid routing connector kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_reinforcement_system_kind_value(value: Any) -> str:
    """Parst ReinforcementSystemKind."""
    try:
        if isinstance(value, ReinforcementSystemKind):
            return value.value

        raw = normalize_enum_key(value)
        return ReinforcementSystemKind(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid reinforcement system kind {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_reinforcement_placement_mode_value(value: Any) -> str:
    """Parst ReinforcementPlacementMode."""
    try:
        if isinstance(value, ReinforcementPlacementMode):
            return value.value

        raw = normalize_enum_key(value)
        return ReinforcementPlacementMode(raw).value
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid reinforcement placement mode {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise AnalysisDefaultsError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"Invalid enum value {value!r}.") from exc


def normalize_float(value: Any, field_name: str) -> float:
    """Normalisiert Float."""
    try:
        if isinstance(value, bool):
            raise AnalysisDefaultsError(f"{field_name} must be a number.")
        return float(value)
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"{field_name} must be a number.") from exc


def normalize_optional_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionalen Float."""
    if value is None:
        return None
    return normalize_float(value, field_name)


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert positive Float-Werte."""
    number = normalize_float(value, field_name)
    if number <= 0:
        raise AnalysisDefaultsError(f"{field_name} must be > 0.")
    return number


def normalize_optional_positive_float(value: Any, field_name: str) -> float | None:
    """Normalisiert optionale positive Float-Werte."""
    if value is None:
        return None
    return normalize_positive_float(value, field_name)


def normalize_non_negative_float(value: Any, field_name: str) -> float:
    """Normalisiert nicht-negative Float-Werte."""
    number = normalize_float(value, field_name)
    if number < 0:
        raise AnalysisDefaultsError(f"{field_name} must be >= 0.")
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
            raise AnalysisDefaultsError(f"Duplicate {field_name} {value!r}.")
        seen.add(value)


def humanize_key(value: Any) -> str:
    """Erzeugt einfaches Label aus technischem Key."""
    return str(value).replace("_", " ").replace(".", " ").title()


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise AnalysisDefaultsError("metadata must be a mapping.")

    return {
        str(key): normalize_json_value(child_value)
        for key, child_value in value.items()
    }


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise AnalysisDefaultsError(f"{field_name} is required.")

        return cleaned
    except AnalysisDefaultsError:
        raise
    except Exception as exc:
        raise AnalysisDefaultsError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def clear_analysis_defaults_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_profile_status_value.cache_clear()
    parse_validation_policy_value.cache_clear()
    parse_value_type_value.cache_clear()
    parse_parameter_source_value.cache_clear()
    parse_check_severity_value.cache_clear()
    parse_check_scope_value.cache_clear()
    parse_statics_system_kind_value.cache_clear()
    parse_load_case_kind_value.cache_clear()
    parse_routing_system_kind_value.cache_clear()
    parse_routing_connector_kind_value.cache_clear()
    parse_reinforcement_system_kind_value.cache_clear()
    parse_reinforcement_placement_mode_value.cache_clear()


__all__ = [
    "ANALYSIS_ASSUMPTIONS_DOCUMENT_SCHEMA_VERSION",
    "ANALYSIS_CHECKS_DOCUMENT_SCHEMA_VERSION",
    "ANALYSIS_DEFAULTS_SCHEMA_VERSION",
    "ANALYSIS_REINFORCEMENT_PROFILE_DOCUMENT_SCHEMA_VERSION",
    "ANALYSIS_ROUTING_PROFILE_DOCUMENT_SCHEMA_VERSION",
    "ANALYSIS_STATICS_PROFILE_DOCUMENT_SCHEMA_VERSION",
    "DEFAULT_ANALYSIS_PROFILE_ID",
    "DEFAULT_ASSUMPTION_SET_ID",
    "DEFAULT_REINFORCEMENT_PROFILE_ID",
    "DEFAULT_ROUTING_PROFILE_ID",
    "DEFAULT_STATICS_PROFILE_ID",
    "FORBIDDEN_ANALYSIS_EXPRESSION_TOKENS",
    "SAFE_ANALYSIS_KEY_RE",
    "SAFE_FIELD_PATH_RE",
    "AnalysisAssumptionDefaults",
    "AnalysisAssumptionsDefaults",
    "AnalysisCheckDefaults",
    "AnalysisCheckScope",
    "AnalysisCheckSeverity",
    "AnalysisChecksDefaults",
    "AnalysisDefaults",
    "AnalysisDefaultsError",
    "AnalysisParameterDefaults",
    "AnalysisParameterSource",
    "AnalysisProfileStatus",
    "AnalysisValidationPolicy",
    "AnalysisValueType",
    "LoadCaseKind",
    "ReinforcementLayerDefaults",
    "ReinforcementPlacementMode",
    "ReinforcementProfileDefaults",
    "ReinforcementSystemKind",
    "RoutingConnectorDefaults",
    "RoutingConnectorKind",
    "RoutingProfileDefaults",
    "RoutingSystemKind",
    "StaticsLoadCaseDefaults",
    "StaticsProfileDefaults",
    "StaticsSystemKind",
    "analysis_defaults_from_context",
    "analysis_defaults_from_create_request",
    "analysis_defaults_from_creation_plan",
    "analysis_documents_from_context",
    "analysis_documents_from_create_request",
    "analysis_documents_from_creation_plan",
    "assert_unique_values",
    "assert_valid_reinforcement_profile_document",
    "assert_valid_routing_profile_document",
    "assert_valid_statics_profile_document",
    "build_analysis_defaults",
    "clean_optional_string",
    "clean_required_string",
    "clear_analysis_defaults_caches",
    "default_reinforcement_assumptions",
    "default_reinforcement_checks",
    "default_reinforcement_layers",
    "default_reinforcement_parameters",
    "default_routing_assumptions",
    "default_routing_checks",
    "default_routing_connectors",
    "default_routing_parameters",
    "default_statics_assumptions",
    "default_statics_checks",
    "default_statics_load_cases",
    "default_statics_parameters",
    "humanize_key",
    "infer_reinforcement_system_kind",
    "infer_routing_system_kind",
    "infer_statics_system_kind",
    "merge_analysis_assumptions",
    "merge_analysis_checks",
    "normalize_analysis_key",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_expression",
    "normalize_field_path",
    "normalize_float",
    "normalize_json_value",
    "normalize_metadata",
    "normalize_non_negative_float",
    "normalize_object_kind_value",
    "normalize_optional_analysis_key",
    "normalize_optional_expression",
    "normalize_optional_field_path",
    "normalize_optional_float",
    "normalize_optional_non_negative_float",
    "normalize_optional_positive_float",
    "normalize_optional_unit_value",
    "normalize_optional_vector3",
    "normalize_positive_float",
    "normalize_typed_value",
    "normalize_vector3",
    "parse_check_scope_value",
    "parse_check_severity_value",
    "parse_load_case_kind_value",
    "parse_parameter_source_value",
    "parse_profile_status_value",
    "parse_reinforcement_placement_mode_value",
    "parse_reinforcement_system_kind_value",
    "parse_routing_connector_kind_value",
    "parse_routing_system_kind_value",
    "parse_statics_system_kind_value",
    "parse_validation_policy_value",
    "parse_value_type_value",
    "validate_reinforcement_profile_document",
    "validate_routing_profile_document",
    "validate_statics_profile_document",
]