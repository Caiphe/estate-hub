"""Operator commands. Run inside the API container:

docker compose run --rm api python -m app.cli create-admin --email ... --name ...
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable
from typing import TextIO

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.users.errors import StaffServiceError
from app.users.service import StaffService

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_REFUSED = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser(
        "create-admin",
        help="Create an administrator account (first-time setup).",
        description=(
            "The password is never accepted as an argument or environment variable. It is "
            "read from a hidden prompt (entered twice), or from one line of standard input "
            "with --password-stdin."
        ),
    )
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True, help="Full name.")
    create.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the password from the first line of standard input instead of a prompt.",
    )
    create.add_argument(
        "--allow-additional-admin",
        action="store_true",
        help="Create the account even though an active administrator already exists.",
    )
    return parser


def _read_password(from_stdin: bool, stdin: TextIO, prompt: Callable[[str], str]) -> str | None:
    if from_stdin:
        line = stdin.readline()
        # Strip only the line ending: spaces are part of the password.
        return line.removesuffix("\n").removesuffix("\r")
    first = prompt("Password: ")
    if prompt("Confirm password: ") != first:
        return None
    return first


async def _create_admin(
    args: argparse.Namespace,
    password: str,
    session_factory: async_sessionmaker[AsyncSession],
    out: TextIO,
    err: TextIO,
) -> int:
    async with session_factory() as db:
        try:
            user = await StaffService(db).bootstrap_administrator(
                args.email,
                args.name,
                password,
                allow_additional=args.allow_additional_admin,
            )
        except ValidationError as exc:
            # Inputs are hidden in schema errors; print field names and messages only.
            for error in exc.errors(include_input=False):
                field = ".".join(str(part) for part in error["loc"]) or "input"
                print(f"error: {field}: {error['msg']}", file=err)
            return EXIT_INVALID
        except StaffServiceError as exc:
            print(f"error: {exc.message} ({exc.code})", file=err)
            if exc.code == "administrator_exists":
                print("Use --allow-additional-admin to add another one.", file=err)
                return EXIT_REFUSED
            return EXIT_INVALID
    print(f"Created administrator {user.email} ({user.id}).", file=out)
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    stdin: TextIO = sys.stdin,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
    prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    args = _parser().parse_args(argv)
    password = _read_password(args.password_stdin, stdin, prompt)
    if password is None:
        print("error: the passwords do not match.", file=err)
        return EXIT_INVALID
    if session_factory is None:
        from app.core.database import async_session_factory

        session_factory = async_session_factory
    return asyncio.run(_create_admin(args, password, session_factory, out, err))


if __name__ == "__main__":
    sys.exit(main())
