
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Customer Feedback & Complaint Management System"
    database_url: str = "sqlite:///./customer_feedback.db"
    secret_key: str = "development-only-change-this-secret"
    access_token_expire_minutes: int = 30
    admin_email: str = ""
    admin_password: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
