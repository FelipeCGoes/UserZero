import argparse
import asyncio
import json
import re
from pathlib import Path

import yaml
from dotenv import load_dotenv
from langgraph.errors import GraphRecursionError

from common.agent_logging import run_with_console_log
from common.budget import Budget
from common.llm import get_llm
from common.mcp_client import playwright_mcp_tools
from compilador.agent import build_agent
from compilador.contracts import derive_and_materialize_contracts
from compilador.review import ask_yes_no_with_feedback, print_contracts, print_flow_and_dry_run
from compilador.spec_store import SpecBuilder
from compilador.tools import build_recording_tools
from executor.dry_run import run_dry


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "flow"


def parse_args():
    parser = argparse.ArgumentParser(description="Compilador — compiles one natural-language flow into spec.yaml")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--flow", required=True, help="The flow to compile, in natural language.")
    parser.add_argument("--flow-id", help="Slug for spec.yaml's `flow:` field. Defaults to a slug of --flow.")
    parser.add_argument("--contracts",
                         help="Natural-language description of the expected behavior for this flow "
                              "(format, language, latency, grounding, change of scope...). Omit to "
                              "leave spec.yaml's contracts empty for now — nothing is derived that "
                              "wasn't described.")
    parser.add_argument("--cartografo-dir", required=True,
                         help="Directory containing the graph.json + map.md this flow anchors on.")
    parser.add_argument("--mode", choices=["ui", "api"], default="ui")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--output-dir", default="output/compilador")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-minutes", type=float, default=8.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true",
                         help="Disable the guardrail for this run. Off by default — turn on only "
                              "if the flow itself requires an action the guardrail would block.")
    return parser.parse_args()


def build_task_message(base_url: str, flow: str, contracts_description: str | None, graph: dict,
                        map_md: str, username: str | None, password: str | None) -> str:
    lines = [f"Target app: {base_url}", "", "Flow to compile (natural language):", flow, ""]
    if contracts_description:
        lines += [
            "The user also described the expected behavior for this flow (context only — "
            "contracts are derived separately from this text after your run, don't try to "
            "verify it yourself):",
            contracts_description, "",
        ]
    lines += [
        "App map (map.md, from the Cartógrafo):", "", map_md, "",
        "Navigation graph (graph.json) — reuse a node's recorded selector when your live "
        "step matches one of these edges; if the live page differs, trust what you see and "
        "record the corrected selector instead:", "",
        json.dumps(graph, indent=2, ensure_ascii=False), "",
    ]
    if username:
        lines += [f"Test credentials: username={username!r}, password={password!r}", ""]
    lines.append(f"Start by calling browser_navigate to {base_url}.")
    return "\n".join(lines)


def print_review(spec: SpecBuilder) -> None:
    """First-contracts-then-flow review order, so a human confirms what the run is
    supposed to guarantee before looking at how it gets there. Confirmation/edits
    themselves happen by hand on spec.yaml for now — see DESIGN.md's three ways
    contracts get set; the dry-run/approval UI is the Executor's job, not built yet."""
    print("\n=== REVIEW: CONTRACTS (confirm first) ===")
    if spec.contracts:
        for c in spec.contracts:
            print(f"- {c}")
            if c.get("type") == "grounding" and not c.get("sources"):
                print("  ! INCOMPLETE: no `sources` — the Compilador never saw this content "
                      "(a pre-existing document it only selected, not typed or read). Add "
                      "`sources:` by hand before anything can judge this contract.")
    else:
        print("(none — no expected behavior was described for this flow; edit spec.yaml "
              "directly to add contracts, or re-run with --contracts)")

    print("\n=== REVIEW: FLOW (confirm second) ===")
    for s in spec.steps:
        detail = f" -> {s['selector']}" if "selector" in s else (f" -> {s['url']}" if "url" in s else "")
        capture = f"  [captures: {s['capture']['name']}]" if "capture" in s else ""
        print(f"- {s['id']}: {s['action']}{detail}{capture}")


