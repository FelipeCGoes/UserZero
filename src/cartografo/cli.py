import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from cartografo.agent import build_agent
from cartografo.budget import Budget
from cartografo.graph_store import GraphBuilder, write_map_md
from cartografo.mcp_client import playwright_mcp_tools
from cartografo.tools import build_recording_tools
from common.llm import get_llm


def parse_args():
    parser = argparse.ArgumentParser(description="Cartógrafo — maps a target app into graph.json + map.md")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--focus", required=True, action="append",
                         help="A flow to map, in natural language. Repeat --focus for up to 2-3 flows.")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--output-dir", default="output/cartografo")
    parser.add_argument("--max-states", type=int, default=12)
    parser.add_argument("--max-minutes", type=float, default=8.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true",
                         help="Disable the read-mostly guardrail. Off by default — turn on only against a throwaway target.")
    return parser.parse_args()


def build_task_message(base_url: str, focus: list[str], username: str | None, password: str | None) -> str:
    lines = [f"Target app: {base_url}", "", "Flows to map:"]
    lines += [f"- {f}" for f in focus]
    if username:
        lines += ["", f"Test credentials: username={username!r}, password={password!r}"]
    lines += ["", f"Start by calling browser_navigate to {base_url}."]
    return "\n".join(lines)


async def run(args) -> tuple[Path, Path]:
    load_dotenv()
    output_dir = Path(args.output_dir)

    graph = GraphBuilder()
    budget = Budget(max_states=args.max_states, max_minutes=args.max_minutes)
    llm = get_llm()

    async with playwright_mcp_tools(output_dir, args.headless, args.allow_destructive) as (mcp_tools, _snapshot):
        recording_tools = build_recording_tools(graph, _snapshot, budget)
        agent = build_agent(llm, mcp_tools, recording_tools)

        task = build_task_message(args.base_url, args.focus, args.username, args.password)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": max(60, args.max_states * 8)},
        )

    map_md_content = result["messages"][-1].content
    graph_path = graph.write(output_dir)
    map_path = write_map_md(output_dir, map_md_content)
    return graph_path, map_path


def main():
    args = parse_args()
    graph_path, map_path = asyncio.run(run(args))
    print(f"graph.json -> {graph_path}")
    print(f"map.md     -> {map_path}")


if __name__ == "__main__":
    main()
