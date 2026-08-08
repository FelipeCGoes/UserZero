import argparse
import asyncio
import json
from pathlib import Path

import yaml

from compilador.cli import compile_and_confirm
from executor.batch import run_batch
from executor.cli import print_batch_result
from judges.runner import run_all_judges, write_judgments
from veredito.aggregate import (
    aggregate_pass_rates,
    build_baseline,
    compare_baseline,
    latency_stats,
    worst_k_examples,
)
from veredito.report import render_report_html


def parse_args():
    parser = argparse.ArgumentParser(
        description="userzero — compile a flow, confirm it (flow then contracts), then run it N times"
    )
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--flow", required=True, help="The flow to compile, in natural language.")
    parser.add_argument("--flow-id")
    parser.add_argument("--contracts")
    parser.add_argument("--cartografo-dir", required=True,
                         help="Directory containing the graph.json + map.md this flow anchors on.")
    parser.add_argument("--mode", choices=["ui", "api"], default="ui")
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--output-dir", default="output/userzero")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-minutes", type=float, default=8.0)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--n", type=int, default=10, help="Number of production runs, after confirmation.")
    parser.add_argument("--concurrency", type=int, default=5)
    return parser.parse_args()


def run_judges_and_verdict(spec_path: Path, executor_dir: Path) -> None:
    """Judges (consumes spec.yaml's contracts + run-*.json, produces judgments.json)
    followed by Veredito (aggregates judgments.json into pass-rates + report.html +
    a new baseline.json) — both built separately, called here as plain library
    functions exactly like compile_and_confirm()/run_batch() above, not subprocesses."""
    judges_dir = executor_dir.parent / "judges"
    judges_dir.mkdir(parents=True, exist_ok=True)

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    llm = None
    if any(c.get("type") == "grounding" for c in spec.get("contracts", [])):
        from common.llm import get_llm
        llm = get_llm(temperature=0.0)

    judgments = run_all_judges(spec_path=str(spec_path), runs_dir=str(executor_dir), llm=llm)
    judgments_path = judges_dir / "judgments.json"
    write_judgments(judgments, str(judgments_path))
    n_fail = sum(1 for j in judgments if not j.passed)
    print(f"{len(judgments)} judgments written to {judgments_path} ({n_fail} failed)")

    judgment_dicts = [j.to_dict() for j in judgments]
    summaries = aggregate_pass_rates(judgment_dicts)
    latency = latency_stats(judgment_dicts)

    baseline_path = judges_dir / "baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    baseline_diff = compare_baseline(summaries, baseline)
    worst = worst_k_examples(judgment_dicts, k=3)

    report_path = judges_dir / "report.html"
    report_path.write_text(render_report_html(summaries, latency, baseline_diff, worst), encoding="utf-8")
    baseline_path.write_text(
        json.dumps(build_baseline(summaries, latency), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Verdict: {len(summaries)} contracts evaluated.")
    for cid, s in sorted(summaries.items()):
        print(f"  {cid}: {s.passes}/{s.n} ({s.pass_rate:.1%})")
    regressions = [cid for cid, d in baseline_diff.items() if d["regression"]]
    if regressions:
        print(f"  Regressions vs. baseline: {regressions}")
    print(f"Report: {report_path}")


async def run(args) -> None:
    spec_path = await compile_and_confirm(args)
    output_dir = spec_path.parent

    print("\n---EXECUTOR STEP---")
    executor_dir = output_dir / "executor"
    runs = await run_batch(output_dir, executor_dir, n=args.n, concurrency=args.concurrency, headless=args.headless)
    print_batch_result(runs, executor_dir)

    print("\n---JUDGES STEP---")
    run_judges_and_verdict(spec_path, executor_dir)


def main():
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
