# SES Daemon Bot - Design Document

## Overview

A Python 3 daemon that processes incoming emails for FrFlashy.com via AWS SES, classifies intent using an LLM, and routes to appropriate handlers.

## Architecture

```
                                    ┌─────────────────┐
                                    │   WorkMail      │
                                    │   (Human UI)    │
                                    └────────▲────────┘
                                             │
┌──────────┐    ┌──────────┐    ┌────────────┴────────────┐
│ Incoming │───▶│  AWS     │───▶│  SES Receipt Rule       │
│  Email   │    │  SES     │    │  1. S3Action → bucket   │
└──────────┘    └──────────┘    │  2. WorkmailAction      │
                                └────────────┬────────────┘
                                             │
                                    ┌────────▼────────┐
                                    │  S3 Bucket      │
                                    │  frflashy-ses-  │
                                    │  incoming/      │
                                    └────────┬────────┘
                                             │
                                    ┌────────▼────────┐
                                    │  ses-daemon-bot │
                                    │  (this daemon)  │
                                    └────────┬────────┘
                                             │
                         ┌───────────────────┼───────────────────┐
                         │                   │                   │
                ┌────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
                │  LLM Classifier │ │   PostgreSQL    │ │    Handlers     │
                │  (OpenAI/GPT-4) │ │   (Neon DB)     │ │  (auto-reply,   │
                └─────────────────┘ └─────────────────┘ │   escalate...)  │
                                                        └─────────────────┘
```

## Email Flow

1. Email arrives at `*@frflashy.com`
2. AWS SES receives and processes via receipt rules
3. **S3 Action**: Stores raw email in `s3://frflashy-ses-incoming/emails/`
4. **WorkMail Action**: Delivers to inbox for human access
5. Daemon polls S3 bucket for new emails
6. Each email is classified by intent using LLM
7. Routed to appropriate handler based on classification
8. Results stored in PostgreSQL

## AWS SES Configuration

### Receipt Rule Set: `INBOUND_MAIL`

```json
{
  "Name": "m-6756a247620e40bca7c9f1fc7d8ce461",
  "Enabled": true,
  "Recipients": ["frflashy.awsapps.com", "frflashy.com"],
  "Actions": [
    {
      "S3Action": {
        "BucketName": "frflashy-ses-incoming",
        "ObjectKeyPrefix": "emails/"
      }
    },
    {
      "WorkmailAction": {
        "OrganizationArn": "arn:aws:workmail:us-east-1:460441405622:organization/m-6756a247620e40bca7c9f1fc7d8ce461"
      }
    }
  ]
}
```

### S3 Bucket: `frflashy-ses-incoming`

