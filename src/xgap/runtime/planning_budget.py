"""Cooperative planning checkpoints, never a hard real-time interruption claim."""
import math
import time
from typing import Callable


class PlanningBudgetExpired(RuntimeError):
    """Optional planning stopped; this is not an unsupported source/strategy."""


class CooperativePlanningBudget:
    def __init__(self,milliseconds: float,*,clock: Callable[[],float]=time.perf_counter):
        if type(milliseconds) not in (int,float) or not math.isfinite(milliseconds) or milliseconds<=0:
            raise ValueError('Planning budget must be finite and positive')
        self.clock=clock;self.deadline=clock()+milliseconds/1000
        self.checks=0;self.expired=False

    def __call__(self) -> None:
        self.checks+=1
        if self.clock()>=self.deadline:
            self.expired=True
            raise PlanningBudgetExpired('Cooperative planning deadline reached; retain completed feasible plans')

    def to_dict(self) -> dict:
        return {'checks':self.checks,'expired':self.expired,
            'scope':'optional physical construction/scoring; first feasible compilation may finish atomically',
            'hard_real_time_bound':False}
