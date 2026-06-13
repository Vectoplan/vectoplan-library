# services/vectoplan-library/src/vplib/planning/module_planner.py
"""
Module planner for the VPLIB package engine.

Diese Datei plant die aktiven VPLIB-Module für ein Package.

Rolle dieser Datei:

    CreateRequest
    + ObjectKindProfile
    + ModulePlanningOptions
    -> ModulePlanningResult
    -> ModulePlan

Diese Datei schreibt keine Dateien und erzeugt keine Dokumentinhalte. Sie
entscheidet nur, welche Module aktiv, required, recommended, optional oder
excluded sind.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


MODULE_PLANNER_SCHEMA_VERSION: Final[str] = "vplib.module_planner.v1"


class ModulePlannerError(ValueError):
    """Wird ausgelöst, wenn Module nicht geplant werden können."""


class ModuleDecisionAction(str, Enum):
    """Aktion einer Modulentscheidung."""

    ACTIVATE = "activate"
    REQUIRE = "require"
    RECOMMEND = "recommend"
    OPTIONAL = "optional"
    EXCLUDE = "exclude"

    @property
    def key(self) -> str:
        return str(self.value)


class ModuleDecisionSource(str, Enum):
    """Quelle einer Modulentscheidung."""

    CORE = "core"
    PROFILE = "profile"
    REQUEST = "request"
    REQUEST_FEATURES = "request_features"
    OPTIONS = "options"
    DEPENDENCY = "dependency"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ModulePlanningOptions:
    """Optionen für die Modulplanung."""

    include_docs: bool = False
    include_tests: bool = False
    activate_inferred_modules: bool = True
    activate_recommended_modules: bool = True
    strict: bool = True
    force_modules: tuple[str, ...] = field(default_factory=tuple)
    require_modules: tuple[str, ...] = field(default_factory=tuple)
    recommend_modules: tuple[str, ...] = field(default_factory=tuple)
    optional_modules: tuple[str, ...] = field(default_factory=tuple)
    exclude_modules: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "ModulePlanningOptions":
        return ModulePlanningOptions(
            include_docs=bool(self.include_docs),
            include_tests=bool(self.include_tests),
            activate_inferred_modules=bool(self.activate_inferred_modules),
            activate_recommended_modules=bool(self.activate_recommended_modules),
            strict=bool(self.strict),
            force_modules=normalize_module_tuple(self.force_modules),
            require_modules=normalize_module_tuple(self.require_modules),
            recommend_modules=normalize_module_tuple(self.recommend_modules),
            optional_modules=normalize_module_tuple(self.optional_modules),
            exclude_modules=normalize_module_tuple(self.exclude_modules),
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "include_docs": normalized.include_docs,
            "include_tests": normalized.include_tests,
            "activate_inferred_modules": normalized.activate_inferred_modules,
            "activate_recommended_modules": normalized.activate_recommended_modules,
            "strict": normalized.strict,
            "force_modules": list(normalized.force_modules),
            "require_modules": list(normalized.require_modules),
            "recommend_modules": list(normalized.recommend_modules),
            "optional_modules": list(normalized.optional_modules),
            "exclude_modules": list(normalized.exclude_modules),
        }


@dataclass(frozen=True, slots=True)
class ModulePlanningDecision:
    """Einzelne Modulentscheidung."""

    module_name: str
    action: str
    source: str
    reason: str = ""
    priority: int = 100
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ModulePlanningDecision":
        module_name = normalize_module_name(self.module_name)
        action = parse_decision_action_value(self.action)
        source = parse_decision_source_value(self.source)
        reason = clean_optional_string(self.reason) or ""
        priority = normalize_int(self.priority, "priority")
        metadata = normalize_metadata(self.metadata)

        return ModulePlanningDecision(
            module_name=module_name,
            action=action,
            source=source,
            reason=reason,
            priority=priority,
            metadata=metadata,
        )

    @property
    def activates_module(self) -> bool:
        return self.normalized().action in {
            ModuleDecisionAction.ACTIVATE.value,
            ModuleDecisionAction.REQUIRE.value,
            ModuleDecisionAction.RECOMMEND.value,
        }

    @property
    def excludes_module(self) -> bool:
        return self.normalized().action == ModuleDecisionAction.EXCLUDE.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "module_name": normalized.module_name,
            "action": normalized.action,
            "source": normalized.source,
            "reason": normalized.reason,
            "priority": normalized.priority,
            "metadata": dict(normalized.metadata),
        }


@dataclass(frozen=True, slots=True)
class ModulePlanningResult:
    """Ergebnis der Modulplanung."""

    module_plan: Any
    decisions: tuple[ModulePlanningDecision, ...] = field(default_factory=tuple)
    options: ModulePlanningOptions = field(default_factory=ModulePlanningOptions)
    object_kind: str | None = None
    profile_key: str | None = None
    schema_version: str = MODULE_PLANNER_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ModulePlanningResult":
        module_plan = normalize_module_plan(self.module_plan)
        decisions = tuple(
            decision.normalized()
            for decision in self.decisions or ()
        )
        decisions = sort_decisions(dedupe_decisions(decisions))
        options = self.options.normalized()
        object_kind = (
            normalize_object_kind_value(self.object_kind)
            if self.object_kind is not None
            else module_plan.object_kind
        )
        profile_key = clean_optional_string(self.profile_key) or module_plan.profile_key
        metadata = normalize_metadata(self.metadata)

        return ModulePlanningResult(
            module_plan=module_plan,
            decisions=decisions,
            options=options,
            object_kind=object_kind,
            profile_key=profile_key,
            schema_version=self.schema_version or MODULE_PLANNER_SCHEMA_VERSION,
            metadata=metadata,
        )

    @property
    def active_module_names(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.active_module_names)

    @property
    def required_module_names(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.required_module_names)

    @property
    def optional_module_names(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.optional_module_names)

    @property
    def excluded_module_names(self) -> tuple[str, ...]:
        return tuple(self.normalized().module_plan.excluded_module_names)

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "object_kind": normalized.object_kind,
            "profile_key": normalized.profile_key,
            "active_modules": list(normalized.active_module_names),
            "required_modules": list(normalized.required_module_names),
            "optional_modules": list(normalized.optional_module_names),
            "excluded_modules": list(normalized.excluded_module_names),
            "module_plan": normalized.module_plan.to_dict(),
            "decisions": [decision.to_dict() for decision in normalized.decisions],
            "options": normalized.options.to_dict(),
            "metadata": dict(normalized.metadata),
        }


def plan_modules_for_request(
    *,
    request: Any,
    profile: Any | None = None,
    options: ModulePlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ModulePlanningResult:
    """
    Plant Module für einen CreateRequest.

    Dies ist der bevorzugte Einstieg für die Modulplanung.
    """
    try:
        normalized_request = normalize_create_request(request)
        normalized_options = normalize_options(options, request=normalized_request)
        resolved_profile = (
            normalize_profile(profile)
            if profile is not None
            else resolve_profile_for_object_kind(normalized_request.object_kind)
        )

        decisions = collect_module_decisions(
            request=normalized_request,
            profile=resolved_profile,
            options=normalized_options,
        )

        module_plan = build_module_plan_from_decisions(
            request=normalized_request,
            profile=resolved_profile,
            decisions=decisions,
            options=normalized_options,
            metadata=metadata,
        )

        return ModulePlanningResult(
            module_plan=module_plan,
            decisions=decisions,
            options=normalized_options,
            object_kind=normalized_request.object_kind,
            profile_key=resolved_profile.profile_key,
            metadata={
                "planned_by": "module_planner",
                **dict(metadata or {}),
            },
        ).normalized()
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Could not plan modules for request: {exc}") from exc


def plan_modules_for_profile(
    *,
    object_kind: Any,
    profile: Any | None = None,
    options: ModulePlanningOptions | Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ModulePlanningResult:
    """
    Plant Module nur aus object_kind/profile heraus.

    Nützlich für Tests, Profile-Preview und Admin-Diagnose.
    """
    try:
        object_kind_value = normalize_object_kind_value(object_kind)
        resolved_profile = (
            normalize_profile(profile)
            if profile is not None
            else resolve_profile_for_object_kind(object_kind_value)
        )
        normalized_options = normalize_options(options)

        decisions = collect_profile_decisions(resolved_profile)
        decisions = (
            *decisions,
            *collect_option_decisions(normalized_options),
        )

        module_plan = build_module_plan_from_decisions(
            request=None,
            profile=resolved_profile,
            decisions=decisions,
            options=normalized_options,
            metadata=metadata,
        )

        return ModulePlanningResult(
            module_plan=module_plan,
            decisions=decisions,
            options=normalized_options,
            object_kind=object_kind_value,
            profile_key=resolved_profile.profile_key,
            metadata={
                "planned_by": "module_planner",
                "request_present": False,
                **dict(metadata or {}),
            },
        ).normalized()
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Could not plan modules for profile: {exc}") from exc


def collect_module_decisions(
    *,
    request: Any,
    profile: Any,
    options: ModulePlanningOptions,
) -> tuple[ModulePlanningDecision, ...]:
    """Sammelt alle Modulentscheidungen."""
    decisions: list[ModulePlanningDecision] = []

    decisions.extend(collect_profile_decisions(profile))
    decisions.extend(collect_request_feature_decisions(request, options=options))
    decisions.extend(collect_option_decisions(options))
    decisions.extend(collect_dependency_decisions(decisions))

    return sort_decisions(dedupe_decisions(decisions))


def collect_profile_decisions(profile: Any) -> tuple[ModulePlanningDecision, ...]:
    """Sammelt Entscheidungen aus einem ObjectKindProfile."""
    normalized_profile = normalize_profile(profile)
    decisions: list[ModulePlanningDecision] = []

    for rule in normalized_profile.module_rules:
        action = {
            "required": ModuleDecisionAction.REQUIRE.value,
            "recommended": ModuleDecisionAction.RECOMMEND.value,
            "optional": ModuleDecisionAction.OPTIONAL.value,
            "excluded": ModuleDecisionAction.EXCLUDE.value,
        }.get(rule.requirement, ModuleDecisionAction.OPTIONAL.value)

        decisions.append(
            ModulePlanningDecision(
                module_name=rule.module_name,
                action=action,
                source=ModuleDecisionSource.PROFILE.value,
                reason=rule.reason or f"Configured by profile {normalized_profile.profile_key}.",
                priority=profile_decision_priority(action),
                metadata={
                    "profile_key": normalized_profile.profile_key,
                    "active_by_default": rule.active_by_default,
                },
            ).normalized()
        )

    return tuple(decisions)


def collect_request_feature_decisions(
    request: Any,
    *,
    options: ModulePlanningOptions,
) -> tuple[ModulePlanningDecision, ...]:
    """
    Sammelt Entscheidungen aus tatsächlich vorhandenen Request-Daten.

    Beispiele:
    - GLB/Textur/Preview -> render
    - physical values -> physical
    - material values -> material
    - calculation payload -> calculation
    - dynamic payload -> dynamic
    - manufacturer overlay data -> manufacturer
    """
    normalized_request = normalize_create_request(request)
    normalized_options = options.normalized()

    if not normalized_options.activate_inferred_modules:
        return tuple()

    decisions: list[ModulePlanningDecision] = []

    if request_has_visual_data(normalized_request):
        decisions.append(
            feature_decision(
                "render",
                "Visual data requires the render module.",
                {"feature": "visual"},
            )
        )

    if request_has_asset_data(normalized_request):
        decisions.append(
            feature_decision(
                "render",
                "Assets require the render module.",
                {"feature": "assets"},
            )
        )

    if request_has_physical_data(normalized_request):
        decisions.append(
            feature_decision(
                "physical",
                "Physical values require the physical module.",
                {"feature": "physical"},
            )
        )

    if request_has_material_data(normalized_request):
        decisions.append(
            feature_decision(
                "material",
                "Material values require the material module.",
                {"feature": "material"},
            )
        )

    if request_has_calculation_data(normalized_request):
        decisions.append(
            feature_decision(
                "calculation",
                "Calculation values require the calculation module.",
                {"feature": "calculation"},
            )
        )

    if request_has_dynamic_data(normalized_request):
        decisions.append(
            feature_decision(
                "dynamic",
                "Dynamic values require the dynamic module.",
                {"feature": "dynamic"},
            )
        )

    if request_has_manufacturer_data(normalized_request):
        decisions.append(
            feature_decision(
                "manufacturer",
                "Manufacturer values require the manufacturer module.",
                {"feature": "manufacturer"},
            )
        )

    if normalized_request.options.include_docs:
        decisions.append(
            ModulePlanningDecision(
                module_name="docs",
                action=ModuleDecisionAction.ACTIVATE.value,
                source=ModuleDecisionSource.REQUEST.value,
                reason="Request options include docs.",
                priority=60,
            ).normalized()
        )

    if normalized_request.options.include_tests:
        decisions.append(
            ModulePlanningDecision(
                module_name="tests",
                action=ModuleDecisionAction.ACTIVATE.value,
                source=ModuleDecisionSource.REQUEST.value,
                reason="Request options include tests.",
                priority=60,
            ).normalized()
        )

    return tuple(decisions)


def collect_option_decisions(
    options: ModulePlanningOptions,
) -> tuple[ModulePlanningDecision, ...]:
    """Sammelt Entscheidungen aus expliziten Planner-Optionen."""
    normalized = options.normalized()
    decisions: list[ModulePlanningDecision] = []

    for module_name in normalized.force_modules:
        decisions.append(
            ModulePlanningDecision(
                module_name=module_name,
                action=ModuleDecisionAction.ACTIVATE.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Module forced by planning options.",
                priority=70,
            ).normalized()
        )

    for module_name in normalized.require_modules:
        decisions.append(
            ModulePlanningDecision(
                module_name=module_name,
                action=ModuleDecisionAction.REQUIRE.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Module required by planning options.",
                priority=90,
            ).normalized()
        )

    for module_name in normalized.recommend_modules:
        decisions.append(
            ModulePlanningDecision(
                module_name=module_name,
                action=ModuleDecisionAction.RECOMMEND.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Module recommended by planning options.",
                priority=50,
            ).normalized()
        )

    for module_name in normalized.optional_modules:
        decisions.append(
            ModulePlanningDecision(
                module_name=module_name,
                action=ModuleDecisionAction.OPTIONAL.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Module marked optional by planning options.",
                priority=30,
            ).normalized()
        )

    for module_name in normalized.exclude_modules:
        decisions.append(
            ModulePlanningDecision(
                module_name=module_name,
                action=ModuleDecisionAction.EXCLUDE.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Module excluded by planning options.",
                priority=100,
            ).normalized()
        )

    if normalized.include_docs:
        decisions.append(
            ModulePlanningDecision(
                module_name="docs",
                action=ModuleDecisionAction.ACTIVATE.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Docs requested by planning options.",
                priority=60,
            ).normalized()
        )

    if normalized.include_tests:
        decisions.append(
            ModulePlanningDecision(
                module_name="tests",
                action=ModuleDecisionAction.ACTIVATE.value,
                source=ModuleDecisionSource.OPTIONS.value,
                reason="Tests requested by planning options.",
                priority=60,
            ).normalized()
        )

    return tuple(decisions)


def collect_dependency_decisions(
    decisions: Iterable[ModulePlanningDecision],
) -> tuple[ModulePlanningDecision, ...]:
    """Sammelt zusätzliche Entscheidungen aus Modulabhängigkeiten."""
    result: list[ModulePlanningDecision] = []
    active_module_names = {
        decision.module_name
        for decision in dedupe_decisions(decisions)
        if decision.activates_module
    }

    for module_name in tuple(active_module_names):
        for dependency in get_module_dependencies_safe(module_name):
            if dependency in active_module_names:
                continue

            result.append(
                ModulePlanningDecision(
                    module_name=dependency,
                    action=ModuleDecisionAction.REQUIRE.value,
                    source=ModuleDecisionSource.DEPENDENCY.value,
                    reason=f"Dependency of module {module_name}.",
                    priority=85,
                ).normalized()
            )
            active_module_names.add(dependency)

    return tuple(result)


def build_module_plan_from_decisions(
    *,
    request: Any | None,
    profile: Any,
    decisions: Iterable[ModulePlanningDecision],
    options: ModulePlanningOptions,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Baut ein ModulePlan-Modell aus Entscheidungen."""
    try:
        from ..models.module_plan import (
            ModuleActivationSource,
            ModulePlan,
            ModulePlanEntry,
            ModuleRequirementLevel,
        )

        normalized_profile = normalize_profile(profile)
        normalized_options = options.normalized()
        normalized_decisions = sort_decisions(dedupe_decisions(decisions))

        entries: list[Any] = []

        for decision in normalized_decisions:
            if decision.action == ModuleDecisionAction.EXCLUDE.value:
                requirement = ModuleRequirementLevel.EXCLUDED.value
                active = False
            elif decision.action == ModuleDecisionAction.REQUIRE.value:
                requirement = ModuleRequirementLevel.REQUIRED.value
                active = True
            elif decision.action == ModuleDecisionAction.RECOMMEND.value:
                requirement = ModuleRequirementLevel.RECOMMENDED.value
                active = normalized_options.activate_recommended_modules
            elif decision.action == ModuleDecisionAction.ACTIVATE.value:
                requirement = ModuleRequirementLevel.OPTIONAL.value
                active = True
            else:
                requirement = ModuleRequirementLevel.OPTIONAL.value
                active = False

            entries.append(
                ModulePlanEntry(
                    module_name=decision.module_name,
                    active=active,
                    requirement=requirement,
                    source=map_decision_source_to_module_source(decision.source),
                    reason=decision.reason,
                ).normalized()
            )

        object_kind = (
            normalize_create_request(request).object_kind
            if request is not None
            else normalized_profile.object_kind
        )

        return ModulePlan(
            entries=tuple(entries),
            object_kind=object_kind,
            profile_key=normalized_profile.profile_key,
            metadata={
                "planned_by": "module_planner",
                "decision_count": len(normalized_decisions),
                **dict(metadata or {}),
            },
        ).normalized()
    except Exception as exc:
        raise ModulePlannerError(f"Could not build ModulePlan from decisions: {exc}") from exc


