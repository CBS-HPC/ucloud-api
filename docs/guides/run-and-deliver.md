# Run a Python workload and create a delivery bundle

This guide shows how to use the `ucloud` CLI to run a local Python workload on UCloud and package the resulting files as a local zip archive. The operator supplies and reviews every input and command. The CLI does not generate a workload, choose data for you, or send the archive to a user.

## Before you start

1. Configure `UCLOUD_TOKEN`, `UCLOUD_PROJECT`, and `UCLOUD_TEMPLATE_JOB_ID` in `.env`.
2. Create a UCloud template job with the required mounted drives, application/container, and SSH settings.
3. Prepare one Python entry point, any local package or input files it needs, and the relative paths of the output files it will create.
4. Check token expiry before a long job. See [Manage UCloud API tokens](token-management.md).

## 1. Run the Python workload

`ucloud workflow python-job` submits a new job from the template, waits for UCloud to publish SSH, probes that endpoint before remote setup, uploads the requested local files, runs setup commands and the Python script, downloads the declared output files, and then terminates the job.

```powershell
uv run ucloud workflow python-job `
  --profile cpu-python-batch `
  --script .\workload\extract.py `
  --package .\workload\my_package `
  --upload .\workload\input.csv `
  --arg --input `
  --arg input.csv `
  --arg --output `
  --arg output/result.csv `
  --output output/result.csv
```

The downloaded files are stored in a unique local run folder under `artifacts/python-job/`. When available, `/work/job-report.csv` is downloaded too and the CLI prints a machine-size recommendation. SSH/SCP calls are noninteractive and time-bounded. The CLI logs the start, completion, or failure of each setup stage; a failed readiness or workspace-preparation stage terminates the job before the workload runs.

## 2. Prepare delivery documentation

Prepare human-readable documentation alongside the extracted data:

- a short `README.md` describing the extraction and delivery contents;
- a variable/data dictionary, for example `variables.json` or `variables.csv`;
- any caveats, source dates, and data-quality notes.

## 3. Create a local delivery archive

Run this command after reviewing the output directory and preparing its documentation:

```powershell
uv run ucloud delivery package `
  --data-dir .\artifacts\python-job\RUN_ID `
  --docs-dir .\delivery-docs `
  --scripts-dir .\workload `
  --job-id JOB_ID `
  --run-id RUN_ID `
  --template-job-id TEMPLATE_JOB_ID `
  --machine-product cpu-amd-zen5-16-vcpu `
  --variables-json .\delivery-docs\variables.json `
  --workflow-note "Output downloaded after successful job completion" `
  --output .\deliveries\delivery-JOB_ID.zip
```

The resulting zip contains `data/`, `docs/`, `scripts/`, and `manifest.json`. The manifest follows `ucloud.artifact-manifest.v1` and records each delivered file's relative path, role, size, SHA-256 checksum, and detected content type. Its provenance section records UCloud job details and optional CLI metadata. The CLI creates this archive locally; distribute it through your approved storage or sharing channel.

## 4. Verify before sharing

1. Open the zip and check that the expected data and documentation are present.
2. Confirm that every declared output has a matching record in `manifest.json`.
3. Retain `job-report.csv` and the rendered utilization analysis when resource sizing matters for a repeat run.
4. Share the archive through the approved storage or sharing channel; do not put API tokens or private credentials in the archive.
