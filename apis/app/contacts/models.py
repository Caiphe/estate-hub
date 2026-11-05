"""Reusable contacts. A contact acts as an owner through ``PropertyOwnership`` and, in later
milestones, as a seller, buyer, tenant, or prospect; there is no owner-only person table.

Email, telephone, address, and notes are personal data. They never appear in audit
metadata, logs, or property summaries for callers without ``contacts:read``.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.catalog.checks import (
    country_code_check,
    normalized_check,
    not_blank_check,
    postal_code_check,
)
from app.catalog.text import normalize_label, normalize_optional_label, normalize_optional_text
from app.contacts.constants import (
    CONTACT_NOTES_MAX_LENGTH,
    DISPLAY_NAME_MAX_LENGTH,
    EMAIL_MAX_LENGTH,
    ORGANIZATION_NAME_MAX_LENGTH,
    TELEPHONE_MAX_LENGTH,
    ContactKind,
    ContactStatus,
)
from app.contacts.normalization import TELEPHONE_PATTERN, normalize_email, normalize_telephone
from app.core.database import Base, TimestampMixin, str_enum
from app.properties.constants import (
    ADDRESS_LINE_MAX_LENGTH,
    LOCALITY_MAX_LENGTH,
    POSTAL_CODE_MAX_LENGTH,
    REGION_MAX_LENGTH,
)

_ADDRESS_COLUMNS = (
    "address_line_1",
    "address_line_2",
    "locality",
    "region",
    "postal_code",
    "country_code",
)
_ADDRESS_ABSENT = " AND ".join(f"{column} IS NULL" for column in _ADDRESS_COLUMNS)


def _telephone_check(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ~ '{TELEPHONE_PATTERN}'", name=f"{column}_format")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[ContactKind] = mapped_column(str_enum(ContactKind, "contact_kind"))
    # A person's name, or the organization's name for an organization.
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_MAX_LENGTH))
    # The organization a person represents. Organizations leave it empty.
    organization_name: Mapped[str | None] = mapped_column(String(ORGANIZATION_NAME_MAX_LENGTH))
    email: Mapped[str | None] = mapped_column(String(EMAIL_MAX_LENGTH))
    telephone: Mapped[str | None] = mapped_column(String(TELEPHONE_MAX_LENGTH))
    alternative_telephone: Mapped[str | None] = mapped_column(String(TELEPHONE_MAX_LENGTH))

    # Optional correspondence address: absent, or at least line 1, locality, and country.
    address_line_1: Mapped[str | None] = mapped_column(String(ADDRESS_LINE_MAX_LENGTH))
    address_line_2: Mapped[str | None] = mapped_column(String(ADDRESS_LINE_MAX_LENGTH))
    locality: Mapped[str | None] = mapped_column(String(LOCALITY_MAX_LENGTH))
    region: Mapped[str | None] = mapped_column(String(REGION_MAX_LENGTH))
    postal_code: Mapped[str | None] = mapped_column(String(POSTAL_CODE_MAX_LENGTH))
    country_code: Mapped[str | None] = mapped_column(String(2))

    # Staff-only. Never add this field to audit metadata or a public schema.
    internal_notes: Mapped[str | None] = mapped_column(String(CONTACT_NOTES_MAX_LENGTH))
    status: Mapped[ContactStatus] = mapped_column(
        str_enum(ContactStatus, "contact_status"),
        default=ContactStatus.ACTIVE,
        server_default=ContactStatus.ACTIVE.value,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None]
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"eager_defaults": True, "version_id_col": version}
    __table_args__ = (
        normalized_check("display_name"),
        normalized_check("organization_name", optional=True),
        CheckConstraint(
            f"kind = '{ContactKind.PERSON.value}' OR organization_name IS NULL",
            name="organization_name_for_people",
        ),
        CheckConstraint(
            "email = lower(btrim(email)) AND email LIKE '_%@_%'", name="email_normalized"
        ),
        _telephone_check("telephone"),
        _telephone_check("alternative_telephone"),
        CheckConstraint(
            "alternative_telephone IS NULL OR "
            "(telephone IS NOT NULL AND alternative_telephone <> telephone)",
            name="alternative_telephone_secondary",
        ),
        normalized_check("address_line_1", optional=True),
        normalized_check("address_line_2", optional=True),
        normalized_check("locality", optional=True),
        normalized_check("region", optional=True),
        postal_code_check(),
        country_code_check(),
        CheckConstraint(
            f"({_ADDRESS_ABSENT}) OR (address_line_1 IS NOT NULL AND locality IS NOT NULL "
            "AND country_code IS NOT NULL)",
            name="address_complete",
        ),
        # A contact must be reachable somehow.
        CheckConstraint(
            "email IS NOT NULL OR telephone IS NOT NULL OR address_line_1 IS NOT NULL",
            name="has_contact_method",
        ),
        not_blank_check("internal_notes"),
        CheckConstraint(
            f"(status = '{ContactStatus.ARCHIVED.value}') = (archived_at IS NOT NULL)",
            name="archived_state_consistent",
        ),
        CheckConstraint(
            "archived_by_id IS NULL OR archived_at IS NOT NULL", name="archived_by_needs_date"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_contacts_status", "status"),
        # Duplicate-contact lookups when staff enter a known email or number.
        Index("ix_contacts_email", "email"),
        Index("ix_contacts_telephone", "telephone"),
        Index(
            "ix_contacts_search_trgm",
            "display_name",
            "organization_name",
            "email",
            postgresql_using="gin",
            postgresql_ops={
                "display_name": "gin_trgm_ops",
                "organization_name": "gin_trgm_ops",
                "email": "gin_trgm_ops",
            },
        ),
    )

    @validates("display_name")
    def _normalize_display_name(self, _: str, value: str) -> str:
        return normalize_label(value)

    @validates("organization_name", "address_line_1", "address_line_2", "locality", "region")
    def _normalize_optional_label(self, _: str, value: str | None) -> str | None:
        return normalize_optional_label(value)

    @validates("email")
    def _normalize_email(self, _: str, value: str | None) -> str | None:
        stripped = normalize_optional_text(value)
        return normalize_email(stripped) if stripped else None

    @validates("telephone", "alternative_telephone")
    def _normalize_telephone(self, _: str, value: str | None) -> str | None:
        stripped = normalize_optional_text(value)
        return normalize_telephone(stripped) if stripped else None

    @validates("postal_code")
    def _normalize_postal_code(self, _: str, value: str | None) -> str | None:
        normalized = normalize_optional_label(value)
        return normalized.upper() if normalized else None

    @validates("country_code")
    def _normalize_country_code(self, _: str, value: str | None) -> str | None:
        stripped = normalize_optional_text(value)
        return stripped.upper() if stripped else None

    @validates("internal_notes")
    def _normalize_notes(self, _: str, value: str | None) -> str | None:
        return normalize_optional_text(value)

    @property
    def is_archived(self) -> bool:
        return self.status == ContactStatus.ARCHIVED
