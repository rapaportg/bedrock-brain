"""
Notes API — CRUD + search.

All access decisions go through app.services.rbac before any S3 or DB operation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CallerIdentity, CurrentCaller
from app.core.s3 import build_s3_key, delete_note, get_note, move_note, put_note
from app.db.session import get_db
from app.models.note import Note, NoteACL
from app.services import rbac

router = APIRouter(prefix="/notes", tags=["notes"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NoteCreate(BaseModel):
    title: str
    content: str
    visibility: Literal["private", "team", "org", "public"] = "private"
    team_id: uuid.UUID | None = None
    tags: list[str] = []


class NoteUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    visibility: Literal["private", "team", "org", "public"] | None = None
    team_id: uuid.UUID | None = None
    tags: list[str] | None = None


class NoteResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    visibility: str
    team_id: uuid.UUID | None
    org_id: uuid.UUID | None
    tags: list[str]
    content_hash: str | None
    byte_size: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteDetailResponse(NoteResponse):
    content: str


class GrantRequest(BaseModel):
    principal_type: Literal["user", "agent"]
    principal_id: uuid.UUID
    permission: Literal["read", "write", "admin"]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(
    body: NoteCreate,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    note_id = uuid.uuid4()
    s3_key = build_s3_key(
        visibility=body.visibility,
        note_id=note_id,
        owner_id=caller.user_id,
        team_id=body.team_id,
    )
    content_hash = put_note(s3_key, body.content)

    note = Note(
        id=note_id,
        owner_id=caller.user_id,
        title=body.title,
        s3_key=s3_key,
        visibility=body.visibility,
        team_id=body.team_id,
        org_id=caller.org_id if body.visibility in ("org", "team") else None,
        tags=body.tags,
        content_hash=content_hash,
        byte_size=len(body.content.encode()),
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


@router.get("", response_model=list[NoteResponse])
async def list_notes(
    caller: CurrentCaller,
    visibility: str | None = Query(None),
    tag: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    accessible_ids = await rbac.list_accessible_note_ids(caller, db, visibility_filter=visibility)
    if not accessible_ids:
        return []

    query = select(Note).where(Note.id.in_(accessible_ids))
    if tag:
        query = query.where(Note.tags.any(tag))  # type: ignore[arg-type]

    result = await db.execute(query.order_by(Note.updated_at.desc()))
    return result.scalars().all()


@router.get("/{note_id}", response_model=NoteDetailResponse)
async def get_note_detail(
    note_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    note = await _get_or_404(note_id, db)
    await _require_read(caller, note, db)
    content = get_note(note.s3_key)
    return NoteDetailResponse(**NoteResponse.model_validate(note).model_dump(), content=content)


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: uuid.UUID,
    body: NoteUpdate,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    note = await _get_or_404(note_id, db)
    await _require_write(caller, note, db)

    if body.title is not None:
        note.title = body.title
    if body.tags is not None:
        note.tags = body.tags

    visibility_changed = body.visibility and body.visibility != note.visibility
    new_visibility = body.visibility or note.visibility
    new_team_id = body.team_id if body.team_id is not None else note.team_id

    if body.content is not None or visibility_changed:
        new_s3_key = build_s3_key(
            visibility=new_visibility,
            note_id=note.id,
            owner_id=note.owner_id,
            team_id=new_team_id,
        )
        current_content = get_note(note.s3_key) if body.content is None else body.content
        content_hash = put_note(new_s3_key, current_content)

        if visibility_changed and new_s3_key != note.s3_key:
            move_note(note.s3_key, new_s3_key)

        note.s3_key = new_s3_key
        note.content_hash = content_hash
        note.byte_size = len(current_content.encode())

    if body.visibility:
        note.visibility = body.visibility
        note.team_id = new_team_id
        note.org_id = caller.org_id if body.visibility in ("org", "team") else None

    await db.commit()
    await db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note_endpoint(
    note_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    note = await _get_or_404(note_id, db)
    await _require_write(caller, note, db)
    delete_note(note.s3_key)
    await db.delete(note)
    await db.commit()


@router.post("/{note_id}/acl", status_code=status.HTTP_201_CREATED)
async def grant_access(
    note_id: uuid.UUID,
    body: GrantRequest,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    note = await _get_or_404(note_id, db)
    await _require_admin(caller, note, db)

    acl = NoteACL(
        note_id=note.id,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        permission=body.permission,
        granted_by=caller.user_id,
    )
    db.add(acl)
    await db.commit()
    return {"status": "granted"}


@router.delete("/{note_id}/acl/{principal_type}/{principal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_access(
    note_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    note = await _get_or_404(note_id, db)
    await _require_admin(caller, note, db)

    result = await db.execute(
        select(NoteACL).where(
            NoteACL.note_id == note_id,
            NoteACL.principal_type == principal_type,
            NoteACL.principal_id == principal_id,
        )
    )
    acl = result.scalar_one_or_none()
    if acl:
        await db.delete(acl)
        await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_or_404(note_id: uuid.UUID, db: AsyncSession) -> Note:
    note = await db.get(Note, note_id)
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    return note


async def _require_read(caller: CallerIdentity, note: Note, db: AsyncSession) -> None:
    if not await rbac.can_read(caller, note, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def _require_write(caller: CallerIdentity, note: Note, db: AsyncSession) -> None:
    if not await rbac.can_write(caller, note, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")


async def _require_admin(caller: CallerIdentity, note: Note, db: AsyncSession) -> None:
    if not await rbac.can_admin(caller, note, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
