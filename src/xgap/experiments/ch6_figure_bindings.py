"""Bind every planned plot position to real dispatch cells or explicit absence.

This is a pre-run integrity check, not a plotter and not result imputation.
"""
import json
import math
from copy import deepcopy
from xgap.experiments.ch6_formal_protocol import matrix,load_pin,METHODS


def audit_bindings(release, *, figures=None):
    checks=[]
    def check(name,value):checks.append(dict(check=name,passed=bool(value),detail=''))
    def key(row):return (row['figure'],row['method'],json.dumps(row['x_value'],sort_keys=True))
    rows = matrix()
    if figures is not None:
        if not figures or set(figures)-{r['figure'] for r in rows}: raise ValueError('Unknown figure audit scope')
        rows = [r for r in rows if r['figure'] in figures]
    expected={key(r):r for r in rows};seen=set();fixed={};cells={}
    for unit in release['units']:
        manifest=load_pin(unit['manifest'])
        for cell in manifest['cells']:cells[(unit['unit_id'],cell['cell_id'])]=(cell,manifest)
    for binding in release.get('figure_bindings',[]):
        k=key(binding);check('unique_plot_position_'+str(k),k in expected and k not in seen);seen.add(k)
        if k not in expected:continue
        row=expected[k];status=binding['status'];refs=binding.get('cells',[])
        check('plot_status_'+str(k),status in ('scheduled','fixed_reference','offline_measured',
            'unsupported_deployment','unsupported_interface','unscorable_metric'))
        if status in ('unsupported_deployment','unsupported_interface','unscorable_metric'):
            check('honest_plot_absence_'+str(k),bool(binding.get('reason')) and binding.get('value') is None and not refs)
            doc=load_pin(binding['evidence_pin'])
            if row['figure']=='F6':
                records=[r for r in doc.get('rows',[]) if r['method']==row['method'] and r['eta']==row['x_value']]
                check('offline_absence_matches_record_'+str(k),doc.get('success') is True and
                    doc.get('schema_version')=='xgap-ch6-terminal-cost-sensitivity-v1' and len(records)==1
                    and records[0].get('status')==status and records[0].get('value') is None
                    and bool(records[0].get('reason')))
            continue
        if status=='offline_measured':
            doc=load_pin(binding['evidence_pin'])
            records=[r for r in doc.get('rows',[]) if r['method']==row['method'] and r['eta']==row['x_value']]
            check('offline_terminal_pool_'+str(k),row['figure']=='F6' and doc.get('success') is True and
                  doc.get('schema_version')=='xgap-ch6-terminal-cost-sensitivity-v1' and len(records)==1)
            record=records[0] if len(records)==1 else {}
            value=record.get('value')
            check('offline_measured_record_'+str(k),record.get('status')=='measured'
                and type(value) in (int,float) and math.isfinite(value) and value>=0
                and ('value' not in binding or binding['value']==value) and not refs)
            audit=load_pin(doc['cost_audit']) if doc.get('cost_audit') else {}
            check('offline_raw_cost_audit_'+str(k),audit.get('schema_version')=='xgap-ch6-cost-measurement-audit-v1'
                and audit.get('success') is True and audit.get('pool',{}).get('sha256')==doc.get('pool',{}).get('sha256')
                and audit.get('frozen_costs',{}).get('sha256')==doc.get('measurements',{}).get('sha256'))
            source_units=[u for u in release['units'] if u['unit_id']==binding.get('source_unit_id')]
            check('offline_source_unit_'+str(k),len(source_units)==1)
            if len(source_units)==1:
                source=load_pin(source_units[0]['manifest']);design=source['design']
                check('offline_same_serving_contract_'+str(k),audit.get('prepared',{}).get('sha256')==source['prepared']['sha256']
                    and audit.get('source_storage')==design.get('source_storage','evidence')
                    and audit.get('source_rss_bytes')==design['source_rss_bytes']
                    and audit.get('source_runtime')==design.get('source_runtime',{}).get('contract')
                    and audit.get('source_budget')==design['source_budget'])
            continue
        check('plot_has_real_cells_'+str(k),bool(refs))
        if row['configuration_kind']=='fixed_reference':
            identity=tuple(sorted((r['unit_id'],r['cell_id']) for r in refs))
            previous=fixed.setdefault(row['reference_key'],identity)
            check('one_fixed_observation_set_'+str(k),status=='fixed_reference' and previous==identity)
        for ref in refs:
            target=(ref['unit_id'],ref['cell_id']);check('plot_cell_exists_'+str(k),target in cells)
            if target not in cells:continue
            cell,manifest=cells[target]
            check('plot_method_'+str(k),cell['method']==METHODS[row['method']])
            # TS fixed-NL references retain their distinct timing boundary.
            controlled='controlled_state' in cell
            check('plot_input_track_'+str(k),controlled==(row['input_track']=='controlled' and row['method']!='TS'))
            # Deployment axes apply to TS too: its NL entry must use the actual
            # factor snapshot, not a fixed two-source observation relabelled 4/8.
            factor=row['x_factor']
            desired=row['defaults'].get(factor,row['x_value'])
            if factor in ('sources','graph_scale'):
                prepared=load_pin(manifest['prepared']);profile=load_pin(prepared['profile'])
                materialization=load_pin(profile['offline']['materialization'])
                measured=materialization['source_count'] if factor=='sources' else float(materialization['scale'])
                check('plot_actual_materialization_'+str(k),measured==desired)
            if row['method']=='TS':continue
            config=load_pin(cell['config']);settings=config['settings']
            if factor in ('depth','horizon'):
                check('plot_configuration_'+str(k),settings['limits'][factor]==desired)
            elif factor=='epsilon':check('plot_configuration_'+str(k),settings['epsilon']==str(desired))
            elif factor in ('candidates','unbound_fields'):
                from xgap.experiments.controlled_state import read_state
                public=load_pin(cell['request']);_,_,state=read_state(load_pin(cell['controlled_state']),public['question'])
                measured=state['initial_candidate_count' if factor=='candidates' else 'initial_ambiguity']
                check('plot_actual_input_'+str(k),measured==desired)
            elif factor in ('probe_price','clarification_price'):
                from release_ch6_five_method_batch import configuration_for
                # Different frozen families have different relaxable slots. A
                # single figure-wide config cannot stand in for every case.
                if 'cost_references' in binding:
                    matches=[r for r in binding['cost_references'] if
                        (r['unit_id'],r['cell_id'])==target]
                    check('unique_case_cost_reference_'+str(k)+str(target),len(matches)==1)
                    if len(matches)!=1:continue
                    cost_reference=matches[0]['configuration']
                else:cost_reference=binding['cost_reference']
                base=configuration_for(load_pin(cost_reference),row['method'])
                check('unit_price_reference_'+str(k),base['costs']['clarification_call']==1
                    and base['costs']['disclosed_field']==.25)
                expected_config=deepcopy(base)
                if factor=='clarification_price':
                    for name in ('clarification_call','disclosed_field'):
                        expected_config['costs'][name]*=desired
                elif row['method']!='NP':
                    for target in expected_config['settings']['information_targets']:
                        if target['kind']=='probe':target['action_cost']*=desired
                    if expected_config['settings'].get('live_probe_policy') is not None:
                        expected_config['settings']['live_probe_policy']['action_cost']*=desired
                check('plot_price_configuration_'+str(k),config==expected_config)
                if factor=='probe_price':
                    live = base['settings'].get('live_probe_policy')
                    if live is not None:
                        from xgap.agent.live_probe import policy_from_dict
                        policy_from_dict(live)
                        check('live_probe_expectation_'+str(k), settings['limits']['aggregation']=='expectation')
                        reference = matches[0] if 'cost_references' in binding and len(matches)==1 else {}
                        identity = reference.get('base_cell') or {}
                        origin = cells.get((identity.get('unit_id'),identity.get('cell_id')))
                        check('live_probe_input_reference_'+str(k), origin is not None)
                        if origin is not None:
                            original_cell, original_manifest = origin
                            check('live_probe_same_inputs_'+str(k),
                                {n:v for n,v in cell.items() if n!='config'}=={n:v for n,v in original_cell.items() if n!='config'}
                                and {n:v for n,v in manifest.items() if n!='cells'}=={n:v for n,v in original_manifest.items() if n!='cells'})
                            check('live_probe_base_config_'+str(k), original_cell['config']==cost_reference)
                    active=bool(live) or any(t['kind']=='probe' for t in settings['information_targets'])
                    check('inactive_probe_axis_declared_'+str(k),active or binding.get('inactive_factor') is True)
    check('all_plot_positions_bound',seen==set(expected))
    return checks
