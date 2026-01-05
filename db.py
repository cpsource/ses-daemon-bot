"""Database operations.

Handles PostgreSQL database connections and operations for storing
and retrieving processed emails.
"""

import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from config import DatabaseConfig

logger = logging.getLogger("ses-daemon-bot")

# SQL statements
CREATE_EMAILS_TABLE = """
CREATE TABLE IF NOT EXISTS ses_emails (
    id SERIAL PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    s3_key TEXT NOT NULL,
    sender TEXT NOT NULL,
    sender_name TEXT,
    recipient TEXT,
    subject TEXT,
    body TEXT,
    received_at TIMESTAMP WITH TIME ZONE,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    intent_flags JSONB NOT NULL,
    intent_label TEXT NOT NULL,
    handler_result JSONB,
    status TEXT DEFAULT 'processed'
);

CREATE INDEX IF NOT EXISTS idx_ses_emails_message_id ON ses_emails(message_id);
CREATE INDEX IF NOT EXISTS idx_ses_emails_sender ON ses_emails(sender);
CREATE INDEX IF NOT EXISTS idx_ses_emails_intent_label ON ses_emails(intent_label);
CREATE INDEX IF NOT EXISTS idx_ses_emails_status ON ses_emails(status);
CREATE INDEX IF NOT EXISTS idx_ses_emails_processed_at ON ses_emails(processed_at);
"""

INSERT_EMAIL = """
INSERT INTO ses_emails (
    message_id, s3_key, sender, sender_name, recipient, subject, body,
    received_at, intent_flags, intent_label, handler_result, status
) VALUES (
    %(message_id)s, %(s3_key)s, %(sender)s, %(sender_name)s, %(recipient)s,
    %(subject)s, %(body)s, %(received_at)s, %(intent_flags)s, %(intent_label)s,
    %(handler_result)s, %(status)s
)
ON CONFLICT (message_id) DO UPDATE SET
    intent_flags = EXCLUDED.intent_flags,
    intent_label = EXCLUDED.intent_label,
    handler_result = EXCLUDED.handler_result,
    status = EXCLUDED.status,
    processed_at = NOW()
RETURNING id;
"""

SELECT_EMAIL_BY_MESSAGE_ID = """
SELECT * FROM ses_emails WHERE message_id = %s;
"""

SELECT_EMAIL_BY_ID = """
SELECT * FROM ses_emails WHERE id = %s;
"""

SELECT_EMAILS_BY_INTENT = """
SELECT * FROM ses_emails WHERE intent_label = %s ORDER BY processed_at DESC LIMIT %s;
"""

SELECT_EMAILS_BY_STATUS = """
SELECT * FROM ses_emails WHERE status = %s ORDER BY processed_at DESC LIMIT %s;
"""

SELECT_RECENT_EMAILS = """
SELECT * FROM ses_emails ORDER BY processed_at DESC LIMIT %s;
"""

UPDATE_EMAIL_STATUS = """
UPDATE ses_emails SET status = %s, handler_result = %s WHERE id = %s;
"""

COUNT_BY_INTENT = """
SELECT intent_label, COUNT(*) as count FROM ses_emails GROUP BY intent_label;
"""

COUNT_BY_STATUS = """
SELECT status, COUNT(*) as count FROM ses_emails GROUP BY status;
"""

EMAIL_EXISTS = """
SELECT EXISTS(SELECT 1 FROM ses_emails WHERE message_id = %s);
"""


@dataclass
class EmailRecord:
    """Represents an email record from the database."""

    id: int
    message_id: str
    s3_key: str
    sender: str
    sender_name: Optional[str]
    recipient: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    received_at: Optional[datetime]
    processed_at: datetime
    intent_flags: list[bool]
    intent_label: str
    handler_result: Optional[dict]
    status: str

    @classmethod
    def from_row(cls, row: dict) -> "EmailRecord":
        """Create EmailRecord from database row."""
        return cls(
            id=row["id"],
            message_id=row["message_id"],
            s3_key=row["s3_key"],
            sender=row["sender"],
            sender_name=row.get("sender_name"),
            recipient=row.get("recipient"),
            subject=row.get("subject"),
            body=row.get("body"),
            received_at=row.get("received_at"),
            processed_at=row["processed_at"],
            intent_flags=row["intent_flags"],
            intent_label=row["intent_label"],
            handler_result=row.get("handler_result"),
            status=row["status"],
        )


