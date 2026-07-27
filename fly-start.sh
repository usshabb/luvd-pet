#!/bin/sh
# Fly.io entrypoint: web + nightly scrape in ONE machine, because Fly volumes
# attach to a single machine — the compose split (web/cron sharing volumes)
# doesn't translate. Both the SQLite DB and the generated pages live on the
# /data volume so deploys and restarts never lose them.
set -u

# Generated pages go on the volume; keep the bundled assets (favicon, assets/)
# from the image on first boot, then point /app/public at the volume.
mkdir -p /data/public
cp -rn /app/public/. /data/public/ 2>/dev/null || true
rm -rf /app/public
ln -s /data/public /app/public

(
  # First ever boot: build the page now instead of serving nothing until 05:30.
  [ -f /data/public/index.html ] || python check.py || true

  # Sleep until the next 05:30 America/New_York (TZ set in the Dockerfile),
  # run once, repeat. Mondays also send the per-rescue digest.
  while true; do
    now=$(date +%s)
    next=$(date -d "today 05:30" +%s)
    [ "$next" -le "$now" ] && next=$((next + 86400))
    echo "cron: next run in $((next - now))s"
    sleep $((next - now))
    python check.py
    [ "$(date +%u)" = "1" ] && python weekly_report.py
  done
) &

exec gunicorn -w 2 -b 0.0.0.0:8000 --timeout 60 app:app
