"""Static backend capability compatibility checks for M8."""

from __future__ import annotations

from dataclasses import dataclass

from xgap.backends.capabilities import (
    BackendCapabilityProfile,
    CompatibilityReport,
    FeatureSupport,
    SupportLevel,
    SupportReason,
    UnsupportedFeature,
)


_LEVEL_RANK = {
    SupportLevel.SUPPORTED: 2,
    SupportLevel.CONDITIONAL: 1,
    SupportLevel.UNSUPPORTED: 0,
}


@dataclass(frozen=True)
class FeatureRequest:
    feature_id: str


def _feature_id(feature_request: str | FeatureRequest) -> str:
    if isinstance(feature_request, FeatureRequest):
        return feature_request.feature_id
    return feature_request


def check_backend_support(
    profile: BackendCapabilityProfile,
    feature_request: str | FeatureRequest,
) -> CompatibilityReport:
    """Check one feature against a backend profile.

    This is a static profile lookup. It does not compile plans, execute
    queries, call backend clients, or call the reference evaluator.
    """

    feature_id = _feature_id(feature_request)
    support = profile.feature(feature_id)
    if support is None:
        reason = SupportReason(
            code="feature_not_declared",
            message=f"Backend '{profile.backend_id}' does not declare feature '{feature_id}'.",
            future_milestone="M8+",
        )
        unsupported = UnsupportedFeature(feature_id=feature_id, reason=reason)
        return CompatibilityReport(
            backend_id=profile.backend_id,
            feature_id=feature_id,
            level=SupportLevel.UNSUPPORTED,
            reason=reason,
            unsupported_features=(unsupported,),
        )

    unsupported_features: tuple[UnsupportedFeature, ...] = ()
    if support.level is not SupportLevel.SUPPORTED:
        unsupported_features = (UnsupportedFeature.from_feature_support(support),)
    return _report_from_support(profile, support, unsupported_features)


def check_backend_features(
    profile: BackendCapabilityProfile,
    feature_requests: tuple[str | FeatureRequest, ...],
    *,
    feature_set_id: str = "feature_set",
) -> CompatibilityReport:
    """Check a deterministic set of required features."""

    reports = tuple(
        check_backend_support(profile, request)
        for request in sorted(feature_requests, key=_feature_id)
    )
    if not reports:
        reason = SupportReason(
            code="empty_feature_set",
            message="No features were requested.",
        )
        return CompatibilityReport(
            backend_id=profile.backend_id,
            feature_id=feature_set_id,
            level=SupportLevel.SUPPORTED,
            reason=reason,
        )

    worst = min((report.level for report in reports), key=lambda level: _LEVEL_RANK[level])
    blocking = tuple(
        unsupported
        for report in reports
        for unsupported in report.unsupported_features
    )
    reason = SupportReason(
        code="feature_set_compatibility",
        message=f"Checked {len(reports)} feature(s) for backend '{profile.backend_id}'.",
    )
    conditions = tuple(
        condition
        for report in reports
        for condition in report.conditions
    )
    return CompatibilityReport(
        backend_id=profile.backend_id,
        feature_id=feature_set_id,
        level=worst,
        reason=reason,
        conditions=conditions,
        unsupported_features=blocking,
        metadata={"checked_features": [report.feature_id for report in reports]},
    )


def _report_from_support(
    profile: BackendCapabilityProfile,
    support: FeatureSupport,
    unsupported_features: tuple[UnsupportedFeature, ...],
) -> CompatibilityReport:
    return CompatibilityReport(
        backend_id=profile.backend_id,
        feature_id=support.feature_id,
        level=support.level,
        reason=support.reason,
        conditions=support.conditions,
        unsupported_features=unsupported_features,
        metadata=support.metadata,
    )
