import logging
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

class Settings(BaseSettings):
    # Meta Instagram Webhook configuration
    instagram_verify_token: str = "mock_verify_token"
    instagram_app_secret: str = "mock_app_secret"
    instagram_page_access_token: str = "mock_page_access_token"
    instagram_api_version: str = "v20.0"
    
    # Server configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # MongoDB Configuration
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "instagram_webhook_db"
    
    # Rate Limiting Configuration
    rate_limit_calls: int = 60
    rate_limit_period_seconds: int = 60
    
    # OpenTelemetry Configuration
    otel_service_name: str = "instagram-webhook-backend"
    otel_exporter_otlp_endpoint: Optional[str] = None
    
    # Allow reading from .env file
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Validate that we have active configuration for production use
if settings.instagram_verify_token == "mock_verify_token":
    logger.warning("Using default INSTAGRAM_VERIFY_TOKEN. Please update it in production.")
if settings.instagram_app_secret == "mock_app_secret":
    logger.warning("Using default INSTAGRAM_APP_SECRET. Please update it in production.")
if settings.instagram_page_access_token == "mock_page_access_token":
    logger.warning("Using default INSTAGRAM_PAGE_ACCESS_TOKEN. Please update it in production.")
