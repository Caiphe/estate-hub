"""Metadata for files kept in object storage. The bytes never live in PostgreSQL.

Each row has exactly one parent: a property or a unit. ``storage_key`` is random and
server-generated; it is never returned by an API schema or written to audit metadata.
Archived rows keep their stored object as history.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.catalog.checks import normalized_check, not_blank_check
from app.catalog.text import normalize_label, normalize_optional_text
from app.core.database import Base, TimestampMixin, str_enum
from app.media.constants import (
    ALT_TEXT_MAX_LENGTH,
    DOCUMENT_TITLE_MAX_LENGTH,
    DOCUMENT_TYPES,
    IMAGE_TYPES,
    MEDIA_TYPE_MAX_LENGTH,
    ORIGINAL_FILENAME_MAX_LENGTH,
    STORAGE_KEY_MAX_LENGTH,
    STORAGE_KEY_PATTERN,
    DocumentCategory,
)


def _one_parent() -> CheckConstraint:
    return CheckConstraint("num_nonnulls(property_id, unit_id) = 1", name="one_parent")


def _media_type_check(allowed: frozenset[str]) -> CheckConstraint:
    values = ", ".join(f"'{value}'" for value in sorted(allowed))
    return CheckConstraint(f"media_type IN ({values})", name="media_type_allowed")


def _stored_file_checks(namespace: str) -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
            f"storage_key ~ '{STORAGE_KEY_PATTERN}' AND storage_key LIKE '{namespace}/%'",
            name="storage_key_format",
        ),
        CheckConstraint("byte_size > 0", name="byte_size_positive"),
        CheckConstraint(
            "char_length(original_filename) > 0 AND original_filename !~ '[/\\\\]'",
            name="original_filename_safe",
        ),
        CheckConstraint(
            "archived_by_id IS NULL OR archived_at IS NOT NULL", name="archived_by_needs_date"
        ),
    )


class _StoredFileMixin(TimestampMixin):
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Exactly one of these is set. RESTRICT: parents are archived, never deleted.
    property_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("properties.id", ondelete="RESTRICT")
    )
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("units.id", ondelete="RESTRICT"))
    storage_key: Mapped[str] = mapped_column(String(STORAGE_KEY_MAX_LENGTH), unique=True)
    # Display label only, validated at intake; never used to build a path.
    original_filename: Mapped[str] = mapped_column(String(ORIGINAL_FILENAME_MAX_LENGTH))
    # Detected from the file signature, never from the client's Content-Type.
    media_type: Mapped[str] = mapped_column(String(MEDIA_TYPE_MAX_LENGTH))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    archived_at: Mapped[datetime | None]
    archived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    @validates("property_id", "unit_id")
    def _parent_is_immutable(self, key: str, value: uuid.UUID | None) -> uuid.UUID | None:
        if getattr(self, key) is not None and getattr(self, key) != value:
            raise ValueError("A file cannot move to another parent.")
        return value

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


class MediaAsset(_StoredFileMixin, Base):
    """An image of a property or unit. Ordered by ``display_order``, then creation, then ID."""

    __tablename__ = "media_assets"

    width: Mapped[int] = mapped_column()
    height: Mapped[int] = mapped_column()
    display_order: Mapped[int] = mapped_column(default=0, server_default="0")
    alt_text: Mapped[str | None] = mapped_column(String(ALT_TEXT_MAX_LENGTH))
    is_cover: Mapped[bool] = mapped_column(default=False, server_default=false())

    __table_args__ = (
        _one_parent(),
        _media_type_check(frozenset(IMAGE_TYPES)),
        *_stored_file_checks("media"),
        CheckConstraint("width > 0 AND height > 0", name="dimensions_positive"),
        CheckConstraint("display_order >= 0", name="display_order_non_negative"),
        not_blank_check("alt_text"),
        CheckConstraint("NOT (is_cover AND archived_at IS NOT NULL)", name="cover_not_archived"),
        # At most one cover per parent.
        Index(
            "uq_media_assets_property_cover",
            "property_id",
            unique=True,
            postgresql_where=text("is_cover AND property_id IS NOT NULL"),
        ),
        Index(
            "uq_media_assets_unit_cover",
            "unit_id",
            unique=True,
            postgresql_where=text("is_cover AND unit_id IS NOT NULL"),
        ),
        # Active gallery order per parent.
        Index(
            "ix_media_assets_property_order",
            "property_id",
            "display_order",
            "created_at",
            "id",
            postgresql_where=text("archived_at IS NULL AND property_id IS NOT NULL"),
        ),
        Index(
            "ix_media_assets_unit_order",
            "unit_id",
            "display_order",
            "created_at",
            "id",
            postgresql_where=text("archived_at IS NULL AND unit_id IS NOT NULL"),
        ),
    )

    @validates("alt_text")
    def _normalize_alt_text(self, _: str, value: str | None) -> str | None:
        return normalize_optional_text(value)


class Document(_StoredFileMixin, Base):
    """A private document. Metadata, downloads, replacement, and archival each need
    ``property_documents:*`` permissions; nothing here is ever public."""

    __tablename__ = "documents"

    category: Mapped[DocumentCategory] = mapped_column(
        str_enum(DocumentCategory, "document_category")
    )
    title: Mapped[str] = mapped_column(String(DOCUMENT_TITLE_MAX_LENGTH))
    expiry_date: Mapped[date | None]
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    __mapper_args__: dict[str, Any] = {"eager_defaults": True, "version_id_col": version}
    __table_args__ = (
        _one_parent(),
        _media_type_check(frozenset(DOCUMENT_TYPES)),
        *_stored_file_checks("documents"),
        normalized_check("title"),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "ix_documents_property",
            "property_id",
            "created_at",
            "id",
            postgresql_where=text("property_id IS NOT NULL"),
        ),
        Index(
            "ix_documents_unit",
            "unit_id",
            "created_at",
            "id",
            postgresql_where=text("unit_id IS NOT NULL"),
        ),
        Index(
            "ix_documents_expiry_date",
            "expiry_date",
            postgresql_where=text("expiry_date IS NOT NULL"),
        ),
    )

    @validates("title")
    def _normalize_title(self, _: str, value: str) -> str:
        return normalize_label(value)
