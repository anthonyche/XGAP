"""Eight public structure strata through proposal and paid scope, without execution."""
from collections import Counter
import json
import os
from pathlib import Path
import time

from xgap.agent.intent_certificate import fingerprint
from xgap.agent.intent_execution import snapshot_identity
from xgap.agent.one_shot_policy import OneShotPolicy
from xgap.agent.scope_authority import QueryIntentAuthority
from xgap.api import public_scope_request
from xgap.catalog.bundle import FrozenResolutionBundle
from xgap.catalog.build import freeze_resolution_bundle
from xgap.experiments.ch6_core_profile import source_catalog
from xgap.experiments.ch6_fact_index import CORES, write
from xgap.experiments.ch6_heldout import STRUCTURES, QUESTION_VERSION, public_edge_role_text
from xgap.experiments.compact_constraints_profile import (
    publish_compact_constraints_profile, load_public_compact_constraints)
from xgap.experiments.compact_equivalence_profile import adapt_compact_provider
from xgap.experiments.evidence_store import write_json_evidence
from xgap.experiments.one_shot_profile import _provider, _backend, read_pinned
from xgap.experiments.one_shot_records import write_once
from xgap.llm.public_typed_compact import adapt_public_typed_compact_provider
from xgap.semantic.intent_scope import ScopePolicy, construct_scope, upgrade_edge_type_domains
from xgap.semantic.interpretation import InterpretationRequest
from xgap.semantic.interpretation_candidates import interpret_candidate_question
from xgap.runtime.semantic_planning import LogicalSource
from xgap.tools.contracts import ToolStatus


SCHEMA = 'xgap-ch6-eight-structure-entry-gate-v1'
PROVIDER = 'frozen_compact_model_public_contract_v1'
BUDGET = dict(model_calls=8, model_calls_per_case=1, max_output_tokens_per_call=4096,
              max_output_tokens_total=32768, user_calls_per_case=1, total_wall_seconds=900)
SELECTION = ('Sorted public templates; select the available dataset with the fewest '
             'already selected cases, then dataset ID and case_id lexicographically')


def locate(pin, mirrors=()):
    original = Path(pin['path']); candidates = []
    for old, new in sorted(mirrors, key=lambda pair: -len(str(pair[0]))):
        if original.is_relative_to(Path(old)):
            candidates.append(Path(new)/original.relative_to(Path(old)))
    for path in candidates or [original]:
        if path.is_file():
            read_pinned(path, pin['sha256'])
            return path
    raise FileNotFoundError('Pinned entry artifact missing from supplied mirrors')


def load(pin, mirrors=()):
    return json.loads(read_pinned(locate(pin, mirrors), pin['sha256']))


def relative_pin(pin, root):
    return {**pin, 'path': str(Path(pin['path']).relative_to(root))}


def select_public_structures(selection):
    """Do not inspect an outcome, reference, private intent, or query AST."""
    by_template = {}
    for cohort in selection['cohorts']:
        for case in cohort['cases']:
            if case['template'] not in STRUCTURES:
                raise ValueError('Entry gate only uses the eight declared public test structures')
            by_template.setdefault(case['template'], []).append((cohort, case))
    if set(by_template) != set(STRUCTURES):
        raise ValueError('Every public test structure must have one available case')
    counts = Counter(); selected = []
    for name in sorted(by_template):
        cohort, case = min(by_template[name], key=lambda pair:
            (counts[pair[0]['dataset']], pair[0]['dataset'], pair[1]['case_id']))
        selected.append((cohort, case)); counts[cohort['dataset']] += 1
    if set(counts) != {'D1', 'D2', 'D3'}:
        raise ValueError('The public deterministic selection must cover all three datasets')
    return selected


