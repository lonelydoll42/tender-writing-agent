"""Small, explicit execution budget ledger."""

from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(Exception):
    """Raised when a runtime operation cannot reserve the requested budget."""


@dataclass
class BudgetLedger:
    token_capacity: int = 40_000
    step_capacity: int = 8
    tokens_used: int = 0
    steps_used: int = 0

    @property
    def tokens_remaining(self) -> int:
        return max(self.token_capacity - self.tokens_used, 0)

    @property
    def steps_remaining(self) -> int:
        return max(self.step_capacity - self.steps_used, 0)

    def reserve_step(self) -> bool:
        if self.steps_remaining <= 0:
            return False
        self.steps_used += 1
        return True

    def reserve_tokens(self, estimated: int) -> bool:
        estimated = max(int(estimated), 0)
        if estimated > self.tokens_remaining:
            return False
        self.tokens_used += estimated
        return True

    def commit_tokens(self, actual: int, estimated: int = 0) -> None:
        """Replace an estimate with actual usage without allowing negatives."""

        estimated = max(int(estimated), 0)
        actual = max(int(actual), 0)
        self.tokens_used = max(self.tokens_used - estimated + actual, 0)

    def snapshot(self) -> dict[str, int]:
        return {
            "token_capacity": self.token_capacity,
            "tokens_used": self.tokens_used,
            "tokens_remaining": self.tokens_remaining,
            "step_capacity": self.step_capacity,
            "steps_used": self.steps_used,
            "steps_remaining": self.steps_remaining,
        }
