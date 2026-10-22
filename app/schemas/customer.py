
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerCreate(BaseModel):
    # Customers may omit this to create their own profile.
    # Authorized staff must provide it when creating a profile for another user.
    user_id: int | None = Field(default=None, gt=0)

    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)

    @field_validator("phone", "address", "city", "state", "postal_code")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None


class CustomerUpdate(BaseModel):
    phone: str | None = Field(default=None, max_length=20)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)

    @field_validator("phone", "address", "city", "state", "postal_code")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        value = value.strip()
        return value or None


class CustomerStatusUpdate(BaseModel):
    is_active: bool


class CustomerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    phone: str | None
    address: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerListItem(CustomerRead):
    full_name: str
    email: str


class CustomerPage(BaseModel):
    items: list[CustomerListItem]
    total: int
    page: int
    page_size: int
    total_pages: int
