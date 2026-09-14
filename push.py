"""Push notifications for new dogs, sent through Apple's push service (APNs).

Inert until configured, the same bargain Turnstile makes: with no key the
nightly run logs one line and sends nothing, so shipping this code changes
nothing on its own. It goes live the moment these four secrets exist:

    APNS_KEY        the .p8 key's PEM text (newlines may be written as \\n),
                    or a filesystem path to the .p8 file
    APNS_KEY_ID     the 10-character key id Apple shows beside the key
    APNS_TEAM_ID    the Apple developer team id
    APNS_BUNDLE_ID  the app's bundle id, which APNs uses as the topic

Token auth (.p8) rather than a push certificate: one key serves every app on
the team, it never expires, and there is no yearly renewal to forget about the
week the certificate lapses and every notification silently stops.

PUSH_PAUSED stops sends while leaving everything else running, the push twin of
EMAILS_PAUSED. They are separate on purpose: pausing email during a
deliverability problem should not also silence the app, and the reverse.
"""
import base64
import json
import os
import time
from typing import Iterable, List, Optional, Tuple

import cities

PROD_HOST = "https://api.push.apple.com"
SANDBOX_HOST = "https://api.sandbox.push.apple.com"

# Apple rejects a provider token older than an hour and throttles one that is
# refreshed more often than every twenty minutes, so a token is minted once and
# reused inside that window rather than signed per request.
_JWT_TTL = 50 * 60
_jwt = {"token": None, "at": 0.0}

# How many names a notification spells out before "and N more". Three reads
# as a list; four starts to truncate on a lock screen.
NAMED = 3
# dog_ids ride in the payload so a tap can open straight to the new dogs.
# APNs caps a payload at 4KB and an id is ~25 bytes, so twenty is far inside.
MAX_IDS = 20


