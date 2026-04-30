# bedrock-brain

A shared, RBAC-enforced Second Brain for sales orgs — built for humans and their AI agents.

---

## What is this?

Modern sales orgs run on institutional knowledge: playbooks, call notes, account research, competitive intel, objection handling, process docs. Today that knowledge is scattered across Notion, Google Drive, email threads, and individual Obsidian vaults — invisible to the team and inaccessible to the AI agents that are increasingly doing the work.

**bedrock-brain** solves this by giving every person and every agent in your org a single shared knowledge base with strict access control built in from the ground up.

### The core problem it solves

Tools like Obsidian with the MCP server make it easy for a single person to build a "Second Brain" that their AI agent can read and write. The moment you try to extend that to a team, you hit a wall: there's no concept of org membership, team-level visibility, or per-document sharing. Everything is either fully open or locked behind a filesystem path. Agents inherit whatever access the laptop they're running on has — which is all-or-nothing.

bedrock-brain replaces that with a purpose-built system where:

- Every note has a **visibility tier**: `private`, `team`, `org`, or `public`
- Every read and write is checked against a **role hierarchy**: owner > org admin > team membership > explicit ACL grant
- **AI agents are first-class principals** — each agent has its own identity and bearer token, inherits its owner's permissions but can never exceed them, and can be revoked instantly without touching the owner's account
- The **same API serves humans and agents** — the React UI and the MCP Gateway are both clients of the same FastAPI backend, so RBAC is enforced in one place

### Who it's for

A sales org of 10–3,000 people where:

- Individual reps want a private scratchpad that no one else can see
- Teams (SDR team, AE team, Sales Leaders) want shared resources visible only to members
- Org leadership wants org-wide resources (pricing, ICP docs, competitive battlecards) readable by everyone
- AI agents — one per rep, one per team, one for ops — need structured, permission-aware access to the same knowledge base

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│                     Clients                          │
│   brain-web (React/Vite)    MCP-compatible agents    │
└────────────┬─────────────────────────┬───────────────┘
             │ HTTPS/REST              │ MCP over SSE
             ▼                         ▼
┌────────────────────┐    ┌─────────────────────────┐
│    brain-api       │    │      mcp-gateway         │
│    (FastAPI)       │◄───│  (Starlette + MCP SSE)  │
│  RBAC · Notes CRUD │    │  agent-facing MCP tools  │
│  Teams · Agents    │    └─────────────────────────┘
└────────┬───────────┘
         │
   ┌─────┴──────┬────────────┐
   ▼            ▼            ▼
Postgres      Redis     S3-compatible
(RBAC/meta)  (cache)    (note content)
             
