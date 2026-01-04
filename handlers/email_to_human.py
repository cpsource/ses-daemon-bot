"""Handler for email_to_human intent."""

import logging
from pathlib import Path

from .base import EmailSender

logger = logging.getLogger("ses-daemon-bot")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Admin email for forwarding human requests
ADMIN_EMAIL = "page.cal@gmail.com"
ADMIN_SUBJECT = "Frflashy user requests help"


def handle_email_to_human(email, sender: EmailSender, dry_run: bool = False) -> dict:
    """Handle email_to_human intent by acknowledging and queuing for human review.

    Args:
        email: Email object from SESClient
        sender: EmailSender instance
        dry_run: If True, don't actually send

    Returns:
        Dict with handler result
    """
    template_path = TEMPLATES_DIR / "email_to_human.template"

    if not template_path.exists():
        logger.error(f"Template not found: {template_path}")
        return {
            "action": "email_to_human",
            "status": "error",
            "error": "Failed to load template",
        }

    try:
        template = template_path.read_text()

        if "---" not in template:
            return {
                "action": "email_to_human",
                "status": "error",
                "error": "Invalid template format",
            }

        header_section, body = template.split("---", 1)
        body = body.strip()

        # Parse From header
        from_addr = None
        for line in header_section.strip().split("\n"):
            if line.lower().startswith("from:"):
                from_addr = line.split(":", 1)[1].strip()

        if not from_addr:
            return {
                "action": "email_to_human",
                "status": "error",
                "error": "No From address in template",
            }

    except Exception as e:
        logger.error(f"Error loading email_to_human template: {e}")
        return {
            "action": "email_to_human",
            "status": "error",
            "error": str(e),
        }

    # Use original subject for reply
    reply_subject = email.subject or "Your inquiry"

    if dry_run:
        logger.info(f"[DRY-RUN] Would reply (email_to_human) to {email.sender} re: {reply_subject}")
        logger.info(f"[DRY-RUN] Would forward to {ADMIN_EMAIL}: {ADMIN_SUBJECT}")
        return {
            "action": "email_to_human",
            "status": "dry_run",
            "to": email.sender,
            "subject": f"Re: {reply_subject}",
            "forwarded_to": ADMIN_EMAIL,
        }

    # Send reply to user
    result = sender.send_reply(
        to_addr=email.sender,
        from_addr=from_addr,
        subject=reply_subject,
        body=body,
        in_reply_to=email.message_id,
    )

    if not result["success"]:
        return {
            "action": "email_to_human",
            "status": "error",
            "error": result["error"],
        }

    reply_message_id = result["message_id"]

    # Forward original email to admin
    forward_body = f"""Original email from: {email.sender}
Original subject: {email.subject}
Received: {email.received_at}

--- Original Message ---

{email.body}
"""

    forward_result = sender.send_email(
        to_addr=ADMIN_EMAIL,
        from_addr=from_addr,
        subject=ADMIN_SUBJECT,
        body=forward_body,
    )

    if forward_result["success"]:
        logger.info(f"Forwarded email to {ADMIN_EMAIL}")
        return {
            "action": "email_to_human",
            "status": "sent",
            "to": email.sender,
            "subject": f"Re: {reply_subject}",
            "message_id": reply_message_id,
            "forwarded_to": ADMIN_EMAIL,
            "forward_message_id": forward_result["message_id"],
        }
    else:
        logger.warning(f"Failed to forward to admin: {forward_result['error']}")
        return {
            "action": "email_to_human",
            "status": "sent",
            "to": email.sender,
            "subject": f"Re: {reply_subject}",
            "message_id": reply_message_id,
            "forward_error": forward_result["error"],
        }
