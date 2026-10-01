"""Bounded retirement races, without model calls or database queries."""
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
import psutil

from xgap.experiments import process_guard as guard
from xgap.experiments.owned_resources import OwnedProcess, OwnedResources


class DelayedChild:
    pid=12345
    returncode=None

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        # The saved failure used only 0.5s, too short for final JVM native threads.
        assert timeout==3.0
        self.returncode=143
        return self.returncode


def no_signal(monkeypatch):
    monkeypatch.setattr(guard.os,'killpg',lambda *_:pytest.fail('No live group may be signalled'))


def test_empty_group_waits_for_owned_leader_before_quiescence(monkeypatch):
    no_signal(monkeypatch)
    monkeypatch.setattr(guard,'_group_sample',lambda _:[])
    monkeypatch.setattr(psutil,'Process',lambda _:SimpleNamespace(create_time=lambda:123.0))
    result=guard._stop_group(DelayedChild(),guard.ProcessBudget(),expected_created=123.0)
    assert result['complete'] and result['live_pids']==[]
    assert result['post_stop_reap_returncode']==143 and result['expected_created']==123.0
    assert result['leader_reap_wait_seconds']==3.0


def test_empty_sample_without_reaped_leader_is_never_complete(monkeypatch):
    no_signal(monkeypatch)
    monkeypatch.setattr(guard,'_group_sample',lambda _:[])
    class Unreaped(DelayedChild):
        def wait(self,timeout):
            raise subprocess.TimeoutExpired('owned-child',timeout)
    result=guard._stop_group(Unreaped(),guard.ProcessBudget())
    assert not result['complete'] and result['live_pids']==[]
    assert result['post_stop_reap_returncode'] is None


def test_final_process_scan_is_followed_by_fresh_reap(monkeypatch):
    no_signal(monkeypatch)
    class LateChild(DelayedChild):
        exited=False
        def wait(self,timeout):
            raise subprocess.TimeoutExpired('owned-child',timeout)
        def poll(self):
            if self.exited:self.returncode=143
            return self.returncode
    child=LateChild();samples=[]
    def sample(_):
        samples.append(True)
        if len(samples)==2:child.exited=True
        return []
    monkeypatch.setattr(guard,'_group_sample',sample)
    result=guard._stop_group(child,guard.ProcessBudget())
    assert result['complete'] and result['post_stop_reap_returncode']==143


def test_reaped_leader_with_live_descendant_cannot_certify_quiescence(monkeypatch):
    no_signal(monkeypatch)
    samples=iter([[],[dict(pid=12346,created=125.,rss=1)]])
    monkeypatch.setattr(guard,'_group_sample',lambda _:next(samples))
    result=guard._stop_group(DelayedChild(),guard.ProcessBudget())
    assert not result['complete'] and result['live_pids']==[12346]
    assert result['post_stop_reap_returncode']==143


@pytest.mark.parametrize('already_reaped',[False,True])
def test_owned_stop_refuses_reused_leader_identity_even_if_handle_reaped(monkeypatch,already_reaped):
    no_signal(monkeypatch)
    monkeypatch.setattr(guard,'_group_sample',lambda _:pytest.fail('Changed identity must not be scanned/stopped'))
    monkeypatch.setattr(psutil,'Process',lambda _:SimpleNamespace(create_time=lambda:124.0))
    child=DelayedChild()
    if already_reaped:child.returncode=143
    owner=OwnedResources.__new__(OwnedResources)
    owner.services=(OwnedProcess('lookup','method_host',child),)
    owner.identities={child.pid:123.0}
    result=owner.stop()
    assert not result['complete']
    assert 'changed process identity' in result['groups'][0]['error']


def test_leader_identity_is_rechecked_after_delayed_wait(monkeypatch):
    no_signal(monkeypatch)
    monkeypatch.setattr(guard,'_group_sample',lambda _:[])
    identities=iter([123.0,124.0])
    monkeypatch.setattr(psutil,'Process',lambda _:SimpleNamespace(create_time=lambda:next(identities)))
    with pytest.raises(ValueError,match='changed process identity'):
        guard._stop_group(DelayedChild(),guard.ProcessBudget(),expected_created=123.0)


def test_disappearing_leader_is_still_reaped_from_owned_handle(monkeypatch):
    no_signal(monkeypatch)
    monkeypatch.setattr(guard,'_group_sample',lambda _:[])
    def missing(pid):
        raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(psutil,'Process',missing)
    child=DelayedChild()
    owner=OwnedResources.__new__(OwnedResources)
    owner.services=(OwnedProcess('lookup','method_host',child),)
    owner.identities={child.pid:123.0}
    result=owner.stop()
    assert result['complete'] and result['groups'][0]['post_stop_reap_returncode']==143


def test_real_zombie_leader_is_reaped_not_assumed_terminal():
    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.03)'],start_new_session=True)
    try:
        owned=psutil.Process(child.pid);created=owned.create_time()
        deadline=time.monotonic()+3
        while owned.status()!=psutil.STATUS_ZOMBIE and time.monotonic()<deadline:
            time.sleep(.01)
        assert owned.status()==psutil.STATUS_ZOMBIE
        assert child.returncode is None
        result=guard._stop_group(child,guard.ProcessBudget(),expected_created=created)
        assert result['complete'] and result['post_stop_reap_returncode']==0
        assert result['signals']==[] and result['live_pids']==[]
    finally:
        if child.poll() is None:
            child.kill();child.wait(timeout=3)
