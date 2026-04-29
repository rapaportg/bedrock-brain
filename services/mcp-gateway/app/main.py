"""
MCP Gateway — the agent-facing MCP server.

Agents connect here using their bearer token. The gateway:
  1. Validates the token against brain-api (/v1/auth/me)
  2. Forwards tool calls to brain-api with the caller's identity
  3. Never returns data the caller is not permitted to see

Transport: SSE (Server-Sent Events) over HTTP on port 8001.
Agents connect via: http://mcp-gateway:8001/sse
"""

import asyncio

import structlog
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route

from app.config import settings
from app.tools.notes import register_note_tools

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Build MCP server and register tools
# ---------------------------------------------------------------------------

mcp_server = Server("bedrock-brain")
register_note_tools(mcp_server)

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

    # Attach token to request state so tools can use it
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


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.query_params.get("token")


# ---------------------------------------------------------------------------
# Starlette app (wraps MCP server in HTTP)
# ---------------------------------------------------------------------------

app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=sse_transport.handle_post_message),
        Route("/healthz", endpoint=lambda r: __import__("starlette.responses", fromlist=["JSONResponse"]).JSONResponse({"status": "ok"})),
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
