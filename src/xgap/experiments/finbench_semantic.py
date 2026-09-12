"""Gold financial programs for deterministic development, never NL dispatch.

No prepared physical plans or native query strings: each program enters ordinary
semantic compilation and bounded estimated planning. Answers are separate inputs.
"""

from xgap.semantic.program import SemanticGraphProgram
from xgap.semantic.parameter_contract import validate_program_parameters


def load_financial_provider(*, mode="performance", disable_thinking=False):
    """Ordinary provider plus generic syntax only; no gold program dependency."""
    from dataclasses import replace
    from pathlib import Path
    from xgap.experiments.hashing import content_hash
    from xgap.experiments.one_shot_toy import load_one_shot_toy_provider
    from xgap.llm.candidate_interpretation import OpenAICompatibleCandidateInterpretationProvider
    base = load_one_shot_toy_provider(mode=mode, wire_profile="envelope-schema-v1",
        disable_thinking=disable_thinking)
    appendix = (Path(__file__).resolve().parents[3]/"prompts/interpretation/financial_binding_v1.txt").read_text()
    prompt = base.system_prompt + "\n" + appendix
    config = replace(base.config, provider_id=base.provider_id + ":financial-binding-v1", prompt_hash=content_hash(prompt))
    return OpenAICompatibleCandidateInterpretationProvider(config, prompt, base.token_guard, base.transport)


class _Program:
    def __init__(self, family):
        self.family, self.ops, self.sources, self.kinds = family, [], {}, {}

    def add(self, name, kind, inputs=(), **parameters):
        output = "grouped_bindings" if kind == "aggregate" else self.kinds[inputs[0]] if kind in ("filter", "order_limit", "union") else "binding_set"
        self.ops.append(dict(operator_id=name, kind=kind, input_ids=list(inputs),
            input_kinds=[self.kinds[i] for i in inputs], output_kind=output, parameters=parameters))
        self.kinds[name] = output
        return name

    def node(self, name, entity, field, properties, *, control=False, values=None):
        self.sources[name] = "control" if control else "graph"
        return self.add(name, "match", node={"label": "XGAPFinBench" + entity.title(), "properties": values or {}},
            entity_field=field, properties=properties)

    def edge(self, name, label, left, right, properties=None, *, source_type=None, target_type=None, source_values=None):
        self.sources[name] = "graph"
        source = {"label": "XGAPFinBench" + source_type.title()} if source_type else {}
        if source_values: source["properties"] = source_values
        target = {"label": "XGAPFinBench" + target_type.title()} if target_type else {}
        return self.add(name, "match", edge={"label": label}, source=source, target=target,
            entity_field=name + "_edge", source_field=left, target_field=right, properties=properties or {})

    def join(self, name, left, right, left_on, right_on):
        return self.add(name, "join", (left, right), left_on=left_on, right_on=right_on)

    def project(self, name, source, **columns):
        return self.add(name, "project", (source,), projections={name:
            {"kind": "field", "field": value} if isinstance(value, str) else {"kind": "literal", "value": value}
            for name, value in columns.items()})

    def filter(self, name, source, *conditions):
        return self.add(name, "filter", (source,), condition={"op": "and", "args": list(conditions)})

    def window(self, name, source, timestamp, parameters, *, inclusive=True):
        return self.filter(name, source,
            {"op": "ge", "field": timestamp, "value": parameters["start_time"], "value_type": "timestamp_ms"},
            {"op": "le" if inclusive else "lt", "field": timestamp, "value": parameters["end_time"], "value_type": "timestamp_ms"})

    def finish(self, root):
        raw = dict(program_id="financial-gold-" + self.family, operators=self.ops, roots=[root],
            metadata={"role": "deterministic_development_gold", "input_profile": "declared_semantic_program", "paper_result": False})
        validate_program_parameters(raw)
        return SemanticGraphProgram.from_dict(raw), self.sources


