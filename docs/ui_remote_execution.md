# UI and CWRU Remote Execution Decision

## Decision

A UI is useful for demonstrations, clarification, and plan-trace inspection,
but it is not currently necessary for obtaining the core experimental results.
The first executable interface should remain a reproducible CLI plus structured
run artifacts. A thin UI should be added only after the M15-B coordinator API
is stable.

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

The missing piece is a general remote-executor plugin around SSH/Slurm, not a
new model-serving stack. Its interface should expose:

- `stage_run`
- `submit_job`
- `job_status`
- `stream_log`
- `cancel_job`
- `fetch_artifacts`

All operations must return normalized tool observations and measured control
cost. `cancel_job` is state-changing and must be separately allowlisted.

## UI go/no-go gate

Build a UI only after:

1. the M15-B CLI returns a correct cross-engine answer;
2. the goal state and trace serialize without UI-specific fields;
3. remote batch submission works through a CLI tool plugin;
4. at least one clarification action needs user interaction.

At that point a small local web application is sufficient: goal submission,
backend/tool status, semantic/federated plan view, clarification prompt,
live job state, and result/metric panels. No graph editor or full database
administration UI is required for the paper.
