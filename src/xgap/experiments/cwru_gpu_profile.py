"""Explicit allocation profiles for the unchanged BF16 Qwen3-32B service.

Legacy contracts retain their historical H100 behavior. New profiles validate
all CUDA-visible devices, not the first device reported by host nvidia-smi.
This module never requests, changes, cancels or retries a Slurm allocation.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class GPUProfile:
    profile_id: str
    model_pattern: str
    count: int
    minimum_memory_mib: int
    feature: str
    tensor_parallel_size: int = 1
    pipeline_parallel_size: int = 1


PROFILES = {
    "h100-single-v1": GPUProfile("h100-single-v1", r"NVIDIA H100(?: .*)?", 1, 79000, "gpu2h100"),
    "a100-80gb-single-v1": GPUProfile("a100-80gb-single-v1", r"NVIDIA A100(?:[- ].*)?", 1, 79000, "dgx"),
    "l40s-pipeline2-v1": GPUProfile("l40s-pipeline2-v1", r"NVIDIA L40S", 2, 45000, "gpul40s",
                                   pipeline_parallel_size=2),
}


def profile_for(contract: Mapping[str, Any]) -> GPUProfile | None:
    name = contract.get("gpu_profile")
    if name is None:
        if any(k in contract["serving"] for k in ("tensor_parallel_size", "pipeline_parallel_size")):
            raise ValueError("Parallel serving requires an explicit GPU profile")
        return None
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError("Unknown explicit GPU profile")
    profile = PROFILES[name]
    serving, slurm = contract["serving"], contract["slurm"]
    for key, expected in {"model":"Qwen/Qwen3-32B", "dtype":"bfloat16", "max_model_len":12288,
                          "gpu_memory_utilization":0.9, "tensor_parallel_size":profile.tensor_parallel_size,
                          "pipeline_parallel_size":profile.pipeline_parallel_size}.items():
        if type(serving.get(key)) is not type(expected) or serving[key] != expected:
            raise ValueError("GPU profile serving configuration mismatch: " + key)
    if (slurm.get("partition") != "gpu" or slurm.get("feature") != profile.feature
            or slurm.get("gres") != f"gpu:{profile.count}"):
        raise ValueError("GPU profile scheduler request mismatch")
    return profile


def visible_gpu_record(profile: GPUProfile, devices: list[dict[str, Any]], *, job_id: str) -> dict[str, Any]:
    """Validate CUDA-indexed device observations; usable capacity is checked by vLLM."""
    if not re.fullmatch(r"[0-9]+", job_id):
        raise ValueError("An actual Slurm job identity is required")
    if len(devices) != profile.count:
        raise ValueError("CUDA-visible GPU count does not match the profile")
    for i, device in enumerate(devices):
        if (type(device.get("cuda_index")) is not int or device["cuda_index"] != i
                or not isinstance(device.get("model"), str)
                or re.fullmatch(profile.model_pattern, device["model"]) is None
                or type(device.get("memory_mib")) is not int
                or device["memory_mib"] < profile.minimum_memory_mib
                or type(device.get("compute_major")) is not int or device["compute_major"] < 8):
            raise ValueError("CUDA-visible device does not support the frozen BF16 profile")
    return {"status":"available", "profile_id":profile.profile_id, "slurm_job_id":job_id,
            "devices":[dict(d) for d in devices], "model":devices[0]["model"],
            "device_count":len(devices), "observation_scope":"cuda_visible_devices",
            "tensor_parallel_size":profile.tensor_parallel_size,
            "pipeline_parallel_size":profile.pipeline_parallel_size}


def collect_visible_gpus(profile: GPUProfile) -> dict[str, Any]:
    # Lazy: default tests and legacy readers do not import CUDA dependencies.
    import torch
    devices = []
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        devices.append({"cuda_index":index, "model":props.name,
                        "memory_mib":props.total_memory // (1024*1024),
                        "compute_major":props.major, "compute_minor":props.minor})
    return visible_gpu_record(profile, devices, job_id=os.environ.get("SLURM_JOB_ID", ""))


def validate_recorded_profile(contract: Mapping[str, Any], environment: Mapping[str, Any]) -> None:
    profile = profile_for(contract)
    if profile is None:
        return
    gpu = environment["gpu"]
    expected = visible_gpu_record(profile, gpu["devices"], job_id=environment["slurm"]["job_id"])
    if json.dumps(gpu, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
        raise ValueError("Recorded CUDA profile mismatch")
    for key in ("tensor_parallel_size", "pipeline_parallel_size"):
        if type(environment["model"].get(key)) is not int or environment["model"][key] != getattr(profile, key):
            raise ValueError("Recorded model parallelism mismatch")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--verify-allocation", action="store_true")
    args = parser.parse_args(argv)
    from xgap.experiments.cwru_vllm import CWRUVLLMContract
    contract = CWRUVLLMContract.load(args.contract)
    profile = profile_for(contract.data)
    if profile is not None:
        if not args.verify_allocation:
            parser.error("Explicit GPU profile requires --verify-allocation before launch")
        collect_visible_gpus(profile)
        # Only fixed allowlisted tokens are emitted, one argument per line.
        for value in ("--tensor-parallel-size", str(profile.tensor_parallel_size),
                      "--pipeline-parallel-size", str(profile.pipeline_parallel_size),
                      "--distributed-executor-backend", "mp"):
            print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
