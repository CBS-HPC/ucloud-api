from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import fnmatch
import os
import re


JobCategory = Literal["interactive", "batch", "analysis", "delivery", "pipeline", "staging"]
MachineClass = Literal["cpu", "gpu", "mixed", "interactive"]
MachineDirection = Literal["decrease", "increase"]


def normalize_catalog_key(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return normalized.upper()


def _catalog_search_key(value: str) -> str:
    return normalize_catalog_key(value).replace("_", "")


@dataclass(frozen=True, slots=True)
class JobProfile:
    name: str
    display_name: str
    category: JobCategory
    description: str
    preferred_machine_families: tuple[str, ...]
    template_env_suffix: str
    requires_ssh: bool = False
    supports_utilization_report: bool = True
    notes: tuple[str, ...] = ()

    @property
    def template_env_var(self) -> str:
        return f"UCLOUD_TEMPLATE_JOB_ID_{normalize_catalog_key(self.template_env_suffix)}"


@dataclass(frozen=True, slots=True)
class TemplateJobCatalogEntry:
    profile_name: str
    display_name: str
    env_var: str
    purpose: str
    notes: tuple[str, ...] = ()

    @property
    def current_value(self) -> str | None:
        raw = os.getenv(self.env_var)
        if raw is None:
            return None
        value = raw.strip()
        return value or None


@dataclass(frozen=True, slots=True)
class MachineTypeInfo:
    product: str
    provider: str
    machine_class: MachineClass
    description: str
    cpu_vcpus: int | None = None
    cpu_model: str | None = None
    memory_gib: int | None = None
    memory_type: str | None = None
    gpu_count: int | None = None
    gpu_model: str | None = None
    mig_instances: int | None = None
    mig_profile: str | None = None
    core_hours_per_hour: int | None = None
    gpu_hours_per_hour: float | None = None
    gpu_hours_label: str | None = None
    status: str | None = None
    notes: tuple[str, ...] = ()


STANDARD_JOB_PROFILES: tuple[JobProfile, ...] = (
    JobProfile(
        name="vscode-remote-session",
        display_name="VS Code remote session",
        category="interactive",
        description="SSH-enabled interactive session intended for VS Code Remote SSH or file inspection.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="vscode_remote_session",
        requires_ssh=True,
        supports_utilization_report=False,
        notes=("Use this for interactive development and debugging.",),
    ),
    JobProfile(
        name="rstudio-session",
        display_name="RStudio session",
        category="interactive",
        description="Interactive RStudio container for statistical analysis and notebooks.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="rstudio_session",
        requires_ssh=False,
        supports_utilization_report=False,
        notes=("Use this when the user needs an RStudio environment.",),
    ),
    JobProfile(
        name="interactive-debug-session",
        display_name="Interactive debug session",
        category="interactive",
        description="General-purpose SSH-enabled job for ad hoc inspection and remote shell access.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="interactive_debug_session",
        requires_ssh=True,
        supports_utilization_report=False,
    ),
    JobProfile(
        name="cpu-python-batch",
        display_name="CPU Python batch",
        category="batch",
        description="Batch job for running a Python script on CPU with optional mounts and outputs.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="cpu_python_batch",
        requires_ssh=True,
        supports_utilization_report=True,
    ),
    JobProfile(
        name="python-package-batch",
        display_name="Python package batch",
        category="batch",
        description="Batch job that uploads a local package, installs it, and runs a Python entrypoint.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="python_package_batch",
        requires_ssh=True,
        supports_utilization_report=True,
    ),
    JobProfile(
        name="data-staging-job",
        display_name="Data staging job",
        category="staging",
        description="Job focused on transferring, mounting, and validating input or output data.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="data_staging_job",
        requires_ssh=True,
        supports_utilization_report=False,
    ),
    JobProfile(
        name="report-analysis-job",
        display_name="Report analysis job",
        category="analysis",
        description="Analyze job metadata, utilization reports, and resource consumption patterns.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="report_analysis_job",
        requires_ssh=False,
        supports_utilization_report=True,
    ),
    JobProfile(
        name="gpu-batch-inference",
        display_name="GPU batch inference",
        category="batch",
        description="Batch inference workload for large models on GPU nodes, including vLLM-style setups.",
        preferred_machine_families=("gpu-nvidia-b200-*-gpu", "gpu-nvidia-b200-*-mig.1g"),
        template_env_suffix="gpu_batch_inference",
        requires_ssh=True,
        supports_utilization_report=True,
        notes=("This is the profile family for batch inference workloads.",),
    ),
    JobProfile(
        name="delivery-packaging-job",
        display_name="Delivery packaging job",
        category="delivery",
        description="Create delivery bundles from data, docs, scripts, and provenance metadata.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4"),
        template_env_suffix="delivery_packaging_job",
        requires_ssh=False,
        supports_utilization_report=False,
    ),
    JobProfile(
        name="pipeline-step",
        display_name="Pipeline step",
        category="pipeline",
        description="Reusable workflow step intended to be chained with other standard job types.",
        preferred_machine_families=("cpu-amd-zen5-*", "cpu-amd-zen4", "gpu-nvidia-b200-*-gpu", "gpu-nvidia-b200-*-mig.1g", "gpu-nvidia-h100"),
        template_env_suffix="pipeline_step",
        requires_ssh=False,
        supports_utilization_report=True,
    ),
)


