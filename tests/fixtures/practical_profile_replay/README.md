# Prior live tiny request, replayed offline

The native response files are copied unchanged from
`/Users/anthonyche/xgap-data/practical-model-strong-native-20260914-v1`.
Both manifests retain hashes of that run's original receipt and full result.
`replay.json` is the initial v1 migration and remains historical evidence.
`replay-v2.json` adds completeness and exact semantic/failure outcome comparison;
the current runner accepts v2 only. No extra source or model calls were made to
produce the migration. The captured model372 tokens and timings are historical.

These responses may be used only with the same typed tool inputs and exact
compiled native query artifacts. Changing a candidate domain, source query or
failure reason must not produce a successful equivalence receipt. Runtime
answer correctness is separate from faithful reproduction; the latter also
supports complete recorded failures.
