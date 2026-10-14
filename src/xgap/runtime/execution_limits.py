"""Execution admission controls, separate from symbolic completion bounds.

Timeout stops dispatch and signals invocation-scoped cancellation. Adapters
without cancellation drain under transport timeouts. Registered bytes exclude
in-flight buffers; max_response_bytes separately bounds each native HTTP body.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ExecutionLimits:
    dispatch_timeout_s: float | None = None
    max_registered_bytes: int | None = None
    per_backend_parallelism: int | None = None
    max_response_bytes: int | None = None

    max_spill_bytes: int = 1024**3

    def __post_init__(self):
        if type(self.max_spill_bytes) is not int or self.max_spill_bytes<1:
            raise ValueError("Spill byte limit must be a positive integer")
        if self.dispatch_timeout_s is not None and (
                type(self.dispatch_timeout_s) not in (int, float)
                or not math.isfinite(self.dispatch_timeout_s) or self.dispatch_timeout_s < 0):
            raise ValueError('Dispatch timeout must be finite and nonnegative')
        for value in (self.max_registered_bytes, self.per_backend_parallelism, self.max_response_bytes, self.max_spill_bytes):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError('Execution byte and parallelism limits must be positive integers')
