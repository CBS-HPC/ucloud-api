from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ucloud_workflow.cli import app
from ucloud_workflow.client import UCloudClient
from ucloud_workflow.settings import Settings, read_dotenv
from ucloud_workflow.setup import (
    list_projects, list_writable_drives, prepare_storage_directory, storage_directory_path,
    write_setup_env,
)


PROJECT = {"id": "project-one", "specification": {"title": "Example's project", "canConsumeResources": True}, "status": {"archived": False}}
DRIVE = {"id": "drive-one", "specification": {"title": "Shared files"},
         "permissions": {"myself": ["EDIT"]}, "status": {"resolvedSupport": {"support": {"files": {"isReadOnly": False}}}}}
JOB = {"id": "template-one", "owner": {"project": PROJECT["id"]},
       "specification": {"application": {"name": "example-app", "version": "1"}, "resources": [{"type": "file", "path": "/drive-one"}]}}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith("UCLOUD_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("UCLOUD_TOKEN", "setup-secret")
    state = {"calls": [], "projects": [deepcopy(PROJECT)], "drives": [deepcopy(DRIVE)],
             "jobs": [deepcopy(JOB)], "folders": {"/drive-one"}, "override": None}

    def handler(request):
        state["calls"].append(request)
        if state["override"] is not None:
            response = state["override"](request)
            if response is not None:
                return response
        path = request.url.path
        if path == "/api/projects/v2/browse":
            return httpx.Response(200, json={"items": state["projects"]})
        if path == "/api/files/collections/browse":
            return httpx.Response(200, json={"items": state["drives"]})
        if path == "/api/jobs/browse":
            return httpx.Response(200, json={"items": state["jobs"]})
        if path == "/api/jobs/retrieve":
            matches = [job for job in state["jobs"] if job["id"] == request.url.params["id"]]
            return httpx.Response(200, json=matches[0]) if matches else httpx.Response(404)
        if path == "/api/files/retrieve":
            target = request.url.params["id"]
            if target not in state["folders"]:
                return httpx.Response(404)
            return httpx.Response(200, json={"id": target, "status": {"type": "DIRECTORY"}, "permissions": {"myself": ["EDIT"]}})
        if path == "/api/files/browse":
            parent = request.url.params["path"]
            return httpx.Response(200, json={"items": [
                {"id": folder, "status": {"type": "DIRECTORY"}, "permissions": {"myself": ["EDIT"]}}
                for folder in api_folders(state["folders"], parent)
            ]})
        if path == "/api/files/folder" and request.method == "POST":
            payload = json.loads(request.content)
            assert payload["items"][0]["conflictPolicy"] == "REJECT"
            state["folders"].add(payload["items"][0]["id"])
            return httpx.Response(200, json={"responses": [{}]})
        raise AssertionError(f"Unexpected API operation: {request.method} {path}")

    original_httpx_client = httpx.Client

    def initialize(*args, **kwargs):
        return original_httpx_client(*args, **kwargs, transport=httpx.MockTransport(handler), trust_env=False)

    monkeypatch.setattr(httpx, "Client", initialize)
    return state


def setup_client() -> UCloudClient:
    return UCloudClient(Settings(server="https://ucloud.invalid", token="setup-secret", project=PROJECT["id"]))


def api_folders(folders, parent):
    return [folder for folder in folders if folder.rsplit("/", 1)[0] == parent]


def test_setup_with_only_token_creates_default_folder_and_usable_env(api):
    result = CliRunner().invoke(app, ["setup", "--yes"])

    assert result.exit_code == 0, result.output
    assert "setup-secret" not in result.output
    assert "Setup complete" in result.output
    saved = read_dotenv()
    assert saved["UCLOUD_TOKEN"] == "setup-secret"
    assert saved["UCLOUD_PROJECT"] == PROJECT["id"]
    assert saved["UCLOUD_STORAGE_PATH"] == "/drive-one/ucloud-workflow"
    assert saved["UCLOUD_WORK_FOLDER"] == "/work"
    assert saved["UCLOUD_TEMPLATE_JOB_ID"] == JOB["id"]
    assert "/drive-one/ucloud-workflow" in api["folders"]
    discovery_request = api["calls"][0]
    assert discovery_request.url.path == "/api/projects/v2/browse"
    assert "project" not in discovery_request.headers
    assert discovery_request.headers["authorization"] == "Bearer setup-secret"
    assert all(request.headers.get("project") == PROJECT["id"] for request in api["calls"][1:])
    assert [request.url.path for request in api["calls"] if request.method == "POST"] == ["/api/files/folder"]
    settings = Settings.from_env()
    assert settings.storage_path == saved["UCLOUD_STORAGE_PATH"]
    assert settings.template_job_id == JOB["id"]
    assert settings.work_folder == "/work"
    if os.name != "nt":
        assert Path(".env").stat().st_mode & 0o777 == 0o600


def test_setup_cancel_has_no_local_or_remote_writes(api):
    result = CliRunner().invoke(app, ["setup"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Cancelled" in result.output
    assert "setup-secret" not in result.output
    assert not Path(".env").exists()
    assert not any(request.method != "GET" for request in api["calls"])


def test_setup_prompts_for_token_without_echoing_it(api, monkeypatch):
    monkeypatch.delenv("UCLOUD_TOKEN")
    result = CliRunner().invoke(app, ["setup"], input="prompt-secret\ny\n")
    assert result.exit_code == 0, result.output
    assert "prompt-secret" not in result.output
    assert read_dotenv()["UCLOUD_TOKEN"] == "prompt-secret"


def test_noninteractive_setup_requires_token(api, monkeypatch):
    monkeypatch.delenv("UCLOUD_TOKEN")
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert not api["calls"]


@pytest.mark.parametrize("category, option", [("projects", "--project"), ("drives", "--drive-id"), ("jobs", "--template-job-id")])
def test_yes_never_silently_selects_ambiguous_resources(api, category, option):
    second = deepcopy(api[category][0])
    second["id"] = "another-choice"
    api[category].append(second)
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert option in result.output
    assert not Path(".env").exists()
    assert not any(request.method != "GET" for request in api["calls"])


def test_setup_interactively_selects_projects_drives_and_templates(api):
    for category in ("projects", "drives", "jobs"):
        second = deepcopy(api[category][0])
        second["id"] = "another-choice"
        api[category].append(second)
    result = CliRunner().invoke(app, ["setup"], input="1\n1\n1\ny\n")
    assert result.exit_code == 0, result.output
    assert read_dotenv()["UCLOUD_PROJECT"] == PROJECT["id"]


@pytest.mark.parametrize("selection", ["0", "3", "-1"])
def test_interactive_selection_rejects_out_of_range_numbers(api, selection):
    second = deepcopy(PROJECT)
    second["id"] = "another-project"
    api["projects"].append(second)
    result = CliRunner().invoke(app, ["setup"], input=selection + "\n")
    assert result.exit_code == 1
    assert "displayed numbers" in result.output
    assert not Path(".env").exists()
    assert all(request.method == "GET" for request in api["calls"])


def test_explicit_selection_preserves_existing_configuration_and_comments(api):
    Path(".env").write_text('# keep this\nUCLOUD_TOKEN="old-secret"\nUCLOUD_PROJECT="Example\'s project"\n'
                           'UCLOUD_WORK_FOLDER="/work/custom"\nUCLOUD_DEFAULT_SIZE="4-vcpu"\n'
                           'UCLOUD_SSH_CONFIG_PATH="C:\\ssh\\config"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["setup", "--yes", "--drive-id", "drive-one", "--storage-path", "/drive-one/custom/"])
    assert result.exit_code == 0, result.output
    values = read_dotenv()
    assert values["UCLOUD_WORK_FOLDER"] == "/work/custom"
    assert values["UCLOUD_DEFAULT_SIZE"] == "4-vcpu"
    assert values["UCLOUD_SSH_CONFIG_PATH"] == "C:\\ssh\\config"
    assert values["UCLOUD_STORAGE_PATH"] == "/drive-one/custom"
    assert "# keep this" in Path(".env").read_text()
    assert "old-secret" not in Path(".env").read_text()
    assert not {"setup-secret", "old-secret"} & set(result.output.split())


def test_setup_uses_custom_env_file_without_polluting_process_environment(api, monkeypatch):
    monkeypatch.delenv("UCLOUD_TOKEN")
    Path("custom.env").write_text("UCLOUD_TOKEN=custom-secret\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["setup", "--env-file", "custom.env", "--yes"])
    assert result.exit_code == 0, result.output
    assert not Path(".env").exists()
    assert read_dotenv(Path("custom.env"))["UCLOUD_TOKEN"] == "custom-secret"
    assert "UCLOUD_TOKEN" not in os.environ
    assert "custom-secret" not in result.output


def test_existing_folder_is_reused_without_post(api):
    api["folders"].add("/drive-one/ucloud-workflow")
    for _ in range(2):
        result = CliRunner().invoke(app, ["setup", "--yes"])
        assert result.exit_code == 0, result.output
    assert all(request.method == "GET" for request in api["calls"])


def test_no_template_jobs_reports_manual_next_step_but_can_create_folder(api):
    api["jobs"] = []
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 0, result.output
    assert "No reusable template" in result.output
    assert "UCLOUD_TEMPLATE_JOB_ID" not in read_dotenv()


def test_other_project_template_is_rejected_before_writes(api):
    api["jobs"][0]["owner"]["project"] = "other-project"
    result = CliRunner().invoke(app, ["setup", "--yes", "--template-job-id", JOB["id"]])
    assert result.exit_code == 1
    assert "selected project" in result.output
    assert not any(request.method != "GET" for request in api["calls"])


@pytest.mark.parametrize("target", ["/other-drive/folder", "/drive-one/../elsewhere", "/drive-one/./folder", "/drive-one/a//b", "/drive-one", "relative", "/drive-one/a\\b", "/drive-one/a\nb"])
def test_storage_path_validation_rejects_cross_drive_root_and_traversal(target):
    with pytest.raises(ValueError):
        storage_directory_path("drive-one", target)


def test_nested_folders_created_in_parent_order_and_retrieved(api):
    with setup_client() as client:
        assert prepare_storage_directory(client, "/drive-one/parent/child") == ("/drive-one/parent", "/drive-one/parent/child")
        assert all(request.method == "GET" for request in api["calls"])
        prepare_storage_directory(client, "/drive-one/parent/child", create=True)
    posts = [json.loads(request.content)["items"][0]["id"] for request in api["calls"] if request.method == "POST"]
    assert posts == ["/drive-one/parent", "/drive-one/parent/child"]


def test_http_400_missing_folder_requires_successful_parent_listing(api):
    def override(request):
        if request.url.path == "/api/files/retrieve" and request.url.params["id"] not in api["folders"]:
            return httpx.Response(400, text="ambiguous setup-secret")
        return None
    api["override"] = override
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 0, result.output
    parent_reads = [request for request in api["calls"] if request.url.path == "/api/files/browse"]
    assert parent_reads and parent_reads[0].url.params["path"] == "/drive-one"
    assert "ambiguous" not in result.output
    assert "setup-secret" not in result.output


def test_http_400_does_not_create_if_parent_listing_is_forbidden(api):
    def override(request):
        if request.url.path == "/api/files/retrieve" and request.url.params["id"] not in api["folders"]:
            return httpx.Response(400)
        if request.url.path == "/api/files/browse":
            return httpx.Response(403, text="private setup-secret")
        return None
    api["override"] = override
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "setup-secret" not in result.output
    assert not any(request.method == "POST" for request in api["calls"])


@pytest.mark.parametrize("status", [401, 403, 500])
def test_failed_directory_lookup_is_not_treated_as_missing(api, status):
    api["override"] = lambda request: httpx.Response(status, text="private response setup-secret") if request.url.path == "/api/files/retrieve" else None
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "private response" not in result.output
    assert "setup-secret" not in result.output
    assert not any(request.method == "POST" for request in api["calls"])


def test_existing_file_is_never_replaced(api):
    def override(request):
        if request.url.path == "/api/files/retrieve" and request.url.params["id"] == "/drive-one/ucloud-workflow":
            return httpx.Response(200, json={"id": "/drive-one/ucloud-workflow", "status": {"type": "FILE"}})
        return None
    api["override"] = override
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "no files will be replaced" in result.output
    assert not any(request.method == "POST" for request in api["calls"])


def test_explicit_drive_and_storage_path_must_agree(api):
    result = CliRunner().invoke(app, ["setup", "--yes", "--drive-id", "drive-one", "--storage-path", "/other-drive/folder"])
    assert result.exit_code == 1
    assert not any(request.method == "POST" for request in api["calls"])


def test_readonly_drive_is_not_an_eligible_destination(api):
    api["drives"][0]["permissions"]["myself"] = ["READ"]
    result = CliRunner().invoke(app, ["setup", "--yes", "--drive-id", "drive-one"])
    assert result.exit_code == 1
    assert not any(request.method == "POST" for request in api["calls"])


def test_folder_permission_failure_is_not_treated_as_missing(api):
    def override(request):
        if request.url.path == "/api/files/retrieve":
            return httpx.Response(200, json={"id": request.url.params["id"], "status": {"type": "DIRECTORY"}, "permissions": {"myself": ["READ"]}})
        return None
    api["override"] = override
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "write access" in result.output
    assert not any(request.method == "POST" for request in api["calls"])


def test_authentication_failure_is_redacted_before_configuration_is_written(api):
    api["override"] = lambda _request: httpx.Response(401, text="setup-secret private details")
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "setup-secret" not in result.output
    assert "private details" not in result.output
    assert not Path(".env").exists()


def test_malformed_metadata_fails_safely_without_writes(api):
    api["drives"][0]["status"] = "not-an-object"
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "Malformed setup metadata" in result.output
    assert not Path(".env").exists()


@pytest.mark.parametrize("permissions", [{"EDIT": True}, "EDIT", [["EDIT"]]])
def test_malformed_permissions_never_count_as_write_access(api, permissions):
    api["drives"][0]["permissions"]["myself"] = permissions
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "write access could not be verified" in result.output
    assert not any(request.method == "POST" for request in api["calls"])


def test_local_save_failure_keeps_verified_folder_for_reuse(api, monkeypatch):
    import ucloud_workflow.setup as setup_module

    def fail_save(*_args, **_kwargs):
        raise OSError("local lock")
    monkeypatch.setattr(setup_module, "write_setup_env", fail_save)
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "configuration was not saved" in result.output
    assert "/drive-one/ucloud-workflow" in api["folders"]
    assert not Path(".env").exists()
    assert not any(request.method == "DELETE" for request in api["calls"])


def test_folder_create_race_retrieves_and_reuses_existing_directory(api):
    def override(request):
        if request.method == "POST":
            api["folders"].add(json.loads(request.content)["items"][0]["id"])
            return httpx.Response(409)
        return None
    api["override"] = override
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 0, result.output
    assert sum(request.method == "POST" for request in api["calls"]) == 1


@pytest.mark.parametrize("failure", ["timeout", "server", "permission"])
def test_create_failures_are_redacted_not_retried_and_do_not_save_token(api, failure):
    def override(request):
        if request.method == "POST":
            if failure == "timeout":
                raise httpx.ReadTimeout("private setup-secret", request=request)
            return httpx.Response(503 if failure == "server" else 403, text="private setup-secret")
        return None
    api["override"] = override
    result = CliRunner().invoke(app, ["setup", "--yes"])
    assert result.exit_code == 1
    assert "private" not in result.output
    assert "setup-secret" not in result.output
    assert sum(request.method == "POST" for request in api["calls"]) == 1
    assert not Path(".env").exists()
    if failure != "permission":
        assert "outcome is unknown" in result.output


def test_discovery_paginates_filters_archived_projects_and_readonly_drives(api):
    archived = deepcopy(PROJECT)
    archived["status"]["archived"] = True
    allocation_only = deepcopy(PROJECT)
    allocation_only["specification"]["canConsumeResources"] = False
    readonly = deepcopy(DRIVE)
    readonly["status"]["resolvedSupport"]["support"]["files"]["isReadOnly"] = True
    unverified = deepcopy(DRIVE)
    unverified["status"] = {}
    no_write = deepcopy(DRIVE)
    no_write["permissions"]["myself"] = ["READ"]
    api["drives"].extend([readonly, unverified, no_write])

    def override(request):
        if request.url.path == "/api/projects/v2/browse":
            if "next" not in request.url.params:
                return httpx.Response(200, json={"items": [archived, allocation_only], "next": "page-two"})
            assert request.url.params["next"] == "page-two"
            return httpx.Response(200, json={"items": [PROJECT], "next": None})
        return None
    api["override"] = override
    with setup_client() as client:
        assert list_projects(client) == [PROJECT]
        assert list_writable_drives(client) == [DRIVE]
    assert api["calls"][-1].url.params["includeSupport"] == "true"


def test_job_browse_pagination_forwards_cursor(api):
    with setup_client() as client:
        client.browse_jobs(next_page="next-jobs")
    assert api["calls"][-1].url.params["next"] == "next-jobs"


@pytest.mark.parametrize("server", ["http://example.invalid", "https://user:pass@example.invalid", "https://example.invalid?token=hidden", "https://example.invalid/api", "https://example.invalid#fragment"])
def test_setup_rejects_unsafe_server_before_transmitting_token(api, server):
    result = CliRunner().invoke(app, ["setup", "--yes", "--server", server])
    assert result.exit_code == 1
    assert not api["calls"]


def test_environment_writer_preserves_unrelated_lines_and_roundtrips_quotes(tmp_path):
    path = tmp_path / "settings.env"
    original = '# hello\nUCLOUD_TOKEN=old\nUCLOUD_TOKEN=duplicate\nOTHER="unchanged"\n'
    path.write_text(original, encoding="utf-8")
    write_setup_env(path, {"UCLOUD_TOKEN": "replacement", "UCLOUD_STORAGE_PATH": '/drive/a "quoted" folder'}, original=original)
    assert read_dotenv(path)["UCLOUD_STORAGE_PATH"] == '/drive/a "quoted" folder'
    assert read_dotenv(path)["OTHER"] == "unchanged"
    assert path.read_text().count("UCLOUD_TOKEN=") == 1
    assert path.read_text().startswith("# hello\n")
    assert not list(tmp_path.glob(".ucloud-setup-*"))


def test_environment_writer_refuses_concurrent_change(tmp_path):
    path = tmp_path / ".env"
    path.write_text("OTHER=new\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        write_setup_env(path, {"UCLOUD_TOKEN": "test"}, original="OTHER=old\n")
    assert path.read_text() == "OTHER=new\n"


def test_environment_writer_cleans_temp_file_on_replace_failure(tmp_path, monkeypatch):
    import ucloud_workflow.setup as setup_module

    path = tmp_path / ".env"
    path.write_text("OTHER=keep\n", encoding="utf-8")
    monkeypatch.setattr(setup_module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError):
        write_setup_env(path, {"UCLOUD_TOKEN": "test"}, original="OTHER=keep\n")
    assert path.read_text() == "OTHER=keep\n"
    assert not list(tmp_path.glob(".ucloud-setup-*"))


def test_environment_symlink_is_refused_without_touching_target(tmp_path):
    target = tmp_path / "target.env"
    target.write_text("OTHER=keep\n", encoding="utf-8")
    link = tmp_path / ".env"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    with pytest.raises(ValueError, match="symlink"):
        write_setup_env(link, {"UCLOUD_TOKEN": "test"}, original="OTHER=keep\n")
    assert target.read_text() == "OTHER=keep\n"
