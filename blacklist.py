"""Email blacklist handling for bounce notifications.

Detects bounce/delivery failure notifications and adds bounced
email addresses to the email_blacklist table.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("ses-daemon-bot")


def is_bounce_notification(sender: str, subject: str) -> bool:
    """Check if an email is a bounce/delivery failure notification.

    Args:
        sender: Sender email address
        subject: Email subject line

    Returns:
        True if this appears to be a bounce notification
    """
    sender_lower = (sender or "").lower()
    subject_lower = (subject or "").lower()

    bounce_indicators = [
        'delivery status notification',
        'undeliverable',
        'mail delivery failed',
        'delivery failure',
        'returned mail',
        'failure notice',
        'undelivered mail',
        'message not delivered',
        'delivery problem',
    ]

    # Check sender
    if 'mailer-daemon' in sender_lower or 'postmaster' in sender_lower:
        return True

    # Check subject
    for indicator in bounce_indicators:
        if indicator in subject_lower:
            return True

    return False


def extract_bounced_email_from_raw(raw_content: bytes) -> Optional[str]:
    """Extract the bounced email address from raw DSN message content.

    Parses the MIME structure to find delivery-status parts and headers.

    Args:
        raw_content: Raw email bytes

    Returns:
        The bounced email address, or None if not found
    """
    import email as email_parser

    try:
        msg = email_parser.message_from_bytes(raw_content)

        # Check X-Failed-Recipients header first
        failed_recipients = msg.get("X-Failed-Recipients")
        if failed_recipients:
            match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', failed_recipients)
            if match:
                return match.group(0).lower()

        # Walk through MIME parts looking for delivery-status
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()

                # Look for delivery-status parts
                if content_type == "message/delivery-status":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            status_text = payload.decode('utf-8', errors='replace')
                            # Look for Final-Recipient or Original-Recipient
                            match = re.search(
                                r'(?:Final-Recipient|Original-Recipient)[:\s]+(?:rfc822;)?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                                status_text,
                                re.IGNORECASE
                            )
                            if match:
                                addr = match.group(1).lower()
                                if not addr.endswith('@frflashy.com'):
                                    return addr
                    except Exception:
                        pass

                # Also check text/plain parts for DSN patterns
                elif content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            text = payload.decode('utf-8', errors='replace')

                            # Look for Amazon SES format: "deliver the mail to the following recipients:"
                            match = re.search(
                                r'(?:deliver|delivering).*(?:to the following recipients?|to)[:\s]*\n*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                                text,
                                re.IGNORECASE
                            )
                            if match:
                                addr = match.group(1).lower()
                                if not addr.endswith('@frflashy.com'):
                                    return addr

                            # Look for Final-Recipient pattern
                            match = re.search(
                                r'(?:Final-Recipient|Original-Recipient)[:\s]+(?:rfc822;)?\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
                                text,
                                re.IGNORECASE
                            )
                            if match:
                                addr = match.group(1).lower()
                                if not addr.endswith('@frflashy.com'):
                                    return addr
                    except Exception:
                        pass

    except Exception as e:
        logger.debug(f"Error parsing raw content for bounce: {e}")

    return None


def extract_bounced_email(email_body: str, raw_content: bytes = None) -> Optional[str]:
    """Extract the bounced email address from a bounce notification.

    Args:
        email_body: The email body text
        raw_content: Raw email bytes (optional, for DSN parsing)

    Returns:
        The bounced email address, or None if not found
    """
    # First try to extract from raw MIME content (more reliable for DSN)
    if raw_content:
        addr = extract_bounced_email_from_raw(raw_content)
        if addr:
            return addr

    if not email_body:
        return None

    # Patterns to find the failed recipient in text body
    patterns = [
        r'(?:failed|rejected|bounced|undeliverable)[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
        r'(?:recipient|address)[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
        r'<([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>.*(?:failed|rejected|bounced|error)',
        r'(?:could not be delivered to)[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
        r'(?:Final-Recipient|Original-Recipient)[:\s]+(?:rfc822;)?<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
    ]

    for pattern in patterns:
        match = re.search(pattern, email_body, re.IGNORECASE)
        if match:
            email_addr = match.group(1).lower()
            # Skip our own domain and system addresses
            if not email_addr.endswith('@frflashy.com') and 'mailer-daemon' not in email_addr:
                return email_addr

    # Fallback: find any email address that's not from our domain or system
    all_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', email_body)
    for addr in all_emails:
        addr_lower = addr.lower()
        if (not addr_lower.endswith('@frflashy.com') and
            'mailer-daemon' not in addr_lower and
            'postmaster' not in addr_lower and
            'amazonses.com' not in addr_lower):
            return addr_lower

    return None


def add_to_blacklist(db, email_addr: str, reason: str = "SES bounce notification",
                     source: str = "ses-daemon-bot") -> Optional[dict]:
    """Add an email address to the email_blacklist table.

    Args:
        db: Database instance
        email_addr: Email address to blacklist
        reason: Reason for blacklisting
        source: Source of the blacklist entry

    Returns:
        Dict with 'inserted' (bool) and 'access_cnt' (int), or None on error
    """
    try:
        with db.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO email_blacklist (email, reason, source)
                VALUES (%s, %s, %s)
                ON CONFLICT (email)
                DO UPDATE SET
                    access_cnt = email_blacklist.access_cnt + 1,
                    last_access_date = NOW()
                RETURNING (xmax = 0) AS inserted, access_cnt
            """, (email_addr, reason, source))

            result = cursor.fetchone()
            return {
                "inserted": result["inserted"],
                "access_cnt": result["access_cnt"]
            }
    except Exception as e:
        logger.error(f"Failed to add {email_addr} to blacklist: {e}")
        return None


def handle_bounce(email, db, dry_run: bool = False) -> Optional[dict]:
    """Handle a bounce notification by extracting and blacklisting the bounced address.

    Args:
        email: Email object from SESClient
        db: Database instance
        dry_run: If True, don't actually modify the database

    Returns:
        Dict with bounce handling result, or None if not a bounce
    """
    # Check if this is a bounce notification
    if not is_bounce_notification(email.sender, email.subject):
        return None

    logger.info(f"Detected bounce notification: {email.subject}")

    # Extract the bounced email address (pass raw_content for DSN parsing)
    bounced_addr = extract_bounced_email(email.body, email.raw_content)

    if not bounced_addr:
        logger.warning("Could not extract bounced email address from notification")
        return {
            "is_bounce": True,
            "extracted_email": None,
            "blacklisted": False,
            "error": "Could not extract email address"
        }

    logger.info(f"Extracted bounced email: {bounced_addr}")

    if dry_run:
        logger.info(f"[DRY-RUN] Would blacklist: {bounced_addr}")
        return {
            "is_bounce": True,
            "extracted_email": bounced_addr,
            "blacklisted": False,
            "dry_run": True
        }

    # Add to blacklist
    result = add_to_blacklist(db, bounced_addr)

    if result:
        if result["inserted"]:
            logger.info(f"Added to blacklist: {bounced_addr}")
        else:
            logger.info(f"Updated blacklist (access_cnt={result['access_cnt']}): {bounced_addr}")

        return {
            "is_bounce": True,
            "extracted_email": bounced_addr,
            "blacklisted": True,
            "inserted": result["inserted"],
            "access_cnt": result["access_cnt"]
        }
    else:
        return {
            "is_bounce": True,
            "extracted_email": bounced_addr,
            "blacklisted": False,
            "error": "Failed to add to blacklist"
        }
