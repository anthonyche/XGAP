"""Bounded proxy-quality eligibility, not a calibrated answer-quality guarantee."""


def quality_band(winners, deficit):
    """O(K) on already validated candidates; preserve unknown-quality provenance."""
    best = max(row["ranking_quality_proxy"] for row in winners)
    minimum = best - deficit
    eligible = [row for row in winners if row["ranking_quality_proxy"] >= minimum]
    ids = {row["candidate_id"] for row in eligible}
    return eligible, {"schema_version": "xgap-proxy-quality-band-v1", "max_quality_deficit": deficit,
        "highest_ranking_quality_proxy": best, "minimum_eligible_ranking_quality_proxy": minimum,
        "eligible_candidate_ids": [row["candidate_id"] for row in eligible],
        "excluded_candidate_ids": [row["candidate_id"] for row in winners if row["candidate_id"] not in ids],
        "all_quality_proxies_known": all(row["quality_proxy"] is not None for row in winners),
        "quality_proxy_calibrated": False, "legacy_soft_penalty_used": False,
        "scope": "estimated cost minimum in the compatible admitted proxy-quality band; no unconditional answer bound"}
