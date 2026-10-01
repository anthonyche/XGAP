"""Independent value examples and consistency laws for binding operators."""

from decimal import Decimal, localcontext
from itertools import permutations

import pytest

from xgap.runtime.binding_operations import aggregate_rows, sort_rows
from xgap.runtime.scalars import numeric, value_key, distinct_rows
from xgap.runtime.row_operations import filter_rows, project_rows
from xgap.runtime import FederatedScheduler as S, RuntimeNode, RuntimeNodeKind as K


XSD='http://www.w3.org/2001/XMLSchema#'
def rdf(value, datatype='decimal'):
    return {'type':'literal','datatype':XSD+datatype,'value':value}


def aggregate(values, op='sum', **options):
    return aggregate_rows({'group_by':[], 'allow_global':True,
        'aggregations':{'result':{'op':op,'field':'v',**options}}}, tuple({'v':v} for v in values))


@pytest.mark.parametrize('values,expected', [
    ([9007199254740993],9007199254740993),
    ([9007199254740993,2],9007199254740995),
    ([2**63-1,1],2**63),
    ([rdf('0.1'),rdf('0.2')],rdf('0.3')),
    ([rdf('10000000000000000000000000000.01'),rdf('0.09')],rdf('10000000000000000000000000000.1')),
    ([rdf('1.50'),2],rdf('3.5')),
    ([rdf('1.5'),2.5],4.0), ([3.1,4.2],7.3),
    ([None,2,None],2), ([],0), ([None],0),
])
def test_sum_preserves_declared_numeric_domain(values,expected):
    with localcontext() as ctx:
        ctx.prec=5
        actual=aggregate(values)[0]['result']
    assert actual == expected
    assert type(actual) is type(expected)


@pytest.mark.parametrize('value', ['12',True,False,{},rdf('yes','string'),
    float('nan'),float('inf'),rdf('NaN','double'),rdf('1e9999','double'),
    rdf('1.1','integer'),rdf('1e2','decimal'),rdf('256','unsignedByte')])
def test_nonnumeric_malformed_and_nonfinite_sums_fail(value):
    with pytest.raises(ValueError):
        aggregate([value])


def test_count_star_field_and_distinct_have_different_denominators():
    values=[1,1.0,rdf('1.00'),True,'1',None]
    rows=tuple({'v':v} for v in values)
    specs={'all':{'op':'count'},'nonnull':{'op':'count','field':'v'},
        'values':{'op':'count','field':'v','distinct':True},'rows':{'op':'count','distinct':True}}
    assert aggregate_rows({'group_by':[],'allow_global':True,'aggregations':specs},rows)==(
        {'all':6,'nonnull':5,'values':3,'rows':4},)
    assert aggregate([1,1.0,2],distinct=True)==({'result':3.0},)
    assert aggregate([rdf('1.00'),1,2],distinct=True)==({'result':rdf('3')},)


def test_numeric_grouping_is_order_independent_and_separates_bool_and_string():
    params={'group_by':['v'],'aggregations':{'n':{'op':'count'}}}
    rows=({'v':1},{'v':1.0},{'v':rdf('1.00')},{'v':True},{'v':'1'},{'v':None})
    expected=({'v':None,'n':1},{'v':1,'n':3},{'v':'1','n':1},{'v':True,'n':1})
    for perm in (rows,tuple(reversed(rows)),rows[2:]+rows[:2]):
        assert aggregate_rows(params,perm)==expected
    assert aggregate_rows(params,())==()


def test_min_max_ignore_nulls_and_share_the_explicit_scalar_order():
    values=[None,True,'2',1.5,1,rdf('1.20')]
    assert aggregate(values,'min')==({'result':1},)
    assert aggregate(values,'max')==({'result':True},)
    assert aggregate([None],'min')==({'result':None},)
    assert aggregate([],'max')==({'result':None},)


@pytest.mark.parametrize('direction,nulls,indices', [
    ('asc','last',[4,5,3,2,1,0]),('desc','last',[1,2,3,5,4,0]),
    ('desc','first',[0,1,2,3,5,4]),('asc','first',[0,4,5,3,2,1]),
])
def test_nullable_mixed_scalar_order_is_explicit(direction,nulls,indices):
    values=[None,True,'2',1.5,1,rdf('1.20')]
    rows=tuple({'id':i,'v':v} for i,v in enumerate(values))
    params={'order_by':[{'field':'v','direction':direction,'nulls':nulls}],'limit':10}
    assert sort_rows(params,rows)==tuple(rows[i] for i in indices)
    assert sort_rows(params,tuple(reversed(rows)))==tuple(rows[i] for i in indices)


def test_even_single_row_order_validates_field_type_and_finiteness():
    p={'order_by':[{'field':'v'}],'limit':1}
    for row in ({'other':1},{'v':float('nan')},{'v':[]},{'v':rdf('NaN','double')}):
        with pytest.raises(ValueError):sort_rows(p,(row,))
    with pytest.raises(ValueError):sort_rows({**p,'order_by':[{'field':'v','nulls':'unspecified'}]},())


def test_filter_group_join_semijoin_and_distinct_share_value_equality():
    rows=({'v':1},{'v':1.0},{'v':rdf('1.00')},{'v':True},{'v':'1'},{'v':None})
    selected=filter_rows(rows,{'op':'eq','field':'v','value':1})
    assert selected==rows[:3]
    assert len(distinct_rows(rows))==4
    join=RuntimeNode('join',K.COORDINATOR_JOIN,('a','b'),{'left_on':'v','right_on':'key'})
    joined=S._join(join,rows,({'key':rdf('1.000')}, {'key':None}))
    assert len(joined)==1 and value_key(joined[0]['v'])==value_key(1)
    semi=RuntimeNode('semi',K.COORDINATOR_SEMI_JOIN,('a','b'),{'left_on':'v','right_on':'key'})
    assert len(S._semi_join(semi,rows,({'key':1.0},{'key':None})))==1
    assert filter_rows(({'v':None},),{'op':'not','arg':{'op':'eq','field':'v','value':1}})==({'v':None},)


def test_row_fields_named_type_value_are_not_misread_as_one_rdf_value():
    rows=({'type':'literal','value':'1'},{'type':'typed-literal','value':'1'})
    assert len(distinct_rows(rows))==2
    assert aggregate_rows({'group_by':[],'allow_global':True,
        'aggregations':{'n':{'op':'count','distinct':True}}},rows)==({'n':2},)


def test_projection_keeps_sorted_order_and_deduplicates_equal_numbers():
    rows=({'v':2,'id':'a'},{'v':1.0,'id':'b'},{'v':1,'id':'c'})
    assert project_rows(rows,{'v':{'kind':'field','field':'v'}})==({'v':2},{'v':1.0})


def test_absent_fields_are_schema_errors_not_null_values():
    with pytest.raises(ValueError,match='missing'):aggregate_rows(
        {'group_by':[],'allow_global':True,'aggregations':{'n':{'op':'count','field':'v'}}},({'x':1},))
    with pytest.raises(ValueError,match='missing'):filter_rows(({},),{'op':'eq','field':'v','value':1})
