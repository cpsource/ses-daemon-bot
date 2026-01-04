"""Handler for unknown intent."""

import logging
from pathlib import Path

from .base import EmailSender

logger = logging.getLogger("ses-daemon-bot")

# Admin email for forwarding unknown messages
ADMIN_EMAIL = "page.cal@gmail.com"
FROM_EMAIL = "admin@frflashy.com"


def handle_unknown(email, sender: EmailSender, dry_run: bool = False) -> dict:
    """Handle unknown intent by forwarding to admin for review.

    Args:
        email: Email object from SESClient
        sender: EmailSender instance
        dry_run: If True, don't actually send

    Returns:
        Dict with handler result
    """
    subject = f"Unknown message received by {FROM_EMAIL}"

    forward_body = f"""An unknown message has been received by {FROM_EMAIL}.

From: {email.sender}
Subject: {email.subject}
Received: {email.received_at}

--- Original Message ---

{email.body}
"""

    if dry_run:
        logger.info(f"[DRY-RUN] Would forward unknown email to {ADMIN_EMAIL}")
        return {
            "action": "unknown",
            "status": "dry_run",
            "forwarded_to": ADMIN_EMAIL,
        }

    # Forward to admin
    result = sender.send_email(
        to_addr=ADMIN_EMAIL,
        from_addr=FROM_EMAIL,
        subject=subject,
        body=forward_body,
    )

    if result["success"]:
        logger.info(f"Forwarded unknown email to {ADMIN_EMAIL}")
        return {
            "action": "unknown",
            "status": "forwarded",
            "forwarded_to": ADMIN_EMAIL,
            "message_id": result["message_id"],
        }
    else:
        return {
            "action": "unknown",
            "status": "error",
            "error": result["error"],
        }
