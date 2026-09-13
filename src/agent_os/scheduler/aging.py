"""
Agent-OS Scheduler — Aging Policy

Prevents starvation by giving a priority bonus to processes
that have been waiting a long time (§22).
"""

from __future__ import annotations

import math

from agent_os.config.settings import get_settings


class AgingPolicy:
    """
    Aging policy for starvation prevention (§22).

    aging_bonus = floor(wait_time / interval_seconds), capped at max_bonus.
    """

    def __init__(self, settings=None, interval_seconds: float | None = None, max_bonus: int | None = None):
        s = settings or get_settings()
        self.interval_seconds = interval_seconds if interval_seconds is not None else s.scheduler.aging.interval_seconds
        self.max_bonus = max_bonus if max_bonus is not None else s.scheduler.aging.max_bonus
        self.enabled = s.scheduler.aging.enabled

    def calculate_bonus(self, wait_time: float) -> int:
        """
        Calculate the aging bonus for a given wait time.

        Returns:
            Integer bonus capped at max_bonus.
        """
        if not self.enabled or self.interval_seconds <= 0:
            return 0
        bonus = math.floor(wait_time / self.interval_seconds)
        return min(bonus, self.max_bonus)
