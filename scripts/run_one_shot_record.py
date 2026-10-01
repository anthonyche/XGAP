"""Run one pinned request through the shared dataset-independent one-shot entry."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from xgap.experiments.one_shot_records import run_record, evaluate_record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Default preflight; explicit execute or offline replay")
    for name in ("profile-path", "profile-sha256", "request-path", "request-sha256", "output"):
        run.add_argument("--"+name, required=True)
    run.add_argument("--mode", required=True, choices=("precision", "performance"))
    run.add_argument("--operation", choices=("preflight", "execute", "replay"), default="preflight")
    run.add_argument("--replay-path")
    run.add_argument("--replay-sha256")
    score = sub.add_parser("evaluate", help="Score a sealed result; never invokes inference")
    for name in ("receipt-path", "receipt-sha256", "reference-path", "reference-sha256", "output"):
        score.add_argument("--"+name, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    result = run_record(**args) if command == "run" else evaluate_record(**args)
    print(json.dumps({k:result.get(k) for k in ("success", "status", "execution_kind", "answer_em", "output_tokens")}))
    return int(command == "run" and not result["success"])


if __name__ == "__main__":
    raise SystemExit(main())
