"""Focused new controller risks only; no source/model calls or old gate repeats."""
from pathlib import Path
import pytest
import run_practical_campaign as campaign


def test_unstarted_never_retries_an_indeterminate_intent(tmp_path):
    schedule = {'cells': [{'cell_id': name} for name in ('indeterminate', 'sealed', 'new')]}
    (tmp_path / 'indeterminate').mkdir()
    (tmp_path / 'sealed').mkdir()
    campaign.write_once(tmp_path / 'sealed' / 'terminal.json', {'status': 'failed'})
    assert campaign.unstarted(schedule, tmp_path) == [{'cell_id': 'new'}]


def test_resume_requires_all_owned_sessions_verified_closed(tmp_path):
    session = tmp_path / 'sessions' / 'session-000'; session.mkdir(parents=True)
    with pytest.raises(ValueError, match='not verified closed'): campaign.assert_closed(tmp_path)
    campaign.write_once(session / 'closed.json', dict.fromkeys(campaign.CLOSED, True))
    campaign.assert_closed(tmp_path)
    second = tmp_path / 'sessions' / 'session-001'; second.mkdir()
    campaign.write_once(second / 'closed.json', {**dict.fromkeys(campaign.CLOSED, True), 'observer_stopped': False})
    with pytest.raises(ValueError, match='not verified closed'): campaign.assert_closed(tmp_path)


def test_failed_finalization_retires_before_next_cell_without_retry(tmp_path, monkeypatch):
    sessions = []; attempted = []
    class Session:
        def __init__(self, *, root, **kwargs):
            self.root = Path(root); self.root.mkdir(parents=True)
            self.closed = False; self.owned = []; self.observer = object(); self.ready_pin = None
            sessions.append(self)
        def start(self):
            assert all(s.closed for s in sessions[:-1])
        def close(self):
            self.closed = True; closure = dict.fromkeys(campaign.CLOSED, True)
            campaign.write_once(self.root / 'closed.json', closure)
            return closure
    def dispatch(**kwargs):
        schedule = campaign.read({'path': kwargs['schedule_path'], 'sha256': kwargs['schedule_sha256']})
        cell = campaign.unstarted(schedule, kwargs['ledger'])[0]; attempted.append(cell['cell_id'])
        root = kwargs['ledger'] / cell['cell_id']; root.mkdir(parents=True)
        campaign.write_once(root / 'intent.json', cell)
        outcome = campaign.write_once(root / 'receipt.json', {'can_continue_session': True})
        # The method returned, but source release failed on the first cell.
        campaign.write_once(root / 'session-finalization.json', {'can_continue_session': len(attempted) > 1})
        row = {'cell_id': cell['cell_id'], 'status': 'outcome_sealed', 'outcome': outcome}
        campaign.write_once(root / 'terminal.json', row)
        return [row]
    monkeypatch.setattr(campaign, 'source_commit', lambda: 'frozen')
    monkeypatch.setattr(campaign, 'NativeStoreSession', Session)
    monkeypatch.setattr(campaign, 'dispatch_practical_group', dispatch)
    schedule = campaign.write_once(tmp_path / 'schedule.json', {'methods': ['xgap-strong-exact', 'xgap-strong-performance'],
        'cells': [{'cell_id': name, 'group_index': 0} for name in ('a', 'b')]})
    release = campaign.write_once(tmp_path / 'release.json', {'schema_version': 'xgap-practical-campaign-release-v1',
        'formal_campaign_ready': True, 'source_commit': 'frozen', 'driver': campaign.pin(campaign.__file__),
        'studies': {'native': {'schedule': schedule, 'prepared': {'path': 'unused', 'sha256': '0'*64}}},
        'source_budget': {}, 'process_budget': {}})
    result = campaign.execute(release, 'native', tmp_path / 'run', 2)
    report = campaign.read(result)
    assert attempted == ['a', 'b'] and len(sessions) == 2
    assert report['success'] and report['remaining_unstarted'] == 0
    assert report['prior_journal_files_unchanged'] and not report['indeterminate_cells']
