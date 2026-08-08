"""
The `language` judge: detects the language of the captured text and compares
it against the expected language from the contract. Deterministic (fixed seed
for langdetect).

spec:
  - { type: language, target: report_text, expect: pt-BR }

Expected params: target (capture name), expect (language code,
accepts "pt-BR" or "pt" — only the portion before the hyphen is compared
because language detectors do not distinguish regional variants).
"""
from __future__ import annotations

from typing import Any, Dict

from langdetect import DetectorFactory, LangDetectException, detect_langs

DetectorFactory.seed = 0  


def judge(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    target = params["target"]
    expect = params["expect"]
    expect_base = expect.split("-")[0].lower()

    text = (run.get("captures") or {}).get(target)
    if not text or not text.strip():
        return {"pass": False, "evidence": {"reason": "empty or missing capture", "target": target}}

    try:
        candidates = detect_langs(text)
    except LangDetectException as e:
        return {"pass": False, "evidence": {"reason": f"detection failed: {e}", "target": target}}

    top = candidates[0]
    detected_base = top.lang.split("-")[0].lower()
    passed = detected_base == expect_base

    return {
        "pass": passed,
        "evidence": {
            "target": target,
            "expect": expect,
            "detected": top.lang,
            "confidence": round(top.prob, 4),
            "candidates": [f"{c.lang}:{round(c.prob, 3)}" for c in candidates[:3]],
        },
    }
