"""Sign in with Apple for the app.

The phone does the sign-in with Apple and hands us the identity token Apple
issued. That token is a JWT signed with one of Apple's published keys, so
checking it needs no secret: fetch the keys, verify the RS256 signature, and
check that it was issued by Apple, for this app, recently, and in answer to
the nonce this phone chose. Only then does it name an account.

The optional half needs a Sign in with Apple private key. With one, the
authorization code from sign-in is exchanged for a refresh token, which is
kept for a single purpose: revoking Apple's grant when someone deletes their
account, which App Review requires. Without a key everything else works and
deletion still deletes; it just cannot tell Apple.

    APPLE_BUNDLE_ID          audience to accept (default APNS_BUNDLE_ID, then com.luvd.app)
    APPLE_SIGNIN_KEY_ID      key id of a key with Sign in with Apple enabled
    APPLE_SIGNIN_KEY         the .p8 contents or a path (default: APNS_KEY)
    APPLE_TEAM_ID            team id (default: APNS_TEAM_ID)

One .p8 key can have both APNs and Sign in with Apple enabled, in which case
only APPLE_SIGNIN_KEY_ID needs setting.
"""
import base64
import hashlib
import json
import os
import time

import requests

ISSUER = "https://appleid.apple.com"
KEYS_URL = ISSUER + "/auth/keys"
TOKEN_URL = ISSUER + "/auth/token"
REVOKE_URL = ISSUER + "/auth/revoke"

# Apple rotates its keys rarely and without notice. Cache for a day, and on a
# token naming a key we do not have, refetch — but not more than once a minute,
# so a stream of garbage tokens cannot turn into a stream of fetches.
_KEYS_TTL = 24 * 3600
_KEYS_RETRY = 60
_keys = {"at": 0.0, "by_kid": {}}

# Clock drift allowed between Apple, the phone and this machine.
_LEEWAY = 120


class AuthError(Exception):
    """The token does not prove who it claims to. The message is for logs."""


def audiences() -> list:
    raw = (os.getenv("APPLE_BUNDLE_ID") or os.getenv("APNS_BUNDLE_ID")
           or "com.luvd.app")
    return [a.strip() for a in raw.split(",") if a.strip()]


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _fetch_keys() -> dict:
    resp = requests.get(KEYS_URL, timeout=8)
    resp.raise_for_status()
    return {k["kid"]: k for k in resp.json().get("keys", [])}


def _apple_key(kid: str, now: float):
    stale = now - _keys["at"] > _KEYS_TTL
    missing = kid not in _keys["by_kid"] and now - _keys["at"] > _KEYS_RETRY
    if stale or missing:
        try:
            _keys.update(by_kid=_fetch_keys(), at=now)
        except Exception as e:
            if not _keys["by_kid"]:
                raise AuthError(f"could not fetch Apple's keys: {e}")
    jwk = _keys["by_kid"].get(kid)
    if jwk is None:
        raise AuthError("token signed with an unknown key")
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    n = int.from_bytes(_b64d(jwk["n"]), "big")
    e = int.from_bytes(_b64d(jwk["e"]), "big")
    return RSAPublicNumbers(e, n).public_key()


def nonce_hash(raw_nonce: str) -> str:
    """What the phone puts in the request, and so what Apple puts in the token."""
    return hashlib.sha256(raw_nonce.encode()).hexdigest()


def verify_identity_token(token: str, raw_nonce: str, now: float = None) -> dict:
    """The token's claims, or AuthError. Every check here is load-bearing."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    now = time.time() if now is None else now
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise AuthError("not a JWT")
    try:
        header = json.loads(_b64d(parts[0]))
        claims = json.loads(_b64d(parts[1]))
        signature = _b64d(parts[2])
    except ValueError:
        raise AuthError("unreadable JWT")
    # Pinned, never taken from the header: a token that says "none" or "HS256"
    # is the textbook way to walk past a verifier that trusts its own input.
    if header.get("alg") != "RS256":
        raise AuthError("unexpected algorithm")
    key = _apple_key(str(header.get("kid") or ""), now)
    try:
        key.verify(signature, f"{parts[0]}.{parts[1]}".encode(),
                   padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise AuthError("bad signature")

    if claims.get("iss") != ISSUER:
        raise AuthError("wrong issuer")
    aud = claims.get("aud")
    aud = aud if isinstance(aud, list) else [aud]
    if not set(aud) & set(audiences()):
        raise AuthError("issued for another app")
    if float(claims.get("exp") or 0) < now - _LEEWAY:
        raise AuthError("expired")
    if float(claims.get("iat") or 0) > now + _LEEWAY:
        raise AuthError("issued in the future")
    # The nonce ties the token to the sign-in this phone just started, so a
    # token lifted from somewhere else cannot be replayed here.
    if not raw_nonce or claims.get("nonce") != nonce_hash(raw_nonce):
        raise AuthError("nonce mismatch")
    if not claims.get("sub"):
        raise AuthError("no subject")
    return claims


# ---- Optional: exchange and revoke ----------------------------------------

def signin_key_configured() -> bool:
    return bool(os.getenv("APPLE_SIGNIN_KEY_ID")
                and (os.getenv("APPLE_SIGNIN_KEY") or os.getenv("APNS_KEY"))
                and (os.getenv("APPLE_TEAM_ID") or os.getenv("APNS_TEAM_ID")))


def _key_pem() -> bytes:
    raw = os.getenv("APPLE_SIGNIN_KEY") or os.getenv("APNS_KEY", "")
    if "BEGIN PRIVATE KEY" in raw:
        return raw.replace("\\n", "\n").encode()
    with open(raw, "rb") as f:
        return f.read()


def client_secret(now: float = None) -> str:
    """The ES256 JWT Apple wants as client_secret on /auth/token and /auth/revoke."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    now = int(time.time() if now is None else now)
    compact = dict(separators=(",", ":"))
    header = _b64e(json.dumps({"alg": "ES256", "kid": os.environ["APPLE_SIGNIN_KEY_ID"]},
                              **compact).encode())
    claims = _b64e(json.dumps({
        "iss": os.getenv("APPLE_TEAM_ID") or os.environ["APNS_TEAM_ID"],
        "iat": now, "exp": now + 300, "aud": ISSUER, "sub": audiences()[0],
    }, **compact).encode())
    signing_input = f"{header}.{claims}".encode()
    key = serialization.load_pem_private_key(_key_pem(), password=None)
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    return f"{header}.{claims}.{_b64e(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def exchange_code(code: str):
    """Apple's refresh token for a sign-in, or None when it cannot be had."""
    if not code or not signin_key_configured():
        return None
    resp = requests.post(TOKEN_URL, timeout=10, data={
        "client_id": audiences()[0], "client_secret": client_secret(),
        "code": code, "grant_type": "authorization_code",
    })
    if resp.status_code != 200:
        raise AuthError(f"code exchange refused: {resp.status_code} {resp.text[:200]}")
    return resp.json().get("refresh_token")


def revoke(refresh_token: str) -> bool:
    if not refresh_token or not signin_key_configured():
        return False
    resp = requests.post(REVOKE_URL, timeout=10, data={
        "client_id": audiences()[0], "client_secret": client_secret(),
        "token": refresh_token, "token_type_hint": "refresh_token",
    })
    return resp.status_code == 200
