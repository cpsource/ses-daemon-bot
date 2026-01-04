"""Handler for unknown intent."""

import logging
from pathlib import Path

from .base import EmailSender

logger = logging.getLogger("ses-daemon-bot")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def handle_unknown(email, sender: EmailSender, dry_run: bool = False) -> dict:
    """Handle unknown intent by sending a fallback reply with info content.

    Args:
        email: Email object from SESClient
        sender: EmailSender instance
        dry_run: If True, don't actually send

    Returns:
        Dict with handler result
    """
    # Load unknown template
    template_path = TEMPLATES_DIR / "unknown.template"
    # Reuse send_info.txt content
    content_path = TEMPLATES_DIR / "send_info.txt"

    if not template_path.exists():
        logger.error(f"Template not found: {template_path}")
        return {
            "action": "unknown",
            "status": "error",
            "error": "Failed to load template",
        }

    if not content_path.exists():
        logger.error(f"Content file not found: {content_path}")
        return {
            "action": "unknown",
            "status": "error",
            "error": "Failed to load content",
        }

    try:
        template = template_path.read_text()
        content = content_path.read_text()

        # Parse template
        if "---" not in template:
            return {
                "action": "unknown",
                "status": "error",
                "error": "Invalid template format",
            }

        header_section, body_template = template.split("---", 1)

        # Parse From header
        from_addr = None
        for line in header_section.strip().split("\n"):
            if line.lower().startswith("from:"):
                from_addr = line.split(":", 1)[1].strip()

        if not from_addr:
            return {
                "action": "unknown",
                "status": "error",
                "error": "No From address in template",
            }

        # Insert content into body
        body = body_template.replace("{BODY_CONTENT}", content).strip()

    except Exception as e:
        logger.error(f"Error loading unknown template: {e}")
        return {
            "action": "unknown",
            "status": "error",
            "error": str(e),
        }

    # Use original subject for reply
    reply_subject = email.subject or "Your inquiry"

    if dry_run:
        logger.info(f"[DRY-RUN] Would reply (unknown) to {email.sender} re: {reply_subject}")
        return {
            "action": "unknown",
            "status": "dry_run",
            "to": email.sender,
            "subject": f"Re: {reply_subject}",
        }

    # Send reply
    result = sender.send_reply(
        to_addr=email.sender,
        from_addr=from_addr,
        subject=reply_subject,
        body=body,
        in_reply_to=email.message_id,
    )

    if result["success"]:
        return {
            "action": "unknown",
            "status": "sent",
            "to": email.sender,
            "subject": f"Re: {reply_subject}",
            "message_id": result["message_id"],
        }
    else:
        return {
            "action": "unknown",
            "status": "error",
            "error": result["error"],
        }
