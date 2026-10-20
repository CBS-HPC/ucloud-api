from __future__ import annotations

from functools import wraps
import json
from pathlib import Path

import rich.console
import rich.table
import typer

from .client import UCloudClient
from .resources import (
    ManagementError, RESOURCE_NAMESPACES, create_resource, delete_resource, list_resources,
    management_call, prepare_resource, scoped_resource, update_resource, wait_for_resource,
)
from .settings import Settings, SettingsError
from .ssh_keys import (
    check_ssh_key, delete_public_key, key_fingerprint, list_ssh_keys, read_public_key,
    register_public_key, ssh_key_summary,
)


def safe_cli(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ManagementError, SettingsError, ValueError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from None
        except OSError:
            typer.echo("Could not access the requested local file or operation record", err=True)
            raise typer.Exit(1) from None
    return wrapped


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("The specification must be a JSON object")
    return data


def emit(value, as_json: bool = False) -> None:
    if as_json or not isinstance(value, list):
        typer.echo(json.dumps(value, indent=2))
        return
    table = rich.table.Table()
    fields = list(value[0]) if value else ["result"]
    for field in fields:
        table.add_column(field)
    for item in value:
        table.add_row(*(str(item.get(field, "-")) for field in fields))
    rich.console.Console().print(table)


def resource_summary(resource: dict) -> dict:
    specification = resource.get("specification") or {}
    status = resource.get("status") or {}
    result = {"id": resource.get("id"), "product": specification.get("product"), "state": status.get("state"),
              "bound_to": (status["boundTo"] or []) if "boundTo" in status else None}
    if "domain" in specification:
        result["domain"] = specification["domain"]
    if "ipAddress" in status:
        result["ip_address"] = status["ipAddress"]
    return result


def register_resource_group(app: typer.Typer, name: str, namespace: str) -> None:
    group = typer.Typer(help=f"Manage {name} in the configured workspace; writes preview unless --yes is supplied")
    app.add_typer(group, name=name)

    @group.command("list")
    @safe_cli
    def list_command(as_json: bool = typer.Option(False, "--json")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            emit([resource_summary(resource) for resource in list_resources(client, namespace)], as_json)

    @group.command("show")
    @safe_cli
    def show_command(resource_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            emit(resource_summary(scoped_resource(client, namespace, resource_id)), as_json)

    @group.command("products")
    @safe_cli
    def products_command(as_json: bool = typer.Option(False, "--json")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            emit(management_call(client.retrieve_resource_products, namespace), as_json)

    @group.command("activate" if namespace == "licenses" else "create")
    @safe_cli
    def create_command(
        spec: Path = typer.Option(..., exists=True, dir_okay=False, help="JSON resource specification"),
        yes: bool = typer.Option(False, "--yes", help="Confirm allocation/activation and potential public exposure"),
        wait: bool = typer.Option(False, "--wait", help="Wait for READY; a timeout does not delete the resource"),
        timeout: float = typer.Option(180, min=1, help="Readiness budget in seconds"),
        operation_dir: Path = typer.Option(Path("artifacts/resource-operations")),
    ) -> None:
        with UCloudClient(Settings.from_env()) as client:
            prepared = prepare_resource(client, namespace, read_object(spec))
            if not yes:
                emit({"preview": True, "namespace": namespace, "specification": prepared,
                      "warning": "Persistent resource; confirm allocation and any public exposure with --yes"})
                return
            result = create_resource(client, namespace, prepared, operation_dir=operation_dir)
            if wait:
                typer.echo("Resource allocated; operation record: " + result["operation_record"], err=True)
                result["resource"] = resource_summary(wait_for_resource(client, namespace, result["id"], timeout_seconds=timeout))
            emit(result)

    @group.command("delete")
    @safe_cli
    def delete_command(resource_id: str, yes: bool = typer.Option(False, "--yes")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            if not yes:
                emit({"preview": True, "operation": "delete", "resource": resource_summary(scoped_resource(client, namespace, resource_id))})
                return
            emit(delete_resource(client, namespace, resource_id))

    @group.command("wait")
    @safe_cli
    def wait_command(resource_id: str, timeout: float = typer.Option(180, min=1)) -> None:
        with UCloudClient(Settings.from_env()) as client:
            emit(resource_summary(wait_for_resource(client, namespace, resource_id, timeout_seconds=timeout)))

    def register_update(command_name: str, operation: str) -> None:
        @group.command(command_name)
        @safe_cli
        def update_command(
            resource_id: str, spec: Path = typer.Option(..., exists=True, dir_okay=False),
            yes: bool = typer.Option(False, "--yes"),
        ) -> None:
            value = read_object(spec)
            with UCloudClient(Settings.from_env()) as client:
                if not yes:
                    scoped_resource(client, namespace, resource_id)
                    emit({"preview": True, "operation": operation, "id": resource_id, "changes": value})
                    return
                emit(update_resource(client, namespace, resource_id, operation, value))

    register_update("labels", "updateLabels")
    register_update("acl", "updateAcl")
    if namespace == "networkips":
        register_update("firewall", "firewall")


def register_management_commands(app: typer.Typer) -> None:
    for name, namespace in RESOURCE_NAMESPACES.items():
        register_resource_group(app, name, namespace)
    group = typer.Typer(help="Manage account SSH public keys; private keys are never uploaded")
    app.add_typer(group, name="ssh-keys")

    @group.command("list")
    @safe_cli
    def list_command(as_json: bool = typer.Option(False, "--json")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            emit([ssh_key_summary(key) for key in list_ssh_keys(client)], as_json)

    @group.command("show")
    @safe_cli
    def show_command(key_id: str, as_json: bool = typer.Option(False, "--json")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            emit(ssh_key_summary(management_call(client.retrieve_ssh_key, key_id)), as_json)

    @group.command("check")
    @safe_cli
    def check_command(public_key: Path | None = typer.Option(None, exists=True, dir_okay=False)) -> None:
        settings = Settings.from_env()
        with UCloudClient(settings) as client:
            result = check_ssh_key(client, settings, public_key)
            emit(result)
            if result["state"] != "MATCHED":
                raise typer.Exit(1)

    @group.command("register")
    @safe_cli
    def register_command(
        public_key: Path = typer.Option(..., exists=True, dir_okay=False),
        title: str = typer.Option(...), yes: bool = typer.Option(False, "--yes"),
        operation_dir: Path = typer.Option(Path("artifacts/resource-operations")),
    ) -> None:
        key = read_public_key(public_key)
        if not title.strip():
            raise ValueError("Key title must not be empty")
        if not yes:
            emit({"preview": True, "operation": "register", "title": title, "fingerprint": key_fingerprint(key)})
            return
        with UCloudClient(Settings.from_env()) as client:
            emit(register_public_key(client, title, key, operation_dir=operation_dir))

    @group.command("delete")
    @safe_cli
    def delete_command(key_id: str, yes: bool = typer.Option(False, "--yes")) -> None:
        with UCloudClient(Settings.from_env()) as client:
            if not yes:
                key = management_call(client.retrieve_ssh_key, key_id)
                emit({"preview": True, "operation": "delete", "key": ssh_key_summary(key)})
                return
            emit(delete_public_key(client, key_id))
