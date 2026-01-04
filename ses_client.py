"""AWS SES/S3 integration.

Handles fetching and parsing emails from the S3 bucket where SES stores them.
"""

import email
import logging
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Iterator, Optional

import boto3
from botocore.exceptions import ClientError

from config import AWSConfig

logger = logging.getLogger("ses-daemon-bot")

# S3 prefixes
INCOMING_PREFIX = "emails/"
PROCESSED_PREFIX = "processed/"
FAILED_PREFIX = "failed/"


@dataclass
class Email:
    """Represents a parsed email message."""

    message_id: str
    s3_key: str
    sender: str
    sender_name: str
    recipient: str
    subject: str
    body_text: str
    body_html: str
    received_at: datetime
    raw_content: bytes = field(repr=False)

    @property
    def body(self) -> str:
        """Return text body, falling back to stripped HTML."""
        if self.body_text:
            return self.body_text
        if self.body_html:
            # Basic HTML stripping (for classification purposes)
            import re

            text = re.sub(r"<[^>]+>", " ", self.body_html)
            text = re.sub(r"\s+", " ", text)
            return text.strip()
        return ""


class SESClient:
    """Client for fetching emails from S3 bucket."""

    def __init__(self, config: AWSConfig):
        """Initialize the SES client.

        Args:
            config: AWS configuration with credentials and bucket name.
        """
        self.bucket = config.ses_bucket
        self.region = config.region

        # Create S3 client
        self.s3 = boto3.client(
            "s3",
            region_name=config.region,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
        )

    def list_pending_emails(self) -> Iterator[str]:
        """List all pending email keys in the incoming prefix.

        Yields:
            S3 object keys for unprocessed emails.
        """
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=INCOMING_PREFIX)

            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    # Skip the prefix itself
                    if key != INCOMING_PREFIX:
                        yield key
        except ClientError as e:
            logger.error(f"Error listing emails: {e}")
            raise

    def count_pending_emails(self) -> int:
        """Count pending emails without fetching them all.

        Returns:
            Number of pending emails.
        """
        count = 0
        try:
            paginator = self.s3.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=INCOMING_PREFIX)

            for page in pages:
                for obj in page.get("Contents", []):
                    if obj["Key"] != INCOMING_PREFIX:
                        count += 1
        except ClientError as e:
            logger.error(f"Error counting emails: {e}")
            raise
        return count

    def fetch_email(self, s3_key: str) -> Optional[Email]:
        """Fetch and parse an email from S3.

        Args:
            s3_key: The S3 object key.

        Returns:
            Parsed Email object, or None if parsing fails.
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
            raw_content = response["Body"].read()

            return self._parse_email(s3_key, raw_content)
        except ClientError as e:
            logger.error(f"Error fetching email {s3_key}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Error parsing email {s3_key}: {e}")
            return None

    def _parse_email(self, s3_key: str, raw_content: bytes) -> Email:
        """Parse raw email content into an Email object.

        Args:
            s3_key: The S3 object key.
            raw_content: Raw email bytes.

        Returns:
            Parsed Email object.
        """
        msg = email.message_from_bytes(raw_content)

        # Extract message ID
        message_id = msg.get("Message-ID", s3_key)

        # Extract sender
        from_header = msg.get("From", "")
        sender_name, sender_addr = parseaddr(from_header)
        sender_name = self._decode_header(sender_name) if sender_name else ""

        # Extract recipient
        to_header = msg.get("To", "")
        _, recipient = parseaddr(to_header)

        # Extract subject
        subject = self._decode_header(msg.get("Subject", ""))

        # Extract date
        date_header = msg.get("Date")
        try:
            received_at = parsedate_to_datetime(date_header) if date_header else datetime.now()
        except Exception:
            received_at = datetime.now()

        # Extract body
        body_text = ""
        body_html = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")

                        if content_type == "text/plain":
                            body_text = text
                        elif content_type == "text/html":
                            body_html = text
                except Exception as e:
                    logger.debug(f"Error decoding part: {e}")
        else:
            # Single part message
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")

                    if msg.get_content_type() == "text/html":
                        body_html = text
                    else:
                        body_text = text
            except Exception as e:
                logger.debug(f"Error decoding body: {e}")

        return Email(
            message_id=message_id,
            s3_key=s3_key,
            sender=sender_addr,
            sender_name=sender_name,
            recipient=recipient,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            received_at=received_at,
            raw_content=raw_content,
        )

    def _decode_header(self, header_value: str) -> str:
        """Decode an email header value.

        Args:
            header_value: Raw header value.

        Returns:
            Decoded string.
        """
        if not header_value:
            return ""

        decoded_parts = []
        for part, encoding in decode_header(header_value):
            if isinstance(part, bytes):
                decoded_parts.append(part.decode(encoding or "utf-8", errors="replace"))
            else:
                decoded_parts.append(part)
        return "".join(decoded_parts)

    def mark_processed(self, s3_key: str) -> bool:
        """Move an email to the processed prefix.

        Args:
            s3_key: The S3 object key.

        Returns:
            True if successful, False otherwise.
        """
        return self._move_email(s3_key, PROCESSED_PREFIX)

    def mark_failed(self, s3_key: str) -> bool:
        """Move an email to the failed prefix.

        Args:
            s3_key: The S3 object key.

        Returns:
            True if successful, False otherwise.
        """
        return self._move_email(s3_key, FAILED_PREFIX)

    def _move_email(self, s3_key: str, dest_prefix: str) -> bool:
        """Move an email to a different prefix.

        Args:
            s3_key: The source S3 object key.
            dest_prefix: The destination prefix.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Extract filename from key
            filename = s3_key.split("/")[-1]
            dest_key = f"{dest_prefix}{filename}"

            # Copy to new location
            self.s3.copy_object(
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": s3_key},
                Key=dest_key,
            )

            # Delete original
            self.s3.delete_object(Bucket=self.bucket, Key=s3_key)

            logger.debug(f"Moved {s3_key} to {dest_key}")
            return True
        except ClientError as e:
            logger.error(f"Error moving email {s3_key}: {e}")
            return False

    def delete_email(self, s3_key: str) -> bool:
        """Delete an email from S3.

        Args:
            s3_key: The S3 object key.

        Returns:
            True if successful, False otherwise.
        """
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=s3_key)
            logger.debug(f"Deleted {s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting email {s3_key}: {e}")
            return False

    def get_email_count_by_prefix(self) -> dict:
        """Get email counts for each prefix.

        Returns:
            Dict with counts: {"incoming": N, "processed": N, "failed": N}
        """
        counts = {"incoming": 0, "processed": 0, "failed": 0}

        for prefix, key in [
            (INCOMING_PREFIX, "incoming"),
            (PROCESSED_PREFIX, "processed"),
            (FAILED_PREFIX, "failed"),
        ]:
            try:
                paginator = self.s3.get_paginator("list_objects_v2")
                pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)

                for page in pages:
                    for obj in page.get("Contents", []):
                        if obj["Key"] != prefix:
                            counts[key] += 1
            except ClientError:
                pass

        return counts