def financial_program(family, p):
    """Finite gold programs for F1/F2/F3, independent of expected rows/costs."""
    b = _Program(family)
    if family == "F2":
        if p["max_hops"] != 3 or type(p["max_hops"]) is not int:
            raise ValueError("Temporal development family requires max_hops=3")
        branches = []
        for length in range(1, 4):
            transfer = b.edge(f"transfer{length}", "TRANSFERRED_TO", f"n{length-1}", f"n{length}",
                {f"t{length}": "createTime"}, source_type="account" if length == 1 else None,
                source_values={"id": p["start_account_id"]} if length == 1 else None)
            transfer = b.window(f"window{length}", transfer, f"t{length}", p)
            if length == 1:
                path = transfer
            else:
                path = b.join(f"chain{length}", path, transfer, f"n{length-1}", f"n{length-1}")
            tests = [{"op": "ne", "field": f"n{i}", "right_field": f"n{length}"} for i in range(length)]
            if length > 1:
                tests.append({"op": "lt", "field": f"t{length-1}", "right_field": f"t{length}", "value_type": "timestamp_ms"})
            path = b.filter(f"valid{length}", path, *tests)
            branches.append(b.project(f"branch{length}", path, endpoint=f"n{length}", account_distance=length))
        paths = b.add("union12", "union", branches[:2])
        paths = b.add("paths", "union", (paths, branches[2]))
        accounts = b.node("accounts", "account", "endpoint", {"other_id": "id"}, control=True)
        paths = b.join("named_paths", paths, accounts, "endpoint", "endpoint")
        signs = b.edge("signs", "SIGNED_IN_TO", "medium", "endpoint")
        media = b.node("media", "medium", "medium", {"medium_id": "id", "medium_type": "mediumType"},
            control=True, values={"isBlocked": True})
        blocked = b.join("blocked_signs", signs, media, "medium", "medium")
        matches = b.join("matches", paths, blocked, "endpoint", "endpoint")
        result = b.project("answer", matches, other_id="other_id", account_distance="account_distance",
            medium_id="medium_id", medium_type="medium_type")
        result = b.add("ordered", "order_limit", (result,), order_by=[{"field": f} for f in
            ("account_distance", "other_id", "medium_id")], limit=None)
    elif family in ("F1", "F3"):
        transfers = b.edge("transfers", "TRANSFERRED_TO", "sender", "account",
            {"amount": "amount", "timestamp": "createTime"}, source_type="account" if family == "F1" else None,
            target_type="account")
        transfers = b.window("window", transfers, "timestamp", p, inclusive=family == "F1")
        owners = b.edge("owners", "OWNS_ACCOUNT", "company", "account", source_type="company", target_type="account")
        companies = b.node("companies", "company", "company", {"company_id": "id"})
        owners = b.join("named_owners", owners, companies, "company", "company")
        if family == "F1":
            own = b.edge("person_owns", "OWNS_ACCOUNT", "person", "sender", source_type="person",
                source_values={"id": p["person_id"]})
            transfers = b.join("person_transfers", own, transfers, "sender", "sender")
            accounts = b.node("blocked", "account", "account", {"account_id": "id"}, control=True, values={"isBlocked": True})
            transfers = b.join("blocked_transfers", transfers, accounts, "account", "account")
            joined = b.join("owned_transfers", owners, transfers, "account", "account")
            grouping, ordering, limit = ["company_id", "account_id"], [{"field": "company_id"}, {"field": "account_id"}], None
        else:
            signs = b.edge("signs", "SIGNED_IN_TO", "medium", "account")
            media = b.node("media", "medium", "medium", {}, control=True, values={"riskLevel": p["risk_level"]})
            signs = b.join("risk_signs", signs, media, "medium", "medium")
            eligible = b.join("eligible", owners, signs, "account", "account")
            eligible = b.project("eligible_accounts", eligible, company="company", company_id="company_id", account="account")
            joined = b.join("incoming", eligible, transfers, "account", "account")
            grouping, ordering, limit = ["company_id"], [{"field": "total_amount", "direction": "desc"}, {"field": "company_id"}], p["top_k"]
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError("Top K outside admitted profile")
        result = b.add("totals", "aggregate", (joined,), group_by=grouping, aggregations={"total_amount": {"op": "sum", "field": "amount"}})
        result = b.add("ordered", "order_limit", (result,), order_by=ordering, limit=limit)
    else:
        raise ValueError("Unknown financial family")
    return b.finish(result)
