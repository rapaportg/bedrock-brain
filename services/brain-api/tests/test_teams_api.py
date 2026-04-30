"""
Endpoint tests for app/api/v1/teams.py

Strategy:
  - Override get_db with a mock AsyncSession
  - Override resolve_caller with a test CallerIdentity
  - Use httpx.AsyncClient against the FastAPI app
  - Each test class isolates one endpoint and covers happy path + error cases
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import CallerIdentity
from app.db.session import get_db
from app.main import app

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

ORG_ID  = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEAM_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OTHER_USER_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

NOW = datetime.now(timezone.utc)


def org_admin_caller() -> CallerIdentity:
    return CallerIdentity(
        user_id=USER_ID, principal_id=USER_ID, principal_type="user",
        email="admin@bedrock.local", org_id=ORG_ID,
        is_org_admin=True, scopes=["read", "write"],
    )


def member_caller() -> CallerIdentity:
    return CallerIdentity(
        user_id=USER_ID, principal_id=USER_ID, principal_type="user",
        email="member@bedrock.local", org_id=ORG_ID,
        is_org_admin=False, scopes=["read", "write"],
    )


def make_team_model(**overrides) -> MagicMock:
    t = MagicMock()
    t.id = TEAM_ID
    t.org_id = ORG_ID
    t.name = overrides.get("name", "SDR Team")
    t.slug = overrides.get("slug", "sdr-team")
    t.created_at = NOW
    t.updated_at = NOW
    for k, v in overrides.items():
        setattr(t, k, v)
    return t


def make_membership_model(user_id=USER_ID, is_admin=True) -> MagicMock:
    m = MagicMock()
    m.user_id = user_id
    m.team_id = TEAM_ID
    m.is_admin = is_admin
    m.joined_at = NOW
    return m


def make_user_model(user_id=USER_ID) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    u.email = "member@bedrock.local"
    u.name = "Test Member"
    u.org_id = ORG_ID
    return u


# ---------------------------------------------------------------------------
# Test client factory
# ---------------------------------------------------------------------------

def override_caller(caller: CallerIdentity):
    """Return a dependency override function that injects the given caller."""
    from app.core.auth import resolve_caller
    async def _override():
        return caller
    return _override


def make_mock_db(
    get_return=None,
    execute_scalars=None,    # list of values for sequential scalar_one_or_none calls
    execute_scalar_one=None, # int for scalar_one (count)
    all_return=None,         # for result.all()
) -> AsyncMock:
    """
    Build a mock AsyncSession with common return value patterns.

    IMPORTANT: db.execute() must return a plain MagicMock (not AsyncMock).
    If the execute result is AsyncMock, scalar_one_or_none() returns another
    AsyncMock (truthy), causing infinite while-loops in slug/rbac helpers.
    """
    db = AsyncMock()
    db.get.return_value = get_return
    db.flush.return_value = None
    db.commit.return_value = None
    db.refresh.return_value = None
    db.delete.return_value = None

    if execute_scalars is not None:
        # Each call to db.execute() gets a fresh result object from the list
        results = []
        for val in execute_scalars:
            r = MagicMock()
            r.scalar_one_or_none.return_value = val
            r.scalar_one.return_value = 0
            r.all.return_value = []
            r.scalars.return_value.all.return_value = []
            results.append(r)
        db.execute.side_effect = results
    else:
        exec_result = MagicMock()
        exec_result.scalar_one_or_none.return_value = None
        exec_result.scalar_one.return_value = execute_scalar_one if execute_scalar_one is not None else 0
        exec_result.all.return_value = all_return if all_return is not None else []
        exec_result.scalars.return_value.all.return_value = []
        db.execute.return_value = exec_result

    return db


async def client_for(caller: CallerIdentity, db: AsyncMock) -> AsyncClient:
    from app.core.auth import resolve_caller
    app.dependency_overrides[resolve_caller] = override_caller(caller)
    app.dependency_overrides[get_db] = lambda: db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# POST /v1/teams — create team
# ---------------------------------------------------------------------------

class TestCreateTeam:
    @pytest.mark.asyncio
    async def test_org_admin_can_create(self):
        team = make_team_model()
        db = make_mock_db(
            execute_scalars=[None],  # slug is available
        )
        db.flush.return_value = None
        # After flush, team gets an id — simulate with the mock object
        db.refresh.side_effect = lambda obj: None

        with patch("app.api.v1.teams._team_response_with_count") as mock_count:
            mock_count.return_value = {
                "id": str(TEAM_ID), "org_id": str(ORG_ID),
                "name": "SDR Team", "slug": "sdr-team",
                "member_count": 1, "created_at": NOW.isoformat(), "updated_at": NOW.isoformat(),
            }
            async with await client_for(org_admin_caller(), db) as ac:
                resp = await ac.post("/v1/teams", json={"name": "SDR Team"})

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_non_org_admin_gets_403(self):
        db = make_mock_db()
        async with await client_for(member_caller(), db) as ac:
            resp = await ac.post("/v1/teams", json={"name": "SDR Team"})
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_caller_without_org_gets_400(self):
        caller = CallerIdentity(
            user_id=USER_ID, principal_id=USER_ID, principal_type="user",
            email="admin@bedrock.local", org_id=None,
            is_org_admin=True, scopes=["read", "write"],
        )
        db = make_mock_db(execute_scalars=[None])
        async with await client_for(caller, db) as ac:
            resp = await ac.post("/v1/teams", json={"name": "SDR Team"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# GET /v1/teams — list teams
# ---------------------------------------------------------------------------

class TestListTeams:
    @pytest.mark.asyncio
    async def test_org_admin_sees_all_teams(self):
        db = make_mock_db()
        db.execute.return_value.scalars.return_value.all.return_value = [make_team_model()]

        with patch("app.api.v1.teams._team_response_with_count") as mock_count:
            mock_count.return_value = {
                "id": str(TEAM_ID), "org_id": str(ORG_ID),
                "name": "SDR Team", "slug": "sdr-team",
                "member_count": 3, "created_at": NOW.isoformat(), "updated_at": NOW.isoformat(),
            }
            async with await client_for(org_admin_caller(), db) as ac:
                resp = await ac.get("/v1/teams")

        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_no_org_returns_empty(self):
        caller = CallerIdentity(
            user_id=USER_ID, principal_id=USER_ID, principal_type="user",
            email="x@x.com", org_id=None, is_org_admin=False, scopes=["read"],
        )
        db = make_mock_db()
        async with await client_for(caller, db) as ac:
            resp = await ac.get("/v1/teams")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /v1/teams/{team_id}
# ---------------------------------------------------------------------------

class TestGetTeam:
    @pytest.mark.asyncio
    async def test_team_member_can_get(self):
        team = make_team_model()
        db = make_mock_db(
            get_return=team,
            execute_scalars=[make_membership_model()],  # is_team_member → found
        )
        with patch("app.api.v1.teams._team_response_with_count") as mock_count:
            mock_count.return_value = {
                "id": str(TEAM_ID), "org_id": str(ORG_ID),
                "name": "SDR Team", "slug": "sdr-team",
                "member_count": 5, "created_at": NOW.isoformat(), "updated_at": NOW.isoformat(),
            }
            async with await client_for(member_caller(), db) as ac:
                resp = await ac.get(f"/v1/teams/{TEAM_ID}")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_team_not_found_returns_404(self):
        db = make_mock_db(get_return=None)
        async with await client_for(org_admin_caller(), db) as ac:
            resp = await ac.get(f"/v1/teams/{TEAM_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_non_member_of_different_org_gets_403(self):
        team = make_team_model(org_id=uuid.uuid4())  # different org
        db = make_mock_db(get_return=team)
        async with await client_for(member_caller(), db) as ac:
            resp = await ac.get(f"/v1/teams/{TEAM_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /v1/teams/{team_id}
# ---------------------------------------------------------------------------

class TestDeleteTeam:
    @pytest.mark.asyncio
    async def test_org_admin_can_delete(self):
        team = make_team_model()
        db = make_mock_db(get_return=team)
        async with await client_for(org_admin_caller(), db) as ac:
            resp = await ac.delete(f"/v1/teams/{TEAM_ID}")
        assert resp.status_code == 204
        db.delete.assert_called_once_with(team)

    @pytest.mark.asyncio
    async def test_non_admin_cannot_delete(self):
        team = make_team_model()
        db = make_mock_db(get_return=team)
        async with await client_for(member_caller(), db) as ac:
            resp = await ac.delete(f"/v1/teams/{TEAM_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/teams/{team_id}/members — add member
# ---------------------------------------------------------------------------

class TestAddMember:
    @pytest.mark.asyncio
    async def test_team_admin_can_add_member(self):
        team = make_team_model()
        user = make_user_model(OTHER_USER_ID)
        membership = make_membership_model(user_id=OTHER_USER_ID, is_admin=False)

        db = make_mock_db(get_return=team)
        # Calls: get_membership (caller is team admin), get user, get_membership for new member (not found)
        db.execute.return_value.scalar_one_or_none.side_effect = [
            make_membership_model(is_admin=True),  # caller is team admin
            None,                                   # new member not yet in team
        ]
        db.get.side_effect = [team, user]
        db.refresh.side_effect = lambda obj: setattr(obj, "joined_at", NOW) or None

        async with await client_for(member_caller(), db) as ac:
            resp = await ac.post(
                f"/v1/teams/{TEAM_ID}/members",
                json={"user_id": str(OTHER_USER_ID), "is_admin": False},
            )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_regular_member_cannot_add(self):
        team = make_team_model()
        db = make_mock_db(get_return=team)
        # Caller is a regular member (not admin)
        db.execute.return_value.scalar_one_or_none.return_value = make_membership_model(is_admin=False)

        async with await client_for(member_caller(), db) as ac:
            resp = await ac.post(
                f"/v1/teams/{TEAM_ID}/members",
                json={"user_id": str(OTHER_USER_ID), "is_admin": False},
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /v1/teams/{team_id}/members/{user_id} — remove member
# ---------------------------------------------------------------------------

class TestRemoveMember:
    @pytest.mark.asyncio
    async def test_member_can_remove_themselves(self):
        """Self-removal (leaving a team) is always allowed."""
        team = make_team_model()
        membership = make_membership_model(is_admin=False)

        db = make_mock_db(get_return=team)
        # is_team_member check for same_org passes; membership found for deletion
        db.execute.return_value.scalar_one_or_none.return_value = membership

        async with await client_for(member_caller(), db) as ac:
            resp = await ac.delete(f"/v1/teams/{TEAM_ID}/members/{USER_ID}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_last_admin_removal_blocked(self):
        team = make_team_model()
        admin_membership = make_membership_model(is_admin=True)

        db = AsyncMock()
        db.get.return_value = team
        db.flush.return_value = None
        db.commit.return_value = None
        db.delete.return_value = None

        # db.execute() must return plain MagicMock results — NOT AsyncMock.
        # AsyncMock.scalar_one_or_none() returns a coroutine (truthy but wrong type).
        def make_result(**kwargs):
            r = MagicMock()
            r.scalar_one_or_none.return_value = kwargs.get("scalar", None)
            r.scalar_one.return_value = kwargs.get("count", 0)
            return r

        db.execute.side_effect = [
            make_result(scalar=admin_membership),   # 1: require_team_admin_or_org_admin
            make_result(scalar=admin_membership),   # 2: get_membership_or_404
            make_result(count=1),                   # 3: ensure_not_last_admin count query
            make_result(scalar=admin_membership),   # 4: ensure_not_last_admin get_membership
        ]

        # Caller is a team admin trying to remove OTHER_USER_ID who is the last admin
        async with await client_for(member_caller(), db) as ac:
            resp = await ac.delete(f"/v1/teams/{TEAM_ID}/members/{OTHER_USER_ID}")
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /v1/users/me/teams
# ---------------------------------------------------------------------------

class TestMyTeams:
    @pytest.mark.asyncio
    async def test_returns_teams_list(self):
        team = make_team_model()
        membership = make_membership_model()

        db = make_mock_db()
        db.execute.return_value.all.return_value = [(membership, team)]

        async with await client_for(member_caller(), db) as ac:
            resp = await ac.get("/v1/users/me/teams")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["team_id"] == str(TEAM_ID)
        assert data[0]["is_admin"] is True

    @pytest.mark.asyncio
    async def test_no_teams_returns_empty_list(self):
        db = make_mock_db()
        db.execute.return_value.all.return_value = []

        async with await client_for(member_caller(), db) as ac:
            resp = await ac.get("/v1/users/me/teams")

        assert resp.status_code == 200
        assert resp.json() == []
