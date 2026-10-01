# Development

Use Python 3.10+ and an isolated environment. Install the package with the test
extras listed in README.md. Run `make acceptance` from the repository root for
repository hygiene, portable tests, and the local demo. Optional Parquet tests
require the `parquet` extra.

Tests that exercise service clients use temporary directories and local doubles.
Standalone native integration utilities need configured external services and are
not automatically launched by `make acceptance`. Do not use production credentials
or submit cluster experiments merely to validate a code change.

## Configuration and outputs

Compact synthetic input datasets, backend descriptors, query templates, and model
interface configurations can be versioned. Generated datasets, downloaded models,
private endpoints, credentials, run reports, and result archives belong outside the
checkout. Keep runtime output directories ignored. Credentials use environment
variable references, never values in configuration or shell commands.

The `apps/xgap-ui` frontend has its own package manifest and lockfile. It requires
Node.js 22.13+ and pnpm. Its frontend build is separate from the Python tests.

## Changes

Keep semantic and physical changes separate in the explanation of a patch. Preserve
hard constraints, authority boundaries, actual-call accounting, and deterministic
fixtures. When a regression is found, keep the smallest input that reproduces it;
remove machine details and measured run results from fixtures.

`python scripts/check_harness.py` validates the tracked repository contents. It
rejects report/history/archive/output paths and broken local documentation links.
It does not inspect or rewrite historical Git commits.
