# UCloud Workflow CLI

`ucloud` is a Python command-line tool for running template-based UCloud jobs, transferring files over SSH, analyzing job utilization, and creating local delivery archives.

It is not an AI agent, a web service, or an unattended scheduler. It runs only the commands an operator explicitly invokes.

## Quick start

```powershell
uv sync --group dev
uv run ucloud --help
```

To configure from just a valid API token, run:

```powershell
uv run ucloud setup
```

Enter the token at the hidden prompt, select the project, writable drive, and reusable template job, then confirm. Setup creates or reuses `/<drive-id>/ucloud-workflow` and saves a local `.env`, preserving unrelated settings. It does not submit jobs, register SSH keys, or change mounts. The token is stored in plaintext locally; never commit it. See [token-based setup](docs/reference/api.md#token-based-setup) for explicit options and limitations.

Alternatively, create a local `.env` file manually:

```text
UCLOUD_TOKEN=<token secret>
UCLOUD_PROJECT=Moody's Datahub
UCLOUD_TEMPLATE_JOB_ID=<known-good UCloud template job>
```

The selected template job supplies mounted drives, application/container settings, SSH behavior, and baseline job configuration. Direct `--mount` flags are experimental and unverified.

`UCLOUD_STORAGE_PATH` identifies persistent UCloud storage; it is not an in-job `/work/...` path and does not automatically mount anything. Fresh setup uses `/work` as its working root unless you supply `--work-folder`; existing working-root settings are preserved.

After UCloud reports a job as running, the CLI first probes the SSH endpoint before creating its remote workspace. SSH and SCP use noninteractive, bounded commands and explicitly use `UCLOUD_SSH_CONFIG_PATH` (default: `~/.ssh/config`); a pre-execution transport timeout terminates the submitted job. Set `UCLOUD_SSH_IDENTITY_FILE` only when the private key is not beside that config file.

## Common commands

```powershell
# Inspect available CLI job profiles and documented machine types.
uv run ucloud catalog profiles
uv run ucloud catalog machines

# Check live capacity and SSH public-key registration without starting a job.
uv run ucloud catalog machines --live --provider ucloud --json
uv run ucloud ssh-keys check

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

`ucloud links`, `ucloud ips`, `ucloud licenses`, and `ucloud ssh-keys` provide explicit resource-management commands. Writes preview unless `--yes` is supplied; they can allocate persistent resources or expose applications publicly. See [resource and SSH-key management](docs/reference/api.md#resource-and-ssh-key-management) before using them. Standalone allocations persist; optional Python per-run provisioning only cleans up resources that it created.

`ucloud jobs submit --resources resources.json` selects existing links, IPs, and named application licenses while preserving the template. `ucloud jobs submit-immediate --candidates candidates.json` previews caller-approved machines; add `--yes` to submit one and terminate it if startup misses the deadline. Both commands accept `--no-ssh` for applications without SSH support. See [job resources](docs/reference/api.md#job-resource-selection-and-owned-cleanup) and [immediate startup](docs/reference/api.md#opt-in-immediate-startup).

Live tests cover setup-folder creation/reuse and configuration saving, links, CBS Stata-license activations, SSH-key registration/deletion, resource-aware CPU jobs, owned cleanup, and startup cancellation. Public-IP creation was rejected by the project's zero quota; IP/firewall success and public-URL serving remain unverified. See [verification status](docs/reference/api.md#verification-status-and-remaining-integration).

Job-launching commands keep the existing CPU default unless you choose an explicit product with `--product-id`, `--product-category`, and `--product-provider`, or use `--use-template-product` to retain the template's machine. CPU, full GPU, and MIG products use the same workflow; the operator or calling integration chooses the machine. See [machine selection](docs/reference/api.md#machine-selection).

## Documentation

- [Documentation index](docs/README.md)
- [Run a Python workload and create a delivery bundle](docs/guides/run-and-deliver.md)
- [Manage UCloud API tokens](docs/guides/token-management.md)
- [Run the SSH smoke test](docs/operations/ssh-smoke-test.md)
- [Maintain template jobs](docs/operations/template-job-catalog.md)
- [CLI and Python library reference](docs/reference/api.md)

## Release status

The project is an internal `0.1.x` CLI tool. Tagged [GitHub releases](https://github.com/CBS-HPC/ucloud-api/releases) include a wheel and source archive. Before publishing a release, update the version and changelog, validate fresh build artifacts, commit the changes, tag the release, and push it.

## License

- Code, including source, tests, example scripts, and code snippets in the documentation: [MIT](LICENSE).
- Original documentation, including root Markdown files and prose under `docs/`: [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-DOCS).

For documentation attribution, credit **ucloud-api contributors**, link to [UCloud Workflow CLI](https://github.com/CBS-HPC/ucloud-api) and [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), and indicate changes when sharing modified documentation. Package metadata uses `MIT AND CC-BY-4.0` because these licenses cover different parts of the distribution, not a choice of license for the same material.

Third-party material retains its own license. These licenses do not grant rights to user-supplied data or generated datasets.
