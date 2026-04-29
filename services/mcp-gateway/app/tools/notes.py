"""
MCP tools exposed to agents:
  - list_notes    : browse notes the caller can read
  - read_note     : fetch full content of a note
  - write_note    : create a new note
  - update_note   : update title, content, or tags of an existing note
  - search_notes  : filter notes by tag or visibility scope

All tools require a valid bearer token passed in the MCP request context.
If the token is invalid or the caller lacks permission, brain-api returns 403
and the tool surfaces that as an error — never silently filters.
"""

from __future__ import annotations

import json

from mcp.server import Server
from mcp.types import TextContent, Tool

from app import brain_client


def register_note_tools(server: Server) -> None:

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_notes",
                description="List notes the current agent has access to. Optionally filter by visibility scope or tag.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "visibility": {
                            "type": "string",
                            "enum": ["private", "team", "org", "public"],
                            "description": "Filter by visibility scope. Omit to return all accessible notes.",
                        },
                        "tag": {
                            "type": "string",
                            "description": "Filter notes that have this tag.",
                        },
                    },
                },
            ),
            Tool(
                name="read_note",
                description="Read the full markdown content of a note by its ID.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string", "description": "UUID of the note to read."},
                    },
                    "required": ["note_id"],
                },
            ),
            Tool(
                name="write_note",
                description="Create a new note in the second brain.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string", "description": "Markdown content."},
                        "visibility": {
                            "type": "string",
                            "enum": ["private", "team", "org", "public"],
                            "default": "private",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of tags.",
                        },
                    },
                    "required": ["title", "content"],
                },
            ),
            Tool(
                name="update_note",
                description="Update the title, content, or tags of an existing note you have write access to.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["note_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict, context=None) -> list[TextContent]:
        # Extract bearer token from context
        token = _get_token(context)
        if not token:
            return [TextContent(type="text", text="Error: No authentication token provided.")]

        try:
            if name == "list_notes":
                notes = await brain_client.list_notes(
                    token,
                    visibility=arguments.get("visibility"),
                    tag=arguments.get("tag"),
                )
                return [TextContent(type="text", text=json.dumps(notes, indent=2, default=str))]

            elif name == "read_note":
                note = await brain_client.get_note(token, arguments["note_id"])
                return [TextContent(type="text", text=note.get("content", ""))]

            elif name == "write_note":
                note = await brain_client.create_note(
                    token,
                    title=arguments["title"],
                    content=arguments["content"],
                    visibility=arguments.get("visibility", "private"),
                    tags=arguments.get("tags", []),
                )
                return [TextContent(type="text", text=f"Note created: {note['id']}")]

            elif name == "update_note":
                note = await brain_client.update_note(
                    token,
                    note_id=arguments["note_id"],
                    title=arguments.get("title"),
                    content=arguments.get("content"),
                    tags=arguments.get("tags"),
                )
                return [TextContent(type="text", text=f"Note updated: {note['id']}")]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

        except Exception as exc:
            return [TextContent(type="text", text=f"Error: {exc}")]


def _get_token(context) -> str | None:
    """Extract bearer token from MCP request context."""
    if context is None:
        return None
    # The token is injected into the request state by handle_sse in main.py
    # MCP context carries the request's lifespan state
    try:
        return context.request_context.request.state.agent_token
    except AttributeError:
        return None
