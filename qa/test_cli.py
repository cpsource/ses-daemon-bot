"""Tests for command line interface."""

import subprocess
import sys


def test_help_option():
    """Test --help displays usage information."""
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "AWS SES mail processor" in result.stdout
    assert "--daemon" in result.stdout
    assert "--dry-run" in result.stdout
    assert "--test-creds" in result.stdout
    assert "--config" in result.stdout


def test_version_option():
    """Test --version displays version."""
    result = subprocess.run(
        [sys.executable, "main.py", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "ses-daemon-bot" in result.stdout
    assert "0.1.3" in result.stdout


def test_dry_run_with_once():
    """Test --dry-run --once runs and exits cleanly."""
    result = subprocess.run(
        [sys.executable, "main.py", "--dry-run", "--once"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "dry-run mode" in result.stderr


def test_verbose_logging():
    """Test -v enables debug logging."""
    result = subprocess.run(
        [sys.executable, "main.py", "-v", "--once"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "DEBUG" in result.stderr


def test_invalid_option():
    """Test invalid option shows error."""
    result = subprocess.run(
        [sys.executable, "main.py", "--invalid-option"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "unrecognized arguments" in result.stderr


def test_interval_option():
    """Test --interval accepts integer value."""
    result = subprocess.run(
        [sys.executable, "main.py", "--interval", "30", "--once"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "interval: 30s" in result.stderr


def test_interval_invalid_value():
    """Test --interval rejects non-integer value."""
    result = subprocess.run(
        [sys.executable, "main.py", "--interval", "abc"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "invalid int value" in result.stderr
