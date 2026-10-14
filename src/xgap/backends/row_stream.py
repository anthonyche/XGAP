"""Native HTTP envelopes spill their row arrays before typed row conversion."""
from contextvars import ContextVar
from xgap.backends.request_control import current_control
from xgap.backends.rdf_terms import RDF_TERMS_V1,parse_select_results
from xgap.backends.sparql_bindings import bind_sparql_iris

array_factory=ContextVar('xgap_json_array_factory',default=None)


def execute_native_stream(client,artifact,emit,control,workspace):
    expected='cypher' if hasattr(client,'_post_statement') else 'sparql'
    if artifact.language.lower()!=expected or artifact.kind not in ('native','compiled'):
        raise ValueError('Native stream artifact language/kind differs')
    raw_stores=[]
    def factory(path):
        if path not in (('results','*','data'),('results','bindings')):return None
        store=workspace.store();raw_stores.append(store);return store
    token=array_factory.set(factory);scope=current_control.set(control)
    try:
        if expected=='cypher':
            response=client._post_statement(artifact.text,artifact.parameters)
            for result in response.get('results',[]):
                for item in result.get('data',[]):
                    control.check()
                    for row in client._rows_from_response({'results':[{'columns':result.get('columns',[]),'data':[item]}]}):emit(row)
        else:
            encoding=artifact.parameters.get('rdf_result_encoding')
            if encoding not in (None,RDF_TERMS_V1):raise ValueError('Unsupported RDF result encoding')
            columns=artifact.parameters.get('expected_result_columns')
            if columns is not None and (not isinstance(columns,list) or len(set(columns))!=len(columns)
                or any(not isinstance(c,str) or not c for c in columns)):raise ValueError('Invalid expected RDF columns')
            response=client._post_query(bind_sparql_iris(artifact.text,artifact.parameters))
            head=response.get('head');bindings=response.get('results',{}).get('bindings')
            if bindings is None:raise ValueError('Missing SELECT bindings')
            def convert(items):
                envelope={'head':head,'results':{'bindings':items}}
                return parse_select_results(envelope,expected_columns=None if columns is None else tuple(columns)) if encoding==RDF_TERMS_V1 else client._rows_from_response(envelope)
            convert([]) # Validate even an empty envelope.
            for item in bindings:
                control.check()
                for row in convert([item]):emit(row)
        control.check()
    finally:
        current_control.reset(scope);array_factory.reset(token)
        for store in raw_stores:store.close()
