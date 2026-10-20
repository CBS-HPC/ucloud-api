from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from typer.testing import CliRunner

from ucloud_workflow import availability, cli, job_resources, resources
from ucloud_workflow.client import UCloudAPIError, UCloudClient
from ucloud_workflow.jobs import submit_job_from_latest_template
from ucloud_workflow.resources import ManagementError
from ucloud_workflow.settings import Settings


COMPUTE = {"id": "compute-test", "category": "compute", "provider": "test-provider"}
RESOURCE = {"id": "resource-test", "category": "resource", "provider": "test-provider"}
SETTINGS = Settings(server="https://ucloud.invalid", token="test-token", project="test-workspace")


class FakeClient:
    _validate_resource_namespace = staticmethod(UCloudClient._validate_resource_namespace)

    def __init__(self):
        self.settings = SETTINGS
        self.application = {
            "metadata": {"name": "test-app", "version": "1"},
            "invocation": {"allowPublicLink": True, "allowPublicIp": True,
                           "parameters": [{"name": "seat", "type": "license_server"}],
                           "tool": {"tool": {"description": {"backend": "DOCKER"}}}},
        }
        self.template = {
            "specification": {"application": {"name": "test-app", "version": "1"}, "product": COMPUTE,
                              "parameters": {"keep": {"type": "text", "value": "unchanged"}},
                              "resources": [{"type": "file", "path": "/test/input"}, {"type": "ingress", "id": "template-link"}],
                              "replicas": 1},
            "status": {"resolvedApplication": self.application},
        }
        self.resources = {namespace: {"reused": self.resource("reused")} for namespace in ("ingresses", "networkips", "licenses")}
        self.events = []
        self.submitted = None
        self.states = ["RUNNING"]
        self.submit_error = None
        self.terminate_error = None
        self.delete_error = None
        self.create_error = None
        self.bound_after_submit = False
        self.queue_status = "AVAILABLE"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def resource(self, identifier):
        return {"id": identifier, "specification": {"product": RESOURCE}, "status": {"state": "READY", "boundTo": None}}

    def retrieve_job(self, identifier, **kwargs):
        self.events.append(("retrieve_job", identifier, kwargs))
        if identifier == "template":
            return deepcopy(self.template)
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"status": {"state": state}}

    def browse_jobs(self, **kwargs):
        self.events.append(("browse_jobs", kwargs))
        return {"items": [deepcopy(self.template)]}

    def retrieve_compute_products(self):
        self.events.append(("compute_products",))
        return {"productsByProvider": {"test-provider": [{"product": {}, "support": {
            "product": COMPUTE, "docker": {"enabled": True, "web": True}, "queueStatus": self.queue_status,
        }}]}}

    def browse_resources(self, namespace, **kwargs):
        return {"items": list(self.resources[namespace].values())}

    def retrieve_resource(self, namespace, identifier):
        return deepcopy(self.resources[namespace][identifier])

    def retrieve_resource_products(self, namespace):
        return {"productsByProvider": {"test-provider": [{"product": {}, "support": {
            "product": RESOURCE, "domainPrefix": "", "domainSuffix": ".example.invalid", "firewall": {"enabled": True},
        }}]}}

    def create_resource(self, namespace, specification):
        self.events.append(("create", namespace))
        if self.create_error:
            raise self.create_error
        identifier = f"created-{namespace}"
        self.resources[namespace][identifier] = self.resource(identifier)
        return {"responses": [{"id": identifier}]}

    def delete_resource(self, namespace, identifier):
        self.events.append(("delete", namespace, identifier))
        if self.delete_error:
            raise self.delete_error
        del self.resources[namespace][identifier]
        return {}

    def submit_job(self, specification):
        self.events.append(("submit",))
        if self.submit_error:
            raise self.submit_error
        self.submitted = deepcopy(specification)
        if self.bound_after_submit:
            for resources in self.resources.values():
                for resource in resources.values():
                    resource["status"]["boundTo"] = ["submitted"]
        return {"responses": [{"id": "submitted"}]}

    def terminate_job(self, identifier):
        self.events.append(("terminate", identifier))
        if self.terminate_error:
            raise self.terminate_error
        return {}


