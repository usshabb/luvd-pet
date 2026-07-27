#!/bin/bash
# Monday-morning digest. Invoked by launchd (com.luvdnyc.weekly.plist).
set -uo pipefail
cd "$(dirname "$0")" || exit 1
mkdir -p logs
LOG="logs/weekly.log"
echo "===== $(TZ=America/New_York date '+%Y-%m-%d %H:%M %Z') =====" >> "$LOG"
.venv/bin/python weekly_report.py >> "$LOG" 2>&1
echo "" >> "$LOG"
