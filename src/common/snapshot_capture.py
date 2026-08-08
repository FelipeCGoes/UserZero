from dataclasses import dataclass, field

from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult, TextContent

# Tools whose result reflects the current page state (an accessibility snapshot),
# as opposed to side-channel tools like screenshots or network logs.
SNAPSHOT_BEARING_TOOLS = {
    "browser_snapshot", "browser_navigate", "browser_navigate_back",
    "browser_click", "browser_type", "browser_press_key",
    "browser_select_option", "browser_file_upload", "browser_wait_for",
    "browser_handle_dialog", "browser_drag",
}


@dataclass
class SnapshotCapture:
    """Holds the most recent accessibility-tree snapshot text seen from the browser,
    so `record_node` can fingerprint "the page as the agent currently sees it"
    without asking the LLM to copy/paste a large snapshot into a tool call."""

    text: str = ""
    url: str = field(default="")


def _extract_text(result) -> str:
    if isinstance(result, CallToolResult):
        return "\n".join(c.text for c in result.content if isinstance(c, TextContent))
    if isinstance(result, ToolMessage) and isinstance(result.content, str):
        return result.content
    return ""


def make_snapshot_capture_interceptor(capture: SnapshotCapture):
    async def interceptor(request: MCPToolCallRequest, handler):
        result = await handler(request)
        if request.name in SNAPSHOT_BEARING_TOOLS:
            text = _extract_text(result)
            if text:
                capture.text = text
        return result

    return interceptor
