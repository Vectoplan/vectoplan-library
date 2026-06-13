# services/vectoplan-library/src/vplib/profiles/profile_resolver.py
"""
Profile resolver for the VPLIB package engine.

Diese Datei löst object_kind-Werte auf kanonische ObjectKindProfile auf.

Rolle dieser Datei:

    object_kind
    -> profile resolver
    -> ObjectKindProfile
    -> ModulePlan / PackagePlan / validators

Der Resolver ist bewusst robust:
- object_kind wird normalisiert
- Profile werden lazy importiert
- Cache-Funktionen sind vorhanden
- Health-/Diagnosefunktionen zeigen, welche Profile ladbar sind

Technische Namen, JSON-Keys und Variablen bleiben Englisch.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from functools import lru_cache
from types import ModuleType
from typing import Any, Callable, Final, Mapping

from .base_profiles import ObjectKindProfile, ProfileError


PROFILE_RESOLVER_SCHEMA_VERSION: Final[str] = "vplib.profile_resolver.v1"


class ProfileResolverError(ProfileError):
    """Wird ausgelöst, wenn ein Profil nicht aufgelöst werden kann."""


@dataclass(frozen=True, slots=True)
class ProfileRegistration:
    """Registrierung eines ObjectKind-Profils."""

    object_kind: str
    profile_key: str
    module_path: str
    factory_name: str
    title: str
    description: str

    def normalized(self) -> "ProfileRegistration":
        object_kind = normalize_object_kind_value(self.object_kind)
        profile_key = clean_required_string(self.profile_key, "profile_key")
        module_path = clean_required_string(self.module_path, "module_path")
        factory_name = clean_required_string(self.factory_name, "factory_name")
        title = clean_required_string(self.title, "title")
        description = clean_optional_string(self.description) or ""

        return ProfileRegistration(
            object_kind=object_kind,
            profile_key=profile_key,
            module_path=module_path,
            factory_name=factory_name,
            title=title,
            description=description,
        )

    def to_dict(self) -> dict[str, Any]:
        normalized = self.normalized()

        return {
            "schema_version": PROFILE_RESOLVER_SCHEMA_VERSION,
            "object_kind": normalized.object_kind,
            "profile_key": normalized.profile_key,
            "module_path": normalized.module_path,
            "factory_name": normalized.factory_name,
            "title": normalized.title,
            "description": normalized.description,
        }


@dataclass(frozen=True, slots=True)
class ProfileResolverStatus:
    """Status eines registrierten Profils."""

    object_kind: str
    profile_key: str
    module_path: str
    factory_name: str
    available: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_RESOLVER_SCHEMA_VERSION,
            "object_kind": self.object_kind,
            "profile_key": self.profile_key,
            "module_path": self.module_path,
            "factory_name": self.factory_name,
            "available": self.available,
            "error": self.error,
        }


_PROFILE_REGISTRATIONS: Final[dict[str, ProfileRegistration]] = {
    "cell_block": ProfileRegistration(
        object_kind="cell_block",
        profile_key="cell_block_profile",
        module_path=".cell_block_profile",
        factory_name="get_cell_block_profile",
        title="Cell Block Profile",
        description="Profile for raster-based single-cell or simple grid building components.",
    ),
    "multi_cell_module": ProfileRegistration(
        object_kind="multi_cell_module",
        profile_key="multi_cell_module_profile",
        module_path=".multi_cell_module_profile",
        factory_name="get_multi_cell_module_profile",
        title="Multi Cell Module Profile",
        description="Profile for components that occupy multiple grid cells but remain one semantic family.",
    ),
    "catalog_object": ProfileRegistration(
        object_kind="catalog_object",
        profile_key="catalog_object_profile",
        module_path=".catalog_object_profile",
        factory_name="get_catalog_object_profile",
        title="Catalog Object Profile",
        description="Profile for furniture, fixtures, equipment and other catalog-like objects.",
    ),
    "adaptive_system": ProfileRegistration(
        object_kind="adaptive_system",
        profile_key="adaptive_system_profile",
        module_path=".adaptive_system_profile",
        factory_name="get_adaptive_system_profile",
        title="Adaptive System Profile",
        description="Profile for declarative context-bound adaptive systems.",
    ),
}


def normalize_object_kind_value(value: Any) -> str:
    """Normalisiert object_kind über die Domain-Schicht."""
    try:
        from ..domain.object_kinds import ensure_object_kind_value

        return ensure_object_kind_value(value)
    except Exception as exc:
        raise ProfileResolverError(f"Invalid object_kind {value!r}: {exc}") from exc


def clean_required_string(value: Any, field_name: str) -> str:
    """Normalisiert einen Pflicht-String."""
    try:
        cleaned = str(value).strip()

        if not cleaned:
            raise ProfileResolverError(f"{field_name} is required.")

        return cleaned
    except ProfileResolverError:
        raise
    except Exception as exc:
        raise ProfileResolverError(f"{field_name} must be string-like.") from exc


def clean_optional_string(value: Any) -> str | None:
    """Normalisiert einen optionalen String."""
    if value is None:
        return None

    try:
        cleaned = str(value).strip()
        return cleaned or None
    except Exception:
        return None


@lru_cache(maxsize=64)
def get_profile_registration(object_kind: Any) -> ProfileRegistration:
    """
    Gibt die Profilregistrierung für eine Objektart zurück.

    Raises:
        ProfileResolverError: Wenn keine Registrierung existiert.
    """
    object_kind_value = normalize_object_kind_value(object_kind)

    try:
        return _PROFILE_REGISTRATIONS[object_kind_value].normalized()
    except KeyError as exc:
        allowed = ", ".join(get_registered_object_kinds())
        raise ProfileResolverError(
            f"No VPLIB profile registered for object_kind {object_kind_value!r}. "
            f"Registered object kinds: {allowed}."
        ) from exc


@lru_cache(maxsize=1)
def get_profile_registrations() -> Mapping[str, ProfileRegistration]:
    """Gibt alle Profilregistrierungen zurück."""
    return {
        object_kind: registration.normalized()
        for object_kind, registration in _PROFILE_REGISTRATIONS.items()
    }


@lru_cache(maxsize=1)
def get_registered_object_kinds() -> tuple[str, ...]:
    """Gibt alle registrierten object_kind-Werte zurück."""
    return tuple(sorted(_PROFILE_REGISTRATIONS.keys()))


@lru_cache(maxsize=1)
def get_registered_profile_keys() -> tuple[str, ...]:
    """Gibt alle registrierten profile_key-Werte zurück."""
    return tuple(
        registration.normalized().profile_key
        for registration in _PROFILE_REGISTRATIONS.values()
    )


@lru_cache(maxsize=64)
def _load_profile_module(object_kind: Any) -> ModuleType:
    """Lädt das Profilmodul für eine Objektart lazy."""
    registration = get_profile_registration(object_kind)

    try:
        return importlib.import_module(registration.module_path, package=__package__)
    except Exception as exc:
        raise ProfileResolverError(
            f"Could not import profile module {registration.module_path!r} "
            f"for object_kind {registration.object_kind!r}: {exc}"
        ) from exc


@lru_cache(maxsize=64)
def _get_profile_factory(object_kind: Any) -> Callable[..., ObjectKindProfile]:
    """Lädt die Profil-Factory für eine Objektart."""
    registration = get_profile_registration(object_kind)
    module = _load_profile_module(registration.object_kind)

    try:
        factory = getattr(module, registration.factory_name)
    except AttributeError as exc:
        raise ProfileResolverError(
            f"Profile module {registration.module_path!r} does not export "
            f"factory {registration.factory_name!r}."
        ) from exc

    if not callable(factory):
        raise ProfileResolverError(
            f"Profile factory {registration.factory_name!r} for "
            f"{registration.object_kind!r} is not callable."
        )

    return factory


@lru_cache(maxsize=64)
def resolve_profile(object_kind: Any) -> ObjectKindProfile:
    """
    Löst eine Objektart auf ein kanonisches ObjectKindProfile auf.

    Raises:
        ProfileResolverError: Wenn das Profil nicht geladen oder validiert werden kann.
    """
    object_kind_value = normalize_object_kind_value(object_kind)
    factory = _get_profile_factory(object_kind_value)

    try:
        profile = factory()
    except Exception as exc:
        raise ProfileResolverError(
            f"Could not build profile for object_kind {object_kind_value!r}: {exc}"
        ) from exc

    if not isinstance(profile, ObjectKindProfile):
        raise ProfileResolverError(
            f"Profile factory for {object_kind_value!r} did not return ObjectKindProfile."
        )

    try:
        normalized = profile.normalized()
    except Exception as exc:
        raise ProfileResolverError(
            f"Profile for object_kind {object_kind_value!r} is invalid: {exc}"
        ) from exc

    if normalized.object_kind != object_kind_value:
        raise ProfileResolverError(
            f"Resolved profile object_kind mismatch. Expected {object_kind_value!r}, "
            f"got {normalized.object_kind!r}."
        )

    return normalized


def try_resolve_profile(
    object_kind: Any,
    default: ObjectKindProfile | None = None,
) -> ObjectKindProfile | None:
    """Sichere Resolver-Variante ohne Exception."""
    try:
        return resolve_profile(object_kind)
    except Exception:
        return default


def resolve_profile_by_key(profile_key: Any) -> ObjectKindProfile:
    """
    Löst ein Profil über profile_key auf.

    Raises:
        ProfileResolverError: Wenn kein passendes Profil registriert ist.
    """
    key = clean_required_string(profile_key, "profile_key")

    for registration in get_profile_registrations().values():
        if registration.profile_key == key:
            return resolve_profile(registration.object_kind)

    allowed = ", ".join(get_registered_profile_keys())
    raise ProfileResolverError(
        f"Unknown VPLIB profile_key {key!r}. Registered profile keys: {allowed}."
    )


def try_resolve_profile_by_key(
    profile_key: Any,
    default: ObjectKindProfile | None = None,
) -> ObjectKindProfile | None:
    """Sichere Resolver-Variante für profile_key."""
    try:
        return resolve_profile_by_key(profile_key)
    except Exception:
        return default


def is_profile_registered(object_kind: Any) -> bool:
    """Gibt zurück, ob für eine Objektart ein Profil registriert ist."""
    try:
        get_profile_registration(object_kind)
        return True
    except Exception:
        return False


def get_profile_module_status(object_kind: Any) -> ProfileResolverStatus:
    """Gibt den Status eines registrierten Profils zurück."""
    try:
        registration = get_profile_registration(object_kind)
    except Exception as exc:
        object_kind_value = str(object_kind)
        return ProfileResolverStatus(
            object_kind=object_kind_value,
            profile_key="",
            module_path="",
            factory_name="",
            available=False,
            error=str(exc),
        )

    try:
        _get_profile_factory(registration.object_kind)
        return ProfileResolverStatus(
            object_kind=registration.object_kind,
            profile_key=registration.profile_key,
            module_path=registration.module_path,
            factory_name=registration.factory_name,
            available=True,
            error=None,
        )
    except Exception as exc:
        return ProfileResolverStatus(
            object_kind=registration.object_kind,
            profile_key=registration.profile_key,
            module_path=registration.module_path,
            factory_name=registration.factory_name,
            available=False,
            error=str(exc),
        )


def get_profile_resolver_statuses() -> tuple[ProfileResolverStatus, ...]:
    """Gibt den Status aller registrierten Profile zurück."""
    return tuple(
        get_profile_module_status(object_kind)
        for object_kind in get_registered_object_kinds()
    )


def get_profile_resolver_health() -> dict[str, Any]:
    """Gibt einen JSON-kompatiblen Health-Snapshot des Profile Resolvers zurück."""
    statuses = get_profile_resolver_statuses()

    return {
        "schema_version": PROFILE_RESOLVER_SCHEMA_VERSION,
        "healthy": all(status.available for status in statuses),
        "registered_profile_count": len(statuses),
        "available_profile_count": sum(1 for status in statuses if status.available),
        "registered_object_kinds": list(get_registered_object_kinds()),
        "registered_profile_keys": list(get_registered_profile_keys()),
        "profiles": [status.to_dict() for status in statuses],
    }


def assert_profiles_ready() -> None:
    """
    Prüft, ob alle registrierten Profile ladbar sind.

    Raises:
        ProfileResolverError: Wenn mindestens ein Profil nicht ladbar ist.
    """
    statuses = get_profile_resolver_statuses()
    failed = [status for status in statuses if not status.available]

    if failed:
        details = "; ".join(
            f"{status.object_kind}: {status.error}" for status in failed
        )
        raise ProfileResolverError(f"VPLIB profiles are not ready: {details}")


def all_profiles() -> tuple[ObjectKindProfile, ...]:
    """Gibt alle registrierten Profile zurück."""
    return tuple(
        resolve_profile(object_kind)
        for object_kind in get_registered_object_kinds()
    )


def all_profiles_to_dict() -> list[dict[str, Any]]:
    """Serialisiert alle Profile JSON-kompatibel."""
    return [profile.to_dict() for profile in all_profiles()]


def registration_to_dict(registration: ProfileRegistration) -> dict[str, Any]:
    """Serialisiert eine Profilregistrierung."""
    return registration.normalized().to_dict()


def all_registrations_to_dict() -> list[dict[str, Any]]:
    """Serialisiert alle Profilregistrierungen."""
    return [
        registration_to_dict(registration)
        for registration in get_profile_registrations().values()
    ]


def profile_summary(object_kind: Any) -> dict[str, Any]:
    """Gibt eine kompakte Profilzusammenfassung zurück."""
    profile = resolve_profile(object_kind)

    return {
        "schema_version": PROFILE_RESOLVER_SCHEMA_VERSION,
        "profile_key": profile.profile_key,
        "object_kind": profile.object_kind,
        "title": profile.title,
        "active_modules": list(profile.active_module_names),
        "required_modules": list(profile.required_module_names),
        "recommended_modules": list(profile.recommended_module_names),
        "optional_modules": list(profile.optional_module_names),
        "excluded_modules": list(profile.excluded_module_names),
        "default_placement_mode": profile.defaults.placement_mode,
        "default_grid_size_cells": list(profile.defaults.grid_size_cells),
    }


def all_profile_summaries() -> list[dict[str, Any]]:
    """Gibt kompakte Zusammenfassungen aller Profile zurück."""
    return [
        profile_summary(object_kind)
        for object_kind in get_registered_object_kinds()
    ]


def clear_profile_resolver_caches() -> None:
    """Leert Resolver-Caches und bekannte Profil-Caches."""
    get_profile_registration.cache_clear()
    get_profile_registrations.cache_clear()
    get_registered_object_kinds.cache_clear()
    get_registered_profile_keys.cache_clear()
    _load_profile_module.cache_clear()
    _get_profile_factory.cache_clear()
    resolve_profile.cache_clear()

    clear_function_names = (
        "clear_base_profile_caches",
        "clear_cell_block_profile_caches",
        "clear_multi_cell_module_profile_caches",
        "clear_catalog_object_profile_caches",
        "clear_adaptive_system_profile_caches",
    )

    for object_kind in tuple(_PROFILE_REGISTRATIONS.keys()):
        try:
            module = _load_profile_module(object_kind)
        except Exception:
            continue

        for function_name in clear_function_names:
            function = getattr(module, function_name, None)
            if callable(function):
                try:
                    function()
                except Exception:
                    continue


__all__ = [
    "PROFILE_RESOLVER_SCHEMA_VERSION",
    "ProfileRegistration",
    "ProfileResolverError",
    "ProfileResolverStatus",
    "all_profile_summaries",
    "all_profiles",
    "all_profiles_to_dict",
    "all_registrations_to_dict",
    "assert_profiles_ready",
    "clean_optional_string",
    "clean_required_string",
    "clear_profile_resolver_caches",
    "get_profile_module_status",
    "get_profile_registration",
    "get_profile_registrations",
    "get_profile_resolver_health",
    "get_profile_resolver_statuses",
    "get_registered_object_kinds",
    "get_registered_profile_keys",
    "is_profile_registered",
    "normalize_object_kind_value",
    "profile_summary",
    "registration_to_dict",
    "resolve_profile",
    "resolve_profile_by_key",
    "try_resolve_profile",
    "try_resolve_profile_by_key",
]