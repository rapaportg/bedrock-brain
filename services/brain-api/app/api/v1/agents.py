"""
Agent management API — register and manage agent tokens.
Agents are owned by users and inherit (but never exceed) owner permissions.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.core.auth import CurrentCaller
from app.db.session import get_db
from app.models.agent import Agent

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str
    scopes: list[Literal["read", "write"]] = ["read"]


class AgentResponse(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    scopes: list[str]
    is_active: bool
    created_at: datetime
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class AgentCreateResponse(AgentResponse):
    token: str  # only returned once at creation time


@router.post("", response_model=AgentCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    body: AgentCreate,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    agent = Agent(
        owner_id=caller.user_id,
        name=body.name,
        token_hash=token_hash,
        scopes=body.scopes,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    return AgentCreateResponse(**AgentResponse.model_validate(agent).model_dump(), token=token)


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Agent).where(Agent.owner_id == caller.user_id).order_by(Agent.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_agent(
    agent_id: uuid.UUID,
    caller: CurrentCaller,
    db: AsyncSession = Depends(get_db),
):
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.owner_id != caller.user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent.is_active = False
    await db.commit()
