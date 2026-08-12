from __future__ import annotations

from pathlib import Path
import json

import httpx
import rich.console
import rich.table
import typer

from .catalog import (
    MACHINE_CATALOG,
    STANDARD_JOB_PROFILES,
    TEMPLATE_JOB_CATALOG,
    machine_products_for_profile,
    profile_by_name,
)
from . import __version__
from .client import UCloudClient
from .delivery import DeliveryBundleSpec, create_delivery_bundle
from .jobs import (
    open_in_vscode,
    submit_job_from_latest_template,
    update_ssh_config,
    wait_for_running_job,
)
from .scripts import ExtractionScriptSpec, write_extraction_script
from .settings import Settings, SettingsError
from .tokens import build_api_token_specification, summarize_api_tokens
from .transfer import (
    RemotePythonJobSpec,
    build_pip_install_command,
    run_remote_python_job,
    run_ssh_transfer_demo,
)
from .utilization import analyze_job_report, render_utilization_analysis

app = typer.Typer(add_completion=False, help="UCloud job workflow command-line tool")
jobs_app = typer.Typer(help="Job lifecycle commands")
delivery_app = typer.Typer(help="Data delivery packaging")
workflow_app = typer.Typer(help="Run UCloud Python jobs and collect outputs")
catalog_app = typer.Typer(help="Catalog of standard job types and machine types")
tokens_app = typer.Typer(help="Inspect UCloud API-token metadata without exposing token secrets")

app.add_typer(jobs_app, name="jobs")
app.add_typer(delivery_app, name="delivery")
app.add_typer(workflow_app, name="workflow")
app.add_typer(catalog_app, name="catalog")
app.add_typer(tokens_app, name="tokens")

console = rich.console.Console()


def _load_settings(
    server: str | None = None,
    token: str | None = None,
    project: str | None = None,
    ssh_alias: str | None = None,
    work_folder: str | None = None,
    default_size: str | None = None,
    default_hours: int | None = None,
) -> Settings:
    return Settings.from_env(
        server=server,
        token=token,
        project=project,
        ssh_alias=ssh_alias,
        work_folder=work_folder,
        default_size=default_size,
        default_hours=default_hours,
    )


def _resolve_template_job_id(settings: Settings, profile: str | None) -> str | None:
    try:
        return settings.template_job_id_for(profile)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _join_notes(notes: tuple[str, ...]) -> str:
    return "; ".join(notes) if notes else "-"


def _load_json_file(path: Path, *, expected_type: type, description: str):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{description} must contain valid JSON: {exc}") from exc
    if not isinstance(value, expected_type):
        raise typer.BadParameter(f"{description} must contain a JSON {expected_type.__name__}")
    return value


@app.command("version")
def version() -> None:
    """Print the installed package version."""
    console.print(f"ucloud-workflow {__version__}")


