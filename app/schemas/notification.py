
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    title: str
    message: str
    notification_type: str
    complaint_id: int | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None


class NotificationListRead(BaseModel):
    items: list[NotificationRead]
    total: int
    unread_count: int


class NotificationCreate(BaseModel):
    user_id: int
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1)
    notification_type: str = Field(
        default="GENERAL",
        min_length=1,
        max_length=50,
    )
    complaint_id: int | None = None
