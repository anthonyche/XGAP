"""Admission contracts for original archive-bound FinBench workloads."""

from __future__ import annotations

from copy import deepcopy

import pytest

from xgap.experiments.m15_finbench_partition import validate_finbench_source_identity


ARCHIVE_SHA = "a1" * 32
PARTITION_SHA = "b2" * 32
OTHER_SHA = "c3" * 32
MODES = ("partition", "source_archive")


@pytest.fixture
def identities():
    return (
        {
            "source_archive_sha256": ARCHIVE_SHA,
            "source_partition_sha256": PARTITION_SHA,
        },
        {
            "source_archive": {"sha256": ARCHIVE_SHA},
            "partition_sha256": PARTITION_SHA,
        },
    )


def test_default_partition_identity_returns_archive_sha_without_mutating_inputs(identities):
    workload, partition = identities
    before = deepcopy(identities)

    assert validate_finbench_source_identity(workload, partition) == ARCHIVE_SHA
    assert identities == before


@pytest.mark.parametrize("declared_partition_pin", (False, True))
def test_explicit_archive_mode_accepts_absent_or_matching_partition_pin(
    identities, declared_partition_pin
):
    workload, partition = identities
    if not declared_partition_pin:
        del workload["source_partition_sha256"]
    before = deepcopy(identities)

    assert validate_finbench_source_identity(
        workload, partition, source_identity_mode="source_archive"
    ) == ARCHIVE_SHA
    assert identities == before


def test_default_mode_does_not_infer_archive_admission_from_missing_pin(identities):
    workload, partition = identities
    del workload["source_partition_sha256"]

    with pytest.raises(ValueError):
        validate_finbench_source_identity(workload, partition)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "pin",
    (None, "", "bad-digest", PARTITION_SHA.upper(), OTHER_SHA, 123),
    ids=("null", "empty", "malformed", "uppercase", "mismatch", "non-string"),
)
def test_declared_partition_pin_is_never_ignored(identities, mode, pin):
    workload, partition = identities
    workload["source_partition_sha256"] = pin

    with pytest.raises(ValueError):
        validate_finbench_source_identity(workload, partition, source_identity_mode=mode)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize(
    "invalid_identity",
    (
        "missing-workload-archive",
        "missing-partition-archive",
        "missing-nested-archive-hash",
        "invalid-archive-container",
        "uppercase-workload-archive",
        "malformed-partition-archive",
        "mismatched-archives",
        "missing-actual-partition",
        "uppercase-actual-partition",
        "malformed-actual-partition",
    ),
)
def test_both_modes_require_complete_valid_source_and_layout_identities(
    identities, mode, invalid_identity
):
    workload, partition = identities
    if mode == "source_archive":
        del workload["source_partition_sha256"]
    if invalid_identity == "missing-workload-archive":
        del workload["source_archive_sha256"]
    elif invalid_identity == "missing-partition-archive":
        del partition["source_archive"]
    elif invalid_identity == "missing-nested-archive-hash":
        partition["source_archive"] = {}
    elif invalid_identity == "invalid-archive-container":
        partition["source_archive"] = None
    elif invalid_identity == "uppercase-workload-archive":
        workload["source_archive_sha256"] = ARCHIVE_SHA.upper()
    elif invalid_identity == "malformed-partition-archive":
        partition["source_archive"]["sha256"] = "g" * 64
    elif invalid_identity == "mismatched-archives":
        partition["source_archive"]["sha256"] = OTHER_SHA
    elif invalid_identity == "missing-actual-partition":
        del partition["partition_sha256"]
    elif invalid_identity == "uppercase-actual-partition":
        partition["partition_sha256"] = PARTITION_SHA.upper()
    else:
        partition["partition_sha256"] = PARTITION_SHA[:-1]

    with pytest.raises(ValueError):
        validate_finbench_source_identity(workload, partition, source_identity_mode=mode)


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("invalid_sha", (None, "", 123))
def test_equal_invalid_archive_values_do_not_establish_identity(identities, mode, invalid_sha):
    workload, partition = identities
    workload["source_archive_sha256"] = invalid_sha
    partition["source_archive"]["sha256"] = invalid_sha

    with pytest.raises(ValueError):
        validate_finbench_source_identity(workload, partition, source_identity_mode=mode)


@pytest.mark.parametrize("mode", (None, "", "archive", "PARTITION", "unknown"))
def test_unknown_or_null_modes_are_rejected(identities, mode):
    workload, partition = identities

    with pytest.raises(ValueError):
        validate_finbench_source_identity(workload, partition, source_identity_mode=mode)
