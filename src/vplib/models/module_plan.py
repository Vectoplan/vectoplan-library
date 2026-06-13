# services/vectoplan-library/src/vplib/models/module_plan.py
"""
ModulePlan model for the VPLIB package engine.

Diese Datei beschreibt, welche VPLIB-Module für ein Package aktiv, erforderlich,
optional oder ausgeschlossen sind.

Rolle dieser Datei:

    CreateRequest / PackageContext
    -> object-kind/profile rules
    -> ModulePlan
    -> PackagePlan
    -> skeleton/document creation

Diese Datei schreibt keine Dateien. Sie beschreibt nur den Modulplan.

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
Kommentare und Docstrings dürfen Deutsch sein.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Final, Iterable, Mapping, Sequence


MODULE_PLAN_SCHEMA_VERSION: Final[str] = "vplib.module_plan.v1"


class ModulePlanError(ValueError):
    """Wird ausgelöst, wenn ein Modulplan ungültig ist."""


class ModuleRequirementLevel(str, Enum):
    """Anforderungsstatus eines Moduls."""

    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    EXCLUDED = "excluded"

    @property
    def key(self) -> str:
        return str(self.value)


class ModuleActivationSource(str, Enum):
    """Quelle, warum ein Modul im Plan gelandet ist."""

    CORE = "core"
    OBJECT_KIND = "object_kind"
    PROFILE = "profile"
    USER_REQUEST = "user_request"
    DEPENDENCY = "dependency"
    DEFAULT = "default"
    SYSTEM = "system"

    @property
    def key(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ModulePlanEntry:
    """
    Ein einzelner Modulplaneintrag.

    Ein Modul kann aktiv sein, obwohl es optional ist. Ein required-Modul muss
    aktiv sein. Ein excluded-Modul darf nicht aktiv sein.
    """

    module_name: str
    active: bool = True
    requirement: str = ModuleRequirementLevel.OPTIONAL.value
    source: str = ModuleActivationSource.DEFAULT.value
    reason: str = ""
    required_files: tuple[str, ...] = field(default_factory=tuple)
    optional_files: tuple[str, ...] = field(default_factory=tuple)
    generated_files: tuple[str, ...] = field(default_factory=tuple)
    directories: tuple[str, ...] = field(default_factory=tuple)
    allowed_subdirectories: tuple[str, ...] = field(default_factory=tuple)

    def normalized(self) -> "ModulePlanEntry":
        module_name = normalize_module_name_value(self.module_name)
        requirement = parse_requirement_level_value(self.requirement)
        source = parse_activation_source_value(self.source)
        active = bool(self.active)
        reason = clean_optional_string(self.reason) or ""

        if requirement == ModuleRequirementLevel.REQUIRED.value:
            active = True

        if requirement == ModuleRequirementLevel.EXCLUDED.value:
            active = False

        required_files = normalize_path_tuple(self.required_files)
        optional_files = normalize_path_tuple(self.optional_files)
        generated_files = normalize_path_tuple(self.generated_files)
        directories = normalize_path_tuple(self.directories)
        allowed_subdirectories = normalize_path_tuple(self.allowed_subdirectories)

        if not required_files and active:
            required_files = get_required_files_for_module_safe(module_name)

        if not optional_files and active:
            optional_files = get_optional_files_for_module_safe(module_name)

        if not generated_files and active:
            generated_files = get_generated_files_for_module_safe(module_name)

        if not directories and active:
            directory = get_module_directory_safe(module_name)
            directories = (directory,) if directory else tuple()

        if not allowed_subdirectories and active:
            allowed_subdirectories = get_allowed_subdirectories_for_module_safe(module_name)

        return ModulePlanEntry(
            module_name=module_name,
            active=active,
            requirement=requirement,
            source=source,
            reason=reason,
            required_files=required_files,
            optional_files=optional_files,
            generated_files=generated_files,
            directories=directories,
            allowed_subdirectories=allowed_subdirectories,
        )

    @property
    def is_required(self) -> bool:
        return self.normalized().requirement == ModuleRequirementLevel.REQUIRED.value

    @property
    def is_recommended(self) -> bool:
        return self.normalized().requirement == ModuleRequirementLevel.RECOMMENDED.value

    @property
    def is_optional(self) -> bool:
        return self.normalized().requirement == ModuleRequirementLevel.OPTIONAL.value

    @property
    def is_excluded(self) -> bool:
        return self.normalized().requirement == ModuleRequirementLevel.EXCLUDED.value

    def with_active(self, active: bool, *, reason: str | None = None) -> "ModulePlanEntry":
        normalized = self.normalized()

        return ModulePlanEntry(
            module_name=normalized.module_name,
            active=bool(active),
            requirement=normalized.requirement,
            source=normalized.source,
            reason=reason if reason is not None else normalized.reason,
            required_files=normalized.required_files,
            optional_files=normalized.optional_files,
            generated_files=normalized.generated_files,
            directories=normalized.directories,
            allowed_subdirectories=normalized.allowed_subdirectories,
        ).normalized()

    def with_requirement(
        self,
        requirement: str,
        *,
        source: str | None = None,
        reason: str | None = None,
    ) -> "ModulePlanEntry":
        normalized = self.normalized()
        parsed_requirement = parse_requirement_level_value(requirement)

        return ModulePlanEntry(
            module_name=normalized.module_name,
            active=parsed_requirement != ModuleRequirementLevel.EXCLUDED.value,
            requirement=parsed_requirement,
            source=source if source is not None else normalized.source,
            reason=reason if reason is not None else normalized.reason,
            required_files=normalized.required_files,
            optional_files=normalized.optional_files,
            generated_files=normalized.generated_files,
            directories=normalized.directories,
            allowed_subdirectories=normalized.allowed_subdirectories,
        ).normalized()

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "module_name": normalized.module_name,
            "active": normalized.active,
            "requirement": normalized.requirement,
            "source": normalized.source,
            "reason": normalized.reason,
            "required_files": list(normalized.required_files),
            "optional_files": list(normalized.optional_files),
            "generated_files": list(normalized.generated_files),
            "directories": list(normalized.directories),
            "allowed_subdirectories": list(normalized.allowed_subdirectories),
        }


@dataclass(frozen=True, slots=True)
class ModulePlan:
    """
    Vollständiger Modulplan für ein VPLIB-Package.

    Der Plan kennt aktive Module und deren Dateianforderungen. Er enthält noch
    keine Zielpfade im Dateisystem und keine fertigen JSON-Dokumente.
    """

    entries: tuple[ModulePlanEntry, ...]
    object_kind: str | None = None
    profile_key: str | None = None
    schema_version: str = MODULE_PLAN_SCHEMA_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ModulePlan":
        object_kind = (
            normalize_object_kind_value(self.object_kind)
            if self.object_kind is not None
            else None
        )
        profile_key = clean_optional_string(self.profile_key)
        metadata = dict(self.metadata or {})

        entries_by_name: dict[str, ModulePlanEntry] = {}

        for entry in self.entries or ():
            normalized_entry = entry.normalized()
            existing = entries_by_name.get(normalized_entry.module_name)

            if existing is None:
                entries_by_name[normalized_entry.module_name] = normalized_entry
                continue

            entries_by_name[normalized_entry.module_name] = merge_module_plan_entries(
                existing,
                normalized_entry,
            )

        for core_module in get_core_module_names_safe():
            existing = entries_by_name.get(core_module)
            core_entry = ModulePlanEntry(
                module_name=core_module,
                active=True,
                requirement=ModuleRequirementLevel.REQUIRED.value,
                source=ModuleActivationSource.CORE.value,
                reason="Core VPLIB module.",
            ).normalized()

            entries_by_name[core_module] = (
                core_entry
                if existing is None
                else merge_module_plan_entries(existing, core_entry)
            )

        entries = tuple(
            entries_by_name[module_name]
            for module_name in sort_module_names_safe(entries_by_name.keys())
        )

        plan = ModulePlan(
            entries=entries,
            object_kind=object_kind,
            profile_key=profile_key,
            schema_version=self.schema_version or MODULE_PLAN_SCHEMA_VERSION,
            metadata=metadata,
        )

        valid, messages = plan.validate()
        if not valid:
            raise ModulePlanError(" ".join(messages))

        return plan

    @property
    def active_entries(self) -> tuple[ModulePlanEntry, ...]:
        return tuple(entry for entry in self.normalized().entries if entry.active)

    @property
    def inactive_entries(self) -> tuple[ModulePlanEntry, ...]:
        return tuple(entry for entry in self.normalized().entries if not entry.active)

    @property
    def required_entries(self) -> tuple[ModulePlanEntry, ...]:
        return tuple(entry for entry in self.normalized().entries if entry.is_required)

    @property
    def recommended_entries(self) -> tuple[ModulePlanEntry, ...]:
        return tuple(entry for entry in self.normalized().entries if entry.is_recommended)

    @property
    def optional_entries(self) -> tuple[ModulePlanEntry, ...]:
        return tuple(entry for entry in self.normalized().entries if entry.is_optional)

    @property
    def excluded_entries(self) -> tuple[ModulePlanEntry, ...]:
        return tuple(entry for entry in self.normalized().entries if entry.is_excluded)

    @property
    def active_module_names(self) -> tuple[str, ...]:
        return tuple(entry.module_name for entry in self.active_entries)

    @property
    def required_module_names(self) -> tuple[str, ...]:
        return tuple(entry.module_name for entry in self.required_entries)

    @property
    def recommended_module_names(self) -> tuple[str, ...]:
        return tuple(entry.module_name for entry in self.recommended_entries)

    @property
    def optional_module_names(self) -> tuple[str, ...]:
        return tuple(entry.module_name for entry in self.optional_entries if entry.active)

    @property
    def excluded_module_names(self) -> tuple[str, ...]:
        return tuple(entry.module_name for entry in self.excluded_entries)

    @property
    def required_files(self) -> tuple[str, ...]:
        paths: list[str] = []

        for entry in self.active_entries:
            paths.extend(entry.required_files)

        return tuple(dict.fromkeys(paths))

    @property
    def optional_files(self) -> tuple[str, ...]:
        paths: list[str] = []

        for entry in self.active_entries:
            paths.extend(entry.optional_files)

        return tuple(dict.fromkeys(paths))

    @property
    def generated_files(self) -> tuple[str, ...]:
        paths: list[str] = []

        for entry in self.active_entries:
            paths.extend(entry.generated_files)

        return tuple(dict.fromkeys(paths))

    @property
    def directories(self) -> tuple[str, ...]:
        paths: list[str] = []

        for entry in self.active_entries:
            paths.extend(entry.directories)

        return tuple(dict.fromkeys(paths))

    @property
    def allowed_subdirectories(self) -> tuple[str, ...]:
        paths: list[str] = []

        for entry in self.active_entries:
            paths.extend(entry.allowed_subdirectories)

        return tuple(dict.fromkeys(paths))

    def get_entry(self, module_name: Any) -> ModulePlanEntry | None:
        normalized_name = normalize_module_name_value(module_name)

        for entry in self.normalized().entries:
            if entry.module_name == normalized_name:
                return entry

        return None

    def has_active_module(self, module_name: Any) -> bool:
        entry = self.get_entry(module_name)
        return bool(entry and entry.active)

    def with_entry(self, entry: ModulePlanEntry) -> "ModulePlan":
        normalized = self.normalized()
        new_entry = entry.normalized()
        entries_by_name = {
            current.module_name: current
            for current in normalized.entries
        }
        entries_by_name[new_entry.module_name] = new_entry

        return ModulePlan(
            entries=tuple(entries_by_name.values()),
            object_kind=normalized.object_kind,
            profile_key=normalized.profile_key,
            schema_version=normalized.schema_version,
            metadata=dict(normalized.metadata),
        ).normalized()

    def with_entries(self, entries: Iterable[ModulePlanEntry]) -> "ModulePlan":
        plan = self.normalized()

        for entry in entries:
            plan = plan.with_entry(entry)

        return plan.normalized()

    def without_module(self, module_name: Any, *, reason: str = "") -> "ModulePlan":
        normalized_name = normalize_module_name_value(module_name)
        existing = self.get_entry(normalized_name)

        if existing is None:
            entry = ModulePlanEntry(
                module_name=normalized_name,
                active=False,
                requirement=ModuleRequirementLevel.EXCLUDED.value,
                source=ModuleActivationSource.USER_REQUEST.value,
                reason=reason or "Module explicitly excluded.",
            )
        else:
            entry = existing.with_requirement(
                ModuleRequirementLevel.EXCLUDED.value,
                source=ModuleActivationSource.USER_REQUEST.value,
                reason=reason or "Module explicitly excluded.",
            )

        return self.with_entry(entry)

    def validate(self) -> tuple[bool, tuple[str, ...]]:
        messages: list[str] = []

        try:
            entries = tuple(entry.normalized() for entry in self.entries or ())
            active_modules = tuple(entry.module_name for entry in entries if entry.active)
            excluded_modules = {entry.module_name for entry in entries if entry.is_excluded}

            for entry in entries:
                if entry.is_required and not entry.active:
                    messages.append(f"Required module {entry.module_name!r} is inactive.")

                if entry.active and entry.module_name in excluded_modules:
                    excluded_entry = next(
                        current for current in entries if current.module_name == entry.module_name
                    )
                    if excluded_entry.is_excluded:
                        messages.append(f"Module {entry.module_name!r} is both active and excluded.")

            core_valid, core_messages = validate_core_modules_present_safe(active_modules)
            if not core_valid:
                messages.extend(core_messages)

            dependency_valid, dependency_messages = validate_module_dependencies_safe(active_modules)
            if not dependency_valid:
                messages.extend(dependency_messages)

            for entry in entries:
                for path in (*entry.required_files, *entry.optional_files, *entry.generated_files):
                    if not is_valid_package_path_safe(path):
                        messages.append(
                            f"Module {entry.module_name!r} contains invalid package path {path!r}."
                        )

        except ModulePlanError as exc:
            messages.append(str(exc))
        except Exception as exc:
            messages.append(f"Could not validate module plan: {exc}")

        return len(messages) == 0, tuple(messages)

    def to_modules_manifest_payload(self) -> dict[str, Any]:
        normalized = self.normalized()

        try:
            from ..domain.module_names import build_modules_manifest_payload

            payload = build_modules_manifest_payload(
                active_modules=normalized.active_module_names,
                required_modules=normalized.required_module_names,
                optional_modules=normalized.optional_module_names,
                profile_key=normalized.profile_key,
            )
        except Exception:
            payload = {
                "schema_version": "vplib.modules.v1",
                "profile_key": normalized.profile_key,
                "active_modules": list(normalized.active_module_names),
                "required_modules": list(normalized.required_module_names),
                "optional_modules": list(normalized.optional_module_names),
            }

        payload["object_kind"] = normalized.object_kind
        return payload

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": normalized.schema_version,
            "object_kind": normalized.object_kind,
            "profile_key": normalized.profile_key,
            "active_modules": list(normalized.active_module_names),
            "required_modules": list(normalized.required_module_names),
            "recommended_modules": list(normalized.recommended_module_names),
            "optional_modules": list(normalized.optional_module_names),
            "excluded_modules": list(normalized.excluded_module_names),
            "required_files": list(normalized.required_files),
            "optional_files": list(normalized.optional_files),
            "generated_files": list(normalized.generated_files),
            "directories": list(normalized.directories),
            "allowed_subdirectories": list(normalized.allowed_subdirectories),
            "entries": [entry.to_dict() for entry in normalized.entries],
            "metadata": dict(normalized.metadata),
        }


def build_module_plan(
    *,
    object_kind: Any,
    active_modules: Iterable[Any] | None = None,
    required_modules: Iterable[Any] | None = None,
    recommended_modules: Iterable[Any] | None = None,
    optional_modules: Iterable[Any] | None = None,
    excluded_modules: Iterable[Any] | None = None,
    include_docs: bool = False,
    include_tests: bool = False,
    profile_key: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ModulePlan:
    """
    Baut einen Modulplan aus Objektart und optionalen Modullisten.

    Diese Factory ist robust und kann später vom module_planner verwendet werden.
    """
    try:
        object_kind_value = normalize_object_kind_value(object_kind)

        base_required = tuple(get_required_module_keys_for_object_kind_safe(object_kind_value))
        base_optional = tuple(get_optional_module_keys_for_object_kind_safe(object_kind_value))
        base_recommended = tuple(get_recommended_module_keys_for_object_kind_safe(object_kind_value))

        requested_active = tuple(active_modules or ())
        requested_required = tuple(required_modules or ())
        requested_recommended = tuple(recommended_modules or ())
        requested_optional = tuple(optional_modules or ())
        requested_excluded = tuple(excluded_modules or ())

        entries: list[ModulePlanEntry] = []

        for module_name in get_core_module_names_safe():
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=ModuleRequirementLevel.REQUIRED.value,
                    source=ModuleActivationSource.CORE.value,
                    reason="Core VPLIB module.",
                )
            )

        for module_name in base_required:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=ModuleRequirementLevel.REQUIRED.value,
                    source=ModuleActivationSource.OBJECT_KIND.value,
                    reason=f"Required by object kind {object_kind_value}.",
                )
            )

        for module_name in base_recommended:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=ModuleRequirementLevel.RECOMMENDED.value,
                    source=ModuleActivationSource.OBJECT_KIND.value,
                    reason=f"Recommended by object kind {object_kind_value}.",
                )
            )

        for module_name in base_optional:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=False,
                    requirement=ModuleRequirementLevel.OPTIONAL.value,
                    source=ModuleActivationSource.OBJECT_KIND.value,
                    reason=f"Optional for object kind {object_kind_value}.",
                )
            )

        for module_name in requested_active:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=ModuleRequirementLevel.OPTIONAL.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Activated by request.",
                )
            )

        for module_name in requested_required:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=ModuleRequirementLevel.REQUIRED.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Required by request.",
                )
            )

        for module_name in requested_recommended:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=ModuleRequirementLevel.RECOMMENDED.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Recommended by request.",
                )
            )

        for module_name in requested_optional:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=False,
                    requirement=ModuleRequirementLevel.OPTIONAL.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Optional by request.",
                )
            )

        if include_docs:
            entries.append(
                ModulePlanEntry(
                    module_name="docs",
                    active=True,
                    requirement=ModuleRequirementLevel.OPTIONAL.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Docs requested.",
                )
            )

        if include_tests:
            entries.append(
                ModulePlanEntry(
                    module_name="tests",
                    active=True,
                    requirement=ModuleRequirementLevel.OPTIONAL.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Tests requested.",
                )
            )

        for module_name in requested_excluded:
            entries.append(
                ModulePlanEntry(
                    module_name=module_name,
                    active=False,
                    requirement=ModuleRequirementLevel.EXCLUDED.value,
                    source=ModuleActivationSource.USER_REQUEST.value,
                    reason="Excluded by request.",
                )
            )

        plan = ModulePlan(
            entries=tuple(entries),
            object_kind=object_kind_value,
            profile_key=profile_key or f"{object_kind_value}_profile",
            metadata=dict(metadata or {}),
        ).normalized()

        return activate_dependencies(plan).normalized()
    except ModulePlanError:
        raise
    except Exception as exc:
        raise ModulePlanError(f"Could not build module plan: {exc}") from exc


def activate_dependencies(plan: ModulePlan) -> ModulePlan:
    """Aktiviert direkte Abhängigkeiten aktiver Module."""
    try:
        normalized = plan.normalized()
        active_module_names = set(normalized.active_module_names)
        entries_to_add: list[ModulePlanEntry] = []

        for module_name in tuple(active_module_names):
            for dependency in get_module_dependencies_safe(module_name):
                if dependency in active_module_names:
                    continue

                entries_to_add.append(
                    ModulePlanEntry(
                        module_name=dependency,
                        active=True,
                        requirement=ModuleRequirementLevel.REQUIRED.value,
                        source=ModuleActivationSource.DEPENDENCY.value,
                        reason=f"Dependency of module {module_name}.",
                    )
                )
                active_module_names.add(dependency)

        if not entries_to_add:
            return normalized

        return normalized.with_entries(entries_to_add).normalized()
    except ModulePlanError:
        raise
    except Exception as exc:
        raise ModulePlanError(f"Could not activate module dependencies: {exc}") from exc


def merge_module_plan_entries(
    left: ModulePlanEntry,
    right: ModulePlanEntry,
) -> ModulePlanEntry:
    """Merged zwei Einträge desselben Moduls."""
    left_normalized = left.normalized()
    right_normalized = right.normalized()

    if left_normalized.module_name != right_normalized.module_name:
        raise ModulePlanError(
            f"Cannot merge entries for different modules: "
            f"{left_normalized.module_name!r}, {right_normalized.module_name!r}."
        )

    requirement = strongest_requirement(
        left_normalized.requirement,
        right_normalized.requirement,
    )

    active = left_normalized.active or right_normalized.active
    if requirement == ModuleRequirementLevel.REQUIRED.value:
        active = True
    if requirement == ModuleRequirementLevel.EXCLUDED.value:
        active = False

    return ModulePlanEntry(
        module_name=left_normalized.module_name,
        active=active,
        requirement=requirement,
        source=right_normalized.source or left_normalized.source,
        reason=right_normalized.reason or left_normalized.reason,
        required_files=merge_tuples(left_normalized.required_files, right_normalized.required_files),
        optional_files=merge_tuples(left_normalized.optional_files, right_normalized.optional_files),
        generated_files=merge_tuples(left_normalized.generated_files, right_normalized.generated_files),
        directories=merge_tuples(left_normalized.directories, right_normalized.directories),
        allowed_subdirectories=merge_tuples(
            left_normalized.allowed_subdirectories,
            right_normalized.allowed_subdirectories,
        ),
    ).normalized()


def strongest_requirement(left: Any, right: Any) -> str:
    """Ermittelt den stärkeren Requirement-Level."""
    left_value = parse_requirement_level_value(left)
    right_value = parse_requirement_level_value(right)

    order = {
        ModuleRequirementLevel.EXCLUDED.value: 0,
        ModuleRequirementLevel.OPTIONAL.value: 1,
        ModuleRequirementLevel.RECOMMENDED.value: 2,
        ModuleRequirementLevel.REQUIRED.value: 3,
    }

    if left_value == ModuleRequirementLevel.EXCLUDED.value or right_value == ModuleRequirementLevel.EXCLUDED.value:
        return ModuleRequirementLevel.EXCLUDED.value

    return left_value if order[left_value] >= order[right_value] else right_value


def module_plan_from_mapping(data: Mapping[str, Any]) -> ModulePlan:
    """Baut einen ModulePlan aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise ModulePlanError("ModulePlan data must be a mapping.")

        entries_data = data.get("entries", ()) or ()
        entries = tuple(
            module_plan_entry_from_mapping(item)
            for item in entries_data
            if isinstance(item, Mapping)
        )

        if not entries and data.get("active_modules"):
            entries = tuple(
                ModulePlanEntry(
                    module_name=module_name,
                    active=True,
                    requirement=(
                        ModuleRequirementLevel.REQUIRED.value
                        if module_name in set(data.get("required_modules", ()) or ())
                        else ModuleRequirementLevel.OPTIONAL.value
                    ),
                    source=ModuleActivationSource.SYSTEM.value,
                )
                for module_name in data.get("active_modules", ()) or ()
            )

        return ModulePlan(
            entries=entries,
            object_kind=data.get("object_kind"),
            profile_key=data.get("profile_key"),
            schema_version=data.get("schema_version", MODULE_PLAN_SCHEMA_VERSION),
            metadata=dict(data.get("metadata", {}) or {}),
        ).normalized()
    except ModulePlanError:
        raise
    except Exception as exc:
        raise ModulePlanError(f"Could not build ModulePlan from mapping: {exc}") from exc


