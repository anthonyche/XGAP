# Current architecture — unified lookahead v1

The current entry is `xgap.api.answer_unified`. Lambda and epsilon configure one
validation/loss contract; they are not two algorithms. A fixed-depth online
controller replaces the historical full strong-policy construction.

```text
NL + frozen source schema and public finite domains
 -> one compact proposal call (or declared development template)
 -> bounded complete candidate family
 -> paid private-user containment confirmation
 -> prepare protected seed plans + configured source/capability evidence
 -> actual state: validated bindings, facts, retained plans, spent resources
      check eligible terminals
      retain compact completion recipe + reserve remaining resources
      compare terminal with D-step symbolic acquisition / local rewrite options
      choose one action -> observe/check actual reply -> replan
      optional limit/no improvement -> saved completion action
 -> recheck contract/snapshots -> execute ONE plan -> rows and observed trace
```

The loss bound is evaluated against every remaining intent, including candidates
without retained optional plans. Plan retention never removes semantic uncertainty.
Mandatory validations cannot be inferred from candidate uniqueness or an LLM score.
Scope confirmation discloses containment, not the true candidate. Subsequent paid
full/scoped replies reveal only requested coordinates; private answer rows never
enter the online method.

`unified_family` maintains protected seeds and bounded plan pools.
`runtime.unified_physical` generates individual compiler-checked changes, not a
whole neighborhood as one action. `unified_information` invokes a registered
read-only scalar metadata/statistics target only when selected. Its finite outcome
category updates estimates or optional-rule prerequisites, not intent authority.
Hypothetical lookahead never contacts a tool or executes a trial plan.

On an optional deadline, keep a root action only after all of its outcomes have
passed completion reservations and fixed-depth scoring; incomplete actions never
replace the saved fallback. Seed identities are fixed at admission. Request-local
state-key/terminal/completion caches each hold at most 128 full state keys, including
bindings, evidence, retained pools and disclosure. See the
[2026-09-22 engineering contract](decisions/ch6_planner_external_followup_20260922.md).

The completion recipe is verified through bounded local scans rather than a full
conditional-policy tree. Remaining validations, final remote calls and known
resources are reserved for every outcome. Unknown bytes/memory bounds cannot
certify finite budgets. Normal-response, source and execution assumptions remain
explicit; backend failure or an exceeded bind bound can still prevent an answer.

`answer_unified_controlled` uses publisher-attested initial clues and the same
runtime, excluding NL initialization from its timing. The historical internal
two-stage diagnostic uses the same semantic eligibility, D and completion/resource guards.
Its semantic stage ranks only acquisition cost, then freezes the first eligible
candidate ID without execution-price feedback. The same physical stage follows.
The old full-validation sequential comparator retains its historical method ID.
The paper's Two-stage now means an actual external-method composition, not this
internal diagnostic; LLM-direct is excluded. See the
[current method contract](decisions/ch6_external_twostage_20260922.md).
noProbe removes only statistics actions; myopic ranks immediate nonterminal cost
while retaining terminal cost and the same completion guard; shallow is D=1.

The batch path is `run_bounded_joint_batch.py` → guarded common trial →
`nl_method_worker` → shared `bounded_joint_worker` → new unified entry.
New manifest/config/method IDs prevent accidental reuse of old algorithms.
Independent answer and query-loss scoring runs after compressed artifacts seal;
resume skips all attempted cells, including failures, and requires resource closure.

The semantic/compiler/runtime substrate remains shared. Catalog/ontology creation
is offline frozen preprocessing. The historical `api.answer(..., mode=...)` and
strong solver remain for frozen runs; see [legacy boundary](legacy_inventory.md).
Details, PTime assumptions and current evidence: [Chapter 6 map](implementation_chapter6.md),
[readiness](report/unified_prerelease_20260921.md).

[Pre-migration architecture](architecture_history_20260921_before_unified.md).