def test_explicit_job_resources_preserve_template_and_use_correct_value_types():
    client = FakeClient()
    original = deepcopy(client.template)
    result = submit_job_from_latest_template(
        client, hours=1, template_job_id="template",
        resource_selection={"links": ["reused", "reused"], "ips": ["reused"], "licenses": {"seat": "reused"}},
    )
    assert result.product_id == COMPUTE["id"]
    assert client.submitted["resources"] == [*original["specification"]["resources"], {"type": "ingress", "id": "reused"}, {"type": "network", "id": "reused"}]
    assert client.submitted["parameters"] == {"keep": {"type": "text", "value": "unchanged"}, "seat": {"type": "license_server", "id": "reused"}}
    assert client.template == original
    assert client.events[0][2]["include_application"] is True


def test_resource_overrides_can_resolve_latest_template_with_application():
    client = FakeClient()
    submit_job_from_latest_template(client, hours=1, resource_selection={"links": ["reused"]})
    assert client.events[0][0] == "browse_jobs"
    assert client.events[0][1]["include_application"] is True


@pytest.mark.parametrize("problem", ["missing-app", "wrong-app", "disabled-link", "disabled-ip", "wrong-license-name", "wrong-provider", "not-ready", "bound", "unknown-binding", "not-in-workspace", "unsupported-backend"])
def test_job_resources_reject_unsafe_selection_without_submission(problem):
    client = FakeClient()
    selection = {"links": ["reused"], "ips": ["reused"], "licenses": {"seat": "reused"}}
    if problem == "missing-app":
        client.template["status"] = {}
    elif problem == "wrong-app":
        client.application["metadata"]["version"] = "other"
    elif problem == "disabled-link":
        client.application["invocation"]["allowPublicLink"] = False
    elif problem == "disabled-ip":
        client.application["invocation"]["allowPublicIp"] = False
    elif problem == "wrong-license-name":
        selection["licenses"] = {"not-a-license": "reused"}
    elif problem == "wrong-provider":
        client.resources["ingresses"]["reused"]["specification"] = {"product": {**RESOURCE, "provider": "other"}}
    elif problem == "not-ready":
        client.resources["ingresses"]["reused"]["status"]["state"] = "PREPARING"
    elif problem == "bound":
        client.resources["ingresses"]["reused"]["status"]["boundTo"] = ["other"]
    elif problem == "unknown-binding":
        del client.resources["ingresses"]["reused"]["status"]["boundTo"]
    elif problem == "not-in-workspace":
        client.resources["ingresses"] = {}
    else:
        client.application["invocation"]["tool"]["tool"]["description"]["backend"] = "UNRECOGNIZED"
    with pytest.raises(ManagementError):
        submit_job_from_latest_template(client, hours=1, template_job_id="template", resource_selection=selection)
    assert not any(event[0] == "submit" for event in client.events)


@pytest.mark.parametrize("value", [{"ssh": ["key"]}, {"links": "id"}, {"licenses": ["id"]}, {"ips": [None]}, {"licenses": {"": "id"}}])
def test_selection_validation(value):
    with pytest.raises(ValueError):
        job_resources.resource_selection(value)


