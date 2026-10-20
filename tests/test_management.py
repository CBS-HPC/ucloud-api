from __future__ import annotations

import base64
from dataclasses import asdict
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from ucloud_workflow import cli, management_cli, resources, ssh_keys
from ucloud_workflow.availability import check_machine_availability
from ucloud_workflow.client import UCloudClient
from ucloud_workflow.settings import Settings


PRODUCT = {"id": "test-product", "category": "test-category", "provider": "test-provider"}
SETTINGS = Settings(server="https://ucloud.invalid", token="test-secret", project="test-workspace")
ALGORITHM = b"ssh-ed25519"
KEY = "ssh-ed25519 " + base64.b64encode(
    len(ALGORITHM).to_bytes(4, "big") + ALGORITHM + (32).to_bytes(4, "big") + bytes(range(32))
).decode() + " test-comment"


@pytest.fixture
def client_factory():
    clients = []

    def make(handler):
        client = UCloudClient(SETTINGS)
        client._client.close()
        client._client = httpx.Client(base_url=SETTINGS.server, transport=httpx.MockTransport(handler))
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.close()


def resource_handler(calls, *, bound_to=None, status_present=True, post_status=200):
    resource = {"id": "test-resource", "specification": {"product": PRODUCT}, "status": {"state": "READY"}}
    if status_present:
        resource["status"]["boundTo"] = bound_to

    def handler(request):
        calls.append(request)
        if request.method == "GET" and request.url.path.endswith("/retrieveProducts"):
            support = {"product": PRODUCT, "domainPrefix": "app-", "domainSuffix": ".example.invalid", "firewall": {"enabled": True}}
            return httpx.Response(200, json={"productsByProvider": {PRODUCT["provider"]: [{"product": {}, "support": support}]}})
        if request.method == "GET" and request.url.path.endswith("/browse"):
            return httpx.Response(200, json={"items": [resource], "next": None})
        if request.method == "GET" and request.url.path.endswith("/retrieve"):
            return httpx.Response(200, json=resource)
        if request.method == "POST":
            return httpx.Response(post_status, json={"responses": [{"id": "created-resource"}]})
        return httpx.Response(200, json={})

    return handler


@pytest.mark.parametrize("namespace", ["ingresses", "networkips", "licenses"])
def test_resource_client_paths_and_single_item_payloads(client_factory, namespace):
    calls = []
    client = client_factory(resource_handler(calls))
    client.browse_resources(namespace, next_page="cursor")
    client.retrieve_resource(namespace, "test-resource")
    client.retrieve_resource_products(namespace)
    client.create_resource(namespace, {"product": PRODUCT})
    client.delete_resource(namespace, "test-resource")
    client.update_resource(namespace, "updateLabels", {"id": "test-resource", "labels": {}})
    assert [(request.method, request.url.path) for request in calls] == [
        ("GET", f"/api/{namespace}/browse"), ("GET", f"/api/{namespace}/retrieve"),
        ("GET", f"/api/{namespace}/retrieveProducts"), ("POST", f"/api/{namespace}"),
        ("DELETE", f"/api/{namespace}"), ("POST", f"/api/{namespace}/updateLabels"),
    ]
    assert calls[0].url.params["next"] == "cursor"
    assert json.loads(calls[3].content) == {"items": [{"product": PRODUCT}]}
    assert json.loads(calls[4].content) == {"items": [{"id": "test-resource"}]}


def test_client_rejects_arbitrary_namespaces_before_http(client_factory):
    calls = []
    client = client_factory(resource_handler(calls))
    with pytest.raises(ValueError):
        client.browse_resources("../tokens")
    with pytest.raises(ValueError):
        client.update_resource("licenses", "firewall", {})
    assert not calls


