
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AgentCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: EmailStr
    is_active: bool
    created_at: datetime


class AgentWorkload(BaseModel):
    agent_id: int
    agent_name: str
    agent_email: EmailStr
    is_active: bool
    assigned_complaints: int
    open_complaints: int
    in_progress_complaints: int
    waiting_for_customer: int
