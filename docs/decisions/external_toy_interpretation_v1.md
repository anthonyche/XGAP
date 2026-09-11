# LINK: external OpenAI-compatible Interpretation on the unchanged tiny chain

2026-09-11. Scope frozen before implementation. This removes a concrete R-E/LINK
dependency on Pioneer model serving. It is a development integration, not a new
paper method, an evaluation population or evidence of model quality.

The shared Interpretation provider already accepts any served model and base URL.
The existing toy factory instead pins Qwen3-32B and its tokenizer revision. A
separate external factory must bind the supplied served identifier, URL and
credential environment-variable name, retaining semantic_program_v2, the wire
schema, deterministic validation and ordinary planning/replay. No weights,
tokenizer, context capacity or backend family is inferred from a model alias.
The existing Qwen factory and frozen remote package remain unchanged.

The external development profile explicitly uses a byte budget, not an exact
token budget: at most 65,536 serialized request bytes, requested output at most
4,096 tokens, one attempt per question, zero repairs, a 120-second transport
timeout and at most 1 MiB response bytes. Byte counts include the complete JSON
request and are never converted to token estimates. Exact input token count,
context fit and tokenizer parity are unverified. Actual token usage is reported
only when the provider supplies internally consistent usage; otherwise unknown
totals remain null. Existing low-level zero counters retain their explicit
usage-unavailable flag and do not become a measured zero-cost claim.

Configuration permits no credentials inside URLs, no query/fragment, no
implicit endpoint/model fallback and no automatic redirect or retry. The external
transport uses the configured environment/system proxy normally and records its
safe failures. It does not edit routing, start a model service or probe another
endpoint. The timeout is the urllib socket timeout, not a proven wall-clock
deadline against a streaming/trickling server. The finite response cap limits
received bytes. This distinction remains visible in run metadata.

The CLI defaults to a zero-call preflight. Execution requires an explicit switch
and the key only in the named environment variable. A run attempts a contiguous
window of 1–5 existing fixed questions, default the first one; an explicit start
index permits the unattempted suffix later without repeating the first call.
All five remain in the report, with
budget-unattempted/provider-blocked cases distinct from executed failures. The
intent/configuration is persisted before a model action. Raw recordings retain
the existing replay schema so a successful response can subsequently enter the
ordinary deterministic backbone without another model call. Semantic validity
does not mean answer correctness; the model receives no gold or native queries.
The report measures each exported recording against the replay reader's 4 MiB
cap; an oversized recording is retained with an explicit replay-size failure.
Each selected question is saved as started with unknown usage before provider
entry; a received outcome and its costs are saved before exporting the recording.
Recording-write failure stops the remaining window without erasing the model
attempt, and an interruption cannot relabel a started entry as unattempted.
A one-question directory is not a complete five-question native replay input:
replay only the recorded question through the ordinary entry, or finish an
explicitly selected unattempted suffix without repeating earlier model calls.

Acceptance is limited to new focused checks for exact endpoint/model selection,
local budget/missing-key refusal, unknown usage/failure accounting, secret
redaction, no redirects, response cap, fixed population/attempt limit, one
controlled HTTP → ordinary P1 → tiny RDFLib answer and replay. No actual model,
native server, large dataset or unchanged regression gate is required for this
local wiring gate. The previously recorded external /models timeout stays a
failed observation; live verification waits for changed access information.

Changing both model and deployment makes a separate evidence track. Any future
comparison with the old Qwen3-32B run cannot isolate a prompt change or establish
the external service's checkpoint identity merely from its response alias.
