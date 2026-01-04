# SES Daemon Bot

A Python 3 background service for processing incoming AWS SES mail for [FrFlashy.com](https://frflashy.com).

## Overview

This daemon monitors an AWS SES mailbox, classifies incoming emails by intent using AI, and routes them to appropriate handlers (auto-reply, CRM task creation, or human escalation).

## Features

- **AWS SES Integration**: Polls or receives incoming emails via SES
- **AI-Powered Intent Classification**: Uses LLM to determine sender intent
- **Automated Routing**: Routes emails based on classification results
- **PostgreSQL Storage**: Persists emails and classification data
- **Daemon Mode**: Runs as a systemd service

## Intent Classification

Emails are classified into one of five intent categories:

| Index | Intent           | Description                                      |
|-------|------------------|--------------------------------------------------|
| 0     | `send_info`      | User wants information, pricing, docs            |
| 1     | `create_account` | User wants to sign up, register, start trial     |
| 2     | `unknown`        | Intent cannot be confidently determined          |
| 3     | `speak_to_human` | User asks for a person, call, or support         |
| 4     | `reserved`       | Reserved for future use                          |

Classification returns a JSON array of 5 booleans with exactly one `true` value:
```json
[false, true, false, false, false]  // create_account intent
```

## Architecture

```
AWS SES --> S3/SNS --> ses-daemon-bot --> PostgreSQL
                            |
                            +--> LLM (intent classification)
                            |
                            +--> Auto-reply / CRM / Human escalation
```

## Requirements

- Python 3.10+
- AWS account with SES configured
- PostgreSQL database
- OpenAI API key (or compatible LLM endpoint)

## Installation

```bash
git clone git@github.com:cpsource/ses-daemon-bot.git
cd ses-daemon-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Environment variables:

| Variable              | Description                          |
|-----------------------|--------------------------------------|
| `AWS_ACCESS_KEY_ID`   | AWS credentials                      |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials                    |
| `AWS_REGION`          | AWS region (e.g., `us-east-1`)       |
| `SES_BUCKET`          | S3 bucket for incoming mail          |
| `DATABASE_URL`        | PostgreSQL connection string         |
| `OPENAI_API_KEY`      | API key for intent classification    |

## Usage

### Run directly
```bash
python3 main.py
```

### Run as systemd service
```bash
sudo cp ses-daemon-bot.service /etc/systemd/system/
sudo systemctl enable ses-daemon-bot
sudo systemctl start ses-daemon-bot
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

## Project Structure

```
ses-daemon-bot/
├── main.py              # Entry point
├── config.py            # Configuration loader
├── ses_client.py        # AWS SES/S3 integration
├── classifier.py        # Intent classification
├── handlers/            # Intent-specific handlers
│   ├── send_info.py
│   ├── create_account.py
│   ├── speak_to_human.py
│   └── unknown.py
├── db.py                # Database operations
├── requirements.txt
├── ses-daemon-bot.service
├── ses-plan.txt         # Classification plan (working doc)
└── README.md
```

## Development

See `ses-plan.txt` for the current intent classification plan. This document evolves as the project develops.

## License

MIT
