"""Bind every planned plot position to real dispatch cells or explicit absence.

This is a pre-run integrity check, not a plotter and not result imputation.
"""
import json
from copy import deepcopy
from xgap.experiments.ch6_formal_protocol import matrix,load_pin,METHODS


def audit_bindings(release):
    checks=[]
    def check(name,value):checks.append(dict(check=name,passed=bool(value),detail=''))
    def key(row):return (row['figure'],row['method'],json.dumps(row['x_value'],sort_keys=True))
    expected={key(r):r for r in matrix()};seen=set();fixed={};cells={}
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
            load_pin(binding['evidence_pin']);continue
        if status=='offline_measured':
            doc=load_pin(binding['evidence_pin'])
            records=[r for r in doc.get('rows',[]) if r['method']==row['method'] and r['eta']==row['x_value']]
            check('offline_terminal_pool_'+str(k),row['figure']=='F6' and doc.get('success') is True and
                  doc.get('schema_version')=='xgap-ch6-terminal-cost-sensitivity-v1' and len(records)==1)
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
            if row['method']=='TS':continue
            config=load_pin(cell['config']);settings=config['settings'];factor=row['x_factor']
            desired=row['defaults'].get(factor,row['x_value'])
            if factor in ('depth','horizon'):
                check('plot_configuration_'+str(k),settings['limits'][factor]==desired)
            elif factor=='epsilon':check('plot_configuration_'+str(k),settings['epsilon']==str(desired))
            elif factor in ('candidates','unbound_fields'):
                from xgap.experiments.controlled_state import read_state
                public=load_pin(cell['request']);_,_,state=read_state(load_pin(cell['controlled_state']),public['question'])
                measured=state['initial_candidate_count' if factor=='candidates' else 'initial_ambiguity']
                check('plot_actual_input_'+str(k),measured==desired)
            elif factor in ('sources','graph_scale'):
                prepared=load_pin(manifest['prepared']);profile=load_pin(prepared['profile'])
                materialization=load_pin(profile['offline']['materialization'])
                measured=materialization['source_count'] if factor=='sources' else float(materialization['scale'])
                check('plot_actual_materialization_'+str(k),measured==desired)
            elif factor in ('probe_price','clarification_price'):
                from release_ch6_five_method_batch import configuration_for
                base=configuration_for(load_pin(binding['cost_reference']),row['method'])
                expected_config=deepcopy(base)
                if factor=='clarification_price':
                    for name in ('clarification_call','disclosed_field'):
                        expected_config['costs'][name]*=desired
                elif row['method']!='NP':
                    for target in expected_config['settings']['information_targets']:
                        if target['kind']=='probe':target['action_cost']*=desired
                check('plot_price_configuration_'+str(k),config==expected_config)
                if factor=='probe_price':
                    active=any(t['kind']=='probe' for t in settings['information_targets'])
                    check('inactive_probe_axis_declared_'+str(k),active or binding.get('inactive_factor') is True)
    check('all_plot_positions_bound',seen==set(expected))
    return checks
