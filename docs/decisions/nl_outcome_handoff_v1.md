# Separate the answer handoff from the full execution trace

2026-09-13 observed integration defect, after the scheduled two NL groups ended.
All four XGAP core receipts report answered/one model/one final plan, but their
333–344MB result.json traces exceed the16MiB frozen-input reader used by the outer
NL worker. The worker fails after execution and incorrectly keeps its initialized
zero call/token counts. Original method outcomes and EM0 scores remain unchanged.

Scope extends the release milestone only to one_shot_records, nl_method_worker,
focused file-boundary tests and evidence. No model/prompt/semantic/planner/estimator/
baseline changes. No failed question rerun, no global increase of the input limit.

Write an additional hash-pinned outcome containing success/status, unchanged answer
rows and timing fields, linked to the full trace pin. The online outer worker reads
this artifact, not all intermediate execution rows. Preserve the full trace and
its hash for diagnosis/replay. No answer truncation or altered normalization. The
existing bounded file reader remains; an oversized final answer still fails
explicitly rather than silently clipping data. This is not a streaming executor.

Copy known core usage/final-execution counts into the outer receipt before reading
the outcome, so a subsequent serialization/integrity failure cannot become a zero
cost claim. A still-active invocation with unknown usage remains unknown. If the
new handoff fails to persist, propagate the recorded failure. Older receipts without
the new field keep their original small-trace read behavior; do not reinterpret or
rescore the saved campaign as successful after the fact.

Acceptance: a synthetic trace larger than16MiB passes through the actual record and
NL-worker file handoff with exact rows and usage, without reading that trace; corrupt
handoff fails and retains known usage; trace-link mismatch/legacy behavior stay
explicit. Tests inject model/backend execution, so they make zero external calls
and cannot establish live query quality. Then use the next unrun scheduled group
for the actual boundary, with an explicit implementation epoch and unchanged inputs.
Full trace persistence remains in the online cost; no artificial speedup from
subtracting it. RQ is valid E2E measurement, X is trace volume, Y is correct return
and complete cost accounting.

Three unique new checks first pass in0.34s, including actual record producer ->
outer NL worker -> post-seal scoring over a synthetic trace exceeding16MiB.
Corrupt summary retains model/token/final-plan counts; mismatched trace linkage
fails, explicit missing summary does not fall back, and legacy small records read.
No external calls or old question retries. Next live gate is unrun RDF NL group5.
