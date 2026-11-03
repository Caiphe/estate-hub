from typing import Annotated

from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25

PageLimit = Annotated[
    int, Field(ge=1, le=MAX_PAGE_SIZE, description=f"Page size, at most {MAX_PAGE_SIZE}.")
]
PageOffset = Annotated[int, Field(ge=0, le=1_000_000, description="Items to skip.")]


class Page[T](BaseModel):
    """The common collection response: one page of items plus pagination metadata."""

    items: list[T]
    total: int = Field(description="Items matching the filters, across all pages.")
    limit: int
    offset: int
