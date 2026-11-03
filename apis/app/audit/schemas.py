from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.audit.metadata import validate_audit_metadata
from app.audit.models import (
    ENTITY_TYPE_MAX_LENGTH,
    EVENT_CODE_MAX_LENGTH,
    EVENT_CODE_PATTERN,
    REQUEST_ID_MAX_LENGTH,
)
from app.core.pagination import DEFAULT_PAGE_SIZE, PageLimit, PageOffset

EventCode = Annotated[str, Field(pattern=EVENT_CODE_PATTERN, max_length=EVENT_CODE_MAX_LENGTH)]
SafeMetadata = Annotated[dict[str, Any], AfterValidator(validate_audit_metadata)]


class AuditEventCreate(BaseModel):
    """Internal input for recording an audit event. Never built from client input."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    event_code: EventCode
    actor_id: UUID | None = None
    entity_type: str | None = Field(default=None, min_length=1, max_length=ENTITY_TYPE_MAX_LENGTH)
    entity_id: UUID | None = None
    request_id: str | None = Field(default=None, max_length=REQUEST_ID_MAX_LENGTH)
    metadata: SafeMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def _entity_reference_complete(self) -> Self:
        if (self.entity_type is None) != (self.entity_id is None):
            raise ValueError("entity_type and entity_id must be provided together.")
        return self


class AuditEventPublic(BaseModel):
    """Audit event output for staff with audit-read permission."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_code: str
    actor_id: UUID | None
    entity_type: str | None
    entity_id: UUID | None
    occurred_at: datetime
    request_id: str | None
    metadata: dict[str, Any] = Field(validation_alias="details")


class AuditEventQuery(BaseModel):
    """Filters and paging for the audit log. Results are newest first."""

    model_config = ConfigDict(extra="forbid")

    event_code: EventCode | None = None
    actor_id: UUID | None = None
    entity_type: str | None = Field(default=None, min_length=1, max_length=ENTITY_TYPE_MAX_LENGTH)
    entity_id: UUID | None = None
    occurred_from: AwareDatetime | None = Field(default=None, description="Inclusive.")
    occurred_to: AwareDatetime | None = Field(default=None, description="Exclusive.")
    limit: PageLimit = DEFAULT_PAGE_SIZE
    offset: PageOffset = 0

    @model_validator(mode="after")
    def _ordered_range(self) -> Self:
        if self.occurred_from and self.occurred_to and self.occurred_from >= self.occurred_to:
            raise ValueError("occurred_from must be before occurred_to.")
        return self
