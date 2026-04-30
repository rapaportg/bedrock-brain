/**
 * Notes API client — thin wrapper around brain-api /v1/notes.
 *
 * Every call injects a fresh Bearer token via getToken() so silent refresh
 * happens automatically without the caller needing to think about it.
 *
 * URL routing:
 *   dev  (make web-dev)  → /api/v1/... proxied by Vite → brain-api /v1/...
 *   prod (Docker/build)  → VITE_API_BASE_URL/v1/... direct to brain-api
 */

import { getToken } from '../keycloak'

// When VITE_API_BASE_URL is set (Docker / prod), requests go directly to brain-api
// and brain-api routes are at /v1/...
// When empty (local `make web-dev`), the Vite dev proxy rewrites /api/... → /v1/...
// so we use /api/v1/... which becomes /v1/... after the rewrite.
const API_BASE = import.meta.env.VITE_API_BASE_URL
  ? `${import.meta.env.VITE_API_BASE_URL}/v1`  // direct: http://localhost:8000/v1
  : '/api/v1'                                    // proxied: /api/v1 → /v1 via Vite rewrite

async function req(method, path, body) {
  const token = await getToken()
  const opts = {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  }
  if (body !== undefined) {
    opts.body = JSON.stringify(body)
  }

  const res = await fetch(`${API_BASE}${path}`, opts)

  if (res.status === 204) return null

  const data = await res.json()
  if (!res.ok) {
    throw new Error(data?.detail || `HTTP ${res.status}`)
  }
  return data
}

// ── Notes CRUD ───────────────────────────────────────────────────────────────

/** List notes accessible to the caller, with optional visibility/tag filters. */
export function listNotes({ visibility, tag } = {}) {
  const params = new URLSearchParams()
  if (visibility) params.set('visibility', visibility)
  if (tag)        params.set('tag', tag)
  const qs = params.toString() ? `?${params}` : ''
  return req('GET', `/notes${qs}`)
}

/** Fetch a single note with its full content. */
export function getNote(noteId) {
  return req('GET', `/notes/${noteId}`)
}

/**
 * Create a new note.
 * @param {{ title, content, visibility, team_id?, tags? }} payload
 */
export function createNote(payload) {
  return req('POST', '/notes', payload)
}

/**
 * Partially update a note (title, content, visibility, tags).
 * Only include fields you want to change.
 */
export function updateNote(noteId, payload) {
  return req('PATCH', `/notes/${noteId}`, payload)
}

/** Delete a note permanently. */
export function deleteNote(noteId) {
  return req('DELETE', `/notes/${noteId}`)
}

// ── ACL ──────────────────────────────────────────────────────────────────────

/** Grant a user or agent access to a specific note. */
export function grantAccess(noteId, { principal_type, principal_id, permission }) {
  return req('POST', `/notes/${noteId}/acl`, { principal_type, principal_id, permission })
}

/** Revoke access previously granted. */
export function revokeAccess(noteId, principal_type, principal_id) {
  return req('DELETE', `/notes/${noteId}/acl/${principal_type}/${principal_id}`)
}
