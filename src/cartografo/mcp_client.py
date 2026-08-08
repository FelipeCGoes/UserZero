from contextlib import asynccontextmanager
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection
from langchain_mcp_adapters.tools import load_mcp_tools

from cartografo.guardrails import make_blocklist_interceptor
from cartografo.snapshot_capture import SnapshotCapture, make_snapshot_capture_interceptor

SERVER_NAME = "playwright"


def _connection(output_dir: Path, headless: bool) -> StdioConnection:
    args = ["-y", "@playwright/mcp@latest", "--output-dir", str(output_dir), "--isolated"]
    if headless:
        args.append("--headless")
    return StdioConnection(transport="stdio", command="npx", args=args)


@asynccontextmanager
async def playwright_mcp_tools(output_dir: Path, headless: bool, allow_destructive: bool):
    """Keeps ONE @playwright/mcp subprocess (one browser) alive for the whole
    exploration so navigation state survives across tool calls. `client.get_tools()`
    would open a fresh session — and a fresh browser — per call, which silently
    discards the current page between every step; the explicit `client.session(...)`
    context manager is what pins tool calls to a single long-lived session.
    """
    client = MultiServerMCPClient({SERVER_NAME: _connection(output_dir, headless)})
    snapshot_capture = SnapshotCapture()
    interceptors = [
        make_blocklist_interceptor(whitelist=allow_destructive),
        make_snapshot_capture_interceptor(snapshot_capture),
    ]
    async with client.session(SERVER_NAME) as session:
        tools = await load_mcp_tools(session, tool_interceptors=interceptors, server_name=SERVER_NAME)
        yield tools, snapshot_capture
