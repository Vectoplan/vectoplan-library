# services/vectoplan-library/src/vplib/profiles/base_profiles.py
"""
Base profile definitions for the VPLIB package engine.

Diese Datei definiert die gemeinsame Profil-Grundlage für alle VPLIB-Objektarten.

Ein ObjectKindProfile beschreibt:
- welche Module für eine Objektart aktiv sind
- welche Module required/recommended/optional/excluded sind
- welche Dateien zusätzlich erwartet werden
- welche Assets erlaubt oder empfohlen sind
- welche Validierungsregeln beim Erstellen gelten
- welche Defaults für neue Packages gelten

Diese Datei ist bewusst generisch. Die konkreten Profile kommen danach in:
- cell_block_profile.py
- multi_cell_module_profile.py
- catalog_object_profile.py
- adaptive_system_profile.py

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping


BASE_PROFILE_SCHEMA_VERSION: Final[str] = "vplib.profile.base.v1"

BASE_PROFILE_KEY: Final[str] = "base"
DEFAULT_SCHEMA_VERSION: Final[str] = "vplib.v1"
DEFAULT_MANUFACTURER_OVERLAY_LEVEL: Final[str] = "none"

CORE_REQUIRED_MODULES: Final[tuple[str, ...]] = (
    "manifest",
    "modules",
    "family",
    "variants",
    "editor",
    "manufacturer",
)

BASE_RECOMMENDED_MODULES: Final[tuple[str, ...]] = (
    "render",
    "physical",
)

BASE_OPTIONAL_MODULES: Final[tuple[str, ...]] = (
    "material",
    "calculation",
    "analysis",
    "dynamic",
    "docs",
    "tests",
)

BASE_FORBIDDEN_MODULES: Final[tuple[str, ...]] = tuple()


class ProfileError(ValueError):
    """Wird ausgelöst, wenn ein VPLIB-Profil ungültig ist."""


class ProfileModuleRequirement(str, Enum):
    """Anforderungsstatus eines Moduls im Profil."""

    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"

    @property
    def key(self) -> str:
        return str(self.value)


class ProfileRuleSeverity(str, Enum):
    """Schweregrad einer Profilregel."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"

    @property
    def key(self) -> str:
        return str(self.value)


class ProfileRuleScope(str, Enum):
    """Gültigkeitsbereich einer Profilregel."""

    PROFILE = "profile"
    MODULE = "module"
    DOCUMENT = "document"
    ASSET = "asset"
    VARIANT = "variant"
    PLACEMENT = "placement"
    RENDER = "render"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    DYNAMIC = "dynamic"
    MANUFACTURER = "manufacturer"

    @property
    def key(self) -> str:
        return str(self.value)


class ProfileAssetPolicy(str, Enum):
    """Asset-Policy für ein Profil."""

    NOT_ALLOWED = "not_allowed"
    OPTIONAL = "optional"
    RECOMMENDED = "recommended"
    REQUIRED = "required"

    @property
    def key(self) -> str:
        return str(self.value)


class ProfileValidationMode(str, Enum):
    """Validierungsmodus für ein Profil."""

    STRICT = "strict"
    NORMAL = "normal"
    PERMISSIVE = "permissive"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ProfileModuleRule:
    """Regel für ein einzelnes VPLIB-Modul innerhalb eines Profils."""

    module_name: str
    requirement: str = ProfileModuleRequirement.OPTIONAL.value
    active_by_default: bool = False
    reason: str = ""
    required_files: tuple[str, ...] = field(default_factory=tuple)
    optional_files: tuple[str, ...] = field(default_factory=tuple)
    generated_files: tuple[str, ...] = field(default_factory=tuple)
    allowed_subdirectories: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "ProfileModuleRule":
        module_name = normalize_module_name(self.module_name)
        requirement = parse_profile_module_requirement_value(self.requirement)
        active_by_default = bool(self.active_by_default)
        reason = clean_optional_string(self.reason) or ""
        required_files = normalize_package_path_tuple(self.required_files)
        optional_files = normalize_package_path_tuple(self.optional_files)
        generated_files = normalize_package_path_tuple(self.generated_files)
        allowed_subdirectories = normalize_package_path_tuple(self.allowed_subdirectories)

        if requirement == ProfileModuleRequirement.REQUIRED.value:
            active_by_default = True

        if requirement == ProfileModuleRequirement.EXCLUDED.value:
            active_by_default = False

        if not required_files and requirement == ProfileModuleRequirement.REQUIRED.value:
            required_files = get_required_files_for_module_safe(module_name)

        if not optional_files:
            optional_files = get_optional_files_for_module_safe(module_name)

        if not generated_files:
            generated_files = get_generated_files_for_module_safe(module_name)

        if not allowed_subdirectories:
            allowed_subdirectories = get_allowed_subdirectories_for_module_safe(module_name)

        return ProfileModuleRule(
            module_name=module_name,
            requirement=requirement,
            active_by_default=active_by_default,
            reason=reason,
            required_files=required_files,
            optional_files=optional_files,
            generated_files=generated_files,
            allowed_subdirectories=allowed_subdirectories,
        )

    @property
    def is_required(self) -> bool:
        return self.normalized().requirement == ProfileModuleRequirement.REQUIRED.value

    @property
    def is_recommended(self) -> bool:
        return self.normalized().requirement == ProfileModuleRequirement.RECOMMENDED.value

    @property
    def is_optional(self) -> bool:
        return self.normalized().requirement == ProfileModuleRequirement.OPTIONAL.value

    @property
    def is_excluded(self) -> bool:
        return self.normalized().requirement == ProfileModuleRequirement.EXCLUDED.value

    @property
    def is_active(self) -> bool:
        normalized = self.normalized()
        return normalized.active_by_default and not normalized.is_excluded

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "module_name": normalized.module_name,
            "requirement": normalized.requirement,
            "active_by_default": normalized.active_by_default,
            "reason": normalized.reason,
            "required_files": list(normalized.required_files),
            "optional_files": list(normalized.optional_files),
            "generated_files": list(normalized.generated_files),
            "allowed_subdirectories": list(normalized.allowed_subdirectories),
        }


