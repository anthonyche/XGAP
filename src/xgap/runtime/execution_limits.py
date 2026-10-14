"""Execution admission controls, separate from symbolic completion bounds.

Timeout stops further dispatch; running backend calls must drain under their
transport timeouts. Registered bytes exclude in-flight and temporary buffers.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ExecutionLimits:
    dispatch_timeout_s: float | None = None
    max_registered_bytes: int | None = None
    per_backend_parallelism: int | None = None

    def __post_init__(self):
        if self.dispatch_timeout_s is not None and (
                type(self.dispatch_timeout_s) not in (int, float)
                or not math.isfinite(self.dispatch_timeout_s) or self.dispatch_timeout_s < 0):
            raise ValueError('Dispatch timeout must be finite and nonnegative')
        for value in (self.max_registered_bytes, self.per_backend_parallelism):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError('Execution byte and parallelism limits must be positive integers')
