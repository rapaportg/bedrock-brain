"""
Team service — business logic and permission guards for team operations.

Permission model:
  org-admin   → full access to all teams in their org
  team-admin  → manage members within their own teams, update team metadata
  member      → read team info and member list
  agent       → inherits owner's team memberships (read-only by default)

Guard functions raise HTTP 403 directly so endpoints stay clean.
"""

from __future__ import annotations

import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CallerIdentity
from app.models.team import Team, TeamMember
from app.models.user import Org


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Convert a team name to a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-")[:64]


async def ensure_unique_slug(org_id: uuid.UUID, slug: str, db: AsyncSession, exclude_id: uuid.UUID | None = None) -> str:
    """Append a counter suffix if the slug already exists in this org."""
    base = slug
    counter = 1
    while True:
        q = select(Team).where(Team.org_id == org_id, Team.slug == slug)
        if exclude_id:
            q = q.where(Team.id != exclude_id)
        result = await db.execute(q)
        if result.scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


# ---------------------------------------------------------------------------
# Fetch helpers
# ---------------------------------------------------------------------------

async def get_team_or_404(team_id: uuid.UUID, db: AsyncSession) -> Team:
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    return team


async def get_membership(user_id: uuid.UUID, team_id: uuid.UUID, db: AsyncSession) -> TeamMember | None:
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.user_id == user_id,
            TeamMember.team_id == team_id,
        )
    )
    return result.scalar_one_or_none()


async def get_membership_or_404(user_id: uuid.UUID, team_id: uuid.UUID, db: AsyncSession) -> TeamMember:
    member = await get_membership(user_id, team_id, db)
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found in team")
    return member


# ---------------------------------------------------------------------------
# Role checks (return bool, no side effects)
# ---------------------------------------------------------------------------

def _is_org_admin(caller: CallerIdentity) -> bool:
    return caller.is_org_admin


async def _is_team_admin(caller: CallerIdentity, team_id: uuid.UUID, db: AsyncSession) -> bool:
    membership = await get_membership(caller.user_id, team_id, db)
    return membership is not None and membership.is_admin


async def _is_team_member(caller: CallerIdentity, team_id: uuid.UUID, db: AsyncSession) -> bool:
    membership = await get_membership(caller.user_id, team_id, db)
    return membership is not None


# ---------------------------------------------------------------------------
# Permission guards (raise 403 on failure)
# ---------------------------------------------------------------------------

def require_org_admin(caller: CallerIdentity) -> None:
    if not _is_org_admin(caller):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Org admin access required",
        )


async def require_team_admin_or_org_admin(
    caller: CallerIdentity, team_id: uuid.UUID, db: AsyncSession
) -> None:
    if _is_org_admin(caller):
        return
    if await _is_team_admin(caller, team_id, db):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Team admin or org admin access required",
    )


async def require_team_member_or_org_admin(
    caller: CallerIdentity, team_id: uuid.UUID, db: AsyncSession
) -> None:
    if _is_org_admin(caller):
        return
    if await _is_team_member(caller, team_id, db):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Must be a member of this team",
    )


async def require_same_org(caller: CallerIdentity, team: Team) -> None:
    """Ensure the caller's org matches the team's org."""
    if caller.org_id is None or caller.org_id != team.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team belongs to a different org",
        )


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

async def ensure_not_last_admin(team_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession) -> None:
    """Prevent removing or demoting the last admin of a team."""
    result = await db.execute(
        select(func.count()).where(
            TeamMember.team_id == team_id,
            TeamMember.is_admin == True,  # noqa: E712
        )
    )
    admin_count = result.scalar_one()
    if admin_count <= 1:
        # Check if this user is the admin being removed/demoted
        membership = await get_membership(user_id, team_id, db)
        if membership and membership.is_admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot remove or demote the last admin of a team. Promote another member first.",
            )


async def ensure_org_exists(org_id: uuid.UUID, db: AsyncSession) -> Org:
    org = await db.get(Org, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Org not found")
    return org
