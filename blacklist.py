"""Email blacklist handling for bounce and complaint notifications.

Detects bounce/delivery failure notifications and complaint feedback
notifications, then adds the offending email addresses to the email_blacklist table.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("ses-daemon-bot")

ADMIN_EMAIL = "page.cal@gmail.com"
FROM_EMAIL = "admin@frflashy.com"


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


def check_user_exists(db, email_addr: str) -> bool:
    """Check if an email address exists in the users table.

    Args:
        db: Database instance
        email_addr: Email address to check

    Returns:
        True if user exists, False otherwise
    """
    try:
        with db.get_cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE email = %s OR username = %s",
                (email_addr, email_addr)
            )
            result = cursor.fetchone()
            return result is not None
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        return False


def notify_admin_bounced_user(email_sender, bounced_addr: str, original_subject: str) -> bool:
    """Send notification to admin about a bounced user.

    Args:
        email_sender: EmailSender instance
        bounced_addr: The bounced email address
        original_subject: Subject of the bounce notification

    Returns:
        True if notification sent successfully
    """
    subject = f"Bounce alert: User in database - {bounced_addr}"
    body = f"""A delivery failure notification was received for an email address that exists in the users table.

Bounced email: {bounced_addr}
Original bounce subject: {original_subject}

This user may need to be contacted through alternative means or removed from the database.

