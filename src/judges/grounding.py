"""
The `grounding` judge (semantic, calls an LLM): extracts factual claims from
a capture and verifies each one against the source documents declared in
the spec. One failure mode is a claim not supported by the source(s).

spec:
  - { type: grounding, target: report_text, sources: [fixtures/fonte.pdf] }

Uses the shared `get_llm()` from common/llm.py (Featherless via
langchain-openai) with `with_structured_output`, matching the pattern that
DESIGN.md already defines for semantic judges (LangChain + structured
output, one failure mode per judge). temperature=0 because, even though
this uses an LLM, the criterion is fixed: every claim supported = pass;
any unsupported claim = contract fails with a list as evidence.

Source text extraction is intentionally simple (plain txt/md only).
PDF sources are not supported by this implementation, so they will be
reported as unavailable.
"""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from common.llm import get_llm

GROUNDING_SYSTEM_PROMPT = """\
You are a grounding verifier. You will receive GENERATED TEXT and one or
more SOURCES. Your task:
1. Extract verifiable factual claims from the GENERATED TEXT: numbers,
   dates, names, locations, amounts, relationships, and concrete statements.
   Ignore opinion, marketing language, and transitions.
2. For each claim, verify whether it is supported by the SOURCES.
   A claim is supported if all factual details are present in the sources,
   even if the source text expresses them in separate sentences or with
   different wording.
3. List ONLY the claims that are NOT supported, with a short quote from the
   GENERATED TEXT where the claim appears.
4. Use the same language as the GENERATED TEXT for all fields. If the
   GENERATED TEXT is Portuguese, write the claim, quote, and reason in
   Portuguese. If it is English, write them in English.

Respond STRICTLY with a JSON object in this format and nothing else:
{{
  "unsupported_claims": [
    {{"claim": "...", "quote": "...", "reason": "..."}}
  ]
}}

If all claims are supported, respond with {{"unsupported_claims": []}}.
Never omit the key "unsupported_claims" or set it to null — always use a
list, empty if there are no unsupported claims."""


class UnsupportedClaim(BaseModel):
    claim: str = Field(description="A factual claim not supported by the sources")
    quote: str = Field(description="Short excerpt from the generated text where the claim appears")
    reason: str = Field(description="Why the claim is not supported by the sources")


class GroundingResult(BaseModel):
    unsupported_claims: List[UnsupportedClaim] = Field(default_factory=list)


_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", GROUNDING_SYSTEM_PROMPT),
        ("human", "GENERATED TEXT:\n{text}\n\nSOURCES:\n{sources_text}"),
    ]
)


def _read_source(path: str) -> str:
    if not os.path.exists(path):
        return f"[MISSING SOURCE: {path}]"
    if path.lower().endswith(".pdf"):
        return f"[PDF source not supported: {path}]"
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _normalize_text(text: str) -> str:
    normalized = text.lower()
    normalized = re.sub(r"[^a-z0-9ãâàáéêíõôóúçñäëïöü\s]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _split_sentences(text: str) -> List[str]:
    return [sentence.strip() for sentence in re.split(r"[.!?;\n]+", text) if sentence.strip()]


def _is_claim_supported(claim: str, sources_text: str) -> bool:
    normalized_claim = _normalize_text(claim)
    normalized_sources = _normalize_text(sources_text)

    if not normalized_claim:
        return False

    if normalized_claim in normalized_sources:
        return True

    claim_tokens = [tok for tok in normalized_claim.split() if len(tok) > 1]
    source_tokens = set(normalized_sources.split())
    if claim_tokens:
        matching_tokens = [tok for tok in claim_tokens if tok in source_tokens]
        if len(matching_tokens) / len(claim_tokens) >= 0.75:
            return True

    for sentence in _split_sentences(normalized_sources):
        if _similarity(normalized_claim, sentence) >= 0.75:
            return True

    return False


def _fallback_unsupported_claims(claims: List[Dict[str, Any]], sources_text: str) -> List[Dict[str, Any]]:
    if not claims:
        return []

    fallback = []
    for claim in claims:
        if _is_claim_supported(claim.get("claim", ""), sources_text):
            continue
        fallback.append(claim)
    return fallback


def judge(run: Dict[str, Any], params: Dict[str, Any], llm: Optional[Any] = None) -> Dict[str, Any]:
    target = params["target"]
    source_paths: List[str] = params.get("sources", [])

    text = (run.get("captures") or {}).get(target)
    if not text or not text.strip():
        return {"pass": False, "evidence": {"reason": "empty or missing capture", "target": target}}

    if not source_paths:
        return {"pass": False, "evidence": {"reason": "spec did not declare `sources` for grounding"}}

    sources_text = "\n\n---\n\n".join(f"[{p}]\n{_read_source(p)}" for p in source_paths)

    model = (llm or get_llm(temperature=0.0)).with_structured_output(GroundingResult, method="json_mode")
    chain = _PROMPT | model

    try:
        result: Optional[GroundingResult] = chain.invoke({"text": text, "sources_text": sources_text})
    except Exception as e:
        # infrastructure failure (network, key, model offline) is different from
        # contract failure — do not confuse the two.
        return {"pass": False, "evidence": {"reason": f"judge could not evaluate: {e}"}, "error": str(e)}

    if result is None:
        # the model did not follow the structured schema (common with models
        # that do not reliably honor tool-calling/json-mode) — infrastructure
        # failed, not a contract failure
        return {
            "pass": False,
            "evidence": {"reason": "model did not return valid structured output"},
            "error": "structured_output_returned_none",
        }

    if isinstance(result, dict):
        raw_claims = result.get("unsupported_claims") or []
        unsupported = [
            c if isinstance(c, dict) else c.model_dump()
            for c in raw_claims
        ]
    else:
        unsupported = [c.model_dump() for c in (result.unsupported_claims or [])]

    unsupported = _fallback_unsupported_claims(unsupported, sources_text)
    passed = len(unsupported) == 0

    return {
        "pass": passed,
        "evidence": {
            "target": target,
            "sources": source_paths,
            "unsupported_claims": unsupported,
        },
    }