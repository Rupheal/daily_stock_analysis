import base64
import hashlib
import json

import httpx
import pytest

from scripts.dsa_private_github_store import PrivateEvidenceError, PrivateGitHubStore, _safe_path


REPO = "Rupheal/TRIDENT-Foundation"
BRANCH = "research/dsa-private-evidence-20260914"


def mock_client(*, private=True, preexisting=None):
    state = dict(preexisting or {})

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
                if target not in state:
                    return httpx.Response(404, json={"message": "Not Found"})
                raw = state[target]
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
                return httpx.Response(201, json={
                    "content": {"sha": hashlib.sha1(raw).hexdigest()},
                    "commit": {"sha": "deadbeef"},
                })
        return httpx.Response(500, json={"message": f"unexpected {request.method} {path}"})

    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler)), state


def test_safe_path_rejects_traversal_and_absolute():
    with pytest.raises(ValueError):
        _safe_path("../secret")
    with pytest.raises(ValueError):
        _safe_path("/absolute")


def test_destination_must_be_private():
    client, _ = mock_client(private=False)
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    with pytest.raises(PrivateEvidenceError, match="not private"):
        store.verify_private_destination()


def test_append_only_write_readback_and_hash():
    client, state = mock_client(private=True)
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    destination = store.verify_private_destination()
    assert destination["private"] is True
    raw = b"synthetic-private-evidence\n"
    result = store.put_new("evidence/dsa/test/probe.txt", raw, "test")
    assert result["verified"] is True
    assert result["sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["readback_sha256"] == result["sha256"]
    assert state["evidence/dsa/test/probe.txt"] == raw


def test_existing_path_is_never_overwritten():
    target = "evidence/dsa/test/probe.txt"
    client, _ = mock_client(private=True, preexisting={target: b"old"})
    store = PrivateGitHubStore("test-token", REPO, BRANCH, client=client)
    with pytest.raises(PrivateEvidenceError, match="append-only"):
        store.put_new(target, b"new", "test")
