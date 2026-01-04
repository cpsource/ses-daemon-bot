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
                      [--interval SECS] [--test-creds]

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
```

## Database Schema

```sql
CREATE TABLE emails (
    id SERIAL PRIMARY KEY,
    message_id TEXT UNIQUE NOT NULL,
    sender TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    received_at TIMESTAMP DEFAULT NOW(),
    intent_flags JSONB NOT NULL,
    processed BOOLEAN DEFAULT FALSE
);
```

The `intent_flags` column stores the classification result as JSONB:
```json
[false, true, false, false, false]
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
│   └── test_credentials.py # Credential validation tests
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