def map_decision_source_to_module_source(source: str) -> str:
    """Mappt Planner-Decision-Source auf ModulePlan-Activation-Source."""
    try:
        from ..models.module_plan import ModuleActivationSource

        source_value = parse_decision_source_value(source)

        mapping = {
            ModuleDecisionSource.CORE.value: ModuleActivationSource.CORE.value,
            ModuleDecisionSource.PROFILE.value: ModuleActivationSource.PROFILE.value,
            ModuleDecisionSource.REQUEST.value: ModuleActivationSource.USER_REQUEST.value,
            ModuleDecisionSource.REQUEST_FEATURES.value: ModuleActivationSource.USER_REQUEST.value,
            ModuleDecisionSource.OPTIONS.value: ModuleActivationSource.USER_REQUEST.value,
            ModuleDecisionSource.DEPENDENCY.value: ModuleActivationSource.DEPENDENCY.value,
            ModuleDecisionSource.SYSTEM.value: ModuleActivationSource.SYSTEM.value,
        }

        return mapping.get(source_value, ModuleActivationSource.SYSTEM.value)
    except Exception:
        return "system"


def feature_decision(
    module_name: str,
    reason: str,
    metadata: Mapping[str, Any] | None = None,
) -> ModulePlanningDecision:
    """Factory für request-feature-basierte Entscheidungen."""
    return ModulePlanningDecision(
        module_name=module_name,
        action=ModuleDecisionAction.ACTIVATE.value,
        source=ModuleDecisionSource.REQUEST_FEATURES.value,
        reason=reason,
        priority=65,
        metadata=dict(metadata or {}),
    ).normalized()


