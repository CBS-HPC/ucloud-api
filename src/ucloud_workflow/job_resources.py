from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .client import UCloudAPIError, UCloudClient
from .jobs import JobLaunchResult, build_job_specification, extract_job_id
from .resources import (
    CreateOutcomeUnknownError, ManagementError, create_resource, delete_resource, find_product_support, management_call,
    prepare_resource, product_reference, product_support, scoped_resource, wait_for_resource, write_operation,
)


def resource_selection(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"links", "ips", "licenses"}:
        raise ValueError("Resource selection accepts links, ips, and named licenses only")
    result = {"links": [], "ips": [], "licenses": {}}
    for field in ("links", "ips"):
        items = value.get(field, [])
        if not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items):
            raise ValueError("Link and IP selections must be lists of non-empty IDs")
        result[field] = list(dict.fromkeys(items))
    licenses = value.get("licenses", {})
    if not isinstance(licenses, Mapping) or any(
        not isinstance(name, str) or not name.strip() or not isinstance(identifier, str) or not identifier.strip()
        for name, identifier in licenses.items()
    ):
        raise ValueError("Licenses must map application parameter names to resource IDs")
    result["licenses"] = dict(licenses)
    return result


def template_with_application(client: UCloudClient, template_job_id: str | None) -> dict[str, Any]:
    if template_job_id:
        job = management_call(client.retrieve_job, template_job_id, include_updates=False, include_application=True)
    else:
        page = management_call(client.browse_jobs, items_per_page=1, include_application=True)
        items = page.get("items") if isinstance(page, Mapping) else None
        job = items[0] if isinstance(items, list) and items else None
    if not isinstance(job, dict) or not isinstance(job.get("specification"), Mapping):
        raise ManagementError("No usable template job with application metadata was returned")
    return job


def application_for_resources(job: Mapping[str, Any], specification: Mapping[str, Any]) -> dict[str, Any]:
    status = job.get("status") or {}
    application = status.get("resolvedApplication") if isinstance(status, Mapping) else None
    if not isinstance(application, dict) or not isinstance(application.get("invocation"), Mapping):
        raise ManagementError("Template application metadata is required for resource overrides")
    reference = specification.get("application") or {}
    metadata = application.get("metadata") or {}
    if not isinstance(reference, Mapping) or not isinstance(metadata, Mapping):
        raise ManagementError("Malformed application reference")
    if any(not reference.get(field) or reference.get(field) != metadata.get(field) for field in ("name", "version")):
        raise ManagementError("Resolved application does not match the job specification")
    return application


def validate_application_selection(application: Mapping[str, Any], selection: Mapping[str, Any], support: Mapping[str, Any]) -> None:
    invocation = application["invocation"]
    tool = invocation.get("tool") or {}
    resolved_tool = tool.get("tool") if isinstance(tool, Mapping) else None
    description = resolved_tool.get("description") if isinstance(resolved_tool, Mapping) else None
    backend = description.get("backend") if isinstance(description, Mapping) else None
    backend_key = {"DOCKER": "docker", "VIRTUAL_MACHINE": "virtualMachine", "NATIVE": "native"}.get(backend)
    backend_support = support.get(backend_key) or {}
    if not backend_key or not isinstance(backend_support, Mapping) or backend_support.get("enabled") is not True:
        raise ManagementError("Provider support for the application backend could not be established")
    if selection["links"] and (invocation.get("allowPublicLink") is not True or backend_support.get("web") is not True):
        raise ManagementError("The application/provider does not permit additional Public Links")
    if selection["ips"] and invocation.get("allowPublicIp") is not True:
        raise ManagementError("The application does not permit additional Public IPs")
    parameters = invocation.get("parameters") or []
    if not isinstance(parameters, list) or any(not isinstance(parameter, Mapping) for parameter in parameters):
        raise ManagementError("Malformed application parameters")
    license_names = {parameter.get("name") for parameter in parameters if parameter.get("type") == "license_server"}
    if set(selection["licenses"]) - license_names:
        raise ManagementError("A selected license is not a named license_server application parameter")


