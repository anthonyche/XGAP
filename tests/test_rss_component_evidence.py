"""Mapped pages stay in the hard guard; unavailable diagnostics remain unknown."""
from types import SimpleNamespace

import xgap.experiments.owned_resources as resources


def test_linux_breakdown_does_not_discount_file_rss(monkeypatch):
    process=SimpleNamespace(pid=123,poll=lambda:None)
    monkeypatch.setattr(resources.psutil,'Process',lambda _:SimpleNamespace(
        create_time=lambda:1.,cpu_times=lambda:SimpleNamespace(user=0.,system=0.)))
    monkeypatch.setattr(resources,'_group_sample',lambda _:[dict(pid=123,created=1.,rss=8192)])
    monkeypatch.setattr(resources.Path,'read_text',lambda _:'RssAnon:\t1 kB\nRssFile:\t7 kB\nRssShmem:\t0 kB\n')
    monitor=resources.OwnedResources([resources.OwnedProcess('fixture','source',process)],source_rss_bytes=4096)
    assert monitor.sample([])=='source_rss_limit_observed'
    assert monitor.summary()['last_linux_rss_components']['123']['bytes']==dict(RssAnon=1024,RssFile=7168,RssShmem=0)
    def missing(_):raise FileNotFoundError('No procfs')
    monkeypatch.setattr(resources.Path,'read_text',missing)
    second=resources.OwnedResources([resources.OwnedProcess('fixture','source',process)],source_rss_bytes=16384)
    assert second.sample([]) is None
    assert second.summary()['last_linux_rss_components']=={}