def request_has_visual_data(request: Any) -> bool:
    """Prüft, ob Request sichtbare Renderdaten enthält."""
    visual = getattr(request, "visual", None)
    if visual is None:
        return False

    return any(
        bool(getattr(visual, attribute, None))
        for attribute in (
            "texture_ref",
            "glb_ref",
            "model_ref",
            "icon_ref",
            "preview_ref",
            "fallback_color",
            "model_bounds_m",
        )
    )


def request_has_asset_data(request: Any) -> bool:
    """Prüft, ob Request Assets enthält."""
    return bool(getattr(request, "assets", ()))


def request_has_physical_data(request: Any) -> bool:
    """Prüft, ob Request physische Daten enthält."""
    physical = getattr(request, "physical", None)
    if physical is None:
        return False

    return any(
        getattr(physical, attribute, None) is not None
        for attribute in (
            "real_width_m",
            "real_height_m",
            "real_depth_m",
            "wall_thickness_m",
            "volume_m3",
            "mass_kg",
            "density_kg_m3",
            "raw_density_kg_m3",
            "load_bearing",
            "fire_class",
        )
    )


def request_has_material_data(request: Any) -> bool:
    """Prüft, ob Request Materialdaten enthält."""
    material = getattr(request, "material", None)
    if material is None:
        return False

    return any(
        getattr(material, attribute, None) is not None
        for attribute in (
            "material_id",
            "material_class",
            "material_name",
            "surface_finish",
            "thermal_conductivity",
            "u_value",
            "compressive_strength",
        )
    )


