"""Step budget for the agent loop.

A confused planner will happily loop forever, and even on a local model that
costs real time and compute. BudgetTracker counts steps and LLM calls per
question; the plan node checks `exhausted` and forces an answer at the cap.

One tracker is shared by every branch once the graph fans out, so the cap is
on total work rather than per branch. That means several threads bump the same
counters, hence the lock -- `self.steps += 1` is not atomic, and without it
parallel branches quietly lose steps and overrun the budget.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class BudgetTracker:
    max_steps: int
    llm_calls: int = 0
    steps: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_llm_call(self) -> None:
        with self._lock:
            self.llm_calls += 1

    def record_step(self) -> int:
        """Bump the counter and return this step's number (unique per caller)."""
        with self._lock:
            self.steps += 1
            return self.steps

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return self.steps >= self.max_steps

    @property
    def elapsed_seconds(self) -> float:
        return round(time.perf_counter() - self.started_at, 2)

    def summary(self) -> dict[str, float | int]:
        return {
            "llm_calls": self.llm_calls,
            "steps": self.steps,
            "elapsed_seconds": self.elapsed_seconds,
        }
