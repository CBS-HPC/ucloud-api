from ucloud_workflow.jobs import (
    build_cpu_product_id,
    build_job_specification,
    build_file_resource,
    clean_specification,
    extract_ssh_command,
    parse_ssh_command,
    submit_job_from_latest_template,
    template_job_specification,
)


def test_clean_specification_removes_read_only_fields() -> None:
    spec = {
        "resolvedProduct": {"id": "old"},
        "parameters": [{"name": "foo", "readOnly": True}, {"name": "bar"}],
    }

    cleaned = clean_specification(spec)

    assert "resolvedProduct" not in cleaned
    assert cleaned["parameters"][0]["name"] == "foo"
    assert "readOnly" not in cleaned["parameters"][0]


def test_build_job_specification_rewrites_product_and_time_allocation() -> None:
    template = {"parameters": []}

    spec = build_job_specification(template, size="128-vcpu", hours=3, name="demo")

    assert spec["product"]["id"] == build_cpu_product_id("128-vcpu")
    assert spec["timeAllocation"]["hours"] == 3
    assert spec["name"] == "demo"


def test_build_job_specification_adds_mount_resources() -> None:
    template = {"parameters": [], "resources": [{"type": "file", "path": "/123/existing", "readOnly": False}]}

    spec = build_job_specification(
        template,
        size="128-vcpu",
        hours=3,
        mounts=["/123/shared-input"],
        read_only_mounts=["/123/reference-data"],
    )

    assert spec["resources"] == [
        {"type": "file", "path": "/123/existing", "readOnly": False},
        {"path": "/123/shared-input", "readOnly": False, "type": "file"},
        {"path": "/123/reference-data", "readOnly": True, "type": "file"},
    ]


def test_build_job_specification_preserves_template_resources_without_mount_override() -> None:
    template = {"parameters": [], "resources": [{"type": "file", "path": "/8983017/moody_agent", "readOnly": False}]}

    spec = build_job_specification(template, size="128-vcpu", hours=3)

    assert spec["resources"] == [{"type": "file", "path": "/8983017/moody_agent", "readOnly": False}]


def test_build_file_resource_rejects_non_ucloud_paths() -> None:
    try:
        build_file_resource("relative/path")
    except ValueError as exc:
        assert "absolute UCloud paths" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_extract_ssh_command_finds_latest_command() -> None:
    job = {
        "updates": [
            {"status": "starting"},
            {"status": "ssh ucloud@host.example -p 12345"},
        ]
    }

    assert extract_ssh_command(job) == "ssh ucloud@host.example -p 12345"


def test_parse_ssh_command_splits_user_host_port() -> None:
    assert parse_ssh_command("ssh ucloud@host.example -p 2222") == (
        "ucloud",
        "host.example",
        "2222",
    )


def test_template_job_specification_uses_explicit_job_id() -> None:
    class DummyClient:
        def retrieve_job(self, job_id: str, *, include_updates: bool = True):
            assert job_id == "job-abc123"
            assert include_updates is False
            return {"specification": {"parameters": []}}

    spec = template_job_specification(DummyClient(), template_job_id="job-abc123")

    assert spec["parameters"] == []


def test_submit_job_from_latest_template_uses_template_job_id() -> None:
    class DummyClient:
        def __init__(self) -> None:
            self.settings = type("Settings", (), {"server": "https://cloud.sdu.dk"})()

        def retrieve_job(self, job_id: str, *, include_updates: bool = True):
            assert job_id == "job-abc123"
            assert include_updates is False
            return {"specification": {"parameters": []}}

        def submit_job(self, specification):
            self.specification = specification
            return {"responses": [{"id": "job-new123"}]}

    client = DummyClient()
    result = submit_job_from_latest_template(
        client,
        size="128-vcpu",
        hours=2,
        template_job_id="job-abc123",
    )

    assert result.job_id == "job-new123"
    assert client.specification["sshEnabled"] is True
    assert result.product_id == build_cpu_product_id("128-vcpu")
