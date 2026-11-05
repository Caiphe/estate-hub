"""Cross-field contact rules, shared by create validation and by PATCH after merging.

Messages name the rule, never a submitted value.
"""

from typing import Protocol

from app.contacts.constants import ContactKind

ADDRESS_FIELDS = (
    "address_line_1",
    "address_line_2",
    "locality",
    "region",
    "postal_code",
    "country_code",
)
REQUIRED_ADDRESS_FIELDS = ("address_line_1", "locality", "country_code")


class ContactFields(Protocol):
    kind: ContactKind
    organization_name: str | None
    email: str | None
    telephone: str | None
    alternative_telephone: str | None
    address_line_1: str | None
    address_line_2: str | None
    locality: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None


def contact_rule_errors(contact: ContactFields) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    if contact.kind == ContactKind.ORGANIZATION and contact.organization_name is not None:
        errors["organization_name"] = [
            "Only people have an organization name; an organization uses its display name."
        ]
    if contact.alternative_telephone is not None:
        if contact.telephone is None:
            errors["alternative_telephone"] = ["Add a main telephone number first."]
        elif contact.alternative_telephone == contact.telephone:
            errors["alternative_telephone"] = ["Must differ from the main telephone number."]
    has_address = any(getattr(contact, name) is not None for name in ADDRESS_FIELDS)
    if has_address:
        for name in REQUIRED_ADDRESS_FIELDS:
            if getattr(contact, name) is None:
                errors[name] = ["Required when a correspondence address is given."]
    if contact.email is None and contact.telephone is None and contact.address_line_1 is None:
        errors["__root__"] = ["Provide an email, a telephone number, or an address."]
    return errors
