"""Open-source authorization boundary with an optional platform provider.

No provider configured means permissive Apache/open-source operation. A
configured provider is loaded from ``VECTOPLAN_LIBRARY_AUTHZ_PROVIDER`` and
fail-closes when it cannot be loaded. Platform-specific policy code therefore
does not have to be shipped with this repository.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Mapping, Protocol

from flask import g, has_request_context, request


class LibraryPermission(str, Enum):
    FAMILY_CREATE = "family.create"
    FAMILY_EDIT = "family.edit"
    PRODUCT_VARIANT_READ = "product_variant.read"
    PRODUCT_VARIANT_CREATE = "product_variant.create"
    PRODUCT_VARIANT_EDIT = "product_variant.edit"
    PRODUCT_VARIANT_APPROVE = "product_variant.approve"
    RIGHTS_MANAGE = "rights.manage"


@dataclass(frozen=True, slots=True)
class AuthorizationIdentity:
    user_id: str | None = None
    organization_id: str | None = None
    roles: tuple[str, ...] = field(default_factory=tuple)
    authenticated: bool = False
    source: str = "anonymous"

    @property
    def subject(self) -> str:
        if self.user_id:
            return f"user:{self.user_id}"
        if self.organization_id:
            return f"organization:{self.organization_id}"
        return "anonymous"

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "roles": list(self.roles),
            "authenticated": self.authenticated,
            "source": self.source,
            "subject": self.subject,
        }


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    permission: str
    reason: str
    policy: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "permission": self.permission,
            "reason": self.reason,
            "policy": self.policy,
            "metadata": dict(self.metadata),
        }


class AuthorizationProvider(Protocol):
    name: str

    def decide(
        self,
        *,
        identity: AuthorizationIdentity,
        permission: str,
        family: Any = None,
        resource: Any = None,
        context: Mapping[str, Any] | None = None,
    ) -> AuthorizationDecision | bool: ...


class OpenSourceAllowAllProvider:
    """Permissive default for self-hosted/open-source operation."""

    name = "open_source_allow_all"

    def decide(
        self,
        *,
        identity: AuthorizationIdentity,
        permission: str,
        family: Any = None,
        resource: Any = None,
        context: Mapping[str, Any] | None = None,
    ) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=True,
            permission=permission,
            reason="Open-source mode allows all library operations.",
            policy=self.name,
            metadata={"mode": "open_source", "family_ref": _family_ref(family)},
        )


class FailedProvider:
    """Fail-closed provider used when an explicitly configured provider fails."""

    name = "configured_provider_unavailable"

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def decide(self, *, permission: str, **_: Any) -> AuthorizationDecision:
        return AuthorizationDecision(
            allowed=False,
            permission=permission,
            reason="Configured authorization provider is unavailable.",
            policy=self.name,
            metadata={"error": f"{type(self.error).__name__}: {self.error}"},
        )


class AuthorizationService:
    def __init__(self, provider: AuthorizationProvider) -> None:
        self.provider = provider

    def identity(self) -> AuthorizationIdentity:
        return identity_from_request()

    def decide(
        self,
        permission: LibraryPermission | str,
        *,
        family: Any = None,
        resource: Any = None,
        context: Mapping[str, Any] | None = None,
        identity: AuthorizationIdentity | None = None,
    ) -> AuthorizationDecision:
        permission_value = permission.value if isinstance(permission, LibraryPermission) else str(permission)
        actor = identity or self.identity()
        try:
            result = self.provider.decide(
                identity=actor,
                permission=permission_value,
                family=family,
                resource=resource,
                context=context or {},
            )
            if isinstance(result, AuthorizationDecision):
                return result
            return AuthorizationDecision(
                allowed=bool(result),
                permission=permission_value,
                reason="Provider returned a boolean decision.",
                policy=getattr(self.provider, "name", type(self.provider).__name__),
            )
        except Exception as exc:
            return AuthorizationDecision(
                allowed=False,
                permission=permission_value,
                reason="Authorization provider failed closed.",
                policy=getattr(self.provider, "name", type(self.provider).__name__),
                metadata={"error": f"{type(exc).__name__}: {exc}"},
            )

    def capabilities(self, *, family: Any = None) -> dict[str, bool]:
        return {
            "family_create": self.decide(LibraryPermission.FAMILY_CREATE, family=family).allowed,
            "family_edit": self.decide(LibraryPermission.FAMILY_EDIT, family=family).allowed,
            "product_variant_read": self.decide(LibraryPermission.PRODUCT_VARIANT_READ, family=family).allowed,
            "product_variant_create": self.decide(LibraryPermission.PRODUCT_VARIANT_CREATE, family=family).allowed,
            "product_variant_edit": self.decide(LibraryPermission.PRODUCT_VARIANT_EDIT, family=family).allowed,
            "product_variant_approve": self.decide(LibraryPermission.PRODUCT_VARIANT_APPROVE, family=family).allowed,
            "rights_manage": self.decide(LibraryPermission.RIGHTS_MANAGE, family=family).allowed,
        }


def identity_from_request() -> AuthorizationIdentity:
    if not has_request_context():
        return AuthorizationIdentity(source="no_request_context")

    user_id = _first_non_empty(
        getattr(g, "user_id", None),
        getattr(getattr(g, "user", None), "id", None),
        request.headers.get("X-Vectoplan-User-Id"),
        request.headers.get("X-User-Id"),
    )
    organization_id = _first_non_empty(
        getattr(g, "organization_id", None),
        request.headers.get("X-Vectoplan-Organization-Id"),
        request.headers.get("X-Organization-Id"),
    )
    raw_roles = _first_non_empty(
        getattr(g, "roles", None),
        request.headers.get("X-Vectoplan-Roles"),
        request.headers.get("X-Roles"),
    )
    roles = _normalize_roles(raw_roles)
    return AuthorizationIdentity(
        user_id=str(user_id) if user_id is not None else None,
        organization_id=str(organization_id) if organization_id is not None else None,
        roles=roles,
        authenticated=bool(user_id or organization_id),
        source="request",
    )


def _normalize_roles(value: Any) -> tuple[str, ...]:
    if value is None:
        return tuple()
    if isinstance(value, str):
        values = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = (value,)
    return tuple(dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip()))


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _family_ref(family: Any) -> str | None:
    if family is None:
        return None
    if isinstance(family, Mapping):
        value = _first_non_empty(family.get("id"), family.get("vplib_uid"), family.get("family_id"))
    else:
        value = _first_non_empty(
            getattr(family, "id", None),
            getattr(family, "vplib_uid", None),
            getattr(family, "family_id", None),
        )
    return str(value) if value is not None else None


def _load_provider(spec: str) -> AuthorizationProvider:
    module_name, separator, attribute_name = spec.partition(":")
    if not separator:
        module_name, _, attribute_name = spec.rpartition(".")
    if not module_name or not attribute_name:
        raise ValueError("Provider must use 'module:factory_or_object' syntax.")
    module = importlib.import_module(module_name)
    candidate = getattr(module, attribute_name)
    provider = candidate() if callable(candidate) else candidate
    if not callable(getattr(provider, "decide", None)):
        raise TypeError("Authorization provider must expose decide(...).")
    return provider


@lru_cache(maxsize=1)
def get_authorization_service() -> AuthorizationService:
    spec = os.environ.get("VECTOPLAN_LIBRARY_AUTHZ_PROVIDER", "").strip()
    if not spec:
        return AuthorizationService(OpenSourceAllowAllProvider())
    try:
        return AuthorizationService(_load_provider(spec))
    except Exception as exc:
        return AuthorizationService(FailedProvider(exc))


__all__ = [
    "AuthorizationDecision",
    "AuthorizationIdentity",
    "AuthorizationProvider",
    "AuthorizationService",
    "LibraryPermission",
    "OpenSourceAllowAllProvider",
    "get_authorization_service",
    "identity_from_request",
]
