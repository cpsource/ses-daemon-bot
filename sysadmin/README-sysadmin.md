# SES Daemon Bot - System Administration Guide

## Overview

This guide covers installation, configuration, and management of the ses-daemon-bot service on Ubuntu/Debian systems.

## Files

| File | Description |
|------|-------------|
| `ses-daemon-bot.sh` | Management script for manual control |
| `ses-daemon-bot.service` | systemd unit file for system integration |

## Quick Start

### Manual Management (ses-daemon-bot.sh)

```bash
# Make executable
chmod +x /home/ubuntu/ses-daemon-bot/sysadmin/ses-daemon-bot.sh

# Create symlink for convenience
sudo ln -sf /home/ubuntu/ses-daemon-bot/sysadmin/ses-daemon-bot.sh /usr/local/bin/ses-daemon-bot

# Usage
ses-daemon-bot start       # Start the daemon
ses-daemon-bot stop        # Stop the daemon
ses-daemon-bot restart     # Restart the daemon
ses-daemon-bot status      # Check status
ses-daemon-bot logs        # Tail log file
ses-daemon-bot test-creds  # Validate credentials
ses-daemon-bot test-ses    # Test S3/SES connection
```

### systemd Integration

```bash
# Install the service file
sudo cp /home/ubuntu/ses-daemon-bot/sysadmin/ses-daemon-bot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable auto-start on boot
sudo systemctl enable ses-daemon-bot

# Start the service
sudo systemctl start ses-daemon-bot

# Check status
sudo systemctl status ses-daemon-bot
```

## systemctl Commands

| Command | Description |
|---------|-------------|
| `sudo systemctl start ses-daemon-bot` | Start the daemon |
| `sudo systemctl stop ses-daemon-bot` | Stop the daemon |
| `sudo systemctl restart ses-daemon-bot` | Restart the daemon |
| `sudo systemctl status ses-daemon-bot` | Show status |
| `sudo systemctl enable ses-daemon-bot` | Enable auto-start on boot |
| `sudo systemctl disable ses-daemon-bot` | Disable auto-start |
| `sudo journalctl -u ses-daemon-bot` | View systemd journal logs |
| `sudo journalctl -u ses-daemon-bot -f` | Follow journal logs |

## Configuration

### Paths

| Path | Description |
|------|-------------|
| `/home/ubuntu/.env` | Credentials and configuration |
| `/var/log/ses-daemon-bot.log` | Application log file |
| `/var/run/ses-daemon-bot.pid` | PID file |
| `/home/ubuntu/ses-daemon-bot/` | Application directory |

### Environment Variables

The daemon reads from `/home/ubuntu/.env`:

```bash
# AWS Credentials
AWS_ACCESS_KEY=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
SES_BUCKET=frflashy-ses-incoming

# Database
NEON_DATABASE_URL=postgresql://user:pass@host/db

# LLM
OPENAI_API_KEY=sk-...
LLM_MODEL=gpt-4

# Daemon (optional)
POLL_INTERVAL=60
LOG_FILE=/var/log/ses-daemon-bot.log
PID_FILE=/var/run/ses-daemon-bot.pid
```

## Log Management

### View Logs

```bash
# Tail application log
tail -f /var/log/ses-daemon-bot.log

# View with ses-daemon-bot.sh
ses-daemon-bot logs

# View systemd journal
sudo journalctl -u ses-daemon-bot -f
```

### Log Rotation

Create `/etc/logrotate.d/ses-daemon-bot`:

```
/var/log/ses-daemon-bot.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 ubuntu ubuntu
    postrotate
        systemctl reload ses-daemon-bot 2>/dev/null || true
    endscript
}
```

## Troubleshooting

### Daemon won't start

1. Check credentials:
   ```bash
   ses-daemon-bot test-creds
   ```

2. Check log file:
   ```bash
   tail -50 /var/log/ses-daemon-bot.log
   ```

3. Test SES/S3 connection:
   ```bash
   ses-daemon-bot test-ses
   ```

4. Check Python environment:
   ```bash
   /home/ubuntu/mnt/myproject/bin/python3 --version
   ```

### Stale PID file

If the daemon crashes, the PID file may remain:

```bash
# Check if process is actually running
ps aux | grep ses-daemon-bot

# Remove stale PID file
rm /var/run/ses-daemon-bot.pid

# Start daemon
ses-daemon-bot start
```

### Permission errors

```bash
# Fix log file permissions
sudo touch /var/log/ses-daemon-bot.log
sudo chown ubuntu:ubuntu /var/log/ses-daemon-bot.log

# Fix PID file directory (if needed)
sudo touch /var/run/ses-daemon-bot.pid
sudo chown ubuntu:ubuntu /var/run/ses-daemon-bot.pid
```

### systemd service fails

```bash
# View detailed status
sudo systemctl status ses-daemon-bot -l

# View journal for errors
sudo journalctl -u ses-daemon-bot --no-pager -n 50

# Reload after changes to service file
sudo systemctl daemon-reload
```

## Security Notes

The systemd service file includes security hardening:

- `NoNewPrivileges=true` - Prevents privilege escalation
- `PrivateTmp=true` - Isolated /tmp directory
- `ProtectSystem=strict` - Read-only filesystem except allowed paths
- `ProtectHome=read-only` - Read-only home directories
- `ReadWritePaths` - Explicit write access only to log/run/app dirs

## Monitoring

### Health Check Script

```bash
#!/bin/bash
# /usr/local/bin/ses-daemon-bot-healthcheck.sh

if ! systemctl is-active --quiet ses-daemon-bot; then
    echo "CRITICAL: ses-daemon-bot is not running"
    exit 2
fi

# Check if processing (optional: check log timestamps)
LOG_FILE="/var/log/ses-daemon-bot.log"
if [ -f "$LOG_FILE" ]; then
    LAST_MOD=$(stat -c %Y "$LOG_FILE")
    NOW=$(date +%s)
    AGE=$((NOW - LAST_MOD))

    if [ $AGE -gt 300 ]; then  # 5 minutes
        echo "WARNING: Log file not updated in ${AGE}s"
        exit 1
    fi
fi

echo "OK: ses-daemon-bot is running"
exit 0
```

### Cron Job for Monitoring

```bash
# Check every 5 minutes, restart if not running
*/5 * * * * systemctl is-active --quiet ses-daemon-bot || systemctl start ses-daemon-bot
```

## Backup

### What to Back Up

1. `/home/ubuntu/.env` - Credentials
2. `/home/ubuntu/ses-daemon-bot/` - Application code
3. Neon database - Use Neon's backup features

### Restore Procedure

1. Restore application code
2. Restore `.env` file
3. Install systemd service: `sudo cp sysadmin/ses-daemon-bot.service /etc/systemd/system/`
4. Reload systemd: `sudo systemctl daemon-reload`
5. Start service: `sudo systemctl start ses-daemon-bot`