def request_has_calculation_data(request: Any) -> bool:
    """Prüft, ob Request Berechnungsdaten enthält."""
    calculation = getattr(request, "calculation", None)
    if calculation is None:
        return False

    return any(
        bool(getattr(calculation, attribute, None))
        for attribute in (
            "variables",
            "formulas",
            "quantities",
            "constraints",
            "measure_logic",
        )
    )


def request_has_dynamic_data(request: Any) -> bool:
    """Prüft, ob Request dynamische/adaptive Daten enthält."""
    dynamic = getattr(request, "dynamic", None)
    if dynamic is None:
        return False

    return any(
        bool(getattr(dynamic, attribute, None))
        for attribute in (
            "context_rules",
            "bindings",
            "generator",
            "parameters",
        )
    )


def request_has_manufacturer_data(request: Any) -> bool:
    """Prüft, ob Request Herstellerdaten enthält."""
    manufacturer = getattr(request, "manufacturer", None)
    if manufacturer is None:
        return False

    return bool(
        getattr(manufacturer, "manufacturer_allowed", False)
        or getattr(manufacturer, "override_slots", ())
        or getattr(manufacturer, "required_product_fields", ())
        or getattr(manufacturer, "product_categories", ())
    )


def dedupe_decisions(
    decisions: Iterable[ModulePlanningDecision],
) -> tuple[ModulePlanningDecision, ...]:
    """
    Dedupliziert Entscheidungen.

    Pro Modul gewinnt die Entscheidung mit der höchsten Priorität. Bei gleicher
    Priorität gewinnt die strengere Aktion.
    """
    by_module: dict[str, ModulePlanningDecision] = {}

    for decision in decisions or ():
        normalized = decision.normalized()
        existing = by_module.get(normalized.module_name)

        if existing is None:
            by_module[normalized.module_name] = normalized
            continue

        by_module[normalized.module_name] = stronger_decision(existing, normalized)

    return tuple(by_module.values())