def test_browse_all_follows_pages_and_rejects_repeated_cursor():
    responses = [{"items": [{"id": "first"}], "next": "second"}, {"items": [{"id": "second"}], "next": None}]
    cursors = []

    def fetch(**kwargs):
        cursors.append(kwargs["next_page"])
        return responses.pop(0)

    assert [item["id"] for item in resources.browse_all(fetch)] == ["first", "second"]
    assert cursors == [None, "second"]
    with pytest.raises(resources.ManagementError, match="pagination"):
        resources.browse_all(lambda **kwargs: {"items": [], "next": "loop"})
    with pytest.raises(resources.ManagementError, match="items list"):
        resources.browse_all(lambda **kwargs: {})


@pytest.mark.parametrize("bound_to,status_present,allowed", [(None, True, True), ([], True, True), (["test-job"], True, False), (None, False, False)])
def test_deletion_requires_known_unused_resource_in_current_scope(client_factory, bound_to, status_present, allowed):
    calls = []
    client = client_factory(resource_handler(calls, bound_to=bound_to, status_present=status_present))
    if allowed:
        assert resources.delete_resource(client, "ingresses", "test-resource")["deleted"]
    else:
        with pytest.raises(resources.ManagementError):
            resources.delete_resource(client, "ingresses", "test-resource")
    assert any(request.method == "DELETE" for request in calls) is allowed
    with pytest.raises(resources.ManagementError, match="workspace"):
        resources.delete_resource(client, "ingresses", "outside-workspace")


def test_create_validates_product_domain_and_closed_firewall(client_factory, tmp_path):
    calls = []
    client = client_factory(resource_handler(calls))
    prepared = resources.prepare_resource(client, "networkips", {"product": PRODUCT})
    assert prepared["firewall"] == {"openPorts": []}
    with pytest.raises(ValueError, match="pattern"):
        resources.prepare_resource(client, "ingresses", {"product": PRODUCT, "domain": "bad.example.org"})
    with pytest.raises(resources.ManagementError, match="advertised"):
        resources.prepare_resource(client, "licenses", {"product": {**PRODUCT, "provider": "wrong-provider"}})
    result = resources.create_resource(client, "ingresses", {"product": PRODUCT, "domain": "app-test.example.invalid"}, operation_dir=tmp_path)
    record = json.loads(Path(result["operation_record"]).read_text())
    assert record["resource_id"] == "created-resource"
    assert record["outcome"] == "created"
    assert record["project"] == SETTINGS.project
    assert "test-secret" not in json.dumps(record)


@pytest.mark.parametrize("status,expected", [(400, "failed"), (503, "unknown")])
def test_http_create_failure_records_safe_outcome(client_factory, tmp_path, status, expected):
    calls = []
    client = client_factory(resource_handler(calls, post_status=status))
    with pytest.raises(resources.ManagementError):
        resources.create_resource(client, "licenses", {"product": PRODUCT}, operation_dir=tmp_path)
    assert sum(request.method == "POST" for request in calls) == 1
    assert json.loads(next(tmp_path.glob("*.json")).read_text())["outcome"] == expected


def test_timeout_does_not_retry_or_log_raw_error(tmp_path):
    calls = []

    def create():
        calls.append(True)
        raise httpx.ReadTimeout("test-secret and private command details")

    with pytest.raises(resources.CreateOutcomeUnknownError) as caught:
        resources.recorded_create(create, namespace="licenses", project="test", operation_dir=tmp_path)
    assert len(calls) == 1
    assert "test-secret" not in str(caught.value)
    record = next(tmp_path.glob("*.json")).read_text()
    assert '"unknown"' in record
    assert "test-secret" not in record


def test_resource_wait_and_updates(client_factory):
    calls = []
    client = client_factory(resource_handler(calls))
    assert resources.wait_for_resource(client, "networkips", "test-resource")["status"]["state"] == "READY"
    resources.update_resource(client, "networkips", "test-resource", "firewall", {"openPorts": [{"start": 443, "end": 443, "protocol": "TCP"}]})
    resources.update_resource(client, "licenses", "test-resource", "updateAcl", {"added": [], "deleted": []})
    assert json.loads(calls[-1].content) == {"items": [{"id": "test-resource", "added": [], "deleted": []}]}


