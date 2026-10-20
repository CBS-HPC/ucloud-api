# UCloud Workflow CLI reference

The `ucloud` command-line interface is the supported way to operate this project. This document describes its configuration and commands, then lists the Python modules and current UCloud HTTP endpoints used by the CLI. It does not describe an AI agent, a hosted service, or an unattended scheduler.

## Environment variables

`Settings.from_env()` automatically loads `.env` from the current working directory. Run the CLI from the repository root when using the repository's `.env` file.

Required:

- `UCLOUD_TOKEN`
- `UCLOUD_PROJECT`

Optional:

- `UCLOUD_SERVER` - defaults to `https://cloud.sdu.dk`
- `UCLOUD_TEMPLATE_JOB_ID` - use a specific job as the reusable template; preferred source for mounted drives and application/job settings
- `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` - profile-specific template override, for example `UCLOUD_TEMPLATE_JOB_ID_CPU_PYTHON_BATCH`
- `UCLOUD_SSH_ALIAS` - SSH host alias written to the selected SSH config file
- `UCLOUD_SSH_CONFIG_PATH` - SSH config path used by every CLI SSH/SCP command; defaults to `~/.ssh/config`
- `UCLOUD_SSH_IDENTITY_FILE` - optional explicit private-key path; otherwise the CLI adds existing standard private keys beside `UCLOUD_SSH_CONFIG_PATH` to its managed SSH block
- `UCLOUD_WORK_FOLDER` - remote working root, defaults to `/work/moody_agent`
- `UCLOUD_STORAGE_PATH` - optional persistent storage directory used by `ucloud setup`; this is a UCloud `/<drive-id>/folder` path, not an automatic job mount or a `/work/...` path
- `UCLOUD_DEFAULT_SIZE` - default CPU size, for example `128-vcpu`
- `UCLOUD_DEFAULT_HOURS` - default job duration in hours
- `UCLOUD_OUTPUT_DIR` - default local output directory for packaging
- `UCLOUD_DELIVERY_ROOT` - default local delivery archive root

## Token-based setup

```powershell
uv run ucloud setup
```

Setup is the exception to the usual requirement for both token and project: it starts with only a valid API token. Enter it at the hidden prompt, or supply it through `UCLOUD_TOKEN` in the process environment or selected environment file. There is deliberately no setup `--token` flag that would put the secret in shell history. The default server is `https://cloud.sdu.dk`; an override must be an HTTPS origin without embedded credentials, path, query, or fragment.

The command:

1. Browses accessible projects without a `Project` header. Archived projects and projects explicitly marked unable to consume resources are excluded.
2. Selects a project by id or unique title and discovers its accessible writable drives. Drive permissions must include EDIT or ADMIN, and provider support must explicitly indicate a writable filesystem.
3. Retrieves an explicitly configured template, or offers existing jobs in that project as template candidates. Existing `UCLOUD_TEMPLATE_JOB_ID` is retained and verified, not silently replaced by the latest job. If there are no candidates, setup can still configure storage but explains that a known-good template is needed before running jobs.
4. Previews the target directory, defaulting to `/<drive-id>/ucloud-workflow`. An explicit `--storage-path` or existing `UCLOUD_STORAGE_PATH` is used instead. Paths outside the selected drive, drive roots, traversal, and control characters are rejected.
5. Asks for confirmation before any write. It creates missing directories in parent order with `conflictPolicy: REJECT`, verifies them, and reuses existing writable directories. Existing files are never replaced or renamed. Concurrent creation is reconciled by checking the exact directory again.
6. Atomically saves `UCLOUD_SERVER`, the supplied `UCLOUD_TOKEN`, the canonical project id, `UCLOUD_STORAGE_PATH`, `UCLOUD_WORK_FOLDER`, and a selected `UCLOUD_TEMPLATE_JOB_ID`. Other settings and comments are preserved. Changed/symlinked environment files are not overwritten.

When multiple choices exist, interactive setup asks for a selection; it never treats the first result as an implicit default. With `--yes`, ambiguous choices fail unless you supply the corresponding explicit option:

```powershell
# Set UCLOUD_TOKEN securely in this process first, or use the interactive prompt.
uv run ucloud setup `
  --project PROJECT_ID `
  --drive-id DRIVE_ID `
  --template-job-id TEMPLATE_JOB_ID `
  --storage-path /DRIVE_ID/workloads `
  --work-folder /work/ALREADY_MOUNTED_FOLDER/workloads `
  --yes
```

Omit `--storage-path` to use the default folder. Use `--env-file custom.env` to read/update a different local file. Setup does not load an unrelated `.env` or modify the current process environment. Process environment values take precedence over file values, and explicit selection options take precedence over both. Subsequent commands still load `.env` in the current directory; they do not automatically use a custom filename.

**Storage is not automatically mounted.** Setup does not add, remove, or edit template resources or change existing job defaults. Choose a known-good template with the needed drive already mounted. `--work-folder` is the separate Linux path inside that job; setup cannot infer or verify that mapping from the storage path. Existing `UCLOUD_WORK_FOLDER` is retained, while fresh setup defaults to the always-present `/work`. A created storage folder is not proof that job outputs will be written there: configure the correct template mount and working path first. SSH private keys cannot be retrieved from the API; use your existing local key/config and `ucloud ssh-keys check` before an SSH workflow. No keys are generated or registered by setup.

The token is never printed by setup, but saving it means storing plaintext in the environment file. New/replaced files use owner-only mode on POSIX; on Windows they inherit the destination directory's access controls. Keep the file private and outside version control. The repository ignores `.env`, `*.env`, `.env.*`, and setup temporary files; installed users must apply equivalent exclusions in their own repositories.

