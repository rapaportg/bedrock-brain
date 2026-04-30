"""
Note CRUD tools exposed to agents via MCP.

Exports note_tools() and handle_note_tool() so main.py can compose them
with navigation tools under a single list_tools / call_tool handler.
"""

from __future__ import annotations

import json

from mcp.types import TextContent, Tool

from app import brain_client


def note_tools() -> list[Tool]:
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
            description="Create a new note in the second brain. Wikilinks ([[Note Title]]) in the content are resolved automatically.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Markdown content. Use [[Note Title]] to link to other notes."},
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


async def handle_note_tool(name: str, arguments: dict, token: str) -> list[TextContent]:
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

    return [TextContent(type="text", text=f"Unknown note tool: {name}")]


def register_note_tools(server):
    """Kept for backwards compatibility — main.py uses the unified handler instead."""
    pass
