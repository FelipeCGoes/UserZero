import re

from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from mcp.types import CallToolResult, TextContent

# Read-mostly exploration: block actions with irreversible or external side effects
# unless the caller explicitly whitelists them. Matched against the tool's own
# argument text (element name, typed value, url) since Playwright MCP acts on
# accessibility-tree refs, not raw selectors we control.
DEFAULT_BLOCKLIST = [
    r"\bdelet(e|ar)\b", r"\bexclu(ir|ído)\b", r"\bremov(e|er)\b",
    r"\bpa(y|gar|gamento)\b", r"\bcheckout\b", r"\bcharge\b",
    r"\bconvit(e|ar)\b", r"\binvite\b",
    r"\bsend\b.*\be-?mail\b", r"\benviar\b.*\be-?mail\b",
    r"\bunsubscribe\b", r"\bcancel(ar)?\b.*\b(subscription|assinatura|plano)\b",
]

ACTION_TOOLS = {"browser_click", "browser_type", "browser_press_key", "browser_select_option", "browser_drag"}


def _request_text(request: MCPToolCallRequest) -> str:
    return " ".join(str(v) for v in request.args.values())


def make_blocklist_interceptor(extra_patterns: list[str] | None = None, whitelist: bool = False):
    """Returns a ToolCallInterceptor that short-circuits destructive-looking actions.

    `whitelist=True` disables the block entirely (explicit opt-in per DESIGN.md's
    guardrail: destructive actions stay off unless the operator turns them on).
    """
    patterns = [re.compile(p, re.IGNORECASE) for p in (DEFAULT_BLOCKLIST + (extra_patterns or []))]

    async def interceptor(request: MCPToolCallRequest, handler):
        if whitelist or request.name not in ACTION_TOOLS:
            return await handler(request)

        text = _request_text(request)
        for pattern in patterns:
            if pattern.search(text):
                return CallToolResult(
                    isError=True,
                    content=[TextContent(
                        type="text",
                        text=(
                            f"Blocked by Cartógrafo guardrail: '{request.name}' targeting "
                            f"{text!r} looks destructive/external and exploration is read-mostly. "
                            "Skip this action and continue mapping elsewhere."
                        ),
                    )],
                )
        return await handler(request)

    return interceptor
