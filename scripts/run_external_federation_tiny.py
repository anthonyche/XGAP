#!/usr/bin/env python3
"""Once-only actual FedUP/FedX transport gate on nine RDF triples. No LLM.

--execute starts owned loopback services. Every output root is exclusive; failures
are retained. This is an integration gate, not a timed comparative campaign.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time

from xgap.experiments.external_federation import SourceObserver, deadline, query_once, score_sparql
from xgap.experiments.m15_native_services import LoopbackPortReservations
from xgap.experiments.one_shot_records import write_once

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests/fixtures/external_federation"


def fingerprint(path):
    p = Path(path)
    return {"path":str(p.resolve()), "bytes":p.stat().st_size, "sha256":hashlib.sha256(p.read_bytes()).hexdigest()}


class Processes:
    def __init__(self, root):
        self.root, self.owned, self.logs = root, [], []

    def start(self, name, command, *, env=None, cwd=None):
        write_once(self.root/f"{name}-intent.json", {"command":command, "environment_overrides":env or {}, "cwd":str(cwd) if cwd else None})
        log = (self.root/f"{name}.log").open("xb")
        self.logs.append(log)
        child = subprocess.Popen(command, cwd=cwd, env={**os.environ, **(env or {})}, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.owned.append((name, child))
        return child

    def command(self, name, command, *, seconds=35):
        started = time.perf_counter()
        process = self.start(name, command)
        code = process.wait(timeout=seconds)
        write_once(self.root/f"{name}-receipt.json", {"exit_code":code, "wall_ms":(time.perf_counter()-started)*1000})
        if code:
            raise RuntimeError(name + " failed; no retry")

    @staticmethod
    def stop(process):
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)

    def close(self):
        for _, process in reversed(self.owned):
            self.stop(process)
        for log in self.logs:
            log.close()
        return [{"name":name, "pid":p.pid, "returncode":p.poll()} for name,p in self.owned]


def ready(process, port):
    end = time.monotonic()+25
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError("Service exited during startup")
        try:
            with socket.create_connection(("127.0.0.1",port), timeout=.2):
                return
        except OSError:
            time.sleep(.1)
    raise TimeoutError("Service readiness exhausted; no restart")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--java", default="/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home/bin/java")
    parser.add_argument("--fuseki-root", type=Path, default=Path("/Users/anthonyche/xgap-data/d202-local-native-20260910-diagnostic2/runtime/apache-jena-fuseki-5.6.0"))
    parser.add_argument("--fedup-build", type=Path, default=Path("/Users/anthonyche/xgap-data/fedup-build-20260912-v1"))
    parser.add_argument("--fedx-jar", type=Path, default=Path("/Users/anthonyche/xgap-data/fedx-adapter-build-20260912-matched/fedx-endpoint-adapter-matched.jar"))
    parser.add_argument("--methods", nargs="+", choices=["fedup","fedx"], default=["fedx","fedup"])
    parser.add_argument("--cases", nargs="+", default=None)
    parser.add_argument("--reuse-summary-from", type=Path, help="Prior gate root with identical facts; reuse frozen summary and map its endpoint base")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    jars = {"fedup":args.fedup_build/"fedup-server.jar", "summary":args.fedup_build/"summarizer.jar", "fedx":args.fedx_jar}
    expected_jars = {"fedup":"64989a0ac220fc56fb5f57184df2195cad73326c796938afcc92b147bb150a05", "summary":"4e25ff950ebfaa97e120daa09105ea409e4d7ba65b9bcc30a2c1b25d06bd6d56", "fedx":"2e12c2630a94e017401ca8287b20ab90c0550a6607d19030a843a7d42d5f1290"}
    for name, path in jars.items():
        if fingerprint(path)["sha256"] != expected_jars[name]:
            raise ValueError("Pinned external artifact mismatch: " + name)
    cases = json.loads((FIXTURE/"queries.json").read_text())
    if args.cases:
        if not set(args.cases) <= {c["id"] for c in cases}:
            raise ValueError("Unknown gate case")
        cases = [c for c in cases if c["id"] in args.cases]
    if len(set(args.methods)) != len(args.methods):
        raise ValueError("Duplicate method would repeat a gate")
    inputs = [*FIXTURE.iterdir(), *jars.values(), Path(__file__), REPO/"src/xgap/experiments/external_federation.py"]
    frozen = [fingerprint(p) for p in inputs]
    snapshot=root/"fixture_snapshot"; snapshot.mkdir()
    for path in FIXTURE.iterdir():
        if path.is_file():
            shutil.copy2(path,snapshot/path.name)
    write_once(root/"case_manifest.json",cases)
    write_once(root/"input_manifest.json", {"inputs":frozen, "methods":args.methods, "cases":[c["id"] for c in cases], "model_calls":0,
        "maximum_top_level_queries":len(cases)*len(args.methods), "query_wall_seconds":8, "overall_wall_seconds":240,
        "maximum_observed_source_requests":256, "source_timeout_seconds":3, "jvm_heap_mib":512,
        "measurement":"HTTP request target + body and response body separately; headers/TCP/TLS excluded", "paper_result":False})
    receipt = {"schema_version":"xgap-external-federation-tiny-v1", "success":False, "status":"preflight", "model_calls":0, "paper_result":False, "runs":[]}
    if not args.execute:
        write_once(root/"receipt.json",receipt)
        print(json.dumps(receipt)); return 0
    processes, observer, ports = Processes(root), None, LoopbackPortReservations.acquire(2+len(args.methods))
    try:
        with deadline(240):
            receipt["status"] = "setup"
            upstreams = {}
            for i, name in enumerate(["a","b"]):
                base = root/f"fuseki-{name}"; base.mkdir()
                port = ports.ports[i]; ports.release(i)
                command = [str(args.fuseki_root/"fuseki-server"), "--localhost", "--port", str(port), "--file", str(FIXTURE/f"source-{name}.ttl"), "/ds"]
                process = processes.start("source-"+name, command, env={"JAVA":args.java, "FUSEKI_HOME":str(args.fuseki_root), "FUSEKI_BASE":str(base), "JVM_ARGS":"-Xms128m -Xmx512m"}, cwd=args.fuseki_root)
                ready(process, port)
                upstreams[f"/{name}/sparql"] = f"http://127.0.0.1:{port}/ds/sparql"
            observer = SourceObserver(upstreams, root/"source_observations")
            endpoints = [observer.base_url + "/"+name+"/sparql" for name in ["a","b"]]
            write_once(root/"endpoints.json", {"observed":endpoints, "upstream":upstreams})
            summary = root/"frozen-summary"
            endpoint_mapping = "(e) -> e"
            old_base=observer.base_url
            if any(m.startswith("fedup") for m in args.methods):
                if args.reuse_summary_from:
                    previous=args.reuse_summary_from.resolve()
                    prior_inputs=json.loads((previous/"input_manifest.json").read_text())["inputs"]
                    for fact in [FIXTURE/"source-a.ttl",FIXTURE/"source-b.ttl"]:
                        if fingerprint(fact) not in prior_inputs:
                            raise ValueError("Cannot reuse a summary of different facts")
                    prior_seal=json.loads((previous/"summary_seal.json").read_text())
                    if [fingerprint(p["path"]) for p in prior_seal["files"]] != prior_seal["files"]:
                        raise ValueError("Prior frozen summary changed")
                    shutil.copytree(previous/"frozen-summary",summary)
                    old_endpoints=json.loads((previous/"endpoints.json").read_text())["observed"]
                    from urllib.parse import urlsplit
                    old_base=old_endpoints[0].rsplit("/a/sparql",1)[0]
                    if old_endpoints != [old_base+"/a/sparql",old_base+"/b/sparql"] or urlsplit(old_base).hostname!="127.0.0.1":
                        raise ValueError("Unexpected prior endpoint mapping")
                    endpoint_mapping="(e) -> e.replace("+json.dumps(old_base)+", "+json.dumps(observer.base_url)+")"
                    write_once(root/"summary_reuse.json", {"prior_seal":fingerprint(previous/"summary_seal.json"),"endpoint_mapping":endpoint_mapping,"offline_summary_builds":0})
                else:
                    data = root/"summary-input.trig"
                    prefix = "@prefix ex: <http://example.org/fin/> .\n"
                    data.write_text(prefix+"\n".join(f"<{endpoint}> {{\n" + (FIXTURE/f"source-{name}.ttl").read_text().split("\n",1)[1] + "}\n" for name,endpoint in zip(["a","b"],endpoints)))
                    summary.mkdir()
                    java = [args.java,"-Xms128m","-Xmx512m","-cp",str(jars["fedup"])]
                    processes.command("offline-tdb-load", java+["tdb2.tdbloader","--loc",str(root/"summary-input"),str(data)])
                    processes.command("offline-summary", [args.java,"-Xmx512m","-jar",str(jars["summary"]),"--input",str(root/"summary-input"),"--output",str(summary),"--hash","1"])
                write_once(root/"summary_seal.json", {"files":[fingerprint(p) for p in sorted(summary.rglob("*")) if p.is_file()], "source_facts":9, "hash_modulo":1, "offline":True})
                shutil.copytree(summary,root/"serving-summary")
            for i, method in enumerate(args.methods):
                observer.set_phase(method+":initialization")
                port=ports.ports[2+i]; ports.release(2+i)
                if method == "fedx":
                    command = [args.java,"-Xms128m","-Xmx512m","-jar",str(jars[method]),str(port),"8",*endpoints]
                    endpoint = f"http://127.0.0.1:{port}/sparql"
                else:
                    command = [args.java,"-Xms128m","-Xmx512m","-jar",str(jars[method]),"--port",str(port),"--summaries",str(root/"serving-summary"),"--engine","FedX","--modify",endpoint_mapping]
                    endpoint = f"http://127.0.0.1:{port}/serving-summary/sparql"
                process=processes.start(method,command); ready(process,port)
                write_once(root/f"{method}-initialization.json",observer.snapshot(method+":initialization"))
                for case in cases:
                    phase=method+":"+case["id"]
                    observer.set_phase(phase,fail_source=case.get("fail_source"))
                    raw=query_once(endpoint,case["query"],seconds=8,output=root/(phase.replace(":","-")+"-raw.json"))
                    if raw["status"] != "returned":
                        processes.stop(process)
                    observed=observer.snapshot(phase)
                    transport_ok=raw["status"]=="returned" and raw["http_status"]==200
                    success=transport_ok and observed["failed_requests"]==0
                    run={"method":method,"case":case["id"],"transport_success":transport_ok,"success":success,"client_wall_ms":raw["client_wall_ms"],"sources":observed}
                    if case["expected_terminal"]=="answer":
                        # Only read gold after the raw output has been durably sealed.
                        if success:
                            gold=json.loads((snapshot/"gold.json").read_text())[case["id"]]
                            run["evaluation"]=score_sparql(json.loads(raw["body_utf8"]),gold,ordered=case["ordered"])
                        run["accepted"]=bool(run.get("evaluation",{}).get("exact"))
                        if case["id"]=="cross_ordered":
                            run["accepted"] &= {r["source"] for r in observed["records"] if r.get("query_kind")=="SELECT"}==set(upstreams)
                    else:
                        run["accepted"]=not success and (observed["failed_requests"]>0 if case.get("fail_source") else observed["requests"]==0 and raw.get("http_status",0)>=400)
                    write_once(root/(phase.replace(":","-")+"-evaluation.json"),run)
                    receipt["runs"].append(run)
                    if case["expected_terminal"]=="answer" and not transport_ok:
                        receipt["early_stop_reason"]="New adapter failed an answer request; retain unrun cases instead of repeating a systemic failure"
                        break
                    if process.poll() is not None:
                        break
                processes.stop(process)
                observer.set_phase(method+":shutdown")
            receipt.update(success=len(receipt["runs"])==len(cases)*len(args.methods) and all(r["accepted"] for r in receipt["runs"]),status="completed")
    except Exception as error:
        receipt.update(status="failed",error_type=type(error).__name__,error=str(error))
    finally:
        receipt["processes"]=processes.close()
        if observer:
            observer.close()
            receipt["observed_source_requests"]=len(observer.records)
            receipt["observer_stopped"]=not observer.thread.is_alive() and observer.inflight==0
        ports.close()
        receipt["inputs_unchanged"]=[fingerprint(p) for p in inputs]==frozen
        if (root/"summary_seal.json").exists():
            sealed=json.loads((root/"summary_seal.json").read_text())["files"]
            receipt["frozen_summary_unchanged"]=[fingerprint(p["path"]) for p in sealed]==sealed
            receipt["success"] &= receipt["frozen_summary_unchanged"]
        receipt["owned_processes_terminal"]=all(p["returncode"] is not None for p in receipt["processes"])
        receipt["success"] &= receipt["inputs_unchanged"] and receipt["owned_processes_terminal"] and receipt.get("observer_stopped",False)
        write_once(root/"receipt.json",receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k not in {"runs","processes"}}))
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
