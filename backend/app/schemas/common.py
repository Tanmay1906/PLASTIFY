"""PLASTIFY Common API Schemas.

Consistent API envelopes, error representations, and pagination models.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class ErrorDetail(BaseModel):
    """Detailed error object returned within error envelopes."""

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Contextual error metadata")


class APIResponse(BaseModel, Generic[DataT]):
    """Standard success API response envelope."""

    success: bool = Field(default=True, description="Indicates request success")
    data: DataT = Field(..., description="Response payload")
    request_id: Optional[str] = Field(default=None, description="Unique correlation request ID")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Response generation UTC timestamp",
    )


class APIErrorResponse(BaseModel):
    """Standard error API response envelope."""

    success: bool = Field(default=False, description="Always False for error responses")
    error: ErrorDetail = Field(..., description="Error details payload")
    request_id: Optional[str] = Field(default=None, description="Unique correlation request ID")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Response generation UTC timestamp",
    )


class PaginationMeta(BaseModel):
    """Metadata regarding pagination state."""

    page: int = Field(..., ge=1, description="Current 1-based page number")
    page_size: int = Field(..., ge=1, le=100, description="Items per page limit")
    total_items: int = Field(..., ge=0, description="Total number of matching items")
    total_pages: int = Field(..., ge=0, description="Total number of pages")


class PaginatedResponse(BaseModel, Generic[DataT]):
    """Standard envelope for paginated collection responses."""

    success: bool = Field(default=True)
    items: List[DataT] = Field(default_factory=list)
    meta: PaginationMeta
    request_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