@pytest.mark.parametrize("ports", [[{"start": 0, "end": 443, "protocol": "TCP"}], [{"start": 443, "end": 1, "protocol": "TCP"}], [{"start": 22, "end": 22, "protocol": "ANY"}]])
def test_bad_firewall_is_rejected(ports):
    with pytest.raises(ValueError):
        resources.validate_firewall({"openPorts": ports})


def test_ssh_public_key_matches_ignoring_comment_and_avoids_duplicates(client_factory, monkeypatch, tmp_path):
    calls = []
    key = {"id": "test-key", "specification": {"title": "Test", "key": KEY.rsplit(" ", 1)[0] + " changed-comment"}}

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"items": [key], "next": None})

    client = client_factory(handler)
    monkeypatch.setattr(ssh_keys.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    path = tmp_path / "key.pub"
    path.write_text(KEY)
    assert ssh_keys.check_ssh_key(client, SETTINGS, path)["state"] == "MATCHED"
    result = ssh_keys.register_public_key(client, "Test", KEY, operation_dir=tmp_path / "operations")
    assert result["already_registered"]
    assert all(request.method == "GET" for request in calls)
    assert not (tmp_path / "operations").exists()


def test_private_key_input_is_rejected_before_http_or_file_read(client_factory, tmp_path, monkeypatch):
    calls = []
    client = client_factory(resource_handler(calls))
    with pytest.raises(ValueError, match="private"):
        ssh_keys.register_public_key(client, "Test", "-----BEGIN OPENSSH PRIVATE KEY-----")
    path = tmp_path / "id_ed25519"
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("Private file must not be read"))
    with pytest.raises(ValueError, match=".pub"):
        ssh_keys.read_public_key(path)
    assert not calls


def test_missing_public_file_is_unverifiable_not_proof_of_missing_agent_key(client_factory, tmp_path):
    settings = Settings(server=SETTINGS.server, token="test", project="test", ssh_config_path=tmp_path / "config")
    client = client_factory(lambda request: pytest.fail("No HTTP required"))
    assert ssh_keys.check_ssh_key(client, settings)["state"] == "UNVERIFIABLE"


@pytest.mark.parametrize("group,namespace,command", [("links", "ingresses", "create"), ("ips", "networkips", "create"), ("licenses", "licenses", "activate")])
def test_create_cli_is_read_only_without_yes(client_factory, monkeypatch, tmp_path, group, namespace, command):
    calls = []
    client = client_factory(resource_handler(calls))
    monkeypatch.setattr(management_cli.Settings, "from_env", lambda: SETTINGS)
    monkeypatch.setattr(management_cli, "UCloudClient", lambda settings: client)
    specification = {"product": PRODUCT}
    if namespace == "ingresses":
        specification["domain"] = "app-test.example.invalid"
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(specification))
    result = CliRunner().invoke(cli.app, [group, command, "--spec", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["preview"] is True
    assert all(request.method == "GET" for request in calls)


@pytest.mark.parametrize("group", ["links", "ips", "licenses", "ssh-keys"])
def test_list_cli_json_is_parseable_and_read_only(client_factory, monkeypatch, group):
    calls = []
    client = client_factory(resource_handler(calls))
    monkeypatch.setattr(management_cli.Settings, "from_env", lambda: SETTINGS)
    monkeypatch.setattr(management_cli, "UCloudClient", lambda settings: client)
    result = CliRunner().invoke(cli.app, [group, "list", "--json"])
    assert result.exit_code == 0, result.output
    assert isinstance(json.loads(result.stdout), list)
    assert all(request.method == "GET" for request in calls)


def compute_entry(product, status):
    return {"product": {"name": product["id"], "cpu": 48, "gpu": 1}, "support": {"product": product, "queueStatus": status}}


def test_availability_is_single_request_and_preserves_exact_candidate_order(client_factory):
    calls = []
    first = {"id": "gpu-nvidia-b200-1-gpu", "category": "gpu-nvidia-b200", "provider": "ucloud"}
    second = {**first, "id": "gpu-nvidia-b200-2-gpu"}
    missing = {**first, "provider": "not-ucloud"}

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"productsByProvider": {"ucloud": [compute_entry(first, "FULL"), compute_entry(second, "AVAILABLE")]}})

    snapshot = check_machine_availability(client_factory(handler), products=[second, first, missing])
    assert len(calls) == 1
    assert calls[0].url.path == "/api/jobs/retrieveProducts"
    assert [machine.product for machine in snapshot.machines] == [second, first, missing]
    assert [machine.queue_status for machine in snapshot.machines] == ["AVAILABLE", "FULL", "UNKNOWN"]
    assert not snapshot.machines[-1].found
    assert json.loads(json.dumps(asdict(snapshot)))["checked_at"].endswith("+00:00")


