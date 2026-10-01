"""Replay Linux service shutdown races without loading another dataset."""
from types import SimpleNamespace
import subprocess

import rdf_tdb_session as sessions
from xgap.experiments.campaign_source_observer import CampaignSourceObserver,SourceObservationBudget


def test_late_owned_child_reap_and_observer_shutdown_are_independent(tmp_path,monkeypatch):
    monkeypatch.setattr(sessions,'_stop_group',lambda *_:dict(complete=False,live_pids=[],signals=['SIGTERM']))
    for finishes in (True,False):
        root=tmp_path/str(finishes);root.mkdir()
        class Child:
            pid=12345
            returncode=None
            def poll(self):return self.returncode
            def wait(self,timeout):
                assert timeout==3
                if not finishes:raise subprocess.TimeoutExpired('fixture',timeout)
                self.returncode=-15;return -15
        monkeypatch.setattr(sessions,'_group_sample',lambda _:[])
        monkeypatch.setattr(sessions.psutil,'Process',lambda _:SimpleNamespace(status=lambda:'zombie'))
        child=Child();session=sessions.RdfTdbSession.__new__(sessions.RdfTdbSession)
        session.root=root;session.processes=SimpleNamespace(owned=[('source',child)],logs=[])
        session.ports=None;session.discard_serving_copies=False
        session.observer=CampaignSourceObserver({},root/'observer',budget=SourceObservationBudget())
        assert session.observer.thread.is_alive()
        result=session.close()
        assert result['observer_stopped'] and not session.observer.thread.is_alive()
        assert result['owned_groups_drained'] is finishes
        assert result['processes'][0]['cleanup']['complete'] is finishes


def test_failed_nfs_reclamation_still_seals_quiescence(tmp_path,monkeypatch):
    session=sessions.RdfTdbSession.__new__(sessions.RdfTdbSession)
    session.root=tmp_path;session.processes=SimpleNamespace(owned=[],logs=[])
    session.ports=None;session.observer=None;session.discard_serving_copies=True
    session.prepared={'stores':{'graph':{}}}
    (tmp_path/'graph-tdb2').mkdir()
    def busy(path):raise OSError(39,'Directory not empty',str(path))
    monkeypatch.setattr(sessions.shutil,'rmtree',busy)
    result=session.close()
    assert result['owned_groups_drained'] and result['observer_stopped']
    assert not result['serving_copy_reclamation_complete']
    assert len(result['retained_serving_copy_errors'])==1
    assert (tmp_path/'closed.json').exists() and (tmp_path/'graph-tdb2').exists()
