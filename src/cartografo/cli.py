import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from langgraph.errors import GraphRecursionError

from cartografo.agent import build_agent
from cartografo.graph_store import GraphBuilder, write_map_md
from cartografo.tools import build_recording_tools
from common.agent_logging import run_with_console_log
from common.budget import Budget
from common.llm import get_llm
from common.mcp_client import playwright_mcp_tools


def parse_args():
    parser = argparse.ArgumentParser(description="Cartógrafo — maps a target app into graph.json + map.md")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--focus", action="append",
                         help="A flow to map, in natural language. Repeat --focus for multiple. "
                              "Omit entirely to explore the whole app autonomously until exhaustion or budget.")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--output-dir", default="output/cartografo")
    parser.add_argument("--max-states", type=int, default=25)
    parser.add_argument("--max-minutes", type=float, default=12.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true",
                         help="Disable the read-mostly guardrail. Off by default — turn on only against a throwaway target.")
    return parser.parse_args()


def build_task_message(base_url: str, focus: list[str] | None, username: str | None, password: str | None) -> str:
    lines = [f"Target app: {base_url}", ""]
    if focus:
        lines += ["Mode: GUIDED", "", "Flows to map:"]
        lines += [f"- {f}" for f in focus]
    else:
        lines += ["Mode: AUTONOMOUS", "",
                   "No flows assigned — explore the entire app breadth-first and map "
                   "everything reachable, until the graph is exhausted or the budget runs out."]
    if username:
        lines += ["", f"Test credentials: username={username!r}, password={password!r}"]
    lines += ["", f"Start by calling browser_navigate to {base_url}."]
    return "\n".join(lines)


async def run(args) -> tuple[Path, Path]:
    load_dotenv()
    output_dir = Path(args.output_dir)

    graph = GraphBuilder()
    budget = Budget(max_units=args.max_states, max_minutes=args.max_minutes)
    llm = get_llm()

    map_md_content = None
    failure = None
    try:
        async with playwright_mcp_tools(output_dir, args.headless, args.allow_destructive) as (mcp_tools, _snapshot):
            recording_tools = build_recording_tools(graph, _snapshot, budget)
            agent = build_agent(llm, mcp_tools, recording_tools)

            task = build_task_message(args.base_url, args.focus, args.username, args.password)
            result = await run_with_console_log(
                agent,
                {"messages": [{"role": "user", "content": task}]},
                config={"recursion_limit": max(60, args.max_states * 8)},
                transcript_path=output_dir / "transcript.jsonl",
            )
            # Extract the answer BEFORE the `async with` above tears down the MCP
            # session — a teardown-phase error (subprocess/transport flakiness) would
            # otherwise propagate past this point and discard an already-obtained,
            # perfectly good final answer along with it.
            last_message = result["messages"][-1]
            if isinstance(last_message.content, str) and last_message.content.strip():
                map_md_content = last_message.content
            else:
                # No exception, but nothing usable either — e.g. the model hit its
                # completion-token cap mid-turn (finish_reason="length") and produced
                # neither visible text nor a tool call. Treat as a failure rather than
                # silently writing a blank map.md.
                failure = "The agent's last turn produced no text and no tool call (possibly truncated by max_tokens)."
    except GraphRecursionError:
        failure = (f"Hit the {max(60, args.max_states * 8)}-step recursion limit before finishing "
                   "(the agent was still exploring/reasoning, not necessarily stuck).")
    except Exception as exc:  # noqa: BLE001 — this is the last line of defense before losing partial exploration
        failure = f"{type(exc).__name__}: {exc}"

    # graph.json reflects whatever record_node/record_edge calls landed before failure —
    # always persist it so a crash mid-run doesn't throw away real exploration progress.
    graph_path = graph.write(output_dir)
    if failure and map_md_content is None:
        # Only fall back to this placeholder if the agent never produced a real answer.
        # If it did (failure happened during session teardown, after a clean finish),
        # map_md_content is already set above and that real answer wins.
        map_md_content = (
            f"# Map: INCOMPLETE\n\nCartógrafo did not finish this run: {failure}\n\n"
            f"{len(graph.nodes)} node(s) and {len(graph.edges)} edge(s) were recorded before "
            "the failure — see graph.json for what was captured. Re-run (a smaller "
            "--max-states/--max-minutes helps isolate where it's spending steps) or inspect "
            f"{output_dir / 'mcp-artifacts'} for the browser-side logs/snapshots leading up to it."
        )
    elif failure:
        map_md_content += (
            f"\n\n---\n\n**Note:** the agent finished cleanly, but a failure occurred "
            f"during session teardown after that: {failure}"
        )
    map_path = write_map_md(output_dir, map_md_content)
    if failure:
        print(f"WARNING: {failure}")
    return graph_path, map_path


def main():
    args = parse_args()
    graph_path, map_path = asyncio.run(run(args))
    print(f"graph.json -> {graph_path}")
    print(f"map.md     -> {map_path}")


if __name__ == "__main__":
    main()
