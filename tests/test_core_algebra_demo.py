import subprocess
import sys
from pathlib import Path


def test_core_algebra_demo_runs_successfully() -> None:
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [sys.executable, str(root / "examples" / "core_algebra_demo.py")],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        "Result paths:",
        "n1 -[e1]-> n2",
        "n1 -[e1]-> n2 -[e2]-> n3",
        "n1 -[e1]-> n2 -[e4]-> n4",
    ]
