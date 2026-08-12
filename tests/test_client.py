from __future__ import annotations

from types import SimpleNamespace

from ucloud_workflow.client import UCloudClient
from ucloud_workflow.settings import Settings


def test_browse_api_tokens_uses_documented_browse_endpoint(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(self, method, path, *, params=None, json=None):
        seen.update(method=method, path=path, params=params, json=json)
        return SimpleNamespace(json=lambda: {"items": []})

    monkeypatch.setattr(UCloudClient, "request", fake_request)
    client = UCloudClient(
        Settings(server="https://cloud.sdu.dk", token="token", project="Moody's Datahub")
    )
    try:
        assert client.browse_api_tokens(items_per_page=25, filter_hidden=True) == {"items": []}
    finally:
        client.close()

    assert seen == {
        "method": "GET",
        "path": "/api/tokens/browse",
        "params": {"itemsPerPage": 25, "filterHidden": "true"},
        "json": None,
    }


def test_create_api_token_uses_single_create_request(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_request(self, method, path, *, params=None, json=None):
        seen.update(method=method, path=path, params=params, json=json)
        return SimpleNamespace(json=lambda: {"id": "token-123", "status": {"token": "one-time-secret"}})

    monkeypatch.setattr(UCloudClient, "request", fake_request)
    client = UCloudClient(
        Settings(server="https://cloud.sdu.dk", token="token", project="Moody's Datahub")
    )
    try:
        assert client.create_api_token({"title": "Test"})["id"] == "token-123"
    finally:
        client.close()

    assert seen == {
        "method": "POST",
        "path": "/api/tokens",
        "params": None,
        "json": {"title": "Test"},
    }
