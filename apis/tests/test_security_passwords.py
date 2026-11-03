import pytest
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.security.exceptions import PasswordHashError, PasswordPolicyError
from app.core.security.passwords import (
    DEFAULT_PASSWORD_HASHER,
    hash_password,
    verify_dummy_password,
    verify_password,
)
from app.users.constants import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH

# Cheap parameters keep the suite fast; the default hasher is exercised separately.
FAST = PasswordHash((Argon2Hasher(time_cost=1, memory_cost=8_192, parallelism=1),))
PASSWORD = "correct horse battery staple"


def test_default_hasher_produces_argon2id_hashes() -> None:
    password_hash = hash_password(PASSWORD)

    assert password_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert PASSWORD not in password_hash
    assert verify_password(PASSWORD, password_hash).valid


def test_correct_and_incorrect_passwords() -> None:
    password_hash = hash_password(PASSWORD, FAST)

    assert verify_password(PASSWORD, password_hash, FAST).valid
    assert not verify_password(PASSWORD + "!", password_hash, FAST).valid
    assert not verify_password(PASSWORD.upper(), password_hash, FAST).valid
    assert not verify_password(" " + PASSWORD, password_hash, FAST).valid


def test_each_hash_uses_a_unique_salt() -> None:
    assert hash_password(PASSWORD, FAST) != hash_password(PASSWORD, FAST)


def test_outdated_parameters_produce_a_replacement_hash() -> None:
    old_hash = hash_password(PASSWORD, FAST)

    check = verify_password(PASSWORD, old_hash, DEFAULT_PASSWORD_HASHER)

    assert check.valid
    assert check.replacement_hash is not None
    assert check.replacement_hash.startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert verify_password(PASSWORD, check.replacement_hash).replacement_hash is None


def test_failed_check_never_offers_a_replacement() -> None:
    check = verify_password("wrong password!", hash_password(PASSWORD, FAST))

    assert check.valid is False
    assert check.replacement_hash is None


def test_unicode_passwords_are_normalized() -> None:
    composed = "café crème brûlée"
    decomposed = "café crème brûlée"
    password_hash = hash_password(composed, FAST)

    assert verify_password(decomposed, password_hash, FAST).valid
    assert verify_password(
        "пароль-日本語-🔐-secret", hash_password("пароль-日本語-🔐-secret", FAST), FAST
    ).valid


@pytest.mark.parametrize("length", [PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH])
def test_policy_boundaries_are_accepted(length: int) -> None:
    password = "p" * length

    assert verify_password(password, hash_password(password, FAST), FAST).valid


def test_long_passphrases_are_not_truncated() -> None:
    passphrase = "a" * (PASSWORD_MAX_LENGTH - 1) + "b"
    password_hash = hash_password(passphrase, FAST)

    assert not verify_password("a" * (PASSWORD_MAX_LENGTH - 1) + "c", password_hash, FAST).valid
    assert not verify_password("a" * (PASSWORD_MAX_LENGTH - 1), password_hash, FAST).valid


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("p" * (PASSWORD_MIN_LENGTH - 1), "password_too_short"),
        ("", "password_too_short"),
        ("p" * (PASSWORD_MAX_LENGTH + 1), "password_too_long"),
    ],
)
def test_policy_violations_are_rejected(password: str, reason: str) -> None:
    with pytest.raises(PasswordPolicyError) as error:
        hash_password(password, FAST)

    assert error.value.reason == reason
    assert password not in str(error.value) or not password


@pytest.mark.parametrize("password", ["", "p" * (PASSWORD_MAX_LENGTH + 1)])
def test_out_of_policy_input_never_matches(password: str) -> None:
    assert not verify_password(password, hash_password("p" * 20, FAST), FAST).valid


@pytest.mark.parametrize(
    "stored", ["", "plaintext", "$2b$12$abcdefghijklmnopqrstuuJ6tVb0/ZpXYhEiJXQkzWG1R6/9Zl6m"]
)
def test_unrecognized_hashes_raise_without_leaking(stored: str) -> None:
    with pytest.raises(PasswordHashError) as error:
        verify_password(PASSWORD, stored, FAST)

    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
    if stored:
        assert stored not in str(error.value)


def test_corrupt_argon2_hash_is_a_failed_check() -> None:
    assert not verify_password(PASSWORD, "$argon2id$v=19$m=8192,t=1,p=1$broken", FAST).valid


def test_dummy_verification_runs_without_matching() -> None:
    verify_dummy_password(PASSWORD, FAST)
