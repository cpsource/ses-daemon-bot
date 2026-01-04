"""Shared pytest fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_env_file():
    """Create a temporary .env file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# Test environment\n")
        f.write("AWS_ACCESS_KEY=test_access_key\n")
        f.write("AWS_SECRET_ACCESS_KEY=test_secret_key\n")
        f.write("AWS_REGION=us-west-2\n")
        f.write("SES_BUCKET=test-bucket\n")
        f.write("NEON_DATABASE_URL=postgresql://user:pass@localhost/testdb\n")
        f.write("OPENAI_API_KEY=sk-test-key\n")
        f.write("LLM_MODEL=gpt-4\n")
        temp_path = f.name

    yield Path(temp_path)

    # Cleanup
    os.unlink(temp_path)


@pytest.fixture
def empty_env_file():
    """Create an empty .env file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# Empty test environment\n")
        temp_path = f.name

    yield Path(temp_path)

    # Cleanup
    os.unlink(temp_path)


@pytest.fixture
def partial_env_file():
    """Create a partial .env file with some missing credentials."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# Partial test environment\n")
        f.write("AWS_ACCESS_KEY=test_access_key\n")
        f.write("AWS_REGION=us-east-1\n")
        # Missing: AWS_SECRET_ACCESS_KEY, SES_BUCKET, NEON_DATABASE_URL, OPENAI_API_KEY
        temp_path = f.name

    yield Path(temp_path)

    # Cleanup
    os.unlink(temp_path)
