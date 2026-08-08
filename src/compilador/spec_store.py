from pathlib import Path

import yaml


class SpecBuilder:
    """Accumulates spec.yaml incrementally as the Compilador agent executes the flow
    once for real, so the spec is a side-effect of tool calls rather than something
    the LLM has to emit correctly as one big YAML blob at the end — same principle as
    Cartógrafo's GraphBuilder."""

    def __init__(self, flow: str, mode: str = "ui"):
        self.flow = flow
        self.mode = mode
        self.steps: list[dict] = []
        self.contracts: list[dict] = []

    def record_step(self, step_id: str, action: str, selector: str | None = None,
                     url: str | None = None, value: str | None = None, file: str | None = None,
                     timeout_ms: int | None = None, goal: str | None = None,
                     capture_name: str | None = None, capture_latency: bool = False,
                     capture_selector: str | None = None) -> str:
        step = {"id": step_id, "action": action}
        if url:
            step["url"] = url
        if selector:
            step["selector"] = selector
        if value is not None:
            step["value"] = value
        if file:
            step["file"] = file
        if timeout_ms:
            step["timeout_ms"] = timeout_ms
        if goal:
            step["goal"] = goal

        warning = None
        if capture_name:
            capture = {"name": capture_name}
            if capture_selector:
                capture["selector"] = capture_selector
            if capture_latency:
                capture["latency"] = True
            step["capture"] = capture
            # A capture is only ever readable from capture_selector, or — absent that —
            # from a wait_for step's own selector (what's being waited for IS the
            # content). Anything else (e.g. a bare capture on a `click`) has no
            # declared read target: the Executor will return None for it rather than
            # guess, so flag it immediately here instead of losing 16 steps of real
            # browser work to a mistake that only shows up much later at replay time.
            if not capture_selector and action != "wait_for":
                warning = (
                    f"WARNING: capture '{capture_name}' on this '{action}' step has no way to "
                    "read a value — only a wait_for step's own selector (or an explicit "
                    "capture_selector) is ever readable. Add a wait_for step targeting the "
                    "element that actually shows the result and put this capture there instead."
                )

        self.steps.append(step)
        outcome = f"recorded step '{step_id}' ({action})"
        return outcome + (f"\n{warning}" if warning else "")

    def to_dict(self) -> dict:
        return {"flow": self.flow, "mode": self.mode, "steps": self.steps, "contracts": self.contracts}

    def write(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "spec.yaml"
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        return path
