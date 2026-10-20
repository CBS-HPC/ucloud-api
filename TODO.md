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
- [x] Use the configured SSH config file and discovered private key for CLI transports
- [x] Live-test `UCLOUD_SSH_CONFIG_PATH` and `UCLOUD_SSH_IDENTITY_FILE` on a real UCloud job
- [ ] If required, validate explicit `--mount` / `--read-only-mount` flags against a real UCloud job
  - Standard workflows inherit drives and app/job settings from `UCLOUD_TEMPLATE_JOB_ID` or profile-specific template jobs.

## Infrastructure

- [x] Add token-based setup with project/drive/template discovery, a default storage directory, confirmed writes, secret-safe output, and atomic preservation of existing configuration
  - `ucloud setup` creates/reuses `/<drive-id>/ucloud-workflow` or an explicit `UCLOUD_STORAGE_PATH`. It does not change template mounts or infer their `/work/...` mapping; existing SSH transfer examples and job defaults remain unchanged.
  - Read-only live checks on 2026-10-20 verified project/drive discovery, the configured template, and folder previews on six reachable drives. Three advertised drives returned provider HTTP 503; no automatic fallback or live writes were performed.
  - Setup tests cover interactive/noninteractive selection, non-destructive folder creation, recovery, and quoted Windows-path compatibility. Wheel/sdist privacy and isolated installation checks pass.
- [x] Live-test `ucloud setup` folder creation and rerun/reuse on an explicitly selected writable drive, plus saving configuration into a disposable local environment file
  - Verified on 2026-10-20 using the writable drive already selected by the configured template: nested folder creation/read-back, configuration roundtrip with an unrelated setting/comment preserved, and rerun/reuse without extra remote writes. `.env` and existing data were preserved, no jobs were submitted, and the disposable local environment file was removed. This was not mount validation.
  - Only the owned empty test tree was moved to UCloud Trash. Permanent file deletion returned HTTP 400; shared Trash was not emptied. Setup does not expose deletion or automatic cleanup.
- [x] Add a reusable catalog of `UCLOUD_TEMPLATE_JOB_ID` values by job family
- [x] Add a standard job profile registry for common workload types
- [x] Add a static machine-capability catalog (live availability is planned separately below)
- [x] Support explicit CPU/GPU/MIG product references and unchanged template products, with backwards-compatible CPU defaults
- [x] Test product selection, conflicting arguments, preserved parameters/resources/public links, and actual launch product ids
- [x] Live-test full GPU and MIG product selection from a real template, including SSH access and job termination
  - Verified on 2026-10-06 with `coder-python` 1.89.1: both products reached `RUNNING`, exposed SSH and B200 hardware, retained template settings/resources, and were terminated immediately after the smoke test.
- [x] Add read-only API-token expiry inspection from `/api/tokens/browse`
- [x] Add controlled API-token creation with explicit `--yes` confirmation
- [x] Test controlled replacement-token creation and validation against the live UCloud API
- [ ] Add an opt-in, safely recoverable token-rotation workflow
  - Validate the replacement from a fresh process before changing `.env` or revoking the old token.
  - Keep manual UCloud web-UI revocation until an explicit revoke flow is designed and tested.
- [ ] Fill `docs/operations/template-job-catalog.md` with verified template jobs for CPU Python, VS Code, RStudio, and GPU workloads
- [x] Add a shared artifact manifest and provenance schema
- [ ] Verify downstream callers map `SSHReadinessError` and `RemoteCommandTimeoutError` to redacted pre-execution recovery records

## Resource and SSH-key management implementation plan

Scope: operator-invoked CLI commands and reusable Python functions for Public Links, Public IPs, software-license activations, and account SSH public keys. Reuse `UCloudClient.request`, Typer, existing SSH tools, and pytest; no new dependencies, background services, or generic resource framework.

Checkpoint 2026-10-20: standalone management commands, resource-aware submission, owned-resource run cleanup, and opt-in immediate startup are implemented. Following explicit operator approval, live tests passed for disposable links, CBS Stata-license activations, account SSH-key CRUD/duplicate checks, READ grant/revoke to an empty temporary group, resource-aware CPU jobs, owned/reused-resource lifecycle, SSH script/output transfer, and startup-deadline cancellation. All test jobs/resources/groups were cleaned up and existing resources/keys and `.env` were preserved. See `CHANGELOG.md` for release history.

