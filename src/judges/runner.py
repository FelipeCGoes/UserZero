"""
Consumes: spec.yaml (contracts) + run-001.json ... run-N.json
Produces: judgments.json

Runs each contract from the spec against each run, using the corresponding
judge in JUDGE_REGISTRY. It never touches the browser — it only reads the
run.json files already recorded by the Executor, which makes this rerunnable
and parallelizable (DESIGN.md).

An exception inside a judge never kills the batch: it becomes a Judgment with
pass=False and `error` populated, following the Executor's philosophy of
never raising an exception due to an isolated failure.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Optional

import yaml

from judges import JUDGE_REGISTRY
from judges.models import Contract, Judgment, contracts_from_spec


def load_spec(spec_path: str) -> Dict[str, Any]:
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_runs(runs_dir: str) -> List[Dict[str, Any]]:
    paths = sorted(glob.glob(os.path.join(runs_dir, "run-*.json")))
    if not paths:
        raise FileNotFoundError(f"no run-*.json files found in {runs_dir}")
    runs = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            runs.append(json.load(f))
    return runs


def judge_run(run: Dict[str, Any], contract: Contract, llm: Optional[Any] = None) -> Judgment:
    judge_fn = JUDGE_REGISTRY.get(contract.type)
    if judge_fn is None:
        return Judgment(
            run=run["run"],
            contract_id=contract.id,
            type=contract.type,
            passed=False,
            error=f"unknown contract type: {contract.type}",
        )

    # run blocked/failed during execution: contract fails by inheritance,
    # without even calling the judge (there is no reliable capture to evaluate)
    if run.get("status") != "ok":
        return Judgment(
            run=run["run"],
            contract_id=contract.id,
            type=contract.type,
            passed=False,
            evidence={"reason": f"run status={run.get('status')}, not evaluated"},
        )

    try:
        kwargs = {"llm": llm} if contract.type == "grounding" else {}
        result = judge_fn(run, contract.params, **kwargs)
        return Judgment(
            run=run["run"],
            contract_id=contract.id,
            type=contract.type,
            passed=bool(result["pass"]),
            evidence=result.get("evidence"),
        )
    except Exception as e:  # juiz não pode derrubar o batch
        return Judgment(
            run=run["run"],
            contract_id=contract.id,
            type=contract.type,
            passed=False,
            error=f"{type(e).__name__}: {e}",
        )


def run_all_judges(spec_path: str, runs_dir: str, llm: Optional[Any] = None) -> List[Judgment]:
    spec = load_spec(spec_path)
    contracts = contracts_from_spec(spec)
    runs = load_runs(runs_dir)

    judgments: List[Judgment] = []
    for run in runs:
        for contract in contracts:
            judgments.append(judge_run(run, contract, llm))
    return judgments


def write_judgments(judgments: List[Judgment], out_path: str) -> None:
    payload = [j.to_dict() for j in judgments]
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
