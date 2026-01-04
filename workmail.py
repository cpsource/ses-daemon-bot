"""AWS WorkMail IMAP integration.

Handles marking processed emails as read in WorkMail.
"""

import imaplib
import logging
from typing import Optional

logger = logging.getLogger("ses-daemon-bot")

# AWS WorkMail IMAP settings
WORKMAIL_SERVER = "imap.mail.us-east-1.awsapps.com"
WORKMAIL_PORT = 993


class WorkMailClient:
    """Client for interacting with AWS WorkMail via IMAP."""

    def __init__(self, email: str, password: str, server: str = None):
        """Initialize the WorkMail client.

        Args:
            email: WorkMail email address (e.g., admin@frflashy.com)
            password: WorkMail password
            server: IMAP server (default: AWS WorkMail)
        """
        self.email = email
        self.password = password
        self.server = server or WORKMAIL_SERVER
        self._connection = None

    def connect(self) -> bool:
        """Connect to WorkMail IMAP server.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self._connection = imaplib.IMAP4_SSL(self.server, WORKMAIL_PORT)
            self._connection.login(self.email, self.password)
            logger.debug(f"Connected to WorkMail as {self.email}")
            return True
        except imaplib.IMAP4.error as e:
            logger.error(f"WorkMail IMAP login failed: {e}")
            self._connection = None
            return False
        except Exception as e:
            logger.error(f"WorkMail connection error: {e}")
            self._connection = None
            return False

    def disconnect(self):
        """Disconnect from WorkMail."""
        if self._connection:
            try:
                self._connection.close()
                self._connection.logout()
            except Exception:
                pass
            self._connection = None

    def mark_as_read_by_message_id(self, message_id: str, mailbox: str = "INBOX") -> bool:
        """Mark an email as read by its Message-ID header.

        Args:
            message_id: The Message-ID header value
            mailbox: Mailbox to search (default: INBOX)

        Returns:
            True if found and marked, False otherwise
        """
        if not self._connection:
            if not self.connect():
                return False

        try:
            # Select mailbox
            status, _ = self._connection.select(mailbox)
            if status != "OK":
                logger.error(f"Failed to select mailbox {mailbox}")
                return False

            # Search for the message by Message-ID
            # Need to escape the message_id for IMAP search
            search_id = message_id.strip("<>")
            status, messages = self._connection.search(None, f'HEADER Message-ID "<{search_id}>"')

            if status != "OK" or not messages[0]:
                # Try without angle brackets
                status, messages = self._connection.search(None, f'HEADER Message-ID "{search_id}"')

            if status != "OK" or not messages[0]:
                logger.debug(f"Message not found in WorkMail: {message_id}")
                return False

            # Get message IDs
            msg_ids = messages[0].split()

            if not msg_ids:
                logger.debug(f"No messages found for Message-ID: {message_id}")
                return False

            # Mark as read (add \Seen flag)
            for msg_id in msg_ids:
                self._connection.store(msg_id, '+FLAGS', '\\Seen')
                logger.debug(f"Marked as read in WorkMail: {message_id}")

            return True

        except Exception as e:
            logger.error(f"Error marking email as read: {e}")
            return False

    def delete_by_message_id(self, message_id: str, mailbox: str = "INBOX") -> bool:
        """Delete an email by its Message-ID header.

        Args:
            message_id: The Message-ID header value
            mailbox: Mailbox to search (default: INBOX)

        Returns:
            True if found and deleted, False otherwise
        """
        if not self._connection:
            if not self.connect():
                return False

        try:
            # Select mailbox
            status, _ = self._connection.select(mailbox)
            if status != "OK":
                logger.error(f"Failed to select mailbox {mailbox}")
                return False

            # Search for the message by Message-ID
            search_id = message_id.strip("<>")
            status, messages = self._connection.search(None, f'HEADER Message-ID "<{search_id}>"')

            if status != "OK" or not messages[0]:
                status, messages = self._connection.search(None, f'HEADER Message-ID "{search_id}"')

            if status != "OK" or not messages[0]:
                logger.debug(f"Message not found in WorkMail: {message_id}")
                return False

            # Get message IDs
            msg_ids = messages[0].split()

            if not msg_ids:
                return False

            # Mark for deletion and expunge
            for msg_id in msg_ids:
                self._connection.store(msg_id, '+FLAGS', '\\Deleted')

            self._connection.expunge()
            logger.debug(f"Deleted from WorkMail: {message_id}")

            return True

        except Exception as e:
            logger.error(f"Error deleting email: {e}")
            return False

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
