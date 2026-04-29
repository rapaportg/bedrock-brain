"""
Auth middleware for brain-api.

Supports two token types:
  1. OIDC JWT (issued by Keycloak/Okta) — for human users
  2. Agent bearer token — hashed and stored in the agents table

Both resolve to a CallerIdentity, which the RBAC service uses to evaluate access.
"""

from __future__ import annotations

import hashlib
from typing import Annotated
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwk, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# JWKS cache (simple in-memory; production should use Redis TTL cache)
# ---------------------------------------------------------------------------
_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(settings.oidc_jwks_url, timeout=10)
            resp.raise_for_status()
            _jwks_cache = resp.json()
    return _jwks_cache


# ---------------------------------------------------------------------------
# Identity model — resolved for every authenticated request
# ---------------------------------------------------------------------------

class CallerIdentity(BaseModel):
    user_id: UUID          # always the human user (owner of agent if agent call)
    principal_id: UUID     # user_id for humans, agent.id for agents
    principal_type: str    # "user" | "agent"
    email: str
    org_id: UUID | None = None
    scopes: list[str] = []
    is_org_admin: bool = False


# ---------------------------------------------------------------------------
# Token resolution
# ---------------------------------------------------------------------------

async def resolve_caller(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> CallerIdentity:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")

    token = credentials.credentials

    # Try OIDC JWT first
    try:
        return await _resolve_oidc_token(token, db)
    except (JWTError, Exception):
        pass

    # Fall back to agent token
    return await _resolve_agent_token(token, db)


async def _resolve_oidc_token(token: str, db: AsyncSession) -> CallerIdentity:
    from sqlalchemy import select
    from app.models.user import User

    jwks = await _get_jwks()
    headers = jwt.get_unverified_header(token)
    key = next(
        (k for k in jwks["keys"] if k.get("kid") == headers.get("kid")),
        jwks["keys"][0],
    )
    public_key = jwk.construct(key)

    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=settings.oidc_audience,
        issuer=settings.oidc_issuer_url,
        options={"verify_exp": True},
    )

    external_id: str = payload["sub"]
    email: str = payload.get("email", "")

    # Upsert user on login
    result = await db.execute(select(User).where(User.external_id == external_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(external_id=external_id, email=email, name=payload.get("name"))
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return CallerIdentity(
        user_id=user.id,
        principal_id=user.id,
        principal_type="user",
        email=user.email,
        org_id=user.org_id,
        scopes=["read", "write"],
        is_org_admin=user.is_org_admin,
    )


async def _resolve_agent_token(token: str, db: AsyncSession) -> CallerIdentity:
    from sqlalchemy import select
    from app.models.agent import Agent
    from app.models.user import User

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(
        select(Agent).where(Agent.token_hash == token_hash, Agent.is_active == True)  # noqa: E712
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")

    owner = await db.get(User, agent.owner_id)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Agent owner not found")

    return CallerIdentity(
        user_id=owner.id,
        principal_id=agent.id,
        principal_type="agent",
        email=owner.email,
        org_id=owner.org_id,
        scopes=list(agent.scopes or ["read"]),
        is_org_admin=False,  # agents never inherit org-admin
    )


# ---------------------------------------------------------------------------
# Dependency shorthand
# ---------------------------------------------------------------------------

CurrentCaller = Annotated[CallerIdentity, Depends(resolve_caller)]
