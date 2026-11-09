"""Keycloak bearer-token authentication for the Riga Data Lake API.

Every data endpoint requires a valid access token issued by the EnergyGuard
Keycloak realm (any authenticated realm user is allowed). Tokens are verified
locally against the realm's public signing keys (JWKS), so the API holds no
Keycloak secret. `/docs` and `/openapi.json` stay public so people can read
the API description and sign in from Swagger UI.

Settings (environment variables):
  KC_ISSUER_URL       Realm URL, e.g. https://keycloak.example.com/realms/MyRealm.
                      Required unless AUTH_DISABLED=true.
  KC_AUDIENCE         Optional. If set, the token's `aud` must contain it.
  KC_DOCS_CLIENT_ID   Optional. Public Keycloak client (PKCE) used by the
                      "Authorize" button in Swagger UI.
  AUTH_DISABLED       Set to "true" to turn authentication off (local dev only).
"""

import logging
import os

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jwt import PyJWKClient

load_dotenv()  # auth.py is imported before app.py loads .env

logger = logging.getLogger(__name__)

AUTH_DISABLED = os.getenv("AUTH_DISABLED", "").lower() == "true"
KC_ISSUER_URL = (os.getenv("KC_ISSUER_URL") or "").rstrip("/")
KC_AUDIENCE = os.getenv("KC_AUDIENCE") or None
KC_DOCS_CLIENT_ID = os.getenv("KC_DOCS_CLIENT_ID") or None

if AUTH_DISABLED:
    logger.warning("AUTH_DISABLED=true: the API is running WITHOUT authentication")
elif not KC_ISSUER_URL:
    raise RuntimeError(
        "Missing required environment variable: KC_ISSUER_URL "
        "(set AUTH_DISABLED=true to run without authentication, local dev only)"
    )

_OIDC = f"{KC_ISSUER_URL}/protocol/openid-connect"

# Swagger UI "Authorize" button (authorization code + PKCE, no client secret).
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{_OIDC}/auth",
    tokenUrl=f"{_OIDC}/token",
    auto_error=False,
)

# Not needed (and no issuer URL may be configured) when auth is disabled.
_jwks = None if AUTH_DISABLED else PyJWKClient(f"{_OIDC}/certs", cache_keys=True, timeout=10)


def _unauthorized(detail):
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_token(token):
    """Return the token's claims, or raise HTTPException (401 / 503)."""
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=KC_ISSUER_URL,
            audience=KC_AUDIENCE,
            options={
                "require": ["exp", "iss"],
                "verify_aud": KC_AUDIENCE is not None,
            },
        )
    except jwt.PyJWKClientConnectionError:
        logger.exception("Could not fetch Keycloak signing keys")
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.PyJWTError:
        raise _unauthorized("Invalid token")


def require_user(token: str = Depends(oauth2_scheme)):
    """FastAPI dependency: only authenticated EnergyGuard realm users pass."""
    if AUTH_DISABLED:
        return None
    if not token:
        raise _unauthorized("Missing bearer token")
    return verify_token(token)
