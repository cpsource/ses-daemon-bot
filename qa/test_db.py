"""Tests for database operations."""

import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DatabaseConfig
from db import Database, EmailRecord, CREATE_EMAILS_TABLE


def test_email_record_dataclass():
    """Test EmailRecord dataclass creation."""
    record = EmailRecord(
        id=1,
        message_id="<test@example.com>",
        s3_key="emails/test123",
        sender="sender@example.com",
        sender_name="Test Sender",
        recipient="recipient@frflashy.com",
        subject="Test Subject",
        body="This is a test email.",
        received_at=datetime(2025, 1, 4, 12, 0, 0),
        processed_at=datetime(2025, 1, 4, 12, 1, 0),
        intent_flags=[True, False, False, False, False],
        intent_label="send_info",
        handler_result={"sent": True},
        status="processed",
    )

    assert record.id == 1
    assert record.message_id == "<test@example.com>"
    assert record.intent_label == "send_info"
    assert record.status == "processed"


def test_email_record_from_row():
    """Test creating EmailRecord from database row dict."""
    row = {
        "id": 42,
        "message_id": "<test123@example.com>",
        "s3_key": "emails/abc123",
        "sender": "user@example.com",
        "sender_name": "User Name",
        "recipient": "support@frflashy.com",
        "subject": "Help needed",
        "body": "Please help me.",
        "received_at": datetime(2025, 1, 4, 10, 0, 0),
        "processed_at": datetime(2025, 1, 4, 10, 5, 0),
        "intent_flags": [False, False, False, True, False],
        "intent_label": "speak_to_human",
        "handler_result": {"escalated": True},
        "status": "escalated",
    }

    record = EmailRecord.from_row(row)

    assert record.id == 42
    assert record.sender == "user@example.com"
    assert record.intent_label == "speak_to_human"


def test_email_record_from_row_optional_fields():
    """Test EmailRecord.from_row with missing optional fields."""
    row = {
        "id": 1,
        "message_id": "<test@example.com>",
        "s3_key": "emails/test",
        "sender": "sender@example.com",
        "processed_at": datetime(2025, 1, 4, 12, 0, 0),
        "intent_flags": [False, False, True, False, False],
        "intent_label": "unknown",
        "status": "processed",
        # Optional fields missing
    }

    record = EmailRecord.from_row(row)

    assert record.sender_name is None
    assert record.recipient is None
    assert record.subject is None
    assert record.body is None
    assert record.received_at is None
    assert record.handler_result is None


@patch("db.psycopg2.connect")
def test_database_init(mock_connect):
    """Test Database initialization."""
    config = DatabaseConfig(url="postgresql://user:pass@localhost/testdb")

    db = Database(config)

    assert db.connection_url == "postgresql://user:pass@localhost/testdb"


@patch("db.psycopg2.connect")
def test_database_get_connection(mock_connect):
    """Test get_connection context manager."""
    mock_conn = MagicMock()
    mock_connect.return_value = mock_conn

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    with db.get_connection() as conn:
        assert conn == mock_conn

    mock_conn.close.assert_called_once()


@patch("db.psycopg2.connect")
def test_database_get_cursor(mock_connect):
    """Test get_cursor context manager."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    with db.get_cursor() as cursor:
        assert cursor == mock_cursor

    mock_conn.commit.assert_called_once()
    mock_cursor.close.assert_called_once()


@patch("db.psycopg2.connect")
def test_database_get_cursor_rollback_on_error(mock_connect):
    """Test get_cursor rolls back on exception."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    try:
        with db.get_cursor() as cursor:
            raise ValueError("test error")
    except ValueError:
        pass

    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()


@patch("db.psycopg2.connect")
def test_database_initialize(mock_connect):
    """Test database schema initialization."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.initialize()

    assert result is True
    mock_cursor.execute.assert_called_once_with(CREATE_EMAILS_TABLE)


@patch("db.psycopg2.connect")
def test_database_initialize_failure(mock_connect):
    """Test database initialization handles errors."""
    mock_connect.side_effect = Exception("Connection failed")

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.initialize()

    assert result is False


@patch("db.psycopg2.connect")
def test_database_save_email(mock_connect):
    """Test saving an email to the database."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {"id": 123}

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.save_email(
        message_id="<test@example.com>",
        s3_key="emails/test123",
        sender="sender@example.com",
        intent_flags=[True, False, False, False, False],
        intent_label="send_info",
        subject="Test",
        body="Body text",
    )

    assert result == 123
    mock_cursor.execute.assert_called_once()