Authentication, listing, provider, and permission failures are errors, not evidence of an empty workspace. Some providers return HTTP 400 for a missing directory; setup requires a successful paginated parent listing before interpreting that ambiguous response as absence. HTTP 503 remains an error; it never silently changes to another drive. Folder POST timeouts and server failures are not retried automatically. Rerun setup to inspect the deterministic target path before another create attempt. If a folder was created but saving configuration failed, it is retained for reuse rather than deleted; existing configuration remains intact. Setup does not clean up folders, allocate drives, alter ACLs, submit jobs, or broaden token permissions.

Live checks on 2026-10-20 verified project discovery, writable-drive discovery, template validation, and folder previews on six reachable drives. Three other advertised drives returned provider HTTP 503. A separately approved smoke test then selected the writable drive already used by the configured template and created a unique parent folder plus a nested workspace. Both directories were read back; configuration was saved into a disposable local environment file. A second `ucloud setup` reused that configuration and directory without remote writes, preserving an unrelated setting and comment. The working `.env`, existing template, and unrelated drive contents were unchanged; no jobs were submitted. Creation/reuse races, cancellation, failure recovery, and unsafe-path rejection also have mocked/local regression coverage.

Test cleanup moved only the owned, empty test tree into UCloud Trash and removed the disposable local environment file. Direct permanent file deletion returned HTTP 400, so permanent deletion is not claimed and shared Trash was not emptied. This is an operational cleanup limitation, not a setup deletion feature: setup does not delete folders or empty Trash.

The reusable functions are in `ucloud_workflow.setup`: `list_projects(client)`, `list_writable_drives(client)`, `storage_directory_path(drive_id, path=None)`, `prepare_storage_directory(client, path, create=False)`, `template_candidates(client)`, `validate_template(client, template_job_id)`, and `write_setup_env(path, values, original=...)`. `prepare_storage_directory` is read-only unless `create=True`; it returns missing/created paths. Python mutation calls do not inherit CLI confirmation prompts.