@dataclass(frozen=True, slots=True)
class ProfileDocumentRule:
    """Regel für ein einzelnes Dokument in einem Profil."""

    path: str
    module_name: str
    required: bool = False
    generated: bool = True
    allow_empty_initially: bool = True
    reason: str = ""

    def normalized(self) -> "ProfileDocumentRule":
        path = normalize_package_path(self.path)
        module_name = normalize_module_name(self.module_name)
        required = bool(self.required)
        generated = bool(self.generated)
        allow_empty_initially = bool(self.allow_empty_initially)
        reason = clean_optional_string(self.reason) or ""

        if not is_path_under_module_safe(path, module_name):
            raise ProfileError(f"Document path {path!r} is not under module {module_name!r}.")

        return ProfileDocumentRule(
            path=path,
            module_name=module_name,
            required=required,
            generated=generated,
            allow_empty_initially=allow_empty_initially,
            reason=reason,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "path": normalized.path,
            "module_name": normalized.module_name,
            "required": normalized.required,
            "generated": normalized.generated,
            "allow_empty_initially": normalized.allow_empty_initially,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class ProfileAssetRule:
    """Regel für Assets in einem Profil."""

    role: str
    policy: str = ProfileAssetPolicy.OPTIONAL.value
    module_name: str = "render"
    allowed_extensions: tuple[str, ...] = field(default_factory=tuple)
    max_size_mb: float | None = None
    requires_bounds: bool = False
    must_fit_grid_footprint: bool = True
    reason: str = ""

    def normalized(self) -> "ProfileAssetRule":
        role = normalize_asset_role_value(self.role)
        policy = parse_profile_asset_policy_value(self.policy)
        module_name = normalize_module_name(self.module_name)
        allowed_extensions = normalize_extension_tuple(self.allowed_extensions)
        max_size_mb = normalize_optional_positive_float(self.max_size_mb, "max_size_mb")
        requires_bounds = bool(self.requires_bounds)
        must_fit_grid_footprint = bool(self.must_fit_grid_footprint)
        reason = clean_optional_string(self.reason) or ""

        return ProfileAssetRule(
            role=role,
            policy=policy,
            module_name=module_name,
            allowed_extensions=allowed_extensions,
            max_size_mb=max_size_mb,
            requires_bounds=requires_bounds,
            must_fit_grid_footprint=must_fit_grid_footprint,
            reason=reason,
        )

    @property
    def is_required(self) -> bool:
        return self.normalized().policy == ProfileAssetPolicy.REQUIRED.value

    @property
    def is_allowed(self) -> bool:
        return self.normalized().policy != ProfileAssetPolicy.NOT_ALLOWED.value

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "role": normalized.role,
            "policy": normalized.policy,
            "module_name": normalized.module_name,
            "allowed_extensions": list(normalized.allowed_extensions),
            "max_size_mb": normalized.max_size_mb,
            "requires_bounds": normalized.requires_bounds,
            "must_fit_grid_footprint": normalized.must_fit_grid_footprint,
            "reason": normalized.reason,
        }


@dataclass(frozen=True, slots=True)
class ProfileValidationRule:
    """Deklarative Validierungsregel eines Profils."""

    rule_key: str
    scope: str
    severity: str = ProfileRuleSeverity.ERROR.value
    enabled: bool = True
    message: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ProfileValidationRule":
        rule_key = normalize_rule_key(self.rule_key)
        scope = parse_profile_rule_scope_value(self.scope)
        severity = parse_profile_rule_severity_value(self.severity)
        enabled = bool(self.enabled)
        message = clean_optional_string(self.message) or rule_key
        details = normalize_metadata(self.details)

        return ProfileValidationRule(
            rule_key=rule_key,
            scope=scope,
            severity=severity,
            enabled=enabled,
            message=message,
            details=details,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "rule_key": normalized.rule_key,
            "scope": normalized.scope,
            "severity": normalized.severity,
            "enabled": normalized.enabled,
            "message": normalized.message,
            "details": dict(normalized.details),
        }


