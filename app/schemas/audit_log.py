
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None
    action: str
    resource_type: str
    resource_id: str | None
    details: str | None
    extra_data: dict | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
