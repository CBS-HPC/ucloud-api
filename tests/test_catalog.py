from __future__ import annotations

import pytest

from ucloud_workflow.catalog import (
    MACHINE_CATALOG,
    STANDARD_JOB_PROFILES,
    TEMPLATE_JOB_CATALOG,
    machine_by_product,
    machine_products_for_profile,
    profile_by_name,
    resolve_template_job_id,
)


def test_profile_lookup_normalizes_names() -> None:
    assert profile_by_name("VS Code remote session").name == "vscode-remote-session"
    assert profile_by_name("vscode_remote_session").name == "vscode-remote-session"


def test_machine_lookup_returns_documented_gpu_products() -> None:
    machine = machine_by_product("gpu-nvidia-b200-8-gpu")
    assert machine is not None
    assert machine.machine_class == "gpu"
    assert machine.cpu_vcpus == 384
    assert machine.cpu_model == "AMD EPYC 9655"
    assert machine.gpu_count == 8
    assert machine.memory_gib == 2304
    assert machine.memory_type == "DDR5-6400"
    assert machine.gpu_hours_per_hour == 8.0
    assert machine.gpu_hours_label == "8 GPU-hours/hour"


def test_machine_lookup_returns_documented_mig_catalog_entries() -> None:
    machine = machine_by_product("gpu-nvidia-b200-4-mig.1g")
    assert machine is not None
    assert machine.machine_class == "gpu"
    assert machine.cpu_vcpus == 24
    assert machine.cpu_model == "AMD EPYC 9655"
    assert machine.gpu_count == 4
    assert machine.mig_instances == 4
    assert machine.mig_profile == "B200-mig.1g.23gb"
    assert machine.memory_gib == 144
    assert machine.memory_type == "DDR5-6400"
    assert machine.gpu_hours_per_hour == 4 / 7
    assert machine.gpu_hours_label == "4 / 7 GPU-hours/hour"


def test_machine_lookup_returns_documented_cpu_catalog_entries() -> None:
    machine = machine_by_product("cpu-amd-zen5-128-vcpu")
    assert machine is not None
    assert machine.machine_class == "cpu"
    assert machine.cpu_vcpus == 128
    assert machine.cpu_model == "AMD EPYC 9535"
    assert machine.memory_gib == 384
    assert machine.memory_type == "DDR5-6000"
    assert machine.core_hours_per_hour == 128


def test_machine_products_for_profile_returns_recommended_catalog_entries() -> None:
    products = {machine.product for machine in machine_products_for_profile("gpu-batch-inference")}

    assert products == {
        "gpu-nvidia-b200-1-gpu",
        "gpu-nvidia-b200-2-gpu",
        "gpu-nvidia-b200-3-gpu",
        "gpu-nvidia-b200-4-gpu",
        "gpu-nvidia-b200-5-gpu",
        "gpu-nvidia-b200-6-gpu",
        "gpu-nvidia-b200-7-gpu",
        "gpu-nvidia-b200-8-gpu",
        "gpu-nvidia-b200-1-mig.1g",
        "gpu-nvidia-b200-2-mig.1g",
        "gpu-nvidia-b200-3-mig.1g",
        "gpu-nvidia-b200-4-mig.1g",
    }


def test_machine_products_for_cpu_profile_returns_full_zen5_ladder() -> None:
    products = {machine.product for machine in machine_products_for_profile("cpu-python-batch")}

    assert "cpu-amd-zen5-1-vcpu" in products
    assert "cpu-amd-zen5-128-vcpu" in products
    assert len(products) >= 8


def test_resolve_template_job_id_prefers_profile_specific_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID", "job-global")
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID_CPU_PYTHON_BATCH", "job-cpu")

    assert resolve_template_job_id("cpu-python-batch", "job-global") == "job-cpu"


def test_resolve_template_job_id_falls_back_to_global(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UCLOUD_TEMPLATE_JOB_ID", "job-global")
    monkeypatch.delenv("UCLOUD_TEMPLATE_JOB_ID_GPU_BATCH_INFERENCE", raising=False)

    assert resolve_template_job_id("gpu-batch-inference", "job-global") == "job-global"


def test_resolve_template_job_id_rejects_unknown_profile() -> None:
    with pytest.raises(ValueError, match="Unknown job profile"):
        resolve_template_job_id("not-a-profile", "job-global")


def test_catalogs_have_expected_size() -> None:
    assert len(STANDARD_JOB_PROFILES) >= 6
    assert len(TEMPLATE_JOB_CATALOG) == len(STANDARD_JOB_PROFILES) + 1
    assert len(MACHINE_CATALOG) >= 22
