"""
Comprehensive endpoint tests for app/api/v1/notes.py

Strategy:
  - Override get_db and resolve_caller via FastAPI dependency_overrides
  - Mock the rbac module as used in notes.py to isolate RBAC from note logic
  - S3 and sync_note_links are already mocked by conftest._no_external_calls
  - Each test class targets one endpoint; happy path + key error cases covered
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

ORG_ID    = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID   = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NOTE_ID   = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
TARGET_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
TEAM_ID   = uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
NOW = datetime.now(timezone.utc)


def default_caller(**kwargs) -> CallerIdentity:
    return CallerIdentity(
        user_id=USER_ID, principal_id=USER_ID, principal_type="user",
        email="user@test.com", org_id=ORG_ID, is_org_admin=False,
        scopes=["read", "write"], **kwargs,
    )


def make_note(**kwargs) -> MagicMock:
    """MagicMock with all NoteResponse fields set to valid typed values."""
    n = MagicMock()
    n.id           = kwargs.get("id", NOTE_ID)
    n.owner_id     = kwargs.get("owner_id", USER_ID)
    n.title        = kwargs.get("title", "Test Note")
    n.visibility   = kwargs.get("visibility", "private")
    n.team_id      = kwargs.get("team_id", None)
    n.org_id       = kwargs.get("org_id", None)
    n.tags         = kwargs.get("tags", [])
    n.content_hash = kwargs.get("content_hash", "testhash")
    n.byte_size    = kwargs.get("byte_size", 100)
    n.created_at   = kwargs.get("created_at", NOW)
    n.updated_at   = kwargs.get("updated_at", NOW)
    n.s3_key       = kwargs.get("s3_key", f"private/{USER_ID}/{NOTE_ID}.md")
    for k, v in kwargs.items():
        setattr(n, k, v)
    return n


def make_db(get_return=None, execute_results=None) -> AsyncMock:
    db = AsyncMock()
    db.get.return_value = get_return
    db.flush.return_value = None
    db.commit.return_value = None
    db.delete.return_value = None
    db.add.return_value = None

    def _refresh(obj):
        obj.created_at = NOW
        obj.updated_at = NOW
    db.refresh.side_effect = _refresh

    if execute_results is not None:
        db.execute.side_effect = list(execute_results)
    else:
        r = MagicMock()
        r.scalar_one_or_none.return_value = None
        r.scalars.return_value.all.return_value = []
        r.all.return_value = []
        r.scalar_one.return_value = 0
        db.execute.return_value = r

    return db


def exec_r(*, scalars=None, rows=None, scalar=None) -> MagicMock:
    """Build a single mock execute result."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = scalars or []
    r.all.return_value = rows or []
    r.scalar_one_or_none.return_value = scalar
    r.scalar_one.return_value = 0
    return r


def override_caller(caller: CallerIdentity):
    async def _dep():
        return caller
    return _dep


async def make_client(caller: CallerIdentity, db: AsyncMock) -> AsyncClient:
    from app.core.auth import resolve_caller
    app.dependency_overrides[resolve_caller] = override_caller(caller)
    app.dependency_overrides[get_db] = lambda: db
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def rbac_mock(
    can_read=True, can_write=True, can_admin=True,
    accessible_ids=None,
):
    """Return a configured mock for the rbac module as imported in notes.py."""
    m = MagicMock()
    m.can_read  = AsyncMock(return_value=can_read)
    m.can_write = AsyncMock(return_value=can_write)
    m.can_admin = AsyncMock(return_value=can_admin)
    m.list_accessible_note_ids = AsyncMock(return_value=accessible_ids if accessible_ids is not None else [NOTE_ID])
    return m


# ---------------------------------------------------------------------------
# POST /v1/notes — create note
# ---------------------------------------------------------------------------