Note: The user has NOT been automatically removed. Manual review is required.
"""

    result = email_sender.send_email(
        to_addr=ADMIN_EMAIL,
        from_addr=FROM_EMAIL,
        subject=subject,
        body=body,
    )

    if result["success"]:
        logger.info(f"Sent admin notification for bounced user: {bounced_addr}")
        return True
    else:
        logger.warning(f"Failed to notify admin about bounced user: {result['error']}")
        return False


def is_complaint_notification(sender: str, subject: str) -> bool:
    """Check if an email is a complaint/feedback notification from SES.

    Args:
        sender: Sender email address
        subject: Email subject line

    Returns:
        True if this appears to be an SES complaint notification
    """
    sender_lower = (sender or "").lower()

    # Amazon SES sends complaints from this address
    if 'complaints@email-abuse.amazonses.com' in sender_lower:
        return True
    if 'complaint@' in sender_lower and 'amazonses.com' in sender_lower:
        return True

    return False


def extract_complaint_email_from_raw(raw_content: bytes) -> Optional[str]:
    """Extract the complainant email address from raw SES complaint message.

    SES complaint notifications contain the original message and feedback headers.

    Args:
        raw_content: Raw email bytes

    Returns:
        The email address that filed the complaint, or None if not found
    """
    import email as email_parser

    try:
        msg = email_parser.message_from_bytes(raw_content)

        # Walk through MIME parts
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()

                # Look for message/feedback-report (ARF format)
                if content_type == "message/feedback-report":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            report_text = payload.decode('utf-8', errors='replace')
                            # Look for Original-Rcpt-To header
                            match = re.search(
                                r'Original-Rcpt-To[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
                                report_text,
                                re.IGNORECASE
                            )
                            if match:
                                return match.group(1).lower()
                    except Exception:
                        pass

                # Look in text/plain parts for the complainant email
                elif content_type == "text/plain":
                    try:
                        payload = part.get_payload(decode=True)
                        if payload:
                            text = payload.decode('utf-8', errors='replace')

                            # Look for To: header in forwarded complaint
                            match = re.search(
                                r'\bTo[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
                                text,
                                re.IGNORECASE
                            )
                            if match:
                                addr = match.group(1).lower()
                                # Skip our own domain
                                if not addr.endswith('@frflashy.com') and 'amazonses.com' not in addr:
                                    return addr
                    except Exception:
                        pass

                # Check message/rfc822 parts (the original email)
                elif content_type == "message/rfc822":
                    try:
                        payload = part.get_payload()
                        if payload and isinstance(payload, list):
                            original_msg = payload[0]
                        elif payload:
                            original_msg = payload

                        # Get To: header from original message
                        if hasattr(original_msg, 'get'):
                            to_header = original_msg.get('To')
                            if to_header:
                                match = re.search(
                                    r'<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
                                    to_header
                                )
                                if match:
                                    addr = match.group(1).lower()
                                    if not addr.endswith('@frflashy.com'):
                                        return addr
                    except Exception:
                        pass

    except Exception as e:
        logger.debug(f"Error parsing raw content for complaint: {e}")

    return None


def extract_complaint_email(email_body: str, raw_content: bytes = None) -> Optional[str]:
    """Extract the complainant email address from a complaint notification.

    Args:
        email_body: The email body text
        raw_content: Raw email bytes (optional, for MIME parsing)

    Returns:
        The email address that filed the complaint, or None if not found
    """
    # First try to extract from raw MIME content (more reliable)
    if raw_content:
        addr = extract_complaint_email_from_raw(raw_content)
        if addr:
            return addr

    if not email_body:
        return None

    # Patterns to find the complainant in text body
    patterns = [
        # To: header in forwarded content
        r'\bTo[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
        # Original recipient patterns
        r'Original-Rcpt-To[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
        r'(?:recipient|delivered to)[:\s]+<?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})>?',
    ]

    for pattern in patterns:
        match = re.search(pattern, email_body, re.IGNORECASE)
        if match:
            email_addr = match.group(1).lower()
            # Skip our own domain and system addresses
            if (not email_addr.endswith('@frflashy.com') and
                'amazonses.com' not in email_addr and
                'mailer-daemon' not in email_addr):
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


def handle_complaint(email, db, dry_run: bool = False, email_sender=None) -> Optional[dict]:
    """Handle a complaint notification by extracting and blacklisting the complainant.

    Args:
        email: Email object from SESClient
        db: Database instance
        dry_run: If True, don't actually modify the database
        email_sender: EmailSender instance (optional, for admin notifications)

    Returns:
        Dict with complaint handling result, or None if not a complaint
    """
    # Check if this is a complaint notification
    if not is_complaint_notification(email.sender, email.subject):
        return None

    logger.info(f"Detected complaint notification: {email.subject}")

    # Extract the complainant email address
    complainant_addr = extract_complaint_email(email.body, email.raw_content)

    if not complainant_addr:
        logger.warning("Could not extract complainant email address from notification")
        return {
            "is_complaint": True,
            "extracted_email": None,
            "blacklisted": False,
            "error": "Could not extract email address"
        }

    logger.info(f"Extracted complainant email: {complainant_addr}")

    if dry_run:
        logger.info(f"[DRY-RUN] Would blacklist complainant: {complainant_addr}")
        return {
            "is_complaint": True,
            "extracted_email": complainant_addr,
            "blacklisted": False,
            "dry_run": True
        }

    # Add to blacklist with complaint-specific reason
    result = add_to_blacklist(
        db,
        complainant_addr,
        reason="SES complaint notification - user marked email as spam",
        source="ses-daemon-bot"
    )

    if result:
        if result["inserted"]:
            logger.info(f"Added complainant to blacklist: {complainant_addr}")
        else:
            logger.info(f"Updated blacklist for complainant (access_cnt={result['access_cnt']}): {complainant_addr}")

        return {
            "is_complaint": True,
            "extracted_email": complainant_addr,
            "blacklisted": True,
            "inserted": result["inserted"],
            "access_cnt": result["access_cnt"]
        }
    else:
        return {
            "is_complaint": True,
            "extracted_email": complainant_addr,
            "blacklisted": False,
            "error": "Failed to add to blacklist"
        }


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


def handle_bounce(email, db, dry_run: bool = False, email_sender=None) -> Optional[dict]:
    """Handle a bounce notification by extracting and blacklisting the bounced address.

    Args:
        email: Email object from SESClient
        db: Database instance
        dry_run: If True, don't actually modify the database
        email_sender: EmailSender instance (optional, for admin notifications)

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

    # Check if bounced address exists in users table
    user_exists = check_user_exists(db, bounced_addr)
    admin_notified = False

    if user_exists:
        logger.warning(f"Bounced email exists in users table: {bounced_addr}")
        if email_sender and not dry_run:
            admin_notified = notify_admin_bounced_user(
                email_sender, bounced_addr, email.subject or "(no subject)"
            )
        elif dry_run:
            logger.info(f"[DRY-RUN] Would notify admin about bounced user: {bounced_addr}")

    if dry_run:
        logger.info(f"[DRY-RUN] Would blacklist: {bounced_addr}")
        return {
            "is_bounce": True,
            "extracted_email": bounced_addr,
            "blacklisted": False,
            "user_in_database": user_exists,
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
            "access_cnt": result["access_cnt"],
            "user_in_database": user_exists,
            "admin_notified": admin_notified
        }
    else:
        return {
            "is_bounce": True,
            "extracted_email": bounced_addr,
            "blacklisted": False,
            "user_in_database": user_exists,
            "admin_notified": admin_notified,
            "error": "Failed to add to blacklist"
        }
