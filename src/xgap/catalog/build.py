"""Explicit offline publisher for small resolution artifacts; never called by runtime."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from xgap.catalog.bundle import SCHEMA, FrozenResolutionBundle, content_hash, read_file


def freeze_resolution_bundle(*, catalog: str | Path, bindings: str | Path,
                             output: str | Path, ontology: str | Path | None = None) -> dict:
    output = Path(output)
    if output.exists():
        raise FileExistsError("Frozen output already exists; publish a new version at a new path")
    inputs = {"catalog.json": Path(catalog), "bindings.json": Path(bindings)}
    if ontology is not None:
        inputs["ontology.json"] = Path(ontology)
    data = {name: read_file(path) for name, path in inputs.items()}
    manifest = {"schema_version": SCHEMA,
                "files": {name: hashlib.sha256(value).hexdigest() for name, value in data.items()}}
    manifest["bundle_hash"] = content_hash(manifest)
    manifest_data = (json.dumps(manifest, indent=2) + "\n").encode()
    # Validate exactly the bytes being published, not mutable preparation paths.
    with tempfile.TemporaryDirectory(prefix="xgap-resolution-prepare-") as temporary:
        staging = Path(temporary)
        for name, value in {**data, "manifest.json": manifest_data}.items():
            (staging / name).write_bytes(value)
        FrozenResolutionBundle.load(staging, expected_bundle_hash=manifest["bundle_hash"])
    output.mkdir(parents=True, exist_ok=False)  # Exclusive ownership; never replace another output.
    for name, value in data.items():
        with (output / name).open("xb") as stream:
            stream.write(value)
    pending = output / ".manifest.tmp"
    with pending.open("xb") as stream:
        stream.write(manifest_data)
    os.replace(pending, output / "manifest.json")  # Publish completeness last.
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--bindings", required=True)
    parser.add_argument("--ontology")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    manifest = freeze_resolution_bundle(**vars(args))
    print(json.dumps({"root": args.output, "bundle_hash": manifest["bundle_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
