# Manage UCloud API tokens

This guide covers token expiry checks, controlled creation, validation, and manual rotation with the `ucloud` CLI. It is intentionally conservative: the CLI can create a token, but it never writes a token to `.env` and never revokes a token automatically. An operator must explicitly run each command and handle the returned secret.

## Commands

```powershell
# List token expiry metadata without showing token secrets.
uv run ucloud tokens status --within-days 30

# Inspect available providers and permissions when the UCloud endpoint responds.
uv run ucloud tokens options

# Preview a six-month replacement token. This does not call UCloud.
uv run ucloud tokens create `
  --title "Moody's Datahub workflow replacement" `
  --valid-for 6

# Create the reviewed token. This is the only command that calls POST /api/tokens.
uv run ucloud tokens create `
  --title "Moody's Datahub workflow replacement" `
  --valid-for 6 `
  --yes
```

Add `--permission NAME:ACTION` repeatedly only when a UCloud provider requires explicit permissions. UCloud's frontend permits an empty permission list.

## Expiry choices

`ucloud tokens create` requires exactly one expiry option:

- `--valid-for MONTHS` calculates a calendar-month expiry. One month from 31 January is 28 February in a non-leap year.
- `--expires-at 2027-02-11T12:00:00Z` uses an explicit ISO 8601 UTC timestamp.

## Safe rotation procedure

1. Check the current token with `ucloud tokens status --within-days 30`.
2. Run `ucloud tokens create` without `--yes` and review the non-secret JSON request.
3. Run the same command with `--yes` once. Save the secret immediately; UCloud returns it only in this response.
4. Replace `UCLOUD_TOKEN` in the local `.env` through the approved credential process. Do not commit `.env`.
5. In a fresh terminal, run `ucloud tokens status`. Also run a harmless authenticated CLI command such as `ucloud wallets`.
6. Only after the replacement works, revoke the old token in the UCloud web UI. The CLI does not yet expose a revoke command.

## Failure handling

- Without `--yes`, the command only prints a request preview and creates nothing.
- The command does not retry a timeout or connection failure. A token may have been created while its one-time secret was lost; check the UCloud web UI before taking any further action.
- If UCloud does not return `status.token`, retain the old token and create a replacement only after confirming the outcome in the web UI.
- If `/api/tokens/retrieveOptions` returns an error, use the UCloud web UI for permission names; do not guess permission names.

## Secret-handling rules

- Never print, commit, or put `UCLOUD_TOKEN` in a delivery archive.
- Do not put token secrets in `metadata.json`, run notes, job scripts, or UCloud output files.
- Do not revoke the current token until the replacement has been validated from a fresh process.
