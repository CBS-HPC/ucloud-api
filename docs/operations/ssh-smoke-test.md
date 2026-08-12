# Run the UCloud SSH smoke test

Use this manual procedure to verify that the `ucloud` CLI can start a UCloud job, connect over SSH, create `dummy.txt` in the configured remote work folder, verify the file, and stop the job.

## Goal

Create this file inside the running UCloud job:

```text
$UCLOUD_WORK_FOLDER/dummy.txt
```

If `UCLOUD_WORK_FOLDER` is not set in `kristoffer_test.env`, the project default is:

```text
/work/moody_agent
```

## Preconditions

- Run commands from the repository root.
- `uv` is installed.
- A local test environment file exists in the repository root. The example below uses `kristoffer_test.env`.
- That test environment file contains at least:
  - `UCLOUD_TOKEN`
  - `UCLOUD_PROJECT`
  - a usable `UCLOUD_TEMPLATE_JOB_ID` or profile-specific template job id
- The selected template job must be SSH-capable.
- Do not print or commit `UCLOUD_TOKEN`.
- This smoke test must not run `ucloud tokens create`; it only needs an already-configured token.

For token expiry checks, controlled creation, and rotation, follow [Manage UCloud API tokens](../guides/token-management.md) instead of this job smoke-test procedure.

The CLI automatically loads `.env`, not `kristoffer_test.env`. For this test, load the selected test environment file into the current PowerShell process before running the CLI.

## PowerShell test procedure

```powershell
$ErrorActionPreference = "Stop"

# Load the selected test environment file into the current PowerShell process.
foreach ($rawLine in Get-Content .\kristoffer_test.env) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
        continue
    }

    $name, $value = $line.Split("=", 2)
    $cleanValue = $value.Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($name.Trim(), $cleanValue, "Process")
}

$sshAlias = if ($env:UCLOUD_SSH_ALIAS) { $env:UCLOUD_SSH_ALIAS } else { "ucloud" }
$workFolder = if ($env:UCLOUD_WORK_FOLDER) { $env:UCLOUD_WORK_FOLDER.TrimEnd("/") } else { "/work/moody_agent" }
$jobId = $null

try {
    # Start a small SSH-enabled job from the configured template.
    $jobOutput = & uv run --no-sync --project . ucloud workflow run --name dummy-file-api-test --hours 1
    $jobOutput | ForEach-Object { Write-Host $_ }

    $jobIdMatch = $jobOutput | Select-String -Pattern "Job submitted:\s*(\S+)"
    if (-not $jobIdMatch) {
        throw "Could not find job id in CLI output."
    }
    $jobId = $jobIdMatch.Matches[0].Groups[1].Value

    # Create and verify dummy.txt inside the UCloud work folder.
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $remoteCommand = "mkdir -p '$workFolder' && printf '%s\n' 'dummy api test job=$jobId utc=$timestamp' > '$workFolder/dummy.txt' && test -s '$workFolder/dummy.txt' && ls -l '$workFolder/dummy.txt' && cat '$workFolder/dummy.txt'"
    & ssh $sshAlias $remoteCommand

    if ($LASTEXITCODE -ne 0) {
        throw "Remote dummy.txt verification failed."
    }

    Write-Host "OK: created and verified $workFolder/dummy.txt on UCloud job $jobId"
}
finally {
    if ($jobId) {
        & uv run --no-sync --project . ucloud jobs stop $jobId
    }
}
```

## Expected success output

The successful run should show:

- a UCloud job id after `Job submitted:`
- an SSH command printed by `ucloud workflow run`
- `ls -l` output for `dummy.txt`
- the content line starting with `dummy api test`
- `Stopped job <job_id>` from the cleanup step

## Failure interpretation

- `Missing required environment variables`: `kristoffer_test.env` was not loaded correctly or is missing required values.
- `Timed out ... waiting for UCloud to expose an SSH command`: the template job is probably not SSH-capable.
- `ssh: Could not resolve hostname ucloud`: SSH config was not written; rerun `ucloud workflow run` and check its output.
- `Permission denied` or write failure under `$UCLOUD_WORK_FOLDER`: the template job does not expose a writable work folder at that path.

## Cleanup check

After the test, confirm the job is not still running:

```powershell
uv run --no-sync --project . ucloud jobs stop <job_id>
```

If the job was already stopped, UCloud may return an error. That is acceptable after the `finally` cleanup has already run.