class Database:
    """PostgreSQL database client."""

    def __init__(self, config: DatabaseConfig):
        """Initialize the database client.

        Args:
            config: Database configuration with connection URL.
        """
        self.config = config
        self.connection_url = config.url
        self._connection = None

    @contextmanager
    def get_connection(self):
        """Get a database connection (context manager).

        Yields:
            psycopg2 connection object.
        """
        conn = None
        try:
            conn = psycopg2.connect(self.connection_url)
            yield conn
        finally:
            if conn:
                conn.close()

    @contextmanager
    def get_cursor(self, commit: bool = True):
        """Get a database cursor (context manager).

        Args:
            commit: Whether to commit after the block.

        Yields:
            psycopg2 cursor with RealDictCursor.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            try:
                yield cursor
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()

    def initialize(self) -> bool:
        """Initialize the database schema.

        Creates tables and indexes if they don't exist.

        Returns:
            True if successful, False otherwise.
        """
        try:
            with self.get_cursor() as cursor:
                cursor.execute(CREATE_EMAILS_TABLE)
            logger.info("Database schema initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            return False

    def save_email(
        self,
        message_id: str,
        s3_key: str,
        sender: str,
        intent_flags: list[bool],
        intent_label: str,
        sender_name: Optional[str] = None,
        recipient: Optional[str] = None,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        received_at: Optional[datetime] = None,
        handler_result: Optional[dict] = None,
        status: str = "processed",
    ) -> Optional[int]:
        """Save a processed email to the database.

        Args:
            message_id: Unique message identifier.
            s3_key: S3 object key.
            sender: Sender email address.
            intent_flags: Classification result as list of bools.
            intent_label: Intent label string.
            sender_name: Optional sender display name.
            recipient: Optional recipient address.
            subject: Optional email subject.
            body: Optional email body text.
            received_at: Optional original received timestamp.
            handler_result: Optional handler execution result.
            status: Processing status (default: 'processed').

        Returns:
            The inserted/updated record ID, or None on failure.
        """
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    INSERT_EMAIL,
                    {
                        "message_id": message_id,
                        "s3_key": s3_key,
                        "sender": sender,
                        "sender_name": sender_name,
                        "recipient": recipient,
                        "subject": subject,
                        "body": body,
                        "received_at": received_at,
                        "intent_flags": json.dumps(intent_flags),
                        "intent_label": intent_label,
                        "handler_result": json.dumps(handler_result) if handler_result else None,
                        "status": status,
                    },
                )
                result = cursor.fetchone()
                return result["id"] if result else None
        except Exception as e:
            logger.error(f"Failed to save email {message_id}: {e}")
            return None

    def get_email_by_message_id(self, message_id: str) -> Optional[EmailRecord]:
        """Get an email by its message ID.

        Args:
            message_id: The message ID to look up.

        Returns:
            EmailRecord if found, None otherwise.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(SELECT_EMAIL_BY_MESSAGE_ID, (message_id,))
                row = cursor.fetchone()
                return EmailRecord.from_row(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get email {message_id}: {e}")
            return None

    def get_email_by_id(self, email_id: int) -> Optional[EmailRecord]:
        """Get an email by its database ID.

        Args:
            email_id: The database ID.

        Returns:
            EmailRecord if found, None otherwise.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(SELECT_EMAIL_BY_ID, (email_id,))
                row = cursor.fetchone()
                return EmailRecord.from_row(row) if row else None
        except Exception as e:
            logger.error(f"Failed to get email id={email_id}: {e}")
            return None

    def email_exists(self, message_id: str) -> bool:
        """Check if an email has already been processed.

        Args:
            message_id: The message ID to check.

        Returns:
            True if email exists in database.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(EMAIL_EXISTS, (message_id,))
                result = cursor.fetchone()
                return result["exists"] if result else False
        except Exception as e:
            logger.error(f"Failed to check email existence: {e}")
            return False

    def get_emails_by_intent(
        self, intent_label: str, limit: int = 100
    ) -> list[EmailRecord]:
        """Get emails by intent label.

        Args:
            intent_label: The intent to filter by.
            limit: Maximum number of records to return.

        Returns:
            List of EmailRecords.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(SELECT_EMAILS_BY_INTENT, (intent_label, limit))
                return [EmailRecord.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get emails by intent {intent_label}: {e}")
            return []

    def get_emails_by_status(
        self, status: str, limit: int = 100
    ) -> list[EmailRecord]:
        """Get emails by status.

        Args:
            status: The status to filter by.
            limit: Maximum number of records to return.

        Returns:
            List of EmailRecords.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(SELECT_EMAILS_BY_STATUS, (status, limit))
                return [EmailRecord.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get emails by status {status}: {e}")
            return []

    def get_recent_emails(self, limit: int = 100) -> list[EmailRecord]:
        """Get most recently processed emails.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of EmailRecords.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(SELECT_RECENT_EMAILS, (limit,))
                return [EmailRecord.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get recent emails: {e}")
            return []

    def update_email_status(
        self, email_id: int, status: str, handler_result: Optional[dict] = None
    ) -> bool:
        """Update the status of a processed email.

        Args:
            email_id: The database ID of the email.
            status: New status value.
            handler_result: Optional handler result data.

        Returns:
            True if successful, False otherwise.
        """
        try:
            with self.get_cursor() as cursor:
                cursor.execute(
                    UPDATE_EMAIL_STATUS,
                    (
                        status,
                        json.dumps(handler_result) if handler_result else None,
                        email_id,
                    ),
                )
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update email status: {e}")
            return False

    def get_counts_by_intent(self) -> dict[str, int]:
        """Get email counts grouped by intent.

        Returns:
            Dict mapping intent labels to counts.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(COUNT_BY_INTENT)
                return {row["intent_label"]: row["count"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get intent counts: {e}")
            return {}

    def get_counts_by_status(self) -> dict[str, int]:
        """Get email counts grouped by status.

        Returns:
            Dict mapping status values to counts.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute(COUNT_BY_STATUS)
                return {row["status"]: row["count"] for row in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Failed to get status counts: {e}")
            return {}

    def test_connection(self) -> bool:
        """Test database connectivity.

        Returns:
            True if connection successful, False otherwise.
        """
        try:
            with self.get_cursor(commit=False) as cursor:
                cursor.execute("SELECT 1;")
                return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
