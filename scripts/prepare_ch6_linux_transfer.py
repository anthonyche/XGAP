#!/usr/bin/env python3
"""Package verified platform-neutral runtime inputs, never Mac executables/keys.

Original repositories travel as Git bundles. Linux rebuilds Redis/Python and
pins its own Java executable. Existing author JAR bytes remain unchanged.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from xgap.experiments.ch6_formal_protocol import pin_file,load_pin
from xgap.experiments.one_shot_records import write_once


def prepare(data_root,profile_path,output):
    data=Path(data_root);root=Path(output).resolve();root.mkdir(parents=True,exist_ok=False)
    files={};repos={}
    def copy(source,relative):
        source=Path(source);target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target);pin=pin_file(target)
        files[relative]=dict(sha256=pin['sha256'],bytes=pin['bytes'])
        return relative
    for label,path,expected in [
        ('aruqula',data/'aruqula-intake-20260920-v1','9a3982baca03d62f7250572e300b1e4ba47727cc'),
        ('lookup',data/'ch7-lookup-intake-20260921-v1/source','939b3f36fefafca444cc6dff6c568c5b559f58e0'),
        ('redis',data/'ch7-baseline-dependencies-20260921-v1/redis-github/source',None)]:
        if Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=path,text=True).strip())!=path:
            raise ValueError('Expected an independent author checkout')
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=path,text=True).strip()
        if expected and head!=expected:raise ValueError('Author commit changed')
        if subprocess.check_output(['git','diff','HEAD','--'],cwd=path):raise ValueError('Tracked author files changed')
        bundle=root/(label+'.bundle');subprocess.run(['git','bundle','create',str(bundle),'HEAD'],cwd=path,check=True)
        p=pin_file(bundle);files[bundle.name]=dict(sha256=p['sha256'],bytes=p['bytes']);repos[label]=head
    copy(data/'aruqula-runtime-20260921-v1/author-pip-requirements.txt','author-requirements.txt')
    copy(data/'aruqula-runtime-20260921-v1/installed-packages.txt','mac-reference-packages.txt')
    classpath=(data/'ch7-lookup-intake-20260921-v1/runtime-classpath.txt').read_text().strip().split(':')
    names=[]
    for index,path in enumerate(classpath):names.append(copy(path,f'lookup-deps/{index:03d}-{Path(path).name}'))
    copy(data/'ch7-lookup-intake-20260921-v1/source/lookup/target/lookup-1.0.jar','lookup.jar')
    build=load_pin(pin_file(data/'ch6-fedx-transport-build-20260922-v4/receipt.json'))
    copy(build['jar']['path'],'fedx-protocol.jar');copy(build['base']['path'],'fedx-original.jar')
    copy(data/'d202-local-native-20260910-diagnostic2/runtime/apache-jena-fuseki-5.6.0/fuseki-server.jar','fuseki-server.jar')
    profile=load_pin(pin_file(profile_path));portable=deepcopy(profile)
    # Keep historical provenance intact, and explicitly replace only live file
    # references. A host publisher will bind these relative paths absolutely.
    copy(profile['estimator']['path'],'tiny/estimator.json');portable['estimator']['path']='tiny/estimator.json'
    catalog=Path(profile['catalog']['path'])
    for p in sorted(catalog.rglob('*')):
        if p.is_file():copy(p,'tiny/catalog/'+str(p.relative_to(catalog)))
    portable['catalog']['path']='tiny/catalog'
    for name,load in portable['offline']['rdf_loads'].items():
        load['path']=copy(load['path'],f'tiny/{name}.ttl')
    for mode in portable['modes'].values():
        prompt=mode['provider']['prompt'];relative='tiny/prompt-'+prompt['sha256'][:12]+'.txt'
        if relative not in files:copy(prompt['path'],relative)
        prompt['path']=relative
    meta=portable['offline']['shared_public_metadata'];meta['path']=copy(meta['path'],'tiny/metadata.nt')
    source_profile=pin_file(profile_path)
    write_once(root/'portable-profile.json',portable)
    p=pin_file(root/'portable-profile.json');files['portable-profile.json']=dict(sha256=p['sha256'],bytes=p['bytes'])
    manifest=dict(schema_version='xgap-ch6-linux-transfer-v1',files=files,repositories=repos,classpath=names,
        source_profile=source_profile,source_fedx_build=build,platform_neutral_only=True,
        credentials_included=False,model_calls=0,backend_calls=0,formal_campaign_ready=False)
    write_once(root/'manifest.json',manifest)
    archive=root.with_suffix('.tar.gz')
    with tarfile.open(archive,'x:gz') as tar:
        for name in sorted([*files,'manifest.json']):tar.add(root/name,arcname=name,recursive=False)
    print(json.dumps(pin_file(archive)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('data-root','profile-path','output'):p.add_argument('--'+key,required=True)
    prepare(**vars(p.parse_args()))
