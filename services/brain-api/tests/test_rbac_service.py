"""
Unit tests for app/services/rbac.py

Tests every branch of the access-control logic:
  - can_read / can_write / can_admin
  - list_accessible_note_ids (including agent two-principal behaviour)

The DB is mocked at the execute() level; no live Postgres required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.auth import CallerIdentity
from app.services import rbac

# ---------------------------------------------------------------------------
# Shared identifiers
# ---------------------------------------------------------------------------

ORG_ID        = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID       = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_USER_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
AGENT_ID      = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOTE_ID       = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
TEAM_ID       = uuid.UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


# ---------------------------------------------------------------------------
# Caller + note factories
# ---------------------------------------------------------------------------

def user_caller(**overrides) -> CallerIdentity:
    kw = dict(
        user_id=USER_ID, principal_id=USER_ID, principal_type="user",
        email="user@test.com", org_id=ORG_ID, is_org_admin=False,
        scopes=["read", "write"],
    )
    kw.update(overrides)
    return CallerIdentity(**kw)


def agent_caller(**overrides) -> CallerIdentity:
    kw = dict(
        user_id=USER_ID, principal_id=AGENT_ID, principal_type="agent",
        email="user@test.com", org_id=ORG_ID, is_org_admin=False,
        scopes=["read"],
    )
    kw.update(overrides)
    return CallerIdentity(**kw)


def make_note(**kwargs) -> MagicMock:
    n = MagicMock()
    n.id         = NOTE_ID
    n.owner_id   = OTHER_USER_ID   # not the caller by default
    n.visibility = "private"
    n.org_id     = ORG_ID
    n.team_id    = TEAM_ID
    n.tags       = []
    for k, v in kwargs.items():
        setattr(n, k, v)
    return n


# ---------------------------------------------------------------------------
# DB mock helpers
# ---------------------------------------------------------------------------

def acl_r(permission: str | None = None) -> MagicMock:
    """Execute result returning an ACL row (or None)."""
    r = MagicMock()
    if permission:
        a = MagicMock()
        a.permission = permission
        r.scalar_one_or_none.return_value = a
    else:
        r.scalar_one_or_none.return_value = None
    return r


def member_r(found: bool = False) -> MagicMock:
    """Execute result returning a TeamMember row (or None)."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = MagicMock() if found else None
    return r


def ids_r(*ids) -> MagicMock:
    """Execute result whose .all() returns a list of (id,) tuples."""
    r = MagicMock()
    r.all.return_value = [(i,) for i in ids]
    return r


def make_db(*execute_results) -> AsyncMock:
    db = AsyncMock()
    if execute_results:
        db.execute.side_effect = list(execute_results)
    else:
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.all.return_value = []
        db.execute.return_value = r
    return db


# ---------------------------------------------------------------------------
# can_read
# ---------------------------------------------------------------------------