def stronger_decision(
    left: ModulePlanningDecision,
    right: ModulePlanningDecision,
) -> ModulePlanningDecision:
    """Ermittelt die stärkere von zwei Entscheidungen für dasselbe Modul."""
    left_normalized = left.normalized()
    right_normalized = right.normalized()

    if left_normalized.module_name != right_normalized.module_name:
        raise ModulePlannerError(
            f"Cannot compare decisions for different modules: "
            f"{left_normalized.module_name!r}, {right_normalized.module_name!r}."
        )

    if right_normalized.priority > left_normalized.priority:
        return right_normalized

    if right_normalized.priority < left_normalized.priority:
        return left_normalized

    action_rank = {
        ModuleDecisionAction.OPTIONAL.value: 10,
        ModuleDecisionAction.ACTIVATE.value: 20,
        ModuleDecisionAction.RECOMMEND.value: 30,
        ModuleDecisionAction.REQUIRE.value: 40,
        ModuleDecisionAction.EXCLUDE.value: 50,
    }

    if action_rank[right_normalized.action] > action_rank[left_normalized.action]:
        return right_normalized

    return left_normalized


def sort_decisions(
    decisions: Iterable[ModulePlanningDecision],
) -> tuple[ModulePlanningDecision, ...]:
    """Sortiert Entscheidungen stabil."""
    return tuple(
        sorted(
            (decision.normalized() for decision in decisions or ()),
            key=lambda decision: (
                -decision.priority,
                get_module_order_safe(decision.module_name),
                decision.module_name,
            ),
        )
    )


