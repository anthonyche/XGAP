# Freeze contribution-v2 for the remaining NL campaign

2026-09-13 bounded milestone; ordinary one-shot interface and deterministic
contribution execution are implemented. Its retained tiny NL failure is an
effectiveness observation, not grounds for retrying or tuning that question.

Publish native/RDF children using the already tested contribution profile helper.
Verify that facts, schema, catalog, estimator, sources, backends, policy, model and
budgets are unchanged; only explicit language/prompt/provider identity differs.
Associate the original frozen stores and author summary by exact source seals.
Load/summary times belong to their original one-time preprocessing; this release
does zero loads, summary builds, fits, model or backend calls. Original records stay.

Carry the full prior12-cell prefix (three question groups) into a new RDF journal
using references to original outcomes, intents and terminals. Preserve prior
language/prompt versions and all negative results. Reject order, population,
method/budget changes or incomplete prefixes. Never redispatch old cells. Dataset
120=24dev/48train/48eval and48 evaluation denominator remain; mixed-version history
is not presented as the overall effectiveness of a homogeneous v2 release.

Allowed changes: one offline release/association script, two focused lineage checks,
release evidence and progress docs. Forbidden: model answer/prompt tuning, baseline
algorithm changes, data/model/catalog/summary rebuilding, source query probes,
old question retries, new ablation/scale work in this milestone.

Acceptance: complete prefix survives and only new cells dispatch; budget/prefix
drift rejected; all existing profile checks succeed; first new real group verifies
original source/engine/summary seals with the unchanged session controller.
Then execute the prespecified next two RDF NL groups (3 and4), four methods each,
at most8 model calls. Keep successes, incorrect answers, interpreter errors and
native failures. Do not condition the second group on whether the first scores well.
RQ is effectiveness/cost of the implemented one-shot system; method/mode is X,
EM/F1, complete online time and stage failure is Y. No quality or speedup assumed.

Two new lineage checks first pass in0.23s: all prior failed outcomes survive and
only the next group dispatches; budget drift/nonprefix history fail before creating
a new journal. No external calls or unchanged earlier gate repetitions.
