"""
HTTP client for brain-api.
The caller's bearer token is forwarded on every request so brain-api
performs its own auth + RBAC check — the gateway never bypasses it.
"""

from __future__ import annotations

import httpx

from app.config import settings


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def list_notes(token: str, visibility: str | None = None, tag: str | None = None) -> list[dict]:
    params = {}
    if visibility:
        params["visibility"] = visibility
    if tag:
        params["tag"] = tag
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.get("/v1/notes", params=params, headers=_headers(token))
        resp.raise_for_status()
        return resp.json()


async def get_note(token: str, note_id: str) -> dict:
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.get(f"/v1/notes/{note_id}", headers=_headers(token))
        resp.raise_for_status()
        return resp.json()


async def create_note(token: str, title: str, content: str, visibility: str = "private", tags: list[str] | None = None) -> dict:
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.post(
            "/v1/notes",
            json={"title": title, "content": content, "visibility": visibility, "tags": tags or []},
            headers=_headers(token),
        )
        resp.raise_for_status()
        return resp.json()


async def update_note(token: str, note_id: str, **kwargs) -> dict:
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.patch(
            f"/v1/notes/{note_id}",
            json={k: v for k, v in kwargs.items() if v is not None},
            headers=_headers(token),
        )
        resp.raise_for_status()
        return resp.json()


async def search_notes(token: str, q: str, tag: str | None = None) -> list[dict]:
    params: dict = {"q": q}
    if tag:
        params["tag"] = tag
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.get("/v1/notes/search", params=params, headers=_headers(token))
        resp.raise_for_status()
        return resp.json()


async def get_note_links(token: str, note_id: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.get(f"/v1/notes/{note_id}/links", headers=_headers(token))
        resp.raise_for_status()
        return resp.json()


async def get_note_backlinks(token: str, note_id: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.get(f"/v1/notes/{note_id}/backlinks", headers=_headers(token))
        resp.raise_for_status()
        return resp.json()


async def get_related_notes(token: str, note_id: str) -> list[dict]:
    async with httpx.AsyncClient(base_url=settings.mcp_brain_api_url) as client:
        resp = await client.get(f"/v1/notes/{note_id}/related", headers=_headers(token))
        resp.raise_for_status()
        return resp.json()
