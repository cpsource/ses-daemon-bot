"""Handler for create_account intent."""

import logging
import random
from pathlib import Path

from werkzeug.security import generate_password_hash

from .base import EmailSender

logger = logging.getLogger("ses-daemon-bot")

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def generate_password() -> str:
    """Generate a random 32-bit hex password.

    Returns:
        8-character hex string (e.g., 'a1b2c3d4')
    """
    random_int = random.getrandbits(32)
    return f"{random_int:08x}"


def hash_password(password: str) -> str:
    """Hash password using werkzeug (compatible with FrFlashCards).

    Args:
        password: Plain text password

    Returns:
        Werkzeug password hash
    """
    return generate_password_hash(password)


def load_template(template_name: str) -> tuple[str, str]:
    """Load a template file and parse it.

    Args:
        template_name: Name of the template file (without .template extension)

    Returns:
        Tuple of (from_addr, body_template)
    """
    template_path = TEMPLATES_DIR / f"{template_name}.template"

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    template = template_path.read_text()

    if "---" not in template:
        raise ValueError(f"Invalid template format: {template_path}")

    header_section, body = template.split("---", 1)

    from_addr = None
    for line in header_section.strip().split("\n"):
        if line.lower().startswith("from:"):
            from_addr = line.split(":", 1)[1].strip()

    if not from_addr:
        raise ValueError(f"No From address in template: {template_path}")

    return from_addr, body.strip()


def check_user_exists(db, email: str) -> bool:
    """Check if a user with this email already exists.

    Args:
        db: Database instance
        email: Email to check

    Returns:
        True if user exists, False otherwise
    """
    try:
        with db.get_cursor(commit=False) as cursor:
            cursor.execute(
                "SELECT EXISTS(SELECT 1 FROM users WHERE email = %s OR username = %s)",
                (email, email)
            )
            result = cursor.fetchone()
            return result["exists"] if result else False
    except Exception as e:
        logger.error(f"Error checking user existence: {e}")
        return False


def create_user(db, email: str, password_hash: str, auth_code: str) -> bool:
    """Create a new user in the database.

    Args:
        db: Database instance
        email: User's email (also used as username)
        password_hash: Hashed password
        auth_code: Plain text authorization code to store in users_auth

    Returns:
        True if created successfully, False otherwise
    """
    try:
        with db.get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash, tier, delf_level, users_auth, ai_tokens)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (email, email, password_hash, 0, 0, auth_code, 5000)
            )
            return True
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        return False


def handle_create_account(email, sender: EmailSender, db, dry_run: bool = False) -> dict:
    """Handle create_account intent by creating a new user account.

    Args:
        email: Email object from SESClient
        sender: EmailSender instance
        db: Database instance
        dry_run: If True, don't actually create account or send email

    Returns:
        Dict with handler result
    """
    user_email = email.sender
    reply_subject = email.subject or "Your inquiry"

    # Check if user already exists
    if check_user_exists(db, user_email):
        logger.info(f"User already exists: {user_email}")

        try:
            from_addr, body_template = load_template("create_account_exists")
            body = body_template.replace("{USER_EMAIL}", user_email)
        except Exception as e:
            logger.error(f"Failed to load template: {e}")
            return {
                "action": "create_account",
                "status": "error",
                "error": f"Failed to load template: {e}",
            }

        if dry_run:
            logger.info(f"[DRY-RUN] Would reply (account exists) to {user_email}")
            return {
                "action": "create_account",
                "status": "dry_run",
                "account_exists": True,
                "to": user_email,
            }

        result = sender.send_reply(
            to_addr=user_email,
            from_addr=from_addr,
            subject=reply_subject,
            body=body,
            in_reply_to=email.message_id,
        )

        if result["success"]:
            return {
                "action": "create_account",
                "status": "account_exists",
                "to": user_email,
                "message_id": result["message_id"],
            }
        else:
            return {
                "action": "create_account",
                "status": "error",
                "error": result["error"],
            }

    # Generate password (also used as authorization code)
    password = generate_password()
    password_hash = hash_password(password)
    auth_code = password  # Store plain password in users_auth for recovery

    if dry_run:
        logger.info(f"[DRY-RUN] Would create account for {user_email}")
        return {
            "action": "create_account",
            "status": "dry_run",
            "account_exists": False,
            "to": user_email,
            "username": user_email,
        }

    # Create the user (store auth_code in users_auth)
    if not create_user(db, user_email, password_hash, auth_code):
        return {
            "action": "create_account",
            "status": "error",
            "error": "Failed to create user in database",
        }

    logger.info(f"Created account for: {user_email}")

    # Load success template and send credentials
    try:
        from_addr, body_template = load_template("create_account_success")
        body = body_template.replace("{USER_EMAIL}", user_email).replace("{PASSWORD}", password).replace("{AUTH_CODE}", auth_code)
    except Exception as e:
        logger.error(f"Failed to load template: {e}")
        return {
            "action": "create_account",
            "status": "created_but_email_failed",
            "to": user_email,
            "username": user_email,
            "error": f"Failed to load template: {e}",
        }

    result = sender.send_reply(
        to_addr=user_email,
        from_addr=from_addr,
        subject=reply_subject,
        body=body,
        in_reply_to=email.message_id,
    )

    if result["success"]:
        return {
            "action": "create_account",
            "status": "created",
            "to": user_email,
            "username": user_email,
            "message_id": result["message_id"],
        }
    else:
        return {
            "action": "create_account",
            "status": "created_but_email_failed",
            "to": user_email,
            "username": user_email,
            "error": result["error"],
        }