Auth: Keycloak (dev) → Okta (prod)
Sync: sync-bridge watches Obsidian vault → pushes to brain-api
```

**Stack:**

| Layer | Dev | Production |
|-------|-----|------------|
| Compute | Docker Compose | Nutanix NKP (Kubernetes) |
| Object storage | MinIO | Nutanix Objects / DO Spaces |
| Database | Postgres 16 (container) | Postgres on Nutanix NCI VM |
| Connection pooler | PgBouncer | PgBouncer |
| Cache | Redis 7 | Redis 7 |
| Auth | Keycloak 24 | Okta (OIDC-compatible) |
| Reverse proxy | — | nginx + Let's Encrypt |

---

## Visibility & permissions model

Every note is assigned one of four visibility tiers:

| Tier | Who can read |
|------|-------------|
| `private` | Owner only |
| `team` | Owner + all members of the assigned team |
| `org` | Everyone in the org |
| `public` | Anyone (including unauthenticated) |

On top of visibility tiers, any note can have **explicit ACL grants** — `read`, `write`, or `admin` — assigned to any user or agent principal. This lets you share a private note with a specific teammate without changing its visibility tier.

Permission resolution order (first match wins):

1. Owner → full access
2. Org admin → full access to org-scoped resources
3. Explicit ACL grant → grant level (read / write / admin)
4. Visibility tier check → read if tier allows

Agents are scoped to their owner's permissions and can never be granted more access than the owner has.

---

## Services

| Service | Path | Purpose |
|---------|------|---------|
| `brain-api` | `services/brain-api` | FastAPI — core RBAC, note CRUD, team management, agent tokens, S3 proxy |
| `mcp-gateway` | `services/mcp-gateway` | MCP SSE server — agent-facing tool interface, forwards to brain-api |
| `sync-bridge` | `services/sync-bridge` | Obsidian vault watcher — pushes .md file changes to brain-api |
| `brain-web` | `services/brain-web` | React + Vite — web UI for humans |

---

## Quick start (local dev)

```bash
git clone https://github.com/YOUR_USERNAME/bedrock-brain.git
cd bedrock-brain
make up
```

| Service | URL |
|---------|-----|
| Brain UI | http://localhost:3000 |
| Brain API docs | http://localhost:8000/docs |
| MCP Gateway | http://localhost:8001 |
| Keycloak admin | http://localhost:8080 (admin / admin) |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin) |

Test users (pre-seeded in Keycloak):

| User | Password | Role |
|------|----------|------|
| `dev-admin` | `admin123` | Org admin |
| `dev-user` | `user123` | Member |

---

## Project status

### ✅ Completed

- [x] **Monorepo scaffold** — full directory structure, all services stubbed, docker-compose, Makefile
- [x] **Git + GitHub** — initialized, remote linked, pushed to private repo
- [x] **Postgres schema** — `orgs`, `teams`, `team_members`, `users`, `agents`, `notes`, `note_acls` tables; enums; GIN indexes; `can_access_note()` PL/pgSQL function
- [x] **Auth system** — dual-path token resolution: OIDC JWT (Keycloak/Okta) + SHA-256 agent bearer tokens; `CallerIdentity` model unifying both principal types
- [x] **RBAC service** — `can_read()`, `can_write()`, `can_admin()` with full priority chain; `list_accessible_note_ids()` for bulk filtering
- [x] **Notes API** — full CRUD (create, read, update, delete) with RBAC guards + ACL grant/revoke endpoints; S3 content storage with path-encoded visibility
- [x] **Agents API** — agent creation (token shown once), listing, and revocation
- [x] **Team management API** — 10 endpoints: create/list/get/patch/delete teams, add/list/patch/remove members, list my teams; slug deduplication; last-admin guard
- [x] **MCP Gateway** — Starlette SSE server; agent bearer token extraction; `list_notes`, `read_note`, `write_note`, `update_note` tools wired to brain-api
- [x] **Sync Bridge** — Watchdog file system watcher; YAML frontmatter parsing for visibility/team/tags; handles create/modify/delete/rename events
- [x] **Brain Web** — React + Vite + Keycloak-js scaffold; nginx container for prod serving
- [x] **Keycloak realm** — `bedrock` realm with roles, groups (Sales Org / SDR Team / AE Team / Sales Leaders), clients, and test users; auto-imported on container start
- [x] **S3 abstraction** — boto3 with `endpoint_url` for MinIO (dev) / Nutanix Objects or DO Spaces (prod); `put_note`, `get_note`, `delete_note`, `move_note`
- [x] **Helm charts** — brain-api, mcp-gateway, sync-bridge, pgbouncer, redis, keycloak; HPA (2→20 / 3→30); PodDisruptionBudget
- [x] **Test suite** — 43 tests across `test_teams_service.py` and `test_teams_api.py`; fully mocked (no live DB/Redis/S3); FastAPI `dependency_overrides` for auth + DB
- [x] **CI pipeline** — GitHub Actions: lint (ruff), test (pytest), build-web (npm), helm-lint, docker-build (matrix, GHA layer cache), auto-deploy to DO
- [x] **.gitignore** — secrets, Python artifacts, test/coverage, Docker, Helm, OS files, IDEs
- [x] **DigitalOcean deployment** — Droplet bootstrap script, nginx + Let's Encrypt config, DO Spaces integration, deploy script with zero-downtime restart, full README

---

### 🔲 Open / In Progress

**Must-have for MVP**

- [ ] **Initial DO deployment** — provision Droplet, configure DO Spaces bucket, run `setup.sh`, issue SSL certs, go live
- [ ] **GitHub secrets for CI auto-deploy** — add `DO_DROPLET_IP`, `DO_SSH_KEY`, `DO_DEPLOY_USER` to repo secrets
- [ ] **GitHub branch protection** — require CI jobs to pass before any PR merges to `main`
- [ ] **Brain Web — core UI** — note editor (Markdown), note list with visibility filter, team browser, agent management panel; currently just a scaffold

**Post-MVP / hardening**

- [ ] **Alembic versioned migrations** — replace `001_initial_schema.sql` seed with proper Alembic revision files so schema changes can be applied without data loss
- [ ] **Rate limiting** — per-principal rate limits on brain-api and mcp-gateway (token bucket via Redis)
- [ ] **Agent token rotation + expiry** — token TTL, scheduled expiry, rotation endpoint
- [ ] **Audit log** — append-only log of every read/write/share action by user or agent (Postgres table + API endpoint)
- [ ] **Test coverage for notes + agents APIs** — current suite covers teams; notes and agents endpoints need the same mock-based test coverage
- [ ] **DO Managed Postgres** — migrate from container Postgres to a DO Managed Database cluster for production durability and backups
- [ ] **Okta migration** — swap Keycloak for Okta in production (config-only change; OIDC interface is identical)
- [ ] **NKP production deployment** — deploy Helm charts to Nutanix NKP cluster; configure Nutanix Objects endpoint; point at NCI Postgres VM
- [ ] **Observability** — structured JSON logging, Prometheus metrics endpoint on brain-api, Grafana dashboard for request latency and agent activity

---

## Deployment

| Environment | Guide |
|-------------|-------|
| Local dev | `make up` (Docker Compose) |
| DigitalOcean (MVP) | [`infra/digitalocean/README.md`](infra/digitalocean/README.md) |
| Nutanix NKP (prod) | `infra/helm/` — Helm charts for all services |

---

## Development commands

```bash
make up           # Start full local stack
make down         # Stop stack
make build        # Rebuild images (after code changes)
make migrate      # Run Alembic migrations
make test         # Run all tests
make lint         # Ruff lint all Python services
make logs         # Tail all service logs
make shell-api    # Shell into brain-api container
make web-dev      # Run brain-web in Vite hot-reload mode (outside Docker)
```
