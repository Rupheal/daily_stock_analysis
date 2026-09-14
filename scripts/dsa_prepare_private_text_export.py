"""Prepare a bounded text-only export for private DSA native acceptance evidence.

The source probe may create a SQLite database for native execution. TRIDENT's
private Git history must not be used for binary backups, so this exporter copies
only the explicitly approved textual acceptance evidence and writes a manifest
of hashes. Missing optional files are recorded without fabricating content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

APPROVED = [
    "preflight.json",
    "preflight-stdout.log",
    "preflight-stderr.log",
    "native-stdout.log",
    "native-stderr.log",
    "process.json",
    "process.rc",
    "original-model/original-input.json",
    "original-model/original-result.json",
    "original-model/provider-response.txt",
    "original-model/request-body.json",
    "original-model/budget.json",
    "original-model/probe-summary.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    rows = []
    for rel in APPROVED:
        src = source / rel
        row = {"path": rel, "present": src.is_file()}
        if src.is_file():
            raw = src.read_bytes()
            if b"\x00" in raw:
                raise ValueError(f"binary-looking evidence refused: {rel}")
            dst = output / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        rows.append(row)
    binary = sorted(str(p.relative_to(source)) for p in source.rglob("*.db") if p.is_file())
    manifest = {
        "schema": "dsa-private-text-export-v1",
        "approved_paths": APPROVED,
        "files": rows,
        "excluded_binary_paths": binary,
        "binary_files_copied": 0,
    }
    manifest_path = output / "private-export-manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    manifest["manifest_sha256"] = sha256(manifest_path)
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = prepare(args.source, args.output)
    print(json.dumps({
        "schema": result["schema"],
        "present_count": sum(1 for x in result["files"] if x["present"]),
        "approved_count": len(result["files"]),
        "excluded_binary_count": len(result["excluded_binary_paths"]),
        "binary_files_copied": result["binary_files_copied"],
        "manifest_sha256": result["manifest_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
