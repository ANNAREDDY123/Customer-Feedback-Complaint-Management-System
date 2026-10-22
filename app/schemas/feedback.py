
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.feedback import FeedbackStatus


class FeedbackCreate(BaseModel):
    category_id: int = Field(gt=0)
    rating: int = Field(ge=1, le=5)
    description: str = Field(min_length=3, max_length=5000)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Description must contain at least 3 characters")
        return value


class FeedbackUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    description: str | None = Field(default=None, min_length=3, max_length=5000)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Description must contain at least 3 characters")
        return value


class FeedbackStatusUpdate(BaseModel):
    status: FeedbackStatus


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    category_id: int
    rating: int
    description: str
    status: FeedbackStatus
    created_at: datetime
    updated_at: datetime


class FeedbackHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    feedback_id: int
    actor_user_id: int
    action: str
    old_value: str | None
    new_value: str | None
    created_at: datetime