def merge_job_resources(
    client: UCloudClient, specification: Mapping[str, Any], selection: Mapping[str, Any], application: Mapping[str, Any],
) -> dict[str, Any]:
    selected = resource_selection(selection)
    product = product_reference(specification.get("product"))
    support = find_product_support(management_call(client.retrieve_compute_products), product)
    validate_application_selection(application, selected, support)
    result = deepcopy(dict(specification))
    resources = result.setdefault("resources", [])
    parameters = result.setdefault("parameters", {})
    if resources is None:
        resources = result["resources"] = []
    if parameters is None:
        parameters = result["parameters"] = {}
    if not isinstance(resources, list) or any(not isinstance(item, Mapping) for item in resources) or not isinstance(parameters, dict):
        raise ManagementError("Template resources/parameters have an unsupported shape")
    entries = [("ingresses", "ingress", identifier, None) for identifier in selected["links"]]
    entries += [("networkips", "network", identifier, None) for identifier in selected["ips"]]
    entries += [("licenses", "license_server", identifier, name) for name, identifier in selected["licenses"].items()]
    for namespace, value_type, identifier, parameter in entries:
        resource = scoped_resource(client, namespace, identifier)
        resource_product = product_reference((resource.get("specification") or {}).get("product"))
        if resource_product["provider"] != product["provider"]:
            raise ManagementError("Resource and job providers do not match")
        product_support(client, namespace, resource_product)
        status = resource.get("status") or {}
        if status.get("state") != "READY":
            raise ManagementError("Selected resource is not READY")
        if namespace != "licenses":
            if "boundTo" not in status or (status["boundTo"] is not None and not isinstance(status["boundTo"], list)):
                raise ManagementError("Cannot establish whether the selected resource is in use")
            if status["boundTo"]:
                raise ManagementError("Selected resource is already bound to a job")
        value = {"type": value_type, "id": identifier}
        if parameter is not None:
            parameters[parameter] = value
        elif not any(item.get("type") == value_type and item.get("id") == identifier for item in resources):
            resources.append(value)
    return result


@dataclass(frozen=True, slots=True)
class RunResourceRequest:
    namespace: str
    specification: Mapping[str, Any]
    parameter: str | None = None


@dataclass(frozen=True, slots=True)
class ManagedResourceRunResult:
    value: Any
    operation_record: Path
    cleanup_complete: bool


