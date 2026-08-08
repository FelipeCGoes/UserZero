from pathlib import Path

CONTRACT_SCHEMA = {
    "title": "ContractList",
    "description": "Contracts to attach to a compiled flow spec, per DESIGN.md's catalog.",
    "type": "object",
    "properties": {
        "contracts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["language", "format", "latency", "grounding", "change_scope"],
                    },
                    "target": {"type": "string", "description": "Capture name this contract checks (language/format/grounding)."},
                    "expect": {"type": "string", "description": "Expected language code, e.g. pt-BR (language contracts)."},
                    "sections": {"type": "array", "items": {"type": "string"}, "description": "Required section headings (format contracts)."},
                    "no_placeholders": {"type": "boolean", "description": "Fail if template placeholders leak into output (format contracts)."},
                    "from": {"type": "string", "description": "Step id marking the start of the timed window (latency contracts)."},
                    "to": {"type": "string", "description": "Step id marking the end of the timed window (latency contracts)."},
                    "p95_max_s": {"type": "number", "description": "p95 latency ceiling in seconds (latency contracts)."},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "What every claim must trace back to (grounding contracts): either a fixture file path, or the id of a step whose own `value` IS the source content (e.g. text the flow typed into an upload form). Omit entirely if the flow never observed the actual source content — never invent a path."},
                    "before": {"type": "string", "description": "Capture name before the edit (change_scope contracts)."},
                    "after": {"type": "string", "description": "Capture name after the edit (change_scope contracts)."},
                    "allowed_section": {"type": "integer", "description": "The only section (1-indexed) allowed to differ between before/after (change_scope contracts)."},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["contracts"],
}


def derive_contracts(llm, contracts_description: str | None, steps: list[dict]) -> list[dict]:
    """One cheap, non-agentic structured-output call: maps the user's natural-language
    description of expected behavior onto the DESIGN.md contract schema, bound to the
    capture names and step ids that actually exist in the compiled flow. Returns an
    empty list if the user didn't describe any expected behavior for this flow —
    contracts are an explicit opt-in here, never invented on the flow's behalf. (A
    later Executor dry-run pass is where automatic contract proposals from observed
    values belong — this function only formalizes what the user already said.)"""
    if not contracts_description:
        return []

    captures = [s["capture"]["name"] for s in steps if "capture" in s]
    step_ids = [s["id"] for s in steps]
    step_lines = "\n".join(
        f"- {s['id']}: {s['action']}" + (f" (capture: {s['capture']['name']})" if "capture" in s else "")
        for s in steps
    )
    # Steps whose own `value` is content the flow itself typed in (e.g. authoring the
    # body of a document it then uploads) are the ONLY thing that can ever fill a
    # grounding contract's `sources` here — the Compilador has no way to see the
    # content of anything it didn't type or read itself (a pre-existing document the
    # flow merely selected is opaque to it). Surface those candidates explicitly
    # instead of leaving the model to guess a file path that doesn't exist.
    content_steps = [(s["id"], s["value"]) for s in steps if s.get("value")]
    content_lines = "\n".join(f"- {sid}: {value[:200]!r}" for sid, value in content_steps) or "(none)"
    # Pair each capture with the question/goal that produced it, so the model can check
    # per-capture whether a content step's document is actually what THAT capture is
    # about — a single available content step must not get reused as the source for
    # every capture just because it's the only one on hand.
    capture_context_lines = []
    for i, s in enumerate(steps):
        if "capture" not in s:
            continue
        question = next((p["value"] for p in reversed(steps[:i]) if p.get("action") == "fill" and p.get("value")), None)
        capture_context_lines.append(
            f"- {s['capture']['name']}: goal={s.get('goal', '')!r}" + (f", question={question!r}" if question else "")
        )
    capture_context = "\n".join(capture_context_lines) or "(none)"
    prompt = (
        "Flow steps compiled so far:\n" + step_lines +
        f"\n\nAvailable capture names: {captures}\nAvailable step ids: {step_ids}\n\n"
        "Steps whose `value` is literal content the flow typed into the app (candidate "
        f"grounding sources — reference the step id, not a file path):\n{content_lines}\n\n"
        f"What each capture is actually about:\n{capture_context}\n\n"
        f"User's description of expected behavior for this flow:\n{contracts_description}\n\n"
        "Produce contracts using ONLY the capture names and step ids listed above — never "
        "invent a name that isn't in those lists. If a part of the description doesn't map "
        "cleanly onto one of the 5 contract types (language, format, latency, grounding, "
        "change_scope), leave it out rather than guessing. For grounding contracts: judge "
        "EACH capture independently against 'what each capture is actually about' above — "
        "set `sources` to a content step's id ONLY if that specific capture's question is "
        "actually about that step's document. A content step being available does NOT mean "
        "every capture should cite it — most flows ask about several different documents, "
        "and only some of them were ever typed in by the flow itself. Still create the "
        "grounding contract for every capture the description says should be grounded — "
        "when a capture's question is about a document with no matching content step, leave "
        "`sources` OUT of that contract rather than reusing an unrelated step's id; do NOT "
        "drop the contract entirely just because you don't know the source. An incomplete "
        "grounding contract is a visible signal for a human to add the right source by hand; "
        "a missing one looks like grounding was never asked for."
    )
    # method="function_calling" deliberately, not the default: this model has already
    # proven itself reliable at tool-calling (every record_step call during the run
    # above), whereas raw JSON-mode output is where it has been observed to degenerate
    # into repetitive garbage on longer prompts (many steps/captures) and blow up the
    # parser. Belt-and-suspenders: still never let a bad response here cost the already-
    # compiled steps — this must degrade to "no contracts", never crash the whole run.
    structured_llm = llm.with_structured_output(CONTRACT_SCHEMA, method="function_calling")

    # Observed directly: identical inputs, no exception either time, yet one call
    # returned 12 well-formed contracts and another returned none — single-shot model
    # flakiness, not a schema/parsing failure (that path is the except below). A
    # description was explicitly provided, so an empty result is suspicious rather
    # than a legitimate "nothing applies" answer — worth one retry before giving up.
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            result = structured_llm.invoke(prompt)
        except Exception as exc:  # noqa: BLE001 — see comment further up
            if attempt == max_attempts:
                print(f"WARNING: contract derivation failed ({type(exc).__name__}: {exc}) — "
                      "spec.yaml will have no contracts. Edit it by hand or re-run with --contracts.")
                return []
            continue

        contracts = result.get("contracts", []) if isinstance(result, dict) else getattr(result, "contracts", [])
        if contracts:
            return contracts
        if attempt == max_attempts:
            print(f"WARNING: contract derivation returned no contracts after {max_attempts} attempt(s), "
                  f"despite --contracts being provided ({contracts_description!r}) — this looks like "
                  "model flakiness on this call, not a real 'nothing applies' answer. Edit spec.yaml by "
                  "hand or re-run.")
    return []