@pytest.mark.parametrize("product_id,status,expected", [("cpu-amd-zen5-8-vcpu", "AVAILABLE", "AVAILABLE"), ("gpu-nvidia-b200-1-mig.1g", "BUSY", "BUSY"), ("gpu-nvidia-b200-4-gpu", None, "UNKNOWN"), ("gpu-test", "NEW_STATUS", "UNKNOWN")])
def test_availability_cpu_gpu_mig_and_unknown_status(client_factory, product_id, status, expected):
    product = {**PRODUCT, "id": product_id}
    client = client_factory(lambda request: httpx.Response(200, json={"productsByProvider": {PRODUCT["provider"]: [compute_entry(product, status)]}}))
    assert check_machine_availability(client).machines[0].queue_status == expected


def test_availability_errors_do_not_become_empty_success(client_factory):
    client = client_factory(lambda request: httpx.Response(403, text="test-secret"))
    with pytest.raises(resources.ManagementError) as caught:
        check_machine_availability(client)
    assert "test-secret" not in str(caught.value)


def test_live_catalog_cli_filters_by_real_provider_and_category(client_factory, monkeypatch):
    client = client_factory(lambda request: httpx.Response(200, json={"productsByProvider": {PRODUCT["provider"]: [compute_entry(PRODUCT, "AVAILABLE")]}}))
    monkeypatch.setattr(cli, "UCloudClient", lambda settings: client)
    monkeypatch.setattr(cli, "_load_settings", lambda: SETTINGS)
    result = CliRunner().invoke(cli.app, ["catalog", "machines", "--live", "--provider", PRODUCT["provider"], "--category", PRODUCT["category"], "--json"])
    assert result.exit_code == 0, result.output
    assert len(json.loads(result.stdout)["machines"]) == 1


@pytest.mark.parametrize("group,command", [("links", "create"), ("ips", "create"), ("licenses", "activate")])
def test_confirmed_create_cli_records_one_creation(client_factory, monkeypatch, tmp_path, group, command):
    calls = []
    client = client_factory(resource_handler(calls))
    monkeypatch.setattr(management_cli.Settings, "from_env", lambda: SETTINGS)
    monkeypatch.setattr(management_cli, "UCloudClient", lambda settings: client)
    specification = {"product": PRODUCT}
    if group == "links":
        specification["domain"] = "app-test.example.invalid"
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(specification))
    result = CliRunner().invoke(cli.app, [group, command, "--spec", str(path), "--yes", "--operation-dir", str(tmp_path / "operations")])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["id"] == "created-resource"
    assert sum(request.method == "POST" for request in calls) == 1
    assert len(list((tmp_path / "operations").glob("*.json"))) == 1


@pytest.mark.parametrize("yes", [False, True])
def test_delete_and_update_cli_confirmation_guards(client_factory, monkeypatch, tmp_path, yes):
    monkeypatch.setattr(management_cli.Settings, "from_env", lambda: SETTINGS)
    for command in ("delete", "labels", "acl", "firewall"):
        calls = []
        client = client_factory(resource_handler(calls))
        monkeypatch.setattr(management_cli, "UCloudClient", lambda settings: client)
        options = ["ips", command, "test-resource"]
        if command != "delete":
            data = {"openPorts": []} if command == "firewall" else {"added": [], "deleted": []} if command == "acl" else {"purpose": "test"}
            path = tmp_path / f"{command}.json"
            path.write_text(json.dumps(data))
            options += ["--spec", str(path)]
        if yes:
            options += ["--yes"]
        result = CliRunner().invoke(cli.app, options)
        assert result.exit_code == 0, result.output
        assert any(request.method != "GET" for request in calls) is yes


