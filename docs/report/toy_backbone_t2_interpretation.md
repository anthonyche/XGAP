# T2-B: question Interpretation connects to the deterministic backbone

2026-09-11; base174393d. Accepted: native, focused and final regression gates pass.

The provider-neutral question entry accepts an explicit question/context and
required hard constraints, admits one typed semantic DAG with source assignments,
then invokes the existing pinned catalog/resolution/planning/execution chain.
Interpretation remains independently callable/testable. Catalog preparation is
checked before provider dispatch. Provider errors and invalid interpretations
stop before backend execution; no automatic repair/retry occurs. Usage and raw
response are retained separately from semantic and answer correctness.

The existing deterministic intake now accepts optional executable constraint
predicates. Its adapter moves legacy hole-ownership annotations into provenance,
so they do not become unsupported executable parameters. Template file hashing
and parsing now consume the same bounded bytes. Existing legacy templates retain
their behavior. This is a controlled phrase-template provider, not a general NL
parser or a real model result. Declared entity holes still use catalog authority
and explicit ambiguity handling; provider metadata is not resolution authority.

The provider journal saves exact requests/context/version, raw structured output
or a safe explicit failure. A replay matches each recorded call, never falls
back to a live provider, and counts zero new external calls/tokens. Historical
usage remains separate. Changed requests, exhausted and unused calls are explicit.
Two minimal authored failure recordings remain in the new input fixture. These
are controlled development failures, not recordings of the old GPU hardware error.
General backend/tool transcript replay is not implemented by this boundary.

| Gate | Evidence |
|---|---|
| Independent Interpretation |5/5 programs match old gold meaning, with only identity/provenance differences |
| Final focused49491 |77 passed in2.32s |
| Daily81728 |546 passed in30.01s plus18 original demos; the later strict request-identity case is included in final focused/full |
| Native71146 |5/5 question programs,18/18 candidate answers,10/10 independent targets and original two-engine slice correct |
| Final full58858 |Exit0:3394 passed/38 skipped in674.23s; all24 harness/example entrypoints pass |

Native output: `/Users/anthonyche/xgap-data/t2-interpretation-native-20260911`.
The only final native source delta is admission in interpretation.py: preset
entity candidates are rejected and provider input is defensively copied. Old
bytes were reconstructed and match the native hash; other33 source hashes match.
All5 current interpreted programs exactly equal the successful native programs. Source calls remain
18 observations+9 serving+25 extra candidate validation+10 independent targets+
2 retained slice calls; controlled clarification is accounted separately.
Both owned Neo4j5.26.30/Fuseki5.6.0 services stopped normally without KILL.
Original graph, old binding gold, catalog and independent target queries stay
unchanged; new inputs comprise two explicitly selected template families.

First focused43107 had67 pass/5 failures: the compiler rejected the old intake
ownership annotation as an unknown Project parameter. The adapter correction
produced72/2.37s, then74/2.39s and final75/2.39s as replay checks were completed.
An earlier local probe also caught rejection of the existing derived is_resolved
field; the parser now validates its consistency with candidates. These are local
development observations. The native gate had no failure or external retry.
Full85404 was deliberately interrupted (2504 passed/37 skipped/575.35s, exit2)
after observing that the legacy resolver trusts singleton program candidates.
The new boundary now rejects entity candidates supplied by Interpretation and
protects caller constraints from provider mutation; focused77 passed. Final
full58858 follows these corrections. No source/test changes after its launch;
full58858 is terminal exit0:3394 passed/38 skipped/674.23s and all24
harness/example entrypoints passed. All handles are terminal; final37 source
hashes match the receipt and old tracked fixtures are unchanged.

The latest user deadline supersedes the previous next-milestone order. After
this interface gate, proceed directly to real-model integration on the tiny
graph, then frozen real-data comparisons bySeptember18. Do not spend this week
first expanding general replay, UI or catalog rebuilds. See
[delivery plan](../experiment_delivery_20260918.md). Overall Goal stays active;
legacy GrailQA migration and the broader system/evaluation obligations remain.
