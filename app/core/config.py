from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    ENVIRONMENT: Literal["development", "production", "test"] = "development"
    APP_NAME: str = "PM Buddy - AI Operations Platform"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_URL: str = "http://localhost:8000"
    ENCRYPTION_KEY: str = "dGhpcy1pcy1hLTMyLWJ5dGUtc2VjcmV0LWtleS0xMjM="  # Base64 32-byte key

    # Supabase & Database
    NEXT_PUBLIC_SUPABASE_URL: str = "https://mock-tenant.supabase.co"
    NEXT_PUBLIC_SUPABASE_ANON_KEY: str = "mock-anon-key"
    SUPABASE_SERVICE_ROLE_KEY: str = "mock-service-role-key"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pm_buddy"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # AI LLM Settings
    LLM_PROVIDER: str = "gemini"  # gemini, openai, anthropic, mock
    LLM_MODEL: str = "gemini-3.6-flash"
    LLM_API_KEY: str = "mock-key"
    GEMINI_API_KEY: str = ""
    gemini_api_key: str = ""
    OPENAI_API_KEY: str = "mock-key"
    ANTHROPIC_API_KEY: str = "mock-key"

    # Calendar Integration
    DEFAULT_CALENDAR_PROVIDER: str = "local"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""


settings = Settings()
