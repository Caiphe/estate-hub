from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models import Role, User
from app.users.constants import (
    INITIAL_ROLES,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    RoleCode,
    UserStatus,
)
from app.users.schemas import StaffCreate, StaffUpdate, UserPublic

VALID_PASSWORD = "correct horse battery"
FORBIDDEN_OUTPUT_FIELDS = {"password", "password_hash", "token_version", "token", "refresh_token"}


def staff_create(**overrides: Any) -> StaffCreate:
    values: dict[str, Any] = {
        "email": "agent@estatehub.example",
        "full_name": "Ada Agent",
        "password": VALID_PASSWORD,
        "roles": ["agent"],
    }
    return StaffCreate.model_validate(values | overrides)


def persisted_user(roles: list[Role]) -> User:
    now = datetime(2026, 11, 3, tzinfo=UTC)
    user = User(
        id=uuid4(),
        email="manager@estatehub.example",
        full_name="Max Manager",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
        status=UserStatus.ACTIVE,
        token_version=4,
        last_login_at=None,
        created_at=now,
        updated_at=now,
    )
    user.roles = roles
    return user


def test_user_model_normalizes_email() -> None:
    user = User(email="  Ada.Agent@EstateHub.Example ", full_name="Ada", password_hash="h")

    assert user.email == "ada.agent@estatehub.example"


def test_role_code_is_immutable() -> None:
    role = Role(code="agent", name="Agent")

    with pytest.raises(ValueError, match="cannot be changed"):
        role.code = "administrator"


def test_initial_roles_cover_every_role_code() -> None:
    assert [definition.code for definition in INITIAL_ROLES] == list(RoleCode)


def test_user_status_and_role_codes() -> None:
    user = persisted_user([Role(code="manager", name="Manager"), Role(code="agent", name="Agent")])

    assert user.is_active
    assert user.role_codes == ["manager", "agent"]
    user.status = UserStatus.DISABLED
    assert not user.is_active


@pytest.mark.parametrize("model", [User, Role])
def test_relationships_never_lazy_load(model: type[User] | type[Role]) -> None:
    for relationship in model.__mapper__.relationships:
        assert relationship.lazy == "raise", relationship


def test_user_public_serializes_only_safe_fields() -> None:
    user = persisted_user([Role(code="manager", name="Manager"), Role(code="agent", name="Agent")])

    public = UserPublic.model_validate(user).model_dump()

    assert set(public) == {
        "id",
        "email",
        "full_name",
        "status",
        "roles",
        "last_login_at",
        "created_at",
        "updated_at",
    }
    assert public["roles"] == ["agent", "manager"]
    assert not FORBIDDEN_OUTPUT_FIELDS & set(public)
    assert "argon2" not in str(public)


def test_staff_create_normalizes_input() -> None:
    staff = staff_create(
        email="  New.Agent@EstateHub.Example ",
        full_name="  Ada Agent ",
        roles=["manager", "agent", "manager"],
    )

    assert staff.email == "new.agent@estatehub.example"
    assert staff.full_name == "Ada Agent"
    assert staff.roles == [RoleCode.AGENT, RoleCode.MANAGER]


def test_staff_create_hides_password_in_repr() -> None:
    staff = staff_create()

    assert VALID_PASSWORD not in repr(staff)
    assert VALID_PASSWORD not in str(staff.model_dump())


@pytest.mark.parametrize(
    "email", ["", "not-an-email", "a@b", f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 63}.ex"]
)
def test_staff_create_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        staff_create(email=email)


@pytest.mark.parametrize(
    "full_name", ["", "   ", "x" * 201, "Ada\x00Agent", "Ada\nAgent", "Ada Agent"]
)
def test_staff_create_rejects_invalid_name(full_name: str) -> None:
    with pytest.raises(ValidationError):
        staff_create(full_name=full_name)


def test_staff_create_accepts_unicode_name_at_maximum_length() -> None:
    assert staff_create(full_name="Zoë Ñúñez").full_name == "Zoë Ñúñez"
    assert len(staff_create(full_name="x" * 200).full_name) == 200


@pytest.mark.parametrize(
    "password",
    [
        "a" * PASSWORD_MIN_LENGTH,
        "é" * PASSWORD_MAX_LENGTH,
        "  spaced passphrase  ",
    ],
)
def test_staff_create_accepts_password_boundaries(password: str) -> None:
    # Passwords are kept exactly as entered: never trimmed or truncated.
    assert staff_create(password=password).password.get_secret_value() == password


@pytest.mark.parametrize(
    "password", ["a" * (PASSWORD_MIN_LENGTH - 1), "a" * (PASSWORD_MAX_LENGTH + 1)]
)
def test_staff_create_rejects_password_outside_bounds(password: str) -> None:
    with pytest.raises(ValidationError) as error:
        staff_create(password=password)

    assert password not in str(error.value)


@pytest.mark.parametrize("roles", [[], ["owner"], ["Administrator"]])
def test_staff_create_rejects_invalid_roles(roles: list[str]) -> None:
    with pytest.raises(ValidationError):
        staff_create(roles=roles)


@pytest.mark.parametrize(
    "field", ["password_hash", "token_version", "id", "last_login_at", "status"]
)
def test_staff_create_rejects_unknown_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        staff_create(**{field: "x"})


def test_staff_update_accepts_partial_changes() -> None:
    update = StaffUpdate.model_validate({"full_name": " New Name "})

    assert update.model_dump(exclude_unset=True) == {"full_name": "New Name"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": None},
        {"full_name": None},
        {"roles": ["agent"]},
        {"status": "disabled"},
        {"password": VALID_PASSWORD},
        {"token_version": 0},
    ],
)
def test_staff_update_rejects_empty_null_and_unknown_fields(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        StaffUpdate.model_validate(payload)
