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
