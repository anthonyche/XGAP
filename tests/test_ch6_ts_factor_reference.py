"""Real source sweeps retain original NL; constructed N/u placeholders do not."""
import pytest
import freeze_ch6_mixed_support as support


def fixture(monkeypatch):
    original=dict(case_id='original',request='old-request',template_family='family')
    case=dict(case_id='factor',base_case_id='original',request='request',template_family='family',
        oracle='NEVER_READ',reference='NEVER_READ',controlled_state='NEVER_READ')
    docs={'base':dict(cases=[original]),'old-request':dict(question='Original NL'),
          'request':dict(schema_version='xgap-one-shot-evaluation-request-v1',question_id='factor',
                        question='Original NL',exposure='test')}
    monkeypatch.setattr(support,'load',lambda p:docs[p])
    bundle=dict(schema_version='xgap-ch6-deployment-factor-v1',deployment='rdf',input_track='controlled',
                factor='sources',method_outputs_used_for_selection=False,base_bundles=['base'],cases=[case])
    return bundle,docs


def test_reference_validates_public_provenance_without_reading_private_evidence(monkeypatch):
    bundle,_=fixture(monkeypatch)
    support.validate_ts_nl_reference(bundle)


@pytest.mark.parametrize('change',[
    lambda b,d:b.update(schema_version='xgap-ch6-factor-inputs-v1'),
    lambda b,d:b.update(deployment='native'),
    lambda b,d:b.update(method_outputs_used_for_selection=True),
    lambda b,d:b['cases'][0].update(base_case_id='unknown'),
    lambda b,d:d['request'].update(question='placeholder'),
    lambda b,d:d['request'].update(question_id='other'),
    lambda b,d:b['cases'][0].update(template_family='different'),
])
def test_no_silent_controlled_or_changed_nl_admission(monkeypatch,change):
    bundle,docs=fixture(monkeypatch);change(bundle,docs)
    with pytest.raises(ValueError):support.validate_ts_nl_reference(bundle)
