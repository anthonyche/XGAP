from copy import deepcopy
import pytest

from rebind_ch6_profile import validate_revision


def profiles():
    old = dict(profile_id='old', estimator={'kind':'relative'},
               source_schema={'edge':'Transfer'}, sources={'s':'snapshot'}, offline={'facts':'sealed'})
    new = deepcopy(old)
    new.update(profile_id='new', estimator={'kind':'endpoint-degree'})
    new['offline']['endpoint_degree_revision'] = {'source':'sealed degree table'}
    return old, new


def test_allows_only_offline_estimator_revision():
    old, new = profiles()
    assert validate_revision(old, new) == new['offline']['endpoint_degree_revision']
    assert 'endpoint_degree_revision' in new['offline']


@pytest.mark.parametrize('field', ['source_schema', 'sources', 'offline'])
def test_rejects_silent_semantic_or_source_changes(field):
    old, new = profiles()
    new[field]['unexpected'] = 'changed'
    with pytest.raises(ValueError, match='Only a new offline'):
        validate_revision(old, new)


def test_rejects_second_revision_or_missing_provenance():
    old, new = profiles()
    with pytest.raises(ValueError):
        validate_revision(new, new)
    del new['offline']['endpoint_degree_revision']
    with pytest.raises(ValueError):
        validate_revision(old, new)
