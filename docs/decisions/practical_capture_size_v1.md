# Admit saved practical source captures under the source-capture byte contract

2026-09-15. After fixing worker outcome handoff, the same audit found practical
replay admission incorrectly routed source capture files through the16MiB config
reader. The existing BackendReplay consumer allows a bounded512MiB capture and
revalidates exact size/hash at consumption. A successful larger source response
could therefore be captured but refused before the existing replay reader ran.

Align practical admission with that existing source-capture limit. Configuration,
manifest and outcome admission remain16MiB. Check declared size (or actual file
size for legacy pins), positive integer range, bounded read and exact SHA-256.
Reject truncation/growth/hash mismatch; do not use a failed replay as permission
for a live call. No changes to BackendReplay, baseline algorithms or capture data.

The purpose is to preserve failure-replay usefulness before larger evaluation,
not to claim unbounded streaming or actual large-graph scalability. Reading a
large JSON capture still consumes memory proportional to its bounded size.
Acceptance: one existing full replay with>16MiB valid trailing JSON whitespace,
three invalid size cases rejected before file opening, hash/truncation checks,
and one affected original failure-fingerprint replay. Whitespace changes no
query/result/observation, and all checks use zero new network calls.
