"""
MCP Gateway — the agent-facing MCP server.

Agents connect here using their bearer token. The gateway:
  1. Validates the token against brain-api (/v1/auth/me)
  2. Forwards tool calls to brain-api with the caller's identity
  3. Never returns data the caller is not permitted to see

Transport: SSE (Server-Sent Events) over HTTP on port 8001.
Agents connect via: http://mcp-gateway:8001/sse

Tools available:
  Note CRUD  : list_notes, read_note, write_note, update_note
  Navigation : search_notes, get_links, get_backlinks, get_related
"""

import structlog
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.config import settings
from app.tools.navigation import handle_navigation_tool, navigation_tools
from app.tools.notes import handle_note_tool, note_tools

log = structlog.get_logger()

_NOTE_TOOL_NAMES = {"list_notes", "read_note", "write_note", "update_note"}
_NAV_TOOL_NAMES = {"search_notes", "get_links", "get_backlinks", "get_related"}

# ---------------------------------------------------------------------------
# Build MCP server with unified tool registry
# ---------------------------------------------------------------------------

mcp_server = Server("bedrock-brain")


@mcp_server.list_tools()
async def list_tools():
    return note_tools() + navigation_tools()


@mcp_server.call_tool()
async def call_tool(name: str, arguments: dict, context=None) -> list[TextContent]:
    token = _extract_token_from_context(context)
    if not token:
        return [TextContent(type="text", text="Error: No authentication token provided.")]

    try:
        if name in _NOTE_TOOL_NAMES:
            return await handle_note_tool(name, arguments, token)
        elif name in _NAV_TOOL_NAMES:
            return await handle_navigation_tool(name, arguments, token)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except Exception as exc:
        return [TextContent(type="text", text=f"Error: {exc}")]


# ---------------------------------------------------------------------------
# SSE transport — each agent connection gets its own SSE stream
# ---------------------------------------------------------------------------

sse_transport = SseServerTransport("/messages/")


async def handle_sse(request: Request):
    """Entry point for agent connections."""
    token = _extract_token(request)
    if not token:
        from starlette.responses import Response
        return Response("Unauthorized", status_code=401)

    request.state.agent_token = token
    log.info("agent connected", path=request.url.path)

    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


async def handle_messages(request: Request):
    await sse_transport.handle_post_message(request.scope, request.receive, request._send)


async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def _extract_token_from_context(context) -> str | None:
    if context is None:
        return None
    try:
        return context.request_context.request.state.agent_token
    except AttributeError:
        return None


# ---------------------------------------------------------------------------
# Starlette app (wraps MCP server in HTTP)
# ---------------------------------------------------------------------------

app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
        Route("/healthz", endpoint=healthz),
    ]
)


if __name__ == "__main__":
    import uvicorn
    log.info("mcp-gateway starting", port=settings.mcp_gateway_port)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.mcp_gateway_port,
        reload=settings.environment == "development",
    )
