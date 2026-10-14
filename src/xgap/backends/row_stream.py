"""Native HTTP rows remain private until the complete response is validated."""
from contextvars import ContextVar
from xgap.backends.request_control import current_control
from xgap.backends.rdf_terms import RDF_TERMS_V1,parse_select_results
from xgap.backends.sparql_bindings import bind_sparql_iris

array_factory=ContextVar('xgap_json_array_factory',default=None)


def execute_native_stream(client,artifact,emit,control,workspace):
    expected='cypher' if hasattr(client,'_post_statement') else 'sparql'
    if artifact.language.lower()!=expected or artifact.kind not in ('native','compiled'):
        raise ValueError('Native stream artifact language/kind differs')
    from xgap.runtime.receive_filter import ReceiveFilter
    private=isinstance(emit,ReceiveFilter)
    raw_stores=[];conversion_errors=[]
    encoding=artifact.parameters.get('rdf_result_encoding')
    columns=artifact.parameters.get('expected_result_columns')
    def rdf_convert(head,items):
        envelope={'head':head,'results':{'bindings':items}}
        return parse_select_results(envelope,expected_columns=None if columns is None else tuple(columns)) if encoding==RDF_TERMS_V1 else client._rows_from_response(envelope)
    class ConsumedArray:
        def __init__(self,convert):self.convert=convert;emit.native_arrays+=1
        def append(self,item):
            control.check()
            if conversion_errors:return
            try:rows=self.convert([item])
            except Exception as error:
                conversion_errors.append(f'{type(error).__name__}: {error}');return
            for row in rows:emit(row)
        def finish(self):return []

    def factory(path):
        if path not in (('results','*','data'),('results','bindings')):return None
        if private:emit.native_arrays_spooled+=1
        store=workspace.store();raw_stores.append(store);return store
    def contextual(path,parents):
        # JSON object order is unconstrained. If metadata is not available yet,
        # retain the exact old spool path. Once spooling starts, keep later arrays
        # on that path too so multiple Neo4j results retain their original order.
        if private and not raw_stores:
            if expected=='cypher' and path==('results','*','data'):
                parent=parents.get(('results','*'),{})
                if 'columns' in parent:
                    return ConsumedArray(lambda items:client._rows_from_response({'results':[{'columns':parent['columns'],'data':items}]}))
            if expected=='sparql' and path==('results','bindings'):
                head=parents.get((),{}).get('head')
                if head is not None:
                    try:rdf_convert(head,[])
                    except Exception:return factory(path)
                    return ConsumedArray(lambda items:rdf_convert(head,items))
        return factory(path)
    factory.with_context=contextual
    token=array_factory.set(factory);scope=current_control.set(control)
    try:
        if expected=='cypher':
            response=client._post_statement(artifact.text,artifact.parameters)
            for result in response.get('results',[]):
                for item in result.get('data',[]):
                    control.check()
                    for row in client._rows_from_response({'results':[{'columns':result.get('columns',[]),'data':[item]}]}):emit(row)
        else:
            if encoding not in (None,RDF_TERMS_V1):raise ValueError('Unsupported RDF result encoding')
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
        if conversion_errors:raise ValueError(conversion_errors[0])
        control.check()
    finally:
        current_control.reset(scope);array_factory.reset(token)
        for store in raw_stores:store.close()