@patch("db.psycopg2.connect")
def test_database_save_email_failure(mock_connect):
    """Test save_email handles errors gracefully."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.execute.side_effect = Exception("Insert failed")

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.save_email(
        message_id="<test@example.com>",
        s3_key="emails/test",
        sender="sender@example.com",
        intent_flags=[False, False, True, False, False],
        intent_label="unknown",
    )

    assert result is None


@patch("db.psycopg2.connect")
def test_database_get_email_by_message_id(mock_connect):
    """Test retrieving email by message ID."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {
        "id": 1,
        "message_id": "<test@example.com>",
        "s3_key": "emails/test",
        "sender": "sender@example.com",
        "processed_at": datetime.now(),
        "intent_flags": [True, False, False, False, False],
        "intent_label": "send_info",
        "status": "processed",
    }

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    record = db.get_email_by_message_id("<test@example.com>")

    assert record is not None
    assert record.message_id == "<test@example.com>"
    assert record.intent_label == "send_info"


@patch("db.psycopg2.connect")
def test_database_get_email_by_message_id_not_found(mock_connect):
    """Test get_email_by_message_id returns None when not found."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    record = db.get_email_by_message_id("<nonexistent@example.com>")

    assert record is None


@patch("db.psycopg2.connect")
def test_database_email_exists(mock_connect):
    """Test checking if email exists."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {"exists": True}

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.email_exists("<test@example.com>")

    assert result is True


@patch("db.psycopg2.connect")
def test_database_email_not_exists(mock_connect):
    """Test email_exists returns False when not found."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {"exists": False}

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.email_exists("<nonexistent@example.com>")

    assert result is False


@patch("db.psycopg2.connect")
def test_database_get_emails_by_intent(mock_connect):
    """Test retrieving emails by intent."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        {
            "id": 1,
            "message_id": "<test1@example.com>",
            "s3_key": "emails/test1",
            "sender": "user1@example.com",
            "processed_at": datetime.now(),
            "intent_flags": [True, False, False, False, False],
            "intent_label": "send_info",
            "status": "processed",
        },
        {
            "id": 2,
            "message_id": "<test2@example.com>",
            "s3_key": "emails/test2",
            "sender": "user2@example.com",
            "processed_at": datetime.now(),
            "intent_flags": [True, False, False, False, False],
            "intent_label": "send_info",
            "status": "processed",
        },
    ]

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    records = db.get_emails_by_intent("send_info", limit=10)

    assert len(records) == 2
    assert all(r.intent_label == "send_info" for r in records)


@patch("db.psycopg2.connect")
def test_database_get_counts_by_intent(mock_connect):
    """Test getting email counts by intent."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        {"intent_label": "send_info", "count": 10},
        {"intent_label": "create_account", "count": 5},
        {"intent_label": "unknown", "count": 3},
    ]

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    counts = db.get_counts_by_intent()

    assert counts == {
        "send_info": 10,
        "create_account": 5,
        "unknown": 3,
    }


@patch("db.psycopg2.connect")
def test_database_get_counts_by_status(mock_connect):
    """Test getting email counts by status."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        {"status": "processed", "count": 15},
        {"status": "failed", "count": 2},
    ]

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    counts = db.get_counts_by_status()

    assert counts == {
        "processed": 15,
        "failed": 2,
    }


@patch("db.psycopg2.connect")
def test_database_update_email_status(mock_connect):
    """Test updating email status."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.rowcount = 1

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.update_email_status(
        email_id=1,
        status="escalated",
        handler_result={"escalated_to": "support@frflashy.com"},
    )

    assert result is True


@patch("db.psycopg2.connect")
def test_database_update_email_status_not_found(mock_connect):
    """Test update_email_status returns False when email not found."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.rowcount = 0

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.update_email_status(email_id=9999, status="failed")

    assert result is False


@patch("db.psycopg2.connect")
def test_database_test_connection_success(mock_connect):
    """Test database connection test succeeds."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.test_connection()

    assert result is True
    mock_cursor.execute.assert_called_once_with("SELECT 1;")


@patch("db.psycopg2.connect")
def test_database_test_connection_failure(mock_connect):
    """Test database connection test handles failure."""
    mock_connect.side_effect = Exception("Connection refused")

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    result = db.test_connection()

    assert result is False


@patch("db.psycopg2.connect")
def test_database_get_recent_emails(mock_connect):
    """Test getting recent emails."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_connect.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [
        {
            "id": 3,
            "message_id": "<recent@example.com>",
            "s3_key": "emails/recent",
            "sender": "recent@example.com",
            "processed_at": datetime.now(),
            "intent_flags": [False, True, False, False, False],
            "intent_label": "create_account",
            "status": "processed",
        }
    ]

    config = DatabaseConfig(url="postgresql://test")
    db = Database(config)

    records = db.get_recent_emails(limit=5)

    assert len(records) == 1
    assert records[0].message_id == "<recent@example.com>"
