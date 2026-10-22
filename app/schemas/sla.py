
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ComplaintSLARead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    complaint_id: int
    reference_number: str
    priority: str
    severity: str
    status: str
    first_response_at: datetime | None
    response_due_at: datetime | None
    resolution_due_at: datetime | None
    response_breached: bool
    resolution_breached: bool
    response_remaining_seconds: int | None
    resolution_remaining_seconds: int | None
