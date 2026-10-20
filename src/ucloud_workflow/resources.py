from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
from uuid import uuid4

import httpx

from .client import UCloudAPIError, UCloudClient


RESOURCE_NAMESPACES = {"links": "ingresses", "ips": "networkips", "licenses": "licenses"}


class ManagementError(RuntimeError):
    """A management failure safe to display without raw HTTP response bodies."""


class CreateOutcomeUnknownError(ManagementError):
    """Creation may have succeeded; reconcile the operation record before retrying."""

    def __init__(self, message: str, *, resource_id: str | None = None, operation_record: Path | None = None) -> None:
        super().__init__(message)
        self.resource_id = resource_id
        self.operation_record = operation_record


def management_call(function: Callable, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (UCloudAPIError, httpx.HTTPError, ValueError):
        raise ManagementError("UCloud management request failed; check credentials, permissions, and connectivity") from None


def browse_all(fetch_page: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    next_page = None
    seen = set()
    for _ in range(100):
        page = management_call(fetch_page, next_page=next_page)
        if not isinstance(page, Mapping) or not isinstance(page.get("items"), list):
            raise ManagementError("Malformed browse response: expected an items list")
        if any(not isinstance(item, dict) for item in page["items"]):
            raise ManagementError("Malformed browse item")
        items.extend(page["items"])
        next_page = page.get("next")
        if next_page is None or next_page == "":
            return items
        if not isinstance(next_page, str) or next_page in seen:
            raise ManagementError("Malformed or repeated pagination cursor")
        seen.add(next_page)
    raise ManagementError("Browse exceeded the page limit; refine the workspace scope")


def list_resources(client: UCloudClient, namespace: str) -> list[dict[str, Any]]:
    client._validate_resource_namespace(namespace)
    return browse_all(lambda **kwargs: client.browse_resources(namespace, **kwargs))


def scoped_resource(client: UCloudClient, namespace: str, resource_id: str) -> dict[str, Any]:
    if not resource_id or not any(str(item.get("id")) == resource_id for item in list_resources(client, namespace)):
        raise ManagementError("Resource is not visible in the selected workspace")
    resource = management_call(client.retrieve_resource, namespace, resource_id)
    if not isinstance(resource, dict) or str(resource.get("id")) != resource_id:
        raise ManagementError("Malformed resource response")
    return resource


def product_reference(value: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(field), str) or not value[field].strip()
        for field in ("id", "category", "provider")
    ):
        raise ValueError("Product requires non-empty id, category, and provider")
    return {field: value[field] for field in ("id", "category", "provider")}


def product_support(client: UCloudClient, namespace: str, product: Mapping[str, str]) -> dict[str, Any]:
    reference = product_reference(product)
    data = management_call(client.retrieve_resource_products, namespace)
    return find_product_support(data, reference)


def find_product_support(data: Any, reference: Mapping[str, str]) -> dict[str, Any]:
    reference = product_reference(reference)
    providers = data.get("productsByProvider") if isinstance(data, Mapping) else None
    if not isinstance(providers, Mapping):
        raise ManagementError("Malformed product discovery response")
    entries = providers.get(reference["provider"], [])
    if not isinstance(entries, list):
        raise ManagementError("Malformed provider product list")
    for entry in entries:
        if not isinstance(entry, Mapping) or (entry.get("support") is not None and not isinstance(entry["support"], Mapping)):
            raise ManagementError("Malformed provider product entry")
        support = entry.get("support") or {}
        candidate = support.get("product")
        if candidate is None:
            advertised = entry.get("product") or {}
            if not isinstance(advertised, Mapping):
                raise ManagementError("Malformed advertised product")
            category = advertised.get("category") or {}
            candidate = {
                "id": advertised.get("name"),
                "category": category.get("name") if isinstance(category, Mapping) else category,
                "provider": category.get("provider") if isinstance(category, Mapping) else reference["provider"],
            }
        if candidate == reference:
            return support
    raise ManagementError("Product is not advertised by the selected provider")


def validate_firewall(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"openPorts"} or not isinstance(value["openPorts"], list):
        raise ValueError("Firewall requires an explicit openPorts list")
    for port in value["openPorts"]:
        if not isinstance(port, dict) or set(port) != {"start", "end", "protocol"}:
            raise ValueError("Each port range requires start, end, and protocol")
        if type(port["start"]) is not int or type(port["end"]) is not int or not 1 <= port["start"] <= port["end"] <= 65535:
            raise ValueError("Port ranges must be within 1..65535")
        if port["protocol"] not in {"TCP", "UDP"}:
            raise ValueError("Protocol must be TCP or UDP")
    return deepcopy(value)


def validate_labels(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise ValueError("Labels must be a JSON object of strings")
    return dict(value)


def prepare_resource(client: UCloudClient, namespace: str, specification: Mapping[str, Any]) -> dict[str, Any]:
    client._validate_resource_namespace(namespace)
    allowed = {"product", "labels"}
    if namespace == "ingresses":
        allowed.add("domain")
    if namespace == "networkips":
        allowed.add("firewall")
    if not isinstance(specification, Mapping) or set(specification) - allowed:
        raise ValueError("Unsupported resource specification fields")
    result = deepcopy(dict(specification))
    result["product"] = product_reference(result.get("product"))
    if "labels" in result:
        result["labels"] = validate_labels(result["labels"])
    support = product_support(client, namespace, result["product"])
    if namespace == "ingresses":
        domain = result.get("domain")
        prefix, suffix = support.get("domainPrefix"), support.get("domainSuffix")
        if not isinstance(prefix, str) or not isinstance(suffix, str) or not suffix:
            raise ManagementError("Provider did not supply a usable domain pattern")
        if not isinstance(domain, str):
            raise ValueError("Public Links require a domain")
        domain = domain.lower()
        if not domain.startswith(prefix) or not domain.endswith(suffix):
            raise ValueError("Domain does not match the provider pattern")
        name = domain[len(prefix):len(domain) - len(suffix)]
        if not re.fullmatch(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
            raise ValueError("Domain name must be a single DNS label starting with a letter")
        result["domain"] = domain
    if namespace == "networkips":
        firewall = support.get("firewall") or {}
        firewall_supported = isinstance(firewall, Mapping) and firewall.get("enabled") is True
        if not firewall_supported:
            raise ManagementError("Cannot enforce closed-by-default IP ports without provider firewall support")
        result["firewall"] = validate_firewall(result.get("firewall", {"openPorts": []}))
    return result


def write_operation(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump(record, temporary, indent=2)
        temporary_name = temporary.name
    try:
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def recorded_create(
    function: Callable[[], dict[str, Any]], *, namespace: str, project: str | None,
    operation_dir: Path = Path("artifacts/resource-operations"),
) -> dict[str, Any]:
    path = operation_dir / f"{uuid4().hex}.json"
    record = {"operation": "create", "namespace": namespace, "project": project,
              "checked_at": datetime.now(timezone.utc).isoformat(), "outcome": "pending", "resource_id": None}
    write_operation(path, record)

    def persist_outcome() -> None:
        try:
            write_operation(path, record)
        except OSError:
            raise CreateOutcomeUnknownError(
                "Creation record could not be saved; manual reconciliation is required before retrying",
                resource_id=record["resource_id"], operation_record=path,
            ) from None

    try:
        response = function()
    except UCloudAPIError as error:
        uncertain = error.status_code is None or error.status_code == 408 or error.status_code >= 500
        record["outcome"] = "unknown" if uncertain else "failed"
        persist_outcome()
        if uncertain:
            raise CreateOutcomeUnknownError("Creation outcome unknown; reconcile operation records before retrying", operation_record=path) from None
        raise ManagementError("Creation rejected; check allocation, permissions, and the operation record") from None
    except (httpx.HTTPError, ValueError):
        record["outcome"] = "unknown"
        persist_outcome()
        raise CreateOutcomeUnknownError("Creation outcome unknown; reconcile operation records before retrying", operation_record=path) from None
    except (KeyboardInterrupt, SystemExit) as error:
        record["outcome"] = "unknown"
        try:
            persist_outcome()
        except CreateOutcomeUnknownError:
            error.add_note("Creation record could not be finalized; reconcile pending operation records")
        raise
    responses = response.get("responses") if isinstance(response, Mapping) else None
    resource_id = responses[0].get("id") if isinstance(responses, list) and len(responses) == 1 and isinstance(responses[0], Mapping) else None
    if not isinstance(resource_id, str) or not resource_id.strip():
        record["outcome"] = "unknown"
        persist_outcome()
        raise CreateOutcomeUnknownError("Creation returned no usable ID; reconcile operation records before retrying", operation_record=path)
    record.update(outcome="created", resource_id=resource_id)
    persist_outcome()
    return {"id": resource_id, "operation_record": str(path)}


def create_resource(
    client: UCloudClient, namespace: str, specification: Mapping[str, Any], *,
    operation_dir: Path = Path("artifacts/resource-operations"),
) -> dict[str, Any]:
    prepared = prepare_resource(client, namespace, specification)
    return recorded_create(lambda: client.create_resource(namespace, prepared), namespace=namespace,
                           project=client.settings.project, operation_dir=operation_dir)


def wait_for_resource(client: UCloudClient, namespace: str, resource_id: str, *, timeout_seconds: float = 180, poll_seconds: float = 2) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or not math.isfinite(poll_seconds) or timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("Wait budgets must be finite and positive")
    deadline = time.monotonic() + timeout_seconds
    scoped_resource(client, namespace, resource_id)
    while True:
        resource = management_call(client.retrieve_resource, namespace, resource_id)
        if not isinstance(resource, Mapping) or not isinstance(resource.get("status"), Mapping):
            raise ManagementError("Malformed resource readiness response")
        state = resource["status"].get("state")
        if state == "READY":
            return resource
        if state != "PREPARING":
            raise ManagementError("Resource is unavailable or returned an unknown state")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ManagementError("Resource readiness deadline exceeded; resource has not been deleted")
        time.sleep(min(poll_seconds, remaining))


def delete_resource(client: UCloudClient, namespace: str, resource_id: str) -> dict[str, Any]:
    resource = scoped_resource(client, namespace, resource_id)
    status = resource.get("status") or {}
    if not isinstance(status, Mapping):
        raise ManagementError("Malformed resource status")
    if "boundTo" not in status or (status["boundTo"] is not None and not isinstance(status["boundTo"], list)):
        raise ManagementError("Cannot establish whether the resource is in use")
    if status["boundTo"]:
        raise ManagementError("Resource is bound to a job; detach it before deletion")
    management_call(client.delete_resource, namespace, resource_id)
    return {"id": resource_id, "deleted": True}


def update_resource(client: UCloudClient, namespace: str, resource_id: str, operation: str, value: Any) -> dict[str, Any]:
    resource = scoped_resource(client, namespace, resource_id)
    if operation == "updateLabels":
        item = {"id": resource_id, "labels": validate_labels(value)}
    elif operation == "updateAcl":
        if not isinstance(value, dict) or set(value) != {"added", "deleted"} or any(not isinstance(value[field], list) for field in value):
            raise ValueError("ACL updates require explicit added and deleted lists")
        item = {"id": resource_id, **value}
    elif namespace == "networkips" and operation == "firewall":
        support = product_support(client, namespace, resource["specification"]["product"])
        if (support.get("firewall") or {}).get("enabled") is not True:
            raise ManagementError("Provider does not advertise firewall support")
        item = {"id": resource_id, "firewall": validate_firewall(value)}
    else:
        raise ValueError("Unsupported resource update")
    management_call(client.update_resource, namespace, operation, item)
    return {"id": resource_id, "updated": operation}