def test_managed_run_only_deletes_new_resources_and_stops_owned_job(tmp_path):
    client = FakeClient()
    requests = [job_resources.RunResourceRequest("ingresses", {"product": RESOURCE, "domain": "test.example.invalid"}),
                job_resources.RunResourceRequest("networkips", {"product": RESOURCE}),
                job_resources.RunResourceRequest("licenses", {"product": RESOURCE}, "seat")]
    result = job_resources.run_with_job_resources(
        client, lambda launch: launch.product_id, requests=requests, existing={"links": ["reused"]},
        template_job_id="template", hours=1, operation_dir=tmp_path,
    )
    assert result.value == COMPUTE["id"] and result.cleanup_complete
    record = json.loads(result.operation_record.read_text())
    assert record["cleanup_complete"] and record["job_termination"] == "requested"
    assert [entry["ownership"] for entry in record["resources"]] == ["reused", "created", "created", "created"]
    assert [(event[1], event[2]) for event in client.events if event[0] == "delete"] == [
        ("licenses", "created-licenses"), ("networkips", "created-networkips"), ("ingresses", "created-ingresses"),
    ]
    assert all("reused" in resources for resources in client.resources.values())
    terminate_index = next(index for index, event in enumerate(client.events) if event[0] == "terminate")
    assert all(index > terminate_index for index, event in enumerate(client.events) if event[0] == "delete")


@pytest.mark.parametrize("failure", ["callback", "termination", "delete", "bound", "submit-unknown", "submit-rejected", "create-unknown"])
def test_managed_run_cleanup_failures_and_unknown_outcomes(tmp_path, failure):
    client = FakeClient()
    original = RuntimeError("callback failed")
    if failure == "termination":
        client.terminate_error = UCloudAPIError("sensitive", status_code=503)
    elif failure == "delete":
        client.delete_error = UCloudAPIError("sensitive", status_code=503)
    elif failure == "bound":
        client.bound_after_submit = True
    elif failure == "submit-unknown":
        client.submit_error = httpx.ReadTimeout("sensitive")
    elif failure == "submit-rejected":
        client.submit_error = UCloudAPIError("sensitive", status_code=400)
    elif failure == "create-unknown":
        client.create_error = httpx.ReadTimeout("sensitive")

    def callback(_launch):
        raise original

    with pytest.raises(RuntimeError) as caught:
        job_resources.run_with_job_resources(
            client, callback, requests=[job_resources.RunResourceRequest("networkips", {"product": RESOURCE})],
            template_job_id="template", hours=1, operation_dir=tmp_path,
        )
    if failure in {"callback", "termination", "delete", "bound"}:
        assert caught.value is original
    assert "sensitive" not in str(caught.value)
    record = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    assert record["cleanup_complete"] is (failure in {"callback", "submit-rejected"})
    if failure == "submit-unknown":
        assert record["phase"] == "submission_unknown"
        assert not any(event[0] in {"delete", "terminate"} for event in client.events)
    if failure in {"termination", "bound", "create-unknown"}:
        assert not any(event[0] == "delete" for event in client.events)