def profile_decision_priority(action: str) -> int:
    """Priorität für Profilentscheidungen."""
    action_value = parse_decision_action_value(action)

    return {
        ModuleDecisionAction.EXCLUDE.value: 100,
        ModuleDecisionAction.REQUIRE.value: 90,
        ModuleDecisionAction.RECOMMEND.value: 50,
        ModuleDecisionAction.ACTIVATE.value: 60,
        ModuleDecisionAction.OPTIONAL.value: 20,
    }.get(action_value, 20)


def normalize_options(
    options: ModulePlanningOptions | Mapping[str, Any] | None,
    *,
    request: Any | None = None,
) -> ModulePlanningOptions:
    """Normalisiert Planning Options."""
    try:
        if options is None:
            if request is None:
                return ModulePlanningOptions().normalized()

            normalized_request = normalize_create_request(request)
            return ModulePlanningOptions(
                include_docs=normalized_request.options.include_docs,
                include_tests=normalized_request.options.include_tests,
                strict=normalized_request.options.strict,
            ).normalized()

        if isinstance(options, ModulePlanningOptions):
            return options.normalized()

        if isinstance(options, Mapping):
            return ModulePlanningOptions(
                include_docs=bool(options.get("include_docs", False)),
                include_tests=bool(options.get("include_tests", False)),
                activate_inferred_modules=bool(options.get("activate_inferred_modules", True)),
                activate_recommended_modules=bool(options.get("activate_recommended_modules", True)),
                strict=bool(options.get("strict", True)),
                force_modules=tuple(options.get("force_modules", ()) or ()),
                require_modules=tuple(options.get("require_modules", ()) or ()),
                recommend_modules=tuple(options.get("recommend_modules", ()) or ()),
                optional_modules=tuple(options.get("optional_modules", ()) or ()),
                exclude_modules=tuple(options.get("exclude_modules", ()) or ()),
            ).normalized()

        raise ModulePlannerError("options must be ModulePlanningOptions, mapping or None.")
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Invalid module planning options: {exc}") from exc