def materialize_grounding_sources(contracts: list[dict], steps: list[dict], output_dir: Path) -> list[dict]:
    """The Judges catalog (built separately, per DESIGN.md) reads a grounding
    contract's `sources` as file paths on disk. Ours can instead be a step id —
    the id of a step whose own `value` IS the source content, when the flow typed
    the content in itself rather than reading a pre-existing file. Rather than
    teach the judge about step-id references, resolve that gap here: write the
    step's value out as a real file so the file-based judge works unmodified.
    Anything already a real path, or that doesn't resolve to a known step either,
    is left untouched — there's nothing more we can do with it on this side."""
    steps_by_id = {s["id"]: s for s in steps}
    sources_dir = output_dir / "sources"

    for contract in contracts:
        if contract.get("type") != "grounding" or not contract.get("sources"):
            continue
        resolved = []
        for source in contract["sources"]:
            if Path(source).exists():
                resolved.append(source)
                continue
            step = steps_by_id.get(source)
            if step is None or step.get("value") is None:
                resolved.append(source)
                continue
            sources_dir.mkdir(parents=True, exist_ok=True)
            path = sources_dir / f"{source}.txt"
            path.write_text(step["value"], encoding="utf-8")
            resolved.append(str(path.resolve()))
        contract["sources"] = resolved

    return contracts


def derive_and_materialize_contracts(llm, contracts_description: str | None, steps: list[dict],
                                      output_dir: Path) -> list[dict]:
    """derive_contracts() + materialize_grounding_sources() in one call — the two
    call sites (initial compile, and the contracts-only retry loop) both need both
    steps, so this keeps them a one-line swap instead of duplicating the pairing."""
    contracts = derive_contracts(llm, contracts_description, steps)
    return materialize_grounding_sources(contracts, steps, output_dir)
