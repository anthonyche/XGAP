"""Command-line entry point for the frozen M13-D GrailQA semantic pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from xgap.experiments.grailqa_semantic_pilot import (
    GrailQASemanticPilotSpec,
    readiness_report,
    run_semantic_pilot,
    validate_frozen_artifacts,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-queries", type=int)
    parser.add_argument("--check-ready", action="store_true")
    args = parser.parse_args(argv)
    repo = Path.cwd().resolve()
    spec = GrailQASemanticPilotSpec.load(args.spec)
    output = Path(args.output).resolve()
    if args.check_ready:
        report = readiness_report(
            spec,
            repo,
            output,
            require_credentials=not args.dry_run,
            require_clean=not args.dry_run,
        )
        output.mkdir(parents=True, exist_ok=True)
        (output / "readiness.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for check in report["checks"]:
            print(f"{check['status'].upper():8} {check['name']}: {check['detail']}")
        print(f"READY={str(report['ready']).lower()}")
        return 0 if report["ready"] else 1

    catalog, model = validate_frozen_artifacts(spec, repo)
    print(f"git_commit={_git_commit(repo)}")
    print(f"spec_sha256={spec.file_sha256}")
    print(f"spec_freeze_hash={spec.freeze_hash}")
    print(f"pilot_bundle_hash={spec.data['pilot_bundle_hash']}")
    print(f"catalog_hash={catalog.catalog_hash}")
    print(f"model={'deterministic-fake' if args.dry_run else model.config.exact_model_snapshot}")
    print(f"query_count={args.max_queries or len(spec.question_ids)}")
    print(f"output={output}")
    result = run_semantic_pilot(
        spec_path=args.spec,
        output_root=output,
        repo_root=repo,
        dry_run=args.dry_run,
        resume=args.resume,
        max_queries=args.max_queries,
    )
    print(result["summary"])
    return 0


def _git_commit(repo: Path) -> str:
    import subprocess

    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
