"""
Usage:
    python -m veredito.cli --judgments judgments.json --baseline baseline.json --out-dir out/

Produces report.html and baseline.json in --out-dir (new baseline for the
next release comparison). Exit code 1 if a regression vs. baseline is detected
— suitable for CI gating.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from veredito.aggregate import (
    aggregate_pass_rates,
    build_baseline,
    compare_baseline,
    latency_stats,
    worst_k_examples,
)
from veredito.report import render_report_html


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate judgments.json into report.html + baseline.json")
    parser.add_argument("--judgments", required=True, help="path to judgments.json")
    parser.add_argument("--baseline", default=None, help="previous release baseline.json (optional)")
    parser.add_argument("--out-dir", required=True, help="where to write report.html and baseline.json")
    parser.add_argument("--worst-k", type=int, default=3, help="how many failed examples to show per contract")
    args = parser.parse_args(argv)

    os.makedirs(args.out_dir, exist_ok=True)

    with open(args.judgments, "r", encoding="utf-8") as f:
        judgments = json.load(f)

    baseline = {}
    if args.baseline and os.path.exists(args.baseline):
        with open(args.baseline, "r", encoding="utf-8") as f:
            baseline = json.load(f)

    summaries = aggregate_pass_rates(judgments)
    latency = latency_stats(judgments)
    baseline_diff = compare_baseline(summaries, baseline)
    worst = worst_k_examples(judgments, k=args.worst_k)

    report_html = render_report_html(summaries, latency, baseline_diff, worst)
    with open(os.path.join(args.out_dir, "report.html"), "w", encoding="utf-8") as f:
        f.write(report_html)

    new_baseline = build_baseline(summaries, latency)
    with open(os.path.join(args.out_dir, "baseline.json"), "w", encoding="utf-8") as f:
        json.dump(new_baseline, f, ensure_ascii=False, indent=2)

    regressions = [cid for cid, d in baseline_diff.items() if d["regression"]]
    print(f"Verdict: {len(summaries)} contracts evaluated.")
    for cid, s in sorted(summaries.items()):
        print(f"  {cid}: {s.passes}/{s.n} ({s.pass_rate:.1%})")
    if regressions:
        print(f"⚠️  Regressions vs. baseline: {regressions}")
    print(f"Report: {os.path.join(args.out_dir, 'report.html')}")

    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
