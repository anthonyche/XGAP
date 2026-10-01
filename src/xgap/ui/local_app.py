"""Assemble and run the local XGAP clarification working surface.

The process reconstructs an E5C session from sealed research artifacts and a
minimal authority-event store.  Remote submission is opt-in and uses the
existing typed ``remote.executor``; SSH authentication remains outside the
process in the user's SSH configuration and agent.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from xgap.experiments.hashing import content_hash
from xgap.experiments.m15_clarification_transport import (
    M15ClarificationTransportSession,
    advance_m15_clarification_transport_session,
    compile_m15_clarification_transport_session,
)
from xgap.experiments.m15_direct_family_prediction import (
    load_m15_direct_training_memory_view,
)
from xgap.experiments.m15_live_resolution_execution_bridge import (
    prepare_m15_resolution_execution_bridge,
)
from xgap.experiments.remote_control import (
    invoke_remote_control,
    load_remote_control_config,
)
from xgap.tools import RemoteExecutorOperation, RemoteTransport
from xgap.ui.local_control import M15LocalClarificationController
from xgap.ui.local_server import (
    DEFAULT_LOCAL_UI_ORIGINS,
    M15LocalHttpConfig,
    build_m15_local_http_server,
)


LOCAL_UI_SESSION_STORE_SCHEMA_VERSION = "m15-e6c-local-ui-session-store-v1"
_DEFAULT_PATHS = {
    "bridge_spec": (
        "experiments/configs/m15_e4_resolution_execution_bridge_dev.json"
    ),
    "predictor_policy": (
        "experiments/configs/m15_f2c10_family_memory_predictor_dev.json"
    ),
    "interpretation_policy": (
        "experiments/configs/m15_e5_hierarchical_interpretation_policy_dev.json"
    ),
    "ontology": "experiments/specs/m15_e3_financial_risk_ontology_dev.json",
    "relaxation_policy": (
        "experiments/configs/m15_e5b_anchored_predicate_relaxation_dev.json"
    ),
    "transport_policy": (
        "experiments/configs/m15_e5c_clarification_transport_dev.json"
    ),
}


class M15LocalAppError(ValueError):
    """Raised before serving when local application inputs drift."""


def _store_body(session: M15ClarificationTransportSession) -> dict[str, Any]:
    payload = session.to_dict()
    return {
        "schema_version": LOCAL_UI_SESSION_STORE_SCHEMA_VERSION,
        "session_id": payload["session_id"],
        "authority_events": copy.deepcopy(payload["authority_events"]),
        "session_sha256": payload["session_sha256"],
        "paper_result": False,
    }


def persist_m15_local_ui_session(
    path: str | Path,
    session: M15ClarificationTransportSession,
) -> None:
    """Atomically persist only the finite authority-event reconstruction key."""

    unresolved = Path(path).expanduser()
    if unresolved.is_symlink():
        raise M15LocalAppError(
            "local UI session store must be a regular non-symbolic-link file"
        )
    target = unresolved.resolve(strict=False)
    if target.exists() and not target.is_file():
        raise M15LocalAppError(
            "local UI session store must be a regular non-symbolic-link file"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    body = _store_body(session)
    payload = {**body, "store_sha256": content_hash(body)}
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def load_m15_local_ui_session_store(
    path: str | Path,
) -> dict[str, Any] | None:
    """Load and verify a minimal authority-event reconstruction key."""

    source = Path(path).expanduser()
    if not source.exists():
        return None
    if source.is_symlink() or not source.is_file():
        raise M15LocalAppError(
            "local UI session store must be a regular non-symbolic-link file"
        )
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M15LocalAppError(
            "local UI session store is not valid JSON"
        ) from exc
    expected_fields = {
        "schema_version",
        "session_id",
        "authority_events",
        "session_sha256",
        "paper_result",
        "store_sha256",
    }
    if not isinstance(raw, Mapping) or set(raw) != expected_fields:
        raise M15LocalAppError("local UI session store fields changed")
    payload = copy.deepcopy(dict(raw))
    observed = payload.pop("store_sha256")
    if (
        payload.get("schema_version") != LOCAL_UI_SESSION_STORE_SCHEMA_VERSION
        or payload.get("paper_result") is not False
        or not isinstance(payload.get("authority_events"), list)
        or len(payload["authority_events"]) > 2
        or content_hash(payload) != observed
    ):
        raise M15LocalAppError("local UI session store hash mismatch")
    return {**payload, "store_sha256": observed}


def _source_path(
    root: Path,
    override: str | Path | None,
    key: str,
) -> Path:
    source = Path(override) if override is not None else root / _DEFAULT_PATHS[key]
    if not source.is_absolute():
        source = root / source
    if source.is_symlink() or not source.is_file():
        raise M15LocalAppError(f"{key} must be a regular file")
    return source.resolve()


def _resolution_question_sha256(path: str | Path) -> str:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise M15LocalAppError(
            "resolution run must be a regular non-symbolic-link JSON file"
        )
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M15LocalAppError("resolution run is not valid JSON") from exc
    intake = raw.get("intake") if isinstance(raw, Mapping) else None
    question_sha256 = (
        intake.get("question_sha256") if isinstance(intake, Mapping) else None
    )
    if (
        not isinstance(question_sha256, str)
        or len(question_sha256) != 64
        or any(character not in "0123456789abcdef" for character in question_sha256)
    ):
        raise M15LocalAppError("resolution run has no valid question hash")
    return question_sha256


def build_m15_local_clarification_controller(
    *,
    resolution_run_path: str | Path,
    training_memory_path: str | Path,
    remote_training_memory_path: str,
    expected_training_memory_sha256: str,
    session_id: str,
    authority_source_id: str,
    display_query: str,
    session_store_path: str | Path,
    workload_destination: str | Path,
    repo_root: str | Path,
    bridge_spec_path: str | Path | None = None,
    predictor_policy_path: str | Path | None = None,
    interpretation_policy_path: str | Path | None = None,
    ontology_path: str | Path | None = None,
    relaxation_policy_path: str | Path | None = None,
    transport_policy_path: str | Path | None = None,
    enable_remote_submit: bool = False,
    remote_environment: Mapping[str, str] | None = None,
    remote_transport: RemoteTransport | None = None,
) -> M15LocalClarificationController:
    """Reconstruct one browser-safe local controller from sealed inputs."""

    root = Path(repo_root).resolve()
    if hashlib.sha256(display_query.encode("utf-8")).hexdigest() != (
        _resolution_question_sha256(resolution_run_path)
    ):
        raise M15LocalAppError(
            "display query does not match the sealed resolution run"
        )
    paths = {
        "bridge_spec": _source_path(root, bridge_spec_path, "bridge_spec"),
        "predictor_policy": _source_path(
            root, predictor_policy_path, "predictor_policy"
        ),
        "interpretation_policy": _source_path(
            root, interpretation_policy_path, "interpretation_policy"
        ),
        "ontology": _source_path(root, ontology_path, "ontology"),
        "relaxation_policy": _source_path(
            root, relaxation_policy_path, "relaxation_policy"
        ),
        "transport_policy": _source_path(
            root, transport_policy_path, "transport_policy"
        ),
    }
    prepared = prepare_m15_resolution_execution_bridge(
        resolution_run_path=resolution_run_path,
        bridge_spec_path=paths["bridge_spec"],
        workload_destination=workload_destination,
        repo_root=root,
    )
    memory = load_m15_direct_training_memory_view(
        training_memory_path,
        workload=prepared.workload,
        expected_memory_view_sha256=expected_training_memory_sha256,
    )
    common = {
        "bridge": prepared.bridge,
        "workload": prepared.workload,
        "memory": memory,
        "predictor_policy": paths["predictor_policy"],
        "interpretation_policy": paths["interpretation_policy"],
        "ontology_path": paths["ontology"],
        "relaxation_policy": paths["relaxation_policy"],
        "transport_policy": paths["transport_policy"],
    }
    stored = load_m15_local_ui_session_store(session_store_path)
    authority_events = [] if stored is None else stored["authority_events"]
    session = compile_m15_clarification_transport_session(
        session_id=session_id,
        authority_events=authority_events,
        **common,
    )
    if stored is not None and (
        stored["session_id"] != session_id
        or stored["session_sha256"] != session.session_hash
    ):
        raise M15LocalAppError(
            "persisted authority events do not reconstruct the sealed session"
        )

    def advance(
        current: M15ClarificationTransportSession,
        authority_event: Mapping[str, Any],
    ) -> M15ClarificationTransportSession:
        return advance_m15_clarification_transport_session(
            session=current,
            authority_event=authority_event,
            **common,
        )

    submit_job = None
    if enable_remote_submit:
        remote_config = load_remote_control_config(
            remote_environment,
            working_directory=root,
        )

        def submit(payload: Mapping[str, Any]) -> Mapping[str, Any]:
            return invoke_remote_control(
                remote_config,
                RemoteExecutorOperation.SUBMIT_JOB,
                payload,
                transport=remote_transport,
            ).to_dict()

        submit_job = submit

    controller = M15LocalClarificationController(
        session=session,
        advance_session=advance,
        remote_training_memory_path=remote_training_memory_path,
        expected_training_memory_sha256=expected_training_memory_sha256,
        authority_source_id=authority_source_id,
        display_query=display_query,
        persist_session=lambda value: persist_m15_local_ui_session(
            session_store_path, value
        ),
        submit_job=submit_job,
    )
    if stored is None:
        persist_m15_local_ui_session(session_store_path, session)
    return controller


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolution-run", required=True)
    parser.add_argument("--training-memory", required=True)
    parser.add_argument("--remote-training-memory", required=True)
    parser.add_argument("--expected-training-memory-sha256", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--authority-source-id", required=True)
    parser.add_argument("--display-query", required=True)
    parser.add_argument("--session-store", required=True)
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allowed-origin", action="append", default=[])
    parser.add_argument("--enable-remote-submit", action="store_true")
    parser.add_argument("--bridge-spec")
    parser.add_argument("--predictor-policy")
    parser.add_argument("--interpretation-policy")
    parser.add_argument("--ontology")
    parser.add_argument("--relaxation-policy")
    parser.add_argument("--transport-policy")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.repo_root).resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="xgap-local-ui-") as temporary:
            controller = build_m15_local_clarification_controller(
                resolution_run_path=args.resolution_run,
                training_memory_path=args.training_memory,
                remote_training_memory_path=args.remote_training_memory,
                expected_training_memory_sha256=(
                    args.expected_training_memory_sha256
                ),
                session_id=args.session_id,
                authority_source_id=args.authority_source_id,
                display_query=args.display_query,
                session_store_path=args.session_store,
                workload_destination=Path(temporary) / "workload",
                repo_root=root,
                bridge_spec_path=args.bridge_spec,
                predictor_policy_path=args.predictor_policy,
                interpretation_policy_path=args.interpretation_policy,
                ontology_path=args.ontology,
                relaxation_policy_path=args.relaxation_policy,
                transport_policy_path=args.transport_policy,
                enable_remote_submit=args.enable_remote_submit,
            )
            origins = tuple(args.allowed_origin) or DEFAULT_LOCAL_UI_ORIGINS
            server = build_m15_local_http_server(
                controller,
                M15LocalHttpConfig(port=args.port, allowed_origins=origins),
            )
            print(
                json.dumps(
                    {
                        "status": "ready",
                        "url": f"http://127.0.0.1:{server.server_address[1]}",
                        "remote_submission_enabled": args.enable_remote_submit,
                        "paper_result": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    except ValueError as exc:
        print(
            json.dumps(
                {"status": "configuration_error", "error": str(exc)},
                sort_keys=True,
            )
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
