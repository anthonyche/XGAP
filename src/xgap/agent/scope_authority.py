"""Private user intent independent of proposals; paid membership confirmation."""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from xgap.agent.intent_certificate import canonical, fingerprint
from xgap.agent.intent_user import ScopedFamilyUser
from xgap.semantic.compact_query import validate_query
from xgap.tools.contracts import ToolResult, ToolStatus


def private_query_intent(question, query, *, language_version='v1'):
    query = validate_query(query, version=language_version)
    return dict(schema_version='xgap-private-query-intent-v1', question_sha256=fingerprint(question),
                query=query, language_version=language_version, nonce=secrets.token_hex(32))


@dataclass(frozen=True)
class QueryIntentAuthority:
    response_path: Path
    expected_sha256: str

    def _query(self, question_sha256):
        with self.response_path.open('rb') as stream:
            raw = stream.read(131073)
        if len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != self.expected_sha256:
            raise ValueError('Private query intent size/hash mismatch')
        data = json.loads(raw)
        if (set(data) != {'schema_version', 'question_sha256', 'query', 'language_version', 'nonce'}
                or data['schema_version'] != 'xgap-private-query-intent-v1'
                or data['question_sha256'] != question_sha256
                or not isinstance(data['nonce'], str) or not re.fullmatch('[a-f0-9]{64}', data['nonce'])):
            raise ValueError('Private query intent identity mismatch')
        return validate_query(data['query'], version=data['language_version']), data['language_version']

    def confirm_scope(self, question, draft):
        """One metered query. A positive reply reveals containment, not a choice."""
        started = time.perf_counter()
        args = dict(question_sha256=fingerprint(question), proposed_scope_sha256=draft.identity)
        try:
            query, version = self._query(args['question_sha256'])
            covered = version == draft.language_version and canonical(query) in {c.query_json for c in draft.candidates}
            result = ToolResult.success('user.confirm_scope', {**args, 'covered': covered})
        except (OSError, ValueError, KeyError, TypeError) as error:
            result = ToolResult.error_result('user.confirm_scope', str(error))
        return ToolResult(result.tool_name, result.status, result.value, result.error,
            metrics=dict(user_calls=1, disclosed_coordinates=0, elapsed_ms=(time.perf_counter()-started)*1000,
                         reply_bytes=len(canonical(result.value).encode()) if result.value else 0))

    def bind(self, question, draft, confirmation):
        args = dict(question_sha256=fingerprint(question), proposed_scope_sha256=draft.identity, covered=True)
        if (confirmation.status is not ToolStatus.SUCCESS
                or confirmation.tool_name != 'user.confirm_scope' or confirmation.value != args):
            raise ValueError('Positive matching authoritative scope reply required')
        family = replace(draft, coverage_basis='private_user_scope_confirmation:' + fingerprint(args))
        return family, ScopedQueryUser(family, self.response_path, self.expected_sha256)


@dataclass(frozen=True)
class ScopedQueryUser(ScopedFamilyUser):
    def _load(self, question_sha256):
        query, version = QueryIntentAuthority(self.response_path, self.expected_sha256)._query(question_sha256)
        matches = [i for i, c in enumerate(self.family.candidates)
                   if c.query_json == canonical(query) and version == self.family.language_version]
        if len(matches) != 1:
            raise ValueError('User intent is outside the confirmed scope')
        return matches[0]