def prepare(*, release_path, release_sha256, output, pin_mirrors=(), proof_mirrors=()):
    release = json.loads(read_pinned(release_path, release_sha256))
    selection = load(release['selection'], pin_mirrors)
    selected = select_public_structures(selection)
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    profiles = {}; proofs = {}; cases = []
    for cohort, case in selected:
        domain, deployment = cohort['dataset'], cohort['deployment']
        profile_key = domain+'-'+deployment
        if profile_key not in profiles:
            parent = load(cohort['profile'], pin_mirrors)
            parent_path = locate(cohort['profile'], pin_mirrors)
            derived = publish_compact_constraints_profile(parent_path=parent_path,
                parent_sha256=cohort['profile']['sha256'], output=root/'publication'/profile_key,
                pin_mirrors=proof_mirrors)
            doc = load(derived); contract = load(doc['offline']['compact_public_constraints'])
            folder = root/'profiles'/profile_key; folder.mkdir(parents=True)
            cpin = write_once(folder/'public-constraints.json', contract)
            doc['offline']['compact_public_constraints'] = relative_pin(cpin, folder)
            # Prompt bytes and source versions stay unchanged; only private local
            # package paths are made portable. Public typing is an explicit adapter.
            for mode, value in doc['modes'].items():
                prompt = value['provider']['prompt']; data = read_pinned(locate(prompt, pin_mirrors), prompt['sha256'])
                target = folder/('prompt-'+mode+'.txt'); target.write_bytes(data)
                value['provider']['prompt'] = dict(path=target.name, sha256=prompt['sha256'])
            profile_pin = write_once(folder/'profile.json', doc)
            materialization = load(parent['offline']['materialization'], proof_mirrors)
            for pin in [parent['offline']['materialization'], materialization['index_receipt'],
                        materialization['source_schema'], materialization['mapping']]:
                if pin['path'] in proofs:
                    continue
                value = read_pinned(locate(pin, proof_mirrors), pin['sha256'])
                folder_proof = root/'public-proofs'; folder_proof.mkdir(exist_ok=True)
                path = folder_proof/(pin['sha256']+'.json'); path.write_bytes(value)
                proofs[pin['path']] = dict(path=str(path.relative_to(root)), sha256=pin['sha256'], bytes=len(value))
            # Reuse the original source-only constructor, and require precisely
            # the old bundle hash. No graph, outcome or authority query is read.
            catalog, bindings = source_catalog(materialization, load(materialization['mapping'], proof_mirrors))
            write(folder/'catalog-input.json',catalog);write(folder/'bindings-input.json',bindings)
            freeze_resolution_bundle(catalog=folder/'catalog-input.json',bindings=folder/'bindings-input.json',
                                     output=folder/'catalog')
            bundle = FrozenResolutionBundle.load(folder/'catalog', expected_bundle_hash=parent['catalog']['bundle_hash'])
            policy = OneShotPolicy(**parent['modes']['performance']['policy'])
            context = dict(source_schema=parent['source_schema'], one_shot_profile=policy.to_dict(),
                runtime=dict(resolution_bundle=bundle.identity, sources={key:dict(version=value['version'], replicas=value['replicas'])
                    for key,value in parent['sources'].items()}))
            profiles[profile_key] = dict(profile=relative_pin(profile_pin, root), parent=cohort['profile'], context=context)
        scope_raw = load(case['scope'], pin_mirrors); scope = ScopePolicy.from_dict(scope_raw)
        request = load(case['request'], pin_mirrors)
        original_question = request['question']
        request = {**request, 'question': original_question+' '+public_edge_role_text(CORES[domain], case['template'], scope),
            'question_id': case['case_id']+'-entry-roles-v2', 'exposure': 'entry_acceptance_not_paper_sample'}
        # The offline packager changes the question binding only. The selected
        # query/nonce are copied untouched and never used to construct public text.
        private = load(case['oracle'], pin_mirrors)
        if private['question_sha256'] != fingerprint(original_question):
            raise ValueError('Original private/public question pin differs')
        private = {**private, 'question_sha256': fingerprint(request['question'])}
        folder = root/'cases'/case['case_id']; folder.mkdir(parents=True)
        request_pin = write_once(folder/'request.json', request)
        scope_pin = write_once(folder/'scope.json', scope_raw)
        oracle_pin = write_once(folder/'private-user.json', private)
        os.chmod(folder/'private-user.json', 0o600)
        context = {**profiles[profile_key]['context'], 'query_id': request['question_id']}
        for key in ('requested_output', 'require_complete_results'):
            if key in request:
                context[key] = request[key]
        cases.append(dict(case_id=case['case_id'], dataset=domain, deployment=deployment,
            template=case['template'], stratum=case['stratum'], workload=case['workload'],
            original_request=case['request'], original_oracle=case['oracle'], original_scope=case['scope'],
            original_query_and_nonce_unchanged=True, profile_key=profile_key,
            request=relative_pin(request_pin,root), scope=relative_pin(scope_pin,root), oracle=relative_pin(oracle_pin,root),
            request_context=context))
    manifest = dict(schema_version=SCHEMA, provider=PROVIDER, source_release_sha256=release_sha256,
        source_selection=release['selection'], question_version=QUESTION_VERSION,
        purpose='Eight-structure entry acceptance, not a paper sample or method comparison',
        selection=SELECTION, selection_counts={key:dict(Counter(c[key] for c in cases))
            for key in ('dataset','deployment','stratum','workload')}, budget=BUDGET,
        automatic_retries=0, profiles=profiles, public_proof_mirrors=proofs, cases=cases,
        method_results_read=0, reference_answers_read=0, original_files_modified=0,
        model_calls=0, backend_calls=0, submitted_jobs=0,
        not_tested=['planner','probe selection','answer execution','answer quality','end-to-end method performance'])
    pin = write_once(root/'manifest.json', manifest)
    checks = preflight(pin['path'], pin['sha256'])
    write_once(root/'preflight.json', checks)
    return pin


