"""
Usage:
    python -m judges.cli --spec spec.yaml --runs-dir runs/ --out judgments.json

Requires FEATHERLESS_BASE_URL / FEATHERLESS_API_KEY / MODEL in the environment
(the same variables used by common/llm.py) only if the spec contains a
`grounding` contract — the only judge that calls an LLM. The other four
run 100% offline and deterministically, without needing network access.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from judges.runner import run_all_judges, write_judgments

# src/judges/cli.py -> parents[0]=judges, [1]=src, [2]=project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _spec_has_grounding(spec_path: str) -> bool:
    with open(spec_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)
    return any(c.get("type") == "grounding" for c in spec.get("contracts", []))


def main(argv=None) -> int:
    load_dotenv(_PROJECT_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Run the judge catalog over a batch of runs")
    parser.add_argument("--spec", required=True, help="path to spec.yaml")
    parser.add_argument("--runs-dir", required=True, help="directory containing run-*.json")
    parser.add_argument("--out", default="judgments.json", help="where to write judgments.json")
    args = parser.parse_args(argv)

    llm = None
    if _spec_has_grounding(args.spec):
        from common.llm import get_llm

        llm = get_llm(temperature=0.0)

    judgments = run_all_judges(spec_path=args.spec, runs_dir=args.runs_dir, llm=llm)
    write_judgments(judgments, args.out)

    n_fail = sum(1 for j in judgments if not j.passed)
    print(f"{len(judgments)} judgments written to {args.out} ({n_fail} failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())