"""Handler for unsubscribe intent."""

import logging
from pathlib import Path

from .base import EmailSender

logger = logging.getLogger("ses-daemon-bot")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
ADMIN_EMAIL = "page.cal@gmail.com"
FROM_EMAIL = "admin@frflashy.com"


def delete_user(db, email: str) -> bool:
    """Delete a user from the database.

    Args:
        db: Database instance
        email: User's email address

    Returns:
        True if user was deleted, False if not found or error
    """
    try:
        with db.get_cursor() as cursor:
            cursor.execute(
                "DELETE FROM users WHERE email = %s OR username = %s RETURNING id",
                (email, email)
            )
            result = cursor.fetchone()
            return result is not None
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        return False


def handle_unsubscribe(email, sender: EmailSender, db=None, dry_run: bool = False) -> dict:
    """Handle unsubscribe intent by removing user and notifying admin.

    Args:
        email: Email object from SESClient
        sender: EmailSender instance
        db: Database instance (optional, needed to delete user)
        dry_run: If True, don't actually send or delete

    Returns:
        Dict with handler result
    """
    template_path = TEMPLATES_DIR / "unsubscribe.template"

    if not template_path.exists():
        logger.error(f"Template not found: {template_path}")
        return {
            "action": "unsubscribe",
            "status": "error",
            "error": "Failed to load template",
        }

    try:
        template = template_path.read_text()

        if "---" not in template:
            return {
                "action": "unsubscribe",
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
                "action": "unsubscribe",
                "status": "error",
                "error": "No From address in template",
            }

    except Exception as e:
        logger.error(f"Error loading unsubscribe template: {e}")
        return {
            "action": "unsubscribe",
            "status": "error",
            "error": str(e),
        }

    user_email = email.sender
    reply_subject = email.subject or "Your inquiry"
    user_deleted = False

    # Try to delete user from database
    if db:
        if dry_run:
            logger.info(f"[DRY-RUN] Would delete user {user_email} from database")
        else:
            user_deleted = delete_user(db, user_email)
            if user_deleted:
                logger.info(f"Deleted user from database: {user_email}")
            else:
                logger.info(f"User not found in database: {user_email}")

    if dry_run:
        logger.info(f"[DRY-RUN] Would reply (unsubscribe) to {user_email} re: {reply_subject}")
        logger.info(f"[DRY-RUN] Would notify admin at {ADMIN_EMAIL}")
        return {
            "action": "unsubscribe",
            "status": "dry_run",
            "to": user_email,
            "subject": f"Re: {reply_subject}",
            "user_deleted": False,
        }

    # Send reply to user
    reply_result = sender.send_reply(
        to_addr=user_email,
        from_addr=from_addr,
        subject=reply_subject,
        body=body,
        in_reply_to=email.message_id,
    )

    # Notify admin about the unsubscribe
    admin_subject = f"User unsubscribed: {user_email}"
    admin_body = f"""An unsubscribe request was processed.

User: {user_email}
Original Subject: {email.subject or '(none)'}
User deleted from database: {'Yes' if user_deleted else 'No (not found)'}

Original message:
---
{email.body or '(no body)'}
"""

    admin_result = sender.send_email(
        to_addr=ADMIN_EMAIL,
        from_addr=FROM_EMAIL,
        subject=admin_subject,
        body=admin_body,
    )

    if not admin_result["success"]:
        logger.warning(f"Failed to notify admin about unsubscribe: {admin_result['error']}")

    if reply_result["success"]:
        return {
            "action": "unsubscribe",
            "status": "sent",
            "to": user_email,
            "subject": f"Re: {reply_subject}",
            "message_id": reply_result["message_id"],
            "user_deleted": user_deleted,
            "admin_notified": admin_result["success"],
        }
    else:
        return {
            "action": "unsubscribe",
            "status": "error",
            "error": reply_result["error"],
            "user_deleted": user_deleted,
        }
