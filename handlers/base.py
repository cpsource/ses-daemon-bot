"""Base handler utilities."""

import logging
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from config import AWSConfig

logger = logging.getLogger("ses-daemon-bot")

# Templates directory
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def load_template(intent: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Load template and content files for an intent.

    Args:
        intent: Intent name (e.g., 'send_info')

    Returns:
        Tuple of (from_addr, subject, body) or (None, None, None) if not found
    """
    template_path = TEMPLATES_DIR / f"{intent}.template"
    content_path = TEMPLATES_DIR / f"{intent}.txt"

    if not template_path.exists():
        logger.error(f"Template not found: {template_path}")
        return None, None, None

    if not content_path.exists():
        logger.error(f"Content file not found: {content_path}")
        return None, None, None

    try:
        template = template_path.read_text()
        content = content_path.read_text()

        # Parse template: headers before ---, body after
        if "---" not in template:
            logger.error(f"Invalid template format (missing ---): {template_path}")
            return None, None, None

        header_section, body_template = template.split("---", 1)

        # Parse headers
        from_addr = None
        subject = None
        for line in header_section.strip().split("\n"):
            if line.lower().startswith("from:"):
                from_addr = line.split(":", 1)[1].strip()
            elif line.lower().startswith("subject:"):
                subject = line.split(":", 1)[1].strip()

        # Insert content into body
        body = body_template.replace("{BODY_CONTENT}", content).strip()

        return from_addr, subject, body

    except Exception as e:
        logger.error(f"Error loading template {intent}: {e}")
        return None, None, None


class EmailSender:
    """Send emails via AWS SES."""

    def __init__(self, config: AWSConfig):
        """Initialize the email sender.

        Args:
            config: AWS configuration with credentials and region
        """
        self.config = config
        self.client = boto3.client(
            "ses",
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
        )

    def send_email(
        self,
        to_addr: str,
        from_addr: str,
        subject: str,
        body: str,
        reply_to: Optional[str] = None,
    ) -> dict:
        """Send an email via SES.

        Args:
            to_addr: Recipient email address
            from_addr: Sender email address
            subject: Email subject
            body: Email body (plain text)
            reply_to: Optional reply-to address

        Returns:
            Dict with 'success' bool and 'message_id' or 'error'
        """
        try:
            kwargs = {
                "Source": from_addr,
                "Destination": {"ToAddresses": [to_addr]},
                "Message": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            }

            if reply_to:
                kwargs["ReplyToAddresses"] = [reply_to]

            response = self.client.send_email(**kwargs)
            message_id = response.get("MessageId")
            logger.info(f"Sent email to {to_addr}: {message_id}")

            return {"success": True, "message_id": message_id}

        except ClientError as e:
            error_msg = e.response["Error"]["Message"]
            logger.error(f"Failed to send email to {to_addr}: {error_msg}")
            return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Failed to send email to {to_addr}: {e}")
            return {"success": False, "error": str(e)}

    def send_reply(
        self,
        to_addr: str,
        from_addr: str,
        subject: str,
        body: str,
        in_reply_to: str,
        references: Optional[str] = None,
    ) -> dict:
        """Send a reply email via SES using raw email format.

        Args:
            to_addr: Recipient email address
            from_addr: Sender email address
            subject: Email subject (will be prefixed with Re: if not already)
            body: Email body (plain text)
            in_reply_to: Message-ID of the email being replied to
            references: Optional References header (defaults to in_reply_to)

        Returns:
            Dict with 'success' bool and 'message_id' or 'error'
        """
        from email.mime.text import MIMEText

        try:
            # Ensure subject has Re: prefix
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            # Build MIME message
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to_addr
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to

            response = self.client.send_raw_email(
                Source=from_addr,
                Destinations=[to_addr],
                RawMessage={"Data": msg.as_string()},
            )
            message_id = response.get("MessageId")
            logger.info(f"Sent reply to {to_addr}: {message_id}")

            return {"success": True, "message_id": message_id}

        except ClientError as e:
            error_msg = e.response["Error"]["Message"]
            logger.error(f"Failed to send reply to {to_addr}: {error_msg}")
            return {"success": False, "error": error_msg}

        except Exception as e:
            logger.error(f"Failed to send reply to {to_addr}: {e}")
            return {"success": False, "error": str(e)}
