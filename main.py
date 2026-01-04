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


def process_emails(dry_run=False):
    """Process a single batch of emails."""
    logger.debug("Checking for new emails...")
    # TODO: Implement email processing
    return 0  # Return count of processed emails


def run(args, config):
    """Main processing loop."""
    if args.dry_run:
        logger.info("Running in dry-run mode - no emails will be processed")

    # Handle graceful shutdown
    running = True

    def signal_handler(signum, frame):
        nonlocal running
        logger.info(f"Received signal {signum}, shutting down...")
        running = False

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    logger.info(f"Starting processing loop (interval: {args.interval}s)")

    while running:
        try:
            count = process_emails(dry_run=args.dry_run)
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
