# Changelog

## Unreleased

## 0.1.7 - 2026-10-20

- Added read-only discovery and explicit, preview-first management commands for Public Links, Public IPs, software-license activations, and account SSH public keys.
- Added workspace-scoped deletion checks, bound-resource guards, closed-by-default supported IP firewalls, and bounded resource-readiness polling.
- Added atomic local creation records and unknown-outcome handling without automatic POST retries.
- Added local public-key validation, duplicate registration checks, and SSH registration preflight without uploading private keys.
- Added live CPU/GPU/MIG availability snapshots and `ucloud catalog machines --live`, leaving the static catalog and existing job defaults unchanged.
- Added opt-in existing-resource selections for template jobs, with workspace, provider, application, readiness, and binding checks.
- Added Python per-run provisioning with ownership journals, job termination, and cleanup limited to confirmed newly created resources; ambiguous job submissions retain resources for reconciliation.
- Added preview-first `jobs submit-immediate` with explicit approved products, optional BUSY acceptance, startup deadlines, and termination on startup failure.
- Added explicit `ssh_enabled=False` to resource-managed and immediate-start Python helpers, and `--no-ssh` to job submission commands. Live testing exposed forced SSH rejecting web-only applications; the existing SSH-on default remains unchanged.
- Live-tested disposable link/license creation, readiness, labels, READ grant/revoke to an empty group, deletion, account SSH-key registration/duplicate detection/deletion, resource-aware CPU jobs, SSH output download, owned/reused-resource lifecycle, and startup cancellation on 2026-10-20. Existing resources/keys and `.env` were preserved; all disposable jobs/resources/groups were cleaned up.
- Public-IP creation returned HTTP 402 with zero project quota, so successful IP/firewall operations remain unverified. A direct public-link HTTP probe returned 449 despite confirmed job binding; public-URL serving remains unverified. Runtime attach/detach remains deferred because provider discovery does not establish effective runtime support.

## 0.1.6 - 2026-10-06

- Added explicit `id` / `category` / `provider` product selection for template-based CPU, GPU, and MIG jobs, without changing existing CPU `size` calls.
- Added template-product preservation when low-level helpers receive no machine override, and `--use-template-product` for CLI workflows and higher-level Python runners.
- Preserved template application parameters, mounts, public links, and other resources while changing the product; job launch results now report the actually submitted product id.
- Rejected incomplete/conflicting machine selections and GPU/MIG product ids passed as CPU sizes.
- Verified with 101 automated tests and live full-B200/MIG submissions from a real Python template; both jobs exposed SSH and were terminated after the smoke tests.

## 0.1.5 - 2026-08-31

- Added `SSHTransportError` for completed `ssh` or `scp` processes that exit with code `255`, allowing callers to retry connection failures without parsing error text.

## 0.1.4 - 2026-08-31

- Made every CLI SSH and SCP operation use the configured `UCLOUD_SSH_CONFIG_PATH` file.
- Added standard private-key discovery beside that config file and the `UCLOUD_SSH_IDENTITY_FILE` override.
- Added managed `IdentityFile` entries without disabling an existing SSH agent.

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
