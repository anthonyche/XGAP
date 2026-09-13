"""Replay the saved Darwin killpg exit race; no live query or benchmark rerun."""
import pytest
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from xgap.experiments.process_guard import ProcessBudget


def test_permission_error_after_last_group_member_exit_is_read_verified(monkeypatch):
    import xgap.experiments.process_guard as module
    scans=iter([[{'pid':12}],[],[]])
    monkeypatch.setattr(module,'_group_sample',lambda _:next(scans))
    def deny(*_):raise PermissionError(1,'Operation not permitted')
    monkeypatch.setattr(module.os,'killpg',deny)
    class Process:
        pid=12
        def poll(self):return 143
    r=module._stop_group(Process(),ProcessBudget())
    assert r['complete'] and r['resolved_permission_races']==1 and r['signals']==[]


def test_permission_error_with_live_members_is_not_silenced(monkeypatch):
    import xgap.experiments.process_guard as module
    monkeypatch.setattr(module,'_group_sample',lambda _:[{'pid':12}])
    def deny(*_):raise PermissionError(1,'Operation not permitted')
    monkeypatch.setattr(module.os,'killpg',deny)
    class Process:
        pid=12
        def poll(self):return None
    with pytest.raises(PermissionError):module._stop_group(Process(),ProcessBudget())


def test_disk_session_reaps_owned_leader_and_only_discards_new_copies(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    from rdf_tdb_session import RdfTdbSession
    child=subprocess.Popen([sys.executable,'-c','pass'],start_new_session=True);child.wait(timeout=3)
    session=RdfTdbSession.__new__(RdfTdbSession);session.root=tmp_path/'session';session.root.mkdir()
    session.processes=SimpleNamespace(owned=[('already-exited',child)],logs=[])
    session.observer=None;session.ports=None;session.discard_serving_copies=True
    retained=session.root/'query-response.json';retained.write_text('immutable outcome')
    frozen=tmp_path/'frozen-source';frozen.write_text('original data')
    for name in ('graph-tdb2','control-tdb2','fedup-host/serving-summary'):
        p=session.root/name;p.mkdir(parents=True);(p/'data').write_text('reconstructable serving copy')
    r=session.close()
    assert r['owned_groups_drained'] and r['owned_processes_terminal'] and r['observer_stopped']
    assert len(r['discarded_reconstructable_serving_copies'])==3
    assert retained.read_text()=='immutable outcome' and frozen.read_text()=='original data'
