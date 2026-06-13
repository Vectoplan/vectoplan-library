# services/vectoplan-library/src/vplib/domain/package_paths.py
"""
Canonical VPLIB package-path definitions.

This module defines the stable directory and file layout for modular VPLIB
packages. It does not create files and it does not validate JSON content.
It provides canonical path knowledge for planners, creators, validators,
archive writers and future scanners.

Important invariants:
- All VPLIB package paths are relative paths.
- Absolute paths are never valid package paths.
- Parent traversal is never valid package-path syntax.
- Executable files are forbidden inside VPLIB packages.
- The modular directory layout is the package contract.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any, Final, Iterable, Mapping, Sequence


PACKAGE_PATH_SCHEMA_VERSION: Final[str] = "vplib.package_paths.v1"

VPLIB_MANIFEST_FILE: Final[str] = "vplib.manifest.json"
VPLIB_MODULES_FILE: Final[str] = "vplib.modules.json"

VARIANT_FILE_PATTERN: Final[str] = "variants/{variant_id}.json"

SAFE_PATH_RE: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z0-9._\-/]+$")
SAFE_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9._-]*[a-z0-9]$|^[a-z0-9]$")

FORBIDDEN_PATH_PARTS: Final[frozenset[str]] = frozenset(
    {
        "",
        ".",
        "..",
        "~",
    }
)

FORBIDDEN_FILE_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".bat",
        ".bin",
        ".cmd",
        ".com",
        ".csh",
        ".dll",
        ".dmg",
        ".elf",
        ".exe",
        ".js",
        ".jse",
        ".ksh",
        ".msi",
        ".msp",
        ".pif",
        ".ps1",
        ".py",
        ".pyc",
        ".pyo",
        ".rb",
        ".run",
        ".scr",
        ".sh",
        ".so",
        ".vbe",
        ".vbs",
        ".wsf",
    }
)

JSON_FILE_EXTENSION: Final[str] = ".json"
MARKDOWN_FILE_EXTENSION: Final[str] = ".md"

ALLOWED_ASSET_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".glb",
        ".gltf",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".ktx2",
        ".basis",
    }
)

ALLOWED_TEXT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".json",
        ".md",
        ".txt",
    }
)

ALLOWED_PACKAGE_EXTENSIONS: Final[frozenset[str]] = (
    ALLOWED_ASSET_EXTENSIONS | ALLOWED_TEXT_EXTENSIONS
)


class PackagePathError(ValueError):
    """Raised when a VPLIB package path is invalid or unknown."""


class PackagePathKind(str, Enum):
    """Canonical package-path kind."""

    TOP_LEVEL_FILE = "top_level_file"
    MODULE_DIRECTORY = "module_directory"
    MODULE_DOCUMENT = "module_document"
    MODULE_ASSET = "module_asset"
    DYNAMIC_DOCUMENT = "dynamic_document"
    GENERATED_DOCUMENT = "generated_document"

    @property
    def key(self) -> str:
        """Return the canonical string key."""
        return str(self.value)


@dataclass(frozen=True, slots=True)
class PackagePathDefinition:
    """
    Canonical definition for one VPLIB package path.

    The path value is always a POSIX-style relative path.
    """

    key: str
    path: str
    kind: PackagePathKind
    module: str
    required: bool
    description: str
    allowed_extensions: tuple[str, ...]
    participates_in_archive: bool
    participates_in_checksum: bool
    may_be_generated: bool
    may_be_user_authored: bool


@dataclass(frozen=True, slots=True)
class ModulePathDefinition:
    """
    Canonical directory and file layout for a VPLIB module.
    """

    module: str
    directory: str | None
    top_level_file: str | None
    required_files: tuple[str, ...]
    optional_files: tuple[str, ...]
    asset_files: tuple[str, ...]
    generated_files: tuple[str, ...]
    allowed_subdirectories: tuple[str, ...]
    forbids_executable_files: bool
    participates_in_archive: bool


def _module_value(value: Any) -> str:
    """
    Convert a module value into a canonical module string.

    Uses module_names.py if available, but remains safe during early bootstrap.
    """
    try:
        from .module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception:
        try:
            raw = str(value).strip()
            if not raw:
                raise PackagePathError("Module value is required.")
            return (
                raw.lower()
                .replace(" ", "_")
                .replace("-", "_")
                .replace("/", "_")
                .replace("\\", "_")
            )
        except PackagePathError:
            raise
        except Exception as exc:
            raise PackagePathError(f"Invalid module value {value!r}.") from exc


_MODULE_PATH_DEFINITIONS: Final[dict[str, ModulePathDefinition]] = {
    "manifest": ModulePathDefinition(
        module="manifest",
        directory=None,
        top_level_file=VPLIB_MANIFEST_FILE,
        required_files=(VPLIB_MANIFEST_FILE,),
        optional_files=tuple(),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "modules": ModulePathDefinition(
        module="modules",
        directory=None,
        top_level_file=VPLIB_MODULES_FILE,
        required_files=(VPLIB_MODULES_FILE,),
        optional_files=tuple(),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "family": ModulePathDefinition(
        module="family",
        directory="family",
        top_level_file=None,
        required_files=(
            "family/identity.json",
            "family/classification.json",
        ),
        optional_files=(
            "family/lifecycle.json",
            "family/aliases.json",
            "family/metadata.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "variants": ModulePathDefinition(
        module="variants",
        directory="variants",
        top_level_file=None,
        required_files=(
            "variants/index.json",
            "variants/default.json",
        ),
        optional_files=tuple(),
        asset_files=tuple(),
        generated_files=(
            "variants/resolved.json",
        ),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "editor": ModulePathDefinition(
        module="editor",
        directory="editor",
        top_level_file=None,
        required_files=(
            "editor/inventory.json",
            "editor/placement.json",
        ),
        optional_files=(
            "editor/targeting.json",
            "editor/anchors.json",
            "editor/sockets.json",
            "editor/ports.json",
            "editor/tools.json",
            "editor/hotbar.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "render": ModulePathDefinition(
        module="render",
        directory="render",
        top_level_file=None,
        required_files=(
            "render/render_variants.json",
        ),
        optional_files=(
            "render/bounds.json",
            "render/materials.json",
            "render/lod.json",
        ),
        asset_files=(
            "render/icon.svg",
            "render/preview.webp",
            "render/mesh.glb",
        ),
        generated_files=tuple(),
        allowed_subdirectories=(
            "render/textures",
            "render/models",
            "render/previews",
            "render/icons",
        ),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "physical": ModulePathDefinition(
        module="physical",
        directory="physical",
        top_level_file=None,
        required_files=(
            "physical/base.json",
            "physical/dimensions.json",
            "physical/collision.json",
        ),
        optional_files=(
            "physical/layers.json",
            "physical/occupancy.json",
            "physical/mass.json",
            "physical/bounds.json",
            "physical/footprint.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "material": ModulePathDefinition(
        module="material",
        directory="material",
        top_level_file=None,
        required_files=(
            "material/base.json",
        ),
        optional_files=(
            "material/performance.json",
            "material/surfaces.json",
            "material/layers.json",
            "material/finishes.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "calculation": ModulePathDefinition(
        module="calculation",
        directory="calculation",
        top_level_file=None,
        required_files=(
            "calculation/variables.json",
            "calculation/formulas.json",
            "calculation/quantities.json",
            "calculation/measure_logic.json",
        ),
        optional_files=(
            "calculation/constraints.json",
            "calculation/units.json",
            "calculation/cost_factors.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "analysis": ModulePathDefinition(
        module="analysis",
        directory="analysis",
        top_level_file=None,
        required_files=tuple(),
        optional_files=(
            "analysis/statics/profile.json",
            "analysis/energy/profile.json",
            "analysis/acoustics/profile.json",
            "analysis/routing/profile.json",
            "analysis/reinforcement/profile.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=(
            "analysis/statics",
            "analysis/energy",
            "analysis/acoustics",
            "analysis/routing",
            "analysis/reinforcement",
        ),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "dynamic": ModulePathDefinition(
        module="dynamic",
        directory="dynamic",
        top_level_file=None,
        required_files=(
            "dynamic/context_rules.json",
            "dynamic/bindings.json",
            "dynamic/generator.json",
        ),
        optional_files=(
            "dynamic/parameters.json",
            "dynamic/constraints.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "manufacturer": ModulePathDefinition(
        module="manufacturer",
        directory="manufacturer",
        top_level_file=None,
        required_files=(
            "manufacturer/contract.json",
        ),
        optional_files=(
            "manufacturer/override_slots.json",
            "manufacturer/product_mapping.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=tuple(),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "docs": ModulePathDefinition(
        module="docs",
        directory="docs",
        top_level_file=None,
        required_files=tuple(),
        optional_files=(
            "docs/notes.md",
            "docs/changelog.md",
            "docs/authoring.md",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=(
            "docs/assets",
        ),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
    "tests": ModulePathDefinition(
        module="tests",
        directory="tests",
        top_level_file=None,
        required_files=tuple(),
        optional_files=(
            "tests/cases.json",
            "tests/fixtures.json",
        ),
        asset_files=tuple(),
        generated_files=tuple(),
        allowed_subdirectories=(
            "tests/fixtures",
        ),
        forbids_executable_files=True,
        participates_in_archive=True,
    ),
}


def _build_path_definitions() -> dict[str, PackagePathDefinition]:
    definitions: dict[str, PackagePathDefinition] = {}

    for module, module_definition in _MODULE_PATH_DEFINITIONS.items():
        if module_definition.top_level_file:
            path = module_definition.top_level_file
            definitions[f"{module}:top_level"] = PackagePathDefinition(
                key=f"{module}:top_level",
                path=path,
                kind=PackagePathKind.TOP_LEVEL_FILE,
                module=module,
                required=True,
                description=f"Top-level file for module {module}.",
                allowed_extensions=(JSON_FILE_EXTENSION,),
                participates_in_archive=True,
                participates_in_checksum=True,
                may_be_generated=True,
                may_be_user_authored=False,
            )

        if module_definition.directory:
            definitions[f"{module}:directory"] = PackagePathDefinition(
                key=f"{module}:directory",
                path=module_definition.directory,
                kind=PackagePathKind.MODULE_DIRECTORY,
                module=module,
                required=bool(module_definition.required_files),
                description=f"Directory for module {module}.",
                allowed_extensions=tuple(),
                participates_in_archive=False,
                participates_in_checksum=False,
                may_be_generated=True,
                may_be_user_authored=False,
            )

        for path in module_definition.required_files:
            definitions[f"{module}:required:{path}"] = PackagePathDefinition(
                key=f"{module}:required:{path}",
                path=path,
                kind=PackagePathKind.MODULE_DOCUMENT,
                module=module,
                required=True,
                description=f"Required document for module {module}.",
                allowed_extensions=(JSON_FILE_EXTENSION,),
                participates_in_archive=True,
                participates_in_checksum=True,
                may_be_generated=True,
                may_be_user_authored=True,
            )

        for path in module_definition.optional_files:
            extension = PurePosixPath(path).suffix.lower()
            allowed_extensions = (
                (MARKDOWN_FILE_EXTENSION,)
                if extension == MARKDOWN_FILE_EXTENSION
                else (JSON_FILE_EXTENSION,)
            )
            definitions[f"{module}:optional:{path}"] = PackagePathDefinition(
                key=f"{module}:optional:{path}",
                path=path,
                kind=PackagePathKind.MODULE_DOCUMENT,
                module=module,
                required=False,
                description=f"Optional document for module {module}.",
                allowed_extensions=allowed_extensions,
                participates_in_archive=True,
                participates_in_checksum=True,
                may_be_generated=True,
                may_be_user_authored=True,
            )

        for path in module_definition.asset_files:
            definitions[f"{module}:asset:{path}"] = PackagePathDefinition(
                key=f"{module}:asset:{path}",
                path=path,
                kind=PackagePathKind.MODULE_ASSET,
                module=module,
                required=False,
                description=f"Asset for module {module}.",
                allowed_extensions=tuple(sorted(ALLOWED_ASSET_EXTENSIONS)),
                participates_in_archive=True,
                participates_in_checksum=True,
                may_be_generated=False,
                may_be_user_authored=True,
            )

        for path in module_definition.generated_files:
            definitions[f"{module}:generated:{path}"] = PackagePathDefinition(
                key=f"{module}:generated:{path}",
                path=path,
                kind=PackagePathKind.GENERATED_DOCUMENT,
                module=module,
                required=False,
                description=f"Generated document for module {module}.",
                allowed_extensions=(JSON_FILE_EXTENSION,),
                participates_in_archive=False,
                participates_in_checksum=False,
                may_be_generated=True,
                may_be_user_authored=False,
            )

    return definitions


_PACKAGE_PATH_DEFINITIONS: Final[dict[str, PackagePathDefinition]] = _build_path_definitions()


def normalize_package_path(value: Any) -> str:
    """
    Normalize a VPLIB package path to a POSIX-style relative path.

    Raises:
        PackagePathError: If the path is empty, absolute, unsafe or traverses parents.
    """
    try:
        if value is None:
            raise PackagePathError("Package path is required, got None.")

        raw = str(value).strip()
        if not raw:
            raise PackagePathError("Package path is required, got an empty value.")

        normalized = raw.replace("\\", "/")
        normalized = posixpath.normpath(normalized)

        if normalized == ".":
            raise PackagePathError("Package path cannot resolve to current directory.")

        if normalized.startswith("/"):
            raise PackagePathError(f"Package path must be relative: {raw!r}.")

        if normalized.startswith("../") or normalized == "..":
            raise PackagePathError(f"Package path cannot traverse parents: {raw!r}.")

        if "//" in normalized:
            raise PackagePathError(f"Package path contains empty segments: {raw!r}.")

        parts = PurePosixPath(normalized).parts
        if any(part in FORBIDDEN_PATH_PARTS for part in parts):
            raise PackagePathError(f"Package path contains forbidden segment: {raw!r}.")

        if not SAFE_PATH_RE.match(normalized):
            raise PackagePathError(f"Package path contains unsafe characters: {raw!r}.")

        return normalized
    except PackagePathError:
        raise
    except Exception as exc:
        raise PackagePathError(f"Could not normalize package path {value!r}.") from exc


def try_normalize_package_path(value: Any, default: str | None = None) -> str | None:
    """
    Safe package-path normalizer.

    Returns default instead of raising PackagePathError.
    """
    try:
        return normalize_package_path(value)
    except Exception:
        return default


def is_valid_package_path(value: Any) -> bool:
    """Return True if value is a valid relative VPLIB package path."""
    try:
        normalize_package_path(value)
        return True
    except Exception:
        return False


def path_extension(value: Any) -> str:
    """Return the lowercase extension for a package path."""
    normalized = normalize_package_path(value)
    return PurePosixPath(normalized).suffix.lower()


def has_forbidden_extension(value: Any) -> bool:
    """Return whether the package path has a forbidden executable extension."""
    try:
        extension = path_extension(value)
        return extension in FORBIDDEN_FILE_EXTENSIONS
    except Exception:
        return True


def is_allowed_package_file_extension(value: Any) -> bool:
    """
    Return whether a package path has an allowed file extension.

    Directories usually have no extension and should be checked separately.
    """
    try:
        extension = path_extension(value)
        if not extension:
            return False
        if extension in FORBIDDEN_FILE_EXTENSIONS:
            return False
        return extension in ALLOWED_PACKAGE_EXTENSIONS
    except Exception:
        return False


def assert_safe_package_file_path(value: Any) -> None:
    """
    Raise PackagePathError if a package file path is unsafe or has a forbidden extension.
    """
    normalized = normalize_package_path(value)
    extension = PurePosixPath(normalized).suffix.lower()

    if not extension:
        raise PackagePathError(f"Package file path has no extension: {normalized!r}.")

    if extension in FORBIDDEN_FILE_EXTENSIONS:
        raise PackagePathError(
            f"Executable or forbidden file type is not allowed in VPLIB packages: {normalized!r}."
        )

    if extension not in ALLOWED_PACKAGE_EXTENSIONS:
        raise PackagePathError(
            f"File extension {extension!r} is not allowed in VPLIB packages: {normalized!r}."
        )


@lru_cache(maxsize=1)
def get_module_path_definitions() -> Mapping[str, ModulePathDefinition]:
    """Return all module path definitions."""
    return dict(_MODULE_PATH_DEFINITIONS)


@lru_cache(maxsize=64)
def get_module_path_definition(module: Any) -> ModulePathDefinition:
    """Return the path definition for a module."""
    module_value = _module_value(module)

    try:
        return _MODULE_PATH_DEFINITIONS[module_value]
    except KeyError as exc:
        raise PackagePathError(f"Unknown module path definition: {module!r}.") from exc


@lru_cache(maxsize=1)
def get_package_path_definitions() -> Mapping[str, PackagePathDefinition]:
    """Return all canonical package path definitions."""
    return dict(_PACKAGE_PATH_DEFINITIONS)


@lru_cache(maxsize=256)
def get_package_path_definition_by_path(path: Any) -> PackagePathDefinition | None:
    """Return a canonical path definition by path, if known."""
    normalized = normalize_package_path(path)

    for definition in _PACKAGE_PATH_DEFINITIONS.values():
        if definition.path == normalized:
            return definition

    return None


def is_known_package_path(path: Any) -> bool:
    """Return whether a path is part of the canonical package-path definition set."""
    try:
        return get_package_path_definition_by_path(path) is not None
    except Exception:
        return False


def get_top_level_files() -> tuple[str, ...]:
    """Return canonical top-level VPLIB files."""
    return (
        VPLIB_MANIFEST_FILE,
        VPLIB_MODULES_FILE,
    )


def get_module_directory(module: Any) -> str | None:
    """Return the module directory for a module, if any."""
    return get_module_path_definition(module).directory


def get_module_top_level_file(module: Any) -> str | None:
    """Return the top-level file for a module, if any."""
    return get_module_path_definition(module).top_level_file


def get_required_files_for_module(module: Any) -> tuple[str, ...]:
    """Return required files for a module."""
    return get_module_path_definition(module).required_files


def get_optional_files_for_module(module: Any) -> tuple[str, ...]:
    """Return optional files for a module."""
    return get_module_path_definition(module).optional_files


def get_asset_files_for_module(module: Any) -> tuple[str, ...]:
    """Return canonical asset files for a module."""
    return get_module_path_definition(module).asset_files


def get_generated_files_for_module(module: Any) -> tuple[str, ...]:
    """Return generated files for a module."""
    return get_module_path_definition(module).generated_files


def get_allowed_subdirectories_for_module(module: Any) -> tuple[str, ...]:
    """Return allowed subdirectories for a module."""
    return get_module_path_definition(module).allowed_subdirectories


def get_required_files_for_modules(modules: Iterable[Any]) -> tuple[str, ...]:
    """Return required files for several modules in stable module order."""
    paths: list[str] = []

    for module in _stable_module_values(modules):
        paths.extend(get_required_files_for_module(module))

    return tuple(dict.fromkeys(paths))


def get_optional_files_for_modules(modules: Iterable[Any]) -> tuple[str, ...]:
    """Return optional files for several modules in stable module order."""
    paths: list[str] = []

    for module in _stable_module_values(modules):
        paths.extend(get_optional_files_for_module(module))

    return tuple(dict.fromkeys(paths))


def get_module_directories_for_modules(modules: Iterable[Any]) -> tuple[str, ...]:
    """Return module directories for several modules in stable module order."""
    directories: list[str] = []

    for module in _stable_module_values(modules):
        directory = get_module_directory(module)
        if directory:
            directories.append(directory)

    return tuple(dict.fromkeys(directories))


def get_allowed_subdirectories_for_modules(modules: Iterable[Any]) -> tuple[str, ...]:
    """Return allowed subdirectories for several modules in stable module order."""
    directories: list[str] = []

    for module in _stable_module_values(modules):
        directories.extend(get_allowed_subdirectories_for_module(module))

    return tuple(dict.fromkeys(directories))


def _stable_module_values(modules: Iterable[Any]) -> tuple[str, ...]:
    """
    Return module string values in canonical stable order.

    Uses module_names.py if available. Falls back to local definition order.
    """
    raw_modules = tuple(modules)

    try:
        from .module_names import sort_module_names

        return tuple(module.value for module in sort_module_names(raw_modules))
    except Exception:
        requested = {_module_value(module) for module in raw_modules}
        return tuple(
            module
            for module in _MODULE_PATH_DEFINITIONS.keys()
            if module in requested
        )


def make_variant_file_path(variant_id: Any) -> str:
    """
    Build a safe variants/<variant_id>.json path.

    Raises:
        PackagePathError: If the variant id is unsafe.
    """
    try:
        raw = str(variant_id).strip()
        if not raw:
            raise PackagePathError("Variant id is required.")

        normalized = raw.lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
        normalized = normalized.replace("..", "_")

        if not SAFE_SLUG_RE.match(normalized):
            raise PackagePathError(f"Unsafe variant id: {variant_id!r}.")

        return normalize_package_path(VARIANT_FILE_PATTERN.format(variant_id=normalized))
    except PackagePathError:
        raise
    except Exception as exc:
        raise PackagePathError(f"Could not build variant path for {variant_id!r}.") from exc


def make_render_texture_path(filename: Any) -> str:
    """Build a safe render/textures/<filename> path."""
    return make_asset_path("render/textures", filename)


def make_render_model_path(filename: Any) -> str:
    """Build a safe render/models/<filename> path."""
    return make_asset_path("render/models", filename)


def make_render_preview_path(filename: Any) -> str:
    """Build a safe render/previews/<filename> path."""
    return make_asset_path("render/previews", filename)


def make_render_icon_path(filename: Any) -> str:
    """Build a safe render/icons/<filename> path."""
    return make_asset_path("render/icons", filename)


def make_asset_path(directory: Any, filename: Any) -> str:
    """
    Build a safe asset path under a package-relative directory.

    Raises:
        PackagePathError: If the directory or filename is unsafe.
    """
    try:
        safe_directory = normalize_package_path(directory)
        safe_filename = str(filename).strip().replace("\\", "/")

        if not safe_filename:
            raise PackagePathError("Asset filename is required.")

        if "/" in safe_filename:
            raise PackagePathError("Asset filename must not contain path separators.")

        candidate = normalize_package_path(f"{safe_directory}/{safe_filename}")
        assert_safe_package_file_path(candidate)

        extension = PurePosixPath(candidate).suffix.lower()
        if extension not in ALLOWED_ASSET_EXTENSIONS:
            raise PackagePathError(
                f"Asset extension {extension!r} is not allowed: {candidate!r}."
            )

        return candidate
    except PackagePathError:
        raise
    except Exception as exc:
        raise PackagePathError(f"Could not build asset path for {filename!r}.") from exc


def resolve_relative_package_path(*parts: Any) -> str:
    """
    Join path parts into a normalized safe package-relative path.
    """
    try:
        string_parts = [str(part).strip().replace("\\", "/") for part in parts if str(part).strip()]
        if not string_parts:
            raise PackagePathError("At least one path part is required.")
        return normalize_package_path(posixpath.join(*string_parts))
    except PackagePathError:
        raise
    except Exception as exc:
        raise PackagePathError(f"Could not resolve package path from parts {parts!r}.") from exc


def is_path_under_module(path: Any, module: Any) -> bool:
    """Return whether a path belongs to the given module."""
    try:
        normalized = normalize_package_path(path)
        module_value = _module_value(module)
        definition = get_module_path_definition(module_value)

        if definition.top_level_file and normalized == definition.top_level_file:
            return True

        if definition.directory:
            return normalized == definition.directory or normalized.startswith(
                f"{definition.directory}/"
            )

        return False
    except Exception:
        return False


def infer_module_from_path(path: Any) -> str | None:
    """
    Infer a module from a VPLIB package path.

    Returns None if no module can be inferred.
    """
    try:
        normalized = normalize_package_path(path)

        for module, definition in _MODULE_PATH_DEFINITIONS.items():
            if definition.top_level_file and normalized == definition.top_level_file:
                return module

            if definition.directory and (
                normalized == definition.directory
                or normalized.startswith(f"{definition.directory}/")
            ):
                return module

        return None
    except Exception:
        return None


def classify_package_path(path: Any) -> PackagePathKind | None:
    """
    Classify a package path by known definitions and structure.

    Returns None for invalid paths.
    """
    try:
        normalized = normalize_package_path(path)

        definition = get_package_path_definition_by_path(normalized)
        if definition is not None:
            return definition.kind

        module = infer_module_from_path(normalized)
        if module is None:
            return None

        extension = PurePosixPath(normalized).suffix.lower()

        if extension in ALLOWED_ASSET_EXTENSIONS:
            return PackagePathKind.MODULE_ASSET

        if extension in ALLOWED_TEXT_EXTENSIONS:
            return PackagePathKind.MODULE_DOCUMENT

        if not extension:
            return PackagePathKind.MODULE_DIRECTORY

        return None
    except Exception:
        return None


def validate_package_paths(paths: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """
    Validate a collection of package-relative paths.

    Returns:
        Tuple of (is_valid, messages).
    """
    messages: list[str] = []

    for path in paths:
        try:
            normalized = normalize_package_path(path)

            if PurePosixPath(normalized).suffix:
                assert_safe_package_file_path(normalized)

            module = infer_module_from_path(normalized)
            if module is None:
                messages.append(f"Path is not under a known VPLIB module: {normalized!r}.")

        except PackagePathError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate path {path!r}: {exc}")

    return len(messages) == 0, tuple(messages)


def assert_valid_package_paths(paths: Iterable[Any]) -> None:
    """
    Raise PackagePathError if any package path is invalid.
    """
    is_valid, messages = validate_package_paths(paths)
    if not is_valid:
        joined = " ".join(messages) if messages else "Invalid package paths."
        raise PackagePathError(joined)


def validate_required_paths_present(
    active_modules: Iterable[Any],
    existing_paths: Iterable[Any],
) -> tuple[bool, tuple[str, ...]]:
    """
    Validate that all required paths for active modules are present.

    This checks only path presence, not file content.
    """
    messages: list[str] = []

    try:
        required_paths = set(get_required_files_for_modules(active_modules))
        normalized_existing = {
            normalize_package_path(path)
            for path in existing_paths
        }

        for required_path in sorted(required_paths):
            if required_path not in normalized_existing:
                messages.append(f"Required VPLIB file is missing: {required_path!r}.")
    except PackagePathError as exc:
        messages.append(str(exc))
    except Exception as exc:
        messages.append(f"Could not validate required package paths: {exc}")

    return len(messages) == 0, tuple(messages)


def path_definition_to_json(definition: PackagePathDefinition) -> dict[str, Any]:
    """Serialize a package path definition into a JSON-compatible dictionary."""
    return {
        "schema_version": PACKAGE_PATH_SCHEMA_VERSION,
        "key": definition.key,
        "path": definition.path,
        "kind": definition.kind.value,
        "module": definition.module,
        "required": definition.required,
        "description": definition.description,
        "allowed_extensions": list(definition.allowed_extensions),
        "participates_in_archive": definition.participates_in_archive,
        "participates_in_checksum": definition.participates_in_checksum,
        "may_be_generated": definition.may_be_generated,
        "may_be_user_authored": definition.may_be_user_authored,
    }


def module_path_definition_to_json(definition: ModulePathDefinition) -> dict[str, Any]:
    """Serialize a module path definition into a JSON-compatible dictionary."""
    return {
        "schema_version": PACKAGE_PATH_SCHEMA_VERSION,
        "module": definition.module,
        "directory": definition.directory,
        "top_level_file": definition.top_level_file,
        "required_files": list(definition.required_files),
        "optional_files": list(definition.optional_files),
        "asset_files": list(definition.asset_files),
        "generated_files": list(definition.generated_files),
        "allowed_subdirectories": list(definition.allowed_subdirectories),
        "forbids_executable_files": definition.forbids_executable_files,
        "participates_in_archive": definition.participates_in_archive,
    }


def all_package_paths_to_json() -> list[dict[str, Any]]:
    """Serialize all canonical package path definitions into JSON-compatible dictionaries."""
    return [
        path_definition_to_json(definition)
        for definition in _PACKAGE_PATH_DEFINITIONS.values()
    ]


def all_module_paths_to_json() -> list[dict[str, Any]]:
    """Serialize all module path definitions into JSON-compatible dictionaries."""
    return [
        module_path_definition_to_json(definition)
        for definition in _MODULE_PATH_DEFINITIONS.values()
    ]


def clear_package_path_caches() -> None:
    """
    Clear internal lru_cache state.

    Useful for tests and long-running developer sessions.
    """
    get_module_path_definitions.cache_clear()
    get_module_path_definition.cache_clear()
    get_package_path_definitions.cache_clear()
    get_package_path_definition_by_path.cache_clear()


__all__ = [
    "ALLOWED_ASSET_EXTENSIONS",
    "ALLOWED_PACKAGE_EXTENSIONS",
    "ALLOWED_TEXT_EXTENSIONS",
    "FORBIDDEN_FILE_EXTENSIONS",
    "PACKAGE_PATH_SCHEMA_VERSION",
    "SAFE_PATH_RE",
    "SAFE_SLUG_RE",
    "VARIANT_FILE_PATTERN",
    "VPLIB_MANIFEST_FILE",
    "VPLIB_MODULES_FILE",
    "ModulePathDefinition",
    "PackagePathDefinition",
    "PackagePathError",
    "PackagePathKind",
    "all_module_paths_to_json",
    "all_package_paths_to_json",
    "assert_safe_package_file_path",
    "assert_valid_package_paths",
    "classify_package_path",
    "clear_package_path_caches",
    "get_allowed_subdirectories_for_module",
    "get_allowed_subdirectories_for_modules",
    "get_asset_files_for_module",
    "get_generated_files_for_module",
    "get_module_directories_for_modules",
    "get_module_directory",
    "get_module_path_definition",
    "get_module_path_definitions",
    "get_module_top_level_file",
    "get_optional_files_for_module",
    "get_optional_files_for_modules",
    "get_package_path_definition_by_path",
    "get_package_path_definitions",
    "get_required_files_for_module",
    "get_required_files_for_modules",
    "get_top_level_files",
    "has_forbidden_extension",
    "infer_module_from_path",
    "is_allowed_package_file_extension",
    "is_known_package_path",
    "is_path_under_module",
    "is_valid_package_path",
    "make_asset_path",
    "make_render_icon_path",
    "make_render_model_path",
    "make_render_preview_path",
    "make_render_texture_path",
    "make_variant_file_path",
    "module_path_definition_to_json",
    "normalize_package_path",
    "path_definition_to_json",
    "path_extension",
    "resolve_relative_package_path",
    "try_normalize_package_path",
    "validate_package_paths",
    "validate_required_paths_present",
]