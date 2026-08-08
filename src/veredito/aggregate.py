"""
Consumes: judgments.json + baseline.json (from the previous release, may not exist)
Produces: the numbers that report.py renders into HTML, plus the new baseline.

This module does not judge anything — it only aggregates what the judges
already decided.
Aggregations: pass-rate per contract with Wilson CI; min/p50/p95/max latency
by declared phase; diff against baseline; worst K examples with evidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

Z_95 = 1.96
REGRESSION_THRESHOLD = 0.05  # rate drop greater than this is considered a regression

def wilson_ci(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson confidence interval for a binomial proportion.
    Preferred over Wald here because run N tends to be small (tens, not thousands) 
    and Wald behaves poorly near 0% and 100%.
    """
    if n == 0:
        return (0.0, 1.0)
    p_hat = successes / n
    denom = 1 + z**2 / n
    center = p_hat + z**2 / (2 * n)
    margin = z * math.sqrt((p_hat * (1 - p_hat) / n) + (z**2 / (4 * n**2)))
    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return (max(0.0, lower), min(1.0, upper))


def percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[f] + (s[c] - s[f]) * (k - f)


@dataclass
class ContractSummary:
    contract_id: str
    type: str
    n: int
    passes: int
    pass_rate: float
    ci: tuple[float, float]
    failing_runs: List[int] = field(default_factory=list)


def aggregate_pass_rates(judgments: List[Dict[str, Any]]) -> Dict[str, ContractSummary]:
    by_contract: Dict[str, List[Dict[str, Any]]] = {}
    for j in judgments:
        by_contract.setdefault(j["contract_id"], []).append(j)

    summaries: Dict[str, ContractSummary] = {}
    for cid, js in by_contract.items():
        n = len(js)
        passes = sum(1 for j in js if j["pass"])
        failing = [j["run"] for j in js if not j["pass"]]
        summaries[cid] = ContractSummary(
            contract_id=cid,
            type=js[0]["type"],
            n=n,
            passes=passes,
            pass_rate=passes / n if n else 0.0,
            ci=wilson_ci(passes, n),
            failing_runs=failing,
        )
    return summaries


def latency_stats(judgments: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """One entry per latency contract: min/p50/p95/max in seconds,
    and whether the observed p95 violated the declared `p95_max_s` in the spec."""
    by_contract: Dict[str, List[float]] = {}
    p95_max_by_contract: Dict[str, Optional[float]] = {}

    for j in judgments:
        if j["type"] != "latency" or not j.get("evidence"):
            continue
        ev = j["evidence"]
        if "latency_s" not in ev:
            continue
        by_contract.setdefault(j["contract_id"], []).append(ev["latency_s"])
        p95_max_by_contract[j["contract_id"]] = ev.get("p95_max_s")

    stats = {}
    for cid, values in by_contract.items():
        p95 = percentile(values, 0.95)
        p95_max = p95_max_by_contract.get(cid)
        stats[cid] = {
            "n": len(values),
            "min_s": round(min(values), 3),
            "p50_s": round(percentile(values, 0.5), 3),
            "p95_s": round(p95, 3) if p95 is not None else None,
            "max_s": round(max(values), 3),
            "p95_max_s": p95_max,
            "p95_violated": bool(p95_max is not None and p95 is not None and p95 > p95_max),
        }
    return stats


def compare_baseline(
    current: Dict[str, ContractSummary], baseline: Dict[str, Any]
) -> Dict[str, Dict[str, Any]]:
    """baseline.json has shape {contract_id: {"pass_rate": float, ...}}.
    Regression = pass-rate drop greater than REGRESSION_THRESHOLD."""
    diffs = {}
    baseline_rates = baseline.get("contracts", {}) if baseline else {}
    for cid, summary in current.items():
        prev = baseline_rates.get(cid, {}).get("pass_rate")
        delta = None if prev is None else summary.pass_rate - prev
        diffs[cid] = {
            "previous_pass_rate": prev,
            "current_pass_rate": summary.pass_rate,
            "delta": round(delta, 4) if delta is not None else None,
            "regression": bool(delta is not None and delta < -REGRESSION_THRESHOLD),
        }
    return diffs


def worst_k_examples(judgments: List[Dict[str, Any]], k: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    """For each contract, up to k failed runs with attached evidence
    (screenshot/trace are outside this module — they come from the run.json /
    evidence store; here we only point to the run number for lookup)."""
    by_contract: Dict[str, List[Dict[str, Any]]] = {}
    for j in judgments:
        if not j["pass"]:
            by_contract.setdefault(j["contract_id"], []).append(j)

    return {cid: sorted(js, key=lambda j: j["run"])[:k] for cid, js in by_contract.items()}


def build_baseline(summaries: Dict[str, ContractSummary], latency: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contracts": {
            cid: {"pass_rate": s.pass_rate, "n": s.n, "passes": s.passes}
            for cid, s in summaries.items()
        },
        "latency": latency,
    }
