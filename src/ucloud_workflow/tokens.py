from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


TokenExpiryState = str


@dataclass(frozen=True, slots=True)
class ApiTokenSummary:
    """Non-secret metadata for a UCloud API token."""

    token_id: str
    title: str
    expires_at: datetime | None
    expiry_state: TokenExpiryState
    days_remaining: float | None
    permissions: tuple[str, ...]


def parse_expiry_timestamp(value: str, *, now: datetime | None = None) -> int:
    """Convert an offset-aware ISO 8601 time into UCloud epoch milliseconds."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO 8601 timestamp, for example 2026-09-11T22:00:00Z") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone offset, for example 2026-09-11T22:00:00Z")

    expires_at = parsed.astimezone(timezone.utc)
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if expires_at <= observed_at:
        raise ValueError("expires_at must be in the future")
    return int(expires_at.timestamp() * 1000)


def expiry_timestamp_after_months(months: int, *, now: datetime | None = None) -> int:
    """Return UCloud epoch milliseconds after a positive number of calendar months."""
    if months < 1:
        raise ValueError("valid_for_months must be at least one")

    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    month_index = observed_at.month - 1 + months
    year = observed_at.year + month_index // 12
    month = month_index % 12 + 1
    day = min(observed_at.day, monthrange(year, month)[1])
    expires_at = observed_at.replace(year=year, month=month, day=day)
    return int(expires_at.timestamp() * 1000)


def resolve_expiry_timestamp(
    *,
    expires_at: str | None,
    valid_for_months: int | None,
    now: datetime | None = None,
) -> int:
    """Require exactly one supported way of declaring a token expiry."""
    if expires_at is None and valid_for_months is None:
        raise ValueError("provide exactly one of expires_at or valid_for_months")
    if expires_at is not None and valid_for_months is not None:
        raise ValueError("provide only one of expires_at or valid_for_months")
    if expires_at is not None:
        return parse_expiry_timestamp(expires_at, now=now)
    return expiry_timestamp_after_months(valid_for_months, now=now)


def parse_requested_permissions(values: Sequence[str]) -> tuple[dict[str, str], ...]:
    """Parse repeatable ``name:action`` CLI values into UCloud permission objects."""
    permissions: list[dict[str, str]] = []
    for value in values:
        name, separator, action = value.rpartition(":")
        if not separator or not name or not action:
            raise ValueError(f"invalid permission {value!r}; use NAME:ACTION")
        permissions.append({"name": name, "action": action})
    return tuple(permissions)


def build_api_token_specification(
    *,
    title: str,
    description: str,
    permissions: Sequence[str],
    expires_at: str | None = None,
    valid_for_months: int | None = None,
    provider: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the non-secret request payload for ``POST /api/tokens``."""
    cleaned_title = title.strip()
    if not cleaned_title:
        raise ValueError("title must not be empty")
    return {
        "title": cleaned_title,
        "description": description.strip(),
        "provider": provider.strip() if provider and provider.strip() else None,
        "requestedPermissions": list(parse_requested_permissions(permissions)),
        "expiresAt": resolve_expiry_timestamp(
            expires_at=expires_at,
            valid_for_months=valid_for_months,
            now=now,
        ),
    }


def _parse_ucloud_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if abs(value) >= 10_000_000_000 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return _parse_ucloud_timestamp(float(value))
        except ValueError:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    raise ValueError(f"Unsupported UCloud token expiry timestamp: {value!r}")


def _permission_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    names: list[str] = []
    for permission in value:
        if not isinstance(permission, Mapping):
            continue
        name = permission.get("name")
        action = permission.get("action")
        if isinstance(name, str) and isinstance(action, str):
            names.append(f"{name}:{action}")
    return tuple(names)


def summarize_api_tokens(
    response: Mapping[str, Any],
    *,
    now: datetime | None = None,
    expiring_within_days: int = 30,
) -> tuple[ApiTokenSummary, ...]:
    """Extract expiration status from ``GET /api/tokens/browse`` without exposing token values."""
    if expiring_within_days < 0:
        raise ValueError("expiring_within_days must be zero or greater")

    raw_items = response.get("items", ())
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes)):
        raise ValueError("UCloud token browse response does not contain an items list")

    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    warning_threshold = timedelta(days=expiring_within_days)
    summaries: list[ApiTokenSummary] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        specification = item.get("specification")
        if not isinstance(specification, Mapping):
            specification = {}

        expires_at = _parse_ucloud_timestamp(specification.get("expiresAt"))
        days_remaining = None if expires_at is None else (expires_at - observed_at).total_seconds() / 86_400
        if expires_at is None:
            expiry_state = "unknown"
        elif expires_at <= observed_at:
            expiry_state = "expired"
        elif expires_at - observed_at <= warning_threshold:
            expiry_state = "expiring-soon"
        else:
            expiry_state = "active"

        token_id = item.get("id")
        title = specification.get("title")
        summaries.append(
            ApiTokenSummary(
                token_id=token_id if isinstance(token_id, str) else "unknown",
                title=title if isinstance(title, str) and title else "Untitled token",
                expires_at=expires_at,
                expiry_state=expiry_state,
                days_remaining=days_remaining,
                permissions=_permission_names(specification.get("requestedPermissions")),
            )
        )

    return tuple(sorted(summaries, key=lambda item: item.expires_at or datetime.max.replace(tzinfo=timezone.utc)))
