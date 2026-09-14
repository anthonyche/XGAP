# Precision evidence and quality band — optional one-shot profile

2026-09-14. Scope: two bounded local changes inside the ordinary precision entry.
No new algebra, native execution, model call, catalog build, training or baseline
change. Existing frozen modes retain their old policy and serialized identities.
This implements the user's request for a more accuracy-oriented precision mode;
it does not assume that a model confidence is a calibrated answer probability.

RQ: Can explicit local name evidence and a quality constraint avoid cheap but
poorly supported selections? X: artifact-order versus contextual name grounding;
soft quality/cost objective versus a declared maximum proxy-quality deficit.
Y: independent ambiguous-query answer correctness, selected proxy deficit,
planning time/calls, and full online cost. Tiny counterexamples verify mechanisms,
not an overall accuracy improvement or a new evaluation campaign.

## Grounding

Optional `grounding_ranking=canonical_context_v1` uses only the candidates already
returned by the frozen catalog within the existing cap. For each candidate, rank
by (1) canonical label exactly matching the hole mention, (2) the complete
canonical label occurring in the question with word boundaries, then original
artifact order. Record both evidence bits and the candidate ordering. Ontology
responses without canonical labels have no such evidence and retain their order.
Only entity holes use this ranking: an entity name elsewhere in a question is
useful lexical evidence, but it is not a general coreference or logical proof.

Do not execute candidate bindings or enumerate combinations. Choose one binding
per hole and apply the existing typed binding/hard-constraint validation. The
binding remains a prediction; only the original artifact can grant authority.
If two names occur or no distinguishing name occurs, ties remain explicit and
stable. Missing/truncated pools remain approximate. A candidate outside the cap
cannot be recovered by this rule. Questions with negation, multiple people or
implicit context can still be resolved incorrectly; no global accuracy bound.

With H holes, C candidates/hole, N catalog size, text length L and total returned
label length T, the existing scans cost O(H*N*L) in the direct implementation.
Additional label evidence and stable sorting cost O(T*L + H*C log C), with bounded
H<=64 and C<=256; storage is O(T+H*C). No candidate Cartesian product is built.

## Interpretation/plan selection

Optional precision-only `max_quality_deficit=delta`, 0<=delta<=1:

1. For each grounded, executable interpretation, predict all admitted physical
   candidates and retain its cheapest estimated plan, as before.
2. Let q_i be the model's quality proxy (or the existing explicitly labeled
   fallback for an unknown proxy); q_max=max_i q_i.
3. Keep interpretations with q_i>=q_max-delta, recording eligible/excluded IDs.
4. Select minimum estimated execution cost among those interpretations. Tie by
   higher proxy, then stable candidate ID. Execute that one plan once.

The band replaces the legacy soft `cost+lambda*(1-q)` objective when enabled;
otherwise the exact legacy selection remains. It does not add another quality
penalty or mix an ordinal score with milliseconds. A hard quality band prevents
an arbitrarily large predicted speed benefit from buying an arbitrarily large
proxy-quality loss. It does **not** prevent an overconfident model from choosing
the wrong meaning. All-missing proxies reduce to the disclosed fallback/cost
choice, with no observed quality guarantee. Failed final execution is terminal.

Extra selection costs O(K), K<=8, on top of the existing bounded polynomial
compile/estimate domain. It is exact estimated-cost minimization within the
admitted quality band; selected proxy deficit is <=delta (finite float arithmetic
as implemented). If every known proxy uniformly approximates true answer quality
within epsilon, selected true quality satisfies
`q_selected >= q_best - (delta + 2*epsilon)`. This is conditional, not an established property of our
model. Unknown proxy fallback provides no such true-quality bound. Under uniform
cost error eta, cost regret is <=2*eta within the same admitted band; no latency
bound applies outside it or to arbitrary physical plans.

## Acceptance and release

Use existing tiny facts with new authored ambiguity and quality/cost counterexamples.
Verify changed actual bindings/answers, unchanged hard constraints and source
facts, no authority promotion, cap/tie/unknown behavior, rejection records and one
final execution. Provider outputs in these mechanism tests are controlled, not
claimed to be actual LLM successes. A subsequent bounded real-NL ambiguity gate
is required before claiming real interpretation effectiveness. Freeze actual
policy settings and a new profile before evaluation; do not tune on old eval
answers or silently apply the changes to shared baseline frontends.

Mechanism gate: seven new directed tests passed in 0.69s. On the unchanged tiny
facts, contextual Alex→Bob grounding returns the independently correct edge e2
instead of Alice's e4, preserving the explicit age/identity hard constraints.
An independent two-meaning cost counterexample selects Bob instead of cheaper
Alice when the proxy band is enabled. Each ordinary request uses one controlled
provider response and one actual final graph plan; no model/fit/probe/network.
These are controlled interpretation results, not observed LLM accuracy gains.
