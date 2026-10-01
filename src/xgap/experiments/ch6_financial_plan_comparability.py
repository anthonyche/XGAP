"""Conservative execution-plan identities for the financial worker scan.

These pins supplement, never replace, the original selected-DAG audit identity.
Worker count is the intervention. Construction IDs may therefore change without
changing execution. All other fields, including input dependencies and ordered
node parameters, remain in the comparison rather than being assumed equivalent.
"""
from copy import deepcopy
import hashlib
import json


SCHEMA = 'xgap-financial-execution-comparability-v1'
EXCLUSIONS = (
    'plan_id',
    'max_parallelism',
    'metadata.financial_composition.selected_branch_plans',
)


def _sha(value):
    body = json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')
    return hashlib.sha256(body).hexdigest()


def plan_fingerprints(plan):
    """Return an exact audit pin and a conservative worker-independent pin.

    The branch identities excluded below are hashes of construction records;
    actual composed branch nodes, source snapshots, bindings, schemas and proof
    remain. Unknown/new metadata is retained conservatively. In particular,
    different binding-key producers are never normalized to one fingerprint.
    """
    raw = plan.to_dict() if hasattr(plan, 'to_dict') else plan
    if not isinstance(raw, dict) or not isinstance(raw.get('nodes'), list) or not raw.get('roots'):
        raise ValueError('An actual executable plan is required for comparison')
    audit = _sha(raw)
    execution = deepcopy(raw)
    execution.pop('plan_id', None)
    execution.pop('max_parallelism', None)
    metadata = execution.get('metadata')
    if isinstance(metadata, dict):
        composition = metadata.get('financial_composition')
        if isinstance(composition, dict):
            composition.pop('selected_branch_plans', None)
    return dict(plan_audit_sha256=audit, execution_plan_sha256=_sha(execution),
                execution_plan_fingerprint_schema=SCHEMA)
