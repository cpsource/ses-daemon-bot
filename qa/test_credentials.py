"""Tests for credential validation."""

import os
import subprocess
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config
from main import check_credentials


def test_credentials_all_present(temp_env_file):
    """Test credential validation with all credentials present."""
    # Clear existing env vars
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
        errors, warnings, success = check_credentials(config)

        assert len(errors) == 0
        assert len(success) >= 6  # At least 6 successful checks
    finally:
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v


def test_credentials_missing_all(empty_env_file):
    """Test credential validation with no credentials."""
    # Clear existing env vars
    env_vars = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SES_BUCKET",
        "NEON_DATABASE_URL",
        "DB_HOST",
        "DB_USER",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ]
    old_values = {k: os.environ.pop(k, None) for k in env_vars}

    try:
        config = load_config(empty_env_file)
        errors, warnings, success = check_credentials(config)

        assert len(errors) >= 4  # At least 4 missing credentials
        assert any("AWS_ACCESS_KEY" in e for e in errors)
        assert any("AWS_SECRET_ACCESS_KEY" in e for e in errors)
        assert any("SES_BUCKET" in e for e in errors)
        assert any("OPENAI_API_KEY" in e for e in errors)
    finally:
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v


def test_credentials_partial(partial_env_file):
    """Test credential validation with partial credentials."""
    # Clear existing env vars
    env_vars = [
        "AWS_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "SES_BUCKET",
        "NEON_DATABASE_URL",
        "DB_HOST",
        "DB_USER",
        "OPENAI_API_KEY",
        "LLM_MODEL",
    ]
    old_values = {k: os.environ.pop(k, None) for k in env_vars}

    try:
        config = load_config(partial_env_file)
        errors, warnings, success = check_credentials(config)

        # Should have some successes and some errors
        assert len(success) > 0
        assert len(errors) > 0
        # AWS_ACCESS_KEY is in partial file
        assert any("AWS_ACCESS_KEY" in s for s in success)
        # AWS_SECRET_ACCESS_KEY is missing
        assert any("AWS_SECRET_ACCESS_KEY" in e for e in errors)
    finally:
        for k, v in old_values.items():
            if v is not None:
                os.environ[k] = v


def test_test_creds_cli_success(temp_env_file):
    """Test --test-creds CLI with valid credentials."""
    # Use clean environment to avoid interference
    clean_env = {"PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, "main.py", "--test-creds", "--config", str(temp_env_file)],
        capture_output=True,
        text=True,
        env=clean_env,
    )
    assert result.returncode == 0
    assert "SUCCESS" in result.stdout


def test_test_creds_cli_failure(empty_env_file):
    """Test --test-creds CLI with missing credentials."""
    # Use clean environment to avoid interference from parent env vars
    clean_env = {"PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [sys.executable, "main.py", "--test-creds", "--config", str(empty_env_file)],
        capture_output=True,
        text=True,
        env=clean_env,
    )
    assert result.returncode == 1
    assert "FAILED" in result.stdout
    assert "[ERROR]" in result.stdout