Remaining gates: obtain a nonzero Public-IP allocation before successful IP/firewall/IP-aware-job tests; resolve HTTP 449 before claiming public-URL serving; establish effective provider support before runtime attach/detach commands. Do not treat advertised products or API binding as proof of effective runtime/HTTP behavior. Further live writes remain operator-controlled; the follow-up stays disabled.

- [x] Investigate upstream resource and SSH-key definitions and verify read-only access on 2026-10-19
  - `ingresses`, `networkips`, and `licenses`: product discovery and browsing returned HTTP 200; retrieving an existing link/license also succeeded.
  - `/api/ssh/browse` and `/api/ssh/retrieve` returned HTTP 200; a discovered local public key matched a registered account key.
  - Subsequent approved live tests verified link/license create/delete, labels and ACL grant/revoke, account SSH-key writes, and link/license job binding. IP creation returned HTTP 402 with zero quota; IP/firewall success remains unverified. Discovery alone does not establish write permission or sufficient allocation.

### 1. Read-only discovery and client contracts

- [x] Add bounded client calls for browse/retrieve/product discovery for the three fixed resource namespaces, and browse/retrieve for SSH keys
- [x] Handle pagination, empty responses, and nullable `boundTo`; identify products by the full id/category/provider reference
- [x] Add `ucloud links`, `ucloud ips`, `ucloud licenses`, and `ucloud ssh-keys` command groups with list/show, resource-product discovery, and machine-readable JSON output
  - Keep thin HTTP calls in `client.py`; put resource behavior in `resources.py` and SSH-key behavior in `ssh_keys.py`. Share only small internal helpers across the three real resource types.
  - Distinguish project-scoped resources from user-owned SSH keys. Do not treat a missing field or failed API call as an empty successful result.

### 2. SSH-key preflight and controlled registration

- [x] Add `ssh-keys check` to compare an explicit/discovered public key with all registered keys, ignoring comments and using key material/fingerprints
  - Report an unverifiable state when there is no usable public-key file; do not conclude that SSH-agent authentication cannot work or change existing job defaults.
- [x] Add public-key registration and ID-based deletion, with payload preview by default and explicit `--yes` for writes
  - Validate public-key input; reject private-key material before HTTP requests, avoid duplicate registration of an existing public key, and never read or upload private-key contents.
  - Key generation, automatic rotation, and automatic deletion after jobs are out of scope. Live revocation for already-running jobs needs a separate provider test.

### 3. Controlled resource creation and deletion

- [x] Add Public Link create/delete using discovered provider domain rules and exact product references
- [x] Add Public IP create/release and explicit firewall updates; keep newly requested IPs closed unless ports are deliberately supplied
- [x] Add activation/deletion for existing software-license products; do not provision vendor licenses, license keys, or license servers
- [x] Apply preview/`--yes`, project/provider validation, bounded `PREPARING` to `READY` polling, and redacted errors to every write path
  - Warn about public exposure and persistent allocation; verify `boundTo` before deletion and refuse in-use resources by default.
  - Record successful IDs immediately. After an ambiguous create timeout, record the unknown outcome and require reconciliation instead of blindly retrying the POST.

### 4. Explicit job integration and ownership-safe cleanup

- [x] Allow explicitly selected existing resource IDs in job submission without discarding template resources or application parameters
  - Use `ingress` for Public Links, `network` for Public IPs, and `license_server` for named application license parameters; validate provider and application compatibility.
- [x] Add optional create-for-run integration only after standalone commands are tested; persist a minimal operation record identifying newly created versus reused resources
  - Never auto-delete template resources, reused resources, or account SSH keys. Cleanup must use confirmed newly created IDs and report incomplete cleanup.
  - On pre-execution failure, terminate the job and clean up only resources explicitly provisioned for that run. Do not let cleanup failures hide the original error.
  - `run_with_job_resources` owns a short-lived job: it requests termination on both normal callback return and failure. Bound resources remain recorded as incomplete cleanup; ambiguous submission retains created resources for reconciliation. It does not infer extraction completion or preserve undownloaded outputs automatically.
- [x] Fix forced SSH in higher-level resource/immediate helpers and expose explicit SSH-off options without changing defaults
  - Live Nginx submission returned HTTP 400 because the application has no SSH support. Added `ssh_enabled=False` to both Python helpers and `--no-ssh` to `jobs submit` / `jobs submit-immediate`, with four reproducing regression cases. Isolated Nginx and Stata jobs then passed live resource binding/cleanup.
