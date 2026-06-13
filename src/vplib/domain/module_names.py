# services/vectoplan-library/src/vplib/domain/module_names.py
"""
Canonical VPLIB module-name definitions.

This module defines the stable module vocabulary for modular VPLIB packages.
A module is a logical package section such as family, variants, editor, render,
physical, calculation or manufacturer.

The module names defined here are used by:
- creation planning
- module planning
- document builders
- package validation
- archive creation
- scanner reports
- future API responses
- future database publication models

Keep canonical values stable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


MODULE_NAME_SCHEMA_VERSION: Final[str] = "vplib.module_names.v1"


class ModuleNameError(ValueError):
    """Raised when a VPLIB module-name value cannot be normalized or validated."""


class VplibModuleName(str, Enum):
    """
    Canonical module names for modular VPLIB packages.

    Top-level technical files:
    - manifest
    - modules

    Directory-backed modules:
    - family
    - variants
    - editor
    - render
    - physical
    - material
    - calculation
    - analysis
    - dynamic
    - manufacturer
    - docs
    - tests
    """

    MANIFEST = "manifest"
    MODULES = "modules"
    FAMILY = "family"
    VARIANTS = "variants"
    EDITOR = "editor"
    RENDER = "render"
    PHYSICAL = "physical"
    MATERIAL = "material"
    CALCULATION = "calculation"
    ANALYSIS = "analysis"
    DYNAMIC = "dynamic"
    MANUFACTURER = "manufacturer"
    DOCS = "docs"
    TESTS = "tests"

    @property
    def key(self) -> str:
        """Return the canonical string key."""
        return str(self.value)

    @property
    def is_top_level_file_module(self) -> bool:
        """Return whether this module is represented by a top-level JSON file."""
        return self in {
            VplibModuleName.MANIFEST,
            VplibModuleName.MODULES,
        }

    @property
    def is_directory_module(self) -> bool:
        """Return whether this module is represented by a directory."""
        return not self.is_top_level_file_module

    @property
    def is_core_module(self) -> bool:
        """Return whether this module belongs to the always-required VPLIB core."""
        return self in get_core_module_names()

    @property
    def is_content_module(self) -> bool:
        """Return whether this module carries domain or authoring content."""
        return self in {
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
            VplibModuleName.EDITOR,
            VplibModuleName.RENDER,
            VplibModuleName.PHYSICAL,
            VplibModuleName.MATERIAL,
            VplibModuleName.CALCULATION,
            VplibModuleName.ANALYSIS,
            VplibModuleName.DYNAMIC,
            VplibModuleName.MANUFACTURER,
        }

    @property
    def is_optional_support_module(self) -> bool:
        """Return whether this module is a support/documentation/test module."""
        return self in {
            VplibModuleName.DOCS,
            VplibModuleName.TESTS,
        }


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """
    Metadata for one canonical VPLIB module.

    This file intentionally defines module-level invariants only. More detailed
    file paths are handled by package-path definitions and document builders.
    """

    name: VplibModuleName
    title: str
    description: str
    required_by_core: bool
    top_level_file: str | None
    directory_name: str | None
    required_document_names: tuple[str, ...]
    optional_document_names: tuple[str, ...]
    depends_on: tuple[VplibModuleName, ...]
    mutually_exclusive_with: tuple[VplibModuleName, ...]
    can_be_empty_initially: bool
    participates_in_archive: bool
    participates_in_checksum: bool
    allows_assets: bool
    allows_json_documents: bool
    allows_markdown_documents: bool
    allows_binary_assets: bool
    forbids_executable_files: bool
    stable_order: int


_MODULE_DEFINITIONS: Final[dict[VplibModuleName, ModuleDefinition]] = {
    VplibModuleName.MANIFEST: ModuleDefinition(
        name=VplibModuleName.MANIFEST,
        title="Manifest",
        description="Top-level technical package identity and version metadata.",
        required_by_core=True,
        top_level_file="vplib.manifest.json",
        directory_name=None,
        required_document_names=("vplib.manifest.json",),
        optional_document_names=tuple(),
        depends_on=tuple(),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=10,
    ),
    VplibModuleName.MODULES: ModuleDefinition(
        name=VplibModuleName.MODULES,
        title="Modules",
        description="Top-level declaration of active, required and optional package modules.",
        required_by_core=True,
        top_level_file="vplib.modules.json",
        directory_name=None,
        required_document_names=("vplib.modules.json",),
        optional_document_names=tuple(),
        depends_on=(VplibModuleName.MANIFEST,),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=20,
    ),
    VplibModuleName.FAMILY: ModuleDefinition(
        name=VplibModuleName.FAMILY,
        title="Family",
        description="Semantic identity and classification of a reusable library family.",
        required_by_core=True,
        top_level_file=None,
        directory_name="family",
        required_document_names=(
            "identity.json",
            "classification.json",
        ),
        optional_document_names=(
            "lifecycle.json",
            "aliases.json",
        ),
        depends_on=(
            VplibModuleName.MANIFEST,
            VplibModuleName.MODULES,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=30,
    ),
    VplibModuleName.VARIANTS: ModuleDefinition(
        name=VplibModuleName.VARIANTS,
        title="Variants",
        description="Variant index, default variant and variant override documents.",
        required_by_core=True,
        top_level_file=None,
        directory_name="variants",
        required_document_names=(
            "index.json",
            "default.json",
        ),
        optional_document_names=tuple(),
        depends_on=(
            VplibModuleName.FAMILY,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=40,
    ),
    VplibModuleName.EDITOR: ModuleDefinition(
        name=VplibModuleName.EDITOR,
        title="Editor",
        description="Editor-facing inventory, placement, targeting and anchor metadata.",
        required_by_core=True,
        top_level_file=None,
        directory_name="editor",
        required_document_names=(
            "inventory.json",
            "placement.json",
        ),
        optional_document_names=(
            "targeting.json",
            "anchors.json",
            "sockets.json",
            "ports.json",
            "tools.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=50,
    ),
    VplibModuleName.RENDER: ModuleDefinition(
        name=VplibModuleName.RENDER,
        title="Render",
        description="Visual representation metadata and render assets such as icons, previews, textures and GLB models.",
        required_by_core=False,
        top_level_file=None,
        directory_name="render",
        required_document_names=(
            "render_variants.json",
        ),
        optional_document_names=(
            "bounds.json",
            "materials.json",
            "lod.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
            VplibModuleName.EDITOR,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=True,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=True,
        forbids_executable_files=True,
        stable_order=60,
    ),
    VplibModuleName.PHYSICAL: ModuleDefinition(
        name=VplibModuleName.PHYSICAL,
        title="Physical",
        description="Physical dimensions, collision, occupancy and real-world object properties.",
        required_by_core=False,
        top_level_file=None,
        directory_name="physical",
        required_document_names=(
            "base.json",
            "dimensions.json",
            "collision.json",
        ),
        optional_document_names=(
            "layers.json",
            "occupancy.json",
            "mass.json",
            "bounds.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
            VplibModuleName.EDITOR,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=70,
    ),
    VplibModuleName.MATERIAL: ModuleDefinition(
        name=VplibModuleName.MATERIAL,
        title="Material",
        description="Material identity, material performance and material-related technical properties.",
        required_by_core=False,
        top_level_file=None,
        directory_name="material",
        required_document_names=(
            "base.json",
        ),
        optional_document_names=(
            "performance.json",
            "surfaces.json",
            "layers.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=80,
    ),
    VplibModuleName.CALCULATION: ModuleDefinition(
        name=VplibModuleName.CALCULATION,
        title="Calculation",
        description="Declarative variables, formulas, quantities, constraints and measurement logic.",
        required_by_core=False,
        top_level_file=None,
        directory_name="calculation",
        required_document_names=(
            "variables.json",
            "formulas.json",
            "quantities.json",
            "measure_logic.json",
        ),
        optional_document_names=(
            "constraints.json",
            "units.json",
            "cost_factors.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=90,
    ),
    VplibModuleName.ANALYSIS: ModuleDefinition(
        name=VplibModuleName.ANALYSIS,
        title="Analysis",
        description="Optional technical analysis profiles for statics, energy, acoustics, routing and reinforcement.",
        required_by_core=False,
        top_level_file=None,
        directory_name="analysis",
        required_document_names=tuple(),
        optional_document_names=(
            "statics/profile.json",
            "energy/profile.json",
            "acoustics/profile.json",
            "routing/profile.json",
            "reinforcement/profile.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=100,
    ),
    VplibModuleName.DYNAMIC: ModuleDefinition(
        name=VplibModuleName.DYNAMIC,
        title="Dynamic",
        description="Declarative context rules, bindings and generator parameters for adaptive systems.",
        required_by_core=False,
        top_level_file=None,
        directory_name="dynamic",
        required_document_names=(
            "context_rules.json",
            "bindings.json",
            "generator.json",
        ),
        optional_document_names=(
            "parameters.json",
            "constraints.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
            VplibModuleName.EDITOR,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=110,
    ),
    VplibModuleName.MANUFACTURER: ModuleDefinition(
        name=VplibModuleName.MANUFACTURER,
        title="Manufacturer",
        description="Manufacturer overlay contract and allowed override-slot declarations.",
        required_by_core=True,
        top_level_file=None,
        directory_name="manufacturer",
        required_document_names=(
            "contract.json",
        ),
        optional_document_names=(
            "override_slots.json",
            "product_mapping.json",
        ),
        depends_on=(
            VplibModuleName.FAMILY,
            VplibModuleName.VARIANTS,
        ),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=False,
        participates_in_archive=True,
        participates_in_checksum=True,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=120,
    ),
    VplibModuleName.DOCS: ModuleDefinition(
        name=VplibModuleName.DOCS,
        title="Docs",
        description="Human-readable package notes and documentation.",
        required_by_core=False,
        top_level_file=None,
        directory_name="docs",
        required_document_names=tuple(),
        optional_document_names=(
            "notes.md",
            "changelog.md",
            "authoring.md",
        ),
        depends_on=tuple(),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=False,
        allows_assets=True,
        allows_json_documents=True,
        allows_markdown_documents=True,
        allows_binary_assets=True,
        forbids_executable_files=True,
        stable_order=130,
    ),
    VplibModuleName.TESTS: ModuleDefinition(
        name=VplibModuleName.TESTS,
        title="Tests",
        description="Package-local declarative validation cases and fixture metadata.",
        required_by_core=False,
        top_level_file=None,
        directory_name="tests",
        required_document_names=tuple(),
        optional_document_names=(
            "cases.json",
            "fixtures.json",
        ),
        depends_on=tuple(),
        mutually_exclusive_with=tuple(),
        can_be_empty_initially=True,
        participates_in_archive=True,
        participates_in_checksum=False,
        allows_assets=False,
        allows_json_documents=True,
        allows_markdown_documents=False,
        allows_binary_assets=False,
        forbids_executable_files=True,
        stable_order=140,
    ),
}


_ALIAS_MAP: Final[dict[str, VplibModuleName]] = {
    # Canonical values
    "manifest": VplibModuleName.MANIFEST,
    "modules": VplibModuleName.MODULES,
    "family": VplibModuleName.FAMILY,
    "variants": VplibModuleName.VARIANTS,
    "editor": VplibModuleName.EDITOR,
    "render": VplibModuleName.RENDER,
    "physical": VplibModuleName.PHYSICAL,
    "material": VplibModuleName.MATERIAL,
    "calculation": VplibModuleName.CALCULATION,
    "analysis": VplibModuleName.ANALYSIS,
    "dynamic": VplibModuleName.DYNAMIC,
    "manufacturer": VplibModuleName.MANUFACTURER,
    "docs": VplibModuleName.DOCS,
    "tests": VplibModuleName.TESTS,
    # Technical aliases
    "vplib_manifest": VplibModuleName.MANIFEST,
    "vplib_manifest_json": VplibModuleName.MANIFEST,
    "vplib.manifest": VplibModuleName.MANIFEST,
    "vplib.manifest.json": VplibModuleName.MANIFEST,
    "vplib_modules": VplibModuleName.MODULES,
    "vplib_modules_json": VplibModuleName.MODULES,
    "vplib.modules": VplibModuleName.MODULES,
    "vplib.modules.json": VplibModuleName.MODULES,
    # Common synonyms
    "families": VplibModuleName.FAMILY,
    "identity": VplibModuleName.FAMILY,
    "classification": VplibModuleName.FAMILY,
    "variant": VplibModuleName.VARIANTS,
    "variant_overrides": VplibModuleName.VARIANTS,
    "inventory": VplibModuleName.EDITOR,
    "placement": VplibModuleName.EDITOR,
    "targeting": VplibModuleName.EDITOR,
    "anchors": VplibModuleName.EDITOR,
    "visual": VplibModuleName.RENDER,
    "graphics": VplibModuleName.RENDER,
    "preview": VplibModuleName.RENDER,
    "assets": VplibModuleName.RENDER,
    "geometry": VplibModuleName.RENDER,
    "dimensions": VplibModuleName.PHYSICAL,
    "collision": VplibModuleName.PHYSICAL,
    "occupancy": VplibModuleName.PHYSICAL,
    "materials": VplibModuleName.MATERIAL,
    "calc": VplibModuleName.CALCULATION,
    "calculations": VplibModuleName.CALCULATION,
    "quantity": VplibModuleName.CALCULATION,
    "quantities": VplibModuleName.CALCULATION,
    "measure": VplibModuleName.CALCULATION,
    "measure_logic": VplibModuleName.CALCULATION,
    "analytics": VplibModuleName.ANALYSIS,
    "profiles": VplibModuleName.ANALYSIS,
    "adaptive": VplibModuleName.DYNAMIC,
    "generator": VplibModuleName.DYNAMIC,
    "bindings": VplibModuleName.DYNAMIC,
    "context": VplibModuleName.DYNAMIC,
    "context_rules": VplibModuleName.DYNAMIC,
    "manufacturing": VplibModuleName.MANUFACTURER,
    "product": VplibModuleName.MANUFACTURER,
    "products": VplibModuleName.MANUFACTURER,
    "contract": VplibModuleName.MANUFACTURER,
    "documentation": VplibModuleName.DOCS,
    "notes": VplibModuleName.DOCS,
    "test": VplibModuleName.TESTS,
    "cases": VplibModuleName.TESTS,
}


_CORE_MODULE_NAMES: Final[tuple[VplibModuleName, ...]] = (
    VplibModuleName.MANIFEST,
    VplibModuleName.MODULES,
    VplibModuleName.FAMILY,
    VplibModuleName.VARIANTS,
    VplibModuleName.EDITOR,
    VplibModuleName.MANUFACTURER,
)

_TECHNICAL_MODULE_NAMES: Final[tuple[VplibModuleName, ...]] = (
    VplibModuleName.MANIFEST,
    VplibModuleName.MODULES,
)

_CONTENT_MODULE_NAMES: Final[tuple[VplibModuleName, ...]] = (
    VplibModuleName.FAMILY,
    VplibModuleName.VARIANTS,
    VplibModuleName.EDITOR,
    VplibModuleName.RENDER,
    VplibModuleName.PHYSICAL,
    VplibModuleName.MATERIAL,
    VplibModuleName.CALCULATION,
    VplibModuleName.ANALYSIS,
    VplibModuleName.DYNAMIC,
    VplibModuleName.MANUFACTURER,
)

_SUPPORT_MODULE_NAMES: Final[tuple[VplibModuleName, ...]] = (
    VplibModuleName.DOCS,
    VplibModuleName.TESTS,
)

_DEFAULT_CREATION_MODULE_NAMES: Final[tuple[VplibModuleName, ...]] = (
    VplibModuleName.MANIFEST,
    VplibModuleName.MODULES,
    VplibModuleName.FAMILY,
    VplibModuleName.VARIANTS,
    VplibModuleName.EDITOR,
    VplibModuleName.RENDER,
    VplibModuleName.PHYSICAL,
    VplibModuleName.MANUFACTURER,
)


def _normalize_key(value: Any) -> str:
    """
    Normalize arbitrary input into a comparable module-name key.

    Raises:
        ModuleNameError: If the value cannot be converted into a usable key.
    """
    try:
        if isinstance(value, VplibModuleName):
            return value.value

        if value is None:
            raise ModuleNameError("Module name is required, got None.")

        raw = str(value).strip()
        if not raw:
            raise ModuleNameError("Module name is required, got an empty value.")

        return (
            raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace("/", "_")
            .replace("\\", "_")
        )
    except ModuleNameError:
        raise
    except Exception as exc:
        raise ModuleNameError(f"Could not normalize module name {value!r}.") from exc


@lru_cache(maxsize=512)
def parse_module_name(value: Any) -> VplibModuleName:
    """
    Parse a module-name input into a canonical VplibModuleName.

    Accepts canonical values and a controlled set of aliases. The result is
    cached because this function is used by planners, validators and scanners.

    Raises:
        ModuleNameError: If the value is unknown.
    """
    key = _normalize_key(value)

    try:
        return VplibModuleName(key)
    except ValueError:
        pass

    try:
        return _ALIAS_MAP[key]
    except KeyError as exc:
        allowed = ", ".join(get_module_name_values())
        raise ModuleNameError(
            f"Unknown VPLIB module name {value!r}. Allowed values: {allowed}."
        ) from exc


def try_parse_module_name(
    value: Any,
    default: VplibModuleName | None = None,
) -> VplibModuleName | None:
    """
    Safe module-name parser.

    Returns default instead of raising ModuleNameError. This is useful for
    non-fatal scan/report paths.
    """
    try:
        return parse_module_name(value)
    except ModuleNameError:
        return default
    except Exception:
        return default


def is_valid_module_name(value: Any) -> bool:
    """Return True if value can be parsed as a canonical VPLIB module name."""
    try:
        parse_module_name(value)
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def get_module_name_values() -> tuple[str, ...]:
    """Return all canonical module-name string values in stable order."""
    return tuple(module.value for module in get_all_module_names())


@lru_cache(maxsize=1)
def get_module_name_aliases() -> Mapping[str, str]:
    """Return a read-only-style mapping of supported aliases to canonical values."""
    return {alias: module.value for alias, module in _ALIAS_MAP.items()}


@lru_cache(maxsize=1)
def get_all_module_names() -> tuple[VplibModuleName, ...]:
    """Return all canonical module names in stable creation order."""
    return tuple(
        definition.name
        for definition in sorted(
            _MODULE_DEFINITIONS.values(),
            key=lambda definition: definition.stable_order,
        )
    )


@lru_cache(maxsize=1)
def get_core_module_names() -> tuple[VplibModuleName, ...]:
    """Return always-required core modules."""
    return _CORE_MODULE_NAMES


@lru_cache(maxsize=1)
def get_technical_module_names() -> tuple[VplibModuleName, ...]:
    """Return top-level technical modules."""
    return _TECHNICAL_MODULE_NAMES


@lru_cache(maxsize=1)
def get_content_module_names() -> tuple[VplibModuleName, ...]:
    """Return content-bearing modules."""
    return _CONTENT_MODULE_NAMES


@lru_cache(maxsize=1)
def get_support_module_names() -> tuple[VplibModuleName, ...]:
    """Return support/documentation/test modules."""
    return _SUPPORT_MODULE_NAMES


@lru_cache(maxsize=1)
def get_default_creation_module_names() -> tuple[VplibModuleName, ...]:
    """Return default modules for a new non-adaptive VPLIB package."""
    return _DEFAULT_CREATION_MODULE_NAMES


@lru_cache(maxsize=1)
def get_module_definitions() -> Mapping[VplibModuleName, ModuleDefinition]:
    """Return all canonical module definitions."""
    return dict(_MODULE_DEFINITIONS)


@lru_cache(maxsize=128)
def get_module_definition(value: Any) -> ModuleDefinition:
    """
    Return the module definition for a module-name value.

    Raises:
        ModuleNameError: If the value is unknown or the definition is missing.
    """
    module = parse_module_name(value)

    try:
        return _MODULE_DEFINITIONS[module]
    except KeyError as exc:
        raise ModuleNameError(f"Missing module definition for {module.value!r}.") from exc


def ensure_module_name(value: Any) -> VplibModuleName:
    """
    Strict parser for call sites that require a valid module name.
    """
    return parse_module_name(value)


def ensure_module_name_value(value: Any) -> str:
    """Return the canonical string value for a module-name input."""
    return ensure_module_name(value).value


def filter_valid_module_names(values: Iterable[Any]) -> tuple[VplibModuleName, ...]:
    """
    Parse many values and return only valid module names.

    Invalid entries are ignored. Duplicates are removed while preserving stable
    input order.
    """
    result: list[VplibModuleName] = []
    seen: set[VplibModuleName] = set()

    for value in values:
        module = try_parse_module_name(value)
        if module is None or module in seen:
            continue
        result.append(module)
        seen.add(module)

    return tuple(result)


def sort_module_names(values: Iterable[Any]) -> tuple[VplibModuleName, ...]:
    """
    Parse and sort module names by canonical stable order.

    Invalid values raise ModuleNameError.
    """
    modules = {parse_module_name(value) for value in values}

    return tuple(
        module
        for module in get_all_module_names()
        if module in modules
    )


def dedupe_module_names(values: Iterable[Any]) -> tuple[VplibModuleName, ...]:
    """
    Parse module names, remove duplicates and preserve input order.

    Invalid values raise ModuleNameError.
    """
    result: list[VplibModuleName] = []
    seen: set[VplibModuleName] = set()

    for value in values:
        module = parse_module_name(value)
        if module in seen:
            continue
        result.append(module)
        seen.add(module)

    return tuple(result)


def merge_module_names(*groups: Iterable[Any]) -> tuple[VplibModuleName, ...]:
    """
    Merge multiple module-name iterables and return a stable-order result.

    Invalid values raise ModuleNameError.
    """
    merged: set[VplibModuleName] = set()

    for group in groups:
        for value in group:
            merged.add(parse_module_name(value))

    return tuple(
        module
        for module in get_all_module_names()
        if module in merged
    )


def module_name_values(values: Iterable[Any]) -> tuple[str, ...]:
    """Return canonical string values for a module-name iterable."""
    return tuple(module.value for module in dedupe_module_names(values))


def required_document_names(value: Any) -> tuple[str, ...]:
    """Return required document names for a module."""
    return get_module_definition(value).required_document_names


def optional_document_names(value: Any) -> tuple[str, ...]:
    """Return optional document names for a module."""
    return get_module_definition(value).optional_document_names


def top_level_file_name(value: Any) -> str | None:
    """Return the top-level file name for a module, if any."""
    return get_module_definition(value).top_level_file


def directory_name(value: Any) -> str | None:
    """Return the directory name for a module, if any."""
    return get_module_definition(value).directory_name


def module_dependencies(value: Any) -> tuple[VplibModuleName, ...]:
    """Return direct module dependencies for a module."""
    return get_module_definition(value).depends_on


def module_mutual_exclusions(value: Any) -> tuple[VplibModuleName, ...]:
    """Return mutually exclusive modules for a module."""
    return get_module_definition(value).mutually_exclusive_with


def module_allows_assets(value: Any) -> bool:
    """Return whether a module can contain or reference assets."""
    return get_module_definition(value).allows_assets


def module_allows_binary_assets(value: Any) -> bool:
    """Return whether a module can contain binary assets."""
    return get_module_definition(value).allows_binary_assets


def module_allows_markdown_documents(value: Any) -> bool:
    """Return whether a module can contain Markdown documents."""
    return get_module_definition(value).allows_markdown_documents


def module_allows_json_documents(value: Any) -> bool:
    """Return whether a module can contain JSON documents."""
    return get_module_definition(value).allows_json_documents


def module_forbids_executable_files(value: Any) -> bool:
    """Return whether executable files are forbidden in this module."""
    return get_module_definition(value).forbids_executable_files


def module_participates_in_archive(value: Any) -> bool:
    """Return whether the module participates in .vplib archives."""
    return get_module_definition(value).participates_in_archive


def module_participates_in_checksum(value: Any) -> bool:
    """Return whether the module participates in package checksums."""
    return get_module_definition(value).participates_in_checksum


def validate_module_dependencies(values: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """
    Validate direct module dependencies for a set of active modules.

    Returns:
        Tuple of (is_valid, messages).
    """
    messages: list[str] = []

    try:
        active_modules = set(dedupe_module_names(values))
    except ModuleNameError as exc:
        return False, (str(exc),)
    except Exception as exc:
        return False, (f"Could not validate module dependencies: {exc}",)

    for module in active_modules:
        definition = get_module_definition(module)

        for dependency in definition.depends_on:
            if dependency not in active_modules:
                messages.append(
                    f"Module {module.value!r} requires dependency {dependency.value!r}."
                )

        for excluded in definition.mutually_exclusive_with:
            if excluded in active_modules:
                messages.append(
                    f"Module {module.value!r} is mutually exclusive with {excluded.value!r}."
                )

    return len(messages) == 0, tuple(messages)


def validate_core_modules_present(values: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """
    Validate that all core modules are present in an active module set.

    Returns:
        Tuple of (is_valid, messages).
    """
    messages: list[str] = []

    try:
        active_modules = set(dedupe_module_names(values))
    except ModuleNameError as exc:
        return False, (str(exc),)
    except Exception as exc:
        return False, (f"Could not validate core modules: {exc}",)

    for module in get_core_module_names():
        if module not in active_modules:
            messages.append(f"Required core module {module.value!r} is missing.")

    return len(messages) == 0, tuple(messages)


def validate_module_set(values: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """
    Validate an active module set.

    Checks:
    - values are valid module names
    - core modules are present
    - dependencies are present
    - mutually exclusive modules are not active together

    Returns:
        Tuple of (is_valid, messages).
    """
    messages: list[str] = []

    core_valid, core_messages = validate_core_modules_present(values)
    messages.extend(core_messages)

    dependency_valid, dependency_messages = validate_module_dependencies(values)
    messages.extend(dependency_messages)

    return core_valid and dependency_valid and not messages, tuple(messages)


def assert_valid_module_set(values: Iterable[Any]) -> None:
    """
    Raise ModuleNameError if an active module set is invalid.
    """
    is_valid, messages = validate_module_set(values)
    if not is_valid:
        joined = " ".join(messages) if messages else "Invalid module set."
        raise ModuleNameError(joined)


def module_definition_to_json(value: Any) -> dict[str, Any]:
    """
    Serialize one module definition into a JSON-compatible dictionary.
    """
    definition = get_module_definition(value)

    return {
        "schema_version": MODULE_NAME_SCHEMA_VERSION,
        "name": definition.name.value,
        "title": definition.title,
        "description": definition.description,
        "required_by_core": definition.required_by_core,
        "top_level_file": definition.top_level_file,
        "directory_name": definition.directory_name,
        "required_document_names": list(definition.required_document_names),
        "optional_document_names": list(definition.optional_document_names),
        "depends_on": [module.value for module in definition.depends_on],
        "mutually_exclusive_with": [
            module.value for module in definition.mutually_exclusive_with
        ],
        "can_be_empty_initially": definition.can_be_empty_initially,
        "participates_in_archive": definition.participates_in_archive,
        "participates_in_checksum": definition.participates_in_checksum,
        "allows_assets": definition.allows_assets,
        "allows_json_documents": definition.allows_json_documents,
        "allows_markdown_documents": definition.allows_markdown_documents,
        "allows_binary_assets": definition.allows_binary_assets,
        "forbids_executable_files": definition.forbids_executable_files,
        "stable_order": definition.stable_order,
    }


def all_module_definitions_to_json() -> list[dict[str, Any]]:
    """Serialize all module definitions into JSON-compatible dictionaries."""
    return [module_definition_to_json(module) for module in get_all_module_names()]


def build_modules_manifest_payload(
    active_modules: Iterable[Any],
    *,
    required_modules: Iterable[Any] | None = None,
    optional_modules: Iterable[Any] | None = None,
    profile_key: str | None = None,
) -> dict[str, Any]:
    """
    Build a JSON-compatible payload for vplib.modules.json.

    This helper does not write files. It only creates a stable payload that later
    document builders can extend.
    """
    active = sort_module_names(active_modules)
    required = (
        sort_module_names(required_modules)
        if required_modules is not None
        else tuple(module for module in active if get_module_definition(module).required_by_core)
    )
    optional = (
        sort_module_names(optional_modules)
        if optional_modules is not None
        else tuple(module for module in active if module not in required)
    )

    return {
        "schema_version": "vplib.modules.v1",
        "profile_key": profile_key,
        "active_modules": [module.value for module in active],
        "required_modules": [module.value for module in required],
        "optional_modules": [module.value for module in optional],
        "module_definitions_version": MODULE_NAME_SCHEMA_VERSION,
    }


def clear_module_name_caches() -> None:
    """
    Clear internal lru_cache state.

    Useful for tests and long-running developer sessions.
    """
    parse_module_name.cache_clear()
    get_module_name_values.cache_clear()
    get_module_name_aliases.cache_clear()
    get_all_module_names.cache_clear()
    get_core_module_names.cache_clear()
    get_technical_module_names.cache_clear()
    get_content_module_names.cache_clear()
    get_support_module_names.cache_clear()
    get_default_creation_module_names.cache_clear()
    get_module_definitions.cache_clear()
    get_module_definition.cache_clear()


__all__ = [
    "MODULE_NAME_SCHEMA_VERSION",
    "ModuleDefinition",
    "ModuleNameError",
    "VplibModuleName",
    "all_module_definitions_to_json",
    "assert_valid_module_set",
    "build_modules_manifest_payload",
    "clear_module_name_caches",
    "dedupe_module_names",
    "directory_name",
    "ensure_module_name",
    "ensure_module_name_value",
    "filter_valid_module_names",
    "get_all_module_names",
    "get_content_module_names",
    "get_core_module_names",
    "get_default_creation_module_names",
    "get_module_definition",
    "get_module_definitions",
    "get_module_name_aliases",
    "get_module_name_values",
    "get_support_module_names",
    "get_technical_module_names",
    "is_valid_module_name",
    "merge_module_names",
    "module_allows_assets",
    "module_allows_binary_assets",
    "module_allows_json_documents",
    "module_allows_markdown_documents",
    "module_definition_to_json",
    "module_dependencies",
    "module_forbids_executable_files",
    "module_mutual_exclusions",
    "module_name_values",
    "module_participates_in_archive",
    "module_participates_in_checksum",
    "optional_document_names",
    "parse_module_name",
    "required_document_names",
    "sort_module_names",
    "top_level_file_name",
    "try_parse_module_name",
    "validate_core_modules_present",
    "validate_module_dependencies",
    "validate_module_set",
]