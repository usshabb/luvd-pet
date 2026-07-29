#!/bin/bash
# Overnight run for LUVD. Invoked by launchd (see com.luvdnyc.daily.plist).
set -uo pipefail

cd "$(dirname "$0")" || exit 1

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily.log"

# Keep the log from growing without bound (~2MB).
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 2000000 ]; then
  tail -c 500000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

echo "===== $(TZ=America/New_York date '+%Y-%m-%d %H:%M:%S %Z') =====" >> "$LOG"

# The scrapers hit five live sites; give the whole run a hard ceiling so a hung
# request can never leave launchd with a stuck process.
if command -v timeout >/dev/null 2>&1; then
  timeout 600 .venv/bin/python check.py >> "$LOG" 2>&1
else
  .venv/bin/python check.py >> "$LOG" 2>&1
fi
STATUS=$?

if [ $STATUS -ne 0 ]; then
  echo "!! check.py exited $STATUS" >> "$LOG"
fi
echo "" >> "$LOG"
exit $STATUS