- **Region**: us-east-1
- **Prefix**: `emails/`
- **Policy**: Allows `ses.amazonaws.com` to `s3:PutObject`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowSESPuts",
      "Effect": "Allow",
      "Principal": {"Service": "ses.amazonaws.com"},
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::frflashy-ses-incoming/*",
      "Condition": {
        "StringEquals": {"AWS:SourceAccount": "460441405622"}
      }
    }
  ]
}
```

## Intent Classification

### Intent Categories

| Index | Intent           | Description                                  | Handler Action        |
|-------|------------------|----------------------------------------------|----------------------|
| 0     | `send_info`      | User wants information, pricing, docs        | Auto-reply with info |
| 1     | `create_account` | User wants to sign up, register, trial       | CRM task creation    |
| 2     | `unknown`        | Intent cannot be determined                  | Queue for review     |
| 3     | `speak_to_human` | User requests human contact                  | Escalate to support  |
| 4     | `reserved`       | Reserved for future use                      | N/A (always false)   |

### Classification Output Format

Returns a JSON array of 5 booleans with exactly one `true`:

```json
[false, true, false, false, false]  // create_account intent
```

### LLM Prompt

Located at: `prompts/intent_classifier.txt`

The prompt instructs the LLM to:
- Analyze email content
- Return exactly one true value
- Default to `unknown` (index 2) if ambiguous
- Always set index 4 to false

## Configuration

### Environment Variables

Loaded from `/home/ubuntu/.env` using python-dotenv.

| Variable              | Description                          | Required |
|-----------------------|--------------------------------------|----------|
| `AWS_ACCESS_KEY`      | AWS access key                       | Yes      |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key                     | Yes      |
| `AWS_REGION`          | AWS region (default: us-east-1)      | No       |
| `SES_BUCKET`          | S3 bucket for incoming emails        | Yes      |
| `NEON_DATABASE_URL`   | PostgreSQL connection string         | Yes      |
| `OPENAI_API_KEY`      | OpenAI API key for classification    | Yes      |
| `LLM_MODEL`           | Model to use (default: gpt-4)        | No       |
| `POLL_INTERVAL`       | Seconds between polls (default: 60)  | No       |
| `LOG_FILE`            | Log file path                        | No       |
| `PID_FILE`            | PID file path                        | No       |

### Credential Validation

```bash
python3 main.py --test-creds
```

Validates all required credentials are present before starting.

## Command Line Interface

```
usage: ses-daemon-bot [-h] [--version] [-v] [--config FILE] [--log-file FILE]
                      [--pid-file FILE] [--dry-run] [--daemon] [--once]
                      [--interval SECS] [--test-creds] [--test-ses]

Options:
  --version        Show version
  -v, --verbose    Debug logging
  --config FILE    Path to .env file (default: /home/ubuntu/.env)
  --log-file FILE  Log file path
  --pid-file FILE  PID file for daemon management
  --dry-run        Test mode, no actual processing
  --daemon         Detach and run as background daemon
  --once           Process one batch and exit
  --interval SECS  Polling interval (default: 60)
  --test-creds     Validate credentials and exit
  --test-ses       Read and display emails from S3 (non-destructive), then exit
```

## Database Schema

### Table: `ses_emails`

```sql
CREATE TABLE IF NOT EXISTS ses_emails (
    id SERIAL PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    s3_key TEXT NOT NULL,
    sender TEXT NOT NULL,
    sender_name TEXT,
    recipient TEXT,
    subject TEXT,
    body TEXT,
    received_at TIMESTAMP WITH TIME ZONE,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    intent_flags JSONB NOT NULL,
    intent_label TEXT NOT NULL,
    handler_result JSONB,
    status TEXT DEFAULT 'processed'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ses_emails_message_id ON ses_emails(message_id);
CREATE INDEX IF NOT EXISTS idx_ses_emails_sender ON ses_emails(sender);
CREATE INDEX IF NOT EXISTS idx_ses_emails_intent_label ON ses_emails(intent_label);
CREATE INDEX IF NOT EXISTS idx_ses_emails_status ON ses_emails(status);
CREATE INDEX IF NOT EXISTS idx_ses_emails_processed_at ON ses_emails(processed_at);
```

### Column Descriptions

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Auto-incrementing primary key |
| `message_id` | TEXT | Unique email Message-ID header (used for deduplication) |
| `s3_key` | TEXT | S3 object key where email was stored |
| `sender` | TEXT | Sender email address |
| `sender_name` | TEXT | Sender display name (if provided) |
| `recipient` | TEXT | Recipient address |
| `subject` | TEXT | Email subject line |
| `body` | TEXT | Plain text body content |
| `received_at` | TIMESTAMPTZ | Original email received timestamp |
| `processed_at` | TIMESTAMPTZ | When daemon processed this email |
| `intent_flags` | JSONB | Classification result as boolean array |
| `intent_label` | TEXT | Human-readable intent (send_info, create_account, etc.) |
| `handler_result` | JSONB | Result data from intent handler |
| `status` | TEXT | Processing status (processed, failed, pending_review) |

### Status Values

| Status | Description |
|--------|-------------|
| `processed` | Successfully classified and handled |
| `failed` | Processing failed (error stored in handler_result) |
| `pending_review` | Queued for human review (unknown intent) |
| `escalated` | Escalated to human support |

### The `intent_flags` Column

Stores the classification result as a JSONB array of 5 booleans:
```json
[false, true, false, false, false]  // create_account intent
```

Index mapping:
- `[0]` = send_info
- `[1]` = create_account
- `[2]` = unknown
- `[3]` = speak_to_human
- `[4]` = reserved (always false)

### Database Operations (db.py)

The `Database` class provides:

| Method | Description |
|--------|-------------|
| `initialize()` | Create tables and indexes if not exist |
| `save_email(...)` | Insert or update email record (upsert on message_id) |
| `get_email_by_message_id(id)` | Retrieve by Message-ID header |
| `get_email_by_id(id)` | Retrieve by database ID |
| `email_exists(message_id)` | Check if already processed (for deduplication) |
| `get_emails_by_intent(label, limit)` | Query by intent classification |
| `get_emails_by_status(status, limit)` | Query by processing status |
| `get_recent_emails(limit)` | Get most recently processed |
| `update_email_status(id, status, result)` | Update status and handler result |
| `get_counts_by_intent()` | Aggregate counts by intent |
| `get_counts_by_status()` | Aggregate counts by status |
| `test_connection()` | Verify database connectivity |

### Connection Management

Uses context managers for safe connection handling:
```python
with db.get_cursor() as cursor:
    cursor.execute(query, params)
    # Auto-commit on success, rollback on exception
```

## Project Structure

```
ses-daemon-bot/
├── main.py              # Entry point, CLI, daemon loop
├── config.py            # Configuration loader from .env
├── classifier.py        # LLM intent classification
├── ses_client.py        # AWS SES/S3 integration
├── db.py                # PostgreSQL operations
├── handlers/            # Intent-specific handlers
│   ├── __init__.py
│   ├── send_info.py     # Auto-reply with information
│   ├── create_account.py # CRM task creation
│   ├── speak_to_human.py # Escalation handler
│   └── unknown.py       # Queue for manual review
├── prompts/
│   └── intent_classifier.txt  # LLM prompt template
├── qa/                  # Test suite
│   ├── conftest.py      # Shared fixtures
│   ├── test_cli.py      # CLI tests
│   ├── test_config.py   # Config loading tests
│   ├── test_credentials.py # Credential validation tests
│   ├── test_ses_client.py  # SES/S3 client tests
│   ├── test_classifier.py  # Intent classifier tests
│   └── test_db.py       # Database operations tests
├── requirements.txt
├── ses-daemon-bot.service  # systemd unit file
├── ses-plan.txt         # Intent classification plan (working doc)
├── .env.example         # Example environment file
├── README.md            # User documentation
└── README-design.md     # This file
```

## Daemon Operation

### Starting

```bash
# Foreground (development)
python3 main.py -v

# Background daemon (production)
python3 main.py --daemon --log-file /var/log/ses-daemon-bot.log --pid-file /var/run/ses-daemon-bot.pid

# Via systemd
sudo systemctl start ses-daemon-bot
```

### Processing Loop

1. Poll S3 bucket for new objects in `emails/` prefix
2. For each new email:
   - Parse MIME content
   - Extract sender, subject, body
   - Call LLM for intent classification
   - Route to appropriate handler
   - Store result in PostgreSQL
   - Mark as processed (move/delete from S3 or mark in DB)
3. Sleep for `--interval` seconds
4. Repeat

### Graceful Shutdown

Handles SIGTERM and SIGINT for clean shutdown:
- Completes current email processing
- Writes final log entries
- Removes PID file

## Security Considerations

- Credentials loaded at runtime from `.env`, never hardcoded
- `.env` file should be readable only by daemon user
- S3 bucket policy restricts access to SES service
- Database credentials use connection string (supports SSL)
- No secrets logged (even at debug level)

## Future Enhancements

From `ses-plan.txt`:
- Confidence scores for classification
- Secondary intent fallback
- Multi-language support (FR/EN)
- Keyword trace for audit/debug
- Workflow ID mapping
