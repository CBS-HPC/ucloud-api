# API Reference

This document describes the code-level API of the Python workflow toolkit and the current UCloud HTTP endpoints it uses.

## Environment variables

`Settings.from_env()` loads `.env` automatically from the project root.

Required:

- `UCLOUD_TOKEN`
- `UCLOUD_PROJECT`

Optional:

- `UCLOUD_SERVER` - defaults to `https://cloud.sdu.dk`
- `UCLOUD_TEMPLATE_JOB_ID` - use a specific job as the reusable template; preferred source for mounted drives and application/job settings
- `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` - profile-specific template override, for example `UCLOUD_TEMPLATE_JOB_ID_CPU_PYTHON_BATCH`
- `UCLOUD_MOUNT_PATH` - legacy/advanced direct mount value; current workflow runners prefer template-job resources and do not inject this automatically
- `UCLOUD_SSH_ALIAS` - SSH host alias written to `~/.ssh/config`
- `UCLOUD_WORK_FOLDER` - remote working root, defaults to `/work/moody_agent`
- `UCLOUD_DEFAULT_SIZE` - default CPU size, for example `128-vcpu`
- `UCLOUD_DEFAULT_HOURS` - default job duration in hours
- `UCLOUD_OUTPUT_DIR` - default local output directory for packaging
- `UCLOUD_DELIVERY_ROOT` - default local delivery archive root

## Python package API

### `ucloud version`

Print the installed package version.

### `ucloud_workflow.settings`

#### `Settings`

Immutable configuration object.

Important fields:

- `server`
- `token`
- `project`
- `template_job_id`
- `mount_path`
- `ssh_alias`
- `work_folder`
- `default_size`
- `default_hours`
- `output_dir`
- `delivery_root`
- `ssh_config_path`

#### `Settings.from_env(...) -> Settings`

Loads settings from keyword arguments, environment variables, and `.env`.

#### `Settings.mount_paths -> list[str]`

Returns a one-item list when `UCLOUD_MOUNT_PATH` is set, otherwise an empty list.
This remains available for explicit low-level mount handling, but the main workflow runners rely on template-job resources.

#### `Settings.template_job_id_for(profile_name=None) -> str | None`

Resolves the template job id for a job family.

- If `profile_name` is provided and a matching `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` value exists, that value is returned.
- Otherwise it falls back to `Settings.template_job_id`, which comes from `UCLOUD_TEMPLATE_JOB_ID` unless overridden directly.

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

Thin HTTP client for the UCloud endpoints used by the workflow.

Uses these headers on every request:

- `Authorization: Bearer <token>`
- `Project: <project>`
- `Accept: application/json`

#### Methods

- `request(method, path, params=None, json=None)`
- `browse_wallets(include_children=True)`
- `browse_jobs(items_per_page=1, sort_by="CREATED_AT", include_parameters=True)`
- `retrieve_job(job_id, include_updates=True)`
- `submit_job(specification)`
- `terminate_job(job_id)`

#### `UCloudAPIError`

Raised when the UCloud API returns a non-2xx response.

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

#### `build_job_specification(template, size, hours, name=None, ssh_enabled=True, mounts=None, read_only_mounts=None) -> dict`

Clones a template spec and rewrites:

- product
- time allocation
- SSH enablement
- optional job name

Existing template `resources` are preserved. Explicit file/folder mounts are merged only when `mounts` or `read_only_mounts` are passed.

#### `submit_job_from_latest_template(...) -> JobLaunchResult`

Submits a CPU job based on the chosen template.
The chosen template provides existing resources such as mounted drives; callers should pass `mounts` only for explicit low-level overrides.

#### `wait_for_running_job(client, job_id, timeout_seconds=600, poll_interval_seconds=5)`

Polls the job until UCloud exposes a usable SSH command.

#### `update_ssh_config(ssh_command, alias, config_path) -> dict`

Writes or replaces a managed SSH config block.

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

#### `run_remote_python_job(settings, spec, name=None, template_job_id=None) -> RemotePythonJobResult`

Generic workflow used for the real use case.

Behavior:

1. submits a fresh UCloud CPU job
2. waits for SSH availability
3. creates a unique remote directory under `settings.work_folder`
4. uploads the script and any additional files/directories
5. runs any setup commands, for example `pip install`
6. executes the Python script over SSH
7. downloads explicitly named output files
8. downloads `/work/job-report.csv` if it exists
9. analyzes the utilization report when present
10. terminates the UCloud job in a `finally` block

`template_job_id` may be passed explicitly when the caller wants a specific template job instead of the fallback stored in `Settings.template_job_id`.

#### `run_ssh_transfer_demo(settings, ..., template_job_id=None) -> SSHTransferDemoResult`

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

#### Other helpers

- `build_python_run_command(script_name, script_args)`
- `build_pip_install_command(package_name, editable=False)`
- `remote_work_root(settings)`
- `remote_job_directory(settings, run_id, job_id)`
- `upload_paths_to_remote(alias, remote_dir, upload_paths)`
- `verify_remote_uploads(alias, remote_dir, filenames)`

### `ucloud_workflow.scripts`

#### `ExtractionScriptSpec`

Metadata container for generated extraction scripts.

#### `write_extraction_script(path, spec) -> Path`

Creates a starter extraction script on disk.

### `ucloud_workflow.delivery`

The delivery packager creates a standardized zip archive containing:

- data files
- documentation
- scripts
- manifest metadata

The CLI entry point is `ucloud delivery package`.

## CLI API

Run the commands with `uv run`.

### Root commands

- `ucloud wallets`
- `ucloud jobs submit`
- `ucloud jobs wait`
- `ucloud jobs stop`
- `ucloud catalog profiles`
- `ucloud catalog templates`
- `ucloud catalog machines`
- `ucloud delivery package`
- `ucloud workflow scaffold-script`
- `ucloud workflow run`
- `ucloud workflow ssh-transfer`
- `ucloud workflow python-job`
- `ucloud workflow analyze-utilization`

All job-launching commands accept `--profile` to pick a named job family from the catalog. The profile controls which `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` variable is consulted before the global fallback.

### `ucloud workflow ssh-transfer`

Demo workflow kept as a smoke test.

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

Generic remote Python runner.

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

## Current UCloud HTTP endpoints

The project currently uses these public endpoints only:

- `GET /api/accounting/v2/browseWallets`
- `GET /api/jobs/browse`
- `GET /api/jobs/retrieve`
- `POST /api/jobs`
- `POST /api/jobs/terminate`

Required request headers:

- `Authorization: Bearer <token>`
- `Project: <project>`

## Notes

- `examples/ssh_transfer_job.py` stays in the repository as the smoke-test/demo workflow.
- The generic runner is the path to use for the real “upload script, install package, run, download outputs” flow.