def test_managed_run_checks_all_specs_and_app_before_any_write(tmp_path):
    client = FakeClient()
    client.application["invocation"]["allowPublicIp"] = False
    with pytest.raises(ManagementError):
        job_resources.run_with_job_resources(
            client, lambda _: None, requests=[job_resources.RunResourceRequest("networkips", {"product": RESOURCE})],
            template_job_id="template", hours=1, operation_dir=tmp_path,
        )
    assert not any(event[0] in {"create", "submit", "delete"} for event in client.events)
    assert not list(tmp_path.iterdir())


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(availability.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(availability.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    return now


@pytest.mark.parametrize("status,allow_busy,submitted", [("AVAILABLE", False, True), ("BUSY", False, False), ("BUSY", True, True), ("FULL", True, False), ("UNKNOWN", True, False)])
def test_immediate_start_status_policy(clock, status, allow_busy, submitted):
    client = FakeClient()
    client.queue_status = status
    if submitted:
        result = availability.submit_immediate_job(client, products=[COMPUTE], hours=1, template_job_id="template", allow_busy=allow_busy)
        assert result.launch.product_id == COMPUTE["id"]
        assert not any(event[0] == "terminate" for event in client.events)
    else:
        with pytest.raises(ManagementError, match="no job was submitted"):
            availability.submit_immediate_job(client, products=[COMPUTE], hours=1, template_job_id="template", allow_busy=allow_busy)
        assert not any(event[0] == "submit" for event in client.events)
    assert sum(event[0] == "compute_products" for event in client.events) == 1


def test_immediate_start_never_falls_back_to_unapproved_machine(clock):
    client = FakeClient()
    with pytest.raises(ManagementError):
        availability.submit_immediate_job(client, products=[{**COMPUTE, "id": "not-advertised"}], hours=1)
    assert not any(event[0] == "submit" for event in client.events)


@pytest.mark.parametrize("termination_fails", [False, True])
def test_immediate_start_deadline_terminates_once_and_reports_recovery(clock, termination_fails):
    client = FakeClient()
    client.states = ["IN_QUEUE"]
    if termination_fails:
        client.terminate_error = UCloudAPIError("sensitive", status_code=503)
    with pytest.raises(availability.ImmediateStartError) as caught:
        availability.submit_immediate_job(client, products=[COMPUTE], hours=1, startup_timeout_seconds=3, poll_interval_seconds=2)
    assert caught.value.termination_succeeded is not termination_fails
    assert "submitted" not in str(caught.value) and "sensitive" not in str(caught.value)
    assert sum(event[0] == "submit" for event in client.events) == 1
    assert sum(event[0] == "terminate" for event in client.events) == 1
    assert clock[0] == 3
    assert [event[2]["request_timeout"] for event in client.events if event[0] == "retrieve_job"] == [3, 1]


def test_immediate_start_pending_then_running_does_not_require_ssh(clock):
    client = FakeClient()
    client.states = ["IN_QUEUE", "RUNNING"]
    assert availability.submit_immediate_job(client, products=[COMPUTE], hours=1).launch.job_id == "submitted"


@pytest.mark.parametrize("budget", [0, float("nan"), float("inf")])
def test_immediate_start_budget_validation_precedes_api(budget):
    client = FakeClient()
    with pytest.raises(ValueError):
        availability.submit_immediate_job(client, products=[COMPUTE], hours=1, startup_timeout_seconds=budget)
    assert not client.events


def test_new_job_metadata_flags_and_request_timeout():
    calls = []
    with UCloudClient(SETTINGS) as client:
        client._client.close()
        client._client = httpx.Client(base_url=SETTINGS.server, transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(200, json={}))[1]))
        client.retrieve_job("template", include_application=True, request_timeout=0.25)
        client.browse_jobs(include_application=True)
    assert calls[0].url.params["includeApplication"] == "true"
    assert calls[0].url.params["includeParameters"] == "true"
    assert calls[0].extensions["timeout"]["read"] == 0.25
    assert calls[1].url.params["includeApplication"] == "true"


@pytest.mark.parametrize("confirmed", [False, True])
def test_immediate_cli_preview_and_confirmation(monkeypatch, tmp_path, clock, confirmed):
    client = FakeClient()
    monkeypatch.setattr(cli, "_load_settings", lambda: SETTINGS)
    monkeypatch.setattr(cli, "UCloudClient", lambda _: client)
    file = tmp_path / "candidates.json"
    file.write_text(json.dumps([COMPUTE]))
    result = CliRunner().invoke(cli.app, ["jobs", "submit-immediate", "--candidates", str(file), *(["--yes"] if confirmed else [])])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert any(event[0] == "submit" for event in client.events) is confirmed
    assert data.get("preview") is (None if confirmed else True)


def test_job_submit_cli_forwards_resource_file(monkeypatch, tmp_path):
    captured = {}
    client = FakeClient()
    monkeypatch.setattr(cli, "_load_settings", lambda **_: SETTINGS)
    monkeypatch.setattr(cli, "UCloudClient", lambda _: client)
    monkeypatch.setattr(cli, "submit_job_from_latest_template", lambda *_, **kwargs: (captured.update(kwargs), SimpleNamespace(job_id="test", job_url="test"))[1])
    file = tmp_path / "resources.json"
    file.write_text(json.dumps({"links": ["reused"]}))
    result = CliRunner().invoke(cli.app, ["jobs", "submit", "--resources", str(file)])
    assert result.exit_code == 0, result.output
    assert captured["resource_selection"] == {"links": ["reused"]}


