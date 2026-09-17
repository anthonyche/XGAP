"""One scoped or full-intent clarification, with a pinned private authority.

The private nonce prevents its public integrity hash from being a lookup table
for the few possible hidden intents. No preflight reply exposes intent values.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from xgap.agent.intent_certificate import canonical, fingerprint
from xgap.tools.contracts import ToolEffect, ToolResult, ToolSpec


def private_family_intent(family, question, candidate_id):
    if candidate_id not in {c.candidate_id for c in family.candidates}:
        raise ValueError('Private intent is outside the declared coverage')
    return dict(schema_version='xgap-private-family-intent-v2',family_sha256=family.identity,
        question_sha256=fingerprint(question),candidate_id=candidate_id,nonce=secrets.token_hex(32))


@dataclass(frozen=True)
class ScopedFamilyUser:
    family: object
    response_path: Path
    expected_sha256: str
    name: str = 'user.scoped_family'

    @property
    def spec(self):
        return ToolSpec(self.name,'Ask for any declared intent scope, including all coordinates',
            {'type':'object','required':['family_sha256','question_sha256','slots'],
             'properties':{'family_sha256':{'const':self.family.identity},
                'question_sha256':{'type':'string'},'slots':{'type':'array','minItems':1,
                    'maxItems':len(self.family.slots),'items':{'enum':[s.name for s in self.family.slots]}}},
             'additionalProperties':False},'authoritative_family_scope',ToolEffect.READ_ONLY)

    def _load(self, question_sha256):
        with Path(self.response_path).open('rb') as stream:
            raw=stream.read(65537)
        if len(raw)>65536 or hashlib.sha256(raw).hexdigest()!=self.expected_sha256:
            raise ValueError('Private intent size/hash mismatch')
        data=json.loads(raw)
        if (set(data)!={'schema_version','family_sha256','question_sha256','candidate_id','nonce'} or
                data['schema_version']!='xgap-private-family-intent-v2' or
                data['family_sha256']!=self.family.identity or data['question_sha256']!=question_sha256 or
                not isinstance(data['nonce'],str) or not re.fullmatch('[0-9a-f]{64}',data['nonce'])):
            raise ValueError('Private intent schema, nonce or question/family identity mismatch')
        matches=[i for i,c in enumerate(self.family.candidates) if c.candidate_id==data['candidate_id']]
        if len(matches)!=1:
            raise ValueError('Private intent is outside the declared coverage')
        return matches[0]

    def preflight(self, question):
        self._load(fingerprint(question))
        return dict(ready=True,family_sha256=self.family.identity,artifact_sha256=self.expected_sha256,
            scope='private configuration checked; no intent disclosed')

    def invoke(self, arguments, context):
        started=time.perf_counter(); fields=0; reply_bytes=0
        try:
            if set(arguments)!={'family_sha256','question_sha256','slots'} or arguments['family_sha256']!=self.family.identity:
                raise ValueError('Unknown request fields or family identity')
            slots=arguments['slots']; names=[s.name for s in self.family.slots]
            if (not isinstance(slots,list) or not 1<=len(slots)<=len(names) or
                    any(not isinstance(s,str) or s not in names for s in slots) or len(set(slots))!=len(slots)):
                raise ValueError('Unknown, duplicated or empty intent scope')
            i=self._load(arguments['question_sha256'])
            answers={s:json.loads(self.family.values[i][names.index(s)]) for s in slots}
            reply={**arguments,'answers':answers}; fields=len(answers); reply_bytes=len(canonical(reply).encode())
            result=ToolResult.success(self.name,reply)
        except (OSError,ValueError,TypeError,KeyError) as error:
            result=ToolResult.error_result(self.name,str(error))
        return ToolResult(result.tool_name,result.status,result.value,result.error,metrics={
            'clarification_calls':1,'disclosed_coordinates':fields,'reply_bytes':reply_bytes,
            'model_calls':0,'tokens':0,'remote_calls':0,'elapsed_ms':(time.perf_counter()-started)*1000})