@dataclass(frozen=True, slots=True)
class ProfileDefaults:
    """Defaults für neue Packages eines Profils."""

    schema_version: str = DEFAULT_SCHEMA_VERSION
    variant_mode: str = "single"
    default_variant_id: str = "default"
    placement_mode: str = "centered"
    fit_mode: str = "strict_inside"
    fallback_color: str = "#9CA3AF"
    cell_size_m: float = 1.0
    grid_size_cells: tuple[int, int, int] = (1, 1, 1)
    manufacturer_allowed: bool = False
    manufacturer_overlay_level: str = DEFAULT_MANUFACTURER_OVERLAY_LEVEL

    def normalized(self) -> "ProfileDefaults":
        schema_version = clean_required_string(self.schema_version, "schema_version")
        variant_mode = normalize_variant_mode_value(self.variant_mode)
        default_variant_id = normalize_slug_like(self.default_variant_id, "default_variant_id")
        placement_mode = normalize_placement_mode_value(self.placement_mode)
        fit_mode = clean_required_string(self.fit_mode, "fit_mode")
        fallback_color = normalize_color(self.fallback_color)
        cell_size_m = normalize_positive_float(self.cell_size_m, "cell_size_m")
        grid_size_cells = normalize_grid_size_cells(self.grid_size_cells)
        manufacturer_allowed = bool(self.manufacturer_allowed)
        manufacturer_overlay_level = clean_required_string(
            self.manufacturer_overlay_level,
            "manufacturer_overlay_level",
        )

        return ProfileDefaults(
            schema_version=schema_version,
            variant_mode=variant_mode,
            default_variant_id=default_variant_id,
            placement_mode=placement_mode,
            fit_mode=fit_mode,
            fallback_color=fallback_color,
            cell_size_m=cell_size_m,
            grid_size_cells=grid_size_cells,
            manufacturer_allowed=manufacturer_allowed,
            manufacturer_overlay_level=manufacturer_overlay_level,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "variant_mode": normalized.variant_mode,
            "default_variant_id": normalized.default_variant_id,
            "placement_mode": normalized.placement_mode,
            "fit_mode": normalized.fit_mode,
            "fallback_color": normalized.fallback_color,
            "cell_size_m": normalized.cell_size_m,
            "grid_size_cells": list(normalized.grid_size_cells),
            "manufacturer_allowed": normalized.manufacturer_allowed,
            "manufacturer_overlay_level": normalized.manufacturer_overlay_level,
        }


