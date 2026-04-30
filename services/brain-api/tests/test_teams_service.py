"""
Unit tests for app/services/teams.py

Strategy: mock the AsyncSession so no DB is required.
Each test targets a specific guard or helper function.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.auth import CallerIdentity
from app.services import teams as svc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ORG_ID   = uuid.uuid4()
TEAM_ID  = uuid.uuid4()
USER_ID  = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def make_caller(
    user_id=USER_ID,
    org_id=ORG_ID,
    is_org_admin=False,
    principal_type="user",
    scopes=None,
) -> CallerIdentity:
    return CallerIdentity(
        user_id=user_id,
        principal_id=user_id,
        principal_type=principal_type,
        email="test@bedrock.local",
        org_id=org_id,
        is_org_admin=is_org_admin,
        scopes=scopes or ["read", "write"],
    )


def make_team(team_id=TEAM_ID, org_id=ORG_ID) -> MagicMock:
    team = MagicMock()
    team.id = team_id
    team.org_id = org_id
    team.name = "Test Team"
    team.slug = "test-team"
    return team


def make_membership(user_id=USER_ID, team_id=TEAM_ID, is_admin=False) -> MagicMock:
    m = MagicMock()
    m.user_id = user_id
    m.team_id = team_id
    m.is_admin = is_admin
    return m


def mock_db() -> AsyncMock:
    """
    AsyncMock where db.execute() returns a plain MagicMock result.
    This is critical: if the execute result is also an AsyncMock, its
    scalar_one_or_none() returns another AsyncMock (truthy), causing
    any while-loop that checks `if result is None` to spin forever.
    """
    db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = None
    exec_result.scalar_one.return_value = 0
    exec_result.all.return_value = []
    exec_result.scalars.return_value.all.return_value = []
    db.execute.return_value = exec_result
    return db


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

class TestSlugify:
    def test_basic(self):
        assert svc.slugify("Sales Team") == "sales-team"

    def test_special_chars_stripped(self):
        # &, /, ! are stripped; remaining spaces collapse to single -
        assert svc.slugify("R&D / Innovation!") == "rd-innovation"

    def test_extra_spaces_collapsed(self):
        assert svc.slugify("  AE   Team  ") == "ae-team"

    def test_already_slug(self):
        assert svc.slugify("sdr-team") == "sdr-team"

    def test_long_name_truncated(self):
        long = "a" * 100
        assert len(svc.slugify(long)) <= 64

    def test_numeric(self):
        assert svc.slugify("Team 42") == "team-42"


# ---------------------------------------------------------------------------
# ensure_unique_slug
# ---------------------------------------------------------------------------

class TestEnsureUniqueSlug:
    @pytest.mark.asyncio
    async def test_available_slug_returned_as_is(self):
        db = mock_db()
        # No existing team found → slug is free
        db.execute.return_value.scalar_one_or_none.return_value = None

        result = await svc.ensure_unique_slug(ORG_ID, "sdr-team", db)
        assert result == "sdr-team"

    @pytest.mark.asyncio
    async def test_collision_appends_counter(self):
        existing = make_team()
        # Need fresh result mock each execute call
        db = AsyncMock()
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": existing}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
        ]
        db.execute.side_effect = results

        result = await svc.ensure_unique_slug(ORG_ID, "sdr-team", db)
        assert result == "sdr-team-1"

    @pytest.mark.asyncio
    async def test_multiple_collisions(self):
        existing = make_team()
        db = AsyncMock()
        results = [
            MagicMock(**{"scalar_one_or_none.return_value": existing}),
            MagicMock(**{"scalar_one_or_none.return_value": existing}),
            MagicMock(**{"scalar_one_or_none.return_value": None}),
        ]
        db.execute.side_effect = results

        result = await svc.ensure_unique_slug(ORG_ID, "sdr-team", db)
        assert result == "sdr-team-2"


# ---------------------------------------------------------------------------
# require_org_admin
# ---------------------------------------------------------------------------

class TestRequireOrgAdmin:
    def test_org_admin_passes(self):
        caller = make_caller(is_org_admin=True)
        svc.require_org_admin(caller)  # should not raise

    def test_non_admin_raises_403(self):
        from fastapi import HTTPException
        caller = make_caller(is_org_admin=False)
        with pytest.raises(HTTPException) as exc:
            svc.require_org_admin(caller)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# require_same_org
# ---------------------------------------------------------------------------

class TestRequireSameOrg:
    @pytest.mark.asyncio
    async def test_same_org_passes(self):
        caller = make_caller(org_id=ORG_ID)
        team = make_team(org_id=ORG_ID)
        await svc.require_same_org(caller, team)  # should not raise

    @pytest.mark.asyncio
    async def test_different_org_raises_403(self):
        from fastapi import HTTPException
        caller = make_caller(org_id=ORG_ID)
        team = make_team(org_id=uuid.uuid4())  # different org
        with pytest.raises(HTTPException) as exc:
            await svc.require_same_org(caller, team)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_org_on_caller_raises_403(self):
        from fastapi import HTTPException
        caller = make_caller(org_id=None)
        team = make_team(org_id=ORG_ID)
        with pytest.raises(HTTPException) as exc:
            await svc.require_same_org(caller, team)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# require_team_admin_or_org_admin
# ---------------------------------------------------------------------------

class TestRequireTeamAdminOrOrgAdmin:
    @pytest.mark.asyncio
    async def test_org_admin_always_passes(self):
        db = mock_db()
        caller = make_caller(is_org_admin=True)
        await svc.require_team_admin_or_org_admin(caller, TEAM_ID, db)

    @pytest.mark.asyncio
    async def test_team_admin_passes(self):
        db = mock_db()
        db.execute.return_value.scalar_one_or_none.return_value = make_membership(is_admin=True)
        caller = make_caller(is_org_admin=False)
        await svc.require_team_admin_or_org_admin(caller, TEAM_ID, db)

    @pytest.mark.asyncio
    async def test_regular_member_raises_403(self):
        from fastapi import HTTPException
        db = mock_db()
        db.execute.return_value.scalar_one_or_none.return_value = make_membership(is_admin=False)
        caller = make_caller(is_org_admin=False)
        with pytest.raises(HTTPException) as exc:
            await svc.require_team_admin_or_org_admin(caller, TEAM_ID, db)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_non_member_raises_403(self):
        from fastapi import HTTPException
        db = mock_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        caller = make_caller(is_org_admin=False)
        with pytest.raises(HTTPException) as exc:
            await svc.require_team_admin_or_org_admin(caller, TEAM_ID, db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# require_team_member_or_org_admin
# ---------------------------------------------------------------------------

class TestRequireTeamMemberOrOrgAdmin:
    @pytest.mark.asyncio
    async def test_org_admin_passes(self):
        db = mock_db()
        caller = make_caller(is_org_admin=True)
        await svc.require_team_member_or_org_admin(caller, TEAM_ID, db)

    @pytest.mark.asyncio
    async def test_member_passes(self):
        db = mock_db()
        db.execute.return_value.scalar_one_or_none.return_value = make_membership()
        caller = make_caller(is_org_admin=False)
        await svc.require_team_member_or_org_admin(caller, TEAM_ID, db)

    @pytest.mark.asyncio
    async def test_non_member_raises_403(self):
        from fastapi import HTTPException
        db = mock_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        caller = make_caller(is_org_admin=False)
        with pytest.raises(HTTPException) as exc:
            await svc.require_team_member_or_org_admin(caller, TEAM_ID, db)
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# ensure_not_last_admin
# ---------------------------------------------------------------------------

class TestEnsureNotLastAdmin:
    @pytest.mark.asyncio
    async def test_multiple_admins_allows_removal(self):
        db = mock_db()
        # 2 admins total → safe to remove one
        db.execute.return_value.scalar_one.return_value = 2
        await svc.ensure_not_last_admin(TEAM_ID, USER_ID, db)  # should not raise

    @pytest.mark.asyncio
    async def test_last_admin_removal_blocked(self):
        from fastapi import HTTPException
        db = mock_db()
        # Only 1 admin, and the user being removed IS that admin
        db.execute.return_value.scalar_one.return_value = 1
        db.execute.return_value.scalar_one_or_none.return_value = make_membership(is_admin=True)

        with pytest.raises(HTTPException) as exc:
            await svc.ensure_not_last_admin(TEAM_ID, USER_ID, db)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_last_admin_count_but_user_not_admin(self):
        """Count=1 but the user being acted on is not the admin — should pass."""
        db = mock_db()
        db.execute.return_value.scalar_one.return_value = 1
        # User being removed is NOT an admin
        db.execute.return_value.scalar_one_or_none.return_value = make_membership(is_admin=False)

        await svc.ensure_not_last_admin(TEAM_ID, USER_ID, db)  # should not raise


# ---------------------------------------------------------------------------
# get_team_or_404 / get_membership_or_404
# ---------------------------------------------------------------------------

class TestGetOrRaise:
    @pytest.mark.asyncio
    async def test_get_team_found(self):
        db = mock_db()
        team = make_team()
        db.get.return_value = team
        result = await svc.get_team_or_404(TEAM_ID, db)
        assert result is team

    @pytest.mark.asyncio
    async def test_get_team_not_found_raises_404(self):
        from fastapi import HTTPException
        db = mock_db()
        db.get.return_value = None
        with pytest.raises(HTTPException) as exc:
            await svc.get_team_or_404(TEAM_ID, db)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_membership_not_found_raises_404(self):
        from fastapi import HTTPException
        db = mock_db()
        db.execute.return_value.scalar_one_or_none.return_value = None
        with pytest.raises(HTTPException) as exc:
            await svc.get_membership_or_404(USER_ID, TEAM_ID, db)
        assert exc.value.status_code == 404
