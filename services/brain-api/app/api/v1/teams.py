"""
Teams API

Endpoints:
  Teams (org-scoped):
    POST   /v1/teams                              Create a team           [org-admin]
    GET    /v1/teams                              List teams in caller's org [member+]
    GET    /v1/teams/{team_id}                    Get team detail         [team-member or org-admin]
    PATCH  /v1/teams/{team_id}                    Update name/slug        [team-admin or org-admin]
    DELETE /v1/teams/{team_id}                    Delete team             [org-admin]

  Membership:
    GET    /v1/teams/{team_id}/members            List members            [team-member or org-admin]
    POST   /v1/teams/{team_id}/members            Add member              [team-admin or org-admin]
    PATCH  /v1/teams/{team_id}/members/{user_id}  Update role             [team-admin or org-admin]
    DELETE /v1/teams/{team_id}/members/{user_id}  Remove member           [team-admin or org-admin]

  Convenience:
    GET    /v1/users/me/teams                     List my team memberships [self]
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentCaller
from app.db.session import get_db
from app.models.team import Team, TeamMember
from app.models.user import User
from app.services import teams as team_svc

router = APIRouter(tags=["teams"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    slug: str | None = Field(None, max_length=64, pattern=r"^[a-z0-9-]+$")


class TeamUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    slug: str | None = Field(None, max_length=64, pattern=r"^[a-z0-9-]+$")


class TeamResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    member_count: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemberSummary(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None
    is_admin: bool
    joined_at: datetime

    model_config = {"from_attributes": True}


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    is_admin: bool = False


class MemberUpdate(BaseModel):
    is_admin: bool


class MyTeamResponse(BaseModel):
    team_id: uuid.UUID
    team_name: str
    team_slug: str
    org_id: uuid.UUID
    is_admin: bool
    joined_at: datetime


# ---------------------------------------------------------------------------
# Team CRUD
# ---------------------------------------------------------------------------

@router.post("/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreate,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """Create a new team within the caller's org. Org admin only."""
    team_svc.require_org_admin(caller)

    if caller.org_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Caller has no org assigned")

    slug = body.slug or team_svc.slugify(body.name)
    slug = await team_svc.ensure_unique_slug(caller.org_id, slug, db)

    team = Team(org_id=caller.org_id, name=body.name, slug=slug)
    db.add(team)
    await db.flush()  # get team.id before adding member

    # Creator becomes the first team admin automatically
    db.add(TeamMember(user_id=caller.user_id, team_id=team.id, is_admin=True))
    await db.commit()
    await db.refresh(team)

    return await _team_response_with_count(team, db)


