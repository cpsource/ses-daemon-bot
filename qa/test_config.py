"""Tests for configuration loading."""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config, load_config


def test_load_config_from_env_file(temp_env_file):
    """Test loading config from a .env file."""
    # Clear any existing env vars that might interfere
    env_vars = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SES_BUCKET",
        "NEON_DATABASE_URL",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ]
    old_values = {k: os.environ.pop(k, None) for k in env_vars}

    try:
        config = load_config(temp_env_file)

        assert config.aws.access_key_id == "test_access_key"
        assert config.aws.secret_access_key == "test_secret_key"
        assert config.aws.region == "us-west-2"
        assert config.aws.ses_bucket == "test-bucket"
        assert config.database.url == "postgresql://user:pass@localhost/testdb"  # NEON_DATABASE_URL
        assert config.llm.api_key == "sk-test-key"
        assert config.llm.model == "gpt-4"
    finally:
        # Restore old values
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v


def test_load_config_missing_file():
    """Test loading config when .env file doesn't exist."""
    from pathlib import Path

    # Clear any existing env vars
    env_vars = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SES_BUCKET",
        "NEON_DATABASE_URL",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ]
    old_values = {k: os.environ.pop(k, None) for k in env_vars}

    try:
        config = load_config(Path("/nonexistent/.env"))

        # Should return config with empty/default values
        assert isinstance(config, Config)
        assert config.aws.region == "us-east-1"  # Default
    finally:
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v


def test_load_config_empty_file(empty_env_file):
    """Test loading config from empty .env file."""
    # Clear any existing env vars
    env_vars = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SES_BUCKET",
        "NEON_DATABASE_URL",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ]
    old_values = {k: os.environ.pop(k, None) for k in env_vars}

    try:
        config = load_config(empty_env_file)

        assert config.aws.access_key_id == ""
        assert config.aws.secret_access_key == ""
        assert config.aws.region == "us-east-1"  # Default
    finally:
        # Restore old values
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v


def test_config_defaults():
    """Test default configuration values."""
    config = Config()

    assert config.aws.region == "us-east-1"
    assert config.database.host == "localhost"
    assert config.database.port == 5432
    assert config.llm.model == "gpt-4"
    assert config.daemon.poll_interval == 60


def test_daemon_config_defaults():
    """Test daemon configuration defaults."""
    config = Config()

    assert config.daemon.poll_interval == 60
    assert config.daemon.log_file is None
    assert config.daemon.pid_file is None
    assert config.daemon.dry_run is False
