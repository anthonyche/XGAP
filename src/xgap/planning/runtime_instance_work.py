"""Frozen instance-to-reference-engine feature projection; no refit or execution.

Keep each actual endpoint's source identity and statistics during extraction.
Then sum its work into a declared trained backend's feature basis. This shares
weights across same-engine instances; it does not establish transfer accuracy.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import time

from xgap.planning.runtime_estimator import FrozenSourceStatistics, _hash, _json, _text
from xgap.planning.runtime_work_estimator import (
    FAMILIES, MODES, MEASURES, REMOTE, FrozenWorkEstimator, WorkFeatures, extract_work_features,
)


INSTANCE_SCHEMA = 'xgap-frozen-instance-work-deployment-v1'


@dataclass(frozen=True)
class FrozenInstanceWorkDeployment:
    model_version: str
    trained_model: FrozenWorkEstimator
    statistics: FrozenSourceStatistics
    reference_backends: tuple
    preparation_ref: str

    def __post_init__(self):
        _text(self.model_version,'deployment version');_text(self.preparation_ref,'preparation reference')
        if not isinstance(self.trained_model,FrozenWorkEstimator) or not isinstance(self.statistics,FrozenSourceStatistics):
            raise TypeError('Instance deployment requires original work model and actual source statistics')
        pairs=tuple(sorted(tuple(p) for p in self.reference_backends))
        if any(len(p)!=2 for p in pairs):raise ValueError('Expected instance/reference pairs')
        object.__setattr__(self,'reference_backends',pairs)
        actual={s.backend_id for s in self.statistics.entries}
        trained={s.backend_id for s in self.trained_model.statistics.entries}
        if (not 1<=len(actual)<=64 or len(pairs)!=len(actual) or {p[0] for p in pairs}!=actual
                or any(p[1] not in trained or p[1] not in {'neo4j','fuseki'} for p in pairs)):
            raise ValueError('Every instance needs one supported trained reference backend')

    @property
    def feature_schema_sha256(self):return self.trained_model.feature_schema_sha256

    @property
    def model_sha256(self):return self.to_dict()['model_sha256']

    def to_dict(self):
        body={'schema_version':INSTANCE_SCHEMA,'model_version':self.model_version,
            'trained_model':self.trained_model.to_dict(),'statistics':self.statistics.to_dict(),
            'reference_backends':dict(self.reference_backends),'preparation_ref':self.preparation_ref,
            'feature_schema_sha256':self.feature_schema_sha256,
            'training_provenance':self.trained_model.to_dict()['training_provenance'],
            'deployment_provenance':{'parent_model_sha256':self.trained_model.model_sha256,
                'feature_projection':'sum_instance_work_into_declared_reference_backend_v1',
                'reference_engine_semantics':'builtin neo4j/fuseki training backend labels',
                'serving_source_statistics_sha256':self.statistics.sha256,
                'weights_changed':False,'fit_calls':0,'collection_calls':0,
                'transfer_calibrated':False,'quality_bound':None}}
        return {**body,'model_sha256':_hash(body)}

    @classmethod
    def from_dict(cls,data):
        body=dict(data);digest=body.pop('model_sha256',None)
        if body.get('schema_version')!=INSTANCE_SCHEMA or _hash(body)!=digest:
            raise ValueError('Instance deployment schema/hash mismatch')
        result=cls(body['model_version'],FrozenWorkEstimator.from_dict(body['trained_model']),
            FrozenSourceStatistics.from_dict(body['statistics']),tuple(body['reference_backends'].items()),body['preparation_ref'])
        if result.to_dict()!=data:raise ValueError('Instance deployment provenance mismatch')
        return result

    def save(self,path):
        with Path(path).open('x') as stream:stream.write(_json(self.to_dict())+'\n')

    def predict(self,plan):
        started=time.perf_counter()
        actual=extract_work_features(plan,self.statistics)
        known={s.backend_id:s for s in self.statistics.entries}
        identities=plan.metadata.get('source_identities',{})
        unknown=list(actual.unknown_fields)
        for node in plan.nodes:
            if node.kind not in REMOTE:continue
            instance=node.parameters.get('backend_id');source=known.get(instance)
            identity=identities.get(instance) if isinstance(identities,dict) else None
            if source is None or identity!={'source_id':source.source_id,'snapshot_version':source.snapshot_version}:
                unknown.append(f'backend.{instance}.deployment_source_identity_mismatch')
        routing={}
        for instance,reference in self.reference_backends:
            for family in FAMILIES:
                for mode in MODES:
                    for measure in MEASURES:
                        tail=f'{family}.{mode}.{measure}'
                        routing[f'backend.{instance}.{tail}']=f'backend.{reference}.{tail}'
        values=dict.fromkeys(self.trained_model.feature_names,0.0)
        for name,value in zip(actual.names,actual.values):
            target=routing.get(name,name)
            if target not in values:raise ValueError('Unmapped instance feature')
            values[target]=None if value is None or values[target] is None else values[target]+value
        projected=WorkFeatures(self.trained_model.feature_names,
            tuple(values[n] for n in self.trained_model.feature_names),self.feature_schema_sha256,
            tuple(sorted(set(unknown))))
        prediction=self.trained_model._predict_features(plan,self.statistics,projected,started=started)
        return replace(prediction,prediction_elapsed_ms=(time.perf_counter()-started)*1000,
            provenance={**prediction.provenance,**self.to_dict()['deployment_provenance'],
                'model_version':self.model_version,'model_sha256':self.model_sha256,
                'reference_backends':dict(self.reference_backends),'instance_features':actual.to_dict(),
                'preparation_ref':self.preparation_ref,
                'uncertainty_scope':'parent residual only; source-instance/engine transfer uncalibrated'})
