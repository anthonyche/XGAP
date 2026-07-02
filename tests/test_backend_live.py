import json
import os
from pathlib import Path

import pytest

from xgap.experiments.backend_smoke import run_backend_smoke


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_BACKENDS = os.environ.get("XGAP_RUN_BACKENDS") == "1"


@pytest.mark.skipif(not RUN_BACKENDS, reason="set XGAP_RUN_BACKENDS=1 to run live backend smoke tests")
@pytest.mark.parametrize("backend_id", ["neo4j", "fuseki"])
def test_live_backend_smoke_harness(tmp_path: Path, backend_id: str) -> None:
    record = run_backend_smoke(
        backend_id=backend_id,
        dataset_spec_path=REPO_ROOT / "examples" / "datasets" / "financial_risk_toy.yaml",
        descriptors_dir=REPO_ROOT / "descriptors" / "backends",
        runs_dir=tmp_path,
        run_id=f"live-{backend_id}",
    )

    assert record.execution.success, record.execution.error
    results = json.loads(Path(record.normalized_result_path).read_text(encoding="utf-8"))
    assert results
    assert {row["company"] for row in results} >= {
        "BlackPeak Trading",
        "Redstone Analytics",
    }