TEMPLATE_JOB_CATALOG: tuple[TemplateJobCatalogEntry, ...] = (
    TemplateJobCatalogEntry(
        profile_name="global",
        display_name="Global fallback template",
        env_var="UCLOUD_TEMPLATE_JOB_ID",
        purpose="Fallback template used when no profile-specific template is set.",
        notes=("Preserves the current single-template behavior.",),
    ),
    *(
        TemplateJobCatalogEntry(
            profile_name=profile.name,
            display_name=profile.display_name,
            env_var=profile.template_env_var,
            purpose=profile.description,
            notes=profile.notes,
        )
        for profile in STANDARD_JOB_PROFILES
    ),
)


MACHINE_CATALOG: tuple[MachineTypeInfo, ...] = (
    MachineTypeInfo(
        product="cpu-amd-zen5-1-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Small CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=1,
        cpu_model="AMD EPYC 9535",
        memory_gib=3,
        memory_type="DDR5-6000",
        core_hours_per_hour=1,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-2-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Small CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=2,
        cpu_model="AMD EPYC 9535",
        memory_gib=6,
        memory_type="DDR5-6000",
        core_hours_per_hour=2,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-4-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Small CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=4,
        cpu_model="AMD EPYC 9535",
        memory_gib=12,
        memory_type="DDR5-6000",
        core_hours_per_hour=4,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-8-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Small CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=8,
        cpu_model="AMD EPYC 9535",
        memory_gib=24,
        memory_type="DDR5-6000",
        core_hours_per_hour=8,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-16-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Small CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=16,
        cpu_model="AMD EPYC 9535",
        memory_gib=48,
        memory_type="DDR5-6000",
        core_hours_per_hour=16,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-32-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Small CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=32,
        cpu_model="AMD EPYC 9535",
        memory_gib=96,
        memory_type="DDR5-6000",
        core_hours_per_hour=32,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-64-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Large CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=64,
        cpu_model="AMD EPYC 9535",
        memory_gib=192,
        memory_type="DDR5-6000",
        core_hours_per_hour=64,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen5-128-vcpu",
        provider="UCloud CPU catalog",
        machine_class="cpu",
        description="Largest CPU instance with AMD EPYC 9535 and DDR5-6000 memory.",
        cpu_vcpus=128,
        cpu_model="AMD EPYC 9535",
        memory_gib=384,
        memory_type="DDR5-6000",
        core_hours_per_hour=128,
    ),
    MachineTypeInfo(
        product="cpu-amd-zen4",
        provider="SDU-Odense",
        machine_class="cpu",
        description="CPU node with AMD EPYC 9534 processors and large-memory configuration.",
        cpu_vcpus=128,
        cpu_model="AMD EPYC 9534",
        memory_gib=768,
        notes=("Documented for the SDU-Odense provider.",),
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-1-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with one NVIDIA B200 accelerator.",
        cpu_vcpus=48,
        cpu_model="AMD EPYC 9655",
        memory_gib=288,
        memory_type="DDR5-6400",
        gpu_count=1,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=48,
        gpu_hours_per_hour=1.0,
        gpu_hours_label="1 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-2-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with two NVIDIA B200 accelerators.",
        cpu_vcpus=96,
        cpu_model="AMD EPYC 9655",
        memory_gib=576,
        memory_type="DDR5-6400",
        gpu_count=2,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=96,
        gpu_hours_per_hour=2.0,
        gpu_hours_label="2 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-3-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with three NVIDIA B200 accelerators.",
        cpu_vcpus=144,
        cpu_model="AMD EPYC 9655",
        memory_gib=864,
        memory_type="DDR5-6400",
        gpu_count=3,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=144,
        gpu_hours_per_hour=3.0,
        gpu_hours_label="3 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-4-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with four NVIDIA B200 accelerators.",
        cpu_vcpus=192,
        cpu_model="AMD EPYC 9655",
        memory_gib=1152,
        memory_type="DDR5-6400",
        gpu_count=4,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=192,
        gpu_hours_per_hour=4.0,
        gpu_hours_label="4 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-5-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with five NVIDIA B200 accelerators.",
        cpu_vcpus=240,
        cpu_model="AMD EPYC 9655",
        memory_gib=1440,
        memory_type="DDR5-6400",
        gpu_count=5,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=240,
        gpu_hours_per_hour=5.0,
        gpu_hours_label="5 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-6-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with six NVIDIA B200 accelerators.",
        cpu_vcpus=288,
        cpu_model="AMD EPYC 9655",
        memory_gib=1728,
        memory_type="DDR5-6400",
        gpu_count=6,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=288,
        gpu_hours_per_hour=6.0,
        gpu_hours_label="6 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-7-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with seven NVIDIA B200 accelerators.",
        cpu_vcpus=336,
        cpu_model="AMD EPYC 9655",
        memory_gib=2016,
        memory_type="DDR5-6400",
        gpu_count=7,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=336,
        gpu_hours_per_hour=7.0,
        gpu_hours_label="7 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-8-gpu",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="GPU instance with eight NVIDIA B200 accelerators.",
        cpu_vcpus=384,
        cpu_model="AMD EPYC 9655",
        memory_gib=2304,
        memory_type="DDR5-6400",
        gpu_count=8,
        gpu_model="NVIDIA B200",
        core_hours_per_hour=384,
        gpu_hours_per_hour=8.0,
        gpu_hours_label="8 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-1-mig.1g",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="B200 MIG instance with one 1g profile slice.",
        cpu_vcpus=6,
        cpu_model="AMD EPYC 9655",
        memory_gib=36,
        memory_type="DDR5-6400",
        gpu_count=1,
        gpu_model="NVIDIA B200 MIG",
        mig_instances=1,
        mig_profile="B200-mig.1g.23gb",
        gpu_hours_per_hour=1 / 7,
        gpu_hours_label="1 / 7 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-2-mig.1g",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="B200 MIG instance with two 1g profile slices.",
        cpu_vcpus=12,
        cpu_model="AMD EPYC 9655",
        memory_gib=72,
        memory_type="DDR5-6400",
        gpu_count=2,
        gpu_model="NVIDIA B200 MIG",
        mig_instances=2,
        mig_profile="B200-mig.1g.23gb",
        gpu_hours_per_hour=2 / 7,
        gpu_hours_label="2 / 7 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-3-mig.1g",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="B200 MIG instance with three 1g profile slices.",
        cpu_vcpus=18,
        cpu_model="AMD EPYC 9655",
        memory_gib=108,
        memory_type="DDR5-6400",
        gpu_count=3,
        gpu_model="NVIDIA B200 MIG",
        mig_instances=3,
        mig_profile="B200-mig.1g.23gb",
        gpu_hours_per_hour=3 / 7,
        gpu_hours_label="3 / 7 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-b200-4-mig.1g",
        provider="UCloud GPU catalog",
        machine_class="gpu",
        description="B200 MIG instance with four 1g profile slices.",
        cpu_vcpus=24,
        cpu_model="AMD EPYC 9655",
        memory_gib=144,
        memory_type="DDR5-6400",
        gpu_count=4,
        gpu_model="NVIDIA B200 MIG",
        mig_instances=4,
        mig_profile="B200-mig.1g.23gb",
        gpu_hours_per_hour=4 / 7,
        gpu_hours_label="4 / 7 GPU-hours/hour",
    ),
    MachineTypeInfo(
        product="gpu-nvidia-h100",
        provider="SDU-Odense",
        machine_class="gpu",
        description="GPU node with NVIDIA H100 accelerators for high-end inference and training.",
        cpu_vcpus=96,
        cpu_model="AMD EPYC 9534",
        memory_gib=768,
        memory_type="DDR5-4800",
        gpu_count=4,
        gpu_model="NVIDIA H100 SXM5 80 GB",
        notes=("Documented for the SDU-Odense provider.",),
    ),
)