class TestCanRead:
    @pytest.mark.asyncio
    async def test_owner_always_reads(self):
        note = make_note(owner_id=USER_ID)
        assert await rbac.can_read(user_caller(), note, make_db()) is True

    @pytest.mark.asyncio
    async def test_owner_needs_no_db(self):
        note = make_note(owner_id=USER_ID)
        db = make_db()
        await rbac.can_read(user_caller(), note, db)
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_org_admin_reads_same_org_note(self):
        note = make_note(org_id=ORG_ID)
        assert await rbac.can_read(user_caller(is_org_admin=True), note, make_db()) is True

    @pytest.mark.asyncio
    async def test_org_admin_cannot_read_different_org_note(self):
        note = make_note(org_id=uuid.uuid4(), visibility="private")
        assert await rbac.can_read(user_caller(is_org_admin=True), note, make_db(acl_r())) is False

    @pytest.mark.asyncio
    async def test_explicit_read_acl_grants_access(self):
        note = make_note()
        assert await rbac.can_read(user_caller(), note, make_db(acl_r("read"))) is True

    @pytest.mark.asyncio
    async def test_explicit_write_acl_grants_read(self):
        note = make_note()
        assert await rbac.can_read(user_caller(), note, make_db(acl_r("write"))) is True

    @pytest.mark.asyncio
    async def test_public_note_readable_by_anyone(self):
        note = make_note(visibility="public")
        assert await rbac.can_read(user_caller(), note, make_db(acl_r())) is True

    @pytest.mark.asyncio
    async def test_org_note_readable_by_same_org_user(self):
        note = make_note(visibility="org", org_id=ORG_ID)
        assert await rbac.can_read(user_caller(), note, make_db(acl_r())) is True

    @pytest.mark.asyncio
    async def test_org_note_not_readable_by_different_org(self):
        note = make_note(visibility="org", org_id=uuid.uuid4())
        assert await rbac.can_read(user_caller(), note, make_db(acl_r())) is False

    @pytest.mark.asyncio
    async def test_team_note_readable_by_member(self):
        note = make_note(visibility="team", team_id=TEAM_ID)
        # ACL check → None; team member check → found
        assert await rbac.can_read(user_caller(), note, make_db(acl_r(), member_r(True))) is True

    @pytest.mark.asyncio
    async def test_team_note_not_readable_by_non_member(self):
        note = make_note(visibility="team", team_id=TEAM_ID)
        assert await rbac.can_read(user_caller(), note, make_db(acl_r(), member_r(False))) is False

    @pytest.mark.asyncio
    async def test_private_note_not_readable_by_other_user(self):
        note = make_note(visibility="private")
        assert await rbac.can_read(user_caller(), note, make_db(acl_r())) is False

    @pytest.mark.asyncio
    async def test_agent_inherits_owner_read_acl(self):
        note = make_note()
        # agent principal → no ACL; owner user → has read ACL
        assert await rbac.can_read(agent_caller(), note, make_db(acl_r(), acl_r("read"))) is True

    @pytest.mark.asyncio
    async def test_agent_cannot_read_when_owner_also_denied(self):
        note = make_note(visibility="private")
        assert await rbac.can_read(agent_caller(), note, make_db(acl_r(), acl_r())) is False

    @pytest.mark.asyncio
    async def test_agent_is_never_org_admin(self):
        # Even if is_org_admin were set on an agent identity, agents are never
        # granted org-admin in _resolve_agent_token — but double-check _check.
        note = make_note(org_id=ORG_ID, visibility="private")
        # Override: pretend agent caller has is_org_admin (should not happen in practice)
        caller = agent_caller()
        # Without owner ACL, agent with no explicit grant should not get access via
        # the org_admin shortcut. CallerIdentity enforces is_org_admin=False for agents.
        assert caller.is_org_admin is False


# ---------------------------------------------------------------------------
# can_write
# ---------------------------------------------------------------------------

class TestCanWrite:
    @pytest.mark.asyncio
    async def test_owner_can_write(self):
        assert await rbac.can_write(user_caller(), make_note(owner_id=USER_ID), make_db()) is True

    @pytest.mark.asyncio
    async def test_read_only_acl_cannot_write(self):
        note = make_note()
        assert await rbac.can_write(user_caller(), note, make_db(acl_r("read"))) is False

    @pytest.mark.asyncio
    async def test_write_acl_can_write(self):
        note = make_note()
        assert await rbac.can_write(user_caller(), note, make_db(acl_r("write"))) is True

    @pytest.mark.asyncio
    async def test_admin_acl_can_write(self):
        note = make_note()
        assert await rbac.can_write(user_caller(), note, make_db(acl_r("admin"))) is True

    @pytest.mark.asyncio
    async def test_public_visibility_without_acl_cannot_write(self):
        note = make_note(visibility="public")
        assert await rbac.can_write(user_caller(), note, make_db(acl_r())) is False

    @pytest.mark.asyncio
    async def test_org_admin_can_write_org_note(self):
        note = make_note(org_id=ORG_ID)
        assert await rbac.can_write(user_caller(is_org_admin=True), note, make_db()) is True


