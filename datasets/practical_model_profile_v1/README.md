# Practical strong-mode development profile

Five nodes and nine edges from `../practical_model_toy_v1`, the same trusted
Chinese request, and one uncertain predicate (KNOWS or FOLLOWS). The pinned
request validates person, age, type and source. The binding-only clarification
fixture validates the predicate only when invoked; it contains no answer rows.

This is a development configuration. Source URLs use unserved localhost port1.
Do not call `execute` on it as if services had been deployed. Model credentials
are referenced only by `XGAP_EXTERNAL_LLM_API_KEY`; none are stored here.

The exact mode requires authority and can spend a bounded improvement budget.
Performance authorizes the predicate proposal, uses fewer search states and no
improvement actions. Both receive the same trusted graph/request; performance
does not truncate hard constraints or claim a discrepancy bound. Unknown action
costs are null; model-first is an explicit heuristic priority.

`estimator.json` deploys the unchanged `trained_model` from
`tests/fixtures/one_shot_record_replay/estimator.json`. Its new source statistics
come from the frozen graph's five node and nine edge JSON records. Width is the
mean UTF-8 length of `json.dumps(record, sort_keys=True, separators=(',', ':'))`:
14 records and60.5 bytes, assigned to each full-copy backend with its source ID
and graph-file SHA-256. This is offline logical width, not native response bytes.
No new training or model collection; the prior model's training provenance stays
embedded. This transfer has no calibration or ranking-accuracy guarantee.

Use `python -m xgap.experiments.practical_records` with explicit profile/request
SHA-256 and a new output path. `publish` resolves all references. `preflight`
constructs a policy without opening the clarification file or contacting a
service. `replay` takes the pinned
`tests/fixtures/practical_profile_replay/replay-v2.json` and consumes its old
proposal/native captures with zero network. A captured372 tokens is historical.

[Contract](../../docs/decisions/practical_profile_v1.md) and
[verification](../../docs/report/practical_profile_20260914.md) distinguish this
development release from native deployment and formal evaluation.