- [ ] Add explicit job attach/detach commands after provider support is checked; do not assume runtime changes are supported for every resource/application
  - Deferred on evidence, not on missing write approval alone: upstream `3d08e18` has no container attach/detach handlers, and KubeVirt handlers are no-ops. Discovery exposes no effective per-resource runtime capability. Establish a documented provider/application contract and live effect checks first; submission-time selection is implemented instead. See `docs/reference/api.md`.

### 5. Resource permissions and labels

- [x] Add explicit ACL and label updates for links, IPs, and license activations, with preview/`--yes` and no automatic permission broadening
  - Resource ACLs do not configure authentication inside an exposed application. This phase does not add project-wide role administration or provider infrastructure management.

### 6. Verification, documentation, and release gate

- [x] Add focused tests alongside each implemented phase: HTTP paths/payloads, pagination, nullable bindings, provider/workspace mismatches, SSH-key matching, private-key rejection, confirmation guards, timeouts, and owned-resource cleanup
- [x] Run approved disposable live-write smoke tests for links, CBS license activations, account SSH keys, labels/ACLs, resource-aware CPU jobs, cleanup, SSH output transfer, and startup cancellation
  - Preserve the working account SSH key and all existing resources. Approve the license product and any billable/publicly exposed resource before live writes; account for leftovers after interruptions.
  - On 2026-10-20, tests used `ucloud`, one-vCPU CPU products, isolated web/license templates with no existing file mounts, and a disposable empty recipient group. READ grant/revoke was read back; no users were added to the group and no ports were opened. Final ownership checks found no test resources or running jobs, and existing resources/groups/SSH keys and `.env` were preserved.
- [ ] Live-test successful Public-IP creation/readiness/firewall/labels/ACL/deletion and IP-aware job submission after a nonzero allocation is granted
  - The authorized attempt returned HTTP 402 because quota was zero. Do not bypass quota or reuse/change somebody else's IP. Use an approved compatible application; the default Python template disallows IPs.
- [ ] Validate HTTP application/session routing for Public Links before advertising working public-URL delivery
  - API creation, binding and bound-resource deletion guards passed, but a direct HTTPS probe returned 449. This is not proof that the linked application is serving correctly.
- [ ] If required, verify SSH-key deletion/revocation effects on an already-running job using only a disposable key
  - Account registration/retrieve/duplicate detection/delete passed; provider revocation propagation to existing jobs was not exercised. Preserve the working key.
- [x] Keep the static SSH transfer smoke test working and run the full regression suite
  - Release 0.1.7 verification: 207 tests passed (101 original regression tests plus 106 added management/integration/policy tests). The static example and transfer implementation were unchanged.
  - Wheel and sdist build successfully; archive contents and relative documentation links pass checks. Isolated wheel installation, dependency compatibility, and nine CLI help/version checks pass. OneDrive blocked an in-workspace install with hardlink/file-lock errors; copy-mode installation outside OneDrive passed without a package-code workaround.
- [x] Update `docs/reference/api.md`, existing SSH operations guidance, and relevant README/TODO entries with examples, security notes, ownership rules, and precisely verified capabilities
  - Prepare a release only after validation; commit/push/publication remain a separate explicit request.

## Live machine availability (separate read-only preflight)

- [x] Implement `check_machine_availability(client, products=None)` using one `GET /api/jobs/retrieveProducts` request, with a UTC check timestamp, exact product matching, caller order, and `AVAILABLE`/`BUSY`/`FULL`/`UNKNOWN` results
  - Missing products/statuses are unknown, not available; authentication/network failures remain errors. Return supplied hardware specifications without inferring GPU requirements or adding a cache.
- [x] Add `ucloud catalog machines --live` with provider/category filters and JSON output; preserve the existing static/offline catalog behavior
- [x] Test CPU/full-GPU/MIG sizes, provider/category collisions, caller ordering, missing/unknown statuses, and API errors
- [x] Add an opt-in immediate-start policy after the preflight is tested: consider only caller-approved products, require `AVAILABLE` by default, explicitly opt into `BUSY`, submit nothing when no candidate qualifies, and terminate a submitted job if its startup deadline is exceeded
  - Availability is advisory, not a reservation or an allocation check. Never silently switch to fewer GPUs or MIG; GPU sizing and permitted alternatives stay with the calling integration. Existing submission defaults remain unchanged.

## Local delivery bundles

- [ ] Add a sample delivery bundle generated from a real output directory
- [x] Document the end-to-end run-and-deliver CLI procedure
