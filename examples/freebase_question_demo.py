"""Controlled question -> provider contract -> RDF-backed answer, no live LLM.

The Neo4j path rows and model response are explicit fixtures. Literal filtering
and the optional independent baseline use RDFLib's actual SPARQL evaluator.
"""

import json
from pathlib import Path
import runpy
from types import SimpleNamespace

from xgap.backends.fuseki_client import FusekiClient
from xgap.backends.rdf_terms import RdfTerm
from xgap.experiments.freebase_candidate_compiler import ExecutionRequirements, FreebaseExecutionMapping, NS
from xgap.experiments.freebase_question import answer_question
from xgap.experiments.grailqa_semantic_pilot import GenerationResult
from xgap.infrastructure.descriptors import BackendDescriptor
from xgap.infrastructure.runtime import ExecutionReport


def main():
    from rdflib import Graph
    fixture = runpy.run_path(str(Path(__file__).with_name('grounded_candidate_execution_demo.py')))
    raw, request, view = fixture['controlled_recording_case']('m.recording', filter_value='1')
    graph = Graph().parse(data=f'''@prefix f: <{NS}> .
      f:m.track f:music.release_track.recording f:m.recording ;
                f:music.release_track.release f:m.release ;
                f:music.release_track.track_number "1" .''', format='turtle')

    class RdfEngine(FusekiClient):
        def _post_query(self, text):
            return json.loads(graph.query(text).serialize(format='json'))

    class ControlledPaths:
        backend_id = 'neo4j'
        def execute(self, artifact):
            rows = [{**{f'n{i}':NS+v for i,v in enumerate(('m.recording','m.track','m.release'))},
                     'answer':RdfTerm('uri',NS+'m.release').to_binding()}]
            return ExecutionReport('neo4j',artifact.artifact_id,'cypher',True,rows=rows)

    retrieval = SimpleNamespace(to_dict=lambda:{'source':'controlled-inference-catalog'})
    catalog = SimpleNamespace(retrieve=lambda *a,**kw:retrieval,prompt_view=lambda *a,**kw:view)
    provider = SimpleNamespace(generate=lambda *a:GenerationResult(raw,(),
        {'generation_calls':0,'repair_calls':0,'controlled_response':True},0.0,0,True))
    result = answer_question(question_record={'question_id':view.task_id,'text':request.question},
        catalog=catalog,provider_factory=lambda qid:provider,
        mapping=FreebaseExecutionMapping('synthetic-facts','a'*64,{'music.release_track.track_number':'string'}),
        requirements=ExecutionRequirements(True),neo4j=ControlledPaths(),
        fuseki=RdfEngine(BackendDescriptor('fuseki','fuseki','sparql','rdf')),verify_baseline=True)
    assert result['success'] and result['answer_count'] == 1, result
    print(json.dumps({'controlled_fixture':True,'live_llm':False,'live_neo4j':False,'result':result},indent=2))


if __name__ == '__main__':
    main()
