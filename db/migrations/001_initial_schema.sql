-- =============================================================================
-- bedrock-brain — initial schema
-- Migration: 001_initial_schema.sql
-- Runs automatically via docker-entrypoint-initdb.d on first postgres start
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- for full-text search on titles/tags

-- =============================================================================
-- Enums
-- =============================================================================

CREATE TYPE visibility_level AS ENUM ('private', 'team', 'org', 'public');
CREATE TYPE permission_level AS ENUM ('read', 'write', 'admin');
CREATE TYPE principal_type   AS ENUM ('user', 'agent');

-- =============================================================================
-- Orgs
-- =============================================================================

CREATE TABLE orgs (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT        NOT NULL,
    slug        TEXT        UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Teams (belong to an org)
-- =============================================================================

CREATE TABLE teams (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID        NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    slug        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, slug)
);

-- =============================================================================
-- Users (synced from Keycloak/Okta via OIDC subject claim)
-- =============================================================================

CREATE TABLE users (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id     TEXT        UNIQUE NOT NULL, -- OIDC sub claim
    email           TEXT        UNIQUE NOT NULL,
    name            TEXT,
    org_id          UUID        REFERENCES orgs(id),
    is_org_admin    BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_external_id ON users(external_id);
CREATE INDEX idx_users_org_id      ON users(org_id);

-- =============================================================================
-- Team memberships
-- =============================================================================

CREATE TABLE team_members (
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    team_id     UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    is_admin    BOOLEAN     NOT NULL DEFAULT FALSE,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, team_id)
);

-- =============================================================================
-- Agents (registered by users; inherit owner's permissions, never exceed them)
-- =============================================================================

CREATE TABLE agents (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT        NOT NULL,
    token_hash      TEXT        UNIQUE NOT NULL,  -- bcrypt hash of the bearer token
    scopes          TEXT[]      NOT NULL DEFAULT '{"read"}',
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ
);

CREATE INDEX idx_agents_owner_id   ON agents(owner_id);
CREATE INDEX idx_agents_token_hash ON agents(token_hash);

-- =============================================================================
-- Notes (metadata only; content stored as S3 objects)
-- =============================================================================

CREATE TABLE notes (
    id              UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID                NOT NULL REFERENCES users(id),
    title           TEXT                NOT NULL DEFAULT '',
    s3_key          TEXT                UNIQUE NOT NULL,
    visibility      visibility_level    NOT NULL DEFAULT 'private',
    team_id         UUID                REFERENCES teams(id),   -- set when visibility='team'
    org_id          UUID                REFERENCES orgs(id),    -- set when visibility='org'
    tags            TEXT[]              NOT NULL DEFAULT '{}',
    content_hash    TEXT,               -- SHA-256 of content for change detection
    byte_size       BIGINT,
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),

    -- Enforce team_id presence when visibility=team
    CONSTRAINT chk_team_visibility CHECK (
        visibility != 'team' OR team_id IS NOT NULL
    ),
    -- Enforce org_id presence when visibility=org
    CONSTRAINT chk_org_visibility CHECK (
        visibility != 'org' OR org_id IS NOT NULL
    )
);

CREATE INDEX idx_notes_owner_id   ON notes(owner_id);
CREATE INDEX idx_notes_team_id    ON notes(team_id);
CREATE INDEX idx_notes_org_id     ON notes(org_id);
CREATE INDEX idx_notes_visibility ON notes(visibility);
CREATE INDEX idx_notes_title_trgm ON notes USING GIN (title gin_trgm_ops);
CREATE INDEX idx_notes_tags       ON notes USING GIN (tags);

-- =============================================================================
-- Note ACLs (individual permission grants that override visibility rules)
-- e.g. share a private note with a specific user or agent
-- =============================================================================

CREATE TABLE note_acls (
    id              UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id         UUID                NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    principal_type  principal_type      NOT NULL,
    principal_id    UUID                NOT NULL,  -- user.id or agent.id
    permission      permission_level    NOT NULL,
    granted_by      UUID                REFERENCES users(id),
    created_at      TIMESTAMPTZ         NOT NULL DEFAULT NOW(),
    UNIQUE (note_id, principal_type, principal_id)
);

CREATE INDEX idx_note_acls_note_id      ON note_acls(note_id);
CREATE INDEX idx_note_acls_principal    ON note_acls(principal_type, principal_id);

-- =============================================================================
-- Helper function: check if a user/agent can access a note
-- Used by the API service layer; can also back a Postgres RLS policy if desired
-- =============================================================================

CREATE OR REPLACE FUNCTION can_access_note(
    p_note_id       UUID,
    p_principal_type principal_type,
    p_principal_id  UUID,
    p_user_id       UUID,        -- always the human owner of an agent session
    p_required_perm permission_level DEFAULT 'read'
) RETURNS BOOLEAN LANGUAGE plpgsql STABLE AS $$
DECLARE
    v_note          notes%ROWTYPE;
    v_user          users%ROWTYPE;
    v_acl_perm      permission_level;
    v_perm_rank     INT;
    v_required_rank INT;
BEGIN
    SELECT * INTO v_note FROM notes WHERE id = p_note_id;
    IF NOT FOUND THEN RETURN FALSE; END IF;

    SELECT * INTO v_user FROM users WHERE id = p_user_id;
    IF NOT FOUND THEN RETURN FALSE; END IF;

    -- Rank permissions: read=1, write=2, admin=3
    v_required_rank := CASE p_required_perm
        WHEN 'read'  THEN 1
        WHEN 'write' THEN 2
        WHEN 'admin' THEN 3
    END;

    -- Owner always has full access
    IF v_note.owner_id = p_user_id THEN RETURN TRUE; END IF;

    -- Org admins have full access within their org
    IF v_user.is_org_admin AND v_user.org_id = v_note.org_id THEN RETURN TRUE; END IF;

    -- Check explicit ACL entry for this principal
    SELECT permission INTO v_acl_perm
    FROM note_acls
    WHERE note_id = p_note_id
      AND principal_type = p_principal_type
      AND principal_id = p_principal_id
    LIMIT 1;

    IF FOUND THEN
        v_perm_rank := CASE v_acl_perm
            WHEN 'read'  THEN 1
            WHEN 'write' THEN 2
            WHEN 'admin' THEN 3
        END;
        IF v_perm_rank >= v_required_rank THEN RETURN TRUE; END IF;
    END IF;

    -- For read-only checks, also honour visibility rules
    IF p_required_perm = 'read' THEN
        IF v_note.visibility = 'public' THEN RETURN TRUE; END IF;

        IF v_note.visibility = 'org'
           AND v_user.org_id = v_note.org_id THEN
            RETURN TRUE;
        END IF;

        IF v_note.visibility = 'team' AND EXISTS (
            SELECT 1 FROM team_members
            WHERE team_id = v_note.team_id AND user_id = p_user_id
        ) THEN
            RETURN TRUE;
        END IF;
    END IF;

    RETURN FALSE;
END;
$$;

-- =============================================================================
-- Seed data — default org for dev
-- =============================================================================

INSERT INTO orgs (id, name, slug) VALUES
    ('00000000-0000-0000-0000-000000000001', 'Bedrock Sales Org', 'bedrock');
