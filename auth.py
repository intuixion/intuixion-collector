"""
API authentication — Clerk session JWTs for users, a static service key for scripts.

Every /v1 route requires a Principal. Platform-admin routes (audit queue, metrics,
public-corpus ingest) additionally require require_admin. Tenant identity comes from
the token's active Clerk organisation, never from the request body.

Environment:
    CLERK_ISSUER              Clerk Frontend API URL, e.g. https://<app>.clerk.accounts.dev
                              (JWKS is fetched from {issuer}/.well-known/jwks.json)
    CLERK_AUTHORIZED_PARTIES  Comma-separated origins allowed in the azp claim, e.g.
                              https://app.intuixion.ai,http://localhost:3000 (recommended)
    ADMIN_USER_IDS            Comma-separated Clerk user IDs with platform-admin access.
                              Customer org admins are NOT platform admins.
    SERVICE_API_KEY           Static bearer token for eval/CI scripts (admin, no tenant).
"""

import hmac
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


@dataclass(frozen=True)
class Principal:
    user_id: str
    org_id: Optional[str]   # active Clerk organisation = tenant; None = public corpus only
    is_admin: bool


_bearer = HTTPBearer(auto_error=False)


def _env_list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


@lru_cache(maxsize=4)
def _jwks_client(issuer: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{issuer}/.well-known/jwks.json", cache_keys=True, lifespan=3600)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def require_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)) -> Principal:
    if creds is None:
        raise _unauthorized("Missing bearer token.")
    token = creds.credentials

    service_key = os.getenv("SERVICE_API_KEY", "")
    if service_key and hmac.compare_digest(token.encode(), service_key.encode()):
        return Principal(user_id="service", org_id=None, is_admin=True)

    issuer = os.getenv("CLERK_ISSUER", "").rstrip("/")
    if not issuer:
        raise _unauthorized("User authentication is not configured.")

    try:
        signing_key = _jwks_client(issuer).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
            leeway=5,
        )
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired token.")

    parties = _env_list("CLERK_AUTHORIZED_PARTIES")
    if parties and claims.get("azp") not in parties:
        raise _unauthorized("Token was issued for a different origin.")

    # Session token v1 uses org_id; v2 nests the active organisation under "o"
    org_id = claims.get("org_id") or (claims.get("o") or {}).get("id")
    user_id = claims["sub"]
    return Principal(user_id=user_id, org_id=org_id, is_admin=user_id in _env_list("ADMIN_USER_IDS"))


def require_admin(principal: Principal = Depends(require_user)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return principal
