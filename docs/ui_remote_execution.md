# UI and CWRU Remote Execution Decision

## Decision and current gate status

A UI is useful for demonstrations, clarification, and plan-trace inspection,
but it is not part of the paper experiment mechanism. The reproducible CLI and
structured run artifacts remain authoritative. The original four-condition UI
gate is now satisfied: the cross-engine CLI, portable goal trace, SSH/Slurm
remote executor, and bounded clarification transport all exist. E6 may
therefore add a thin local working surface without changing experiment logic.

This avoids coupling correctness and benchmark automation to a web framework,
while ensuring the eventual UI visualizes the same goals, tool calls,
observations, plans, costs, and results used in experiments.

## Recommended architecture

```text
Local browser
  -> thin local XGAP UI/API
     -> local deterministic planning and artifact viewer
     -> remote-executor plugin
        -> SSH to CWRU login environment
        -> submit/poll/cancel Slurm job
        -> coordinator + Neo4j/Fuseki + optional vLLM inside allocation
        -> retrieve immutable result artifacts
```

The UI must not communicate directly with vLLM or a compute-node port for the
normal experiment path. The remote-executor plugin should submit jobs, poll
Slurm state, stream bounded logs, and retrieve artifacts. This batch design is
more reproducible and robust to VPN or laptop disconnection.

An optional interactive-demo mode may use an SSH local-forward tunnel to a
short-lived API inside an allocated job. It requires a valid CWRU network path,
must bind the remote service to loopback, and must terminate with the Slurm
allocation. It should not be the paper experiment mechanism.

## VPN and authentication boundary

The local machine audit on 2026-09-04 found no `~/.ssh/config` and found the
configured Fortinet CWRU VPN disconnected. CWRU now documents OpenVPN
CloudConnexa as its VPN platform and states that legacy FortiClient service
ended after 2026-05-31:

- <https://vpnsetup.case.edu/>
- <https://case.edu/utech/help/vpn>

Before implementing live remote submission, configure and test OpenVPN, then
create a user-owned SSH host alias for the Pioneer login host. XGAP should read
only that alias. Passwords, Duo responses, private keys, and VPN credentials
must never be stored in repository config or run artifacts.

## Feasibility

Remote integration is feasible. The repository already contains CWRU Slurm
wrappers and a loopback-only vLLM deployment contract. The public Pioneer
resource page also currently lists the `gpu2h100` resources used by the frozen
environment contract:

- <https://ondemand-pioneer.case.edu/public/sinfo_pioneer.html>

The remote-executor plugin around SSH/Slurm now exposes:

- `stage_run`
- `submit_job`
- `job_status`
- `stream_log`
- `cancel_job`
- `fetch_artifacts`

All operations must return normalized tool observations and measured control
cost. `cancel_job` is state-changing and must be separately allowlisted.

E6A closes the remaining clarification-submission gap. `submit_job` may carry
an explicit per-job environment object, but every key is checked against the
selected Slurm script rather than a global list. Only the E5D selected-session
wrapper accepts the six non-secret historical-memory and authority fields.
Values are passed as an argument vector, never shell-interpolated; commas,
whitespace, newlines, equals signs, and oversized values fail before SSH.
Other wrappers accept none of those fields. Fixed Python/Java module settings
remain separately configured, and credential-shaped variables are never in an
allowlist.

## UI go/no-go gate

The UI gate required:

1. the M15-B CLI returns a correct cross-engine answer;
2. the goal state and trace serialize without UI-specific fields;
3. remote batch submission works through a CLI tool plugin;
4. at least one clarification action needs user interaction.

All four conditions now hold. The next UI slice is a small local working
surface: clarification prompt first, sealed selection preview, explicit submit,
live job state, bounded logs, and immutable result/metric panels. It must call
the typed remote executor rather than build shell commands, must not expose a
generic environment editor, and must never contact vLLM or graph backends
directly. No graph editor or database-administration UI is required.