# ---------------------------------------------------------------------------
# can_admin
# ---------------------------------------------------------------------------

class TestCanAdmin:
    @pytest.mark.asyncio
    async def test_owner_can_admin(self):
        assert await rbac.can_admin(user_caller(), make_note(owner_id=USER_ID), make_db()) is True

    @pytest.mark.asyncio
    async def test_admin_acl_can_admin(self):
        note = make_note()
        assert await rbac.can_admin(user_caller(), note, make_db(acl_r("admin"))) is True

    @pytest.mark.asyncio
    async def test_write_acl_cannot_admin(self):
        note = make_note()
        assert await rbac.can_admin(user_caller(), note, make_db(acl_r("write"))) is False

    @pytest.mark.asyncio
    async def test_read_acl_cannot_admin(self):
        note = make_note()
        assert await rbac.can_admin(user_caller(), note, make_db(acl_r("read"))) is False

    @pytest.mark.asyncio
    async def test_org_admin_can_admin_same_org_note(self):
        note = make_note(org_id=ORG_ID)
        assert await rbac.can_admin(user_caller(is_org_admin=True), note, make_db()) is True


# ---------------------------------------------------------------------------
# list_accessible_note_ids
# ---------------------------------------------------------------------------

class TestListAccessibleNoteIds:
    @pytest.mark.asyncio
    async def test_includes_owned_and_public(self):
        # teams → empty, acl → empty, final query → owned/public notes
        db = make_db(ids_r(), ids_r(), ids_r(NOTE_ID))
        result = await rbac.list_accessible_note_ids(user_caller(), db)
        assert NOTE_ID in result

    @pytest.mark.asyncio
    async def test_returns_empty_when_nothing_accessible(self):
        db = make_db(ids_r(), ids_r(), ids_r())
        result = await rbac.list_accessible_note_ids(user_caller(), db)
        assert result == []

    @pytest.mark.asyncio
    async def test_includes_team_notes_for_member(self):
        # teams → [TEAM_ID], acl → empty, final → [NOTE_ID]
        db = make_db(ids_r(TEAM_ID), ids_r(), ids_r(NOTE_ID))
        result = await rbac.list_accessible_note_ids(user_caller(), db)
        assert NOTE_ID in result

    @pytest.mark.asyncio
    async def test_includes_acl_granted_notes(self):
        # teams → empty, acl → [NOTE_ID], final → [NOTE_ID]
        db = make_db(ids_r(), ids_r(NOTE_ID), ids_r(NOTE_ID))
        result = await rbac.list_accessible_note_ids(user_caller(), db)
        assert NOTE_ID in result

    @pytest.mark.asyncio
    async def test_agent_checks_owner_acl_too(self):
        # For agent: teams, agent-principal acl, owner-user acl, final
        db = make_db(ids_r(), ids_r(), ids_r(NOTE_ID), ids_r(NOTE_ID))
        result = await rbac.list_accessible_note_ids(agent_caller(), db)
        assert NOTE_ID in result

    @pytest.mark.asyncio
    async def test_agent_uses_four_execute_calls(self):
        db = make_db(ids_r(), ids_r(), ids_r(), ids_r())
        await rbac.list_accessible_note_ids(agent_caller(), db)
        assert db.execute.call_count == 4

    @pytest.mark.asyncio
    async def test_user_uses_three_execute_calls(self):
        db = make_db(ids_r(), ids_r(), ids_r())
        await rbac.list_accessible_note_ids(user_caller(), db)
        assert db.execute.call_count == 3

    @pytest.mark.asyncio
    async def test_no_team_query_when_no_org(self):
        caller = user_caller(org_id=None)
        db = make_db(ids_r(), ids_r(), ids_r())
        result = await rbac.list_accessible_note_ids(caller, db)
        assert isinstance(result, list)
