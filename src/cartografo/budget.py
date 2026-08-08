import time
from dataclasses import dataclass


@dataclass
class Budget:
    max_states: int
    max_minutes: float
    _start: float = 0.0

    def __post_init__(self):
        self._start = time.monotonic()

    def status(self, states_recorded: int) -> str | None:
        """Returns a warning string once a limit is hit, else None. Soft limit: the
        agent is expected to wrap up and write map.md on its own — this is a nudge
        surfaced through tool results, not a hard kill switch."""
        elapsed_min = (time.monotonic() - self._start) / 60
        if states_recorded >= self.max_states:
            return f"Budget reached: {states_recorded}/{self.max_states} states recorded. Stop exploring now and write map.md."
        if elapsed_min >= self.max_minutes:
            return f"Budget reached: {elapsed_min:.1f}/{self.max_minutes} minutes elapsed. Stop exploring now and write map.md."
        return None
