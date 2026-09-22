"""Download bounded public development sources only, never databases/models.

Raw data stay outside Git. Original licenses are retained. No full benchmark,
IMDb pages, TMDB endpoint, or Wikidata service is accessed by this command.
"""
import argparse,hashlib,json
from pathlib import Path
import urllib.request

LC_COMMIT='0a5f8f85b6f863c3b80f0fa02839e25d438af3ae'
SNB_COMMIT='11db98cc2ba14c33492f6c0c34e68c8be7e22e5f'


def fetch(url,path,expected=None,cap=8*1024*1024):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raw=path.read_bytes()
    else:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'XGAP-research-development-intake'}),timeout=30) as response:
            raw=response.read(cap+1)
        if len(raw)>cap:raise ValueError('Bounded intake byte limit: '+url)
        if expected and hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Pinned source changed: '+url)
        with path.open('xb') as f:f.write(raw)
    if expected and hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Existing file hash differs: '+str(path))
    return raw


def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args();root=args.output;root.mkdir(parents=True,exist_ok=True)
    fetch('https://raw.githubusercontent.com/AskNowQA/LC-QuAD2.0/'+LC_COMMIT+'/dataset/test.json',root/'lcquad-test.json',
          'ba1500efe6308ba86af7f91033e184778204dca7ba358c77222626ae6bd3454d')
    fetch('https://files.grouplens.org/datasets/movielens/ml-latest-small.zip',root/'ml-latest-small.zip',
          '696d65a3dfceac7c45750ad32df2c259311949efec81f0f144fdfb91ebc9e436')
    tree=json.loads(fetch('https://api.github.com/repos/ldbc/ldbc_snb_interactive_v1_impls/git/trees/'+SNB_COMMIT+'?recursive=1',root/'snb-pinned-tree.json'))
    dest=root/'snb-official-tiny';records=[]
    for item in tree['tree']:
        name=item['path']
        if item['type']!='blob' or not (name.startswith('cypher/test-data/vanilla/') or name in ('LICENSE.txt','test-data.md')):continue
        if '..' in Path(name).parts or Path(name).is_absolute():raise ValueError('Unsafe source path')
        url='https://raw.githubusercontent.com/ldbc/ldbc_snb_interactive_v1_impls/'+SNB_COMMIT+'/'+name
        raw=fetch(url,dest/name)
        if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=item['sha']:raise ValueError('Git blob differs')
        records.append(dict(path=name,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob=item['sha'],url=url))
    receipt=dict(commit=SNB_COMMIT,files=records,selection='all vanilla cypher official test files; no answer-dependent selection',
                 license_scope='repository LICENSE.txt; data-specific terms must be checked before redistribution')
    out=dest/'receipt.json'
    if out.exists():
        if json.loads(out.read_text())!=receipt:raise ValueError('Existing source receipt differs')
    else:out.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'root':str(root),'sources':['LC-QuAD test structures','official SNB tiny','MovieLens development'],
                      'model_calls':0,'backend_calls':0,'formal_data_downloaded':False}))

if __name__=='__main__':main()