def module_plan_entry_from_mapping(data: Mapping[str, Any]) -> ModulePlanEntry:
    """Baut einen ModulePlanEntry aus einem Mapping."""
    try:
        if not isinstance(data, Mapping):
            raise ModulePlanError("ModulePlanEntry data must be a mapping.")

        return ModulePlanEntry(
            module_name=data.get("module_name") or data.get("name") or data.get("module"),
            active=bool(data.get("active", True)),
            requirement=data.get("requirement", ModuleRequirementLevel.OPTIONAL.value),
            source=data.get("source", ModuleActivationSource.DEFAULT.value),
            reason=data.get("reason", ""),
            required_files=tuple(data.get("required_files", ()) or ()),
            optional_files=tuple(data.get("optional_files", ()) or ()),
            generated_files=tuple(data.get("generated_files", ()) or ()),
            directories=tuple(data.get("directories", ()) or ()),
            allowed_subdirectories=tuple(data.get("allowed_subdirectories", ()) or ()),
        ).normalized()
    except ModulePlanError:
        raise
    except Exception as exc:
        raise ModulePlanError(f"Could not build ModulePlanEntry from mapping: {exc}") from exc


def normalize_module_name_value(value: Any) -> str:
    """Normalisiert einen Modulnamen."""
    try:
        from ..domain.module_names import ensure_module_name_value

        return ensure_module_name_value(value)
    except Exception as exc:
        raise ModulePlanError(f"Invalid module name {value!r}: {exc}") from exc


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert eine Objektart."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise ModulePlanError(f"Invalid object kind {value!r}: {exc}") from exc


