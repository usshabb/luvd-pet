# Deploying LUVD NYC

Target: a small VPS running Docker, with Caddy terminating TLS. Roughly $5/month.
Everything below is copy-paste; substitute your domain where marked.

**Why not a free tier:** the SQLite file holds `first_seen` dates (the whole
timeline), your subscriber list and view counts. Free tiers use ephemeral disks
that reset on every deploy — every dog would read as "new today" and the
subscriber list would vanish. This setup keeps that state on a named volume.

---

## 1. Create the server (AWS)

**Lightsail is the right AWS product here** — it's a flat-rate VPS, so the
Docker setup below works as-is and the bill doesn't move. EC2 works too, but
you're managing VPCs and security groups for no gain at this size.

### Lightsail (recommended)

1. Lightsail console → **Create instance**
2. Region **us-east-1** (close to the rescues, and where most of their image
   hosts sit)
3. Platform **Linux/Unix** → Blueprint **OS Only → Ubuntu 24.04 LTS**
4. Plan: **$5/mo** (1 GB RAM). The 512 MB plan is too tight once Chrome-less
   image processing and two Python processes are running.
5. Create, then **Networking → Attach static IP**. Do this before touching DNS:
   without it the IP changes whenever the instance stops and your domain
   silently breaks.
6. **Networking → IPv4 Firewall** → add rules for **HTTP 80** and **HTTPS 443**.

Note the static IP — that's `YOUR_SERVER_IP` below.

### EC2 instead

`t4g.small` (ARM, cheap) or `t3.micro` (free tier for 12 months), Ubuntu 24.04.
Then:
- Allocate and associate an **Elastic IP** (same reason as above)
- Security group inbound: **80**, **443**, and **22** from your IP only
- Keep the default 8 GB gp3 root volume — Docker named volumes live on it and
  persist across reboots

Everything from step 2 on is identical for either.

## 2. Point the domain (GoDaddy)

GoDaddy → **My Products** → your domain → **DNS** → **Manage Zones**.

Add or edit:

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `@` | `YOUR_SERVER_IP` (static/Elastic IP) | 600 |
| A | `www` | `YOUR_SERVER_IP` | 600 |

Delete GoDaddy's default "Parked" A record on `@` if present, and any
conflicting CNAME on `www` — GoDaddy adds these automatically and they will
shadow yours.

Check it propagated (should print your server IP):

```bash
dig +short yourdomain.com
```

Do not run step 5 until this returns the right IP — Caddy's certificate request
will fail and Let's Encrypt rate-limits repeated failures.

## 3. Install Docker on the server

Lightsail and EC2 Ubuntu images log in as `ubuntu`, not `root`, using the key
pair you downloaded:

```bash
ssh -i ~/Downloads/LightsailDefaultKey.pem ubuntu@YOUR_SERVER_IP
```

(If SSH refuses the key: `chmod 400 ~/Downloads/LightsailDefaultKey.pem`)

Then on the server:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && exit
```

SSH back in so the group membership takes effect.

## 4. Copy the project up

From your Mac:

```bash
sudo mkdir -p /opt/luvd && sudo chown ubuntu:ubuntu /opt/luvd   # run on server first
```

```bash
rsync -av -e "ssh -i ~/Downloads/LightsailDefaultKey.pem" \
  --exclude .venv --exclude logs --exclude dogfinder.db --exclude public \
  ~/luvd-nyc/ ubuntu@YOUR_SERVER_IP:/opt/luvd/
```

## 5. Configure and launch

On the server:

```bash
cd /opt/luvd && cp .env.example .env && nano .env
```

Fill in — the first two are what make the site fully live. Fetching dogs needs
no keys; every rescue source is a public endpoint:

```
LUVD_DOMAIN=yourdomain.com
SITE_URL=https://yourdomain.com
RESEND_API_KEY=
FROM_EMAIL=LUVD NYC <hello@yourdomain.com>
ALERT_EMAIL=you@example.com
LUVD_DB=/data/dogfinder.db
```

Then:

```bash
cd /opt/luvd && docker compose up -d --build
```

Seed the first run so the page exists immediately (otherwise it's blank until
05:30):

```bash
docker compose run --rm cron python check.py
```

Open `https://yourdomain.com` — Caddy will have issued the certificate.

## 6. Verify

```bash
curl -sI https://yourdomain.com | head -1
curl -s https://yourdomain.com/views
docker compose logs --tail=40 cron
```

---

## Day to day

```bash
docker compose logs -f cron        # watch the nightly scrape
docker compose run --rm cron python check.py --dry-run   # rebuild, no email
docker compose up -d --build       # deploy new code
docker compose exec web python -c "import db; print(db.list_subscribers())"
```

**Back up the state** — it is not reproducible:

```bash
docker run --rm -v luvd_luvd-data:/d -v $PWD:/b alpine \
  tar czf /b/luvd-backup-$(date +%F).tgz -C /d .
```

## Turning off the Mac jobs

Once the server is live, stop the local launchd agents so they don't email
subscribers twice:

```bash
launchctl unload ~/Library/LaunchAgents/com.luvdnyc.daily.plist
launchctl unload ~/Library/LaunchAgents/com.luvdnyc.web.plist
```

## Sending from your own domain

Resend's `onboarding@resend.dev` works for testing but lands in spam at scale.
In Resend → Domains → Add, then add the TXT/CNAME records it gives you to
GoDaddy DNS. Once verified, set `FROM_EMAIL=LUVD NYC <hello@yourdomain.com>`.
