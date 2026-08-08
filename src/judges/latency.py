"""
The `latency` judge: pure arithmetic over timestamps for steps declared in
the spec (from/to) — the "phases" are declared by the spec, not hardcoded
in the code, so this judge is generic for any from/to pair.

spec:
  - { type: latency, from: s3, to: s4, p95_max_s: 180 }

Important: the `p95_max_s` threshold is an aggregated statistic across N runs,
not something that can be approved/rejected by a single isolated run. This
judge always computes and returns the run latency as evidence (`pass: true`
by default); Verdict aggregates the N values and decides whether p95
violated the contract. If the spec also includes a `soft_max_s` per run,
this judge applies that individual ceiling — useful to catch gross outliers
early without waiting for aggregation.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def judge(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    from_id = params["from"]
    to_id = params["to"]

    steps_by_id = {s["id"]: s for s in run.get("steps", [])}
    from_step = steps_by_id.get(from_id)
    to_step = steps_by_id.get(to_id)

    if from_step is None or to_step is None:
        missing = [sid for sid, s in [(from_id, from_step), (to_id, to_step)] if s is None]
        return {
            "pass": False,
            "evidence": {"reason": f"step(s) not found in run: {missing}"},
        }

    if not from_step.get("ok") or not to_step.get("ok"):
        return {
            "pass": False,
            "evidence": {"reason": "from/to step did not finish ok in this run", "from": from_id, "to": to_id},
        }

    t_start = from_step.get("t_start_ms")
    t_end = to_step.get("t_end_ms")
    if t_start is None or t_end is None:
        return {"pass": False, "evidence": {"reason": "missing timestamps"}}

    latency_ms = t_end - t_start
    latency_s = latency_ms / 1000.0

    first_content_ms = to_step.get("t_first_content_ms")
    ttfb_s: Optional[float] = None
    if first_content_ms is not None:
        ttfb_s = (first_content_ms - t_start) / 1000.0

    soft_max_s = params.get("soft_max_s")
    passed = True
    reason = None
    if soft_max_s is not None and latency_s > soft_max_s:
        passed = False
        reason = f"latency {latency_s:.1f}s exceeded per-run ceiling of {soft_max_s}s"

    evidence: Dict[str, Any] = {
        "from": from_id,
        "to": to_id,
        "latency_s": round(latency_s, 3),
        "p95_max_s": params.get("p95_max_s"),  # for aggregation, not per-run
    }
    if ttfb_s is not None:
        evidence["time_to_first_content_s"] = round(ttfb_s, 3)
    if reason:
        evidence["reason"] = reason

    return {"pass": passed, "evidence": evidence}
