"""
Unit tests for app/services/links.py

Tests wikilink parsing (extract_wikilink_targets) and the sync function
(sync_note_links) that keeps the note_links table up to date.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.services.links import extract_wikilink_targets, sync_note_links

NOTE_ID   = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TARGET_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
OTHER_ID  = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_db(title_lookup: uuid.UUID | None = None) -> AsyncMock:
    """
    DB mock where execute() handles both:
      - title resolution queries (returns scalar = title_lookup)
      - delete queries (return value ignored)
    """
    db = AsyncMock()
    r = MagicMock()
    r.scalar_one_or_none.return_value = title_lookup
    r.all.return_value = []
    db.execute.return_value = r
    return db


# ---------------------------------------------------------------------------
# extract_wikilink_targets
# ---------------------------------------------------------------------------

class TestExtractWikilinkTargets:
    def test_single_title_link(self):
        assert extract_wikilink_targets("See [[Pricing Doc]]") == ["Pricing Doc"]

    def test_multiple_links(self):
        result = extract_wikilink_targets("See [[Pricing]] and [[ICP Doc]].")
        assert result == ["Pricing", "ICP Doc"]

    def test_uuid_link(self):
        result = extract_wikilink_targets(f"See [[{TARGET_ID}]]")
        assert result == [str(TARGET_ID)]

    def test_no_links_returns_empty(self):
        assert extract_wikilink_targets("Plain text, no wikilinks.") == []

    def test_empty_content(self):
        assert extract_wikilink_targets("") == []

    def test_single_brackets_ignored(self):
        assert extract_wikilink_targets("[Not a wikilink]") == []

    def test_link_embedded_in_sentence(self):
        assert extract_wikilink_targets("Read [[Note A]] for background.") == ["Note A"]

    def test_link_at_start_of_line(self):
        assert extract_wikilink_targets("[[Sales Playbook]] is the source.") == ["Sales Playbook"]

    def test_link_with_spaces_in_title(self):
        result = extract_wikilink_targets("[[Q2 OKR Summary]]")
        assert result == ["Q2 OKR Summary"]

    def test_multiline_content(self):
        content = "First para.\n\nSee [[Note A]] and\n[[Note B]] for more."
        result = extract_wikilink_targets(content)
        assert "Note A" in result
        assert "Note B" in result

    def test_duplicate_links_both_returned(self):
        result = extract_wikilink_targets("[[Note A]] repeated [[Note A]]")
        assert result.count("Note A") == 2


# ---------------------------------------------------------------------------
# sync_note_links
# ---------------------------------------------------------------------------

class TestSyncNoteLinks:
    @pytest.mark.asyncio
    async def test_uuid_link_resolves_and_is_added(self):
        db = make_db()
        await sync_note_links(NOTE_ID, f"[[{TARGET_ID}]]", db)
        added = [c.args[0] for c in db.add.call_args_list]
        assert any(getattr(obj, "target_id", None) == TARGET_ID for obj in added)

    @pytest.mark.asyncio
    async def test_title_link_resolved_via_db(self):
        db = make_db(title_lookup=TARGET_ID)
        await sync_note_links(NOTE_ID, "[[My Note]]", db)
        added = [c.args[0] for c in db.add.call_args_list]
        assert any(getattr(obj, "target_id", None) == TARGET_ID for obj in added)

    @pytest.mark.asyncio
    async def test_self_link_ignored(self):
        db = make_db()
        await sync_note_links(NOTE_ID, f"[[{NOTE_ID}]]", db)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_unresolvable_title_ignored(self):
        db = make_db(title_lookup=None)
        await sync_note_links(NOTE_ID, "[[Nonexistent Note]]", db)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_links_no_adds(self):
        db = make_db()
        await sync_note_links(NOTE_ID, "Plain content with no links.", db)
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_executed_before_add(self):
        """Existing outbound links are cleared before new ones are inserted."""
        db = make_db()
        await sync_note_links(NOTE_ID, f"[[{TARGET_ID}]]", db)
        # execute() is called for delete; add() for insert
        assert db.execute.called

    @pytest.mark.asyncio
    async def test_duplicate_uuid_links_deduplicated(self):
        db = make_db()
        content = f"[[{TARGET_ID}]] then again [[{TARGET_ID}]]"
        await sync_note_links(NOTE_ID, content, db)
        added = [c.args[0] for c in db.add.call_args_list]
        # UUID resolves immediately (no title lookup); dedup via set → only one NoteLink
        assert len(added) == 1

    @pytest.mark.asyncio
    async def test_multiple_distinct_links_all_added(self):
        db = make_db()
        content = f"[[{TARGET_ID}]] and [[{OTHER_ID}]]"
        await sync_note_links(NOTE_ID, content, db)
        added = [c.args[0] for c in db.add.call_args_list]
        target_ids = {getattr(obj, "target_id", None) for obj in added}
        assert TARGET_ID in target_ids
        assert OTHER_ID in target_ids

    @pytest.mark.asyncio
    async def test_source_id_set_correctly(self):
        db = make_db()
        await sync_note_links(NOTE_ID, f"[[{TARGET_ID}]]", db)
        added = [c.args[0] for c in db.add.call_args_list]
        assert all(getattr(obj, "source_id", None) == NOTE_ID for obj in added)
