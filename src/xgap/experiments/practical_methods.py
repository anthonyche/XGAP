"""Explicit identities; composed frontends are never labelled bare FedUP/FedX."""

STRONG_METHODS = {'xgap-strong-exact': 'exact', 'xgap-strong-performance': 'performance'}
FIXED_INFORMATION_METHODS = {f'fixed-info-{mode}-{engine}': (mode, engine)
    for mode in ('exact', 'performance') for engine in ('fedup', 'fedx')}
PRACTICAL_METHODS = (*STRONG_METHODS, *FIXED_INFORMATION_METHODS)


def external_engine(method):
    if method in ('fedup', 'fedx'):
        return method
    return FIXED_INFORMATION_METHODS.get(method, (None, None))[1]
