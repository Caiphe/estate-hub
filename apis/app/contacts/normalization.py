"""Email and telephone normalization shared by contact schemas and models.

Telephone numbers are stored as digits with an optional leading "+": spaces, dots,
hyphens, and brackets are removed, and an international "00" prefix becomes "+". The
number is not checked against a numbering plan, and a number without "+" is kept as
entered because its country is unknown.
"""

import re

from app.contacts.constants import TELEPHONE_MAX_DIGITS, TELEPHONE_MIN_DIGITS

_SEPARATORS = re.compile(r"[\s.\-()/]")
TELEPHONE_PATTERN = rf"^\+?[0-9]{{{TELEPHONE_MIN_DIGITS},{TELEPHONE_MAX_DIGITS}}}$"
_TELEPHONE = re.compile(TELEPHONE_PATTERN)


class InvalidTelephoneError(ValueError):
    pass


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_telephone(value: str) -> str:
    """Return the stored form, or raise ``InvalidTelephoneError`` without echoing input."""
    compact = _SEPARATORS.sub("", value.strip())
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if not _TELEPHONE.match(compact):
        raise InvalidTelephoneError(
            f"Enter a telephone number of {TELEPHONE_MIN_DIGITS} to {TELEPHONE_MAX_DIGITS} "
            "digits, optionally starting with +."
        )
    return compact
