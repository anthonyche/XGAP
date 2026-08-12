# Qwen3 vLLM OpenAI-Compatible Template

This is a configuration boundary only. Set the repository-relative
ModelBundle configuration to the OpenAI-compatible vLLM base URL, exact model
snapshot, and an API-key environment-variable name used by that deployment.

M12-B does not download weights, install or start vLLM, choose GPU placement,
or commit credentials. Materialize a full prompt and structured schema from
the DashScope live bundle before use; the template itself is intentionally
non-executable.
