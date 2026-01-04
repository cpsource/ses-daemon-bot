"""Integration tests for database operations.

These tests require a live connection to the Neon database.
Run with: pytest qa/test_db_integration.py -v
"""

import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config
from db import Database


@pytest.fixture
def db():
    """Create a database connection using real credentials."""
    config = load_config()
    return Database(config.database)


def test_database_connection(db):
    """Test that we can connect to the Neon database."""
    result = db.test_connection()
    assert result is True, "Failed to connect to Neon database"


def test_ses_emails_table_exists(db):
    """Test that ses_emails table exists in the database."""
    with db.get_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'ses_emails'
            );
        """)
        result = cursor.fetchone()
        assert result["exists"] is True, "ses_emails table does not exist"


def test_ses_emails_table_columns(db):
    """Test that ses_emails table has all required columns."""
    expected_columns = {
        "id": "integer",
        "message_id": "text",
        "s3_key": "text",
        "sender": "text",
        "sender_name": "text",
        "recipient": "text",
        "subject": "text",
        "body": "text",
        "received_at": "timestamp with time zone",
        "processed_at": "timestamp with time zone",
        "intent_flags": "jsonb",
        "intent_label": "text",
        "handler_result": "jsonb",
        "status": "text",
    }

    with db.get_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'ses_emails'
            ORDER BY ordinal_position;
        """)
        columns = {row["column_name"]: row["data_type"] for row in cursor.fetchall()}

    assert len(columns) == 14, f"Expected 14 columns, got {len(columns)}"

    for col_name, col_type in expected_columns.items():
        assert col_name in columns, f"Missing column: {col_name}"
        assert columns[col_name] == col_type, (
            f"Column {col_name}: expected {col_type}, got {columns[col_name]}"
        )


def test_ses_emails_not_null_constraints(db):
    """Test that required columns have NOT NULL constraints."""
    required_columns = ["id", "message_id", "s3_key", "sender", "intent_flags", "intent_label"]

    with db.get_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'ses_emails';
        """)
        columns = {row["column_name"]: row["is_nullable"] for row in cursor.fetchall()}

    for col_name in required_columns:
        assert columns.get(col_name) == "NO", f"Column {col_name} should be NOT NULL"


def test_ses_emails_indexes(db):
    """Test that all required indexes exist."""
    expected_indexes = [
        "ses_emails_pkey",
        "ses_emails_message_id_key",
        "idx_ses_emails_message_id",
        "idx_ses_emails_sender",
        "idx_ses_emails_intent_label",
        "idx_ses_emails_status",
        "idx_ses_emails_processed_at",
    ]

    with db.get_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'ses_emails';
        """)
        indexes = [row["indexname"] for row in cursor.fetchall()]

    for idx_name in expected_indexes:
        assert idx_name in indexes, f"Missing index: {idx_name}"


def test_ses_emails_message_id_unique(db):
    """Test that message_id has a unique constraint."""
    with db.get_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_name = 'ses_emails'
            AND constraint_type = 'UNIQUE';
        """)
        constraints = [row["constraint_name"] for row in cursor.fetchall()]

    assert "ses_emails_message_id_key" in constraints, "message_id unique constraint missing"


def test_ses_emails_defaults(db):
    """Test that default values are set correctly."""
    with db.get_cursor(commit=False) as cursor:
        cursor.execute("""
            SELECT column_name, column_default
            FROM information_schema.columns
            WHERE table_name = 'ses_emails'
            AND column_default IS NOT NULL;
        """)
        defaults = {row["column_name"]: row["column_default"] for row in cursor.fetchall()}

    assert "id" in defaults, "id should have a default (serial)"
    assert "nextval" in defaults["id"], "id should use a sequence"

    assert "processed_at" in defaults, "processed_at should have a default"
    assert "now()" in defaults["processed_at"], "processed_at should default to now()"

    assert "status" in defaults, "status should have a default"
    assert "processed" in defaults["status"], "status should default to 'processed'"