Upstream contracts: [projects](https://github.com/SDU-eScience/UCloud/blob/3d08e18c539d364c127b898a147e40151c9708d8/provider-integration/shared/pkg/foundation/projects.go), [drives](https://github.com/SDU-eScience/UCloud/blob/3d08e18c539d364c127b898a147e40151c9708d8/provider-integration/shared/pkg/orchestrators/drives.go), and [files](https://github.com/SDU-eScience/UCloud/blob/3d08e18c539d364c127b898a147e40151c9708d8/provider-integration/shared/pkg/orchestrators/files.go).

## SSH configuration

The CLI writes its managed `Host` block to `UCLOUD_SSH_CONFIG_PATH` and passes that file to each SSH and SCP process with `-F`. If the path is not the normal OpenSSH config, include any required `ProxyJump`, host, or user settings in that file because `-F` does not merge the client's default config.

The CLI writes existing standard private keys found beside the selected config into the managed block. Use `UCLOUD_SSH_IDENTITY_FILE` for a key elsewhere. The CLI never reads or prints private-key contents, and it leaves SSH-agent authentication enabled.

`ucloud workflow run --open-vscode` opens a VS Code Remote-SSH URI. VS Code chooses its own SSH configuration, so configure VS Code's `remote.SSH.configFile` to the same path when `UCLOUD_SSH_CONFIG_PATH` is non-default.

Token-expiry inspection uses the same authenticated client. The configured token must have access to the token-management API; a `uc...` token string does not reveal its own expiry locally.

## Python library reference

The Python modules below implement the CLI and can also be imported by advanced integrations. For routine UCloud operations, prefer the corresponding `ucloud` command. Use `uv run ucloud --help` for the installed command and option list.

### `ucloud version`

Print the installed CLI package version.

### `ucloud_workflow.settings`

#### `Settings`

Immutable configuration object.

Important fields:

- `server`
- `token`
- `project`
- `template_job_id`
- `ssh_alias`
- `work_folder`
- `default_size`
- `default_hours`
- `output_dir`
- `delivery_root`
- `ssh_config_path`
- `ssh_identity_file`
- `storage_path`

#### `Settings.from_env(...) -> Settings`

Loads settings from keyword arguments, environment variables, and `.env`.

#### `Settings.template_job_id_for(profile_name=None) -> str | None`

Resolves the template job id for a job family.

- If `profile_name` is provided and a matching `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` value exists, that value is returned.
- Otherwise it falls back to `Settings.template_job_id`, which comes from `UCLOUD_TEMPLATE_JOB_ID` unless overridden directly.

#### `Settings.resolved_ssh_identity_files() -> tuple[Path, ...]`

Returns the explicit `ssh_identity_file`, when configured, or private keys with standard OpenSSH names beside `ssh_config_path`. It does not set `IdentitiesOnly`, so an existing SSH agent remains available.

### `ucloud_workflow.catalog`

The catalog module defines the standard job families and machine types used by the CLI.

#### `STANDARD_JOB_PROFILES`

Tuple of profile definitions such as:

- `vscode-remote-session`
- `cpu-python-batch`
- `python-package-batch`
- `gpu-batch-inference`
- `delivery-packaging-job`

#### `TEMPLATE_JOB_CATALOG`

Catalog of template-job environment variables.

- Includes the global fallback `UCLOUD_TEMPLATE_JOB_ID`
- Includes one env var per standard job profile

#### `MACHINE_CATALOG`

Static catalog of documented UCloud machine types.

The CPU ladder currently includes:

- `cpu-amd-zen5-1-vcpu`
- `cpu-amd-zen5-2-vcpu`
- `cpu-amd-zen5-4-vcpu`
- `cpu-amd-zen5-8-vcpu`
- `cpu-amd-zen5-16-vcpu`
- `cpu-amd-zen5-32-vcpu`
- `cpu-amd-zen5-64-vcpu`
- `cpu-amd-zen5-128-vcpu`

The GPU ladder currently includes:

- `gpu-nvidia-b200-1-gpu`
- `gpu-nvidia-b200-2-gpu`
- `gpu-nvidia-b200-3-gpu`
- `gpu-nvidia-b200-4-gpu`
- `gpu-nvidia-b200-5-gpu`
- `gpu-nvidia-b200-6-gpu`
- `gpu-nvidia-b200-7-gpu`
- `gpu-nvidia-b200-8-gpu`

The MIG ladder currently includes:

- `gpu-nvidia-b200-1-mig.1g`
- `gpu-nvidia-b200-2-mig.1g`
- `gpu-nvidia-b200-3-mig.1g`
- `gpu-nvidia-b200-4-mig.1g`

`MachineTypeInfo` includes fields for:

- `product`
- `provider`
- `machine_class`
- `cpu_vcpus`
- `cpu_model`
- `memory_gib`
- `memory_type`
- `gpu_count`
- `gpu_model`
- `mig_instances`
- `mig_profile`
- `core_hours_per_hour`
- `gpu_hours_per_hour`
- `gpu_hours_label`
- `status`
- `notes`

#### Helpers

- `profile_by_name(name) -> JobProfile | None`
- `machine_by_product(product) -> MachineTypeInfo | None`
- `machine_products_for_profile(profile_name) -> tuple[MachineTypeInfo, ...]`
- `resolve_template_job_id(profile_name, global_template_job_id=None) -> str | None`

### `ucloud_workflow.client`

#### `UCloudClient(settings, timeout=30.0)`

Thin HTTP client for the UCloud endpoints used by the CLI.

Uses these headers:

- `Authorization: Bearer <token>`
- `Project: <project>` when nonempty; token-only discovery uses `Settings(..., project="")` to omit this header
- `Accept: application/json`

#### Methods

- `request(method, path, params=None, json=None)`
- `browse_wallets(include_children=True)`
- `browse_jobs(items_per_page=1, sort_by="CREATED_AT", include_parameters=True, include_application=False, next_page=None)`
- `browse_projects(items_per_page=100, next_page=None)`
- `browse_drives(items_per_page=100, next_page=None)` - includes filesystem-support metadata
- `retrieve_file(path)`
- `browse_files(path, items_per_page=100, next_page=None)`
- `create_folder(path)` - one bulk item with `conflictPolicy: REJECT`; this low-level method performs a write without an interactive prompt
- `retrieve_job(job_id, include_updates=True)`
- `submit_job(specification)`
- `terminate_job(job_id)`
- `browse_api_tokens(items_per_page=100, filter_hidden=False)` - calls `GET /api/tokens/browse` and returns metadata only
- `retrieve_api_token_options()` - calls `GET /api/tokens/retrieveOptions` for available providers and permission definitions
- `create_api_token(specification)` - calls `POST /api/tokens`; the response contains a token secret only once at `status.token`

#### `UCloudAPIError`

Raised when the UCloud API returns a non-2xx response.

### `ucloud_workflow.tokens`

#### `summarize_api_tokens(response, expiring_within_days=30)`

Converts the `GET /api/tokens/browse` response into non-secret token summaries. It supports UCloud epoch-millisecond `specification.expiresAt` values and marks each token as `active`, `expiring-soon`, `expired`, or `unknown`.

#### CLI

`ucloud tokens status --within-days 30` prints the title, token id, expiry timestamp, remaining days, state, and requested permissions. It does not print or persist token secrets.

`ucloud tokens options` prints the available token providers and permissions for the authenticated user. If UCloud returns an error, use the web UI rather than guessing permission names.

`ucloud tokens create` requires `--title` and exactly one of timezone-aware `--expires-at` or `--valid-for MONTHS`. `--permission NAME:ACTION` is optional and repeatable. `--valid-for` uses calendar months. It only previews the non-secret payload unless the user supplies `--yes`. With `--yes`, it sends `POST /api/tokens`, prints the one-time secret returned by UCloud, but does not write `.env` or revoke any token. A network failure is treated as an unknown outcome and is never retried automatically because the one-time secret could be lost.

#### Token helper functions

- `build_api_token_specification(...)` builds the non-secret `POST /api/tokens` payload.
- `parse_expiry_timestamp(...)` converts a timezone-aware ISO 8601 timestamp to UCloud epoch milliseconds.
- `expiry_timestamp_after_months(...)` calculates a calendar-month expiry in UCloud epoch milliseconds.
- `resolve_expiry_timestamp(...)` enforces exactly one expiry declaration.

The complete operational procedure is documented in [`Token management`](../guides/token-management.md).

### `ucloud_workflow.artifacts`

#### `ARTIFACT_MANIFEST_SCHEMA`

The shared manifest schema identifier: `ucloud.artifact-manifest.v1`.

#### `ArtifactRecord`

One delivered artifact with `path`, `role`, `size_bytes`, `sha256`, and optional `content_type`.

#### `build_artifact_manifest(...)`

Builds the manifest used by delivery archives. `manifest.json` retains a legacy `files` list for simple consumers and adds the full `artifacts` and `provenance` records.

### `ucloud delivery package`

In addition to input directories and `--job-id`, the delivery command accepts `--run-id`, `--template-job-id`, `--machine-product`, repeatable `--workflow-note`, `--variables-json` (a JSON array), and `--metadata-json` (a JSON object). These values are stored in `manifest.json`; API-token secrets must never be included.

### `ucloud_workflow.jobs`

#### `JobLaunchResult`

Returned by `submit_job_from_latest_template(...)`.

Fields:

- `job_id`
- `ssh_command`
- `job_url`
- `product_id`

#### `template_job_specification(client, template_job_id=None) -> dict`

Returns a reusable job specification.

- If `template_job_id` is set, the code retrieves that job and uses its spec, including existing resources such as mounted drives.
- Otherwise it uses the latest job returned by `/api/jobs/browse`.

#### `build_job_specification(template, *, size=None, product=None, hours, name=None, ssh_enabled=True, mounts=None, read_only_mounts=None) -> dict`

Deep-copies a template specification. Select its machine with exactly one of these modes:

- `size="8-vcpu"`: backward-compatible CPU selection, producing `cpu-amd-zen5-8-vcpu` in category `cpu-amd-zen5` with provider `ucloud`.
- `product={"id": ..., "category": ..., "provider": ...}`: an explicit product reference for CPU, full GPU, MIG, or another provider.
- Omit both `size` and `product`: retain the template's existing product unchanged.

Combining `size` and `product` raises `ValueError`. Every selected product must contain non-empty string values for `id`, `category`, and `provider`. `size` accepts positive CPU sizes such as `8-vcpu`, not full GPU/MIG product ids.

The helper sets the time allocation, SSH enablement, and optional job name. It preserves application settings, parameters, mounted drives, public links, and other template resources. Explicit file/folder mounts are merged only when `mounts` or `read_only_mounts` are passed; this low-level path remains unverified against a real job.

#### `submit_job_from_latest_template(...) -> JobLaunchResult`

Submits a job based on the chosen template, using the same `size` / `product` / unchanged-template selection as `build_job_specification`. `JobLaunchResult.product_id` contains the id actually submitted, not a CPU-derived placeholder.

The chosen template provides existing resources such as mounted drives; callers should pass `mounts` only for explicit low-level overrides. The caller chooses the machine and remains responsible for application compatibility, quota, and any GPU-sizing policy.

```python
from ucloud_workflow.jobs import submit_job_from_latest_template

launched = submit_job_from_latest_template(
    client,
    template_job_id=settings.template_job_id,
    hours=1,
    product={
        "id": "gpu-nvidia-b200-1-gpu",
        "category": "gpu-nvidia-b200",
        "provider": "ucloud",
    },
)
```

For one MIG slice, use `id="gpu-nvidia-b200-1-mig.1g"` with the same category and provider. To retain the template machine, omit `size` and `product` entirely. Reusing a public-link resource preserves its identifier; review resource sharing before running concurrent jobs from the same template.

#### `wait_for_running_job(client, job_id, timeout_seconds=600, poll_interval_seconds=5)`

Polls the job until UCloud exposes a usable SSH command.

#### `update_ssh_config(ssh_command, alias, config_path, identity_files=()) -> dict`

Writes or replaces a managed SSH config block, including configured private-key paths when available.

#### `open_in_vscode(alias, folder) -> bool`

Opens the remote folder in VS Code when the local `code` CLI is available.

### `ucloud_workflow.transfer`

#### `RemotePythonJobSpec`

Generic runner specification for a remote Python job.

Fields:

- `script_path`
- `upload_paths`
- `setup_commands`
- `script_args`
- `output_paths`
- `local_output_root`
- `job_name_prefix`

#### `RemotePythonJobResult`

Returned by `run_remote_python_job(...)`.

Fields:

- `job_id`
- `run_id`
- `remote_dir`
- `local_output_dir`
- `downloaded_paths`
- `job_report_path`

#### `run_remote_python_job(settings, spec, *, name=None, template_job_id=None, product=None, use_template_product=False) -> RemotePythonJobResult`

Python implementation behind the `ucloud workflow python-job` command.

Behavior:

1. submits a fresh UCloud job on the selected CPU, GPU, or MIG product
2. waits for UCloud to publish an SSH command
3. probes `ssh <alias> true` until the endpoint accepts a noninteractive connection
4. creates a unique remote directory under `settings.work_folder`
5. uploads the script and any additional files/directories
6. runs any setup commands, for example `pip install`
7. executes the Python script over SSH
8. downloads explicitly named output files
9. downloads `/work/job-report.csv` if it exists
10. analyzes the utilization report when present
11. terminates the UCloud job in a `finally` block

`template_job_id` may be passed explicitly when the caller wants a specific template job instead of the fallback stored in `Settings.template_job_id`.

This higher-level runner retains `settings.default_size` as its CPU default for backward compatibility. Pass a complete `product` reference to override that default, or `use_template_product=True` to keep the template machine. Passing both raises `ValueError` before submitting a job.

Every SSH/SCP process is noninteractive, time-bounded, and receives `-F <Settings.ssh_config_path>`. On Windows, a timeout runs `taskkill /T /F` for the transport process tree; on POSIX, the process group is killed. `RemoteCommandTimeoutError` and `SSHReadinessError` intentionally omit remote command text, so callers can safely record pre-execution failures.

#### `SSHTransportError`

With the default `check=True`, `run_command(...)` raises this error when the local `ssh` or `scp` process exits with code `255`. This represents an SSH transport failure after the process completed, not a local timeout. Its fields are `command`, `returncode`, `stdout`, `stderr`, and `operation` (`ssh` or `scp`). Callers should avoid logging the raw command or output unless they first redact sensitive values.

Other nonzero SSH/SCP statuses remain `RuntimeError`; `check=False` always returns `CompletedProcess` for status inspection.

#### `run_ssh_transfer_demo(settings, ..., template_job_id=None, product=None, use_template_product=False) -> SSHTransferDemoResult`

Proof-of-concept smoke test that remains available for validation.

Returned result fields:

- `job_id`
- `run_id`
- `local_output_path`
- `job_report_path`
- `remote_dir`

It keeps the following files as its demo payload:

- `examples/worker.py`
- `examples/dummy_input.txt`
- if present, `/work/job-report.csv` is downloaded to `examples/job-report.csv`

`template_job_id` may also be passed explicitly for the demo workflow.

The demo accepts the same `product` and `use_template_product` options as `run_remote_python_job`, while keeping its existing CPU default and static payload. `examples/ssh_transfer_job.py` remains an unchanged CPU-default smoke-test wrapper.

#### Other helpers

- `run_command(args, timeout_seconds=..., command_name=...)`
- `wait_for_ssh_ready(alias, config_path=None, attempts=6, retry_seconds=5, probe_timeout_seconds=25, timeout_seconds=None)`
- `remote_mkdir(alias, remote_dir, config_path=None, timeout_seconds=180)`
- `build_python_run_command(script_name, script_args)`
- `build_pip_install_command(package_name, editable=False)`
- `remote_work_root(settings)`
- `remote_job_directory(settings, run_id, job_id)`
- `upload_paths_to_remote(alias, remote_dir, upload_paths, config_path=None, timeout_seconds=900)`
- `verify_remote_uploads(alias, remote_dir, filenames, config_path=None, timeout_seconds=120)`

`run_setup_stage(...)` prints flushed start, completion, and failure logs with the configured budget. The standard budgets are 180 seconds for remote workspace preparation, 15 minutes for upload/download stages, and 30 minutes for individual setup commands. The Python workload itself receives the requested UCloud allocation plus five minutes.

### `ucloud_workflow.scripts`

#### `ExtractionScriptSpec`

Metadata container for a local starter extraction script.

#### `write_extraction_script(path, spec) -> Path`

Creates a local starter extraction script on disk. It does not generate code through an AI service.

### `ucloud_workflow.delivery`

The delivery packager creates a standardized zip archive containing:

- data files
- documentation
- scripts
- manifest metadata

The CLI entry point is `ucloud delivery package`.

## CLI command reference

Run the commands with `uv run`.

### Root commands

- `ucloud setup`
- `ucloud wallets`
- `ucloud jobs submit`
- `ucloud jobs wait`
- `ucloud jobs stop`
- `ucloud catalog profiles`
- `ucloud catalog templates`
- `ucloud catalog machines`
- `ucloud tokens status`
- `ucloud tokens options`
- `ucloud tokens create`
- `ucloud delivery package`
- `ucloud workflow scaffold-script`
- `ucloud workflow run`
- `ucloud workflow ssh-transfer`
- `ucloud workflow python-job`
- `ucloud workflow analyze-utilization`

All job-launching commands accept `--profile` to pick a named job family from the catalog. The profile controls which `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` variable is consulted before the global fallback.

### Machine selection

`ucloud jobs submit`, `ucloud workflow run`, `ucloud workflow python-job`, and `ucloud workflow ssh-transfer` accept:

- `--product-id`, `--product-category`, and `--product-provider`: supply all three together to select an exact product reference.
- `--use-template-product`: retain the selected template's machine instead of applying `UCLOUD_DEFAULT_SIZE`.

`jobs submit`, `workflow run`, and `workflow python-job` also retain `--size` for CPU-only overrides. Explicit product options cannot be combined with `--size`; `--use-template-product` cannot be combined with either. Partial product references and conflicting options fail before API calls.

With no machine-selection options, these CLI commands and the high-level Python runners retain the existing `UCLOUD_DEFAULT_SIZE` CPU behavior. Low-level `build_job_specification` and `submit_job_from_latest_template` instead retain the template machine when neither `size` nor `product` is passed. A `--profile gpu-batch-inference` selects a template source; it does not implicitly choose GPU hardware.

```powershell
# Submit one full B200 GPU using the configured template; stop it when finished.
uv run ucloud jobs submit `
  --product-id gpu-nvidia-b200-1-gpu `
  --product-category gpu-nvidia-b200 `
  --product-provider ucloud `
  --hours 1
uv run ucloud jobs stop JOB_ID

# Retain a GPU/MIG template's existing product for the SSH smoke test.
uv run ucloud workflow ssh-transfer --use-template-product
```

Use the exact product reference from a working UCloud job specification. Display labels in the static machine catalog are not substitutes for API provider/category identifiers. The CLI does not query live product availability or calculate GPU requirements.

### `ucloud workflow ssh-transfer`

Demo command kept as a smoke test.

Inputs from `.env`:

- `UCLOUD_TEMPLATE_JOB_ID`
- `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>`
- `UCLOUD_SSH_ALIAS`
- `UCLOUD_WORK_FOLDER`

Behavior:

- uploads `examples/worker.py` and `examples/dummy_input.txt`
- inherits drives and job settings from the selected template job
- runs `worker.py` on the remote job
- downloads `dummy_output.txt` back to `examples/dummy_output.txt`
- terminates the job

### `ucloud workflow python-job`

Remote Python runner.

Required:

- `--script`

Optional:

- `--profile` - use a profile-specific template job id
- `--package` - local package directory to upload and install
- `--upload` - extra file or directory to upload, repeatable
- `--install-command` - extra remote setup command, repeatable
- `--arg` - script argument, repeatable
- `--output` - remote output path to download, repeatable
- `--editable-package` - install the package in editable mode
- `--local-output-root` - local directory for downloaded files
- if `/work/job-report.csv` exists, download it alongside the outputs and print a utilization recommendation
- when the launched job has a known machine product id, the utilization report also includes a next-machine suggestion

Typical use:

```bash
uv run ucloud workflow python-job --script path/to/main.py --package path/to/local-package --output output/result.json
```

### `ucloud workflow analyze-utilization`

Analyze a downloaded `job-report.csv` and print a size recommendation.

Required:

- report path argument

Optional:

- `--output` - write the rendered Markdown analysis to a file
- `--current-machine` - current UCloud product id for a next-machine suggestion

### `ucloud_workflow.utilization`

#### `analyze_job_report(report_path, current_machine_product=None) -> UtilizationAnalysis`

Parses a utilization report and returns:

- a summary of the observed metric series, including CPU, memory, and optional GPU metrics
- a recommendation action: `decrease`, `keep`, or `increase`
- supporting reasons
- if `current_machine_product` is provided, a concrete next-machine suggestion from the catalog

The analyzer is intentionally conservative about memory pressure because that is the main crash risk in these jobs.

#### `render_utilization_analysis(analysis) -> str`

Renders the analysis as Markdown.

#### `examples/analyze_job_report.py`

Standalone script wrapper around the same analyzer.

Optional `--current-machine` prints a concrete next-machine suggestion.

## Resource and SSH-key management

These commands are explicit operator actions, not automatic provisioning around job runs. They use the existing `.env` settings. SSH public keys are account-owned; Public Links, Public IPs, and license activations are managed in the configured workspace.

### Read-only commands

```powershell
uv run ucloud links list --json
uv run ucloud links products --json
uv run ucloud links show RESOURCE_ID --json
uv run ucloud ips list --json
uv run ucloud ips products --json
uv run ucloud licenses list --json
uv run ucloud licenses products --json
uv run ucloud ssh-keys list --json
uv run ucloud ssh-keys show KEY_ID --json
uv run ucloud ssh-keys check
uv run ucloud ssh-keys check --public-key .\keys\id_ed25519.pub
```

List commands follow pagination. SSH output contains titles, ids, creation timestamps, and computed fingerprints, not public-key text. The key check ignores comments; without a usable public-key sidecar it reports `UNVERIFIABLE`, not proof that SSH-agent authentication will fail. It never registers a key automatically.

### Controlled writes

Resource creation takes a JSON specification file containing a complete `product` reference (`id`, `category`, `provider`). Get those values from that resource's `products` command, not static catalog display labels. For example, `ip.json` could contain:

```json
{
  "product": {
    "id": "public-ip",
    "category": "public-ip",
    "provider": "ucloud"
  }
}
```

Commands preview unless `--yes` is supplied. Preview may perform read-only discovery but does not allocate resources or write operation records.

```powershell
uv run ucloud ips create --spec .\ip.json
# Explicitly allocate only after reviewing the preview, allocation, and exposure.
uv run ucloud ips create --spec .\ip.json --yes --wait --timeout 180
uv run ucloud links create --spec .\link.json
uv run ucloud licenses activate --spec .\license.json
uv run ucloud links delete RESOURCE_ID
uv run ucloud ips delete RESOURCE_ID
uv run ucloud licenses delete RESOURCE_ID
uv run ucloud ssh-keys register --public-key .\keys\id_ed25519.pub --title "Workstation key"
uv run ucloud ssh-keys delete KEY_ID
```

Add `--yes` to confirm any of the preview-only examples. Public Link specifications additionally require `domain`, validated against the advertised provider prefix/suffix. IP specifications may include `firewall: {"openPorts": [...]}`; omission becomes an empty port list. This implementation refuses IP creation without advertised firewall support because it cannot enforce closed-by-default ports. Each port range needs integer `start`/`end` values within 1..65535 and `protocol` equal to `TCP` or `UDP`.

License activation accepts an existing provider-configured product, not a vendor key or license-server configuration. Discovery is not proof of allocation, write permission, or license entitlement. Exposing an application does not configure its authentication.

Public-key input must be a single OpenSSH key in a `.pub` file, validated locally using bounded `ssh-keygen`. Private-key markers, unsupported formats, and oversized files are rejected. Registration skips an already registered public key. Deleting an account key can affect other workflows; revocation on already-running jobs is not certified by this implementation.

### Updates, readiness, and recovery

The three resource groups support `wait RESOURCE_ID --timeout SECONDS`, `labels RESOURCE_ID --spec FILE`, and `acl RESOURCE_ID --spec FILE`. IPs also support `firewall RESOURCE_ID --spec FILE`. Updates preview unless `--yes` is present. A labels file is a string-to-string object; an ACL file contains explicit `added` and `deleted` lists in UCloud's ACL format; a firewall file contains an explicit `openPorts` list. ACL changes are not inferred from project roles or automatically broadened.

Deletion checks visibility in the selected workspace, then retrieves the resource and refuses deletion if it is bound or its binding state cannot be established. Readiness polling has a finite budget. A readiness timeout does not delete the allocation.

Confirmed creations write an atomic JSON operation record under `artifacts/resource-operations/` (override with `--operation-dir`). Records contain the namespace, workspace, confirmed resource id, and outcome; they omit API secrets, public-key text, and full specifications. Transport failures, server failures, and malformed success responses are treated as unknown creation outcomes. There is no automatic POST retry. Reconcile `pending`/`unknown` records against the workspace/account before retrying; do not delete unrelated resources. Resources can persist independently of jobs, and these commands do not perform automatic cleanup.

The reusable Python functions live in `ucloud_workflow.resources` and `ucloud_workflow.ssh_keys`; they accept an existing `UCloudClient`. Python mutation functions execute when explicitly called; CLI preview/`--yes` is not an HTTP-client permission system. Use `prepare_resource` for a read-only resource-specification preflight. New management errors intentionally omit raw HTTP bodies; `CreateOutcomeUnknownError` distinguishes ambiguous creation from a known rejection. Its `operation_record` identifies the local journal; if saving a confirmed ID fails, `resource_id` retains that ID for reconciliation without putting it in the exception message. Interrupted POSTs also require reconciliation.

### Job resource selection and owned cleanup

`ucloud jobs submit --resources resources.json` and `submit_job_from_latest_template(..., resource_selection=...)` accept this selection shape:

```json
{
  "links": ["EXISTING_LINK_ID"],
  "ips": ["EXISTING_IP_ID"],
  "licenses": {"application_license_parameter": "EXISTING_LICENSE_ID"}
}
```

Omit unused fields. This job submission is an explicit write, just like ordinary `jobs submit`; it is not a management-command preview. Existing template resources, mounts, other parameters, and machine-selection defaults remain intact. Links and IPs are deduplicated by type and ID. Named license selections deliberately replace only those named parameter values.

Job submission still requests SSH by default. Use `jobs submit --no-ssh`, `jobs submit-immediate --no-ssh`, or the Python helpers' `ssh_enabled=False` for web/VNC/batch applications that do not support SSH. Startup detection does not require an SSH endpoint when this is disabled. SSH transfer workflows continue to require SSH and are unchanged.

Overrides retrieve the selected template with `includeApplication=true`. The resolved application must match its name/version, and the selected compute product must advertise an enabled backend. Additional links require application `allowPublicLink` and backend `web`; IPs require application `allowPublicIp`. License names must be declared `license_server` parameters. Resources must be visible in the configured workspace, READY, advertised by their provider, and on the same provider as the compute product. Links/IPs must have a known, unbound state. Licenses can be shared as permitted by UCloud. Payload types are `ingress`, `network`, and `license_server`, respectively. These are conservative preflight checks, not a guarantee of allocation, permission, or provider acceptance; missing/unsupported metadata fails closed. No new metadata requests occur on the unchanged default submission path.

For deliberate per-run creation, Python integrations can use `ucloud_workflow.job_resources.run_with_job_resources`:

```python
from ucloud_workflow.job_resources import RunResourceRequest, run_with_job_resources
from ucloud_workflow.jobs import wait_for_running_job

def execute_and_download(launch):
    job, ssh_command = wait_for_running_job(client, launch.job_id)
    return my_transfer_and_extraction(job, ssh_command)

result = run_with_job_resources(
    client,
    execute_and_download,
    template_job_id=template_job_id,
    hours=1,
    existing={"links": [existing_link_id]},
    requests=[RunResourceRequest("licenses", {"product": license_product}, "seat")],
)
```

The example assumes an open `client`, a compatible template declaring the `seat` license parameter and allowing Public Links, approved license entitlement/product, and your own `my_transfer_and_extraction` callback. Supplying `requests` allocates real resources when called; there is no implicit CLI confirmation inside this Python helper. The callback owns startup waiting, execution, and download; the helper does not infer script completion from UCloud status. Without a `size` or `product` override, this low-level helper keeps the template machine.

The helper validates all requested specs/application compatibility before creating anything, waits for READY, records created and explicitly reused IDs, submits one job, and invokes the callback. **It always requests termination of its own submitted job on callback completion or failure**, then attempts deletion only of confirmed resources it created in this invocation. Template resources, reused resources, and account SSH keys are never automatically deleted. Do not use this short-lived-run helper when you intend to keep the job or undownloaded outputs alive after the callback.

`run_with_job_resources(..., ssh_enabled=False)` permits non-SSH applications such as the isolated web and VNC applications used in live validation. The default remains `True`; the callback must not call SSH helpers when SSH is disabled.

`ManagedResourceRunResult` contains `value`, `operation_record`, and `cleanup_complete`. A successful termination request is not proof that provider unbinding has finished; bound/missing-binding resources are retained and reported as incomplete rather than forcibly detached or deleted. A cleanup failure does not replace the original callback/provisioning error; a safe note and the run journal identify incomplete recovery. Journals omit secrets/specifications but contain operational IDs, so keep them local. If job submission times out or has an ambiguous response, no submission retry occurs and created resources are retained: an unknown job may still use them. Unknown resource creations likewise need manual reconciliation. Python mutation helpers and operation journals are not an authentication boundary or a cross-process garbage collector.

### Runtime attach and detach: deferred

The upstream API defines `POST /api/jobs/attachResource` and `/detachResource` with a single `{jobId, resource}` object, not a bulk body. This CLI intentionally does not expose them yet. Product discovery has no per-resource runtime-effectiveness flag. In inspected upstream revision [`3d08e18`](https://github.com/SDU-eScience/UCloud/tree/3d08e18c539d364c127b898a147e40151c9708d8), the [container service](https://github.com/SDU-eScience/UCloud/blob/3d08e18c539d364c127b898a147e40151c9708d8/provider-integration/im2/pkg/integrations/k8s/containers/00_module.go) installs no attach/detach handlers, while the [KubeVirt handlers](https://github.com/SDU-eScience/UCloud/blob/3d08e18c539d364c127b898a147e40151c9708d8/provider-integration/im2/pkg/integrations/k8s/kubevirt/00_module.go) return success without implementing a runtime change. HTTP success alone therefore cannot establish that an application gained/lost a resource. A documented, effective provider/application contract and separately authorized live effect checks are required before exposing these commands. Select resources at job submission in the meantime.

### Live machine availability

```powershell
uv run ucloud catalog machines --live --provider ucloud --category gpu-nvidia-b200 --json
```

`ucloud_workflow.availability.check_machine_availability(client, products=None)` performs one `GET /api/jobs/retrieveProducts` request and returns an `AvailabilitySnapshot` with an aware UTC check timestamp. Pass a sequence of complete product references to retain caller order and check exact sizes. Each machine reports the reference, `found`, `queue_status`, and supplied hardware fields. Missing products/statuses or unrecognized status values become `UNKNOWN`; failed/malformed requests remain errors. Provider/category collisions are not merged.

`AVAILABLE`, `BUSY`, and `FULL` are advisory provider snapshots, not reservations or quota checks. No local availability cache or GPU-sizing policy is introduced. The static/offline catalog remains the default; live mode uses provider/category filters rather than static profile filters.

### Opt-in immediate startup

Create `candidates.json` as a non-empty array of full product references, in preference order. For example, explicitly approving only these two full-GPU sizes:

```json
[
  {"id": "gpu-nvidia-b200-1-gpu", "category": "gpu-nvidia-b200", "provider": "ucloud"},
  {"id": "gpu-nvidia-b200-2-gpu", "category": "gpu-nvidia-b200", "provider": "ucloud"}
]
```

```powershell
# Read-only preview; it does not create a job.
uv run ucloud jobs submit-immediate --candidates .\candidates.json
# Recheck and submit one approved product, with a startup deadline.
uv run ucloud jobs submit-immediate --candidates .\candidates.json --yes --startup-timeout 120
```

Use a compatible `UCLOUD_TEMPLATE_JOB_ID` or `--profile`. Optional `--resources FILE` uses the same selection schema above. Python callers use `submit_immediate_job(client, products=approved_products, hours=1, template_job_id=..., startup_timeout_seconds=120)` from `ucloud_workflow.availability`.

Each submission checks one fresh snapshot and chooses the first approved `AVAILABLE` product. `--allow-busy` / `allow_busy=True` explicitly permits BUSY in the same caller preference order; FULL, UNKNOWN, and missing products never qualify. Nothing is submitted if none qualifies. It never discovers alternative GPU counts, selects MIG automatically, resizes workloads, retries a POST, or tries another machine after startup fails. Budget values must be finite and positive.

Startup polling caps each HTTP timeout to the remaining budget and accepts only observed RUNNING before the deadline; it does not wait for SSH or assert script completion. On deadline, terminal-before-running state, polling failure, or interruption, it immediately requests job termination. HTTP timeouts bound network operations, not a strict total wall-clock SLA; termination is also a bounded request and may fail. `ImmediateStartError` exposes `job_id` for caller recovery and `termination_succeeded` (request accepted, not proof of terminal state), without including operational IDs or raw HTTP bodies in its message. Interruptions preserve their original exception. After a successful startup, lifecycle/termination belongs to the caller. Existing submission commands do not acquire this policy by default.

### Verification status and remaining integration

Read-only discovery passed on 2026-10-19. With separate operator approval, disposable live-write tests were then performed on 2026-10-20 in the configured project, using `ucloud` and one-vCPU CPU jobs:

| Capability | Live result |
| --- | --- |
| Public Links | Create, READY, label read-back, deletion, binding to an isolated Nginx job, and refusal to delete a bound link passed. |
| License activations | `STATA-MP19.5-CBS` create/READY/labels/delete passed; Stata 19.5 reached RUNNING with a named `server_lic` license resource. |
| Resource ACLs | READ grant and revoke passed for disposable links and licenses, with permission read-back. The temporary recipient project group contained no users and was deleted afterward. |
| Account SSH keys | Temporary public-key registration, retrieve, duplicate detection, and deletion passed; the original working key was preserved. |
| Existing-resource submission | An explicitly selected disposable license was bound to a running job and survived job termination, then was separately deleted by its test owner. |
| Managed ownership/cleanup | Newly created link/license resources were cleaned up after successful callbacks; a deliberate pre-execution abort preserved the original error and stopped its job. |
| Immediate startup | A live availability-selected CPU job reached RUNNING; a deliberately short startup deadline triggered termination, and terminal state was independently confirmed. |
| SSH execution and output | A Python worker was uploaded and executed, produced `dummy.txt` in an isolated `/work` subdirectory, and the downloaded content matched. The job was stopped afterward. |
| Public IPs/firewall | Creation was rejected with HTTP 402; the project's IP quota was zero. No IP was allocated. Successful IP create/readiness/firewall/ACL/label/delete and IP-aware job submission still need a nonzero allocation and an approved compatible template. No ports were opened. |
| Public URL serving | A direct HTTPS probe returned 449 despite confirmed resource/job binding. HTTP application/session routing remains unverified; API binding is not proof of a working public website. |

The live run found and reproduced forced SSH in the new higher-level helpers rejecting a web-only application with HTTP 400. The fix exposes an explicit SSH-off choice without changing existing defaults, with regression tests for both Python helpers and CLI commands. Web/license test jobs used isolated templates without existing file mounts; only disposable test data was used. Existing resources, account keys, project groups, and `.env` were preserved; independent final checks found no owned test resources or running test jobs. Local operational journals are retained under ignored `artifacts/`, without token secrets or retained temporary private keys.

These results verify the exercised provider/products and scenarios, not every advertised SKU, provider, or failure mode. Live account-key revocation effects on already-running jobs remain unverified. Runtime attach/detach remains explicitly deferred for the provider-contract reason above. The static SSH transfer example and normal template-inheritance defaults remain unchanged.

## UCloud HTTP endpoints used by the CLI

- `GET /api/projects/v2/browse`
- `GET /api/files/collections/browse`
- `GET /api/files/retrieve`
- `GET /api/files/browse`
- `POST /api/files/folder`

The CLI currently uses these endpoints:

- `GET /api/accounting/v2/browseWallets`
- `GET /api/jobs/browse`
- `GET /api/jobs/retrieve`
- `POST /api/jobs`
- `POST /api/jobs/terminate`
- `GET /api/tokens/browse`
- `GET /api/tokens/retrieveOptions`
- `POST /api/tokens`
- `GET /api/{ingresses|networkips|licenses}/browse`
- `GET /api/{ingresses|networkips|licenses}/retrieve`
- `GET /api/{ingresses|networkips|licenses}/retrieveProducts`
- `POST` / `DELETE /api/{ingresses|networkips|licenses}`
- `POST /api/{ingresses|networkips|licenses}/updateAcl`
- `POST /api/{ingresses|networkips|licenses}/updateLabels`
- `POST /api/networkips/firewall`
- `GET /api/ssh/browse` and `GET /api/ssh/retrieve`
- `POST /api/ssh` and `DELETE /api/ssh`
- `GET /api/jobs/retrieveProducts`

Required request headers:

- `Authorization: Bearer <token>`
- `Project: <project>`

## Notes

- `examples/ssh_transfer_job.py` stays in the repository as the smoke-test/demo command.
- `ucloud workflow python-job` is the supported command for "upload script, install package, run, download outputs".
