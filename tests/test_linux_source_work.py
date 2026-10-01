from xgap.experiments.linux_source_work import LinuxSourceWork,read_counters


def proc(tmp_path, *, start=17,minor=20,major=3,io=True):
    p=tmp_path/'123';p.mkdir(exist_ok=True)
    s=['0']*50;s[0]='R';s[7]=str(minor);s[9]=str(major);s[19]=str(start)
    (p/'stat').write_text('123 (name with ) and spaces) '+' '.join(s))
    if io:(p/'io').write_text('read_bytes: 1024\nsyscr: 10\n')
    return p


def test_deltas_and_missing_are_distinct(tmp_path):
    p=proc(tmp_path);m=LinuxSourceWork(proc_root=tmp_path);m.observe(123,1.,'source')
    proc(tmp_path,minor=30,major=5);(p/'io').write_text('read_bytes: 4096\nsyscr: 10\n')
    m.observe(123,1.,'source');d=m.summary()['processes'][0]['observed_delta']
    assert d['major_faults']==2 and d['minor_faults']==10 and d['read_bytes']==3072
    assert d['syscr']==0 and d['write_bytes'] is None


def test_pid_reuse_cannot_charge_another_process(tmp_path):
    proc(tmp_path);m=LinuxSourceWork(proc_root=tmp_path);m.observe(123,1.,'source')
    proc(tmp_path,start=99,major=800);m.observe(123,1.,'source')
    r=m.summary()['processes'][0]
    assert r['identity_changed'] and all(v is None for v in r['observed_delta'].values())


def test_nonlinux_and_single_sample_are_unknown(tmp_path):
    assert read_counters(123,proc_root=tmp_path) is None
    m=LinuxSourceWork(proc_root=tmp_path);m.observe(123,1.,'source')
    proc(tmp_path,io=False);m.observe(123,1.,'source')
    assert all(v is None for v in m.summary()['processes'][0]['observed_delta'].values())


def test_counter_reset_is_not_zero_work(tmp_path):
    proc(tmp_path);m=LinuxSourceWork(proc_root=tmp_path);m.observe(123,1.,'source')
    proc(tmp_path,major=1);m.observe(123,1.,'source')
    assert m.summary()['processes'][0]['observed_delta']['major_faults'] is None
