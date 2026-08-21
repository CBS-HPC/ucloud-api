# UCloud Workflow CLI

`ucloud` is a Python command-line tool for running template-based UCloud jobs, transferring files over SSH, analyzing job utilization, and creating local delivery archives.

It is not an AI agent, a web service, or an unattended scheduler. It runs only the commands an operator explicitly invokes.

## Quick start

```powershell
uv sync --group dev
uv run ucloud --help
```

Create a local `.env` file with:

```text
UCLOUD_TOKEN=<token secret>
UCLOUD_PROJECT=Moody's Datahub
UCLOUD_TEMPLATE_JOB_ID=<known-good UCloud template job>
```

The selected template job supplies mounted drives, application/container settings, SSH behavior, and baseline job configuration. Direct `--mount` flags are experimental and unverified.

After UCloud reports a job as running, the CLI first probes the SSH endpoint before creating its remote workspace. SSH and SCP use noninteractive, bounded commands; a pre-execution transport timeout terminates the submitted job.

## Common commands

```powershell
# Inspect available CLI job profiles and documented machine types.
uv run ucloud catalog profiles
uv run ucloud catalog machines

# Verify SSH file transfer with the static dummy input and worker files.
uv run ucloud workflow ssh-transfer --output artifacts/ssh-transfer/dummy_output.txt

# Upload a Python script and input file, run it, and download one declared output.
# Output paths are inside the Linux UCloud job, so use forward slashes.
uv run ucloud workflow python-job `
  --profile cpu-python-batch `
  --script .\workload\extract.py `
  --upload .\workload\input.csv `
  --output output/result.csv

# Analyze a downloaded UCloud job report.
uv run ucloud workflow analyze-utilization path\to\job-report.csv

# Create a local zip archive from a completed run's outputs.
uv run ucloud delivery package `
  --data-dir .\artifacts\python-job\RUN_ID `
  --docs-dir .\delivery-docs `
  --scripts-dir .\workload `
  --output .\deliveries\delivery-JOB_ID.zip

# Check token expiry before starting a longer job.
uv run ucloud tokens status --within-days 30
```

`ucloud delivery package` creates an archive locally; it does not send data to a user or external storage service.

## Documentation

- [Documentation index](docs/README.md)
- [Run a Python workload and create a delivery bundle](docs/guides/run-and-deliver.md)
- [Manage UCloud API tokens](docs/guides/token-management.md)
- [Run the SSH smoke test](docs/operations/ssh-smoke-test.md)
- [Maintain template jobs](docs/operations/template-job-catalog.md)
- [CLI and Python library reference](docs/reference/api.md)

## Release status

The project is an internal `0.1.x` release candidate. Before publishing a release, update the version and changelog, build fresh wheel/source artifacts, commit the changes, tag the release, and push it.
