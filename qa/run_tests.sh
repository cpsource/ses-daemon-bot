#!/bin/bash
# QA test runner script

set -e
cd "$(dirname "$0")/.."

echo "=== Running unit tests (pytest) ==="
python -m pytest qa/ -v

echo ""
echo "=== Testing credentials ==="
python main.py --test-creds

echo ""
echo "=== Testing SES connection ==="
python main.py --test-ses

echo ""
echo "=== All tests passed ==="
