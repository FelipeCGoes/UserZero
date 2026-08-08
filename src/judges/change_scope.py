"""
The `change_scope` judge: verifies that between two captures (before/after
a localized edit request), only the allowed section changed. Structural split
+ per-section hash + diff — never a naive full-string comparison, because
extra whitespace in another section should not count as a violation and a
subtle change inside a forbidden section should not escape detection.

spec:
  - { type: change_scope, before: report_text, after: report_text_v2,
      allowed_section: 2 }

Recognizes markdown headings (`#`, `##`, ...) or numbered headings ("2. Title",
"2 - Title"). Sections are 1-indexed in the order they appear in the `before`
text (the `after` text is compared section-by-section by the same order/title).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Tuple

HEADER_RE = re.compile(r"^(?:#{1,6}\s+|\d+[\.\)\-]\s+)(.+)$", flags=re.MULTILINE)


def _split_sections(text: str) -> List[Tuple[str, str]]:
    """Outputs [(title, body)] in the order they appear."""
    matches = list(HEADER_RE.finditer(text))
    if not matches:
        return [("(No detected sections)", text)]

    sections = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((title, body))
    return sections


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def judge(run: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    before_key = params["before"]
    after_key = params["after"]
    allowed_section = params["allowed_section"]  

    captures = run.get("captures") or {}
    before_text = captures.get(before_key)
    after_text = captures.get(after_key)

    if before_text is None or after_text is None:
        return {
            "pass": False,
            "evidence": {"reason": "missing before/after capture", "before": before_key, "after": after_key},
        }

    before_sections = _split_sections(before_text)
    after_sections = _split_sections(after_text)

    if len(before_sections) != len(after_sections):
        return {
            "pass": False,
            "evidence": {
                "reason": "number of sections changed between before/after",
                "before_count": len(before_sections),
                "after_count": len(after_sections),
            },
        }

    changed_indices: List[int] = []
    diffs = []
    for idx, ((b_title, b_body), (a_title, a_body)) in enumerate(zip(before_sections, after_sections), start=1):
        b_hash, a_hash = _hash(b_body), _hash(a_body)
        if b_hash != a_hash:
            changed_indices.append(idx)
            diffs.append({"section": idx, "title": b_title, "before_hash": b_hash, "after_hash": a_hash})

    unexpected = [i for i in changed_indices if i != allowed_section]
    allowed_did_change = allowed_section in changed_indices
    passed = len(unexpected) == 0

    return {
        "pass": passed,
        "evidence": {
            "allowed_section": allowed_section,
            "allowed_section_changed": allowed_did_change,
            "changed_sections": changed_indices,
            "unexpected_changes": unexpected,
            "diffs": diffs,
        },
    }