async def run(args, print_summary: bool = True) -> Path:
    load_dotenv()
    output_dir = Path(args.output_dir)
    cartografo_dir = Path(args.cartografo_dir)

    graph = json.loads((cartografo_dir / "graph.json").read_text(encoding="utf-8"))
    map_md = (cartografo_dir / "map.md").read_text(encoding="utf-8")

    flow_id = args.flow_id or slugify(args.flow)
    spec = SpecBuilder(flow=flow_id, mode=args.mode)
    budget = Budget(max_units=args.max_steps, max_minutes=args.max_minutes)
    llm = get_llm()

    failure = None
    try:
        async with playwright_mcp_tools(output_dir, args.headless, args.allow_destructive) as (mcp_tools, _snapshot):
            recording_tools = build_recording_tools(spec, budget)
            agent = build_agent(llm, mcp_tools, recording_tools)

            task = build_task_message(args.base_url, args.flow, args.contracts, graph, map_md,
                                       args.username, args.password)
            await run_with_console_log(
                agent,
                {"messages": [{"role": "user", "content": task}]},
                config={"recursion_limit": max(40, args.max_steps * 8)},
                transcript_path=output_dir / "transcript.jsonl",
            )
    except GraphRecursionError:
        failure = (f"Hit the {max(40, args.max_steps * 8)}-step recursion limit before finishing "
                   "(the agent was still acting, not necessarily stuck).")
    except Exception as exc:  # noqa: BLE001 — last line of defense before losing partial steps
        failure = f"{type(exc).__name__}: {exc}"

    # Contracts are derived from whatever steps/captures exist, even on partial failure —
    # a half-compiled flow with correctly-bound contracts is still useful to inspect.
    # derive_contracts() already guards its own model call, but nothing between here and
    # spec.write() below is allowed to cost the steps compiled above (mirrors Cartógrafo's
    # graph.write()-always-runs discipline) — a bug in this step must degrade to "no
    # contracts", never lose an already-completed, expensive agentic run.
    try:
        spec.contracts = derive_and_materialize_contracts(llm, args.contracts, spec.steps, output_dir)
    except Exception as exc:  # noqa: BLE001 — last line of defense before losing recorded steps
        print(f"WARNING: contract derivation failed unexpectedly ({type(exc).__name__}: {exc}) "
              "— continuing with no contracts.")
    spec_path = spec.write(output_dir)

    if failure:
        print(f"WARNING: {failure} — {len(spec.steps)} step(s) recorded before the failure; see {spec_path}.")

    if print_summary:
        print_review(spec)
    return spec_path


async def compile_and_confirm(args) -> Path:
    """Owns the confirm-and-possibly-retry loop end to end: compile -> dry-run ->
    confirm flow (real dry-run result, not just the agent's self-report) -> confirm
    contracts. Only compilador can own this loop — it's the only piece with the
    context (base-url, credentials, the flow's own text) needed to recompile if the
    flow is rejected. Executor never sees any of this; it only ever runs what
    already exists.

    Flow rejection -> full recompile with feedback appended (expensive: another full
    agentic run, same cost as the first compile). Contracts rejection -> re-run only
    derive_contracts with feedback appended (cheap: no browser, no recompile) — flow
    is confirmed first specifically so a contracts-only retry never has to
    re-question a flow that's already been signed off.
    """
    load_dotenv()
    llm = get_llm()
    original_flow = args.flow
    original_contracts = args.contracts

    while True:
        spec_path = await run(args, print_summary=False)
        output_dir = spec_path.parent
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))

        dry = await run_dry(output_dir, output_dir / "executor", headless=args.headless)
        print_flow_and_dry_run(spec, dry["run"])
        approved, feedback = ask_yes_no_with_feedback("Approve this flow?")
        if approved:
            break
        args.flow = f"{original_flow}\n\nFeedback from a rejected previous attempt: {feedback}"

    args.flow = original_flow  # restore for a clean re-run if this whole function is called again

    contracts_description = original_contracts
    while True:
        print_contracts(spec.get("contracts", []))
        approved, feedback = ask_yes_no_with_feedback("Approve these contracts?")
        if approved:
            break
        contracts_description = f"{contracts_description}\n\nFeedback: {feedback}" if contracts_description else feedback
        spec["contracts"] = derive_and_materialize_contracts(llm, contracts_description, spec["steps"], output_dir)
        spec_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")

    return spec_path


def main():
    args = parse_args()
    spec_path = asyncio.run(compile_and_confirm(args))
    print(f"\nTest case is ready under {spec_path.parent}")


if __name__ == "__main__":
    main()
