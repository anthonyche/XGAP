"""Public controlled-state publication, never an NL frontend or online oracle."""
from dataclasses import replace
import json

from xgap.agent.intent_certificate import IntentFamily, canonical, fingerprint

SCHEMA='xgap-controlled-intent-state-v1'


def publish_state(question,family,true_query,*,clue_names=(),semantic_choices):
    """Offline authored application clues; no trace/answer/cost-based selection.

    Private intent is used by the dataset publisher, never by the online reader.
    Full family, slots and normalization remain identical across clue variants.
    """
    matches=[i for i,c in enumerate(family.candidates) if c.query_json==canonical(true_query)]
    if len(matches)!=1:raise ValueError('Private intent is outside the published full family')
    covered=replace(family,coverage_basis='controlled_dataset_publisher:'+fingerprint(
        [fingerprint(question),[c.query_json for c in family.candidates],family.source_snapshot]))
    names=[s.name for s in family.slots]
    if len(set(clue_names))!=len(clue_names) or any(n not in names for n in clue_names):
        raise ValueError('Unknown or duplicate initial clue')
    clues={n:json.loads(family.values[matches[0]][names.index(n)]) for n in clue_names}
    document=dict(schema_version=SCHEMA,question_sha256=fingerprint(question),family=covered.to_dict(),
        initial_clues=clues,semantic_choices=semantic_choices,
        initial_evidence_origin='authored request/application knowledge, not observations from an evaluated run')
    read_state(document,question)
    return document


def read_state(document,question):
    if (set(document)!={'schema_version','question_sha256','family','initial_clues','semantic_choices','initial_evidence_origin'}
            or document['schema_version']!=SCHEMA or document['question_sha256']!=fingerprint(question)
            or document['initial_evidence_origin']!='authored request/application knowledge, not observations from an evaluated run'):
        raise ValueError('Controlled state identity or initial-evidence origin differs')
    family=IntentFamily.from_dict(document['family'])
    if not family.coverage_basis:raise ValueError('Missing controlled scope authority')
    names=[s.name for s in family.slots];clues=document['initial_clues'];choices=document['semantic_choices']
    if not isinstance(clues,dict) or set(clues)-set(names):raise ValueError('Unknown initial clue')
    if not isinstance(choices,list) or len(choices)>32:raise ValueError('Bounded named semantic choices required')
    used=[];choice_names=[]
    for choice in choices:
        if (set(choice)!={'name','type','slots'} or not choice['name'] or not choice['type'] or
                not isinstance(choice['slots'],list) or not choice['slots']):raise ValueError('Invalid semantic choice')
        used.extend(choice['slots']);choice_names.append(choice['name'])
    if sorted(used)!=sorted(names) or len(set(choice_names))!=len(choice_names):
        raise ValueError('Every coordinate belongs to exactly one declared semantic choice')
    observations=tuple(sorted((names.index(n),canonical(v)) for n,v in clues.items()))
    remaining=family.consistent(observations)
    ambiguous=[choice['name'] for choice in choices if len({tuple(family.values[i][names.index(n)]
        for n in choice['slots']) for i in remaining})>1]
    return family,observations,dict(initial_candidate_count=len(remaining),full_family_count=len(family.candidates),
        initial_ambiguity=len(ambiguous),ambiguous_choices=ambiguous,semantic_choices=choices,
        loss_denominator=sum(s.weight for s in family.slots if not s.hard) or 1)
