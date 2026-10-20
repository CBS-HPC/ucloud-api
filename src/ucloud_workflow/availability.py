from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import math
import time
from typing import Any

from .client import UCloudClient
from .resources import ManagementError, management_call, product_reference
from .jobs import JobLaunchResult, TERMINAL_STATES, latest_update_state, submit_job_from_latest_template


@dataclass(frozen=True, slots=True)
class MachineAvailability:
    product: dict[str, str]
    queue_status: str
    found: bool
    hardware: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AvailabilitySnapshot:
    checked_at: str
    machines: tuple[MachineAvailability, ...]


class ImmediateStartError(ManagementError):
    """Startup failed after submission; inspect termination_succeeded before recovery."""

    def __init__(self, *, job_id: str, termination_succeeded: bool) -> None:
        super().__init__("Immediate startup failed; job termination was requested" if termination_succeeded
                         else "Immediate startup failed and job termination failed; manual recovery is required")
        self.job_id = job_id
        self.termination_succeeded = termination_succeeded


@dataclass(frozen=True, slots=True)
class ImmediateStartResult:
    launch: JobLaunchResult
    availability: AvailabilitySnapshot


def check_machine_availability(
    client: UCloudClient, *, products: Sequence[Mapping[str, str]] | None = None,
) -> AvailabilitySnapshot:
    requested = [product_reference(product) for product in products] if products is not None else None
    data = management_call(client.retrieve_compute_products)
    providers = data.get("productsByProvider") if isinstance(data, Mapping) else None
    if not isinstance(providers, Mapping):
        raise ManagementError("Malformed compute-product response")
    machines = {}
    for provider, entries in providers.items():
        if not isinstance(entries, list):
            raise ManagementError("Malformed provider product list")
        for entry in entries:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("product"), Mapping) or (entry.get("support") is not None and not isinstance(entry["support"], Mapping)):
                raise ManagementError("Malformed compute-product entry")
            product = entry.get("product") or {}
            support = entry.get("support") or {}
            category = product.get("category") or {}
            reference = support.get("product") or {
                "id": product.get("name"), "category": category.get("name") if isinstance(category, Mapping) else category,
                "provider": provider,
            }
            try:
                reference = product_reference(reference)
            except ValueError:
                raise ManagementError("Malformed compute-product reference") from None
            if reference["provider"] != provider:
                raise ManagementError("Compute-product provider mismatch")
            identity = tuple(reference[field] for field in ("id", "category", "provider"))
            if identity in machines:
                raise ManagementError("Duplicate compute-product reference")
            status = support.get("queueStatus")
            status = status if isinstance(status, str) and status in {"AVAILABLE", "BUSY", "FULL"} else "UNKNOWN"
            hardware = {field: product[field] for field in ("cpu", "memoryInGigs", "gpu", "gpuModel", "fraction") if field in product}
            machines[identity] = MachineAvailability(reference, status, True, hardware)
    if requested is None:
        selected = list(machines.values())
    else:
        selected = [machines.get(tuple(reference[field] for field in ("id", "category", "provider")),
                                 MachineAvailability(reference, "UNKNOWN", False, {})) for reference in requested]
    return AvailabilitySnapshot(datetime.now(timezone.utc).isoformat(), tuple(selected))


def choose_available_machine(snapshot: AvailabilitySnapshot, *, allow_busy: bool = False) -> MachineAvailability | None:
    allowed = {"AVAILABLE", "BUSY"} if allow_busy else {"AVAILABLE"}
    return next((machine for machine in snapshot.machines if machine.found and machine.queue_status in allowed), None)


def submit_immediate_job(
    client: UCloudClient, *, products: Sequence[Mapping[str, str]], hours: int,
    template_job_id: str | None = None, name: str | None = None, allow_busy: bool = False,
    startup_timeout_seconds: float = 120, poll_interval_seconds: float = 2,
    resource_selection: Mapping[str, Any] | None = None,
    ssh_enabled: bool = True,
) -> ImmediateStartResult:
    """Try one explicitly approved product; queue information is not a reservation."""
    if not products:
        raise ValueError("At least one explicitly approved product is required")
    if type(hours) is not int or hours < 1:
        raise ValueError("Time allocation must be a positive whole number of hours")
    if any(not math.isfinite(value) or value <= 0 for value in (startup_timeout_seconds, poll_interval_seconds)):
        raise ValueError("Startup and polling budgets must be finite and positive")
    snapshot = check_machine_availability(client, products=products)
    selected = choose_available_machine(snapshot, allow_busy=allow_busy)
    if selected is None:
        raise ManagementError("No approved machine meets the immediate-start policy; no job was submitted")
    launched = management_call(
        submit_job_from_latest_template, client, product=selected.product, hours=hours, template_job_id=template_job_id, name=name,
        resource_selection=resource_selection,
        ssh_enabled=ssh_enabled,
    )
    deadline = time.monotonic() + startup_timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            job = management_call(client.retrieve_job, launched.job_id, include_updates=True, request_timeout=min(30, remaining))
            status = job.get("status") or {}
            state = status.get("state") or latest_update_state(job)
            if time.monotonic() >= deadline:
                raise TimeoutError
            if state == "RUNNING":
                return ImmediateStartResult(launched, snapshot)
            if state in TERMINAL_STATES:
                raise ManagementError("Job ended before immediate startup was confirmed")
            time.sleep(max(0, min(poll_interval_seconds, deadline - time.monotonic())))
    except BaseException as error:
        terminated = False
        try:
            management_call(client.terminate_job, launched.job_id)
            terminated = True
        except Exception:
            pass
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            if not terminated:
                error.add_note("Job termination failed; manual recovery is required")
            raise
        raise ImmediateStartError(job_id=launched.job_id, termination_succeeded=terminated) from None
