import io
from pathlib import Path
import tarfile
import pytest
from bootstrap_ch6_linux_runtime import unpack,portable_constraints


def archive(tmp_path, names, *, link=None):
    path=tmp_path/'input.tar'
    with tarfile.open(path,'w') as target:
        for name in names:
            info=tarfile.TarInfo(name);info.size=2
            target.addfile(info,io.BytesIO(b'ok'))
        if link:
            info=tarfile.TarInfo(link[0]);info.type=tarfile.SYMTYPE;info.linkname=link[1]
            target.addfile(info)
    return path


@pytest.mark.parametrize('names', [['../escape'],['same','same'],['/absolute']])
def test_bad_paths_rejected_before_creating_output(tmp_path,names):
    with pytest.raises(ValueError):unpack(archive(tmp_path,names),tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_link_parent_and_expansion_budget_rejected(tmp_path):
    path=archive(tmp_path,['link/file'],link=('link','dir'))
    with pytest.raises(ValueError):unpack(path,tmp_path/'out',allow_links=True)
    assert not (tmp_path/'out').exists()
    path=archive(tmp_path,['valid'])
    with pytest.raises(ValueError):unpack(path,tmp_path/'out',max_bytes=1)


def test_only_contained_nonparent_java_links_allowed(tmp_path):
    path=archive(tmp_path,['lib/source'],link=('src','lib/source'))
    with pytest.raises(ValueError):unpack(path,tmp_path/'rejected')
    unpack(path,tmp_path/'out',allow_links=True)
    assert (tmp_path/'out/src').read_bytes()==b'ok'


def test_mac_source_reference_maps_to_same_frozen_author_bytes():
    result=portable_constraints('appnope==1.0.0\nredis==5.2.1\nlitellm @ file:///old/litellm-1.37.19.tar.gz\n')
    assert 'file:' not in result and 'appnope' not in result
    assert 'redis==5.2.1' in result and '#sha256=61ce6448' in result
    with pytest.raises(ValueError):portable_constraints('unknown @ file:///private/unknown.whl')
