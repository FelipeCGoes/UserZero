def ask_yes_no_with_feedback(prompt: str) -> tuple[bool, str | None]:
    """Blocks on console input — fine here: by the time this is called, the MCP
    browser session and the dry-run's browser are both already closed, so there's
    nothing else running concurrently for a blocking call to hold up."""
    answer = input(f"{prompt} [y/n]: ").strip().lower()
    if answer.startswith("y"):
        return True, None
    feedback = input("What should change? ").strip()
    return False, (feedback or None)


def print_flow_and_dry_run(spec: dict, dry_run: dict) -> None:
    """Flow confirmation: compiled steps side by side with what the dry-run (n=1,
    real browser, no LLM) actually observed — not just what the compiling agent
    self-reported. Contracts are bound to this flow, so confirming the flow itself
    comes first: rejecting it would invalidate any contract confirmation anyway."""
    print("\n=== CONFIRM: FLOW (dry-run n=1 result) ===")
    outcomes = {s["id"]: s for s in dry_run["steps"]}
    for step in spec["steps"]:
        outcome = outcomes.get(step["id"])
        marker = ("OK" if outcome["ok"] else f"FAIL ({outcome.get('error')})") if outcome else "not reached"
        detail = f" -> {step.get('selector') or step.get('url', '')}"
        capture = f"  [captures: {step['capture']['name']}]" if "capture" in step else ""
        print(f"- {step['id']}: {step['action']}{detail}{capture}  [{marker}]")

    if dry_run["captures"]:
        print("\nObserved captures (dry-run, n=1):")
        for name, value in dry_run["captures"].items():
            if value is None:
                print(f"- {name}: (empty — spec has no `capture.selector` to read from here)")
            else:
                preview = value if len(value) <= 200 else value[:200] + "..."
                print(f"- {name}: {preview!r}")


def print_contracts(contracts: list[dict]) -> None:
    print("\n=== CONFIRM: CONTRACTS ===")
    if contracts:
        for c in contracts:
            print(f"- {c}")
            if c.get("type") == "grounding" and not c.get("sources"):
                print("  ! INCOMPLETE: no `sources` — the Compilador never saw this content "
                      "(a pre-existing document it only selected, not typed or read). Add "
                      "`sources:` by hand before anything can judge this contract.")
    else:
        print("(none declared)")
    print("(suggested contracts from observed dry-run values: coming soon)")
