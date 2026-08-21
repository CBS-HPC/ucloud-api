# TODO

## Verified

- [x] Verify `UCLOUD_TEMPLATE_JOB_ID` is loaded from `.env`

## CLI workflows

- [ ] Live-test `examples/ssh_transfer_job.py` against a real UCloud job, including SSH-readiness retry and timeout cleanup
- [ ] Replace the dummy SSH transfer demo with a real extraction workflow
- [x] Add configurable output naming for the transfer demo
- [x] Add an overview tool for all UCloud machine types
- [x] Remove unsupported `UCLOUD_MOUNT_PATH` configuration
- [x] Bound noninteractive SSH/SCP transport and retry endpoint readiness before remote workspace setup
- [ ] If required, validate explicit `--mount` / `--read-only-mount` flags against a real UCloud job
  - Standard workflows inherit drives and app/job settings from `UCLOUD_TEMPLATE_JOB_ID` or profile-specific template jobs.

## Infrastructure

- [x] Add a reusable catalog of `UCLOUD_TEMPLATE_JOB_ID` values by job family
- [x] Add a standard job profile registry for common workload types
- [x] Add a machine capability / availability overview tool
- [x] Add read-only API-token expiry inspection from `/api/tokens/browse`
- [x] Add controlled API-token creation with explicit `--yes` confirmation
- [x] Test controlled replacement-token creation and validation against the live UCloud API
- [ ] Add an opt-in, safely recoverable token-rotation workflow
  - Validate the replacement from a fresh process before changing `.env` or revoking the old token.
  - Keep manual UCloud web-UI revocation until an explicit revoke flow is designed and tested.
- [ ] Fill `docs/operations/template-job-catalog.md` with verified template jobs for CPU Python, VS Code, RStudio, and GPU workloads
- [x] Add a shared artifact manifest and provenance schema
- [ ] Verify downstream callers map `SSHReadinessError` and `RemoteCommandTimeoutError` to redacted pre-execution recovery records

## Local delivery bundles

- [ ] Add a sample delivery bundle generated from a real output directory
- [x] Document the end-to-end run-and-deliver CLI procedure
