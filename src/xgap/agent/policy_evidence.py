"""Export the selected complete strong policy, not a fabricated execution trace."""
import json

from xgap.agent.intent_certificate import fingerprint


def export_intent_policy(root, family):
    nodes=[];edges=[];plans={};seen=set()
    def visit(node):
        name='state:'+str(node.state_id)
        if name in seen:raise ValueError('Selected policy has repeated state identity')
        seen.add(name)
        nodes.append(dict(id=name,kind='OR',state_id=node.state_id,estimated_cost=node.estimated_cost))
        if node.terminal is not None:
            payload=node.terminal.payload;plan=payload['plan'].to_dict();pin=fingerprint(plan)
            plans[pin]=plan;candidate=family.candidates[payload['candidate_index']]
            terminal=name+':execute'
            nodes.append(dict(id=terminal,kind='EXECUTE',candidate_id=candidate.candidate_id,
                query=json.loads(candidate.query_json),certificate=payload['certificate'],
                physical_plan_id=pin,observation_assumptions=list(payload['observations']),
                evidence_status='planned_until_observed'))
            edges.append(dict(source=name,target=terminal,kind='selected_terminal'))
            return name
        action=node.action
        if action is None or set(label for label,_ in node.children)!={o.outcome_id for o in action.outcomes}:
            raise ValueError('Export requires a continuation for every declared outcome')
        action_name=name+':action'
        nodes.append(dict(id=action_name,kind='AND',action_id=action.action_id,tool_name=action.tool_name,
            arguments=action.arguments,declared_outcomes=len(action.outcomes),estimated_cost=action.estimated_cost))
        edges.append(dict(source=name,target=action_name,kind='selected_action'))
        outcomes={o.outcome_id:o for o in action.outcomes}
        for label,child in node.children:
            child_name=visit(child)
            edges.append(dict(source=action_name,target=child_name,kind='outcome',outcome_id=label,
                observation_assumptions=list(outcomes[label].state.observations)))
        return name
    root_id=visit(root)
    return dict(schema_version='xgap-selected-intent-policy-v1',root=root_id,nodes=nodes,edges=edges,
        physical_plans=plans,family_sha256=family.identity,
        scope='selected complete policy, not all searched alternatives; no counterfactual measured latency or bytes')
