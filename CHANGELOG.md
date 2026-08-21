# Changelog

## 0.1.3 - 2026-08-21

- Bound every SSH and SCP command, with process-tree cleanup after a local transport timeout.
- Added noninteractive SSH/SCP options and retried readiness probes before remote workspace setup.
- Added explicit stage budgets and flushed start, completion, and failure logs for remote job preparation and transfers.
- Added typed, redacted SSH-readiness and transport-timeout errors for callers that need recovery handling.

## 0.1.2 - 2026-08-12

- Added `ucloud tokens status` for read-only API-token expiry metadata.
- Added `ucloud tokens options` for UCloud token-provider and permission discovery.
- Added controlled `ucloud tokens create`, with request preview by default and explicit `--yes` confirmation for `POST /api/tokens`.
- Added `--valid-for MONTHS` for calendar-month token expiry and documented one-time-secret, timeout, validation, and rotation handling.
- Added checksummed delivery manifests with artifact roles and UCloud run provenance.
- Added a configurable local output path for the SSH transfer smoke test.
- Removed the unsupported `UCLOUD_MOUNT_PATH` setting; normal workflows inherit attached drives from template jobs.
- Reorganized the documentation under `docs/`, including API, token-management, run-and-deliver, SSH smoke-test, and template-job guides.
- Clarified that the project is an operator-invoked CLI, not an AI agent, hosted service, or unattended scheduler.
- Removed stale architecture-audit and duplicate standard-job-type documents.

## 0.1.1

- Added a reusable UCloud CLI toolkit packaged as a `uv` project.
- Added job submission helpers, SSH transfer demos, and generic Python job execution.
- Added utilization report parsing for `job-report.csv` and machine-size recommendations.
- Added a documented machine catalog, standard job profiles, and template-job catalog.
- Standardized the workflow around `UCLOUD_TEMPLATE_JOB_ID` so mounted drives and app settings come from UCloud template jobs.
- Added delivery bundle creation and release-oriented documentation.

## 0.1.0

- Initial wheelable packaging baseline for the UCloud workflow prototype.
