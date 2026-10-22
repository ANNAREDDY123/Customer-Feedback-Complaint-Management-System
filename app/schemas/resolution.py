
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ComplaintCommentCreate(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    is_internal: bool = False

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Comment cannot be empty")
        return value


class ComplaintCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    complaint_id: int
    author_user_id: int
    content: str
    is_internal: bool
    created_at: datetime


class ComplaintResolveRequest(BaseModel):
    resolution_details: str = Field(min_length=10, max_length=10000)

    @field_validator("resolution_details")
    @classmethod
    def validate_resolution_details(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Resolution details must contain at least 10 characters")
        return value


class ComplaintReopenRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 5:
            raise ValueError("Reopening reason must contain at least 5 characters")
        return value


class ComplaintResolutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference_number: str
    status: str
    resolution_details: str | None
    resolved_by_user_id: int | None
    resolved_at: datetime | None
    closed_at: datetime | None
