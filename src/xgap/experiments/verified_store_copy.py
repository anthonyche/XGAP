"""One-pass sealed-store copy for private serving sessions, without mutation.

Hash the exact stream being copied instead of reading a large frozen store once
for verification and a second time for copying. A failed copy is never served.
This is setup I/O, not query work or an estimator observation.
"""
import hashlib
from pathlib import Path
import shutil


def copy_sealed_store(source, destination, files, *, parts=('.',)):
    source=Path(source).resolve();destination=Path(destination).absolute()
    if destination.is_symlink():raise ValueError('Serving-copy destination must be new')
    destination=destination.resolve()
    if source==destination or source in destination.parents or destination in source.parents:
        raise ValueError('Serving copy and frozen store must be disjoint')
    if destination.exists() or destination.is_symlink():
        raise ValueError('Serving-copy destination must be new')
    expected={}
    for pin in files:
        path=Path(pin['path'])
        relative=path.relative_to(source)
        if relative in expected or '..' in relative.parts or not path.is_absolute():
            raise ValueError('Invalid sealed store member')
        if type(pin['bytes']) is not int or pin['bytes']<0:
            raise ValueError('Invalid sealed store size')
        expected[relative]=pin
    actual={};directories=set()
    for part in parts:
        relative=Path(part)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid store part')
        base=source/relative
        if base.is_symlink() or not base.is_dir():raise ValueError('Invalid frozen store directory')
        directories.add(relative)
        for path in base.rglob('*'):
            if path.is_symlink():raise ValueError('Frozen store links are not admitted')
            key=path.relative_to(source)
            if path.is_dir():directories.add(key)
            elif path.is_file():
                if key in actual:raise ValueError('Overlapping store parts')
                actual[key]=path
            else:raise ValueError('Unsupported frozen store member')
    if set(actual)!=set(expected):raise ValueError('Frozen store file inventory changed')
    # Reject changed sizes before copying; verify contents on the copying pass.
    if any(p.stat().st_size!=expected[k]['bytes'] for k,p in actual.items()):
        raise ValueError('Frozen store size changed')
    destination.mkdir(parents=True,exist_ok=False)
    for relative in sorted(directories,key=lambda p:(len(p.parts),str(p))):
        (destination/relative).mkdir(parents=True,exist_ok=True)
    copied=0
    for relative,path in sorted(actual.items()):
        digest=hashlib.sha256();size=0;pin=expected[relative];target=destination/relative
        with path.open('rb') as incoming,target.open('xb') as outgoing:
            for chunk in iter(lambda:incoming.read(1024**2),b''):
                size+=len(chunk)
                if size>pin['bytes']:raise ValueError('Frozen store grew during copy')
                digest.update(chunk);outgoing.write(chunk)
        if size!=pin['bytes'] or digest.hexdigest()!=pin['sha256']:
            raise ValueError('Frozen store content changed')
        shutil.copystat(path,target);copied+=size
    return dict(profile='sealed-stream-copy-v1',files=len(actual),bytes=copied,
        source_read_passes=1,content_verified=True)
