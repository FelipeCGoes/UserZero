from langchain_core.tools import tool

from cartografo.graph_store import GraphBuilder
from common.budget import Budget
from common.mcp_client import SCREENSHOTS_SUBDIR
from common.snapshot_capture import SnapshotCapture


def build_recording_tools(graph: GraphBuilder, snapshot: SnapshotCapture, budget: Budget) -> list:
    """Local (non-MCP) tools the Cartógrafo agent uses to write graph.json
    incrementally, closing over this run's GraphBuilder/SnapshotCapture/Budget."""

    @tool
    def record_node(node_id: str, url: str, title: str, screenshot: str | None = None) -> str:
        """Record the current page as a graph node. Call `browser_snapshot` (or any
        navigation/click action, which returns a fresh snapshot) immediately before
        this, so the node is fingerprinted from what the browser is showing right now.
        `node_id` should be short and slug-like (e.g. "reports", "report-view").
        `screenshot` is the filename you passed to browser_take_screenshot for this
        page, if you took one (just the filename — where it's saved is handled for you)."""
        if not snapshot.text:
            return "No snapshot captured yet — call browser_snapshot (or navigate/click) before record_node."

        screenshot_path = f"{SCREENSHOTS_SUBDIR}/{screenshot}" if screenshot else None
        actual_id, is_new = graph.record_node(node_id, url, title, snapshot.text, screenshot_path)
        outcome = f"recorded new node '{actual_id}'" if is_new else (
            f"'{node_id}' matches an already-recorded state — reusing existing node '{actual_id}' instead of duplicating it"
        )
        reason = budget.status(len(graph.nodes))
        warning = f"Budget reached: {reason}. Stop exploring now and write map.md." if reason else None
        return outcome + (f"\n{warning}" if warning else "")

    @tool
    def record_edge(from_id: str, to_id: str, action: str, selector: str, label: str,
                     api_method: str | None = None, api_path: str | None = None) -> str:
        """Record the action that moves the app from one recorded node to another.
        `selector` must be a stable Playwright selector, in priority order:
        [data-testid="..."] (or the target's data-test/data-qa/data-cy equivalent,
        found via browser_evaluate on the element's ref) > role=...[name="..."] > a
        plain text selector. Never pass an MCP ref (e.g. "e5") as the selector — refs
        aren't valid outside this MCP session and the Executor can't use them.
        If this action triggered a network request (check browser_network_requests),
        pass its method/path so the flow can later run in API (volume) mode."""
        return graph.record_edge(from_id, to_id, action, selector, label, api_method, api_path)

    return [record_node, record_edge]
