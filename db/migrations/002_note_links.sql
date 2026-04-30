-- =============================================================================
-- bedrock-brain — note link graph
-- Migration: 002_note_links.sql
-- Tracks [[wikilink]] references between notes.
-- Populated and kept in sync by brain-api on every note create/update.
-- =============================================================================

CREATE TABLE note_links (
    source_id   UUID    NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_id   UUID    NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, target_id)
);

-- Fast inbound-link lookups (backlinks)
CREATE INDEX idx_note_links_target ON note_links(target_id);
-- Fast outbound-link lookups (covered by the PK index, but explicit for clarity)
CREATE INDEX idx_note_links_source ON note_links(source_id);
