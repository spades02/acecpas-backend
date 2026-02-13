"""
AceCPAs Backend - Configuration Module
Loads and validates environment variables using Pydantic Settings.
"""
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Supabase Configuration
    supabase_url: str
    supabase_key: str  # Anon key for client-side
    supabase_service_key: str  # Service role key for server-side operations
    
    # OpenAI Configuration
    openai_api_key: str
    openai_embedding_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o"
    
    # Redis Configuration (for Celery)
    redis_url: str = "redis://localhost:6379/0"
    
    # S3/Storage Configuration
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    s3_bucket_name: Optional[str] = None
    
    # Application Settings
    debug: bool = False
    environment: str = "development"
    
    # Mapper Agent Thresholds
    mapper_auto_threshold: float = 0.92  # Auto-assign if similarity > this
    mapper_min_threshold: float = 0.5    # Reject if similarity < this
    
    # Auditor Agent Settings
    capex_threshold: float = 2500.0  # Flag R&M transactions above this
    flagged_keywords: list[str] = [
        "venmo", "cash", "reimbursement", "personal", 
        "atm", "withdrawal", "transfer"
    ]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