@app.command()
def wallets(
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Show the wallet hierarchy returned by browseWallets."""
    settings = _load_settings(server=server, token=token, project=project)
    with UCloudClient(settings) as client:
        data = client.browse_wallets(include_children=True)

    table = rich.table.Table(title="UCloud wallets")
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("items", str(len(data.get("items", [])) if isinstance(data, dict) else 0))
    console.print(table)
    console.print_json(json.dumps(data, indent=2))


@jobs_app.command("submit")
def submit_job(
    size: str = typer.Option(None, help="UCloud CPU size, for example 128-vcpu"),
    hours: int | None = typer.Option(None, help="Time allocation in hours"),
    name: str | None = typer.Option(None, help="Optional job name"),
    profile: str | None = typer.Option(None, help="Standard job profile name, for example vscode-remote-session"),
    mount: list[str] = typer.Option([], "--mount", help="UCloud file or folder path to mount (repeatable)"),
    read_only_mount: list[str] = typer.Option(
        [],
        "--read-only-mount",
        "--ro-mount",
        help="UCloud file or folder path to mount read-only (repeatable)",
    ),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Submit a job using the configured template."""
    settings = _load_settings(server=server, token=token, project=project)
    template_job_id = _resolve_template_job_id(settings, profile)
    with UCloudClient(settings) as client:
        result = submit_job_from_latest_template(
            client,
            size=size or settings.default_size,
            hours=hours if hours is not None else settings.default_hours,
            name=name,
            mounts=mount,
            read_only_mounts=read_only_mount,
            template_job_id=template_job_id,
        )
    console.print(f"Job submitted: {result.job_id}")
    console.print(f"Job URL: {result.job_url}")


@jobs_app.command("wait")
def wait_job(
    job_id: str = typer.Argument(..., help="UCloud job id"),
    timeout_seconds: int = typer.Option(600, help="Timeout in seconds"),
    poll_interval_seconds: int = typer.Option(5, help="Polling interval in seconds"),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
    ssh_alias: str | None = typer.Option(None, help="SSH alias to write to config"),
    work_folder: str | None = typer.Option(None, help="Remote folder to open"),
) -> None:
    """Wait until the job is running and print the SSH command."""
    settings = _load_settings(server=server, token=token, project=project, ssh_alias=ssh_alias, work_folder=work_folder)
    with UCloudClient(settings) as client:
        job, ssh_command = wait_for_running_job(
            client,
            job_id,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        config_info = update_ssh_config(ssh_command, alias=settings.ssh_alias, config_path=settings.ssh_config_path)

    console.print(f"SSH command: {ssh_command}")
    console.print(f"SSH config updated for {config_info['alias']}")
    console.print(f"Job state: {job.get('updates', [])[-1].get('state', 'unknown') if job.get('updates') else 'unknown'}")


@jobs_app.command("stop")
def stop_job(
    job_id: str = typer.Argument(..., help="UCloud job id"),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Terminate a job."""
    settings = _load_settings(server=server, token=token, project=project)
    with UCloudClient(settings) as client:
        client.terminate_job(job_id)
    console.print(f"Stopped job {job_id}")


@delivery_app.command("package")
def package_delivery(
    data_dir: Path = typer.Option(..., exists=True, file_okay=False, dir_okay=True, help="Directory with data files"),
    output: Path = typer.Option(Path("dist/delivery.zip"), help="Output zip file"),
    docs_dir: Path | None = typer.Option(None, file_okay=False, dir_okay=True, help="Optional documentation directory"),
    scripts_dir: Path | None = typer.Option(None, file_okay=False, dir_okay=True, help="Optional scripts directory"),
    job_id: str | None = typer.Option(None, help="Optional UCloud job id"),
    run_id: str | None = typer.Option(None, help="Optional local workflow run id"),
    template_job_id: str | None = typer.Option(None, help="Optional UCloud template job id"),
    machine_product: str | None = typer.Option(None, help="Optional UCloud machine product id"),
    variables_json: Path | None = typer.Option(
        None,
        exists=True,
        dir_okay=False,
        help="Optional JSON array describing delivered variables",
    ),
    metadata_json: Path | None = typer.Option(
        None,
        exists=True,
        dir_okay=False,
        help="Optional JSON object with workflow metadata",
    ),
    workflow_note: list[str] = typer.Option([], "--workflow-note", help="Workflow provenance note (repeatable)"),
) -> None:
    """Create a standardized delivery zip."""
    variables = () if variables_json is None else _load_json_file(
        variables_json,
        expected_type=list,
        description="--variables-json",
    )
    metadata = {} if metadata_json is None else _load_json_file(
        metadata_json,
        expected_type=dict,
        description="--metadata-json",
    )
    bundle = DeliveryBundleSpec(
        data_dir=data_dir,
        docs_dir=docs_dir,
        scripts_dir=scripts_dir,
        output_path=output,
        job_id=job_id,
        run_id=run_id,
        template_job_id=template_job_id,
        machine_product=machine_product,
        variables=variables,
        workflow_notes=tuple(workflow_note),
        metadata=metadata,
    )
    result = create_delivery_bundle(bundle)
    console.print(f"Created delivery bundle: {result}")


@workflow_app.command("scaffold-script")
def scaffold_script(
    output: Path = typer.Option(..., help="Path to write the generated script"),
    title: str = typer.Option(..., help="Script title"),
    objective: str = typer.Option(..., help="Script objective"),
) -> None:
    """Generate a starter Python extraction script."""
    spec = ExtractionScriptSpec(title=title, objective=objective)
    result = write_extraction_script(output, spec)
    console.print(f"Generated extraction script: {result}")


@workflow_app.command("run")
def run_workflow(
    size: str = typer.Option(None, help="UCloud CPU size"),
    hours: int | None = typer.Option(None, help="Time allocation in hours"),
    name: str | None = typer.Option(None, help="Optional job name"),
    profile: str | None = typer.Option(None, help="Standard job profile name, for example cpu-python-batch"),
    mount: list[str] = typer.Option([], "--mount", help="UCloud file or folder path to mount (repeatable)"),
    read_only_mount: list[str] = typer.Option(
        [],
        "--read-only-mount",
        "--ro-mount",
        help="UCloud file or folder path to mount read-only (repeatable)",
    ),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
    ssh_alias: str | None = typer.Option(None, help="SSH alias to write to config"),
    work_folder: str | None = typer.Option(None, help="Remote folder to open"),
    open_vscode: bool = typer.Option(False, help="Try to open VS Code after config is written"),
) -> None:
    """Submit a configured template job and prepare SSH access."""
    settings = _load_settings(
        server=server,
        token=token,
        project=project,
        ssh_alias=ssh_alias,
        work_folder=work_folder,
        default_size=size,
        default_hours=hours,
    )
    template_job_id = _resolve_template_job_id(settings, profile)
    with UCloudClient(settings) as client:
        launched = submit_job_from_latest_template(
            client,
            size=size or settings.default_size,
            hours=hours if hours is not None else settings.default_hours,
            name=name,
            mounts=mount,
            read_only_mounts=read_only_mount,
            template_job_id=template_job_id,
        )
        job, ssh_command = wait_for_running_job(client, launched.job_id)
        update_ssh_config(ssh_command, alias=settings.ssh_alias, config_path=settings.ssh_config_path)

    console.print(f"Job submitted: {launched.job_id}")
    console.print(f"SSH command: {ssh_command}")
    if open_vscode and open_in_vscode(settings.ssh_alias, settings.work_folder):
        console.print("VS Code launch requested")


@workflow_app.command("ssh-transfer")
def ssh_transfer(
    delay_seconds: float = typer.Option(3.0, "--delay", help="Delay before the dummy output is written"),
    poll_seconds: int = typer.Option(2, "--poll", help="Polling interval in seconds"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Local destination for dummy_output.txt (defaults to examples/dummy_output.txt)",
    ),
    profile: str | None = typer.Option(None, help="Standard job profile name for the transfer demo"),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Run the SSH transfer demo and terminate the job after the dummy output is downloaded."""
    settings = _load_settings(server=server, token=token, project=project)
    template_job_id = _resolve_template_job_id(settings, profile)
    result = run_ssh_transfer_demo(
        settings,
        delay_seconds=delay_seconds,
        poll_seconds=poll_seconds,
        local_output_path=output,
        template_job_id=template_job_id,
    )
    console.print(f"Job submitted: {result.job_id}")
    console.print(f"Local output file: {result.local_output_path}")
    console.print(f"Remote job directory: {result.remote_dir}")


@tokens_app.command("status")
def token_status(
    expiring_within_days: int = typer.Option(
        30,
        "--within-days",
        min=0,
        help="Flag active tokens that expire within this many days",
    ),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Show token expiry metadata; the token secret is never printed or stored."""
    settings = _load_settings(server=server, token=token, project=project)
    with UCloudClient(settings) as client:
        response = client.browse_api_tokens()
    summaries = summarize_api_tokens(
        response,
        expiring_within_days=expiring_within_days,
    )

    table = rich.table.Table(title="UCloud API token expiry")
    table.add_column("Title", style="cyan")
    table.add_column("Token ID", style="white")
    table.add_column("Expires (UTC)", style="white")
    table.add_column("Days left", style="yellow")
    table.add_column("State", style="magenta")
    table.add_column("Permissions", style="white")
    for item in summaries:
        expires_at = "-" if item.expires_at is None else item.expires_at.isoformat()
        days_left = "-" if item.days_remaining is None else f"{item.days_remaining:.1f}"
        table.add_row(
            item.title,
            item.token_id,
            expires_at,
            days_left,
            item.expiry_state,
            ", ".join(item.permissions) or "-",
        )
    console.print(table)


@tokens_app.command("options")
def token_options(
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Show the available providers and permissions for API-token creation."""
    settings = _load_settings(server=server, token=token, project=project)
    with UCloudClient(settings) as client:
        response = client.retrieve_api_token_options()
    console.print_json(json.dumps(response, indent=2))


@tokens_app.command("create")
def token_create(
    title: str = typer.Option(..., help="Human-readable token title"),
    expires_at: str | None = typer.Option(
        None,
        "--expires-at",
        help="ISO 8601 expiry with timezone, for example 2026-09-11T22:00:00Z",
    ),
    valid_for: int | None = typer.Option(
        None,
        "--valid-for",
        min=1,
        help="Number of calendar months the token is valid for",
    ),
    permission: list[str] = typer.Option(
        [],
        "--permission",
        help="Optional requested permission as NAME:ACTION; repeat for each permission",
    ),
    description: str = typer.Option("Created by ucloud-workflow", help="Token description"),
    provider: str | None = typer.Option(None, help="Optional UCloud token provider"),
    yes: bool = typer.Option(False, "--yes", help="Actually create the token after previewing the request"),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
) -> None:
    """Preview or explicitly create an API token; the secret is shown only once."""
    try:
        specification = build_api_token_specification(
            title=title,
            description=description,
            expires_at=expires_at,
            valid_for_months=valid_for,
            permissions=permission,
            provider=provider,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    console.print("Token creation request:")
    console.print_json(json.dumps(specification, indent=2))
    if not yes:
        console.print("Preview only. Review the request, then rerun with --yes to create the token.")
        return

    settings = _load_settings(server=server, token=token, project=project)
    try:
        with UCloudClient(settings) as client:
            response = client.create_api_token(specification)
    except httpx.RequestError as exc:
        console.print(f"UCloud did not confirm token creation: {exc.__class__.__name__}.")
        console.print("Do not retry automatically. Check UCloud's API-token page for a newly created token first.")
        console.print("If UCloud created it but the response was lost, its one-time secret cannot be recovered.")
        raise typer.Exit(code=1) from exc

    status = response.get("status") if isinstance(response, dict) else None
    secret = status.get("token") if isinstance(status, dict) else None
    if not isinstance(secret, str) or not secret:
        console.print("The token was created, but UCloud did not return its one-time secret.")
        console.print("Do not revoke the current token until the replacement credential has been recovered or recreated.")
        raise typer.Exit(code=1)

    token_id = response.get("id") if isinstance(response, dict) and isinstance(response.get("id"), str) else "unknown"
    console.print(f"Created API token: {token_id}")
    console.print("Save this token now. It is not written to .env and cannot be retrieved again:")
    console.print(secret, markup=False, highlight=False)
    console.print("Validate the replacement token before revoking the current token.")


@workflow_app.command("python-job")
def python_job(
    script: Path = typer.Option(..., exists=True, dir_okay=False, help="Python script to upload and run"),
    package: Path | None = typer.Option(
        None,
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Local package directory to upload and install with pip",
    ),
    upload: list[Path] = typer.Option(
        [],
        "--upload",
        exists=True,
        file_okay=True,
        dir_okay=True,
        help="Additional file or directory to upload (repeatable)",
    ),
    install_command: list[str] = typer.Option(
        [],
        "--install-command",
        help="Extra shell command to run before the script (repeatable)",
    ),
    arg: list[str] = typer.Option([], "--arg", help="Argument passed to the Python script (repeatable)"),
    output: list[str] = typer.Option(
        [],
        "--output",
        help="Relative remote output file to download after the run (repeatable)",
    ),
    editable_package: bool = typer.Option(False, "--editable-package", help="Install the package in editable mode"),
    local_output_root: Path = typer.Option(
        Path("artifacts/python-job"),
        help="Local directory for downloaded files",
    ),
    size: str = typer.Option(None, help="UCloud CPU size"),
    hours: int | None = typer.Option(None, help="Time allocation in hours"),
    name: str | None = typer.Option(None, help="Optional job name"),
    profile: str | None = typer.Option(None, help="Standard job profile name for the batch runner"),
    server: str | None = typer.Option(None, help="UCloud server URL"),
    token: str | None = typer.Option(None, help="Bearer token"),
    project: str | None = typer.Option(None, help="Project header"),
    ssh_alias: str | None = typer.Option(None, help="SSH alias to write to config"),
    work_folder: str | None = typer.Option(None, help="Remote folder to open"),
) -> None:
    """Upload a Python script, install a local package, run it, and download outputs."""
    settings = _load_settings(
        server=server,
        token=token,
        project=project,
        ssh_alias=ssh_alias,
        work_folder=work_folder,
        default_size=size,
        default_hours=hours,
    )
    template_job_id = _resolve_template_job_id(settings, profile)

    upload_paths = list(upload)
    setup_commands = list(install_command)
    if package is not None:
        upload_paths.append(package)
        setup_commands.insert(0, build_pip_install_command(package.name, editable=editable_package))

    spec = RemotePythonJobSpec(
        script_path=script,
        upload_paths=tuple(upload_paths),
        setup_commands=tuple(setup_commands),
        script_args=tuple(arg),
        output_paths=tuple(output),
        local_output_root=local_output_root,
    )
    result = run_remote_python_job(settings, spec, name=name, template_job_id=template_job_id)

    console.print(f"Job submitted: {result.job_id}")
    console.print(f"Local output directory: {result.local_output_dir}")
    console.print(f"Downloaded files: {len(result.downloaded_paths)}")
    if result.job_report_path is not None:
        console.print(f"Job report: {result.job_report_path}")
    console.print(f"Remote job directory: {result.remote_dir}")


@workflow_app.command("analyze-utilization")
def analyze_utilization(
    report: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to a job-report.csv file"),
    current_machine: str | None = typer.Option(
        None,
        "--current-machine",
        help="Optional current UCloud product id for a next-machine suggestion",
    ),
    output: Path | None = typer.Option(None, help="Optional markdown file to write the analysis to"),
) -> None:
    """Analyze a utilization report and recommend a machine-size direction."""
    analysis = analyze_job_report(report, current_machine_product=current_machine)
    rendered = render_utilization_analysis(analysis)
    console.print(rendered)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        console.print(f"Wrote analysis to {output}")


@catalog_app.command("profiles")
def list_profiles() -> None:
    """List the standard job profiles."""
    table = rich.table.Table(title="Standard UCloud job profiles")
    table.add_column("Profile key", style="cyan")
    table.add_column("Display name", style="white")
    table.add_column("Category", style="magenta")
    table.add_column("Template env var", style="green")
    table.add_column("Machine families", style="white")
    table.add_column("SSH", style="yellow")
    table.add_column("Utilization", style="yellow")
    table.add_column("Notes", style="white")
    for profile in STANDARD_JOB_PROFILES:
        table.add_row(
            profile.name,
            profile.display_name,
            profile.category,
            profile.template_env_var,
            ", ".join(profile.preferred_machine_families),
            "yes" if profile.requires_ssh else "no",
            "yes" if profile.supports_utilization_report else "no",
            _join_notes(profile.notes),
        )
    console.print(table)


@catalog_app.command("templates")
def list_template_jobs() -> None:
    """List the template job catalog and the environment variables used to resolve it."""
    table = rich.table.Table(title="UCloud template job catalog")
    table.add_column("Entry", style="cyan")
    table.add_column("Profile key", style="white")
    table.add_column("Template env var", style="green")
    table.add_column("Current value", style="white")
    table.add_column("Purpose", style="white")
    table.add_column("Notes", style="white")
    for entry in TEMPLATE_JOB_CATALOG:
        current_value = entry.current_value or "-"
        table.add_row(
            entry.display_name,
            entry.profile_name,
            entry.env_var,
            current_value,
            entry.purpose,
            _join_notes(entry.notes),
        )
    console.print(table)


@catalog_app.command("machines")
def list_machines(
    profile: str | None = typer.Option(None, help="Optional standard job profile to filter machine types"),
) -> None:
    """List the known machine types documented by UCloud."""
    if profile is not None:
        resolved_profile = profile_by_name(profile)
        if resolved_profile is None:
            raise typer.BadParameter(f"Unknown job profile: {profile!r}")
        machines = machine_products_for_profile(resolved_profile.name)
    else:
        machines = MACHINE_CATALOG

    table = rich.table.Table(title="UCloud machine types")
    table.add_column("Product", style="cyan")
    table.add_column("Provider", style="white")
    table.add_column("Class", style="magenta")
    table.add_column("vCPUs", style="yellow")
    table.add_column("CPU model", style="white")
    table.add_column("RAM GiB", style="yellow")
    table.add_column("Memory type", style="white")
    table.add_column("GPUs", style="yellow")
    table.add_column("GPU model", style="white")
    table.add_column("MIG instances", style="yellow")
    table.add_column("MIG profile", style="white")
    table.add_column("Core-hours/hour", style="yellow")
    table.add_column("GPU-hours/hour", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Notes", style="white")
    for machine in machines:
        gpu_hours_display = machine.gpu_hours_label or (
            "-" if machine.gpu_hours_per_hour is None else str(machine.gpu_hours_per_hour)
        )
        table.add_row(
            machine.product,
            machine.provider,
            machine.machine_class,
            "-" if machine.cpu_vcpus is None else str(machine.cpu_vcpus),
            machine.cpu_model or "-",
            "-" if machine.memory_gib is None else str(machine.memory_gib),
            machine.memory_type or "-",
            "-" if machine.gpu_count is None else str(machine.gpu_count),
            machine.gpu_model or "-",
            "-" if machine.mig_instances is None else str(machine.mig_instances),
            machine.mig_profile or "-",
            "-" if machine.core_hours_per_hour is None else str(machine.core_hours_per_hour),
            gpu_hours_display,
            machine.status or "-",
            _join_notes(machine.notes),
        )
    console.print(table)


if __name__ == "__main__":
    try:
        app()
    except SettingsError as exc:
        raise typer.Exit(code=2) from exc
