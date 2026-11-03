"""The authorization policy layer. Every permission decision goes through this module.

It is framework-free so services can enforce the same rules as HTTP dependencies: a
caller that skips the API still cannot skip the policy.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from app.auth.errors import PermissionDeniedError
from app.auth.permissions import Permission, permissions_for_roles
from app.users.models import User


@dataclass(frozen=True, slots=True)
class Actor:
    """Who is acting, as loaded from the database for this request.

    Roles come from PostgreSQL, never from the client or the access token, so role
    changes and account disabling apply on the next request.
    """

    user_id: uuid.UUID
    role_codes: frozenset[str]
    active: bool

    @classmethod
    def from_user(cls, user: User) -> Actor:
        """Requires ``user.roles`` to be loaded."""
        return cls(user_id=user.id, role_codes=frozenset(user.role_codes), active=user.is_active)

    @property
    def permissions(self) -> frozenset[Permission]:
        if not self.active:
            return frozenset()
        return permissions_for_roles(self.role_codes)


def validate_permissions(permissions: Iterable[Permission]) -> tuple[Permission, ...]:
    """Reject empty requirements and non-Permission values (for example a raw string)."""
    checked = tuple(permissions)
    if not checked:
        # An empty requirement would allow everyone; treat it as a programming error.
        raise ValueError("At least one permission must be required.")
    for permission in checked:
        if not isinstance(permission, Permission):
            raise TypeError(f"{permission!r} is not a Permission.")
    return checked


def has_permissions(actor: Actor, *required: Permission) -> bool:
    """True when the actor holds every required permission."""
    return set(validate_permissions(required)) <= actor.permissions


def has_any_permission(actor: Actor, *candidates: Permission) -> bool:
    """True when the actor holds at least one of the candidate permissions."""
    return bool(set(validate_permissions(candidates)) & actor.permissions)


def require_permissions(actor: Actor, *required: Permission) -> None:
    if not has_permissions(actor, *required):
        raise PermissionDeniedError(required=required, mode="all")


def require_any_permission(actor: Actor, *candidates: Permission) -> None:
    if not has_any_permission(actor, *candidates):
        raise PermissionDeniedError(required=candidates, mode="any")