@dataclass(frozen=True, slots=True)
class ObjectKindProfile:
    """
    Vollständiges VPLIB-Profil für eine Objektart.

    Dieses Profil ist Datenmodell und Regelträger. Es schreibt keine Dateien.
    """

    profile_key: str
    object_kind: str
    title: str
    description: str = ""
    module_rules: tuple[ProfileModuleRule, ...] = field(default_factory=tuple)
    document_rules: tuple[ProfileDocumentRule, ...] = field(default_factory=tuple)
    asset_rules: tuple[ProfileAssetRule, ...] = field(default_factory=tuple)
    validation_rules: tuple[ProfileValidationRule, ...] = field(default_factory=tuple)
    defaults: ProfileDefaults = field(default_factory=ProfileDefaults)
    validation_mode: str = ProfileValidationMode.NORMAL.value
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ObjectKindProfile":
        profile_key = normalize_profile_key(self.profile_key)
        object_kind = normalize_object_kind_value(self.object_kind)
        title = clean_required_string(self.title, "title")
        description = clean_optional_string(self.description) or ""
        validation_mode = parse_profile_validation_mode_value(self.validation_mode)
        metadata = normalize_metadata(self.metadata)

        module_rules = normalize_module_rules(self.module_rules)
        document_rules = normalize_document_rules(self.document_rules)
        asset_rules = normalize_asset_rules(self.asset_rules)
        validation_rules = normalize_validation_rules(self.validation_rules)
        defaults = self.defaults.normalized()

        module_rules = ensure_core_module_rules(module_rules)
        module_rules = tuple(
            sorted(
                module_rules,
                key=lambda rule: get_module_order_safe(rule.module_name),
            )
        )

        profile = ObjectKindProfile(
            profile_key=profile_key,
            object_kind=object_kind,
            title=title,
            description=description,
            module_rules=module_rules,
            document_rules=document_rules,
            asset_rules=asset_rules,
            validation_rules=validation_rules,
            defaults=defaults,
            validation_mode=validation_mode,
            metadata=metadata,
        )

        valid, messages = profile.validate()
        if not valid:
            raise ProfileError(" ".join(messages))

        return profile

    @property
    def required_module_names(self) -> tuple[str, ...]:
        return tuple(
            rule.module_name
            for rule in self.normalized().module_rules
            if rule.requirement == ProfileModuleRequirement.REQUIRED.value
        )

    @property
    def recommended_module_names(self) -> tuple[str, ...]:
        return tuple(
            rule.module_name
            for rule in self.normalized().module_rules
            if rule.requirement == ProfileModuleRequirement.RECOMMENDED.value
        )

    @property
    def optional_module_names(self) -> tuple[str, ...]:
        return tuple(
            rule.module_name
            for rule in self.normalized().module_rules
            if rule.requirement == ProfileModuleRequirement.OPTIONAL.value
        )

    @property
    def excluded_module_names(self) -> tuple[str, ...]:
        return tuple(
            rule.module_name
            for rule in self.normalized().module_rules
            if rule.requirement == ProfileModuleRequirement.EXCLUDED.value
        )

    @property
    def active_module_names(self) -> tuple[str, ...]:
        return tuple(
            rule.module_name
            for rule in self.normalized().module_rules
            if rule.active_by_default
        )

    @property
    def required_document_paths(self) -> tuple[str, ...]:
        paths: list[str] = []

        for rule in self.normalized().module_rules:
            if rule.active_by_default:
                paths.extend(rule.required_files)

        for rule in self.normalized().document_rules:
            if rule.required:
                paths.append(rule.path)

        return tuple(dict.fromkeys(paths))

    @property
    def optional_document_paths(self) -> tuple[str, ...]:
        paths: list[str] = []

        for rule in self.normalized().module_rules:
            if rule.active_by_default:
                paths.extend(rule.optional_files)

        for rule in self.normalized().document_rules:
            if not rule.required:
                paths.append(rule.path)

        return tuple(dict.fromkeys(paths))

    def get_module_rule(self, module_name: Any) -> ProfileModuleRule | None:
        module_value = normalize_module_name(module_name)

        for rule in self.normalized().module_rules:
            if rule.module_name == module_value:
                return rule

        return None

    def requires_module(self, module_name: Any) -> bool:
        rule = self.get_module_rule(module_name)
        return bool(rule and rule.requirement == ProfileModuleRequirement.REQUIRED.value)

    def activates_module(self, module_name: Any) -> bool:
        rule = self.get_module_rule(module_name)
        return bool(rule and rule.active_by_default)

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        messages: list[str] = []

        try:
            module_names = [rule.module_name for rule in self.module_rules]
            duplicate_modules = find_duplicates(module_names)
            for module_name in duplicate_modules:
                messages.append(f"Duplicate module rule for module {module_name!r}.")

            for core_module in CORE_REQUIRED_MODULES:
                rule = next((item for item in self.module_rules if item.module_name == core_module), None)
                if rule is None:
                    messages.append(f"Missing core module rule {core_module!r}.")
                elif rule.requirement != ProfileModuleRequirement.REQUIRED.value:
                    messages.append(f"Core module {core_module!r} must be required.")

            document_paths = [rule.path for rule in self.document_rules]
            duplicate_documents = find_duplicates(document_paths)
            for path in duplicate_documents:
                messages.append(f"Duplicate document rule for path {path!r}.")

            for document_rule in self.document_rules:
                if document_rule.module_name not in module_names:
                    messages.append(
                        f"Document rule {document_rule.path!r} references unknown module "
                        f"{document_rule.module_name!r}."
                    )

            for asset_rule in self.asset_rules:
                if asset_rule.module_name not in module_names:
                    messages.append(
                        f"Asset rule {asset_rule.role!r} references unknown module "
                        f"{asset_rule.module_name!r}."
                    )

            if self.defaults.grid_size_cells[0] < 1 or self.defaults.grid_size_cells[1] < 1 or self.defaults.grid_size_cells[2] < 1:
                messages.append("Default grid_size_cells must contain positive dimensions.")

        except ProfileError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate profile: {exc}")

        return len(messages) == 0, tuple(messages)

    def to_module_plan_entries(self) -> tuple[Any, ...]:
        """
        Wandelt die Profil-Modulregeln in ModulePlanEntry-Objekte um.

        Der Import ist lazy, damit Profile auch ohne vollständige Model-Schicht
        inspiziert werden können.
        """
        try:
            from ..models.module_plan import ModuleActivationSource, ModulePlanEntry

            return tuple(
                ModulePlanEntry(
                    module_name=rule.module_name,
                    active=rule.active_by_default,
                    requirement=rule.requirement,
                    source=ModuleActivationSource.PROFILE.value,
                    reason=rule.reason or f"Configured by profile {self.profile_key}.",
                    required_files=rule.required_files,
                    optional_files=rule.optional_files,
                    generated_files=rule.generated_files,
                    allowed_subdirectories=rule.allowed_subdirectories,
                ).normalized()
                for rule in self.normalized().module_rules
            )
        except Exception as exc:
            raise ProfileError(f"Could not convert profile to module plan entries: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": BASE_PROFILE_SCHEMA_VERSION,
            "profile_key": normalized.profile_key,
            "object_kind": normalized.object_kind,
            "title": normalized.title,
            "description": normalized.description,
            "validation_mode": normalized.validation_mode,
            "active_modules": list(normalized.active_module_names),
            "required_modules": list(normalized.required_module_names),
            "recommended_modules": list(normalized.recommended_module_names),
            "optional_modules": list(normalized.optional_module_names),
            "excluded_modules": list(normalized.excluded_module_names),
            "required_document_paths": list(normalized.required_document_paths),
            "optional_document_paths": list(normalized.optional_document_paths),
            "module_rules": [rule.to_dict() for rule in normalized.module_rules],
            "document_rules": [rule.to_dict() for rule in normalized.document_rules],
            "asset_rules": [rule.to_dict() for rule in normalized.asset_rules],
            "validation_rules": [rule.to_dict() for rule in normalized.validation_rules],
            "defaults": normalized.defaults.to_dict(),
            "metadata": dict(normalized.metadata),
        }


def build_base_profile(
    *,
    profile_key: str = BASE_PROFILE_KEY,
    object_kind: str = "cell_block",
    title: str = "Base profile",
    description: str = "Base VPLIB object-kind profile.",
    defaults: ProfileDefaults | None = None,
    extra_module_rules: Iterable[ProfileModuleRule] | None = None,
    extra_document_rules: Iterable[ProfileDocumentRule] | None = None,
    extra_asset_rules: Iterable[ProfileAssetRule] | None = None,
    extra_validation_rules: Iterable[ProfileValidationRule] | None = None,
    validation_mode: str = ProfileValidationMode.NORMAL.value,
    metadata: Mapping[str, Any] | None = None,
) -> ObjectKindProfile:
    """Baut ein generisches Basisprofil."""
    module_rules = [
        *base_required_module_rules(),
        *base_recommended_module_rules(),
        *base_optional_module_rules(),
        *(extra_module_rules or ()),
    ]

    document_rules = tuple(extra_document_rules or ())
    asset_rules = tuple(extra_asset_rules or ())
    validation_rules = (
        *base_validation_rules(),
        *(extra_validation_rules or ()),
    )

    return ObjectKindProfile(
        profile_key=profile_key,
        object_kind=object_kind,
        title=title,
        description=description,
        module_rules=tuple(module_rules),
        document_rules=document_rules,
        asset_rules=asset_rules,
        validation_rules=tuple(validation_rules),
        defaults=defaults or ProfileDefaults(),
        validation_mode=validation_mode,
        metadata=dict(metadata or {}),
    ).normalized()


