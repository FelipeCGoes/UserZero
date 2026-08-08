"""
Judge catalog v0 (DESIGN.md): the judge TYPE is fixed in code;
WHICH instances run, with which parameters, is declared by the spec.

Signature: judge(run: dict, params: dict) -> {"pass": bool, "evidence": ...}
`grounding` accepts an optional extra kwarg `llm` (default: common.llm.get_llm())
because it is the only judge that talks to a model — the others are pure functions.
"""
from __future__ import annotations

from . import change_scope, format, grounding, language, latency

JUDGE_REGISTRY = {
    "language": language.judge,
    "format": format.judge,
    "latency": latency.judge,
    "change_scope": change_scope.judge,
    "grounding": grounding.judge,
}

DETERMINISTIC_TYPES = {"language", "format", "latency", "change_scope"}
SEMANTIC_TYPES = {"grounding"}

__all__ = ["JUDGE_REGISTRY", "DETERMINISTIC_TYPES", "SEMANTIC_TYPES"]