@router.get("/teams", response_model=list[TeamResponse])
async def list_teams(
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """
    List teams in the caller's org.
    Org admins see all teams. Regular members see only teams they belong to.
    """
    if caller.org_id is None:
        return []

    if caller.is_org_admin:
        result = await db.execute(
            select(Team)
            .where(Team.org_id == caller.org_id)
            .order_by(Team.name)
        )
        teams = result.scalars().all()
    else:
        result = await db.execute(
            select(Team)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(
                Team.org_id == caller.org_id,
                TeamMember.user_id == caller.user_id,
            )
            .order_by(Team.name)
        )
        teams = result.scalars().all()

    return [await _team_response_with_count(t, db) for t in teams]


@router.get("/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """Get team detail. Team members and org admins only."""
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)
    await team_svc.require_team_member_or_org_admin(caller, team_id, db)
    return await _team_response_with_count(team, db)


@router.patch("/teams/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: uuid.UUID,
    body: TeamUpdate,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """Update team name or slug. Team admin or org admin."""
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)
    await team_svc.require_team_admin_or_org_admin(caller, team_id, db)

    if body.name is not None:
        team.name = body.name
        # Auto-reslug if slug was not explicitly set
        if body.slug is None:
            new_slug = await team_svc.ensure_unique_slug(
                team.org_id, team_svc.slugify(body.name), db, exclude_id=team.id
            )
            team.slug = new_slug

    if body.slug is not None:
        slug = await team_svc.ensure_unique_slug(team.org_id, body.slug, db, exclude_id=team.id)
        team.slug = slug

    await db.commit()
    await db.refresh(team)
    return await _team_response_with_count(team, db)


@router.delete("/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """Delete a team. Org admin only. Also removes all memberships (cascade)."""
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)
    team_svc.require_org_admin(caller)

    await db.delete(team)
    await db.commit()


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

@router.get("/teams/{team_id}/members", response_model=list[MemberSummary])
async def list_members(
    team_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """List all members of a team."""
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)
    await team_svc.require_team_member_or_org_admin(caller, team_id, db)

    result = await db.execute(
        select(TeamMember, User)
        .join(User, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
        .order_by(TeamMember.is_admin.desc(), User.name)
    )
    rows = result.all()

    return [
        MemberSummary(
            user_id=member.user_id,
            email=user.email,
            name=user.name,
            is_admin=member.is_admin,
            joined_at=member.joined_at,
        )
        for member, user in rows
    ]


@router.post("/teams/{team_id}/members", response_model=MemberSummary, status_code=status.HTTP_201_CREATED)
async def add_member(
    team_id: uuid.UUID,
    body: MemberAdd,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """Add a user to a team. Team admin or org admin."""
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)
    await team_svc.require_team_admin_or_org_admin(caller, team_id, db)

    # Check user exists and belongs to the same org
    user = await db.get(User, body.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.org_id != team.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User belongs to a different org",
        )

    # Idempotent — if already a member, update their role instead
    existing = await team_svc.get_membership(body.user_id, team_id, db)
    if existing:
        existing.is_admin = body.is_admin
        await db.commit()
        await db.refresh(existing)
        return MemberSummary(
            user_id=user.id,
            email=user.email,
            name=user.name,
            is_admin=existing.is_admin,
            joined_at=existing.joined_at,
        )

    membership = TeamMember(user_id=body.user_id, team_id=team_id, is_admin=body.is_admin)
    db.add(membership)
    await db.commit()
    await db.refresh(membership)

    return MemberSummary(
        user_id=user.id,
        email=user.email,
        name=user.name,
        is_admin=membership.is_admin,
        joined_at=membership.joined_at,
    )


@router.patch("/teams/{team_id}/members/{user_id}", response_model=MemberSummary)
async def update_member_role(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberUpdate,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """Promote or demote a member. Team admin or org admin."""
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)
    await team_svc.require_team_admin_or_org_admin(caller, team_id, db)

    membership = await team_svc.get_membership_or_404(user_id, team_id, db)

    # Prevent demoting last admin
    if not body.is_admin and membership.is_admin:
        await team_svc.ensure_not_last_admin(team_id, user_id, db)

    membership.is_admin = body.is_admin
    await db.commit()

    user = await db.get(User, user_id)
    return MemberSummary(
        user_id=user.id,
        email=user.email,
        name=user.name,
        is_admin=membership.is_admin,
        joined_at=membership.joined_at,
    )


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove a member from a team. Team admin or org admin.
    Members may remove themselves (leave team).
    Cannot remove the last admin.
    """
    team = await team_svc.get_team_or_404(team_id, db)
    await team_svc.require_same_org(caller, team)

    # Allow self-removal (leave team); otherwise require admin
    if caller.user_id != user_id:
        await team_svc.require_team_admin_or_org_admin(caller, team_id, db)

    membership = await team_svc.get_membership_or_404(user_id, team_id, db)

    if membership.is_admin:
        await team_svc.ensure_not_last_admin(team_id, user_id, db)

    await db.delete(membership)
    await db.commit()


# ---------------------------------------------------------------------------
# Convenience — my teams
# ---------------------------------------------------------------------------

@router.get("/users/me/teams", response_model=list[MyTeamResponse])
async def my_teams(
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    """List all teams the caller belongs to."""
    result = await db.execute(
        select(TeamMember, Team)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.user_id == caller.user_id)
        .order_by(Team.name)
    )
    rows = result.all()

    return [
        MyTeamResponse(
            team_id=team.id,
            team_name=team.name,
            team_slug=team.slug,
            org_id=team.org_id,
            is_admin=membership.is_admin,
            joined_at=membership.joined_at,
        )
        for membership, team in rows
    ]


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def _team_response_with_count(team: Team, db: AsyncSession) -> TeamResponse:
    from sqlalchemy import func as sa_func
    result = await db.execute(
        select(sa_func.count()).where(TeamMember.team_id == team.id)
    )
    count = result.scalar_one()
    return TeamResponse(
        id=team.id,
        org_id=team.org_id,
        name=team.name,
        slug=team.slug,
        member_count=count,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )
