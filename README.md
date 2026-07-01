# UCloud workflow toolkit

Python `uv` project for the workflow you described, with focus on:

- point 5: automated generation and submission of extraction jobs through the UCloud API
- point 6: automated packaging and delivery of the resulting data bundle

The old R script and notebook in this folder are kept as reference material. The Python package below is the new source of truth.

## What is included

- `ucloud` CLI for browsing wallets, submitting jobs, running Python jobs, waiting for SSH endpoints, and terminating jobs
- `ucloud version` to confirm the installed release
- UCloud API client for the working endpoints you identified
- job-spec helpers for cloning and sanitizing the latest job template
- delivery packager that builds a standardized zip bundle with data, docs, scripts, and manifest
- script scaffold generator for AI-assisted extraction jobs
- utilization report analyzer for `job-report.csv` with CPU, memory, and GPU heuristics
- catalog commands for standard job profiles, template-job IDs, and documented machine types
- machine catalog includes the current CPU size ladder, the B200 GPU ladder (`1` through `8` GPUs), and the B200 MIG ladder (`1` through `4` MIG slices)
- code-level reference in [`API_REFERENCE.md`](API_REFERENCE.md)
- architecture audit in [`AUDIT_GENERIC_TOOL.md`](AUDIT_GENERIC_TOOL.md)
- standard job types in [`STANDARD_JOB_TYPES.md`](STANDARD_JOB_TYPES.md)
- template catalog in [`TEMPLATE_JOB_CATALOG.md`](TEMPLATE_JOB_CATALOG.md)

## Setup

```bash
uv sync --group dev
```

Set at least:

- `UCLOUD_TOKEN`
- `UCLOUD_PROJECT`

Optional:

- `UCLOUD_TEMPLATE_JOB_ID` - use this existing UCloud job as the template instead of the latest one; this is the preferred place to define mounted drives and application/job settings
- `UCLOUD_TEMPLATE_JOB_ID_<PROFILE>` - profile-specific template override, for example `UCLOUD_TEMPLATE_JOB_ID_CPU_PYTHON_BATCH`
- `UCLOUD_MOUNT_PATH` - legacy/advanced direct mount value; current workflow runners prefer template-job resources and do not inject this automatically

The Python helpers load `.env` automatically if it exists in the project root, so edit that file directly.

## Template jobs and drives

The normal workflow is based on reusable UCloud template jobs.

Create or choose a template job in UCloud with the required:

- mounted drives
- application/container
- SSH behavior
- baseline application parameters

Then point the toolkit at that job with `UCLOUD_TEMPLATE_JOB_ID` or a profile-specific variable such as `UCLOUD_TEMPLATE_JOB_ID_CPU_PYTHON_BATCH`.

Direct mount injection through `UCLOUD_MOUNT_PATH` is parked for now. The code still keeps the setting for low-level experiments, but the main workflow runners do not inject it automatically.

## Usage

```bash
uv run ucloud wallets
uv run ucloud catalog profiles
uv run ucloud catalog templates
uv run ucloud catalog machines
uv run ucloud jobs submit --size 128-vcpu --hours 2
uv run ucloud jobs submit --profile cpu-python-batch --size 128-vcpu --hours 2
uv run ucloud jobs submit --mount /123/shared-input --read-only-mount /123/reference-data
uv run ucloud jobs wait JOB_ID
uv run ucloud workflow python-job --profile cpu-python-batch --script path/to/main.py --package path/to/local-package --upload path/to/input.csv --install-command "python3 -m pip install --user pandas" --output output/result.csv
uv run ucloud workflow ssh-transfer
uv run ucloud workflow analyze-utilization path/to/job-report.csv
uv run ucloud workflow analyze-utilization path/to/job-report.csv --current-machine cpu-amd-zen5-128-vcpu
uv run ucloud delivery package --data-dir path/to/output --docs-dir path/to/docs --scripts-dir path/to/scripts --output dist/delivery.zip
uv run python examples/start_cpu_job.py
uv run python examples/ssh_transfer_job.py
uv run python examples/analyze_job_report.py path/to/job-report.csv
uv run python examples/analyze_job_report.py path/to/job-report.csv --current-machine cpu-amd-zen5-128-vcpu
```

