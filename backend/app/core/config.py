import json
import os
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import List, Union
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from dotenv import load_dotenv

# Ensure .env is loaded from backend directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Campus Space & Resource Booking System"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    CAMPUS_TIMEZONE: str = "Asia/Kolkata"

    # MySQL Database Config
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "smart_campus"
    DB_POOL_NAME: str = "smart_campus_pool"
    DB_POOL_SIZE: int = 5
    DB_SSL_CA: str = ""
    DB_SSL_VERIFY_CERT: bool = True
    DB_SSL_VERIFY_IDENTITY: bool = True

    # JWT Security Config — Strong Secret Key required
    SECRET_KEY: str = Field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 hours

    # Booking Rules
    BOOKING_WINDOW_DAYS: int = 30
    DEFAULT_APPROVAL_CATEGORIES: List[str] = ["Auditorium", "Seminar Hall"]

    # CORS configuration
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "null"
    ]

    @field_validator("SECRET_KEY")
    def validate_secret_key(cls, v: str):
        v = (v or "").strip()
        if not v or v == "change_this_to_a_secure_random_key":
            raise ValueError("SECRET_KEY environment variable is required and must be set in .env to a secure secret.")
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long for production security.")
        return v

    @field_validator("DB_SSL_CA")
    @classmethod
    def validate_db_ssl_ca(cls, value: str):
        value = (value or "").strip().strip('"').strip("'")
        if not value:
            return value
        if not os.path.exists(value):
            raise ValueError(f"DB_SSL_CA points to a missing file: {value}")
        return value

    @field_validator("CAMPUS_TIMEZONE")
    @classmethod
    def validate_campus_timezone(cls, value: str):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("CAMPUS_TIMEZONE must be a valid IANA timezone.") from exc
        return value

    @field_validator("CORS_ORIGINS", mode="before")
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    class Config:
        env_file = env_path
        extra = "allow"


settings = Settings()