def test_create_journal_failure_preserves_confirmed_id_for_reconciliation(monkeypatch, tmp_path):
    original_write = resources.write_operation
    writes = []

    def fail_final_write(path, record):
        writes.append(deepcopy(record))
        if len(writes) > 1:
            raise OSError("disk unavailable")
        original_write(path, record)

    monkeypatch.setattr(resources, "write_operation", fail_final_write)
    with pytest.raises(resources.CreateOutcomeUnknownError) as caught:
        resources.recorded_create(lambda: {"responses": [{"id": "confirmed-resource"}]}, namespace="networkips", project="test", operation_dir=tmp_path)
    assert caught.value.resource_id == "confirmed-resource"
    assert caught.value.operation_record.is_file()
    assert "confirmed-resource" not in str(caught.value)


def test_interrupted_create_keeps_recovery_record_and_original_interrupt(tmp_path):
    client = FakeClient()
    original = KeyboardInterrupt()
    client.create_error = original
    with pytest.raises(KeyboardInterrupt) as caught:
        job_resources.run_with_job_resources(
            client, lambda _: None, requests=[job_resources.RunResourceRequest("networkips", {"product": RESOURCE})],
            hours=1, operation_dir=tmp_path,
        )
    assert caught.value is original
    record = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    assert record["unknown_creation"] and not record["cleanup_complete"]
    assert not any(event[0] in {"submit", "delete"} for event in client.events)


def test_partial_provisioning_cleans_known_ids_but_not_ambiguous_create(tmp_path):
    client = FakeClient()
    original_create = client.create_resource

    def create(namespace, specification):
        if namespace == "networkips":
            client.create_error = httpx.ReadTimeout("sensitive")
        return original_create(namespace, specification)

    client.create_resource = create
    requests = [job_resources.RunResourceRequest("ingresses", {"product": RESOURCE, "domain": "test.example.invalid"}),
                job_resources.RunResourceRequest("networkips", {"product": RESOURCE})]
    with pytest.raises(resources.CreateOutcomeUnknownError):
        job_resources.run_with_job_resources(client, lambda _: None, requests=requests, hours=1, operation_dir=tmp_path)
    assert [event for event in client.events if event[0] == "delete"] == [("delete", "ingresses", "created-ingresses")]
    record = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    assert record["uncertain_creation"]["namespace"] == "networkips"
    assert not record["cleanup_complete"]


def test_known_create_rejection_does_not_claim_an_unknown_allocation(tmp_path):
    client = FakeClient()
    client.create_error = UCloudAPIError("sensitive", status_code=403)
    with pytest.raises(ManagementError, match="rejected"):
        job_resources.run_with_job_resources(
            client, lambda _: None, requests=[job_resources.RunResourceRequest("networkips", {"product": RESOURCE})], hours=1, operation_dir=tmp_path,
        )
    record = json.loads(next(tmp_path.glob("run-*.json")).read_text())
    assert record["cleanup_complete"] and not record.get("unknown_creation")
    assert not any(event[0] in {"submit", "delete", "terminate"} for event in client.events)


def test_resource_readiness_failure_cleans_known_owned_id_before_submission(monkeypatch, tmp_path):
    client = FakeClient()

    def fail_wait(*_args, **_kwargs):
        raise ManagementError("Readiness deadline exceeded")

    monkeypatch.setattr(job_resources, "wait_for_resource", fail_wait)
    with pytest.raises(ManagementError, match="deadline"):
        job_resources.run_with_job_resources(
            client, lambda _: None, requests=[job_resources.RunResourceRequest("networkips", {"product": RESOURCE})], hours=1, operation_dir=tmp_path,
        )
    assert not any(event[0] == "submit" for event in client.events)
    assert ("delete", "networkips", "created-networkips") in client.events


