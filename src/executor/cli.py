import argparse
import asyncio
from pathlib import Path

from executor.batch import run_batch
from executor.dry_run import run_dry


def parse_args():
    parser = argparse.ArgumentParser(
        description="Executor — deterministically replays a compiled spec.yaml, no LLM in the loop. "
                     "Standalone: just runs what's already there, no confirmation UI (that's compilador's job)."
    )
    parser.add_argument("--compilador-dir", required=True, help="Directory containing spec.yaml")
    parser.add_argument("--mode", choices=["dry", "batch"], default="dry")
    parser.add_argument("--n", type=int, default=10, help="Number of runs (batch mode only)")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--output-dir", help="Defaults to <compilador-dir>/executor")
    parser.add_argument("--headless", action="store_true")
    return parser.parse_args()


def print_dry_result(result: dict) -> None:
    run = result["run"]
    print(f"\n=== DRY RUN: {run['status'].upper()} ===")
    for s in run["steps"]:
        marker = "OK" if s["ok"] else f"FAIL ({s.get('error')})"
        duration_ms = s["t_end_ms"] - s["t_start_ms"]
        print(f"- {s['id']}: {marker} ({duration_ms:.0f}ms)")

    print("\nCaptures:")
    if run["captures"]:
        for name, value in run["captures"].items():
            if value is None:
                print(f"- {name}: (empty — spec doesn't declare a `capture.selector` to read from here)")
            else:
                preview = value if len(value) <= 200 else value[:200] + "..."
                print(f"- {name}: {preview!r}")
    else:
        print("(none declared)")

    print(f"\ndry-run.json -> {result['run_path']}")


def print_batch_result(runs: list[dict], output_dir: Path) -> None:
    ok = sum(1 for r in runs if r["status"] == "ok")
    print(f"\n=== BATCH: {ok}/{len(runs)} ok ===")
    for r in runs:
        if r["status"] != "ok":
            failed_step = next((s for s in r["steps"] if not s["ok"]), None)
            reason = f" at {failed_step['id']}: {failed_step.get('error')}" if failed_step else ""
            print(f"- run {r['run']:03d}: {r['status']}{reason}")
    print(f"\nrun-*.json -> {output_dir}")


def main():
    args = parse_args()
    compilador_dir = Path(args.compilador_dir)
    output_dir = Path(args.output_dir) if args.output_dir else compilador_dir / "executor"

    if args.mode == "dry":
        result = asyncio.run(run_dry(compilador_dir, output_dir, headless=args.headless))
        print_dry_result(result)
    else:
        runs = asyncio.run(run_batch(compilador_dir, output_dir, n=args.n,
                                      concurrency=args.concurrency, headless=args.headless))
        print_batch_result(runs, output_dir)


if __name__ == "__main__":
    main()
