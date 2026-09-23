"""Bounded per-owned-process Linux counters, never an inferred I/O wait time."""
from pathlib import Path


def read_counters(pid, *, proc_root=Path('/proc')):
    base=Path(proc_root)/str(pid)
    try:
        stat=(base/'stat').read_text().rsplit(')',1)[1].split()
        identity=int(stat[19])  # Field 22: starttime, not the process name.
        counters={'minor_faults':int(stat[7]),'major_faults':int(stat[9])}
    except (OSError,ValueError,IndexError):
        return None
    try:
        io=dict(line.split(':',1) for line in (base/'io').read_text().splitlines())
        for key in ('read_bytes','write_bytes','rchar','wchar','syscr','syscw'):
            if key in io:counters[key]=int(io[key])
    except (OSError,ValueError):
        pass  # Missing I/O is unknown; still retain available fault counters.
    try:
        after=(base/'stat').read_text().rsplit(')',1)[1].split()
        if int(after[19])!=identity:return None
    except (OSError,ValueError,IndexError):return None
    return {'start_ticks':identity,'counters':counters}


class LinuxSourceWork:
    def __init__(self, *, proc_root=Path('/proc')):
        self.proc_root=proc_root;self.records={}

    def observe(self,pid,created,name):
        key=(pid,created,name);sample=read_counters(pid,proc_root=self.proc_root)
        record=self.records.setdefault(key,{'first':sample,'last':sample,'samples':0,'identity_changed':False})
        if sample is None:return
        if record['first'] is None:record['first']=sample
        if sample['start_ticks']!=record['first']['start_ticks']:
            record['identity_changed']=True;return
        record['last']=sample;record['samples']+=1

    def summary(self):
        rows=[]
        keys=('minor_faults','major_faults','read_bytes','write_bytes','rchar','wchar','syscr','syscw')
        for (pid,created,name),r in sorted(self.records.items()):
            delta={k:None for k in keys}
            if r['samples']>=2 and not r['identity_changed']:
                first=r['first']['counters'];last=r['last']['counters']
                for k in keys:
                    if k in first and k in last and last[k]>=first[k]:delta[k]=last[k]-first[k]
            rows.append(dict(pid=pid,created=created,source=name,samples=r['samples'],
                identity_changed=r['identity_changed'],observed_delta=delta))
        return dict(processes=rows,scope='owned source processes, first-to-last observed sample; no global counters',
            limitations='Missing counters stay null. Short-lived work or the final tail may be missed. '
                'Faults are not scan rows; read_bytes is storage-layer process I/O, not HTTP bytes. '
                'No I/O wait duration is inferred from CPU/wall or faults.')