def test_successful_callback_reports_incomplete_cleanup_without_deleting_bound_resources(tmp_path):
    client = FakeClient()
    client.bound_after_submit = True
    result = job_resources.run_with_job_resources(
        client, lambda _: "completed", requests=[job_resources.RunResourceRequest("networkips", {"product": RESOURCE})], hours=1, operation_dir=tmp_path,
    )
    assert result.value == "completed" and not result.cleanup_complete
    record = json.loads(result.operation_record.read_text())
    assert record["resources"][0]["cleanup"] == "incomplete"
    assert not any(event[0] == "delete" for event in client.events)


def test_account_ssh_keys_are_not_run_owned_resources(tmp_path):
    client = FakeClient()
    with pytest.raises(ValueError, match="Only links"):
        job_resources.run_with_job_resources(
            client, lambda _: None, requests=[job_resources.RunResourceRequest("ssh", {})], hours=1, operation_dir=tmp_path,
        )
    assert not any(event[0] in {"create", "submit", "delete"} for event in client.events)


@pytest.mark.parametrize("failure", ["ended", "read-error", "late-running", "interrupted"])
def test_immediate_start_errors_terminate_without_claiming_script_completion(clock, failure):
    client = FakeClient()
    if failure == "ended":
        client.states = ["SUCCESS"]
    else:
        def retrieve(_identifier, **kwargs):
            if failure == "read-error":
                raise httpx.ReadTimeout("sensitive")
            if failure == "interrupted":
                raise KeyboardInterrupt
            clock[0] = 10
            return {"status": {"state": "RUNNING"}}

        client.retrieve_job = retrieve
    expected = KeyboardInterrupt if failure == "interrupted" else availability.ImmediateStartError
    with pytest.raises(expected):
        availability.submit_immediate_job(client, products=[COMPUTE], hours=1, startup_timeout_seconds=3)
    assert ("terminate", "submitted") in client.events


def test_immediate_choice_honors_caller_order_and_busy_opt_in():
    first = availability.MachineAvailability({**COMPUTE, "id": "preferred"}, "BUSY", True, {})
    second = availability.MachineAvailability(COMPUTE, "AVAILABLE", True, {})
    snapshot = availability.AvailabilitySnapshot("test-time", (first, second))
    assert availability.choose_available_machine(snapshot) is second
    assert availability.choose_available_machine(snapshot, allow_busy=True) is first


def test_managed_run_can_disable_ssh_for_web_only_application(tmp_path):
    client = FakeClient()
    result = job_resources.run_with_job_resources(client, lambda _: True, hours=1, ssh_enabled=False, operation_dir=tmp_path)
    assert result.cleanup_complete and client.submitted["sshEnabled"] is False


def test_immediate_start_can_disable_ssh_for_web_only_application(clock):
    client = FakeClient()
    result = availability.submit_immediate_job(client, products=[COMPUTE], hours=1, ssh_enabled=False)
    assert result.launch.job_id == "submitted" and client.submitted["sshEnabled"] is False


@pytest.mark.parametrize("command", ["submit", "submit-immediate"])
def test_job_cli_allows_explicitly_disabling_ssh(monkeypatch, tmp_path, clock, command):
    client = FakeClient()
    monkeypatch.setattr(cli, "_load_settings", lambda **_: SETTINGS)
    monkeypatch.setattr(cli, "UCloudClient", lambda _: client)
    options = ["jobs", command, "--no-ssh"]
    if command == "submit-immediate":
        file = tmp_path / "candidates.json"
        file.write_text(json.dumps([COMPUTE]))
        options += ["--candidates", str(file), "--yes"]
    else:
        options += ["--product-id", COMPUTE["id"], "--product-category", COMPUTE["category"], "--product-provider", COMPUTE["provider"]]
    result = CliRunner().invoke(cli.app, options)
    assert result.exit_code == 0, result.output
    assert client.submitted["sshEnabled"] is False