def run_with_job_resources(
    client: UCloudClient, operation: Callable[[JobLaunchResult], Any], *,
    requests: Sequence[RunResourceRequest] = (), existing: Mapping[str, Any] | None = None,
    template_job_id: str | None = None, hours: int, size: str | None = None,
    product: Mapping[str, str] | None = None, name: str | None = None,
    ssh_enabled: bool = True,
    resource_timeout_seconds: float = 180, operation_dir: Path = Path("artifacts/resource-operations"),
) -> ManagedResourceRunResult:
    """Own one job and only resources created by this call; always stop that job on exit."""
    if not math.isfinite(resource_timeout_seconds) or resource_timeout_seconds <= 0:
        raise ValueError("Resource readiness budget must be finite and positive")
    if type(hours) is not int or hours < 1:
        raise ValueError("Time allocation must be a positive whole number of hours")
    selected = resource_selection({} if existing is None else existing)
    template = template_with_application(client, template_job_id)
    specification = build_job_specification(template["specification"], hours=hours, size=size, product=product, name=name, ssh_enabled=ssh_enabled)
    application = application_for_resources(template, specification)
    specification = merge_job_resources(client, specification, selected, application)
    prepared = []
    planned = deepcopy(selected)
    for request in requests:
        if request.namespace not in {"ingresses", "networkips", "licenses"}:
            raise ValueError("Only links, IPs, and license activations can be created for a run")
        if request.namespace == "licenses":
            if not isinstance(request.parameter, str) or not request.parameter.strip() or request.parameter in planned["licenses"]:
                raise ValueError("Each new license needs a distinct application parameter")
            planned["licenses"][request.parameter] = "planned"
        else:
            if request.parameter is not None:
                raise ValueError("Only license activations accept a parameter name")
            planned["links" if request.namespace == "ingresses" else "ips"].append("planned")
        spec = prepare_resource(client, request.namespace, request.specification)
        if spec["product"]["provider"] != specification["product"]["provider"]:
            raise ManagementError("New resource and job providers do not match")
        prepared.append((request, spec))
    support = find_product_support(management_call(client.retrieve_compute_products), specification["product"])
    validate_application_selection(application, planned, support)
    path = operation_dir / f"run-{uuid4().hex}.json"
    reused = [{"namespace": namespace, "id": identifier, "ownership": "reused"}
              for namespace, identifiers in (("ingresses", selected["links"]), ("networkips", selected["ips"]),
                                             ("licenses", selected["licenses"].values())) for identifier in identifiers]
    record = {"operation": "job_resources", "project": client.settings.project, "job_id": None,
              "phase": "provisioning", "resources": reused, "cleanup_complete": False}
    write_operation(path, record)
    owned = []
    job_id = None
    submission_unknown = False
    original_error = None
    try:
        for request, spec in prepared:
            record["uncertain_creation"] = {"namespace": request.namespace, "resource_id": None, "operation_record": None}
            write_operation(path, record)
            try:
                created = create_resource(client, request.namespace, spec, operation_dir=operation_dir)
            except CreateOutcomeUnknownError as error:
                record["uncertain_creation"] = {"namespace": request.namespace, "resource_id": error.resource_id,
                                                "operation_record": str(error.operation_record) if error.operation_record else None}
                raise
            except ManagementError:
                record.pop("uncertain_creation", None)
                raise
            entry = {"namespace": request.namespace, "id": created["id"], "ownership": "created",
                     "operation_record": created["operation_record"], "cleanup": "pending"}
            owned.append(entry)
            record["resources"].append(entry)
            record.pop("uncertain_creation", None)
            write_operation(path, record)
            wait_for_resource(client, request.namespace, created["id"], timeout_seconds=resource_timeout_seconds)
            if request.namespace == "licenses":
                selected["licenses"][request.parameter] = created["id"]
            else:
                selected["links" if request.namespace == "ingresses" else "ips"].append(created["id"])
        specification = merge_job_resources(client, specification, selected, application)
        record["phase"] = "submitting"
        write_operation(path, record)
        submission_unknown = True
        try:
            response = client.submit_job(specification)
            job_id = extract_job_id(response)
        except UCloudAPIError as error:
            submission_unknown = error.status_code is None or error.status_code == 408 or error.status_code >= 500
            raise ManagementError("Job submission failed; consult the run operation record before retrying") from None
        except (httpx.HTTPError, ValueError, RuntimeError):
            raise ManagementError("Job submission outcome unknown; reconcile before retrying") from None
        submission_unknown = False
        record.update(job_id=job_id, phase="running_callback")
        write_operation(path, record)
        launched = JobLaunchResult(job_id, "", f"{client.settings.server.rstrip('/')}/app/jobs/properties/{job_id}", specification["product"]["id"])
        value = operation(launched)
    except BaseException as error:
        original_error = error
        if isinstance(error, CreateOutcomeUnknownError) or record.get("uncertain_creation"):
            record["unknown_creation"] = True
        raise
    finally:
        record["phase"] = "submission_unknown" if submission_unknown else "cleanup"
        can_cleanup = not submission_unknown
        if job_id is not None:
            try:
                management_call(client.terminate_job, job_id)
                record["job_termination"] = "requested"
            except Exception:
                can_cleanup = False
                record["job_termination"] = "failed"
        for entry in reversed(owned):
            if not can_cleanup:
                entry["cleanup"] = "retained"
                continue
            try:
                delete_resource(client, entry["namespace"], entry["id"])
                entry["cleanup"] = "deleted"
            except Exception:
                entry["cleanup"] = "incomplete"
        record["cleanup_complete"] = can_cleanup and not record.get("unknown_creation", False) and all(entry["cleanup"] == "deleted" for entry in owned)
        try:
            write_operation(path, record)
        except OSError:
            if original_error is None:
                raise ManagementError("Could not save the final run cleanup record; manual reconciliation is required") from None
            original_error.add_note("Could not save the cleanup record; manual reconciliation is required")
        if original_error is not None and not record["cleanup_complete"]:
            original_error.add_note("Run cleanup is incomplete; consult resource operation records")
    return ManagedResourceRunResult(value, path, record["cleanup_complete"])