Both example scripts terminate the UCloud job when they finish.

## Workflow focus

### Point 5

The project can:

- clone the latest UCloud job spec
- clone a specific `UCLOUD_TEMPLATE_JOB_ID` when provided
- sanitize it for reuse
- replace the product/time allocation fields
- preserve drives and application settings already defined in the template job
- attach extra UCloud file or folder mounts only when explicit CLI `--mount` / `--read-only-mount` flags are used
- submit the job through `/api/jobs`
- poll `/api/jobs/retrieve` until the job is running
- extract the SSH command from job updates

Explicitly supplied mounted paths are added as `AppParameterValue.File` resources, for example:

```json
{"path": "/123/shared-input", "readOnly": false, "type": "file"}
```

Use absolute UCloud paths, not local filesystem paths.
For the normal workflow, create or choose a UCloud template job that already has the required drives attached.

### Point 6

The delivery packager can:

- collect output files from a data directory
- include documentation and scripts
- store a machine-readable manifest
- produce a deterministic zip archive for handoff

### SSH transfer demo

`examples/ssh_transfer_job.py` shows the workflow you asked for:

- submit a CPU job with SSH enabled
- inherit drives and job settings from the selected template job
- create a unique job directory inside `/work/moody_agent/`
- upload the static `examples/worker.py` and `examples/dummy_input.txt` files over SSH
- run the worker from that job directory so it creates `dummy_output.txt`
- download `dummy_output.txt` back to `examples/dummy_output.txt`
- if `job-report.csv` exists at `/work/job-report.csv`, download it to `examples/job-report.csv` and print a utilization recommendation
- terminate the UCloud job after the files have been transferred back

The same cleanup behavior is available from the CLI:

```bash
uv run ucloud workflow ssh-transfer
```

### Generic Python job runner

`ucloud workflow python-job` is the reusable workflow for your actual use case:

- upload one Python script to the job
- optionally upload a local package directory or extra input files
- inherit drives and job settings from the selected template job
- run one or more install commands, for example `python3 -m pip install --user ./mypackage`
- execute the Python script inside the UCloud job
- download the output files you name explicitly
- if `/work/job-report.csv` exists, download it alongside the outputs and print a utilization recommendation
- when the launched job exposes a known machine product id, also print a next-machine suggestion
- terminate the UCloud job after the run completes
- select a standard template with `--profile` when you want a named job family instead of the global fallback template

### Utilization analysis

`ucloud workflow analyze-utilization` evaluates a downloaded `job-report.csv` and recommends whether to:

- decrease the machine size
- keep the machine size
- increase the machine size

Optional `--current-machine` adds a concrete next-machine suggestion from the documented machine ladder.

It flags both very low utilization and saturation, with special attention to memory pressure that can cause crashes.
It also accepts GPU-style reports when they expose the same `*_limit_*` / value-column pattern.

Example:

```bash
uv run ucloud workflow analyze-utilization artifacts/python-job/20260611-080000/job-report.csv
```

The same analysis is also available as a standalone script:

```bash
uv run python examples/analyze_job_report.py path/to/job-report.csv
```

Add `--current-machine cpu-amd-zen5-128-vcpu` to print the next machine candidate for the current run size.

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

## Release status

This repository is ready for an internal `0.1.x` release candidate.

Release-ready scope:

- package builds as a wheel and source distribution
- unit test suite passes
- `examples/ssh_transfer_job.py` has been live-tested against UCloud
- template-job based drive/settings inheritance is the documented workflow
- utilization reports are downloaded and analyzed when `/work/job-report.csv` exists

Not yet `1.0.0` scope:

- verified template IDs still need to be filled into `TEMPLATE_JOB_CATALOG.md`
- direct mount injection is deliberately not the main workflow path
- artifact manifests and provenance tracking are still TODO
- the dummy SSH transfer demo still needs to be replaced by a real extraction workflow

The next platform step is to turn the current primitives into a fuller orchestration layer that takes a plain-language request and produces:

1. a generated Python extraction script
2. a UCloud job submission
3. a packaged delivery archive