@pytest.mark.parametrize("yes", [False, True])
def test_ssh_registration_and_deletion_cli_confirmation(client_factory, monkeypatch, tmp_path, yes):
    monkeypatch.setattr(management_cli.Settings, "from_env", lambda: SETTINGS)
    monkeypatch.setattr(ssh_keys.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    path = tmp_path / "key.pub"
    path.write_text(KEY)
    for operation in ("register", "delete"):
        calls = []

        def handler(request):
            calls.append(request)
            if request.url.path.endswith("/browse"):
                keys = [] if operation == "register" else [{"id": "test-key", "specification": {"title": "Test", "key": KEY}}]
                return httpx.Response(200, json={"items": keys, "next": None})
            if request.url.path.endswith("/retrieve"):
                return httpx.Response(200, json={"id": "test-key", "specification": {"title": "Test", "key": KEY}})
            return httpx.Response(200, json={"responses": [{"id": "created-key"}]})

        client = client_factory(handler)
        monkeypatch.setattr(management_cli, "UCloudClient", lambda settings: client)
        options = ["ssh-keys", operation]
        options += ["--public-key", str(path), "--title", "Test", "--operation-dir", str(tmp_path / "operations")] if operation == "register" else ["test-key"]
        if yes:
            options += ["--yes"]
        result = CliRunner().invoke(cli.app, options)
        assert result.exit_code == 0, result.output
        assert any(request.method != "GET" for request in calls) is yes
        assert KEY not in result.stdout


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="OpenSSH not installed")
def test_native_public_key_validation_accepts_a_real_wire_format(tmp_path):
    path = tmp_path / "key.pub"
    path.write_text(KEY)
    assert ssh_keys.read_public_key(path) == KEY


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 0])
def test_resource_wait_refuses_unbounded_budget(client_factory, timeout):
    client = client_factory(lambda request: pytest.fail("Invalid budget must fail before HTTP"))
    with pytest.raises(ValueError, match="finite"):
        resources.wait_for_resource(client, "licenses", "test-resource", timeout_seconds=timeout)


def test_resource_readiness_timeout_leaves_resource_for_explicit_cleanup(client_factory):
    calls = []

    def handler(request):
        calls.append(request)
        resource = {"id": "test-resource", "status": {"state": "PREPARING"}}
        return httpx.Response(200, json={"items": [resource], "next": None} if request.url.path.endswith("/browse") else resource)

    client = client_factory(handler)
    with pytest.raises(resources.ManagementError, match="deadline"):
        resources.wait_for_resource(client, "licenses", "test-resource", timeout_seconds=0.001, poll_seconds=0.001)
    assert all(request.method == "GET" for request in calls)


def test_availability_category_collisions_null_status_and_malformed_responses(client_factory):
    other = {**PRODUCT, "category": "other-category"}
    data = {"productsByProvider": {PRODUCT["provider"]: [compute_entry(PRODUCT, "FULL"), compute_entry(other, "AVAILABLE")]}}
    client = client_factory(lambda request: httpx.Response(200, json=data))
    snapshot = check_machine_availability(client, products=[other, PRODUCT])
    assert [machine.queue_status for machine in snapshot.machines] == ["AVAILABLE", "FULL"]
    data["productsByProvider"][PRODUCT["provider"]] = [{"product": {"name": PRODUCT["id"], "category": {"name": PRODUCT["category"]}}, "support": None}]
    assert check_machine_availability(client).machines[0].queue_status == "UNKNOWN"
    data["productsByProvider"][PRODUCT["provider"]] = [None]
    with pytest.raises(resources.ManagementError, match="Malformed"):
        check_machine_availability(client)
