from enum import StrEnum

DISPLAY_NAME_MAX_LENGTH = 200
ORGANIZATION_NAME_MAX_LENGTH = 200
EMAIL_MAX_LENGTH = 254
TELEPHONE_MAX_LENGTH = 16  # "+" and at most 15 digits (E.164).
TELEPHONE_MIN_DIGITS = 6
TELEPHONE_MAX_DIGITS = 15
CONTACT_NOTES_MAX_LENGTH = 10_000


class ContactKind(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class ContactStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
