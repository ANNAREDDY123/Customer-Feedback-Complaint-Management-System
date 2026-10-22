
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.complaint import (
    ComplaintPriority,
    ComplaintSeverity,
    ComplaintStatus,
)


def validate_attachment_urls(urls: list[str]) -> list[str]:
    if len(urls) > 10:
        raise ValueError("A complaint can contain at most 10 attachment URLs")

    normalized = []

    for raw_url in urls:
        value = raw_url.strip()
        parsed = urlparse(value)

        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or any(char.isspace() for char in value)
        ):
            raise ValueError(
                "Each attachment must be a valid HTTP or HTTPS URL"
            )

        normalized.append(value)

    return normalized


class ComplaintCreate(BaseModel):
    category_id: int = Field(gt=0)
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=10000)
    priority: ComplaintPriority = ComplaintPriority.MEDIUM
    severity: ComplaintSeverity = ComplaintSeverity.MEDIUM
    attachment_urls: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Title must contain at least 3 characters")
        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Description must contain at least 10 characters")
        return value

    @field_validator("attachment_urls")
    @classmethod
    def check_attachment_urls(cls, value: list[str]) -> list[str]:
        return validate_attachment_urls(value)


class ComplaintUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    description: str | None = Field(
        default=None,
        min_length=10,
        max_length=10000,
    )
    priority: ComplaintPriority | None = None
    severity: ComplaintSeverity | None = None
    attachment_urls: list[str] | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if len(value) < 3:
            raise ValueError("Title must contain at least 3 characters")

        return value

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: str | None) -> str | None:
        if value is None:
            return None

        value = value.strip()

        if len(value) < 10:
            raise ValueError("Description must contain at least 10 characters")

        return value

    @field_validator("attachment_urls")
    @classmethod
    def check_attachment_urls(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        if value is None:
            return None

        return validate_attachment_urls(value)


class ComplaintStatusUpdate(BaseModel):
    status: ComplaintStatus


class ComplaintRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference_number: str
    customer_id: int
    category_id: int
    assigned_agent_id: int | None = None
    title: str
    description: str
    priority: ComplaintPriority
    severity: ComplaintSeverity
    status: ComplaintStatus
    attachment_urls: list[str]
    created_at: datetime
    updated_at: datetime


class ComplaintPage(BaseModel):
    items: list[ComplaintRead]
    total: int
    page: int
    page_size: int
    total_pages: int


class ComplaintHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    complaint_id: int
    actor_user_id: int
    action: str
    old_value: str | None
    new_value: str | None
    created_at: datetime
