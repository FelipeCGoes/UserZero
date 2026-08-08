"""Shared types. No logic — just data shape."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Judgment:
    """Judge output for a contract applied to a specific run."""

    run: int
    contract_id: str
    type: str
    passed: bool
    evidence: Any = None
    error: Optional[str] = None  # populated if the judge could not even evaluate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run": self.run,
            "contract_id": self.contract_id,
            "type": self.type,
            "pass": self.passed,
            "evidence": self.evidence,
            "error": self.error,
        }


@dataclass
class Contract:
    """A contract declared in spec.yaml, normalized with a unique id."""

    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)


def contracts_from_spec(spec: Dict[str, Any]) -> List[Contract]:
    """Reads spec['contracts'] (a list of loose dicts, DESIGN.md shape) and
    normalizes them into Contract objects with a stable unique id (type +
    target/from-to, improving report readability; falls back to an index if
    there is no disambiguator)."""
    out: List[Contract] = []
    counts: Dict[str, int] = {}
    for raw in spec.get("contracts", []):
        c_type = raw["type"]
        params = {k: v for k, v in raw.items() if k != "type"}

        if c_type == "latency":
            disambiguator = f"{params.get('from')}-{params.get('to')}"
        else:
            disambiguator = params.get("target") or params.get("before") or ""

        idx = counts.get(c_type, 0)
        counts[c_type] = idx + 1
        cid = f"{c_type}:{disambiguator}" if disambiguator else f"{c_type}#{idx}"
        if any(c.id == cid for c in out):
            cid = f"{cid}#{idx}"

        out.append(Contract(id=cid, type=c_type, params=params))
    return out