@lru_cache(maxsize=128)
def parse_requirement_level_value(value: Any) -> str:
    """Parst einen Requirement-Level."""
    try:
        if isinstance(value, ModuleRequirementLevel):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")

        aliases = {
            "must": ModuleRequirementLevel.REQUIRED.value,
            "mandatory": ModuleRequirementLevel.REQUIRED.value,
            "required": ModuleRequirementLevel.REQUIRED.value,
            "recommended": ModuleRequirementLevel.RECOMMENDED.value,
            "suggested": ModuleRequirementLevel.RECOMMENDED.value,
            "optional": ModuleRequirementLevel.OPTIONAL.value,
            "excluded": ModuleRequirementLevel.EXCLUDED.value,
            "disabled": ModuleRequirementLevel.EXCLUDED.value,
            "forbidden": ModuleRequirementLevel.EXCLUDED.value,
        }

        if raw in aliases:
            return aliases[raw]

        return ModuleRequirementLevel(raw).value
    except Exception as exc:
        raise ModulePlanError(f"Invalid module requirement level {value!r}.") from exc


@lru_cache(maxsize=128)
def parse_activation_source_value(value: Any) -> str:
    """Parst eine Activation Source."""
    try:
        if isinstance(value, ModuleActivationSource):
            return value.value

        raw = str(value).strip().lower().replace(" ", "_").replace("-", "_")
        return ModuleActivationSource(raw).value
    except Exception as exc:
        raise ModulePlanError(f"Invalid module activation source {value!r}.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


def normalize_path_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    """Normalisiert Package-Pfade und entfernt Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in values or ():
        path = normalize_package_path_safe(value)
        if not path or path in seen:
            continue
        result.append(path)
        seen.add(path)

    return tuple(result)


def merge_tuples(left: Iterable[Any], right: Iterable[Any]) -> tuple[str, ...]:
    """Merged zwei Sequenzen ohne Duplikate."""
    result: list[str] = []
    seen: set[str] = set()

    for value in (*tuple(left or ()), *tuple(right or ())):
        cleaned = clean_optional_string(value)
        if not cleaned or cleaned in seen:
            continue
        result.append(cleaned)
        seen.add(cleaned)

    return tuple(result)


def normalize_package_path_safe(value: Any) -> str:
    """Normalisiert einen Package-Pfad robust."""
    try:
        from ..domain.package_paths import normalize_package_path

        return normalize_package_path(value)
    except Exception as exc:
        raise ModulePlanError(f"Invalid package path {value!r}: {exc}") from exc


def is_valid_package_path_safe(value: Any) -> bool:
    """Prüft einen Package-Pfad robust."""
    try:
        from ..domain.package_paths import is_valid_package_path

        return is_valid_package_path(value)
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


def get_module_directory_safe(module_name: Any) -> str | None:
    """Liest den Modulordner."""
    try:
        from ..domain.package_paths import get_module_directory

        return get_module_directory(module_name)
    except Exception:
        return None


def get_allowed_subdirectories_for_module_safe(module_name: Any) -> tuple[str, ...]:
    """Liest erlaubte Modulunterordner."""
    try:
        from ..domain.package_paths import get_allowed_subdirectories_for_module

        return tuple(get_allowed_subdirectories_for_module(module_name))
    except Exception:
        return tuple()


def get_core_module_names_safe() -> tuple[str, ...]:
    """Liest Core-Module."""
    try:
        from ..domain.module_names import get_core_module_names

        return tuple(module.value for module in get_core_module_names())
    except Exception:
        return (
            "manifest",
            "modules",
            "family",
            "variants",
            "editor",
            "manufacturer",
        )


def sort_module_names_safe(values: Iterable[Any]) -> tuple[str, ...]:
    """Sortiert Modulnamen in stabiler Reihenfolge."""
    try:
        from ..domain.module_names import sort_module_names

        return tuple(module.value for module in sort_module_names(values))
    except Exception:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            normalized = normalize_module_name_value(value)
            if normalized in seen:
                continue
            result.append(normalized)
            seen.add(normalized)

        return tuple(result)


def get_module_dependencies_safe(module_name: Any) -> tuple[str, ...]:
    """Liest Modulabhängigkeiten."""
    try:
        from ..domain.module_names import module_dependencies

        return tuple(module.value for module in module_dependencies(module_name))
    except Exception:
        return tuple()


def validate_core_modules_present_safe(values: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert Core-Module robust."""
    try:
        from ..domain.module_names import validate_core_modules_present

        return validate_core_modules_present(values)
    except Exception as exc:
        return False, (f"Could not validate core modules: {exc}",)


def validate_module_dependencies_safe(values: Iterable[Any]) -> tuple[bool, tuple[str, ...]]:
    """Validiert Modulabhängigkeiten robust."""
    try:
        from ..domain.module_names import validate_module_dependencies

        return validate_module_dependencies(values)
    except Exception as exc:
        return False, (f"Could not validate module dependencies: {exc}",)


def get_required_module_keys_for_object_kind_safe(object_kind: Any) -> tuple[str, ...]:
    """Liest Pflichtmodule für eine Objektart."""
    try:
        from ..domain.object_kinds import get_required_module_keys

        return tuple(get_required_module_keys(object_kind))
    except Exception:
        return get_core_module_names_safe()


def get_optional_module_keys_for_object_kind_safe(object_kind: Any) -> tuple[str, ...]:
    """Liest optionale Module für eine Objektart."""
    try:
        from ..domain.object_kinds import get_optional_module_keys

        return tuple(get_optional_module_keys(object_kind))
    except Exception:
        return tuple()


def get_recommended_module_keys_for_object_kind_safe(object_kind: Any) -> tuple[str, ...]:
    """Liest empfohlene Module für eine Objektart."""
    try:
        from ..domain.object_kinds import get_recommended_module_keys

        return tuple(get_recommended_module_keys(object_kind))
    except Exception:
        return tuple()


def clear_module_plan_caches() -> None:
    """Leert interne Parser-Caches."""
    parse_requirement_level_value.cache_clear()
    parse_activation_source_value.cache_clear()


__all__ = [
    "MODULE_PLAN_SCHEMA_VERSION",
    "ModuleActivationSource",
    "ModulePlan",
    "ModulePlanEntry",
    "ModulePlanError",
    "ModuleRequirementLevel",
    "activate_dependencies",
    "build_module_plan",
    "clear_module_plan_caches",
    "clean_optional_string",
    "get_allowed_subdirectories_for_module_safe",
    "get_core_module_names_safe",
    "get_generated_files_for_module_safe",
    "get_module_dependencies_safe",
    "get_module_directory_safe",
    "get_optional_files_for_module_safe",
    "get_optional_module_keys_for_object_kind_safe",
    "get_recommended_module_keys_for_object_kind_safe",
    "get_required_files_for_module_safe",
    "get_required_module_keys_for_object_kind_safe",
    "is_valid_package_path_safe",
    "merge_module_plan_entries",
    "merge_tuples",
    "module_plan_entry_from_mapping",
    "module_plan_from_mapping",
    "normalize_module_name_value",
    "normalize_object_kind_value",
    "normalize_package_path_safe",
    "normalize_path_tuple",
    "parse_activation_source_value",
    "parse_requirement_level_value",
    "sort_module_names_safe",
    "strongest_requirement",
    "validate_core_modules_present_safe",
    "validate_module_dependencies_safe",
]