def base_required_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt Basisregeln für Core-Required-Module."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.REQUIRED.value,
            active_by_default=True,
            reason="Core VPLIB module.",
        ).normalized()
        for module_name in CORE_REQUIRED_MODULES
    )


def base_recommended_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt Basisregeln für empfohlene Module."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.RECOMMENDED.value,
            active_by_default=True,
            reason="Recommended for most VPLIB packages.",
        ).normalized()
        for module_name in BASE_RECOMMENDED_MODULES
    )


def base_optional_module_rules() -> tuple[ProfileModuleRule, ...]:
    """Erzeugt Basisregeln für optionale Module."""
    return tuple(
        ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.OPTIONAL.value,
            active_by_default=False,
            reason="Optional VPLIB module.",
        ).normalized()
        for module_name in BASE_OPTIONAL_MODULES
    )


def base_validation_rules() -> tuple[ProfileValidationRule, ...]:
    """Erzeugt gemeinsame Basis-Validierungsregeln."""
    return (
        ProfileValidationRule(
            rule_key="core_modules_present",
            scope=ProfileRuleScope.MODULE.value,
            severity=ProfileRuleSeverity.FATAL.value,
            message="All core VPLIB modules must be present.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="required_files_present",
            scope=ProfileRuleScope.DOCUMENT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            message="All required files for active modules must be present.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="no_executable_files",
            scope=ProfileRuleScope.ASSET.value,
            severity=ProfileRuleSeverity.FATAL.value,
            message="Executable files are forbidden inside VPLIB packages.",
        ).normalized(),
        ProfileValidationRule(
            rule_key="variant_overrides_only",
            scope=ProfileRuleScope.VARIANT.value,
            severity=ProfileRuleSeverity.ERROR.value,
            message="Variants must only define allowed overrides.",
        ).normalized(),
    )


def ensure_core_module_rules(
    module_rules: Iterable[ProfileModuleRule],
) -> tuple[ProfileModuleRule, ...]:
    """Stellt sicher, dass Core-Modulregeln vorhanden und required sind."""
    rules_by_name: dict[str, ProfileModuleRule] = {}

    for rule in module_rules or ():
        normalized = rule.normalized()
        rules_by_name[normalized.module_name] = normalized

    for module_name in CORE_REQUIRED_MODULES:
        existing = rules_by_name.get(module_name)
        core_rule = ProfileModuleRule(
            module_name=module_name,
            requirement=ProfileModuleRequirement.REQUIRED.value,
            active_by_default=True,
            reason="Core VPLIB module.",
        ).normalized()

        if existing is None:
            rules_by_name[module_name] = core_rule
            continue

        rules_by_name[module_name] = merge_profile_module_rules(existing, core_rule)

    return tuple(rules_by_name.values())


def merge_profile_module_rules(
    left: ProfileModuleRule,
    right: ProfileModuleRule,
) -> ProfileModuleRule:
    """Merged zwei Modulregeln desselben Moduls."""
    left_normalized = left.normalized()
    right_normalized = right.normalized()

    if left_normalized.module_name != right_normalized.module_name:
        raise ProfileError(
            f"Cannot merge module rules for different modules: "
            f"{left_normalized.module_name!r}, {right_normalized.module_name!r}."
        )

    requirement = strongest_module_requirement(
        left_normalized.requirement,
        right_normalized.requirement,
    )
    active_by_default = left_normalized.active_by_default or right_normalized.active_by_default

    if requirement == ProfileModuleRequirement.REQUIRED.value:
        active_by_default = True

    if requirement == ProfileModuleRequirement.EXCLUDED.value:
        active_by_default = False

    return ProfileModuleRule(
        module_name=left_normalized.module_name,
        requirement=requirement,
        active_by_default=active_by_default,
        reason=right_normalized.reason or left_normalized.reason,
        required_files=merge_string_tuples(left_normalized.required_files, right_normalized.required_files),
        optional_files=merge_string_tuples(left_normalized.optional_files, right_normalized.optional_files),
        generated_files=merge_string_tuples(left_normalized.generated_files, right_normalized.generated_files),
        allowed_subdirectories=merge_string_tuples(
            left_normalized.allowed_subdirectories,
            right_normalized.allowed_subdirectories,
        ),
    ).normalized()


def strongest_module_requirement(left: Any, right: Any) -> str:
    """Ermittelt den stärkeren Requirement-Level."""
    left_value = parse_profile_module_requirement_value(left)
    right_value = parse_profile_module_requirement_value(right)

    if left_value == ProfileModuleRequirement.EXCLUDED.value or right_value == ProfileModuleRequirement.EXCLUDED.value:
        return ProfileModuleRequirement.EXCLUDED.value

    order = {
        ProfileModuleRequirement.OPTIONAL.value: 1,
        ProfileModuleRequirement.RECOMMENDED.value: 2,
        ProfileModuleRequirement.REQUIRED.value: 3,
    }

    return left_value if order[left_value] >= order[right_value] else right_value


