"""
Sync Bridge — watches an Obsidian vault directory and syncs changes to brain-api.

Behaviour:
  - On startup: scans vault and upserts any notes not yet in brain-api
  - On file create/modify: uploads new content via brain-api
  - On file delete: deletes the note from brain-api
  - New files default to visibility=private; change via brain-api or the Obsidian
    frontmatter field `visibility: team|org|public`

Frontmatter support:
  Each .md file may contain YAML frontmatter:
    ---
    visibility: team
    team_id: <uuid>
    tags: [sales, q2]
    ---
"""

import time

import structlog
from watchdog.observers import Observer

from app.config import settings
from app.watcher import VaultEventHandler

log = structlog.get_logger()


def main():
    log.info(
        "sync-bridge starting",
        vault=settings.sync_vault_path,
        api=settings.sync_api_url,
    )

    handler = VaultEventHandler(
        api_url=settings.sync_api_url,
        agent_token=settings.sync_agent_token,
    )
    handler.initial_scan()

    observer = Observer()
    observer.schedule(handler, path=settings.sync_vault_path, recursive=True)
    observer.start()

    log.info("watching vault", path=settings.sync_vault_path)
    try:
        while True:
            time.sleep(settings.sync_poll_interval_seconds)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