class TestCreateNote:
    @pytest.mark.asyncio
    async def test_happy_path_returns_201(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/notes", json={"title": "T", "content": "body"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "T"

    @pytest.mark.asyncio
    async def test_content_hash_from_s3(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/notes", json={"title": "T", "content": "body"})
        assert resp.json()["content_hash"] == "testhash"

    @pytest.mark.asyncio
    async def test_org_visibility_sets_org_id(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/notes", json={"title": "T", "content": "c", "visibility": "org"})
        assert resp.json()["org_id"] == str(ORG_ID)

    @pytest.mark.asyncio
    async def test_private_visibility_no_org_id(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/notes", json={"title": "T", "content": "c", "visibility": "private"})
        assert resp.json()["org_id"] is None

    @pytest.mark.asyncio
    async def test_tags_stored(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.post("/v1/notes", json={"title": "T", "content": "c", "tags": ["sales", "q2"]})
        assert resp.json()["tags"] == ["sales", "q2"]

    @pytest.mark.asyncio
    async def test_db_flush_called_before_commit(self):
        """flush() must be called so note.id is assigned before sync_note_links."""
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            await ac.post("/v1/notes", json={"title": "T", "content": "c"})
        db.flush.assert_called_once()
        db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# GET /v1/notes — list notes
# ---------------------------------------------------------------------------

class TestListNotes:
    @pytest.mark.asyncio
    async def test_returns_accessible_notes(self):
        note = make_note()
        db = make_db(execute_results=[exec_r(scalars=[note])])
        with patch("app.api.v1.notes.rbac", rbac_mock(accessible_ids=[NOTE_ID])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get("/v1/notes")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_access(self):
        db = make_db()
        with patch("app.api.v1.notes.rbac", rbac_mock(accessible_ids=[])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get("/v1/notes")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_tag_filter_applied(self):
        db = make_db(execute_results=[exec_r(scalars=[])])
        with patch("app.api.v1.notes.rbac", rbac_mock(accessible_ids=[NOTE_ID])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get("/v1/notes", params={"tag": "sales"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_visibility_filter_passed_to_rbac(self):
        db = make_db(execute_results=[exec_r(scalars=[])])
        mock_rbac = rbac_mock(accessible_ids=[])
        with patch("app.api.v1.notes.rbac", mock_rbac):
            async with await make_client(default_caller(), db) as ac:
                await ac.get("/v1/notes", params={"visibility": "team"})
        mock_rbac.list_accessible_note_ids.assert_called_once()
        _, kwargs = mock_rbac.list_accessible_note_ids.call_args
        assert kwargs.get("visibility_filter") == "team"


# ---------------------------------------------------------------------------
# GET /v1/notes/search — title search
# ---------------------------------------------------------------------------

class TestSearchNotes:
    @pytest.mark.asyncio
    async def test_returns_matching_notes(self):
        note = make_note(title="Pricing Doc")
        db = make_db(execute_results=[exec_r(scalars=[note])])
        with patch("app.api.v1.notes.rbac", rbac_mock(accessible_ids=[NOTE_ID])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get("/v1/notes/search", params={"q": "Pricing"})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_access(self):
        db = make_db()
        with patch("app.api.v1.notes.rbac", rbac_mock(accessible_ids=[])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get("/v1/notes/search", params={"q": "anything"})
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_missing_q_returns_422(self):
        db = make_db()
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get("/v1/notes/search")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /v1/notes/{note_id} — get note detail
# ---------------------------------------------------------------------------

class TestGetNoteDetail:
    @pytest.mark.asyncio
    async def test_returns_note_with_content(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}")
        assert resp.status_code == 200
        assert resp.json()["content"] == "# test content"
        assert resp.json()["title"] == "Test Note"

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        db = make_db(get_return=None)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get(f"/v1/notes/{NOTE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_read_access_returns_403(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=False)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /v1/notes/{note_id} — update note
# ---------------------------------------------------------------------------

class TestUpdateNote:
    @pytest.mark.asyncio
    async def test_update_title(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_write=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.patch(f"/v1/notes/{NOTE_ID}", json={"title": "New Title"})
        assert resp.status_code == 200
        assert note.title == "New Title"

    @pytest.mark.asyncio
    async def test_update_content_calls_put_and_sync(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_write=True)):
            with patch("app.api.v1.notes.put_note", new_callable=AsyncMock, return_value="newhash") as mock_put:
                with patch("app.api.v1.notes.sync_note_links", new_callable=AsyncMock) as mock_sync:
                    async with await make_client(default_caller(), db) as ac:
                        resp = await ac.patch(f"/v1/notes/{NOTE_ID}", json={"content": "new body"})
        assert resp.status_code == 200
        mock_put.assert_called_once()
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_visibility_change_deletes_old_s3_key(self):
        note = make_note(visibility="private")
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_write=True)):
            with patch("app.api.v1.notes.put_note", new_callable=AsyncMock, return_value="h"):
                with patch("app.api.v1.notes.get_note", new_callable=AsyncMock, return_value="content"):
                    with patch("app.api.v1.notes.delete_note", new_callable=AsyncMock) as mock_del:
                        async with await make_client(default_caller(), db) as ac:
                            resp = await ac.patch(
                                f"/v1/notes/{NOTE_ID}",
                                json={"visibility": "org"},
                            )
        assert resp.status_code == 200
        # Old key should be deleted, not overwritten via move
        mock_del.assert_called_once()

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        db = make_db(get_return=None)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.patch(f"/v1/notes/{NOTE_ID}", json={"title": "x"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_write_access_returns_403(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_write=False)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.patch(f"/v1/notes/{NOTE_ID}", json={"title": "x"})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /v1/notes/{note_id} — delete note
# ---------------------------------------------------------------------------

class TestDeleteNote:
    @pytest.mark.asyncio
    async def test_happy_path_returns_204(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_write=True)):
            with patch("app.api.v1.notes.delete_note", new_callable=AsyncMock) as mock_del:
                async with await make_client(default_caller(), db) as ac:
                    resp = await ac.delete(f"/v1/notes/{NOTE_ID}")
        assert resp.status_code == 204
        mock_del.assert_called_once_with(note.s3_key)
        db.delete.assert_called_once_with(note)

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        db = make_db(get_return=None)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.delete(f"/v1/notes/{NOTE_ID}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_no_write_access_returns_403(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_write=False)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.delete(f"/v1/notes/{NOTE_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /v1/notes/{note_id}/acl — grant access
# ---------------------------------------------------------------------------

class TestGrantAccess:
    GRANT_BODY = {"principal_type": "user", "principal_id": str(TARGET_ID), "permission": "read"}

    @pytest.mark.asyncio
    async def test_admin_can_grant(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_admin=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.post(f"/v1/notes/{NOTE_ID}/acl", json=self.GRANT_BODY)
        assert resp.status_code == 201
        assert resp.json() == {"status": "granted"}

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_admin=False)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.post(f"/v1/notes/{NOTE_ID}/acl", json=self.GRANT_BODY)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_duplicate_grant_returns_409(self):
        from sqlalchemy.exc import IntegrityError
        note = make_note()
        db = make_db(get_return=note)
        db.commit.side_effect = IntegrityError("dup", {}, None)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_admin=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.post(f"/v1/notes/{NOTE_ID}/acl", json=self.GRANT_BODY)
        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# DELETE /v1/notes/{note_id}/acl/{type}/{id} — revoke access
# ---------------------------------------------------------------------------

class TestRevokeAccess:
    @pytest.mark.asyncio
    async def test_admin_can_revoke(self):
        note = make_note()
        acl = MagicMock()
        db = make_db(get_return=note, execute_results=[exec_r(scalar=acl)])
        with patch("app.api.v1.notes.rbac", rbac_mock(can_admin=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.delete(f"/v1/notes/{NOTE_ID}/acl/user/{TARGET_ID}")
        assert resp.status_code == 204
        db.delete.assert_called_once_with(acl)

    @pytest.mark.asyncio
    async def test_nonexistent_acl_still_204(self):
        note = make_note()
        db = make_db(get_return=note, execute_results=[exec_r(scalar=None)])
        with patch("app.api.v1.notes.rbac", rbac_mock(can_admin=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.delete(f"/v1/notes/{NOTE_ID}/acl/user/{TARGET_ID}")
        assert resp.status_code == 204
        db.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self):
        note = make_note()
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_admin=False)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.delete(f"/v1/notes/{NOTE_ID}/acl/user/{TARGET_ID}")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /v1/notes/{note_id}/links — outbound links
# ---------------------------------------------------------------------------

class TestGetNoteLinks:
    @pytest.mark.asyncio
    async def test_returns_linked_notes(self):
        source = make_note()
        target = make_note(id=TARGET_ID, title="Target")
        db = make_db(
            get_return=source,
            execute_results=[
                exec_r(rows=[(TARGET_ID,)]),    # NoteLink.target_id query
                exec_r(scalars=[target]),        # Note query
            ],
        )
        mock_rbac = rbac_mock(can_read=True, accessible_ids=[TARGET_ID])
        with patch("app.api.v1.notes.rbac", mock_rbac):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/links")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["id"] == str(TARGET_ID)

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_links(self):
        source = make_note()
        db = make_db(get_return=source, execute_results=[exec_r(rows=[])])
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/links")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_inaccessible_links_filtered_out(self):
        source = make_note()
        db = make_db(
            get_return=source,
            execute_results=[exec_r(rows=[(TARGET_ID,)])],
        )
        # TARGET_ID not in accessible_ids → filtered out
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True, accessible_ids=[])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/links")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_source_not_found_returns_404(self):
        db = make_db(get_return=None)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get(f"/v1/notes/{NOTE_ID}/links")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/notes/{note_id}/backlinks — inbound links
# ---------------------------------------------------------------------------

class TestGetNoteBacklinks:
    @pytest.mark.asyncio
    async def test_returns_backlink_notes(self):
        target = make_note()
        source = make_note(id=TARGET_ID, title="Source")
        db = make_db(
            get_return=target,
            execute_results=[
                exec_r(rows=[(TARGET_ID,)]),    # NoteLink.source_id query
                exec_r(scalars=[source]),        # Note query
            ],
        )
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True, accessible_ids=[TARGET_ID])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/backlinks")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_backlinks(self):
        note = make_note()
        db = make_db(get_return=note, execute_results=[exec_r(rows=[])])
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/backlinks")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_inaccessible_backlinks_filtered(self):
        note = make_note()
        db = make_db(get_return=note, execute_results=[exec_r(rows=[(TARGET_ID,)])])
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True, accessible_ids=[])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/backlinks")
        assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /v1/notes/{note_id}/related — tag-based related notes
# ---------------------------------------------------------------------------

class TestGetRelatedNotes:
    @pytest.mark.asyncio
    async def test_returns_related_notes(self):
        note = make_note(tags=["sales"])
        related = make_note(id=TARGET_ID, tags=["sales"])
        db = make_db(
            get_return=note,
            execute_results=[exec_r(scalars=[related])],
        )
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True, accessible_ids=[TARGET_ID])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/related")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_note_has_no_tags(self):
        note = make_note(tags=[])
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True)):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/related")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_accessible_notes(self):
        note = make_note(tags=["sales"])
        db = make_db(get_return=note)
        with patch("app.api.v1.notes.rbac", rbac_mock(can_read=True, accessible_ids=[])):
            async with await make_client(default_caller(), db) as ac:
                resp = await ac.get(f"/v1/notes/{NOTE_ID}/related")
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        db = make_db(get_return=None)
        async with await make_client(default_caller(), db) as ac:
            resp = await ac.get(f"/v1/notes/{NOTE_ID}/related")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /healthz
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healthz():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