def configured() -> bool:
    return all(os.getenv(k) for k in
               ("APNS_KEY", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID"))


def _key_pem() -> bytes:
    raw = os.getenv("APNS_KEY", "")
    # A Fly secret holds one line, so a pasted key usually arrives with its
    # newlines written as the two characters \n.
    if "BEGIN PRIVATE KEY" in raw:
        return raw.replace("\\n", "\n").encode()
    with open(raw, "rb") as f:
        return f.read()


def _b64(b: bytes) -> bytes:
    return base64.urlsafe_b64encode(b).rstrip(b"=")


def provider_token(now: float = None) -> str:
    """The ES256 JWT APNs wants in the authorization header."""
    now = time.time() if now is None else now
    if _jwt["token"] and now - _jwt["at"] < _JWT_TTL:
        return _jwt["token"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import (
        decode_dss_signature)

    compact = dict(separators=(",", ":"))
    header = _b64(json.dumps({"alg": "ES256", "kid": os.environ["APNS_KEY_ID"]},
                             **compact).encode())
    claims = _b64(json.dumps({"iss": os.environ["APNS_TEAM_ID"],
                              "iat": int(now)}, **compact).encode())
    signing_input = header + b"." + claims
    key = serialization.load_pem_private_key(_key_pem(), password=None)
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # cryptography signs in DER; a JWS wants the raw 64-byte R||S. Sending the
    # DER form is the classic reason a hand-rolled APNs JWT is rejected with
    # InvalidProviderToken while looking perfectly well-formed.
    r, s = decode_dss_signature(der)
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = (signing_input + b"." + _b64(sig)).decode()
    _jwt.update(token=token, at=now)
    return token


def _join(names: List[str], more: int) -> str:
    if more > 0:
        return ", ".join(names) + f" and {more} more"
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def build_payload(dogs, city: str, today: str = None) -> dict:
    """The notification for one city's morning.

    One dog is named in the title, because a single arrival is news about that
    dog. Several are counted in the title and named in the body, because the
    count is the news and the names are the reason to tap.
    """
    c = cities.resolve(city)
    n = len(dogs)
    names = [d.name.strip() for d in dogs if (d.name or "").strip()]
    if n == 1:
        d = dogs[0]
        title = f"{names[0] if names else 'A new dog'} just arrived"
        # Rescues type "Unknown" into the breed field as often as they leave it
        # blank, and a lock screen reading "Unknown · 5 years" sounds like the
        # dog is a mystery rather than a mix. Say nothing instead.
        breed = (d.breed or "").strip()
        if breed.lower() in ("unknown", "unknown breed", "n/a", "-"):
            breed = ""
        facts = [f for f in (breed, d.age, d.source_label) if f]
        body = " · ".join(facts) or f"New in {c.short} today"
    else:
        title = f"{n} new dogs in {c.short}"
        shown = names[:NAMED]
        body = "Meet " + _join(shown, n - len(shown))
    return {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            # One thread per city, so a week of mornings stacks as one group
            # on the lock screen instead of seven separate banners.
            "thread-id": f"new-dogs-{c.code}",
        },
        "kind": "new_dogs",
        "city": c.code,
        "date": today or "",
        "dog_ids": [d.id for d in dogs][:MAX_IDS],
    }


def _reason(resp) -> str:
    try:
        return (resp.json() or {}).get("reason", "")
    except Exception:
        return ""


def send(devices: Iterable[Tuple[str, str]], payload: dict,
         collapse_id: str = None, client=None) -> dict:
    """Deliver one payload to many devices over a single HTTP/2 connection.

    `devices` is (token, env) pairs, env being "production" or "sandbox".
    Returns counts plus the tokens APNs says are gone, for the caller to prune.

    A BadDeviceToken is retried once on the other host before the token is
    treated as dead. A sandbox token sent to production reports exactly that
    error, so without the retry a build that mislabelled its environment would
    get every one of its devices deleted on the first morning.
    """
    import httpx

    bundle = os.environ["APNS_BUNDLE_ID"]
    body = json.dumps(payload, separators=(",", ":")).encode()
    own = client is None
    if own:
        client = httpx.Client(http2=True, timeout=15)
    sent, failed, dead = 0, 0, []

    def post(host, token):
        headers = {
            "authorization": f"bearer {provider_token()}",
            "apns-topic": bundle,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        if collapse_id:
            headers["apns-collapse-id"] = collapse_id[:64]
        return client.post(f"{host}/3/device/{token}", content=body,
                           headers=headers)

    try:
        for token, env in devices:
            first = SANDBOX_HOST if env == "sandbox" else PROD_HOST
            other = PROD_HOST if first == SANDBOX_HOST else SANDBOX_HOST
            try:
                r = post(first, token)
                if r.status_code == 403 and _reason(r) == "ExpiredProviderToken":
                    _jwt.update(token=None, at=0.0)
                    r = post(first, token)
                if r.status_code == 400 and _reason(r) == "BadDeviceToken":
                    r = post(other, token)
            except Exception as e:
                print(f"  push: {token[:8]}… {type(e).__name__}: {e}")
                failed += 1
                continue
            if r.status_code == 200:
                sent += 1
            elif r.status_code == 410 or _reason(r) in (
                    "BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
                dead.append(token)
            else:
                print(f"  push: {token[:8]}… HTTP {r.status_code} {_reason(r)}")
                failed += 1
    finally:
        if own:
            client.close()
    return {"sent": sent, "failed": failed, "dead": dead}


def send_new_dogs(city: str, dogs, client=None) -> Optional[dict]:
    """Tell every device following `city` about this morning's new dogs.

    Returns None when nothing was attempted — no dogs, paused, unconfigured, or
    nobody installed — so the caller can tell "sent to nobody" from "did not try".
    """
    import db

    if not dogs:
        return None
    if os.getenv("PUSH_PAUSED"):
        print(f"PUSH_PAUSED set — {len(dogs)} new {city} dog(s), no push sent.")
        return None
    if not configured():
        print("  (APNS_* unset — push not sent)")
        return None
    devices = db.devices_for(city)
    if not devices:
        print(f"  no {city} devices registered for push")
        return None
    from datetime import datetime
    from zoneinfo import ZoneInfo
    c = cities.resolve(city)
    today = datetime.now(ZoneInfo(c.tz)).date().isoformat()
    result = send([(d["token"], d["env"]) for d in devices],
                  build_payload(dogs, city, today),
                  collapse_id=f"new-{c.code}-{today}", client=client)
    for token in result["dead"]:
        db.remove_device(token)
    extra = ""
    if result["dead"]:
        extra += f", pruned {len(result['dead'])}"
    if result["failed"]:
        extra += f", {result['failed']} failed"
    print(f"Pushed {result['sent']}/{len(devices)} {city} device(s){extra}.")
    return result
