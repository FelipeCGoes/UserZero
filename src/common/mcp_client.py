from contextlib import asynccontextmanager
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StdioConnection
from langchain_mcp_adapters.tools import load_mcp_tools

from common.guardrails import make_blocklist_interceptor
from common.snapshot_capture import SnapshotCapture, make_snapshot_capture_interceptor

SERVER_NAME = "playwright"

# @playwright/mcp splits "output" into two unrelated concepts: named files the agent
# explicitly asks to save (screenshots) resolve relative to the server process's cwd
# ("workspace"), while auto-generated diagnostics (page-*.yml snapshots, console-*.log)
# always resolve under --output-dir regardless of cwd. Pointing --output-dir at one
# subfolder and the subprocess cwd at another keeps both kinds out of src/ and out of
# each other's way, instead of the flat dump you get from leaving cwd unset (it then
# inherits whatever directory we launched Python from).
ARTIFACTS_SUBDIR = "mcp-artifacts"
SCREENSHOTS_SUBDIR = "screenshots"


def _connection(output_dir: Path, headless: bool) -> StdioConnection:
    # Absolute, because --output-dir is a string the *subprocess* resolves against its
    # own cwd (which we point at screenshots_dir below) — a relative path here would
    # get re-resolved from the wrong base and land nested inside screenshots_dir.
    output_dir = output_dir.resolve()
    artifacts_dir = output_dir / ARTIFACTS_SUBDIR
    screenshots_dir = output_dir / SCREENSHOTS_SUBDIR
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    args = ["-y", "@playwright/mcp@latest", "--output-dir", str(artifacts_dir), "--isolated"]
    if headless:
        args.append("--headless")
    return StdioConnection(transport="stdio", command="npx", args=args, cwd=str(screenshots_dir))


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