def normalize_module_rules(
    values: Iterable[ProfileModuleRule],
) -> tuple[ProfileModuleRule, ...]:
    """Normalisiert Modulregeln und merged Duplikate."""
    rules_by_name: dict[str, ProfileModuleRule] = {}

    for value in values or ():
        rule = value.normalized()
        existing = rules_by_name.get(rule.module_name)

        rules_by_name[rule.module_name] = (
            rule if existing is None else merge_profile_module_rules(existing, rule)
        )

    return tuple(rules_by_name.values())


def normalize_document_rules(
    values: Iterable[ProfileDocumentRule],
) -> tuple[ProfileDocumentRule, ...]:
    """Normalisiert Dokumentregeln."""
    rules_by_path: dict[str, ProfileDocumentRule] = {}

    for value in values or ():
        rule = value.normalized()
        existing = rules_by_path.get(rule.path)

        if existing is not None:
            rule = ProfileDocumentRule(
                path=rule.path,
                module_name=rule.module_name,
                required=existing.required or rule.required,
                generated=existing.generated or rule.generated,
                allow_empty_initially=existing.allow_empty_initially and rule.allow_empty_initially,
                reason=rule.reason or existing.reason,
            ).normalized()

        rules_by_path[rule.path] = rule

    return tuple(rules_by_path.values())


def normalize_asset_rules(
    values: Iterable[ProfileAssetRule],
) -> tuple[ProfileAssetRule, ...]:
    """Normalisiert Assetregeln."""
    rules_by_role: dict[str, ProfileAssetRule] = {}

    for value in values or ():
        rule = value.normalized()
        existing = rules_by_role.get(rule.role)

        if existing is not None:
            rule = ProfileAssetRule(
                role=rule.role,
                policy=strongest_asset_policy(existing.policy, rule.policy),
                module_name=rule.module_name or existing.module_name,
                allowed_extensions=merge_string_tuples(existing.allowed_extensions, rule.allowed_extensions),
                max_size_mb=rule.max_size_mb if rule.max_size_mb is not None else existing.max_size_mb,
                requires_bounds=existing.requires_bounds or rule.requires_bounds,
                must_fit_grid_footprint=existing.must_fit_grid_footprint or rule.must_fit_grid_footprint,
                reason=rule.reason or existing.reason,
            ).normalized()

        rules_by_role[rule.role] = rule

    return tuple(rules_by_role.values())


def normalize_validation_rules(
    values: Iterable[ProfileValidationRule],
) -> tuple[ProfileValidationRule, ...]:
    """Normalisiert Validierungsregeln."""
    rules_by_key: dict[str, ProfileValidationRule] = {}

    for value in values or ():
        rule = value.normalized()
        rules_by_key[rule.rule_key] = rule

    return tuple(rules_by_key.values())


def strongest_asset_policy(left: Any, right: Any) -> str:
    """Ermittelt die stärkere Asset-Policy."""
    left_value = parse_profile_asset_policy_value(left)
    right_value = parse_profile_asset_policy_value(right)

    order = {
        ProfileAssetPolicy.NOT_ALLOWED.value: 0,
        ProfileAssetPolicy.OPTIONAL.value: 1,
        ProfileAssetPolicy.RECOMMENDED.value: 2,
        ProfileAssetPolicy.REQUIRED.value: 3,
    }

    return left_value if order[left_value] >= order[right_value] else right_value


