"""Preflight or record five tiny model requests; no large dataset or catalog build."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from xgap.experiments.toy_live_interpretation import load_qwen_toy_provider, toy_model_requests, run_toy_model_requests


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-snapshot", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true", help="Send at most five model requests")
    args = parser.parse_args(argv)
    provider = load_qwen_toy_provider(args.tokenizer_snapshot)
    if args.execute:
        report = run_toy_model_requests(provider, args.output)
    else:
        checks = [{"query_id": qid, "token_budget": provider.token_guard.check(
            provider.build_request_payload(request), call_kind="generation")}
            for qid, request in toy_model_requests()]
        report = {"success": all(c["token_budget"]["passed"] for c in checks),
                  "external_calls": 0, "checks": checks}
        with Path(args.output).open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"success": report["success"], "external_calls": report["external_calls"],
                      "output": str(args.output)}))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
