# Deploying LUVD

## Read this first: `main` deploys itself

`.github/workflows/fly-deploy.yml` runs `flyctl deploy --remote-only` on **every
push to `main`**. There is no test step, no staging environment and no approval
gate, so a push is a production release the moment it lands. It needs the
`FLY_API_TOKEN` repo secret; the live app is `luvd-nyc` (`fly.toml`).

Two consequences worth knowing before you push:

- **Schema changes apply on the first request, not in the workflow.** Nothing in
  CI runs a migration. `app.py` calls `db.init_db()` at import, so the new
  container migrates the volume as it boots. Migrations therefore have to be
  additive and idempotent — see `db._migrate()`.
- **A second push cancels the first mid-flight.** The workflow sets
  `cancel-in-progress: true`, which is right for a queue of images but means a
  rapid follow-up push can interrupt a release that was already rolling.

The rest of this file is the **manual VPS runbook** — the original Docker +
Caddy target, kept because it still works and because it documents the
environment the container expects. It is not what production runs; production is
Fly, one machine, one volume, `fly-start.sh` running gunicorn and the nightly
scrape together.

---

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
MANDRILL_API_KEY=
FROM_EMAIL=LUVD <cory@luvd.com>
ALERT_EMAIL=you@example.com
LUVD_DB=/data/dogfinder.db
```

`SHEET_WEBHOOK_URL` is optional and deliberately left out of the file above: it
mirrors the subscribers table to a Google Sheet (see `sheet_webhook.gs`), and
the URL is itself the credential, so on Fly set it as a secret rather than
putting it in `.env`:

```bash
fly secrets set SHEET_WEBHOOK_URL='https://script.google.com/macros/s/.../exec'
```

Leave it unset and the mirror is skipped; SQLite on the volume is the source of
truth either way.

`ADMIN_TOKEN` is the same shape of thing and you have to set it, because the
operator endpoints fail closed without it:

```bash
fly secrets set ADMIN_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

It gates `/subscribers`, `/report` and `/interest-report`, which until now served
the subscriber list and the business metrics to anyone who typed the URL. Pass it
as `?token=...` or an `X-Admin-Token` header:

```bash
curl -s "https://luvd.com/report?token=$ADMIN_TOKEN"
curl -s "https://luvd.com/subscribers?token=$ADMIN_TOKEN"   # counts, never addresses
```

**While it is unset those three answer 404 for everyone, including you.** That is
deliberate: falling open until someone remembers to configure it is the bug being
fixed. Nothing on the public site depends on them, so an unset token costs you
the tools and nothing else. A wrong token also gets 404 rather than 403, so the
endpoints don't confirm they exist. `/subscribers` returns counts even when
authenticated — the Google Sheet mirror holds the list, so a leaked token still
can't dump it.

## Opening a new city

Everything a city is lives in `cities.py`. To open one:

1. Add it to `CITIES` with `live=False` — code, name, the short form the copy
   uses, state, timezone, coordinates, and the path its page publishes at.
2. Write its scrapers under `sources/rescues/`, each with `city = "<CODE>"`, and
   register them in `sources/registry.py`. Give each one a `rescue_contacts.json`
   entry, and populate `listed_since` from the start — the "Longest waiting" sort
   depends on it and five NYC scrapers had to be retrofitted for it.
3. Check it fetches: `python check.py --city <CODE> --dry-run`.
4. Flip `live=True`. That is the switch that puts it in the header picker, in the
   sitemap and on the list of cities people can subscribe to, and gives it its
   own 05:30 run in its own timezone. Nothing before this step is visible.
5. Deploy. `python cities.py --live` and `--next` show what the container will
   do.

`live=False` is not a soft launch, it is invisible: no page, no link, no signup.
Don't flip it before the scrapers work, because the picker link would 404 and the
sitemap would advertise a page with no dogs on it.

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

Mandrill will only sign mail for a domain you have verified. In Mandrill →
Settings → Domains, add `luvd.com`, then put the SPF and DKIM records it gives
you into GoDaddy DNS. Once both show as verified, set
`FROM_EMAIL=LUVD <cory@luvd.com>` — an address on an unverified domain is
rejected outright rather than merely landing in spam.
