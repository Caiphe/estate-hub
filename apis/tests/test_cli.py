"""The create-admin bootstrap command."""

import io
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.cli import EXIT_INVALID, EXIT_OK, EXIT_REFUSED, main
from app.users.models import User

Sessions = async_sessionmaker[AsyncSession]
PASSWORD = "bootstrap passphrase for admin"
EMAIL = "first.admin@estatehub.example"


def run(
    session_factory: Sessions,
    *args: str,
    stdin: str = "",
    prompts: list[str] | None = None,
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    answers: Iterator[str] = iter(prompts or [])

    def prompt(_: str) -> str:
        return next(answers)

    code = main(
        list(args),
        session_factory=session_factory,
        stdin=io.StringIO(stdin),
        out=out,
        err=err,
        prompt=prompt,
    )
    return code, out.getvalue(), err.getvalue()


def create(session_factory: Sessions, email: str = EMAIL, *extra: str) -> tuple[int, str, str]:
    return run(
        session_factory,
        "create-admin",
        "--email",
        email,
        "--name",
        "First Admin",
        "--password-stdin",
        *extra,
        stdin=PASSWORD + "\n",
    )


async def administrators(session_factory: Sessions) -> list[User]:
    from sqlalchemy.orm import selectinload

    async with session_factory() as db:
        users = await db.scalars(select(User).options(selectinload(User.roles)))
        return [user for user in users if "administrator" in user.role_codes]


async def test_creates_the_first_administrator(
    session_factory: Sessions, run_sync: Callable[..., tuple[int, str, str]]
) -> None:
    code, out, err = run_sync(create, session_factory, f"  {EMAIL.upper()} ")

    assert code == EXIT_OK, err
    assert EMAIL in out
    assert PASSWORD not in out + err
    (admin,) = await administrators(session_factory)
    assert admin.email == EMAIL
    async with session_factory() as db:
        (event,) = list(await db.scalars(select(AuditEvent)))
    assert event.event_code == "staff.bootstrap_admin_created"
    assert (event.actor_id, event.entity_id) == (None, admin.id)
    assert event.details == {"roles": ["administrator"]}


async def test_refuses_a_second_administrator_without_override(
    session_factory: Sessions, run_sync: Callable[..., tuple[int, str, str]]
) -> None:
    assert run_sync(create, session_factory)[0] == EXIT_OK

    code, _, err = run_sync(create, session_factory, "second@estatehub.example")
    assert code == EXIT_REFUSED
    assert "--allow-additional-admin" in err
    assert len(await administrators(session_factory)) == 1

    code, _, _ = run_sync(
        create, session_factory, "second@estatehub.example", "--allow-additional-admin"
    )
    assert code == EXIT_OK
    assert len(await administrators(session_factory)) == 2


async def test_interactive_prompt_requires_matching_confirmation(
    session_factory: Sessions, run_sync: Callable[..., tuple[int, str, str]]
) -> None:
    args = ("create-admin", "--email", EMAIL, "--name", "First Admin")

    mismatch = run_sync(run, session_factory, *args, prompts=[PASSWORD, PASSWORD + "x"])
    assert mismatch[0] == EXIT_INVALID
    assert "do not match" in mismatch[2]
    assert await administrators(session_factory) == []

    matched = run_sync(run, session_factory, *args, prompts=[PASSWORD, PASSWORD])
    assert matched[0] == EXIT_OK


@pytest.mark.parametrize(
    ("email", "password", "field"),
    [
        (EMAIL, "too short", "password"),
        (EMAIL, "p" * 129, "password"),
        ("not-an-email", PASSWORD, "email"),
    ],
)
async def test_rejects_invalid_input_without_echoing_it(
    session_factory: Sessions,
    run_sync: Callable[..., tuple[int, str, str]],
    email: str,
    password: str,
    field: str,
) -> None:
    code, out, err = run_sync(
        run,
        session_factory,
        "create-admin",
        "--email",
        email,
        "--name",
        "First Admin",
        "--password-stdin",
        stdin=password + "\n",
    )

    assert code == EXIT_INVALID
    assert f"error: {field}:" in err
    assert password not in out + err
    assert await administrators(session_factory) == []


def test_password_cannot_be_passed_as_an_argument() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["create-admin", "--email", EMAIL, "--name", "Admin", "--password", PASSWORD])

    assert exit_info.value.code == 2


@pytest.fixture
def run_sync() -> Callable[..., tuple[int, str, str]]:
    """The CLI owns its event loop (asyncio.run), so run it in a worker thread."""
    import concurrent.futures

    def call(
        function: Callable[..., tuple[int, str, str]], *args: object, **kwargs: object
    ) -> tuple[int, str, str]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(function, *args, **kwargs).result()

    return call
