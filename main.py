#!/usr/bin/env python3
"""SES Daemon Bot - Entry point."""

import argparse
import atexit
import logging
import os
import signal
import sys
import time
from pathlib import Path

from config import load_config
from ses_client import SESClient
from classifier import Classifier
from db import Database
from blacklist import handle_bounce
from workmail import WorkMailClient
from handlers import EmailSender, handle_send_info, handle_unknown, handle_speak_to_human, handle_email_to_human, handle_create_account

__version__ = "0.1.0"

logger = logging.getLogger("ses-daemon-bot")


def setup_logging(verbose=False, log_file=None):
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    handlers = []

    if log_file:
        handlers.append(logging.FileHandler(log_file))
    else:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def write_pid_file(pid_file):
    """Write current PID to file."""
    pid = os.getpid()
    with open(pid_file, "w") as f:
        f.write(str(pid))
    logger.info(f"PID {pid} written to {pid_file}")

    # Register cleanup on exit
    def remove_pid_file():
        try:
            os.remove(pid_file)
            logger.info(f"Removed PID file {pid_file}")
        except OSError:
            pass

    atexit.register(remove_pid_file)


def daemonize():
    """Detach process and run as a daemon."""
    # First fork
    pid = os.fork()
    if pid > 0:
        # Parent exits
        sys.exit(0)

    # Decouple from parent environment
    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Second fork
    pid = os.fork()
    if pid > 0:
        # First child exits
        sys.exit(0)

    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()
    with open("/dev/null", "rb", 0) as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open("/dev/null", "ab", 0) as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
    with open("/dev/null", "ab", 0) as f:
        os.dup2(f.fileno(), sys.stderr.fileno())


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="ses-daemon-bot",
        description="AWS SES mail processor for FrFlashy.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                      Run in foreground
  %(prog)s --daemon             Run as background daemon
  %(prog)s --dry-run            Test mode, no actual processing
  %(prog)s --once               Process one batch and exit
  %(prog)s -v --log-file bot.log  Verbose logging to file
        """,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (debug) logging",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        default="/home/ubuntu/.env",
        help="Path to .env configuration file (default: /home/ubuntu/.env)",
    )
    parser.add_argument(
        "--log-file",
        metavar="FILE",
        help="Path to log file (default: stdout)",
    )
    parser.add_argument(
        "--pid-file",
        metavar="FILE",
        help="Path to PID file for daemon management",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run in test mode without processing emails or sending responses",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Detach from terminal and run as a background daemon",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch of emails and exit",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        metavar="SECS",
        help="Polling interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--test-creds",
        action="store_true",
        help="Test that all required credentials are configured, then exit",
    )
    parser.add_argument(
        "--test-ses",
        action="store_true",
        help="Read and display emails from S3 bucket (non-destructive), then exit",
    )
    return parser.parse_args()


def check_credentials(config):
    """Check that all required credentials are configured.

    Returns:
        Tuple of (errors, warnings, success) lists of str
    """
    errors = []
    warnings = []
    success = []

    # AWS credentials
    if config.aws.access_key_id:
        success.append("AWS_ACCESS_KEY: configured")
    else:
        errors.append("AWS_ACCESS_KEY: MISSING")

    if config.aws.secret_access_key:
        success.append("AWS_SECRET_ACCESS_KEY: configured")
    else:
        errors.append("AWS_SECRET_ACCESS_KEY: MISSING")

    if config.aws.region:
        success.append(f"AWS_REGION: {config.aws.region}")
    else:
        warnings.append("AWS_REGION: not set (will use default)")

    if config.aws.ses_bucket:
        success.append(f"SES_BUCKET: {config.aws.ses_bucket}")
    else:
        errors.append("SES_BUCKET: MISSING")

    # Database
    if config.database.url:
        success.append("NEON_DATABASE_URL: configured")
    elif config.database.host and config.database.user:
        success.append("DB_HOST/DB_USER: configured")
    else:
        errors.append("NEON_DATABASE_URL or DB_HOST/DB_USER: MISSING")

    # LLM / OpenAI
    if config.llm.api_key:
        success.append("OPENAI_API_KEY: configured")
    else:
        errors.append("OPENAI_API_KEY: MISSING")

    if config.llm.model:
        success.append(f"LLM_MODEL: {config.llm.model}")

    return errors, warnings, success


def test_ses_connection(config):
    """Test SES/S3 connection by reading and displaying emails.

    Non-destructive: only reads emails, does not move or delete them.
    """
    from ses_client import SESClient

    print(f"Connecting to S3 bucket: {config.aws.ses_bucket}")
    print(f"Region: {config.aws.region}")
    print("=" * 60)

    try:
        client = SESClient(config.aws)

        # Get counts
        counts = client.get_email_count_by_prefix()
        print(f"Email counts:")
        print(f"  Incoming:  {counts['incoming']}")
        print(f"  Processed: {counts['processed']}")
        print(f"  Failed:    {counts['failed']}")
        print("=" * 60)

        # List and display pending emails
        pending_keys = list(client.list_pending_emails())

        if not pending_keys:
            print("No pending emails in inbox.")
            return

        print(f"\nPending emails ({len(pending_keys)}):\n")

        for i, s3_key in enumerate(pending_keys, 1):
            print(f"--- Email {i}/{len(pending_keys)} ---")
            print(f"S3 Key: {s3_key}")

            email = client.fetch_email(s3_key)
            if email:
                print(f"Message-ID: {email.message_id}")
                print(f"From: {email.sender_name} <{email.sender}>" if email.sender_name else f"From: {email.sender}")
                print(f"To: {email.recipient}")
                print(f"Subject: {email.subject}")
                print(f"Date: {email.received_at}")
                print(f"Body ({len(email.body)} chars):")
                # Show first 500 chars of body
                body_preview = email.body[:500]
                if len(email.body) > 500:
                    body_preview += "..."
                print("-" * 40)
                print(body_preview)
                print("-" * 40)
            else:
                print("  [Failed to parse email]")

            print()

    except Exception as e:
        print(f"ERROR: {e}")
        raise


def process_single_email(email, ses_client, classifier, db, email_sender=None, workmail_client=None, dry_run=False):
    """Process a single email through classification and handling.

    Args:
        email: Email object from SESClient
        ses_client: SESClient instance
        classifier: Classifier instance
        db: Database instance
        email_sender: EmailSender instance (optional)
        workmail_client: WorkMailClient instance (optional)
        dry_run: If True, don't modify S3 or send responses

    Returns:
        True if processed successfully, False otherwise
    """
    try:
        # Check if already processed (deduplication)
        if db.email_exists(email.message_id):
            logger.debug(f"Email {email.message_id} already processed, skipping")
            if not dry_run:
                ses_client.mark_processed(email.s3_key)
            return True

        # Step 2.5: Check for bounce notifications and blacklist bounced addresses
        bounce_result = handle_bounce(email, db, dry_run)
        if bounce_result:
            # This is a bounce notification - store it with special handling
            if not dry_run:
                db.save_email(
                    message_id=email.message_id,
                    s3_key=email.s3_key,
                    sender=email.sender,
                    sender_name=email.sender_name,
                    recipient=email.recipient,
                    subject=email.subject,
                    body=email.body,
                    received_at=email.received_at,
                    intent_flags=[False, False, False, False, False, False, False],  # No intent classification
                    intent_label="bounce_notification",
                    handler_result=bounce_result,
                    status="processed",
                )
                ses_client.mark_processed(email.s3_key)

                # Mark as read in WorkMail
                if workmail_client and email.message_id:
                    if workmail_client.mark_as_read_by_message_id(email.message_id):
                        logger.debug(f"Marked bounce as read in WorkMail: {email.message_id}")
                    else:
                        logger.warning(f"Failed to mark bounce as read in WorkMail: {email.message_id}")

            return True

        # Classify intent
        logger.debug(f"Classifying email: {email.subject}")
        result = classifier.classify_with_context(
            subject=email.subject or "",
            body=email.body or "",
            sender=email.sender,
        )

        logger.info(
            f"Email from {email.sender}: intent={result.intent_label} "
            f"subject=\"{email.subject[:50]}...\"" if email.subject and len(email.subject) > 50
            else f"Email from {email.sender}: intent={result.intent_label} subject=\"{email.subject}\""
        )

        # Route to handler based on intent
        handler_result = route_to_handler(
            intent=result.intent,
            email=email,
            email_sender=email_sender,
            db=db,
            dry_run=dry_run,
        )

        # Determine status based on handler result
        status = "processed"
        if result.intent_label == "unknown":
            status = "pending_review"
        elif result.intent_label == "speak_to_human":
            status = "escalated"

        # Save to database
        if not dry_run:
            db.save_email(
                message_id=email.message_id,
                s3_key=email.s3_key,
                sender=email.sender,
                sender_name=email.sender_name,
                recipient=email.recipient,
                subject=email.subject,
                body=email.body,
                received_at=email.received_at,
                intent_flags=result.intent_flags,
                intent_label=result.intent_label,
                handler_result=handler_result,
                status=status,
            )

            # Mark as processed in S3
            ses_client.mark_processed(email.s3_key)

        return True

    except Exception as e:
        logger.error(f"Failed to process email {email.message_id}: {e}")
        if not dry_run:
            try:
                ses_client.mark_failed(email.s3_key)
            except Exception as move_err:
                logger.error(f"Failed to move email to failed/: {move_err}")
        return False


def route_to_handler(intent, email, email_sender=None, db=None, dry_run=False):
    """Route email to appropriate handler based on intent.

    Args:
        intent: Intent enum value
        email: Email object
        email_sender: EmailSender instance (optional)
        db: Database instance (optional, needed for create_account)
        dry_run: If True, don't take real actions

    Returns:
        Dict with handler result data
    """
    from classifier import Intent

    handler_result = {
        "intent": intent.label,
        "dry_run": dry_run,
    }

    if intent == Intent.SEND_INFO:
        logger.debug(f"Handler: send_info for {email.sender}")
        if email_sender:
            handler_result = handle_send_info(email, email_sender, dry_run)
            handler_result["intent"] = intent.label
        else:
            handler_result["action"] = "send_info"
            handler_result["status"] = "error"
            handler_result["error"] = "EmailSender not configured"

    elif intent == Intent.CREATE_ACCOUNT:
        logger.debug(f"Handler: create_account for {email.sender}")
        if email_sender and db:
            handler_result = handle_create_account(email, email_sender, db, dry_run)
            handler_result["intent"] = intent.label
        else:
            handler_result["action"] = "create_account"
            handler_result["status"] = "error"
            handler_result["error"] = "EmailSender or Database not configured"

    elif intent == Intent.SPEAK_TO_HUMAN:
        logger.debug(f"Handler: speak_to_human for {email.sender}")
        if email_sender:
            handler_result = handle_speak_to_human(email, email_sender, dry_run)
            handler_result["intent"] = intent.label
        else:
            handler_result["action"] = "speak_to_human"
            handler_result["status"] = "error"
            handler_result["error"] = "EmailSender not configured"

    elif intent == Intent.EMAIL_TO_HUMAN:
        logger.debug(f"Handler: email_to_human for {email.sender}")
        if email_sender:
            handler_result = handle_email_to_human(email, email_sender, dry_run)
            handler_result["intent"] = intent.label
        else:
            handler_result["action"] = "email_to_human"
            handler_result["status"] = "error"
            handler_result["error"] = "EmailSender not configured"

    elif intent == Intent.UNKNOWN:
        logger.debug(f"Handler: unknown for {email.sender}")
        if email_sender:
            handler_result = handle_unknown(email, email_sender, dry_run)
            handler_result["intent"] = intent.label
        else:
            handler_result["action"] = "unknown"
            handler_result["status"] = "error"
            handler_result["error"] = "EmailSender not configured"

    elif intent == Intent.SPAM_OR_AUTO_REPLY:
        # Silently ignore spam and auto-replies to avoid email loops
        logger.info(f"Ignoring spam/auto-reply from {email.sender}")
        handler_result["action"] = "ignore"
        handler_result["status"] = "ignored"

    else:
        # Reserved or unexpected
        logger.warning(f"No handler for intent: {intent}")
        handler_result["action"] = "none"
        handler_result["status"] = "no_handler"

    return handler_result


def process_emails(ses_client, classifier, db, email_sender=None, workmail_client=None, dry_run=False):
    """Process a single batch of emails.

    Args:
        ses_client: SESClient instance
        classifier: Classifier instance
        db: Database instance
        email_sender: EmailSender instance (optional)
        workmail_client: WorkMailClient instance (optional)
        dry_run: If True, don't modify anything

    Returns:
        Number of emails processed
    """
    logger.debug("Checking for new emails...")

    # List pending emails
    pending_keys = list(ses_client.list_pending_emails())

    if not pending_keys:
        logger.debug("No pending emails")
        return 0

    logger.info(f"Found {len(pending_keys)} pending email(s)")

    processed_count = 0
    for s3_key in pending_keys:
        # Fetch and parse email
        email = ses_client.fetch_email(s3_key)
        if not email:
            logger.warning(f"Failed to fetch email: {s3_key}")
            if not dry_run:
                ses_client.mark_failed(s3_key)
            continue

        # Process the email
        if process_single_email(email, ses_client, classifier, db, email_sender, workmail_client, dry_run):
            processed_count += 1

    return processed_count


def run(args, config):
    """Main processing loop."""
    if args.dry_run:
        logger.info("Running in dry-run mode - no emails will be processed")

    # Initialize clients
    logger.info("Initializing SES client...")
    ses_client = SESClient(config.aws)

    logger.info("Initializing classifier...")
    classifier = Classifier(config.llm)

    logger.info("Initializing database...")
    db = Database(config.database)

    logger.info("Initializing email sender...")
    email_sender = EmailSender(config.aws)

    # Initialize WorkMail client (optional - for marking emails as read)
    workmail_client = None
    if config.workmail.email and config.workmail.password:
        logger.info("Initializing WorkMail client...")
        workmail_client = WorkMailClient(
            email=config.workmail.email,
            password=config.workmail.password,
            server=config.workmail.server,
        )
        if workmail_client.connect():
            logger.info(f"Connected to WorkMail as {config.workmail.email}")
        else:
            logger.warning("Failed to connect to WorkMail - emails will not be marked as read")
            workmail_client = None
    else:
        logger.debug("WorkMail credentials not configured - skipping WorkMail integration")

    # Initialize database schema
    if not db.initialize():
        logger.error("Failed to initialize database schema")
        return

    # Test connections
    if not db.test_connection():
        logger.error("Database connection failed")
        return

    logger.info("All services initialized successfully")

    # Handle graceful shutdown
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        logger.info(f"Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(f"Starting processing loop (interval: {args.interval}s)")

    try:
        while running:
            try:
                count = process_emails(ses_client, classifier, db, email_sender, workmail_client, dry_run=args.dry_run)
                if count > 0:
                    logger.info(f"Processed {count} email(s)")
            except Exception as e:
                logger.exception(f"Error processing emails: {e}")

            if args.once:
                logger.info("Single run complete, exiting")
                break

            # Sleep in small increments to allow signal handling
            for _ in range(args.interval):
                if not running:
                    break
                time.sleep(1)
    finally:
        # Cleanup
        if workmail_client:
            workmail_client.disconnect()
            logger.debug("Disconnected from WorkMail")


def main():
    """Main entry point for the daemon."""
    args = parse_args()

    # Load configuration from .env file
    config_path = Path(args.config) if args.config else None
    config = load_config(config_path)

    # Handle --test-creds: validate and exit
    if args.test_creds:
        print(f"Testing credentials from: {args.config}")
        print("-" * 40)
        errors, warnings, success = check_credentials(config)

        for msg in success:
            print(f"  [OK] {msg}")
        for msg in warnings:
            print(f"  [WARN] {msg}")
        for msg in errors:
            print(f"  [ERROR] {msg}")

        print("-" * 40)
        if errors:
            print(f"FAILED: {len(errors)} missing credential(s)")
            sys.exit(1)
        else:
            print("SUCCESS: All required credentials configured")
            sys.exit(0)

    # Handle --test-ses: read and display emails from S3
    if args.test_ses:
        test_ses_connection(config)
        sys.exit(0)

    # Command line args override config file settings
    log_file = args.log_file or config.daemon.log_file
    pid_file = args.pid_file or config.daemon.pid_file
    interval = args.interval if args.interval != 60 else config.daemon.poll_interval

    # Update args with resolved values
    args.interval = interval

    # Daemon mode requires log file (stdout is /dev/null)
    if args.daemon and not log_file:
        print("Warning: --daemon without --log-file means no log output", file=sys.stderr)

    # Setup logging before daemonizing so we can log the startup
    if args.daemon and log_file:
        # Delay logging setup until after daemonize for daemon mode
        print(f"Starting daemon, logging to {log_file}...")
    else:
        setup_logging(verbose=args.verbose, log_file=log_file)

    if args.daemon:
        daemonize()
        # Setup logging after daemonize
        setup_logging(verbose=args.verbose, log_file=log_file)

    # Write PID file after daemonizing (so we get the final PID)
    if pid_file:
        write_pid_file(pid_file)

    logger.info(f"Loaded config from {args.config}")
    logger.info(f"ses-daemon-bot v{__version__} starting")

    # Log config summary (without secrets)
    logger.debug(f"AWS Region: {config.aws.region}")
    logger.debug(f"SES Bucket: {config.aws.ses_bucket}")
    logger.debug(f"LLM Model: {config.llm.model}")

    run(args, config)
    logger.info("ses-daemon-bot stopped")


if __name__ == "__main__":
    main()
