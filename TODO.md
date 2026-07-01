# TODO

## Verified

- [x] Verify `UCLOUD_TEMPLATE_JOB_ID` is loaded from `.env`
- [x] Verify `UCLOUD_MOUNT_PATH` is loaded from `.env`

## Workflow

- [ ] Add a smoke test for `examples/ssh_transfer_job.py` against a real UCloud job
- [ ] Replace the dummy SSH transfer demo with a real extraction workflow
- [ ] Add configurable output naming for the transfer demo
- [x] Add an overview tool for all UCloud machine types
- [x] Verify mount / drive attachment against a real UCloud job
  - Verified good path form: `UCLOUD_MOUNT_PATH="/8983017/moody_agent/"`.
  - The human-readable path form `UCLOUD_MOUNT_PATH="/agent (8983017)/moody_agent/"` failed with HTTP 400 `Unknown file or permission denied`.
- [x] Park direct `.env` mount injection for workflow runners
  - Standard workflows should inherit drives and app/job settings from `UCLOUD_TEMPLATE_JOB_ID` or profile-specific template jobs.

## Infrastructure

- [x] Add a reusable catalog of `UCLOUD_TEMPLATE_JOB_ID` values by job family
- [x] Add a standard job profile registry for common workload types
- [x] Add a machine capability / availability overview tool
- [ ] Fill `TEMPLATE_JOB_CATALOG.md` with verified template jobs for CPU Python, VS Code, RStudio, and GPU workloads
- [ ] Add a shared artifact manifest and provenance schema

## Delivery

- [ ] Add a sample delivery bundle generated from a real output directory
- [ ] Document the full point 5 -> point 6 flow end to end