def local_pin(root, pin):
    path = root/pin['path']
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Entry package pin escapes its root')
    return dict(pin, path=str(path))


def entry_inputs(root, manifest, cell):
    item = manifest['profiles'][cell['profile_key']]
    pin = local_pin(root, item['profile']); doc = load(pin); folder = Path(pin['path']).parent
    mirrors = [(old, str(root/value['path'])) for old,value in manifest['public_proof_mirrors'].items()]
    for value in manifest['public_proof_mirrors'].values():
        load(local_pin(root,value))
    constraints = load_public_compact_constraints(doc, profile_root=folder, pin_mirrors=mirrors)
    policy = OneShotPolicy(**doc['modes']['performance']['policy'])
    provider = _provider(folder, doc['modes']['performance']['provider'], policy)
    backends = {key:_backend(value['semantic'],key) for key,value in doc['backends'].items()}
    sources = {key:LogicalSource(key,value['version'],tuple(value['replicas'])) for key,value in doc['sources'].items()}
    provider, adapter = adapt_compact_provider(provider, doc['source_schema'], backends)
    provider = adapt_public_typed_compact_provider(provider)
    if (provider.config.candidate_cap != 1 or provider.config.max_tokens != 4096
            or provider.config.max_repair_calls != 0):
        raise ValueError('Entry model bounds differ from the frozen one-call contract')
    raw = load(local_pin(root,cell['request']))
    scope = upgrade_edge_type_domains(ScopePolicy.from_dict(load(local_pin(root,cell['scope']))))
    request = InterpretationRequest(raw['question'], cell['request_context'], tuple(raw.get('required_constraints',())))
    if request.context['source_schema'] != doc['source_schema']:
        raise ValueError('Entry request source schema differs from its proof')
    request = public_scope_request(request, scope)
    return request, provider, scope, constraints, adapter, snapshot_identity(sources,backends,doc['source_schema'])


def preflight(manifest_path, manifest_sha256):
    root = Path(manifest_path).resolve().parent
    manifest = json.loads(read_pinned(manifest_path,manifest_sha256))
    if (manifest['schema_version'] != SCHEMA or manifest['provider'] != PROVIDER
            or len(manifest['cases']) != 8 or len({c['template'] for c in manifest['cases']}) != 8
            or manifest['automatic_retries'] != 0 or manifest['budget'] != BUDGET
            or set(c['template'] for c in manifest['cases']) != set(STRUCTURES)
            or {c['dataset'] for c in manifest['cases']} != {'D1','D2','D3'}):
        raise ValueError('Entry gate must contain exactly eight bounded public structures')
    checks=[]
    for cell in manifest['cases']:
        request, provider, _, constraints, _, _ = entry_inputs(root,manifest,cell)
        check = provider.token_guard.check(provider.build_request_payload(request),call_kind='generation')
        if not check['passed']:
            raise ValueError('Entry request exceeds the frozen byte/output budget')
        checks.append(dict(case_id=cell['case_id'], request_budget=check, public_constraints_sha256=constraints.identity))
    return dict(success=True, cases=checks, model_calls=0, backend_calls=0, private_intent_reads=0)


def run(*, manifest_path, manifest_sha256, output):
    preflight(manifest_path,manifest_sha256)
    root = Path(manifest_path).resolve().parent
    manifest = json.loads(read_pinned(manifest_path,manifest_sha256))
    out = Path(output).resolve(); out.mkdir(parents=True,exist_ok=False)
    started=time.monotonic(); calls=0; input_tokens=0; output_tokens=0; records=[]
    unknown_calls=False; unknown_tokens=False
    write_once(out/'intent.json',dict(manifest_sha256=manifest_sha256,budget=manifest['budget'], provider=PROVIDER))
    for cell in manifest['cases']:
        if time.monotonic()-started >= manifest['budget']['total_wall_seconds'] or calls >= 8:
            break
        request, provider, scope, constraints, adapter, snapshot = entry_inputs(root,manifest,cell)
        if not os.environ.get(provider.config.api_key_env):
            raise ValueError('Fresh model credential required before the entry gate')
        case_out=out/cell['case_id'];case_out.mkdir()
        interpreted=interpret_candidate_question(request,provider,candidate_cap=1)
        if interpreted['external_call_count_complete']:
            calls+=interpreted['external_calls']
        else:
            unknown_calls=True
        if interpreted['token_usage_complete']:
            input_tokens+=interpreted['input_tokens'];output_tokens+=interpreted['output_tokens']
        else:
            unknown_tokens=True
        row=dict(case_id=cell['case_id'],dataset=cell['dataset'],template=cell['template'],stratum=cell['stratum'],
            workload=cell['workload'],deployment=cell['deployment'],status='proposal_failed',
            model_calls=interpreted['external_calls'] if interpreted['external_call_count_complete'] else None,
            input_tokens=interpreted['input_tokens'] if interpreted['token_usage_complete'] else None,
            output_tokens=interpreted['output_tokens'] if interpreted['token_usage_complete'] else None,
            interpretation=write_json_evidence(case_out/'interpretation.json.gz',interpreted),
            provider_adapter=adapter, public_constraints_sha256=constraints.identity,
            user_calls=0, scope_covered=False, backend_calls=0, planner_calls=0, answer_executions=0,
            unknown_model_calls=not interpreted['external_call_count_complete'],
            unknown_tokens=not interpreted['token_usage_complete'])
        if interpreted['success']:
            try:
                provenance=interpreted['provenance'];raw=provenance.get('canonical_compact_response',provenance['raw_compact_response'])
                admitted={c['candidate_id'] for c in interpreted['candidates'] if c['status']=='admitted'}
                draft=construct_scope([c['query'] for c in raw['candidates'] if c['candidate_id'] in admitted],
                    scope,snapshot)
                oracle=local_pin(root,cell['oracle'])
                authority=QueryIntentAuthority(Path(oracle['path']),oracle['sha256'],constraints=constraints)
                confirmation=authority.confirm_scope(request.question,draft)
                row.update(user_calls=1,scope_confirmation=confirmation.to_dict(),
                    scope_covered=bool((confirmation.value or {}).get('covered')))
                row['status']=('scope_authority_failed' if confirmation.status is not ToolStatus.SUCCESS
                    else 'entry_admitted' if row['scope_covered'] else 'scope_not_covered')
            except (ValueError,KeyError,TypeError) as error:
                row.update(status='scope_construction_failed',error_type=type(error).__name__,error=str(error))
        row['receipt']=write_once(case_out/'receipt.json',dict(row))
        records.append(row)
        print(json.dumps({k:row[k] for k in ('case_id','status','model_calls','user_calls')}),flush=True)
        if unknown_calls or unknown_tokens:
            break
    result=dict(schema_version=SCHEMA,purpose=manifest['purpose'],attempted=len(records),
        counts=dict(Counter(row['status'] for row in records)),completed_all=len(records)==8,
        remaining=[c['case_id'] for c in manifest['cases'][len(records):]],
        usage=dict(model_calls=calls if not unknown_calls else None,
                   input_tokens=input_tokens if not unknown_tokens else None,
                   output_tokens=output_tokens if not unknown_tokens else None,
                   known_model_calls=calls,known_input_tokens=input_tokens,known_output_tokens=output_tokens,
                   unknown_model_calls=unknown_calls,unknown_tokens=unknown_tokens,
                   user_calls=sum(row['user_calls'] for row in records)),
        records=records, backend_calls=0,planner_calls=0,answer_executions=0,method_results_created=0,
        not_tested=manifest['not_tested'],elapsed_seconds=time.monotonic()-started)
    write_once(out/'receipt.json',result)
    return result
