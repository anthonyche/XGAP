"""Recompile only our HTTP envelope; retain every pinned external JAR entry."""
import argparse
from pathlib import Path
import subprocess
from zipfile import ZipFile

from check_common_rdf_trial import JAVA,JARS,PINS
from xgap.experiments.evidence_store import file_pin
from xgap.experiments.one_shot_records import write_once


def build(output):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    original=JARS['fedx']
    if file_pin(original)['sha256']!=PINS['fedx']:raise ValueError('Pinned FedX distribution changed')
    source=Path(__file__).resolve().parents[1]/'experiments/external/fedx/src/main/java/org/xgap/experiments/FedXEndpoint.java'
    classes=root/'classes';classes.mkdir()
    subprocess.run([str(Path(JAVA).with_name('javac')),'--release','21','-cp',str(original),'-d',str(classes),str(source)],check=True,timeout=60)
    jar=root/'fedx-protocol.jar'
    replacements={str(p.relative_to(classes)):p.read_bytes() for p in classes.rglob('*.class')}
    with ZipFile(original) as before,ZipFile(jar,'w') as after:
        for info in before.infolist():
            after.writestr(info,replacements.pop(info.filename,before.read(info)))
        for name,data in replacements.items():after.writestr(name,data)
    with ZipFile(original) as before,ZipFile(jar) as after:
        names={n for n in before.namelist() if not n.startswith('org/xgap/')}
        assert names=={n for n in after.namelist() if not n.startswith('org/xgap/')}
        assert all(before.read(n)==after.read(n) for n in names)
    result=dict(success=True,base=file_pin(original),source=file_pin(source),jar=file_pin(jar),
        external_entries_byte_identical=True,external_algorithm_changes=0,model_calls=0,backend_calls=0)
    write_once(root/'receipt.json',result)
    print(result['jar'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    build(p.parse_args().output)
