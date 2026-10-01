"""Opt-in, offline diagnostic boundary check against an already frozen FedX jar."""
import hashlib
import os
from pathlib import Path
import subprocess

import pytest


def test_fedx_failure_stages_preserve_http_and_query(tmp_path):
    jar_value = os.environ.get("XGAP_TEST_FEDX_JAR")
    java_home = os.environ.get("XGAP_TEST_JAVA_HOME")
    if not jar_value or not java_home:
        pytest.skip("requires existing XGAP_TEST_FEDX_JAR and XGAP_TEST_JAVA_HOME; never downloads dependencies")
    jar = Path(jar_value)
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    root = Path(__file__).resolve().parents[1]
    java = Path(java_home) / "bin" / "java"
    javac = Path(java_home) / "bin" / "javac"
    source = root / "experiments/external/fedx/src/main/java/org/xgap/experiments/FedXEndpoint.java"
    check = root / "tests/java/org/xgap/experiments/FedXFailureDiagnosticCheck.java"
    compiled = subprocess.run([str(javac), "--release", "21", "-cp", str(jar), "-d", str(tmp_path), str(source), str(check)], capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stderr
    result = subprocess.run([str(java), "-cp", os.pathsep.join((str(tmp_path), str(jar))), "org.xgap.experiments.FedXFailureDiagnosticCheck"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "prepare/evaluate/serialization diagnostics passed; source query executions=0" in result.stdout
    assert hashlib.sha256(jar.read_bytes()).hexdigest() == digest
