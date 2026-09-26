"""Publish an opt-in equivalence compiler profile; no prompt or data tuning."""
import json
from dataclasses import replace
from pathlib import Path

from xgap.experiments.one_shot_profile import FrozenOneShotProfile
from xgap.experiments.one_shot_records import write_once
from xgap.llm.compact_interpretation import WIRE_PROFILE_V2, WIRE_PROFILE_EQUIVALENCE
from xgap.semantic.compact_equivalence import PROFILE, validate_identity_schema


PROVIDER = 'frozen_compact_model_equivalence_v1'


def adapt_compact_provider(provider, source_schema, backends):
    """Adapt an already pinned/rebound provider while retaining its transport.

The returned receipt explicitly distinguishes the adapter from the original
profile. The request prompt/schema and all network/token settings stay pinned.
"""
    from xgap.llm.compact_interpretation import OpenAICompatibleCompactInterpretationProvider
    if (not isinstance(provider, OpenAICompatibleCompactInterpretationProvider)
            or provider.config.language_version != 'v2'
            or provider.config.normalization_profile is not None):
        raise ValueError('Equivalence adapter requires the original compact v2 provider')
    validate_identity_schema(source_schema, backends)
    config = replace(provider.config, normalization_profile=PROFILE,
                     provider_id=provider.config.provider_id + ':' + PROFILE)
    adapted = replace(provider, config=config)
    receipt = dict(profile=PROFILE, provider=PROVIDER,
        original_provider=provider.config.safe_dict(), adapted_provider=config.safe_dict(),
        historical_profile_pin_unchanged=True, prompt_changed=False, data_changed=False,
        scope_authority_required=True, model_calls=0, backend_calls=0)
    return adapted, receipt


def derive_compact_equivalence_profile(*, parent_path, parent_sha256, output):
    parent = FrozenOneShotProfile.load(parent_path, expected_sha256=parent_sha256)
    doc, _, _, _, backends, _, _ = parent.materialize()
    validate_identity_schema(doc['source_schema'], backends)
    if any(m['provider']['wire_profile'] != WIRE_PROFILE_V2 for m in doc['modes'].values()):
        raise ValueError('Equivalence revision requires an unmodified compact v2 parent')
    # Preserve the exact bytes of every referenced artifact at its original path.
    def absolute_pins(value):
        if isinstance(value, list):
            return [absolute_pins(v) for v in value]
        if isinstance(value, dict):
            return {k: str((parent.root / v).resolve()) if k == 'path' and isinstance(v, str)
                    else absolute_pins(v) for k, v in value.items()}
        return value
    doc = absolute_pins(doc)
    for mode in doc['modes'].values():
        mode['provider']['wire_profile'] = WIRE_PROFILE_EQUIVALENCE
        mode['provider']['provider_id'] += ':' + PROFILE
    doc['profile_id'] += ':' + PROFILE
    doc['offline']['compact_equivalence_revision'] = dict(profile=PROFILE,
        parent=dict(path=str(Path(parent_path).resolve()), sha256=parent_sha256),
        scope='same-domain canonical identity equality and redundant nonaggregate contribution projection',
        queries_read=0, answers_read=0, model_calls=0, backend_calls=0,
        prompt_changed=False, data_changed=False, historical_results_preserved=True)
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    pin = write_once(root / 'profile.json', doc)
    FrozenOneShotProfile.load(pin['path'], expected_sha256=pin['sha256'])
    return pin
