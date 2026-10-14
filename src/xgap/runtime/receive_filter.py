"""Private, uncommitted reception filter; never publishes a prefix of a response."""
import json
from xgap.runtime.row_operations import condition_fields,_matches
from xgap.runtime.row_size import encoded_row_size
from xgap.runtime.scalars import stable_text


class ReceiveFilter:
    def __init__(self,workspace,node,budget=None):
        self.workspace=workspace;self.node=node;self.budget=budget
        self.store=workspace.store();self.received=0;self.count=0;self.encoded_bytes=2
        self.error=None;self.native_arrays=0;self.native_arrays_spooled=0
        try:self.fields=condition_fields(node.parameters['condition'])
        except Exception as error:self.fail(error)
    def fail(self,error):
        if self.error is None:self.error=f'{type(error).__name__}: {error}'
    def __call__(self,row):
        self.workspace.control.check()
        if not isinstance(row,dict):raise ValueError('Backend returned a non-row value')
        self.received+=1
        if self.budget and self.received>self.budget['fetch_rows']:
            raise ValueError('Backend exceeded the compiled relationship fetch bound')
        if self.budget and self.received>self.budget['rows']:return
        # Validate and meter even discarded rows, exactly as the old source spool.
        self.encoded_bytes+=encoded_row_size(row)+int(self.count>0);self.count+=1
        if self.error is not None:return
        try:
            # The old spool normalizes Decimal/tuples and JSON object keys before
            # filtering. Keep that representation for all predicate operands.
            if any(type(k) is not str for k in row):row=json.loads(stable_text(row))
            if not self.fields<=row.keys():raise ValueError('Row filter references a missing field')
            normalized=row
            if any(type(row[k]) not in (str,int,float,bool,type(None)) for k in self.fields):
                normalized=dict(row)
                for k in self.fields:
                    if type(row[k]) not in (str,int,float,bool,type(None)):
                        normalized[k]=json.loads(stable_text(row[k]))
            keep=_matches(normalized,self.node.parameters['condition'])
        except Exception as error:
            self.fail(error);return
        if keep:self.store.append(row)
    def close(self):self.store.close()
