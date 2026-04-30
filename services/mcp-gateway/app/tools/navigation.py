"""
MCP navigation tools — Obsidian-style graph traversal for agents:
  - search_notes   : trigram title search across accessible notes
  - get_links      : outbound [[wikilinks]] from a note
  - get_backlinks  : inbound wikilinks pointing to a note
  - get_related    : notes sharing tags with a note

All tools enforce the caller's RBAC via brain-api — the gateway
forwards the bearer token and never bypasses access control.
"""

from __future__ import annotations

import json

from mcp.types import TextContent, Tool

from app import brain_client


def navigation_tools() -> list[Tool]:
    return [
        Tool(
            name="search_notes",
            description=(
                "Search for notes by title using trigram similarity. "
                "Returns notes accessible to the caller ranked by relevance. "
                "Use this to find a note when you know part of its title."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search term to match against note titles.",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Optional tag filter applied on top of the title search.",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_links",
            description=(
                "Return the notes that a given note links to via [[wikilinks]] "
                "(outbound graph edges). Only notes the caller can read are returned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "UUID of the source note."},
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="get_backlinks",
            description=(
                "Return all notes that link TO a given note (inbound backlinks). "
                "Useful for discovering which notes reference a topic or document. "
                "Only notes the caller can read are returned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "UUID of the target note."},
                },
                "required": ["note_id"],
            },
        ),
        Tool(
            name="get_related",
            description=(
                "Return notes that share at least one tag with the given note, "
                "ordered by recency. Useful for discovering thematically connected "
                "content without following explicit links."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "UUID of the note to find related content for."},
                },
                "required": ["note_id"],
            },
        ),
    ]


async def handle_navigation_tool(name: str, arguments: dict, token: str) -> list[TextContent]:
    if name == "search_notes":
        results = await brain_client.search_notes(
            token,
            q=arguments["query"],
            tag=arguments.get("tag"),
        )
        return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]

    elif name == "get_links":
        links = await brain_client.get_note_links(token, arguments["note_id"])
        return [TextContent(type="text", text=json.dumps(links, indent=2, default=str))]

    elif name == "get_backlinks":
        backlinks = await brain_client.get_note_backlinks(token, arguments["note_id"])
        return [TextContent(type="text", text=json.dumps(backlinks, indent=2, default=str))]

    elif name == "get_related":
        related = await brain_client.get_related_notes(token, arguments["note_id"])
        return [TextContent(type="text", text=json.dumps(related, indent=2, default=str))]

    return [TextContent(type="text", text=f"Unknown navigation tool: {name}")]
