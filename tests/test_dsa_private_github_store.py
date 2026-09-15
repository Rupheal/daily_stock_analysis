import base64
import hashlib
import json

import httpx
import pytest

from scripts.dsa_private_github_store import PrivateEvidenceError, PrivateGitHubStore, _safe_path


REPO = "Rupheal/TRIDENT-Foundation"
BRANCH = "research/dsa-private-evidence-20260914"


def mock_client(*, private=True, preexisting=None, transient_branch_404=False):
    state = dict(preexisting or {})
    commit_state = {}
    seen_refs = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/repos/{REPO}":
            return httpx.Response(200, json={"id": 1368133325, "private": private,
                                             "visibility": "private" if private else "public"})
        if path == f"/repos/{REPO}/git/ref/heads/{BRANCH}":
            return httpx.Response(200, json={"ref": f"refs/heads/{BRANCH}"})
        prefix = f"/repos/{REPO}/contents/"
        if path.startswith(prefix):
            target = path[len(prefix):]
            if request.method == "GET":
                ref = request.url.params.get("ref")
                seen_refs.append((target, ref))
                if ref and ref in commit_state and target in commit_state[ref]:
                    raw = commit_state[ref][target]
                elif target in state and not (transient_branch_404 and ref == BRANCH):
                    raw = state[target]
                else:
                    return httpx.Response(404, json={"message": "Not Found"})
                return httpx.Response(200, json={
                    "content": base64.b64encode(raw).decode("ascii"),
                    "encoding": "base64",
                    "sha": hashlib.sha1(raw).hexdigest(),
                })
            if request.method == "PUT":
                if target in state:
                    return httpx.Response(422, json={"message": "already exists"})
                payload = json.loads(request.content)
                raw = base64.b64decode(payload["content"])
                state[target] = raw
                commit_sha = "deadbeef"
                commit_state[commit_sha] = dict(state)
                return httpx.Response(201, json={
                    "content": {"sha": hashlib.sha1(raw).hexdigest()},
                    "commit": {"sha": commit_sha},
                })
        return httpx.Response(500, json={"message": f"unexpected {request.method} {path}"})

    client = httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))
    return client, state, seen_refs


def test_safe_path_rejects_traversal_and_absolute():
    with pytest.raises(ValueError):
        _safe_path("../secret")
    with pytest.raises(ValueError):
        _safe_path("/absolute")


def test_destination_must_be_private():
    client, _, _ = mock_client(private=False)
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    with pytest.raises(PrivateEvidenceError, match="not private"):
        store.verify_private_destination()


def test_append_only_write_readback_and_hash():
    client, state, seen_refs = mock_client(private=True)
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    destination = store.verify_private_destination()
    assert destination["private"] is True
    raw = b"synthetic-private-evidence\n"
    result = store.put_new("evidence/dsa/test/probe.txt", raw, "test")
    assert result["verified"] is True
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["readback_sha256"] == result["sha256"]
    assert result["readback_ref"] == "deadbeef"
    assert state["evidence/dsa/test/probe.txt"] == raw
    assert ("evidence/dsa/test/probe.txt", "deadbeef") in seen_refs


def test_commit_pinned_readback_survives_branch_propagation_404():
    client, state, seen_refs = mock_client(private=True, transient_branch_404=True)
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    raw = b"newly-created-evidence\n"
    result = store.put_new("evidence/dsa/test/propagation.txt", raw, "test")
    assert result["verified"] is True
    assert result["readback_ref"] == "deadbeef"
    assert state["evidence/dsa/test/propagation.txt"] == raw
    assert ("evidence/dsa/test/propagation.txt", "deadbeef") in seen_refs


def test_existing_path_is_never_overwritten():
    target = "evidence/dsa/test/probe.txt"
    client, _, _ = mock_client(private=True, preexisting={target: b"old"})
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    with pytest.raises(PrivateEvidenceError, match="append-only"):
        store.put_new(target, b"new", "test")
