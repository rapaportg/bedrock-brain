"""
Endpoint tests for app/api/v1/agents.py

Covers all three endpoints:
  POST   /v1/agents
  GET    /v1/agents
  DELETE /v1/agents/{agent_id}
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CallerIdentity
from app.db.session import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

USER_ID  = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
AGENT_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OTHER_USER_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime.now(timezone.utc)


def default_caller(**kwargs) -> CallerIdentity:
    return CallerIdentity(
        user_id=USER_ID, principal_id=USER_ID, principal_type="user",
        email="user@test.com", org_id=None, is_org_admin=False,
        scopes=["read", "write"], **kwargs,
    )


def make_agent(**kwargs) -> MagicMock:
    a = MagicMock()
    a.id           = kwargs.get("id", AGENT_ID)
    a.owner_id     = kwargs.get("owner_id", USER_ID)
    a.name         = kwargs.get("name", "Test Agent")
    a.scopes       = kwargs.get("scopes", ["read"])
    a.is_active    = kwargs.get("is_active", True)
    a.created_at   = NOW
    a.last_seen_at = None
    for k, v in kwargs.items():
        setattr(a, k, v)
    return a


def make_db(get_return=None, scalars_return=None) -> AsyncMock:
    db = AsyncMock()
    db.get.return_value = get_return
    db.commit.return_value = None
    db.add.return_value = None

    # refresh simulates DB populating server_default and default columns
    def _refresh(obj):
        for attr, val in [("id", AGENT_ID), ("is_active", True), ("created_at", NOW)]:
            if getattr(obj, attr, None) is None:
                setattr(obj, attr, val)
    db.refresh.side_effect = _refresh

    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars_return or []
    db.execute.return_value = r

    return db


def override_caller(caller: CallerIdentity):
    async def _dep():
        return caller
    return _dep


async def make_client(caller: CallerIdentity, db: AsyncMock) -> AsyncClient:
    from app.core.auth import resolve_caller
    app.dependency_overrides[resolve_caller] = override_caller(caller)
    app.dependency_overrides[get_db] = lambda: db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# POST /v1/agents — create agent
# ---------------------------------------------------------------------------

class TestCreateAgent:
    @pytest.mark.asyncio
    async def test_returns_201_with_token(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/agents", json={"name": "My Bot", "scopes": ["read"]})
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert len(data["token"]) > 0

    @pytest.mark.asyncio
    async def test_token_is_url_safe_and_unique_across_calls(self):
        db1, db2 = make_db(), make_db()
        async with await make_client(default_caller(), db1) as ac:
            r1 = await ac.post("/v1/agents", json={"name": "A"})
        async with await make_client(default_caller(), db2) as ac:
            r2 = await ac.post("/v1/agents", json={"name": "B"})
        assert r1.json()["token"] != r2.json()["token"]

    @pytest.mark.asyncio
    async def test_stored_hash_differs_from_plaintext_token(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/agents", json={"name": "Agent"})
        token = resp.json()["token"]
        stored_agent = db.add.call_args[0][0]
        assert stored_agent.token_hash != token

    @pytest.mark.asyncio
    async def test_defaults_to_read_scope(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/agents", json={"name": "Agent"})
        assert resp.json()["scopes"] == ["read"]

    @pytest.mark.asyncio
    async def test_write_scope_accepted(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/agents", json={"name": "Agent", "scopes": ["read", "write"]})
        assert resp.status_code == 201
        assert "write" in resp.json()["scopes"]

    @pytest.mark.asyncio
    async def test_owner_id_set_from_caller(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/agents", json={"name": "Agent"})
        assert resp.json()["owner_id"] == str(USER_ID)

    @pytest.mark.asyncio
    async def test_token_not_present_in_list_response(self):
        """The token is only returned at creation; subsequent list calls must not include it."""
        agent = make_agent()
        db = make_db(scalars_return=[agent])
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get("/v1/agents")
        assert "token" not in resp.json()[0]


# ---------------------------------------------------------------------------
# GET /v1/agents — list agents
# ---------------------------------------------------------------------------

class TestListAgents:
    @pytest.mark.asyncio
    async def test_returns_caller_agents(self):
        agent = make_agent()
        db = make_db(scalars_return=[agent])
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get("/v1/agents")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == str(AGENT_ID)

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_none(self):
        db = make_db(scalars_return=[])
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get("/v1/agents")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_multiple_agents_returned(self):
        agents = [make_agent(id=uuid.uuid4(), name=f"Agent {i}") for i in range(3)]
        db = make_db(scalars_return=agents)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get("/v1/agents")
        assert len(resp.json()) == 3


# ---------------------------------------------------------------------------
# DELETE /v1/agents/{agent_id} — revoke agent
# ---------------------------------------------------------------------------

class TestRevokeAgent:
    @pytest.mark.asyncio
    async def test_owner_can_revoke(self):
        agent = make_agent()
        db = make_db(get_return=agent)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.delete(f"/v1/agents/{AGENT_ID}")
        assert resp.status_code == 204
        assert agent.is_active is False
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_is_soft_delete(self):
        """Agent row is not deleted — only is_active is set to False."""
        agent = make_agent()
        db = make_db(get_return=agent)
        async with await make_client(default_caller(), db) as ac:
            await ac.delete(f"/v1/agents/{AGENT_ID}")
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        db = make_db(get_return=None)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.delete(f"/v1/agents/{AGENT_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_wrong_owner_returns_404(self):
        """Callers cannot revoke agents owned by someone else."""
        agent = make_agent(owner_id=OTHER_USER_ID)
        db = make_db(get_return=agent)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.delete(f"/v1/agents/{AGENT_ID}")
        assert resp.status_code == 404
        assert agent.is_active is True  # not modified
