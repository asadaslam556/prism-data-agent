"""Step budget for the agent loop.

A confused planner will happily loop forever, and even on a local model that
costs real time and compute. BudgetTracker counts steps per question; the plan
node checks `exhausted` and forces an answer at the cap.

One tracker is shared by every branch once the graph fans out, so the cap is
on total work rather than per branch. That means several threads bump the same
counters, hence the lock -- `self.steps += 1` is not atomic, and without it
parallel branches quietly lose steps and overrun the budget.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class BudgetTracker:
    max_steps: int
    steps: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_step(self) -> int:
        """Bump the counter and return this step's number (unique per caller)."""
        with self._lock:
            self.steps += 1
            return self.steps

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return self.steps >= self.max_steps
