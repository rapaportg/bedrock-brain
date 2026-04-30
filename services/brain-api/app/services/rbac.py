"""
RBAC service — single source of truth for access decisions.

Rules (in priority order):
  1. Note owner → full access
  2. Org admin → full access within their org
  3. Explicit ACL entry → grants specified permission level
  4. Visibility rules (read-only):
       public  → everyone
       org     → any user in the same org
       team    → any member of the note's team
       private → owner only (already covered by rule 1)

Agents never exceed their owner's permissions.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CallerIdentity
from app.models.note import Note, NoteACL
from app.models.team import TeamMember

PERM_RANK = {"read": 1, "write": 2, "admin": 3}


async def can_read(caller: CallerIdentity, note: Note, db: AsyncSession) -> bool:
    return await _check(caller, note, db, required="read")


async def can_write(caller: CallerIdentity, note: Note, db: AsyncSession) -> bool:
    return await _check(caller, note, db, required="write")


async def can_admin(caller: CallerIdentity, note: Note, db: AsyncSession) -> bool:
    return await _check(caller, note, db, required="admin")


async def _check(
    caller: CallerIdentity,
    note: Note,
    db: AsyncSession,
    required: str,
) -> bool:
    required_rank = PERM_RANK[required]

    # 1. Owner always has full access
    if note.owner_id == caller.user_id:
        return True

    # 2. Org admin has full access within their org
    if caller.is_org_admin and caller.org_id and caller.org_id == note.org_id:
        return True

    # 3. Explicit ACL — check both the human user and the agent principal
    principals_to_check = [(caller.principal_type, caller.principal_id)]
    if caller.principal_type == "agent":
        # Also check if the owner user has an ACL entry (agents inherit from owner's explicit grants)
        principals_to_check.append(("user", caller.user_id))

    for p_type, p_id in principals_to_check:
        result = await db.execute(
            select(NoteACL).where(
                NoteACL.note_id == note.id,
                NoteACL.principal_type == p_type,
                NoteACL.principal_id == p_id,
            )
        )
        acl = result.scalar_one_or_none()
        if acl and PERM_RANK[acl.permission] >= required_rank:
            return True

    # 4. Visibility rules (read-only)
    if required_rank <= PERM_RANK["read"]:
        if note.visibility == "public":
            return True

        if note.visibility == "org" and caller.org_id and caller.org_id == note.org_id:
            return True

        if note.visibility == "team" and note.team_id:
            member = await db.execute(
                select(TeamMember).where(
                    TeamMember.team_id == note.team_id,
                    TeamMember.user_id == caller.user_id,
                )
            )
            if member.scalar_one_or_none() is not None:
                return True

    return False


async def list_accessible_note_ids(
    caller: CallerIdentity,
    db: AsyncSession,
    visibility_filter: str | None = None,
) -> list[UUID]:
    """
    Return note IDs the caller can read.
    Used to build efficient WHERE id = ANY(...) queries.
    TODO: For large orgs, replace with a server-side CTE or materialized view.
    """
    from sqlalchemy import or_

    from app.models.note import Note

    conditions = [
        Note.owner_id == caller.user_id,
        Note.visibility == "public",
    ]

    if caller.org_id:
        conditions.append(
            (Note.visibility == "org") & (Note.org_id == caller.org_id)
        )

    # Team visibility — get user's team IDs first
    team_result = await db.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == caller.user_id)
    )
    team_ids = [row[0] for row in team_result.all()]
    if team_ids:
        conditions.append(
            (Note.visibility == "team") & Note.team_id.in_(team_ids)
        )

    # ACL grants — check the caller's own principal, and for agents also the owner
    # user (agents inherit owner's explicit ACL grants, matching the _check() logic).
    acl_principals = [(caller.principal_type, caller.principal_id)]
    if caller.principal_type == "agent":
        acl_principals.append(("user", caller.user_id))

    acl_note_ids: set[UUID] = set()
    for p_type, p_id in acl_principals:
        acl_result = await db.execute(
            select(NoteACL.note_id).where(
                NoteACL.principal_type == p_type,
                NoteACL.principal_id == p_id,
            )
        )
        acl_note_ids.update(row[0] for row in acl_result.all())

    if acl_note_ids:
        conditions.append(Note.id.in_(list(acl_note_ids)))

    query = select(Note.id).where(or_(*conditions))
    if visibility_filter:
        query = query.where(Note.visibility == visibility_filter)

    result = await db.execute(query)
    return [row[0] for row in result.all()]