def normalize_create_request(value: Any) -> Any:
    """Normalisiert einen CreateRequest."""
    try:
        from ..models.create_request import CreateRequest, create_request_from_mapping

        if isinstance(value, CreateRequest):
            return value.normalized()

        if isinstance(value, Mapping):
            return create_request_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise ModulePlannerError("CreateRequest value is required.")
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Invalid CreateRequest: {exc}") from exc


def normalize_profile(value: Any) -> Any:
    """Normalisiert ein ObjectKindProfile."""
    try:
        from ..profiles.base_profiles import ObjectKindProfile

        if isinstance(value, ObjectKindProfile):
            return value.normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise ModulePlannerError("ObjectKindProfile value is required.")
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Invalid ObjectKindProfile: {exc}") from exc


def normalize_module_plan(value: Any) -> Any:
    """Normalisiert einen ModulePlan."""
    try:
        from ..models.module_plan import ModulePlan, module_plan_from_mapping

        if isinstance(value, ModulePlan):
            return value.normalized()

        if isinstance(value, Mapping):
            return module_plan_from_mapping(value).normalized()

        if hasattr(value, "normalized") and callable(value.normalized):
            return value.normalized()

        raise ModulePlannerError("ModulePlan value is required.")
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Invalid ModulePlan: {exc}") from exc


def resolve_profile_for_object_kind(object_kind: Any) -> Any:
    """Löst Profil für eine Objektart."""
    try:
        from ..profiles.profile_resolver import resolve_profile

        return resolve_profile(object_kind).normalized()
    except Exception as exc:
        raise ModulePlannerError(f"Could not resolve profile: {exc}") from exc


def normalize_module_name(value: Any) -> str:
    """Normalisiert einen Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise ModulePlannerError(f"Invalid module name {value!r}: {exc}") from exc


def normalize_module_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert mehrere Modulnamen ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        module_name = normalize_module_name(value)
        if module_name in seen:
            continue
        result.append(module_name)
        seen.add(module_name)

    return tuple(result)


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise ModulePlannerError(f"Invalid object_kind {value!r}: {exc}") from exc


def get_module_dependencies_safe(module_name: Any) -> tuple[str, ...]:
    """Liest Modulabhängigkeiten robust."""
    try:
        from ..domain.module_names import module_dependencies

        return tuple(module.value for module in module_dependencies(module_name))
    except Exception:
        return tuple()


def get_module_order_safe(module_name: Any) -> int:
    """Stabile Modulsortierung."""
    order = {
        "manifest": 10,
        "modules": 20,
        "family": 30,
        "variants": 40,
        "editor": 50,
        "render": 60,
        "physical": 70,
        "material": 80,
        "calculation": 90,
        "analysis": 100,
        "dynamic": 110,
        "manufacturer": 120,
        "docs": 130,
        "tests": 140,
    }

    try:
        return order.get(normalize_module_name(module_name), 999)
    except Exception:
        return 999


@lru_cache(maxsize=128)
def parse_decision_action_value(value: Any) -> str:
    """Parst ModuleDecisionAction."""
    try:
        if isinstance(value, ModuleDecisionAction):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "activate": ModuleDecisionAction.ACTIVATE.value,
            "active": ModuleDecisionAction.ACTIVATE.value,
            "enable": ModuleDecisionAction.ACTIVATE.value,
            "require": ModuleDecisionAction.REQUIRE.value,
            "required": ModuleDecisionAction.REQUIRE.value,
            "mandatory": ModuleDecisionAction.REQUIRE.value,
            "recommend": ModuleDecisionAction.RECOMMEND.value,
            "recommended": ModuleDecisionAction.RECOMMEND.value,
            "optional": ModuleDecisionAction.OPTIONAL.value,
            "exclude": ModuleDecisionAction.EXCLUDE.value,
            "excluded": ModuleDecisionAction.EXCLUDE.value,
            "disable": ModuleDecisionAction.EXCLUDE.value,
            "disabled": ModuleDecisionAction.EXCLUDE.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ModuleDecisionAction(raw).value
    except Exception as exc:
        raise ModulePlannerError(f"Invalid module decision action {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_decision_source_value(value: Any) -> str:
    """Parst ModuleDecisionSource."""
    try:
        if isinstance(value, ModuleDecisionSource):
            return value.value

        raw = normalize_enum_key(value)
        return ModuleDecisionSource(raw).value
    except Exception as exc:
        raise ModulePlannerError(f"Invalid module decision source {value!r}.") from exc


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ModulePlannerError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"Invalid enum value {value!r}.") from exc


def normalize_int(value: Any, field_name: str) -> int:
    """Normalisiert einen Integer."""
    try:
        if isinstance(value, bool):
            raise ModulePlannerError(f"{field_name} must be an integer.")

        return int(value)
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"{field_name} must be an integer.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ModulePlannerError(f"{field_name} is required.")

        return cleaned
    except ModulePlannerError:
        raise
    except Exception as exc:
        raise ModulePlannerError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
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
        raise ModulePlannerError("metadata must be a mapping.")

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


def clear_module_planner_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_decision_action_value.cache_clear()
    parse_decision_source_value.cache_clear()


__all__ = [
    "MODULE_PLANNER_SCHEMA_VERSION",
    "ModuleDecisionAction",
    "ModuleDecisionSource",
    "ModulePlannerError",
    "ModulePlanningDecision",
    "ModulePlanningOptions",
    "ModulePlanningResult",
    "build_module_plan_from_decisions",
    "clean_optional_string",
    "clean_required_string",
    "clear_module_planner_caches",
    "collect_dependency_decisions",
    "collect_module_decisions",
    "collect_option_decisions",
    "collect_profile_decisions",
    "collect_request_feature_decisions",
    "dedupe_decisions",
    "feature_decision",
    "get_module_dependencies_safe",
    "get_module_order_safe",
    "map_decision_source_to_module_source",
    "normalize_create_request",
    "normalize_enum_key",
    "normalize_int",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_module_name",
    "normalize_module_plan",
    "normalize_module_tuple",
    "normalize_object_kind_value",
    "normalize_options",
    "normalize_profile",
    "parse_decision_action_value",
    "parse_decision_source_value",
    "plan_modules_for_profile",
    "plan_modules_for_request",
    "profile_decision_priority",
    "request_has_asset_data",
    "request_has_calculation_data",
    "request_has_dynamic_data",
    "request_has_manufacturer_data",
    "request_has_material_data",
    "request_has_physical_data",
    "request_has_visual_data",
    "resolve_profile_for_object_kind",
    "sort_decisions",
    "stronger_decision",
]