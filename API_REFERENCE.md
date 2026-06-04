# API Reference

This document describes the code-level API of the Python workflow toolkit and the current UCloud HTTP endpoints it uses.

## Environment variables

`Settings.from_env()` loads `.env` automatically from the project root.

Required:

- `UCLOUD_TOKEN`
- `UCLOUD_PROJECT`

Optional:

- `UCLOUD_SERVER` - defaults to `https://cloud.sdu.dk`
- `UCLOUD_TEMPLATE_JOB_ID` - use a specific job as the reusable template
- `UCLOUD_MOUNT_PATH` - mount one UCloud path; omitted means no mount resources
- `UCLOUD_SSH_ALIAS` - SSH host alias written to `~/.ssh/config`
- `UCLOUD_WORK_FOLDER` - remote working root, defaults to `/work/moody_agent`
- `UCLOUD_DEFAULT_SIZE` - default CPU size, for example `128-vcpu`
- `UCLOUD_DEFAULT_HOURS` - default job duration in hours
- `UCLOUD_OUTPUT_DIR` - default local output directory for packaging
- `UCLOUD_DELIVERY_ROOT` - default local delivery archive root

## Python package API

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

#### `template_job_specification(client, template_job_id=None) -> dict`

Returns a reusable job specification.

- If `template_job_id` is set, the code retrieves that job and uses its spec.
- Otherwise it uses the latest job returned by `/api/jobs/browse`.

#### `build_job_specification(template, size, hours, name=None, ssh_enabled=True, mounts=None, read_only_mounts=None) -> dict`

Clones a template spec and rewrites:

- product
- time allocation
- SSH enablement
- file/folder mounts
- optional job name

#### `submit_job_from_latest_template(...) -> JobLaunchResult`

Submits a CPU job based on the chosen template.

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

#### `run_remote_python_job(settings, spec, name=None) -> RemotePythonJobResult`

Generic workflow used for the real use case.

Behavior:

1. submits a fresh UCloud CPU job
2. waits for SSH availability
3. creates a unique remote directory under `settings.work_folder`
4. uploads the script and any additional files/directories
5. runs any setup commands, for example `pip install`
6. executes the Python script over SSH
7. downloads explicitly named output files
8. terminates the UCloud job in a `finally` block

#### `run_ssh_transfer_demo(settings, ...) -> SSHTransferDemoResult`

Proof-of-concept smoke test that remains available for validation.

It keeps the following files as its demo payload:

- `examples/worker.py`
- `examples/dummy_input.txt`

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
- `ucloud delivery package`
- `ucloud workflow scaffold-script`
- `ucloud workflow run`
- `ucloud workflow ssh-transfer`
- `ucloud workflow python-job`

### `ucloud workflow ssh-transfer`

Demo workflow kept as a smoke test.

Inputs from `.env`:

- `UCLOUD_TEMPLATE_JOB_ID`
- `UCLOUD_MOUNT_PATH`
- `UCLOUD_SSH_ALIAS`
- `UCLOUD_WORK_FOLDER`

Behavior:

- uploads `examples/worker.py` and `examples/dummy_input.txt`
- runs `worker.py` on the remote job
- downloads `dummy_output.txt` back to `examples/dummy_output.txt`
- terminates the job

### `ucloud workflow python-job`

Generic remote Python runner.

Required:

- `--script`

Optional:

- `--package` - local package directory to upload and install
- `--upload` - extra file or directory to upload, repeatable
- `--install-command` - extra remote setup command, repeatable
- `--arg` - script argument, repeatable
- `--output` - remote output path to download, repeatable
- `--editable-package` - install the package in editable mode
- `--local-output-root` - local directory for downloaded files

Typical use:

```bash
uv run ucloud workflow python-job --script path/to/main.py --package path/to/local-package --output output/result.json
```

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
