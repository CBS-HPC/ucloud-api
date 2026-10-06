# Maintain UCloud template jobs

This document tracks reusable `UCLOUD_TEMPLATE_JOB_ID` values for the `ucloud` CLI. It is an operator-maintained record, not a source of automatic job selection.

Use it to replace a single global template with **known-good template jobs** for each CLI job profile.

Template jobs should carry the UCloud-side configuration that is hard to reproduce safely from guessed API fields:

- mounted drives
- selected application/container
- application parameters
- SSH behavior
- baseline machine family and runtime assumptions

## Suggested fields

Each catalog entry should record:

- `purpose`
- `template_job_id`
- `machine_type`
- `product_id`, `product_category`, and `product_provider` (exact values from the job specification)
- `gpu_type`
- `ssh_enabled`
- `working_directory`
- `notes`
- `last_verified_utc`
- `owner`

## Catalog

| Purpose | Template Job ID | Machine Type | Notes | Last Verified |
| --- | --- | --- | --- | --- |
| VS Code remote session | _tbd_ | _tbd_ | SSH-enabled job suitable for VS Code Remote SSH | _tbd_ |
| RStudio container | _tbd_ | _tbd_ | Stable interactive session template | _tbd_ |
| Python batch CPU job | _tbd_ | _tbd_ | Generic batch template for scripts and packages | _tbd_ |
| Utilization-aware batch job | _tbd_ | _tbd_ | Emits or preserves `job-report.csv` | _tbd_ |
| GPU inference job | _tbd_ | _tbd_ | Base template for GPU batch inference, e.g. vLLM-style workloads | _tbd_ |

## How to maintain it

Rules for adding a template job:

1. Use a job that is already known to start reliably.
2. Verify it exposes the expected SSH or runtime behavior.
3. Verify the machine family matches the intended workload.
4. Verify attached drives are visible inside the running job.
5. Record the last verified date.
6. Keep one template per job family rather than one global fallback.

## Why this matters

The CLI can use a single `UCLOUD_TEMPLATE_JOB_ID`, but that is too coarse when you run different kinds of jobs.

A catalog gives you:

- one template for interactive debugging
- one template for CPU batch jobs
- one template for GPU inference jobs
- one template for RStudio or similar containerized sessions

The CLI reads these ids from `UCLOUD_TEMPLATE_JOB_ID` and profile-specific `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` variables; this document is the operational record of which values are known to work.

Template selection and machine selection are separate. Use `--use-template-product` to retain a template's GPU/MIG product, or provide all three explicit product options to change the machine while retaining its application and resources. Otherwise the CLI applies `UCLOUD_DEFAULT_SIZE` as a CPU override. Changing hardware does not make an incompatible application GPU-ready. See [machine selection](../reference/api.md#machine-selection).

## Verified GPU product-selection smoke test

On 2026-10-06, the configured Python SSH template (`8985848`, `coder-python` 1.89.1, originally `cpu-amd-zen5-128-vcpu`) was used to submit both:

| Product ID | Category | Provider | Result |
| --- | --- | --- | --- |
| `gpu-nvidia-b200-1-gpu` | `gpu-nvidia-b200` | `ucloud` | Reached `RUNNING`; SSH and `nvidia-smi` succeeded; B200 reported 183359 MiB |
| `gpu-nvidia-b200-1-mig.1g` | `gpu-nvidia-b200` | `ucloud` | Reached `RUNNING`; SSH and B200 device query succeeded; parent-GPU memory query reported insufficient permissions |

The retrieved specifications matched the requested products and retained the template's application, parameters, resources, and replica count. Both newly created jobs were terminated after the probes and reached a terminal state. This verifies product selection and SSH/device visibility, not CUDA computation, inference software, GPU sizing, or MIG memory capacity. Template ids are project/access-specific; use your own known-good template outside this project.
