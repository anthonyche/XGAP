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
