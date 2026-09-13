"""Classify saved source evidence without treating harness limits as method errors."""
from collections import Counter


def classify_source_failure(observed):
    categories=Counter(observed.get('failure_categories',{}))
    # Read-only compatibility for archived development evidence; no rerun needed.
    if not categories:
        legacy={'Source call budget exceeded':'harness_call_budget',
                'Source response byte budget exceeded':'harness_response_budget',
                'Request byte budget exceeded':'harness_request_budget'}
        for row in observed.get('records',[]):
            if row.get('error') in legacy:categories[legacy[row['error']]]+=1
            elif row.get('http_status',0)>=400:categories['upstream_http_failure']+=1
            elif row.get('status')!='returned':categories['unclassified_source_failure']+=1
    if any(k.startswith('harness_') and k.endswith('_budget') for k in categories):
        status='harness_budget_censored'
    elif any(k.startswith('harness_') for k in categories) or observed.get('persistence_failures'):
        status='harness_observation_failure'
    elif categories:status='upstream_source_failure'
    else:status='observed_source_failure'
    return {'status':status,'categories':dict(categories),
            'native_answer_observed':False,'intrinsic_method_incorrectness_established':False}
