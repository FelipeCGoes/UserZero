import time
from dataclasses import dataclass


@dataclass
class Budget:
    """Generic soft limit on count + elapsed time, shared by every agent that needs
    to tell its own LLM loop when to wrap up (Cartógrafo counts states, Compilador
    counts steps — the arithmetic is identical either way). Soft limit: the agent is
    expected to wrap up on its own — this is a nudge surfaced through a tool result,
    not a hard kill switch. Reason phrasing (what "recorded" means, what to do once
    hit) is the caller's job, not this class's — see each agent's tools.py."""

    max_units: int
    max_minutes: float
    _start: float = 0.0

    def __post_init__(self):
        self._start = time.monotonic()

    def status(self, units_recorded: int) -> str | None:
        """Returns a short reason string once a limit is hit, else None."""
        elapsed_min = (time.monotonic() - self._start) / 60
        if units_recorded >= self.max_units:
            return f"{units_recorded}/{self.max_units} recorded"
        if elapsed_min >= self.max_minutes:
            return f"{elapsed_min:.1f}/{self.max_minutes} minutes elapsed"
        return None