def profile_by_name(name: str) -> JobProfile | None:
    search_name = _catalog_search_key(name)
    for profile in STANDARD_JOB_PROFILES:
        if _catalog_search_key(profile.name) == search_name or _catalog_search_key(profile.display_name) == search_name:
            return profile
    return None


def machine_by_product(product: str) -> MachineTypeInfo | None:
    for machine in MACHINE_CATALOG:
        if machine.product == product:
            return machine
    return None


def machine_products_for_profile(profile_name: str) -> tuple[MachineTypeInfo, ...]:
    profile = profile_by_name(profile_name)
    if profile is None:
        return ()
    machines = [
        machine
        for machine in MACHINE_CATALOG
        if any(
            fnmatch.fnmatchcase(machine.product, family)
            for family in profile.preferred_machine_families
        )
    ]
    return tuple(sorted(machines, key=machine_sort_key))


MACHINE_LADDERS: dict[str, tuple[str, ...]] = {
    "cpu-amd-zen5": (
        "cpu-amd-zen5-1-vcpu",
        "cpu-amd-zen5-2-vcpu",
        "cpu-amd-zen5-4-vcpu",
        "cpu-amd-zen5-8-vcpu",
        "cpu-amd-zen5-16-vcpu",
        "cpu-amd-zen5-32-vcpu",
        "cpu-amd-zen5-64-vcpu",
        "cpu-amd-zen5-128-vcpu",
    ),
    "gpu-nvidia-b200-mig.1g": (
        "gpu-nvidia-b200-1-mig.1g",
        "gpu-nvidia-b200-2-mig.1g",
        "gpu-nvidia-b200-3-mig.1g",
        "gpu-nvidia-b200-4-mig.1g",
    ),
    "gpu-nvidia-b200-gpu": (
        "gpu-nvidia-b200-1-gpu",
        "gpu-nvidia-b200-2-gpu",
        "gpu-nvidia-b200-3-gpu",
        "gpu-nvidia-b200-4-gpu",
        "gpu-nvidia-b200-5-gpu",
        "gpu-nvidia-b200-6-gpu",
        "gpu-nvidia-b200-7-gpu",
        "gpu-nvidia-b200-8-gpu",
    ),
    "cpu-amd-zen4": ("cpu-amd-zen4",),
    "gpu-nvidia-h100": ("gpu-nvidia-h100",),
}

