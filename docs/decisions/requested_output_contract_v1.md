# LINK: request-owned output columns before execution

2026-09-11. Parent4d5b194. B01's NL already says to return person and edge;
the extra age column is a model projection error, not a hidden gold requirement.
This change makes that explicit request obligation machine-checkable for R-E.

An optional `context.requested_output` contract contains exactly
`{"kind":"binding_set","fields":[...]}`. The unique1–64nonempty field names
declare the answer schema, not values, entity identities, path positions or a
gold plan. The request validates this contract before provider entry. After
parsing a generated semantic program, admission requires one binding_set root
whose statically explicit fields match exactly. This profile supports final
Project and Match; other root shapes must fail explicitly under this optional
contract. No property fetching, renaming, column removal, inferred projection
or backend call is performed by validation. It does not prove field lineage,
answer values or complete NL meaning. Legacy requests without the contract keep
their existing behavior and exact serialized request shape.

The separate external toy `explicit-output-v1` request profile recognizes only
the two explicit return-clause forms already present in the frozen questions:
`返回人员和边` → person,edge; `返回<name>的身份和年龄` → person,age.
It parses the original question text, never expected_rows/reference queries or
the authored semantic template. Unsupported/multiple return clauses fail before
model access; this is a bounded development intake, not an open-domain NL parser.
Question text, hard constraints, data, gold and entity clarification are unchanged.
The v3 prompt states that fields needed only for filtering are not requested
outputs, and points to the explicit request contract. The legacy external-v2
profile, H100 package and recorded old inputs remain available and unchanged.

The shared tiny runner accepts one explicit request profile, records it before
dispatch and preserves its five-question population/window/cost ledger. Native
replay must choose the identical profile; it must not silently alter a recorded
request or apply a different context. Old saved payloads may be checked against
the new output contract as a labeled local compatibility diagnostic, never
rewritten as if the model had seen the new input. Old extra-column failures
remain failures. New actual generation after this correction is a distinct
versioned diagnostic, not repair/retry of the identical external action.

Acceptance: focused request/contract/admission/replay checks, all five old
payloads evaluated without modification or network, and a tiny complete slice.
After those gates, at most five fresh external requests under the new profile,
then one bounded native replay if parser admission succeeds. No broad regression,
large-data run, gold projection or automatic retry. The existing true native
gate still uses exact answers and stops at the first failure. Missing native
outcomes remain unattempted. Positive quality/performance is not assumed.
