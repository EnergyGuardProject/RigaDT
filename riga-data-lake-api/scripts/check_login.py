#!/usr/bin/env python3
"""End-to-end check of the Keycloak login against the Riga Data Lake API.

Logs in to Keycloak with your EnergyGuard username and password, then calls
the API with and without the token. The password is read from an environment
variable, never from this file, and neither the password nor the token is
ever printed.

Usage:
    read -s -p "EnergyGuard password: " KC_PASSWORD; echo; export KC_PASSWORD
    export KC_USERNAME=you@example.com
    python3 scripts/check_login.py

Optional variables (defaults in brackets):
    KC_ISSUER_URL  [https://keycloak.toolbox.epu.ntua.gr/realms/EnergyGuard]
    KC_CLIENT_ID   [riga-data-lake-api]  (needs "Direct access grants" enabled)
    API_URL        [https://dashboard.energy-guard.eu/riga-data-lake-api]
                   e.g. http://127.0.0.1:9007 when run on the server

Exit code is 0 only if every check passed.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ISSUER = os.getenv("KC_ISSUER_URL", "https://keycloak.toolbox.epu.ntua.gr/realms/EnergyGuard").rstrip("/")
CLIENT_ID = os.getenv("KC_CLIENT_ID", "riga-data-lake-api")
API = os.getenv("API_URL", "https://dashboard.energy-guard.eu/riga-data-lake-api").rstrip("/")
USERNAME = os.getenv("KC_USERNAME")
PASSWORD = os.getenv("KC_PASSWORD")

failures = 0


def check(name, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    return ok


def request(url, data=None, token=None):
    """Return (status, parsed_json_or_text). Never raises on HTTP errors."""
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, raw = r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode()
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def token_expiry(token):
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["exp"]


def main():
    if not USERNAME or not PASSWORD:
        sys.exit("Set KC_USERNAME and KC_PASSWORD first (see the usage at the top of this file).")

    print(f"Keycloak: {ISSUER}\nClient:   {CLIENT_ID}\nAPI:      {API}\nUser:     {USERNAME}\n")

    # 1. Log in
    status, body = request(
        f"{ISSUER}/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": CLIENT_ID, "username": USERNAME, "password": PASSWORD},
    )
    token = body.get("access_token") if isinstance(body, dict) else None
    if not check("Keycloak login (password grant)", status == 200 and token, f"HTTP {status}"):
        err = body if isinstance(body, dict) else {}
        print(f"\n  Keycloak said: {err.get('error')}: {err.get('error_description')}")
        hint = {
            "invalid_grant": "wrong username or password, or the account needs an action (e.g. password change)",
            "unauthorized_client": "'Direct access grants' is not enabled on the client",
            "invalid_client": "KC_CLIENT_ID does not match a Keycloak client",
        }.get(err.get("error"))
        if hint:
            print(f"  Likely cause: {hint}")
        sys.exit(1)
    left = int(token_expiry(token) - time.time())
    print(f"      token received ({len(token)} chars), valid for about {left} s\n")

    # 2. Authenticated calls
    status, body = request(f"{API}/whoami", token=token)
    ok = status == 200 and isinstance(body, dict) and body.get("authenticated") is True
    check("GET /whoami with token", ok, f"HTTP {status}")
    if ok:
        print(f"      signed in as {body.get('username')!r} ({body.get('name')}), expires {body.get('expires_at')}")

    status, body = request(f"{API}/georiga/suburbs?limit=1&include_geometry=false", token=token)
    rows = body.get("data") if isinstance(body, dict) else None
    check("GET /georiga/suburbs with token returns data", status == 200 and bool(rows),
          f"HTTP {status}, total={body.get('total') if isinstance(body, dict) else '?'}")

    status, body = request(f"{API}/cadastre/buildings?limit=1", token=token)
    rows = body.get("data") if isinstance(body, dict) else None
    check("GET /cadastre/buildings with token returns data", status == 200 and bool(rows), f"HTTP {status}")

    # 3. Access must be refused without a valid token
    status, _ = request(f"{API}/georiga/suburbs?limit=1")
    check("data endpoint WITHOUT token is refused", status == 401, f"HTTP {status}, expected 401")

    status, _ = request(f"{API}/georiga/suburbs?limit=1", token="not-a-real-token")
    check("data endpoint with a BAD token is refused", status == 401, f"HTTP {status}, expected 401")

    status, _ = request(f"{API}/docs")
    check("/docs is public", status == 200, f"HTTP {status}")

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