MACHINE_LADDER_ORDER: dict[str, int] = {
    family_key: index for index, family_key in enumerate(MACHINE_LADDERS)
}


def machine_family_key(product: str) -> str | None:
    if re.match(r"^cpu-amd-zen5-\d+-vcpu$", product):
        return "cpu-amd-zen5"
    if re.match(r"^gpu-nvidia-b200-\d+-mig\.1g$", product):
        return "gpu-nvidia-b200-mig.1g"
    if re.match(r"^gpu-nvidia-b200-\d+-gpu$", product):
        return "gpu-nvidia-b200-gpu"
    if product == "cpu-amd-zen4":
        return "cpu-amd-zen4"
    if product == "gpu-nvidia-h100":
        return "gpu-nvidia-h100"
    return None


def machine_ladder_for_family(family_key: str) -> tuple[MachineTypeInfo, ...]:
    products = MACHINE_LADDERS.get(family_key)
    if products is None:
        return ()
    machines = [machine_by_product(product) for product in products]
    return tuple(machine for machine in machines if machine is not None)


def machine_sort_key(machine: MachineTypeInfo) -> tuple[int, float, str]:
    family_key = machine_family_key(machine.product)
    family_order = MACHINE_LADDER_ORDER.get(family_key or "", len(MACHINE_LADDER_ORDER))

    if family_key == "cpu-amd-zen5":
        capacity = float(machine.core_hours_per_hour or machine.cpu_vcpus or 0)
    elif family_key == "gpu-nvidia-b200-gpu":
        capacity = float(machine.gpu_hours_per_hour or machine.gpu_count or 0)
    elif family_key == "gpu-nvidia-b200-mig.1g":
        capacity = float(machine.gpu_hours_per_hour or machine.mig_instances or 0)
    else:
        capacity = float(machine.core_hours_per_hour or machine.gpu_hours_per_hour or machine.cpu_vcpus or machine.gpu_count or 0)

    return (family_order, capacity, machine.product)


def machine_ladder_for_product(product: str) -> tuple[MachineTypeInfo, ...]:
    family_key = machine_family_key(product)
    if family_key is None:
        return ()
    return machine_ladder_for_family(family_key)


def next_machine_in_ladder(product: str, direction: MachineDirection) -> MachineTypeInfo | None:
    ladder = machine_ladder_for_product(product)
    if not ladder:
        return None

    for index, machine in enumerate(ladder):
        if machine.product != product:
            continue
        if direction == "increase":
            next_index = index + 1
        else:
            next_index = index - 1
        if next_index < 0 or next_index >= len(ladder):
            return None
        return ladder[next_index]
    return None


def resolve_template_job_id(profile_name: str | None, global_template_job_id: str | None = None) -> str | None:
    if profile_name:
        profile = profile_by_name(profile_name)
        if profile is None:
            raise ValueError(f"Unknown job profile: {profile_name!r}")
        env_value = os.getenv(profile.template_env_var)
        if env_value:
            resolved = env_value.strip()
            if resolved:
                return resolved
    return global_template_job_id
