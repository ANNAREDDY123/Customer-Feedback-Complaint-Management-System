
from pydantic import BaseModel, Field, model_validator

from app.models.complaint import ComplaintStatus


class BulkAssignRequest(BaseModel):
    complaint_ids: list[int] = Field(min_length=1, max_length=100)
    agent_id: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_complaint_ids(self):
        if any(complaint_id <= 0 for complaint_id in self.complaint_ids):
            raise ValueError("Complaint IDs must be positive integers")

        if len(self.complaint_ids) != len(set(self.complaint_ids)):
            raise ValueError("Complaint IDs must not contain duplicates")

        return self


class BulkStatusRequest(BaseModel):
    complaint_ids: list[int] = Field(min_length=1, max_length=100)
    status: ComplaintStatus

    @model_validator(mode="after")
    def validate_complaint_ids(self):
        if any(complaint_id <= 0 for complaint_id in self.complaint_ids):
            raise ValueError("Complaint IDs must be positive integers")

        if len(self.complaint_ids) != len(set(self.complaint_ids)):
            raise ValueError("Complaint IDs must not contain duplicates")

        return self


class BulkOperationResult(BaseModel):
    message: str
    updated_count: int
    complaint_ids: list[int]
