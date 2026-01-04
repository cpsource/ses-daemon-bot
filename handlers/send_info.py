"""Handler for send_info intent."""

import logging

from .base import EmailSender, load_template

logger = logging.getLogger("ses-daemon-bot")


def handle_send_info(email, sender: EmailSender, dry_run: bool = False) -> dict:
    """Handle send_info intent by sending an auto-reply.

    Args:
        email: Email object from SESClient
        sender: EmailSender instance
        dry_run: If True, don't actually send

    Returns:
        Dict with handler result
    """
    # Load template (we only use from_addr and body, subject comes from original)
    from_addr, _, body = load_template("send_info")

    if not all([from_addr, body]):
        return {
            "action": "send_info",
            "status": "error",
            "error": "Failed to load template",
        }

    # Use original subject for reply
    reply_subject = email.subject or "Your inquiry"

    if dry_run:
        logger.info(f"[DRY-RUN] Would reply to {email.sender} re: {reply_subject}")
        return {
            "action": "send_info",
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
            "action": "send_info",
            "status": "sent",
            "to": email.sender,
            "subject": f"Re: {reply_subject}",
            "message_id": result["message_id"],
        }
    else:
        return {
            "action": "send_info",
            "status": "error",
            "error": result["error"],
        }
