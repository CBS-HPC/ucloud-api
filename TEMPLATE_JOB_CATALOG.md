# UCloud Template Job Catalog

This document tracks reusable `UCLOUD_TEMPLATE_JOB_ID` values by purpose.

The point is to stop treating the template job as a single global value and instead manage **known-good template jobs** by job family.

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

The current code can already take a single `UCLOUD_TEMPLATE_JOB_ID`, but that is too coarse for a generic platform.

A catalog gives you:

- one template for interactive debugging
- one template for CPU batch jobs
- one template for GPU inference jobs
- one template for RStudio or similar containerized sessions

That is the right abstraction boundary for a generic UCloud tool.
