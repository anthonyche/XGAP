"""Finite package disk/time/admission budgets layered over common method limits."""
from pathlib import Path
import shutil
import time

GIB=1024**3


class CampaignBudget:
    def __init__(self,root,*,maximum_cells,seconds=3600,max_bytes=12*GIB,reserve_bytes=6*GIB):
        if type(maximum_cells) is not int or not 1<=maximum_cells<=16:raise ValueError('Campaign chunk must contain1..16cells')
        self.root=Path(root);self.maximum_cells=maximum_cells;self.seconds=seconds
        self.max_bytes=max_bytes;self.reserve_bytes=reserve_bytes
        self.started=time.monotonic();self.attempted=0;self.last_sample=0;self.status=None;self.peak_bytes=0;self.free_bytes=None

    def sample(self,_):
        if time.monotonic()-self.started>=self.seconds:self.status='campaign_wall_budget'
        if time.monotonic()-self.last_sample>=.5:
            self.last_sample=time.monotonic()
            size=sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file())
            self.peak_bytes=max(size,self.peak_bytes);self.free_bytes=shutil.disk_usage(self.root).free
            if size>self.max_bytes:self.status='campaign_disk_budget'
            if self.free_bytes<self.reserve_bytes:self.status='campaign_free_disk_reserve'
        return self.status

    def readiness(self):
        self.sample([])
        reason=self.status
        if self.attempted>=self.maximum_cells:reason='chunk_cell_budget'
        if self.seconds-(time.monotonic()-self.started)<300:reason='insufficient_complete_cell_time'
        if self.free_bytes is not None and self.free_bytes<self.reserve_bytes+2*GIB:reason='insufficient_complete_cell_disk_reserve'
        return {'ready':reason is None,'reason':reason,**self.summary()}

    def admit(self):
        if not self.readiness()['ready']:raise ValueError('Campaign package cannot admit another cell')
        self.attempted+=1

    def summary(self):
        return {'maximum_cells':self.maximum_cells,'attempted':self.attempted,'seconds':self.seconds,
            'max_bytes':self.max_bytes,'reserve_bytes':self.reserve_bytes,'sampled_peak_bytes':self.peak_bytes,
            'latest_free_bytes':self.free_bytes,'elapsed_seconds':time.monotonic()-self.started,
            'status':self.status,'scope':'package disk/time sampling; native method/source RSS separately guarded'}
