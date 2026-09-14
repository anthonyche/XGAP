# One admitted dependency snapshot per ordinary record request

2026-09-15. The preceding offline audit observed four FrozenResolutionBundle.load
calls in one practical replay: eager profile admission, repeated materialization
in the record runner, repeated materialization in profile.run and the ordinary
question route. Each load includes hash checking and catalog parsing. This is
online repeated work, distinct from offline catalog construction.

Scope: practical profile/record preparation and the practical question options.
No new result cache, query strategy, information authority, model weight, source
facts, baseline or formal experiment change. Legacy question routes are unchanged.
Research relevance is honest online cost accounting and avoiding repeated metadata
work in the same request; it does not establish overall mode superiority.

The record runner loads and validates the entire pinned profile, all mode settings
and dependencies once, then admits the pinned request. It retains that request's
in-memory intake, catalog/bindings, estimator, source descriptors and instantiated
acquisition providers. PreparedPracticalRequest binds the snapshot to the profile
and request hashes. Execution wraps its already prepared tools for capture/replay
and passes the admitted bundle through the ordinary question route. A different
profile/configuration/bundle identity is rejected before an external action.

After admission, a change to a dependency file cannot rewrite the in-flight
request's parsed snapshot. The next record request loads and revalidates the files
and therefore rejects a changed pinned file. There is no global cache or cached
answer. Existing direct load/run methods remain available; explicit materialize
still means a fresh validation. A host explicitly retaining a PreparedPracticalRequest
owns its snapshot lifetime; it must not describe another execution as a new file
admission. Trusted in-process objects are not a sandbox against hostile host code.

Late artifacts are intentionally outside this dependency snapshot: clarification
responses are only read and pin-checked when their action is invoked, and native
replay response files are rechecked when consumed. This preserves failed and
indeterminate outcomes and prevents admission from learning a future answer.
Model prompts/configuration are admitted; model answers are never prefetched.

The runner records admission_ms. profile_preparation_ms receives that actual
duration, and request_total_ms includes admission plus request execution. Overall
receipt elapsed_ms still covers record setup/persistence. These are nested scopes,
not mutually exclusive bars to add together. No preparation cost is silently
removed from end-to-end accounting or relabeled as one-time catalog construction.
Cross-request initialization amortization remains a separate future protocol.

The change reduces repeated work from four bundle admissions to one for a record
request, without changing the asymptotic polynomial planner or semantic result.
It gives no latency bound/speedup ratio. The five new cases verify single loading,
complete replay, admission accounting, late dependency drift versus fresh admission,
and mismatched profile/configuration/bundle identities. Two affected existing cases
verify late clarification pins and exact failed-outcome replay. Only saved native
captures are used; no model or database service needs to be started.
