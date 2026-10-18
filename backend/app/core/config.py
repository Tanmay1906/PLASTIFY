"""PLASTIFY Core Configuration Module.

Centralized configuration using Pydantic v2 BaseSettings.
All sensitive parameters and environment settings are loaded from environment
variables or .env files, ensuring secrets are never hardcoded.
"""

from functools import lru_cache
from typing import List, Optional, Union
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings schema and environment variable loader."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Project Information
    PROJECT_NAME: str = Field(default="PLASTIFY", description="Application name")
    PROJECT_DESCRIPTION: str = Field(
        default="Production-grade plastic recovery verification and circular-economy platform backend.",
        description="Application description",
    )
    VERSION: str = Field(default="0.1.0", description="SemVer application version")
    API_V1_STR: str = Field(default="/api/v1", description="Prefix for API v1 routes")
    ENVIRONMENT: str = Field(
        default="development",
        description="Deployment environment (development, staging, production, test)",
    )
    DEBUG: bool = Field(default=False, description="Debug mode flag")

    # Logging
    LOG_LEVEL: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    LOG_FORMAT: str = Field(default="json", description="Log format: 'json' or 'console'")

    # Security & JWT Authentication
    SECRET_KEY: str = Field(
        default="plastify-secret-key-must-be-overridden-in-production-environment-42",
        description="Cryptographic secret key for signing sessions/tokens",
    )
    JWT_SECRET_KEY: Optional[str] = Field(
        default=None,
        description="Dedicated JWT secret key (defaults to SECRET_KEY if unset)",
    )
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT cryptographic signing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60, description="Access token expiration window in minutes"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=7, description="Refresh token expiration window in days"
    )
    ALLOWED_HOSTS: Union[List[str], str] = Field(default=["*"], description="Allowed HTTP host headers")
    CORS_ORIGINS: Union[List[str], str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"],
        description="Allowed CORS origin URLs",
    )

    # Request ID Correlation
    REQUEST_ID_HEADER: str = Field(default="X-Request-ID", description="Header name for Request Correlation ID")

    # PostgreSQL Database Settings
    POSTGRES_SERVER: str = Field(default="localhost", description="PostgreSQL host")
    POSTGRES_PORT: int = Field(default=5432, description="PostgreSQL port")
    POSTGRES_USER: str = Field(default="plastify_user", description="PostgreSQL username")
    POSTGRES_PASSWORD: str = Field(default="plastify_password", description="PostgreSQL password")
    POSTGRES_DB: str = Field(default="plastify_db", description="PostgreSQL database name")

    # Explicit Database URLs (optional override, e.g. for CI/testing)
    DATABASE_URL: Optional[str] = Field(default=None, description="Full sync database URL override")
    ASYNC_DATABASE_URL: Optional[str] = Field(default=None, description="Full async database URL override")

    # DB Connection Pool Config
    DB_POOL_SIZE: int = Field(default=10, description="SQLAlchemy connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=20, description="SQLAlchemy connection pool max overflow")
    DB_POOL_TIMEOUT: int = Field(default=30, description="Connection pool timeout in seconds")
    DB_POOL_RECYCLE: int = Field(default=1800, description="Recycle connections older than seconds")
    DB_ECHO: bool = Field(default=False, description="Log raw SQL queries")

    # Redis Settings
    REDIS_HOST: str = Field(default="localhost", description="Redis host")
    REDIS_PORT: int = Field(default=6379, description="Redis port")
    REDIS_DB: int = Field(default=0, description="Redis database index")
    REDIS_PASSWORD: Optional[str] = Field(default=None, description="Redis authentication password")
    REDIS_URL: Optional[str] = Field(default=None, description="Full Redis URL override")

    # Celery Worker Settings
    CELERY_BROKER_URL: Optional[str] = Field(default=None, description="Celery message broker URL")
    CELERY_RESULT_BACKEND: Optional[str] = Field(default=None, description="Celery results backend URL")

    # S3-Compatible Object Storage (MinIO / AWS S3)
    S3_ENDPOINT_URL: Optional[str] = Field(
        default=None,
        description="S3 endpoint URL (e.g. http://localhost:9000 for MinIO, None for AWS S3)",
    )
    S3_REGION_NAME: str = Field(default="us-east-1", description="S3 region name")
    S3_ACCESS_KEY_ID: str = Field(default="minioadmin", description="S3 / MinIO access key ID")
    S3_SECRET_ACCESS_KEY: str = Field(
        default="minioadmin", description="S3 / MinIO secret access key"
    )
    S3_BUCKET_NAME: str = Field(default="plastify-evidence", description="S3 evidence bucket name")
    S3_USE_SSL: bool = Field(default=False, description="Use SSL for S3 connection")
    S3_SIGNED_URL_EXPIRE_SECONDS: int = Field(
        default=900, description="Expiration time for short-lived presigned URLs in seconds"
    )

    # Evidence Validation & Storage Limits
    MAX_EVIDENCE_FILE_SIZE_BYTES: int = Field(
        default=15 * 1024 * 1024, description="Maximum allowed evidence upload size in bytes (15 MB default)"
    )
    MALWARE_SCANNER_TYPE: str = Field(
        default="mock", description="Configured malware scanner implementation ('mock', 'clamav')"
    )

    # Logistics & Delivery Weight Tolerance
    DEFAULT_WEIGHT_TOLERANCE_PERCENT: float = Field(
        default=2.0,
        description="Default allowable weight tolerance threshold percentage (+/- percent)",
    )

    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        """Allow comma-separated strings or list representation."""
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Enforce production security controls ensuring default secrets are not deployed."""
        if self.ENVIRONMENT == "production":
            default_placeholder = "plastify-secret-key-must-be-overridden-in-production-environment-42"
            if self.SECRET_KEY == default_placeholder:
                raise ValueError(
                    "Production environment detected: SECRET_KEY must be overridden with a secure secret string."
                )
            if self.JWT_SECRET_KEY == default_placeholder:
                raise ValueError(
                    "Production environment detected: JWT_SECRET_KEY cannot match default development placeholder."
                )
        return self

    @property
    def async_database_url_constructed(self) -> str:
        """Return the async database connection URI."""
        if self.ASYNC_DATABASE_URL:
            return self.ASYNC_DATABASE_URL
        if self.DATABASE_URL:
            # If standard postgresql:// provided, ensure asyncpg driver is specified
            url = self.DATABASE_URL
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url_constructed(self) -> str:
        """Return the sync database connection URI (used by Alembic / sync tools)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@"
            f"{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url_constructed(self) -> str:
        """Return the Redis connection URI."""
        if self.REDIS_URL:
            return self.REDIS_URL
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def celery_broker_url_constructed(self) -> str:
        """Return the Celery broker connection URI (Redis DB 1 by default)."""
        if self.CELERY_BROKER_URL:
            return self.CELERY_BROKER_URL
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    @property
    def celery_result_backend_constructed(self) -> str:
        """Return the Celery result backend URI (Redis DB 2 by default)."""
        if self.CELERY_RESULT_BACKEND:
            return self.CELERY_RESULT_BACKEND
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/2"

    @property
    def effective_jwt_secret_key(self) -> str:
        """Return JWT secret key, falling back to SECRET_KEY."""
        return self.JWT_SECRET_KEY or self.SECRET_KEY


@lru_cache()
def get_settings() -> Settings:
    """Retrieve cached application settings instance."""
    return Settings()
