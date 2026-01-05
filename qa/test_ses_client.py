"""Tests for SES client."""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import AWSConfig
from ses_client import Email, SESClient


def test_email_dataclass():
    """Test Email dataclass creation."""
    email = Email(
        message_id="<test@example.com>",
        s3_key="emails/test123",
        sender="sender@example.com",
        sender_name="Test Sender",
        recipient="recipient@frflashy.com",
        subject="Test Subject",
        body_text="This is a test email.",
        body_html="<p>This is a test email.</p>",
        received_at=datetime.now(),
        raw_content=b"raw email content",
    )

    assert email.message_id == "<test@example.com>"
    assert email.sender == "sender@example.com"
    assert email.subject == "Test Subject"
    assert email.body == "This is a test email."


def test_email_body_fallback_to_html():
    """Test Email.body falls back to HTML when text is empty."""
    email = Email(
        message_id="<test@example.com>",
        s3_key="emails/test123",
        sender="sender@example.com",
        sender_name="",
        recipient="recipient@frflashy.com",
        subject="Test",
        body_text="",
        body_html="<p>Hello</p><br><p>World</p>",
        received_at=datetime.now(),
        raw_content=b"",
    )

    # Should strip HTML tags
    assert "Hello" in email.body
    assert "World" in email.body
    assert "<p>" not in email.body


def test_email_body_empty():
    """Test Email.body returns empty string when both are empty."""
    email = Email(
        message_id="<test@example.com>",
        s3_key="emails/test123",
        sender="sender@example.com",
        sender_name="",
        recipient="recipient@frflashy.com",
        subject="Test",
        body_text="",
        body_html="",
        received_at=datetime.now(),
        raw_content=b"",
    )

    assert email.body == ""


@patch("ses_client.boto3.client")
def test_ses_client_init(mock_boto_client):
    """Test SESClient initialization."""
    config = AWSConfig(
        access_key_id="test_key",
        secret_access_key="test_secret",
        region="us-east-1",
        ses_bucket="test-bucket",
    )

    client = SESClient(config)

    assert client.bucket == "test-bucket"
    assert client.region == "us-east-1"
    mock_boto_client.assert_called_once_with(
        "s3",
        region_name="us-east-1",
        aws_access_key_id="test_key",
        aws_secret_access_key="test_secret",
    )


@patch("ses_client.boto3.client")
def test_list_pending_emails(mock_boto_client):
    """Test listing pending emails from S3."""
    # Setup mock
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    mock_paginator = MagicMock()
    mock_s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "emails/"},  # Should be skipped
                {"Key": "emails/email1"},
                {"Key": "emails/email2"},
            ]
        }
    ]

    config = AWSConfig(
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        ses_bucket="test-bucket",
    )

    client = SESClient(config)
    keys = list(client.list_pending_emails())

    assert keys == ["emails/email1", "emails/email2"]


@patch("ses_client.boto3.client")
def test_count_pending_emails(mock_boto_client):
    """Test counting pending emails."""
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    mock_paginator = MagicMock()
    mock_s3.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "Contents": [
                {"Key": "emails/"},
                {"Key": "emails/email1"},
                {"Key": "emails/email2"},
                {"Key": "emails/email3"},
            ]
        }
    ]

    config = AWSConfig(
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        ses_bucket="test-bucket",
    )

    client = SESClient(config)
    count = client.count_pending_emails()

    assert count == 3


@patch("ses_client.boto3.client")
def test_mark_processed(mock_boto_client):
    """Test marking an email as processed."""
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    config = AWSConfig(
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        ses_bucket="test-bucket",
    )

    client = SESClient(config)
    result = client.mark_processed("emails/test123")

    assert result is True
    mock_s3.copy_object.assert_called_once()
    mock_s3.delete_object.assert_called_once_with(
        Bucket="test-bucket", Key="emails/test123"
    )


@patch("ses_client.boto3.client")
def test_parse_simple_email(mock_boto_client):
    """Test parsing a simple email."""
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3

    # Simple email content
    raw_email = b"""From: Test Sender <sender@example.com>
To: recipient@frflashy.com
Subject: Test Subject
Date: Sat, 04 Jan 2025 12:00:00 +0000
Message-ID: <test123@example.com>
Content-Type: text/plain; charset="utf-8"

This is the email body.
"""

    mock_s3.get_object.return_value = {"Body": MagicMock(read=lambda: raw_email)}

    config = AWSConfig(
        access_key_id="test",
        secret_access_key="test",
        region="us-east-1",
        ses_bucket="test-bucket",
    )

    client = SESClient(config)
    email = client.fetch_email("emails/test123")

    assert email is not None
    assert email.sender == "sender@example.com"
    assert email.sender_name == "Test Sender"
    assert email.recipient == "recipient@frflashy.com"
    assert email.subject == "Test Subject"
    assert "email body" in email.body_text
