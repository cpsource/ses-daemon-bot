"""Configuration loader.

Loads configuration from environment variables.
Default .env location: /home/ubuntu/.env
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Default .env file location
DEFAULT_ENV_FILE = Path("/home/ubuntu/.env")


@dataclass
class AWSConfig:
    """AWS credentials and settings."""

    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = "us-east-1"
    ses_bucket: str = ""


@dataclass
class DatabaseConfig:
    """PostgreSQL database settings."""

    url: str = ""
    # Parsed components (optional, derived from url)
    host: str = "localhost"
    port: int = 5432
    name: str = "ses_daemon"
    user: str = ""
    password: str = ""


@dataclass
class LLMConfig:
    """LLM/OpenAI settings for intent classification."""

    api_key: str = ""
    model: str = "gpt-4"
    base_url: Optional[str] = None  # For custom endpoints


@dataclass
class DaemonConfig:
    """Daemon runtime settings."""

    poll_interval: int = 60
    log_file: Optional[str] = None
    pid_file: Optional[str] = None
    dry_run: bool = False


@dataclass
class Config:
    """Main configuration container."""

    aws: AWSConfig = field(default_factory=AWSConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    daemon: DaemonConfig = field(default_factory=DaemonConfig)


def load_config(env_file: Optional[Path] = None) -> Config:
    """Load configuration from environment variables.

    Args:
        env_file: Path to .env file. Defaults to /home/ubuntu/.env

    Returns:
        Config object with all settings loaded.
    """
    env_path = env_file or DEFAULT_ENV_FILE

    if env_path.exists():
        load_dotenv(env_path)

    config = Config(
        aws=AWSConfig(
            access_key_id=os.getenv("AWS_ACCESS_KEY", ""),
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", ""),
            region=os.getenv("AWS_REGION", "us-east-1"),
            ses_bucket=os.getenv("SES_BUCKET", ""),
        ),
        database=DatabaseConfig(
            url=os.getenv("NEON_DATABASE_URL", ""),
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            name=os.getenv("DB_NAME", "ses_daemon"),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
        ),
        llm=LLMConfig(
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("LLM_MODEL", "gpt-4"),
            base_url=os.getenv("LLM_BASE_URL"),
        ),
        daemon=DaemonConfig(
            poll_interval=int(os.getenv("POLL_INTERVAL", "60")),
            log_file=os.getenv("LOG_FILE"),
            pid_file=os.getenv("PID_FILE"),
        ),
    )

    return config


# Singleton instance (loaded on import if needed)
_config: Optional[Config] = None


def get_config(env_file: Optional[Path] = None) -> Config:
    """Get or create the singleton config instance."""
    global _config
    if _config is None:
        _config = load_config(env_file)
    return _config
