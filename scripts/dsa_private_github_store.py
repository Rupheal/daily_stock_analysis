"""Append-only private GitHub evidence storage with read-back hash verification.

This helper never accepts a token on the command line and never prints payload bytes.
It is intended to bridge the public DSA runner to an explicitly authorized private
repository after a synthetic persistence probe has passed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

DEFAULT_REPOSITORY = "Rupheal/TRIDENT-Foundation"
DEFAULT_BRANCH = "research/dsa-private-evidence-20260914"
TOKEN_ENV = "DSA_EVIDENCE_TOKEN"


class PrivateEvidenceError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_path(value: str) -> str:
    p = PurePosixPath(value)
    if p.is_absolute() or not p.parts or any(part in {"", ".", ".."} for part in p.parts):
        raise ValueError("unsafe destination path")
    return str(p)


class PrivateGitHubStore:
    def __init__(self, token: str, repository: str = DEFAULT_REPOSITORY,
                 branch: str = DEFAULT_BRANCH, client: httpx.Client | None = None):
        if not token or not token.strip():
            raise PrivateEvidenceError(f"missing {TOKEN_ENV}")
        self.repository = repository
        self.branch = branch
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url="https://api.github.com",
            headers={
                "Authorization": f"Bearer {token.strip()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "dsa-private-evidence-store/1",
            },
            timeout=30.0,
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def verify_private_destination(self) -> dict:
        r = self.client.get(f"/repos/{self.repository}")
        if r.status_code != 200:
            raise PrivateEvidenceError(f"destination repository check failed: HTTP {r.status_code}")
        meta = r.json()
        if not (meta.get("private") is True or meta.get("visibility") == "private"):
            raise PrivateEvidenceError("destination repository is not private")
        ref = self.client.get(f"/repos/{self.repository}/git/ref/heads/{quote(self.branch, safe='/')}")
        if ref.status_code != 200:
            raise PrivateEvidenceError(f"destination branch check failed: HTTP {ref.status_code}")
        return {
            "repository": self.repository,
            "branch": self.branch,
            "private": True,
            "repository_id": meta.get("id"),
        }

    def put_new(self, destination_path: str, data: bytes, commit_message: str) -> dict:
        destination_path = _safe_path(destination_path)
        encoded_path = quote(destination_path, safe="/")
        endpoint = f"/repos/{self.repository}/contents/{encoded_path}"
        existing = self.client.get(endpoint, params={"ref": self.branch})
        if existing.status_code == 200:
            raise PrivateEvidenceError("destination path already exists; append-only write refused")
        if existing.status_code != 404:
            raise PrivateEvidenceError(f"destination existence check failed: HTTP {existing.status_code}")
        digest = sha256_bytes(data)
        payload = {
            "message": commit_message,
            "content": base64.b64encode(data).decode("ascii"),
            "branch": self.branch,
        }
        created = self.client.put(endpoint, json=payload)
        if created.status_code not in {200, 201}:
            raise PrivateEvidenceError(f"private write failed: HTTP {created.status_code}")
        readback = self.client.get(endpoint, params={"ref": self.branch})
        if readback.status_code != 200:
            raise PrivateEvidenceError(f"private read-back failed: HTTP {readback.status_code}")
        body = readback.json()
        try:
            recovered = base64.b64decode(body["content"], validate=False)
        except Exception as exc:
            raise PrivateEvidenceError("private read-back content was not decodable") from exc
        recovered_digest = sha256_bytes(recovered)
        if recovered != data or recovered_digest != digest:
            raise PrivateEvidenceError("private read-back hash mismatch")
        commit = created.json().get("commit") or {}
        content = created.json().get("content") or {}
        return {
            "path": destination_path,
            "bytes": len(data),
            "sha256": digest,
            "readback_sha256": recovered_digest,
            "verified": True,
            "blob_sha": body.get("sha") or content.get("sha"),
            "commit_sha": commit.get("sha"),
        }

    def put_tree(self, source: Path, destination_prefix: str, commit_prefix: str) -> dict:
        destination_prefix = _safe_path(destination_prefix)
        if not source.exists():
            raise FileNotFoundError(source)
        files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
        if not files:
            raise PrivateEvidenceError("source contains no files")
        root = source.parent if source.is_file() else source
        stored = []
        for path in files:
            rel = path.name if source.is_file() else path.relative_to(root).as_posix()
            target = f"{destination_prefix}/{rel}"
            stored.append(self.put_new(target, path.read_bytes(), f"{commit_prefix}: {rel}"))
        return {
            "repository": self.repository,
            "branch": self.branch,
            "destination_prefix": destination_prefix,
            "files": stored,
            "file_count": len(stored),
            "all_verified": all(item["verified"] for item in stored),
        }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--destination-prefix", required=True)
    p.add_argument("--repository", default=DEFAULT_REPOSITORY)
    p.add_argument("--branch", default=DEFAULT_BRANCH)
    p.add_argument("--commit-prefix", default="evidence(dsa): persist private acceptance")
    args = p.parse_args()
    token = os.environ.get(TOKEN_ENV, "")
    store = PrivateGitHubStore(token, args.repository, args.branch)
    try:
        destination = store.verify_private_destination()
        result = store.put_tree(args.source, args.destination_prefix, args.commit_prefix)
        result["destination"] = destination
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        store.close()


if __name__ == "__main__":
    main()
