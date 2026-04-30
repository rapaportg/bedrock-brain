"""
Vault event handler — translates file system events into brain-api calls.
"""

from __future__ import annotations

import os
import re

import httpx
import structlog
from watchdog.events import (
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)

log = structlog.get_logger()

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (metadata, body)."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    fm_text = match.group(1)
    body = content[match.end():]
    meta: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    # Parse tags list if present
    if "tags" in meta:
        tags_raw = meta["tags"].strip("[]")
        meta["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return meta, body


class VaultEventHandler(FileSystemEventHandler):
    def __init__(self, api_url: str, agent_token: str):
        self._api_url = api_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {agent_token}"}
        # Local cache: file path → note_id (populated from brain-api on startup)
        self._path_to_note_id: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Startup scan
    # ------------------------------------------------------------------

    def initial_scan(self):
        """Walk the vault and upsert all .md files into brain-api."""
        from app.config import settings
        vault = settings.sync_vault_path
        log.info("scanning vault", path=vault)
        for root, _, files in os.walk(vault):
            for fname in files:
                if fname.endswith(".md"):
                    fpath = os.path.join(root, fname)
                    self._upsert_file(fpath)
        log.info("initial scan complete")

    # ------------------------------------------------------------------
    # Watchdog callbacks
    # ------------------------------------------------------------------

    def on_created(self, event: FileCreatedEvent):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._upsert_file(event.src_path)

    def on_modified(self, event: FileModifiedEvent):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._upsert_file(event.src_path)

    def on_deleted(self, event: FileDeletedEvent):
        if not event.is_directory and event.src_path.endswith(".md"):
            self._delete_file(event.src_path)

    def on_moved(self, event: FileMovedEvent):
        if not event.is_directory and event.dest_path.endswith(".md"):
            self._delete_file(event.src_path)
            self._upsert_file(event.dest_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _upsert_file(self, path: str):
        try:
            with open(path, encoding="utf-8") as f:
                raw = f.read()
        except OSError as e:
            log.warning("could not read file", path=path, error=str(e))
            return

        meta, body = _parse_frontmatter(raw)
        title = meta.get("title") or os.path.splitext(os.path.basename(path))[0]
        visibility = meta.get("visibility", "private")
        team_id = meta.get("team_id")
        tags = meta.get("tags", []) if isinstance(meta.get("tags"), list) else []

        note_id = self._path_to_note_id.get(path)

        try:
            if note_id:
                resp = httpx.patch(
                    f"{self._api_url}/v1/notes/{note_id}",
                    json={"title": title, "content": raw, "tags": tags},
                    headers=self._headers,
                    timeout=10,
                )
            else:
                payload: dict = {
                    "title": title,
                    "content": raw,
                    "visibility": visibility,
                    "tags": tags,
                }
                if team_id:
                    payload["team_id"] = team_id
                resp = httpx.post(
                    f"{self._api_url}/v1/notes",
                    json=payload,
                    headers=self._headers,
                    timeout=10,
                )
                if resp.status_code == 201:
                    self._path_to_note_id[path] = resp.json()["id"]

            resp.raise_for_status()
            log.info("synced", path=path, status=resp.status_code)
        except Exception as e:
            log.error("sync failed", path=path, error=str(e))

    def _delete_file(self, path: str):
        note_id = self._path_to_note_id.pop(path, None)
        if not note_id:
            return
        try:
            resp = httpx.delete(
                f"{self._api_url}/v1/notes/{note_id}",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            log.info("deleted", path=path, note_id=note_id)
        except Exception as e:
            log.error("delete failed", path=path, note_id=note_id, error=str(e))
