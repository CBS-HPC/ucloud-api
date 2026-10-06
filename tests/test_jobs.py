from pathlib import Path

import pytest

from ucloud_workflow.jobs import (
    build_cpu_product_id,
    build_job_specification,
    build_file_resource,
    clean_specification,
    extract_ssh_command,
    parse_ssh_command,
    submit_job_from_latest_template,
    template_job_specification,
    update_ssh_config,
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


def test_build_job_specification_uses_explicit_gpu_product() -> None:
    product = {"id": "gpu-nvidia-b200-1-gpu", "category": "gpu-nvidia-b200", "provider": "ucloud"}
    template = {"product": {"id": "cpu-amd-zen5-8-vcpu", "category": "cpu-amd-zen5", "provider": "ucloud"}}

    specification = build_job_specification(template, product=product, hours=1)

    assert specification["product"] == product
    assert template["product"]["id"] == "cpu-amd-zen5-8-vcpu"


def test_build_job_specification_preserves_explicit_category_and_provider() -> None:
    product = {"id": "gpu-test", "category": "custom-gpu", "provider": "custom-provider"}

    specification = build_job_specification({}, product=product, hours=1)

    assert specification["product"] == product


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


def test_update_ssh_config_writes_explicit_identity_files(tmp_path) -> None:
    config_path = tmp_path / "ssh" / "config"
    identity_file = tmp_path / "keys" / "id_ed25519"

    update_ssh_config(
        "ssh ucloud@host.example -p 2222",
        alias="ucloud",
        config_path=config_path,
        identity_files=[identity_file],
    )

    config_text = config_path.read_text(encoding="utf-8")
    assert f'IdentityFile "{identity_file.as_posix()}"' in config_text
    assert "IdentitiesOnly" not in config_text


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


@pytest.mark.parametrize("product_id", ["gpu-nvidia-b200-1-gpu", "gpu-nvidia-b200-1-mig.1g"])
@pytest.mark.parametrize("retain_template_product", [False, True])
def test_submit_gpu_job_preserves_template_and_returns_selected_product(
    product_id: str,
    retain_template_product: bool,
) -> None:
    product = {"id": product_id, "category": "gpu-nvidia-b200", "provider": "ucloud"}
    template = {
        "product": product,
        "application": {"name": "gpu-test-app", "version": "1.0"},
        "parameters": {"input": {"type": "file", "path": "/drive/input"}, "count": {"value": 1}},
        "resources": [
            {"type": "file", "path": "/drive/work", "readOnly": False},
            {"type": "ingress", "id": "test-link"},
            {"type": "license", "id": "test-license"},
        ],
        "replicas": 1,
    }

    class DummyClient:
        settings = type("Settings", (), {"server": "https://cloud.sdu.dk"})()

        def retrieve_job(self, job_id: str, *, include_updates: bool = True):
            return {"specification": template}

        def submit_job(self, specification):
            self.specification = specification
            return {"responses": [{"id": "new-test-job"}]}

    client = DummyClient()
    result = submit_job_from_latest_template(
        client,
        hours=1,
        product=None if retain_template_product else product,
        template_job_id="test-template",
    )

    assert result.product_id == product_id
    assert client.specification["product"] == product
    for field in ("application", "parameters", "resources", "replicas"):
        assert client.specification[field] == template[field]
    client.specification["parameters"]["count"]["value"] = 2
    assert template["parameters"]["count"]["value"] == 1


def test_build_job_specification_merges_mounts_without_losing_public_links() -> None:
    product = {"id": "gpu-nvidia-b200-1-gpu", "category": "gpu-nvidia-b200", "provider": "ucloud"}
    template = {"product": product, "resources": [{"type": "ingress", "id": "test-link"}]}

    specification = build_job_specification(template, hours=1, mounts=["/drive/work"])

    assert specification["resources"] == [
        {"type": "ingress", "id": "test-link"},
        {"type": "file", "path": "/drive/work", "readOnly": False},
    ]
    assert template["resources"] == [{"type": "ingress", "id": "test-link"}]


def test_build_job_specification_rejects_conflicting_size_and_product() -> None:
    product = {"id": "gpu-nvidia-b200-1-gpu", "category": "gpu-nvidia-b200", "provider": "ucloud"}

    with pytest.raises(ValueError, match="either CPU size or an explicit product"):
        build_job_specification({}, size="8-vcpu", product=product, hours=1)


@pytest.mark.parametrize("invalid_product", [
    {},
    {"id": "gpu-test"},
    {"id": "gpu-test", "category": "gpu-test", "provider": " "},
    {"id": "gpu-test", "category": "gpu-test", "provider": None},
])
def test_build_job_specification_rejects_incomplete_product(invalid_product) -> None:
    with pytest.raises(ValueError, match="product must contain non-empty"):
        build_job_specification({}, product=invalid_product, hours=1)


def test_build_job_specification_requires_valid_product_when_inheriting() -> None:
    with pytest.raises(ValueError, match="product must contain non-empty"):
        build_job_specification({}, hours=1)


@pytest.mark.parametrize("size", ["gpu-nvidia-b200-1-gpu", "gpu-nvidia-b200-1-mig.1g"])
def test_build_cpu_product_id_rejects_gpu_ids_as_cpu_sizes(size: str) -> None:
    with pytest.raises(ValueError, match="CPU size"):
        build_cpu_product_id(size)
