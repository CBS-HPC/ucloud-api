# UCloud workflow toolkit

Python `uv` project for the workflow you described, with focus on:

- point 5: automated generation and submission of extraction jobs through the UCloud API
- point 6: automated packaging and delivery of the resulting data bundle

The old R script and notebook in this folder are kept as reference material. The Python package below is the new source of truth.

## What is included

- `ucloud` CLI for browsing wallets, submitting jobs, running Python jobs, waiting for SSH endpoints, and terminating jobs
- UCloud API client for the working endpoints you identified
- job-spec helpers for cloning and sanitizing the latest job template
- delivery packager that builds a standardized zip bundle with data, docs, scripts, and manifest
- script scaffold generator for AI-assisted extraction jobs
- code-level reference in [`API_REFERENCE.md`](API_REFERENCE.md)

## Setup

```bash
uv sync --group dev
```

Set at least:

- `UCLOUD_TOKEN`
- `UCLOUD_PROJECT`

Optional:

- `UCLOUD_TEMPLATE_JOB_ID` - use this existing UCloud job as the template instead of the latest one
- `UCLOUD_MOUNT_PATH` - when set, the job is submitted with that UCloud path mounted; when omitted, the job runs without any mount resources

The Python helpers load `.env` automatically if it exists in the project root, so edit that file directly.

## Usage

```bash
uv run ucloud wallets
uv run ucloud jobs submit --size 128-vcpu --hours 2
uv run ucloud jobs submit --mount /123/shared-input --read-only-mount /123/reference-data
uv run ucloud jobs wait JOB_ID
uv run ucloud workflow python-job --script path/to/main.py --package path/to/local-package --upload path/to/input.csv --install-command "python3 -m pip install --user pandas" --output output/result.csv
uv run ucloud workflow ssh-transfer
uv run ucloud delivery package --data-dir path/to/output --docs-dir path/to/docs --scripts-dir path/to/scripts --output dist/delivery.zip
uv run python examples/start_cpu_job.py
uv run python examples/ssh_transfer_job.py
```

Both example scripts terminate the UCloud job when they finish.

## Workflow focus

### Point 5

The project can:

- clone the latest UCloud job spec
- sanitize it for reuse
- replace the product/time allocation fields
- attach UCloud file or folder mounts through `resources`
- submit the job through `/api/jobs`
- poll `/api/jobs/retrieve` until the job is running
- extract the SSH command from job updates

Mounted paths are added as `AppParameterValue.File` resources, for example:

```json
{"path": "/123/shared-input", "readOnly": false, "type": "file"}
```

Use absolute UCloud paths, not local filesystem paths.

### Point 6

The delivery packager can:

- collect output files from a data directory
- include documentation and scripts
- store a machine-readable manifest
- produce a deterministic zip archive for handoff

### SSH transfer demo

`examples/ssh_transfer_job.py` shows the workflow you asked for:

- submit a CPU job with SSH enabled
- create a unique job directory inside `/work/moody_agent/`
- upload the static `examples/worker.py` and `examples/dummy_input.txt` files over SSH
- run the worker from that job directory so it creates `dummy_output.txt`
- download `dummy_output.txt` back to `examples/dummy_output.txt`
- terminate the UCloud job after the files have been transferred back

The same cleanup behavior is available from the CLI:

```bash
uv run ucloud workflow ssh-transfer
```

### Generic Python job runner

`ucloud workflow python-job` is the reusable workflow for your actual use case:

- upload one Python script to the job
- optionally upload a local package directory or extra input files
- run one or more install commands, for example `python3 -m pip install --user ./mypackage`
- execute the Python script inside the UCloud job
- download the output files you name explicitly
- terminate the UCloud job after the run completes

Example:

```bash
uv run ucloud workflow python-job ^
  --script path/to/main.py ^
  --package path/to/local-package ^
  --upload path/to/input.csv ^
  --install-command "python3 -m pip install --user numpy" ^
  --arg "--input" ^
  --arg "input.csv" ^
  --arg "--output" ^
  --arg "output/result.csv" ^
  --output output/result.csv
```

## Next step

If you want, I can extend this into a fuller orchestration layer that takes a plain-language request and turns it into:

1. a generated Python extraction script
2. a UCloud job submission
3. a packaged delivery archive

