import argparse
import asyncio

from compilador.cli import compile_and_confirm
from executor.batch import run_batch
from executor.cli import print_batch_result


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


async def run(args) -> None:
    spec_path = await compile_and_confirm(args)
    output_dir = spec_path.parent

    print("\n---EXECUTOR STEP---")
    executor_dir = output_dir / "executor"
    runs = await run_batch(output_dir, executor_dir, n=args.n, concurrency=args.concurrency, headless=args.headless)
    print_batch_result(runs, executor_dir)

    print("\nJUDGES BEING IMPLEMENTED")


def main():
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
