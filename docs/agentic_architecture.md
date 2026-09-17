# Current agent architecture

Read [current architecture](architecture.md), [Chapter 6 implementation map](implementation_chapter6.md)
and [active contract](decisions/bounded_joint_system_v1.md).

The current `xgap.api.answer` uses candidate construction, paid scope confirmation,
shared strong policy search and one execution. Clarification and estimated execution
share declared work units; common model/scope costs are separately accounted for.
The current release does not dynamically decide whether to call the initial model
or buy new statistics: those remain explicit limitations, not claimed savings.

The [historical agent architecture](agentic_architecture_history_20260917.md) retains
SGP/tool definitions and earlier profiles. These definitions remain useful; its
chronological task instructions do not describe the current default entry.
