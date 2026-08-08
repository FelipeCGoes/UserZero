from langchain_core.tools import tool

from common.budget import Budget
from compilador.spec_store import SpecBuilder


def build_recording_tools(spec: SpecBuilder, budget: Budget) -> list:
    """Local (non-MCP) tools the Compilador agent uses to write spec.yaml
    incrementally, closing over this run's SpecBuilder/Budget."""

    @tool
    def record_step(step_id: str, action: str, selector: str | None = None, url: str | None = None,
                     value: str | None = None, file: str | None = None, timeout_ms: int | None = None,
                     goal: str | None = None, capture_name: str | None = None,
                     capture_latency: bool = False, capture_selector: str | None = None) -> str:
        """Record one step of the flow being compiled. `action` is one of goto, click,
        fill, upload, wait_for. Pass `url` for goto; `selector` for click/fill/upload/
        wait_for, in priority order [data-testid] (or the app's own data-test/data-qa/
        data-cy variant) > role=...[name="..."] > plain text — never an MCP ref, it's
        meaningless outside this session. Pass `value` for fill, `file` for upload,
        `timeout_ms` for wait_for. `goal` is a short sentence on *why* this step exists —
        the Healer reads it later to re-find a broken selector, so make it specific.

        Pass `capture_name` (short snake_case) when this step's result should be kept
        for judging later (e.g. the final chat answer). A capture is ONLY ever readable
        from a `wait_for` step's own `selector` (what's being waited for IS the content
        — e.g. wait_for the answer container, then capture it) — never from a `click`'s
        selector, which is just the button you pressed, not the result. If the content
        to capture genuinely lives somewhere other than this step's own `selector`, pass
        `capture_selector` explicitly instead. Add `capture_latency=True` to also time
        how long it took to reach this step."""
        outcome = spec.record_step(step_id, action, selector, url, value, file, timeout_ms,
                                    goal, capture_name, capture_latency, capture_selector)
        reason = budget.status(len(spec.steps))
        warning = f"Budget reached: {reason}. Stop acting now and give your final summary." if reason else None
        return outcome + (f"\n{warning}" if warning else "")

    return [record_step]
