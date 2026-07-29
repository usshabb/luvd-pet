#!/bin/bash
# One-command deploy from your Mac to a fresh Ubuntu box (Lightsail or EC2).
# Idempotent — safe to re-run to ship new code.
#
#   ./deploy.sh 1.2.3.4 luvdnyc.com ~/Downloads/LightsailDefaultKey.pem
#
set -euo pipefail

IP="${1:-}"
DOMAIN="${2:-}"
KEY="${3:-}"

# Accept www.luvd.com or luvd.com — the apex is canonical either way.
DOMAIN="${DOMAIN#www.}"

if [ -z "$IP" ] || [ -z "$DOMAIN" ]; then
  echo "usage: ./deploy.sh <server-ip> <domain> [ssh-key.pem]"
  exit 1
fi

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")
REMOTE="ubuntu@$IP"
cd "$(dirname "$0")"

say() { printf '\n\033[1;35m▸ %s\033[0m\n' "$1"; }

# --- 0. DNS sanity: Caddy will fail to get a cert if this is wrong, and
#        Let's Encrypt rate-limits repeated failures. Check before we build.
say "Checking DNS for $DOMAIN"
RESOLVED="$(dig +short "$DOMAIN" A | tail -1)"
if [ "$RESOLVED" != "$IP" ]; then
  echo "  ✗ $DOMAIN resolves to '${RESOLVED:-nothing}', expected $IP"
  echo "    Update the A record in GoDaddy and wait for it to propagate."
  echo "    (Continuing anyway would burn Let's Encrypt retries.)"
  exit 1
fi
echo "  ✓ $DOMAIN → $IP"

say "Installing Docker (skipped if present)"
ssh "${SSH_OPTS[@]}" "$REMOTE" 'command -v docker >/dev/null 2>&1 || {
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker ubuntu
  }
  sudo mkdir -p /opt/luvd && sudo chown -R ubuntu:ubuntu /opt/luvd'

say "Uploading code"
rsync -az --delete \
  -e "ssh ${SSH_OPTS[*]}" \
  --exclude .venv --exclude .git --exclude logs \
  --exclude dogfinder.db --exclude public --exclude '__pycache__' \
  --exclude '*.pyc' --exclude .env \
  ./ "$REMOTE:/opt/luvd/"

say "Writing config"
# .env is created once and then left alone, so secrets you add on the server
# aren't clobbered by the next deploy.
ssh "${SSH_OPTS[@]}" "$REMOTE" "cd /opt/luvd
  if [ ! -f .env ]; then
    cp .env.example .env
    printf '\nLUVD_DOMAIN=%s\nSITE_URL=https://%s\nLUVD_DB=/data/dogfinder.db\n' \
      '$DOMAIN' '$DOMAIN' >> .env
    echo '  created .env — add the RESEND key later with: nano /opt/luvd/.env'
  else
    grep -q '^LUVD_DOMAIN=' .env || echo 'LUVD_DOMAIN=$DOMAIN' >> .env
    echo '  .env already exists, left as-is'
  fi"

say "Building and starting"
ssh "${SSH_OPTS[@]}" "$REMOTE" 'cd /opt/luvd && docker compose up -d --build'

say "Seeding the first scrape (so the page is not blank until 05:30)"
ssh "${SSH_OPTS[@]}" "$REMOTE" 'cd /opt/luvd && docker compose run --rm cron python check.py' || true

say "Verifying"
sleep 6
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 25 "https://$DOMAIN" || echo 000)"
echo "  https://$DOMAIN → HTTP $CODE"
if [ "$CODE" = "200" ]; then
  echo "  ✓ live"
else
  echo "  Certificate can take ~30s on first boot. Check with:"
  echo "    ssh ${SSH_OPTS[*]} $REMOTE 'cd /opt/luvd && docker compose logs caddy | tail -30'"
fi
