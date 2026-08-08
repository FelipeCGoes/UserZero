"""
The `format` judge: checks required sections, absence of placeholders, and
optionally that the capture is JSON-parsable.

spec:
  - { type: format, target: report_text, sections: [Resumo, Análise, Riscos],
      no_placeholders: true }
  - { type: format, target: payload_json, json: true }

Covers what LLM API schema enforcement does not catch: truncation due to
max_tokens in the middle of text, malformed stream reassembly, forgotten
template placeholders, or post-processing that corrupted the output.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

PLACEHOLDER_PATTERNS = [
    r"\{\{.*?\}\}",           # {{placeholder}}
    r"\[\[.*?\]\]",           # [[placeholder]]
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bLorem ipsum\b",
    r"\bundefined\b",
    r"\bNaN\b",
    r"\[PLACEHOLDER\]",
]

# Commun signs that show max_tokens was reached and the text was truncated, or that the stream was  cut off mid-sentence. These are heuristics, not guaranteed to be correct.
TRUNCATION_PATTERNS = [
    r",\s*$",               
    r"\.\.\.\s*$",          
]


def judge(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    target = params["target"]
    text = (run.get("captures") or {}).get(target)

    if text is None:
        return {"pass": False, "evidence": {"reason": "missing capture", "target": target}}

    if params.get("json"):
        return _judge_json(text, target)

    problems: List[str] = []

    expected_sections = params.get("sections", [])
    missing = [s for s in expected_sections if s.lower() not in text.lower()]
    if missing:
        problems.append(f"missing sections: {missing}")

    if params.get("no_placeholders", False):
        found_placeholders = [
            m.group(0)
            for pat in PLACEHOLDER_PATTERNS
            for m in re.finditer(pat, text, flags=re.IGNORECASE)
        ]
        if found_placeholders:
            problems.append(f"placeholders found: {found_placeholders[:5]}")

    stripped = text.strip()
    if params.get("check_truncation", True) and stripped:
        if any(re.search(pat, stripped) for pat in TRUNCATION_PATTERNS):
            problems.append("possible truncation at end of text")

    passed = len(problems) == 0
    return {
        "pass": passed,
        "evidence": {
            "target": target,
            "problems": problems,
            "chars": len(text),
            "sections_checked": expected_sections,
        },
    }


def _judge_json(text: str, target: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return {
            "pass": False,
            "evidence": {"target": target, "reason": f"Invalid JSON: {e}"},
        }
    return {"pass": True, "evidence": {"target": target, "keys": _top_level_keys(parsed)}}


def _top_level_keys(parsed: Any) -> Any:
    if isinstance(parsed, dict):
        return list(parsed.keys())
    if isinstance(parsed, list):
        return f"list with {len(parsed)} items"
    return type(parsed).__name__