@lru_cache(maxsize=128)
def parse_profile_module_requirement_value(value: Any) -> str:
    """Parst ProfileModuleRequirement."""
    try:
        if isinstance(value, ProfileModuleRequirement):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "must": ProfileModuleRequirement.REQUIRED.value,
            "mandatory": ProfileModuleRequirement.REQUIRED.value,
            "required": ProfileModuleRequirement.REQUIRED.value,
            "recommended": ProfileModuleRequirement.RECOMMENDED.value,
            "suggested": ProfileModuleRequirement.RECOMMENDED.value,
            "optional": ProfileModuleRequirement.OPTIONAL.value,
            "excluded": ProfileModuleRequirement.EXCLUDED.value,
            "disabled": ProfileModuleRequirement.EXCLUDED.value,
            "forbidden": ProfileModuleRequirement.EXCLUDED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ProfileModuleRequirement(raw).value
    except Exception as exc:
        raise ProfileError(f"Invalid profile module requirement {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_profile_rule_severity_value(value: Any) -> str:
    """Parst ProfileRuleSeverity."""
    try:
        if isinstance(value, ProfileRuleSeverity):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "info": ProfileRuleSeverity.INFO.value,
            "warning": ProfileRuleSeverity.WARNING.value,
            "warn": ProfileRuleSeverity.WARNING.value,
            "error": ProfileRuleSeverity.ERROR.value,
            "fatal": ProfileRuleSeverity.FATAL.value,
            "critical": ProfileRuleSeverity.FATAL.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ProfileRuleSeverity(raw).value
    except Exception as exc:
        raise ProfileError(f"Invalid profile rule severity {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_profile_rule_scope_value(value: Any) -> str:
    """Parst ProfileRuleScope."""
    try:
        if isinstance(value, ProfileRuleScope):
            return value.value

        raw = normalize_enum_key(value)
        return ProfileRuleScope(raw).value
    except Exception as exc:
        raise ProfileError(f"Invalid profile rule scope {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_profile_asset_policy_value(value: Any) -> str:
    """Parst ProfileAssetPolicy."""
    try:
        if isinstance(value, ProfileAssetPolicy):
            return value.value

        raw = normalize_enum_key(value)

        aliases = {
            "not_allowed": ProfileAssetPolicy.NOT_ALLOWED.value,
            "forbidden": ProfileAssetPolicy.NOT_ALLOWED.value,
            "disabled": ProfileAssetPolicy.NOT_ALLOWED.value,
            "optional": ProfileAssetPolicy.OPTIONAL.value,
            "recommended": ProfileAssetPolicy.RECOMMENDED.value,
            "suggested": ProfileAssetPolicy.RECOMMENDED.value,
            "required": ProfileAssetPolicy.REQUIRED.value,
            "mandatory": ProfileAssetPolicy.REQUIRED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ProfileAssetPolicy(raw).value
    except Exception as exc:
        raise ProfileError(f"Invalid profile asset policy {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_profile_validation_mode_value(value: Any) -> str:
    """Parst ProfileValidationMode."""
    try:
        if isinstance(value, ProfileValidationMode):
            return value.value

        raw = normalize_enum_key(value)
        return ProfileValidationMode(raw).value
    except Exception as exc:
        raise ProfileError(f"Invalid profile validation mode {value!r}.") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert eine Objektart."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise ProfileError(f"Invalid object_kind {value!r}: {exc}") from exc


def normalize_module_name(value: Any) -> str:
    """Normalisiert einen Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise ProfileError(f"Invalid module_name {value!r}: {exc}") from exc


def normalize_placement_mode_value(value: Any) -> str:
    """Normalisiert einen Placement Mode."""
    try:
        from ..domain.placement_modes import ensure_placement_mode_value

        return ensure_placement_mode_value(value)
    except Exception as exc:
        raise ProfileError(f"Invalid placement_mode {value!r}: {exc}") from exc


def normalize_variant_mode_value(value: Any) -> str:
    """Normalisiert einen Variant Mode."""
    try:
        from ..models.variant_definition import parse_variant_mode_value

        return parse_variant_mode_value(value)
    except Exception:
        raw = normalize_enum_key(value)
        if raw not in {"single", "multiple"}:
            raise ProfileError(f"Invalid variant_mode {value!r}.")
        return raw


def normalize_package_path(value: Any) -> str:
    """Normalisiert einen Package-Pfad."""
    try:
        from ..domain.package_paths import normalize_package_path as normalize

        return normalize(value)
    except Exception as exc:
        raise ProfileError(f"Invalid package path {value!r}: {exc}") from exc


def normalize_asset_role_value(value: Any) -> str:
    """Normalisiert eine Asset-Rolle."""
    try:
        from ..models.asset_reference import parse_asset_role_value

        return parse_asset_role_value(value)
    except Exception:
        return normalize_enum_key(value)


def is_path_under_module_safe(path: Any, module_name: Any) -> bool:
    """Prüft, ob ein Pfad unter einem Modul liegt."""
    try:
        from ..domain.package_paths import is_path_under_module

        return is_path_under_module(path, module_name)
    except Exception:
        return False


def get_required_files_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest Pflichtdateien eines Moduls."""
    try:
        from ..domain.package_paths import get_required_files_for_module

        return tuple(get_required_files_for_module(module_name))
    except Exception:
        return tuple()


def get_optional_files_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest optionale Dateien eines Moduls."""
    try:
        from ..domain.package_paths import get_optional_files_for_module

        return tuple(get_optional_files_for_module(module_name))
    except Exception:
        return tuple()


def get_generated_files_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest generierte Dateien eines Moduls."""
    try:
        from ..domain.package_paths import get_generated_files_for_module

        return tuple(get_generated_files_for_module(module_name))
    except Exception:
        return tuple()


def get_allowed_subdirectories_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest erlaubte Unterordner eines Moduls."""
    try:
        from ..domain.package_paths import get_allowed_subdirectories_for_module

        return tuple(get_allowed_subdirectories_for_module(module_name))
    except Exception:
        return tuple()


def get_module_order_safe(module_name: Any) -> int:
    """Ermittelt eine stabile Modulsortierung."""
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


def normalize_profile_key(value: Any) -> str:
    """Normalisiert einen Profil-Key."""
    key = normalize_enum_key(value)

    if not key:
        raise ProfileError("profile_key is required.")

    return key


def normalize_rule_key(value: Any) -> str:
    """Normalisiert einen Rule-Key."""
    return normalize_enum_key(value)


def normalize_grid_size_cells(value: Any) -> tuple[int, int, int]:
    """Normalisiert Grid Size Cells."""
    try:
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ProfileError("grid_size_cells must contain exactly three values.")

        x = normalize_positive_int(value[0], "grid_size_cells[0]")
        y = normalize_positive_int(value[1], "grid_size_cells[1]")
        z = normalize_positive_int(value[2], "grid_size_cells[2]")

        return (x, y, z)
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Invalid grid_size_cells {value!r}.") from exc


def normalize_package_path_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert mehrere Package-Pfade ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        path = normalize_package_path(value)
        if path in seen:
            continue
        result.append(path)
        seen.add(path)

    return tuple(result)


def normalize_extension_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Dateiendungen."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        extension = str(value).strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = f".{extension}"
        if extension in seen:
            continue
        result.append(extension)
        seen.add(extension)

    return tuple(result)


def normalize_metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalisiert Metadata JSON-kompatibel."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise ProfileError("metadata must be a mapping.")

    return {
        str(key): normalize_metadata_value(child_value)
        for key, child_value in value.items()
    }


def normalize_metadata_value(value: Any) -> Any:
    """Normalisiert einen Metadata-Wert JSON-kompatibel."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return normalize_metadata(value)

    if isinstance(value, (list, tuple, set)):
        return [normalize_metadata_value(item) for item in value]

    return str(value)


def normalize_positive_float(value: Any, field_name: str) -> float:
    """Normalisiert eine positive Zahl."""
    try:
        if isinstance(value, bool):
            raise ProfileError(f"{field_name} must be a number.")

        number = float(value)
        if number <= 0:
            raise ProfileError(f"{field_name} must be > 0.")

        return number
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"{field_name} must be a positive number.") from exc


def normalize_optional_positive_float(value: Any, field_name: str) -> float | None:
    """Normalisiert eine optionale positive Zahl."""
    if value is None:
        return None

    return normalize_positive_float(value, field_name)


def normalize_positive_int(value: Any, field_name: str) -> int:
    """Normalisiert einen positiven Integer."""
    try:
        if isinstance(value, bool):
            raise ProfileError(f"{field_name} must be an integer.")

        number = int(value)
        if number < 1:
            raise ProfileError(f"{field_name} must be >= 1.")

        return number
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"{field_name} must be a positive integer.") from exc


def normalize_slug_like(value: Any, field_name: str) -> str:
    """Normalisiert einfache Slug-Werte."""
    raw = clean_required_string(value, field_name)
    return raw.lower().replace(" ", "_").replace("-", "_")


def normalize_color(value: Any) -> str:
    """Normalisiert eine Hex-Farbe."""
    try:
        from ..models.create_request import normalize_color as normalize

        return normalize(value)
    except Exception:
        color = clean_required_string(value, "fallback_color")
        if not color.startswith("#"):
            raise ProfileError(f"Invalid color {value!r}.")
        return color


def normalize_enum_key(value: Any) -> str:
    """Normalisiert Enum-ähnliche Werte."""
    try:
        raw = str(value).strip()

        if not raw:
            raise ProfileError("Enum value is required.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"Invalid enum value {value!r}.") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ProfileError(f"{field_name} is required.")

        return cleaned
    except ProfileError:
        raise
    except Exception as exc:
        raise ProfileError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def merge_string_tuples(left: Iterable[Any], right: Iterable[Any]) -> tuple[str, ...]:
    """Merged Stringsequenzen ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in (*tuple(left or ()), *tuple(right or ())):
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def find_duplicates(values: Iterable[Any]) -> tuple[str, ...]:
    """Findet Duplikate in einer Sequenz."""
    seen: set[str] = set()
    duplicates: set[str] = set()

    for value in values or ():
        cleaned = clean_optional_string(value)
        if not cleaned:
            continue
        if cleaned in seen:
            duplicates.add(cleaned)
        seen.add(cleaned)

    return tuple(sorted(duplicates))


def clear_base_profile_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_profile_module_requirement_value.cache_clear()
    parse_profile_rule_severity_value.cache_clear()
    parse_profile_rule_scope_value.cache_clear()
    parse_profile_asset_policy_value.cache_clear()
    parse_profile_validation_mode_value.cache_clear()


__all__ = [
    "BASE_FORBIDDEN_MODULES",
    "BASE_OPTIONAL_MODULES",
    "BASE_PROFILE_KEY",
    "BASE_PROFILE_SCHEMA_VERSION",
    "BASE_RECOMMENDED_MODULES",
    "CORE_REQUIRED_MODULES",
    "DEFAULT_MANUFACTURER_OVERLAY_LEVEL",
    "DEFAULT_SCHEMA_VERSION",
    "ObjectKindProfile",
    "ProfileAssetPolicy",
    "ProfileAssetRule",
    "ProfileDefaults",
    "ProfileDocumentRule",
    "ProfileError",
    "ProfileModuleRequirement",
    "ProfileModuleRule",
    "ProfileRuleScope",
    "ProfileRuleSeverity",
    "ProfileValidationMode",
    "ProfileValidationRule",
    "base_optional_module_rules",
    "base_recommended_module_rules",
    "base_required_module_rules",
    "base_validation_rules",
    "build_base_profile",
    "clean_optional_string",
    "clean_required_string",
    "clear_base_profile_caches",
    "ensure_core_module_rules",
    "find_duplicates",
    "get_allowed_subdirectories_for_module_safe",
    "get_generated_files_for_module_safe",
    "get_module_order_safe",
    "get_optional_files_for_module_safe",
    "get_required_files_for_module_safe",
    "is_path_under_module_safe",
    "merge_profile_module_rules",
    "merge_string_tuples",
    "normalize_asset_role_value",
    "normalize_color",
    "normalize_document_rules",
    "normalize_enum_key",
    "normalize_extension_tuple",
    "normalize_grid_size_cells",
    "normalize_metadata",
    "normalize_metadata_value",
    "normalize_module_name",
    "normalize_module_rules",
    "normalize_object_kind_value",
    "normalize_package_path",
    "normalize_package_path_tuple",
    "normalize_placement_mode_value",
    "normalize_positive_float",
    "normalize_positive_int",
    "normalize_profile_key",
    "normalize_rule_key",
    "normalize_slug_like",
    "normalize_validation_rules",
    "normalize_variant_mode_value",
    "parse_profile_asset_policy_value",
    "parse_profile_module_requirement_value",
    "parse_profile_rule_scope_value",
    "parse_profile_rule_severity_value",
    "parse_profile_validation_mode_value",
    "strongest_asset_policy",
    "strongest_module_requirement",
]