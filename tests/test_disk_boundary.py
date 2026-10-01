"""Live loader disk samples tolerate deletion races without hiding I/O faults."""
from contextlib import contextmanager
import errno
from pathlib import Path
from types import SimpleNamespace

import pytest

import prepare_rdf_tdb as loader


@pytest.fixture(autouse=True)
def ample_disk(monkeypatch):
    monkeypatch.setattr(loader.shutil, 'disk_usage', lambda _: SimpleNamespace(free=20*loader.GIB))


def test_removed_descendant_directory_does_not_abort_sample(tmp_path, monkeypatch):
    (tmp_path/'store').write_bytes(b'12345')
    transient=tmp_path/'data/databases/neo4j/temp';transient.mkdir(parents=True)
    original=loader.os.scandir

    def remove_before_scan(directory):
        if Path(directory)==transient:transient.rmdir()
        return original(directory)

    monkeypatch.setattr(loader.os, 'scandir', remove_before_scan)
    monitor=loader.DiskBoundary(tmp_path, max_store_bytes=4)
    assert monitor.sample(None, force=True)=='offline_store_disk_budget_reached'
    assert monitor.peak==5
    assert not transient.exists()


def test_removed_file_between_listing_and_stat_is_tolerated(tmp_path, monkeypatch):
    transient=tmp_path/'temp';transient.write_bytes(b'temporary')
    (tmp_path/'store').write_bytes(b'12345')
    original=loader.os.scandir

    @contextmanager
    def remove_after_listing(directory):
        with original(directory) as entries:
            def removing_entries():
                for entry in entries:
                    if Path(entry.path)==transient:transient.unlink()
                    yield entry
            yield removing_entries()

    monkeypatch.setattr(loader.os, 'scandir', remove_after_listing)
    monitor=loader.DiskBoundary(tmp_path)
    assert monitor.sample(None, force=True) is None
    assert monitor.peak==5


@pytest.mark.parametrize('during_scan', [False, True])
def test_missing_root_remains_a_monitor_failure(tmp_path, monkeypatch, during_scan):
    original=loader.os.scandir
    if during_scan:
        transient=tmp_path/'temp';transient.mkdir()

        def remove_root_during_scan(directory):
            if Path(directory)==transient:
                transient.rmdir();tmp_path.rmdir()
            return original(directory)

        monkeypatch.setattr(loader.os, 'scandir', remove_root_during_scan)
    else:
        tmp_path.rmdir()
    with pytest.raises(FileNotFoundError):
        loader.DiskBoundary(tmp_path).sample(None, force=True)


@pytest.mark.parametrize('error_number', [errno.EACCES, errno.EIO])
@pytest.mark.parametrize('location', ['root', 'directory', 'file'])
def test_other_io_errors_are_never_suppressed(tmp_path, monkeypatch, error_number, location):
    target=tmp_path if location=='root' else tmp_path/'child'
    if location=='file':target.write_bytes(b'x')
    elif location=='directory':target.mkdir()
    original=loader.os.scandir

    @contextmanager
    def failing_scan(directory):
        if location!='file' and Path(directory)==target:
            raise OSError(error_number, 'injected storage failure', str(target))
        with original(directory) as entries:
            def checked_entries():
                for entry in entries:
                    if location=='file' and Path(entry.path)==target:
                        def fail_stat(*args, **kwargs):
                            raise OSError(error_number, 'injected storage failure', str(target))
                        yield SimpleNamespace(path=entry.path, stat=fail_stat)
                    else:yield entry
            yield checked_entries()

    monkeypatch.setattr(loader.os, 'scandir', failing_scan)
    with pytest.raises(OSError) as caught:
        loader.DiskBoundary(tmp_path).sample(None, force=True)
    assert caught.value.errno==error_number


def test_file_counting_peak_quota_and_sample_cadence_are_preserved(tmp_path, monkeypatch):
    regular=tmp_path/'regular';regular.write_bytes(b'123')
    nested=tmp_path/'nested';nested.mkdir();(nested/'data').write_bytes(b'1234')
    (tmp_path/'file-link').symlink_to(regular)
    (tmp_path/'dir-link').symlink_to(nested, target_is_directory=True)
    (tmp_path/'missing-link').symlink_to(tmp_path/'absent')
    now=[10.0];monkeypatch.setattr(loader.time, 'monotonic', lambda: now[0])
    monitor=loader.DiskBoundary(tmp_path, max_store_bytes=10)
    assert monitor.sample(None) is None
    assert monitor.peak==10
    regular.write_bytes(b'1234')
    now[0]+=.5
    assert monitor.sample(None) is None
    assert monitor.peak==10
    assert monitor.sample(None, force=True)=='offline_store_disk_budget_reached'
    assert monitor.peak==12
    regular.write_bytes(b'')
    assert monitor.sample(None, force=True)=='offline_store_disk_budget_reached'
    assert monitor.peak==12


def test_free_space_reserve_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(loader.shutil, 'disk_usage', lambda _: SimpleNamespace(free=5*loader.GIB))
    monitor=loader.DiskBoundary(tmp_path)
    assert monitor.sample(None, force=True)=='offline_free_disk_reserve_reached'
    assert monitor.minimum_free==5*loader.GIB
