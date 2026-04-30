"""
Link graph service — parses [[wikilinks]] from note content and keeps
the note_links table in sync.

Wikilink syntax supported:
  [[Note Title]]          — resolved by case-insensitive title match
  [[some-uuid-here]]      — resolved directly as a note UUID

Call sync_note_links() inside the same DB transaction as the note upsert
so links are always consistent with the saved content.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.note_link import NoteLink

WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")


def extract_wikilink_targets(content: str) -> list[str]:
    return WIKILINK_RE.findall(content)


async def _resolve_target(raw: str, db: AsyncSession) -> UUID | None:
    raw = raw.strip()
    try:
        return UUID(raw)
    except ValueError:
        pass
    result = await db.execute(
        select(Note.id).where(func.lower(Note.title) == raw.lower()).limit(1)
    )
    return result.scalar_one_or_none()


async def sync_note_links(note_id: UUID, content: str, db: AsyncSession) -> None:
    """
    Parse wikilinks from content, resolve them to note IDs, and replace
    all outbound links for this note in note_links.

    Must be called before db.commit() so links land in the same transaction.
    """
    raw_targets = extract_wikilink_targets(content)

    resolved: set[UUID] = set()
    for raw in raw_targets:
        target_id = await _resolve_target(raw, db)
        if target_id and target_id != note_id:
            resolved.add(target_id)

    # Replace outbound links atomically
    await db.execute(delete(NoteLink).where(NoteLink.source_id == note_id))
    for target_id in resolved:
        db.add(NoteLink(source_id=note_id, target_id=target_id))
