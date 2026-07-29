#!/bin/sh
# Fly.io entrypoint: web + nightly scrape in ONE machine, because Fly volumes
# attach to a single machine — the compose split (web/cron sharing volumes)
# doesn't translate. Both the SQLite DB and the generated pages live on the
# /data volume so deploys and restarts never lose them.
set -u

# Generated pages go on the volume; the bundled assets (favicon, assets/) come
# from the image. Two steps, because they need opposite clobber rules:
#
#   1. Seed whatever the volume is missing, no-clobber. Can only ever add
#      files, so it can never eat generated output.
#   2. Force-refresh the committed assets, so an edited logo or favicon
#      actually reaches production. Step 1 alone never updates a file that
#      already exists, which is why the logo sat stale through every deploy.
#
# The list below is deliberately explicit rather than "everything in the
# image": that keeps generated output safe by construction instead of relying
# on .dockerignore listing every file check.py writes. `git ls-files public/`
# is the source of truth for it, but .git is not in the image so the list
# cannot be derived at boot — keep it in sync by hand when adding an asset. A
# missing entry only fails to refresh; it can never destroy volume data.
IMAGE_PUBLIC=/app/public
mkdir -p /data/public
cp -rn "$IMAGE_PUBLIC/." /data/public/ 2>/dev/null || true

for asset in \
  apple-touch-icon.png \
  favicon.png \
  assets/luvd-logo.png \
  assets/luvd-logo-email.png
do
  [ -f "$IMAGE_PUBLIC/$asset" ] || continue
  mkdir -p "/data/public/$(dirname "$asset")"
  # -p keeps the image's mtime, so Last-Modified tracks the asset, not boot time.
  cp -p "$IMAGE_PUBLIC/$asset" "/data/public/$asset" || true
done

rm -rf /app/public
ln -s /data/public /app/public

# A boot render and the 05:30 cron render are the same script and would fight
# over public/ if a deploy landed just before 05:30 — page.write() deletes and
# rebuilds public/dog/, so an overlap can leave a torn tree. mkdir is atomic,
# which makes it a real mutex with no extra dependencies.
#
# The lock lives in /tmp, not on /data, so a machine killed mid-render comes
# back with a clean lock instead of a wedged one that survives forever.
RENDER_LOCK=/tmp/luvd-render.lock

# Which city owns the once-a-week jobs. Read from the registry rather than
# written here, so there is still exactly one place that decides it.
DEFAULT_CITY=$(python cities.py --default 2>/dev/null || echo NYC)

# Minutes within which an existing page counts as "just rendered".
RENDER_FRESH_MIN=12

render() {
  # Reap a lock left behind by a render whose process died without the
  # container going with it (an OOM kill during the montage, say). Without
  # this, one bad night would silently stop every later render.
  if [ -n "$(find "$RENDER_LOCK" -mmin +60 2>/dev/null)" ]; then
    echo "render: clearing a stale lock"
    rmdir "$RENDER_LOCK" 2>/dev/null || true
  fi
  if ! mkdir "$RENDER_LOCK" 2>/dev/null; then
    echo "render: another render holds the lock, skipping this one"
    return 0
  fi
  # Never fatal: a failed scrape must leave the previous page being served
  # rather than taking the container down with it.
  python "$@" || true
  rmdir "$RENDER_LOCK" 2>/dev/null || true
}

# Backgrounded so gunicorn below starts and answers requests immediately — the
# render happens behind a site that is already serving the previous page.
(
  # Deploying should publish. The page lives on the volume, so shipping new
  # code changed nothing on its own: this used to render only when index.html
  # was missing, which left new frontend work invisible until the next 05:30.
  #
  # --dry-run is the no-email path. It still writes the page, share card and
  # montage, but takes first_seen_map() instead of record_seen(), skips
  # forget_missing()/update_photo_state(), and returns before the subscriber
  # digest — so no boot, first ever or otherwise, can mail the list.
  if [ ! -f /data/public/index.html ]; then
    echo "boot: no page on the volume — rendering now"
    render check.py --dry-run
  elif [ -n "$(find /data/public/index.html -mmin -"$RENDER_FRESH_MIN" 2>/dev/null)" ]; then
    # Fly restarts on crashes and failed health checks, and a render scrapes
    # seven rescue sites. Don't hammer them re-rendering a page that is
    # already current; the next boot outside this window will pick it up.
    echo "boot: page is under ${RENDER_FRESH_MIN}m old — skipping the render"
  else
    echo "boot: re-rendering so this deploy's changes go live"
    render check.py --dry-run
  fi

  # Sleep until the next city's 05:30, run that city, repeat. Mondays also send
  # the per-rescue digest. These are the real runs — they record what was seen
  # and mail the digest.
  #
  # Each city runs at 05:30 in ITS OWN timezone, so New York and Los Angeles are
  # three hours apart and each city's readers get their morning email in the
  # morning. The container's TZ is fixed (America/New_York, set in the
  # Dockerfile), so the arithmetic cannot be left to the ambient clock: cities.py
  # computes each city's local 05:30 with zoneinfo and prints the soonest, which
  # also keeps the schedule and the city registry from drifting apart.
  #
  # It replaces `date -d "today 05:30"` for a second reason: -d is a GNU
  # extension, so that line was silently portable only to this image.
  #
  # The two cities' runs share the render lock, so they serialise rather than
  # tearing public/ between them if one overruns into the other. Nothing new is
  # needed for that — it is the same mutex the boot render already uses.
  while true; do
    schedule=$(python cities.py --next) || schedule=""
    if [ -z "$schedule" ]; then
      # Registry unreadable. An hour is short enough to recover quickly and long
      # enough not to spin, and the page currently being served stays up.
      echo "cron: could not compute the next run — retrying in 1h"
      sleep 3600
      continue
    fi
    wait_s=${schedule%% *}
    due=${schedule#* }
    echo "cron: next run in ${wait_s}s for: ${due}"
    sleep "$wait_s"
    for city in $due; do
      render check.py --city "$city"
    done
    # The weekly report is one business summary, not a per-city one, so it goes
    # out after the default city's run only. Without that it would arrive once
    # per live city every Monday.
    case " $due " in
      *" $DEFAULT_CITY "*)
        [ "$(date +%u)" = "1" ] && python weekly_report.py
        ;;
    esac
  done
) &

exec gunicorn -w 2 -b 0.0.0.0:8000 --timeout 60 app:app
