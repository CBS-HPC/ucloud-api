from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ucloud_workflow.tokens import (
    build_api_token_specification,
    expiry_timestamp_after_months,
    parse_expiry_timestamp,
    parse_requested_permissions,
    resolve_expiry_timestamp,
    summarize_api_tokens,
)


def test_summarize_api_tokens_classifies_expiry_from_milliseconds() -> None:
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    response = {
        "items": [
            {
                "id": "active",
                "specification": {
                    "title": "Long-lived token",
                    "expiresAt": int((now + timedelta(days=31)).timestamp() * 1000),
                    "requestedPermissions": [{"name": "jobs", "action": "READ"}],
                },
            },
            {
                "id": "soon",
                "specification": {
                    "title": "Rotate me",
                    "expiresAt": int((now + timedelta(days=7)).timestamp() * 1000),
                },
            },
            {
                "id": "expired",
                "specification": {
                    "title": "Old token",
                    "expiresAt": int((now - timedelta(seconds=1)).timestamp() * 1000),
                },
            },
        ]
    }

    summaries = summarize_api_tokens(response, now=now, expiring_within_days=30)

    assert [item.token_id for item in summaries] == ["expired", "soon", "active"]
    assert [item.expiry_state for item in summaries] == ["expired", "expiring-soon", "active"]
    assert summaries[2].permissions == ("jobs:READ",)


def test_summarize_api_tokens_rejects_invalid_response() -> None:
    with pytest.raises(ValueError, match="items list"):
        summarize_api_tokens({"items": "not a list"})


def test_build_api_token_specification_uses_epoch_milliseconds() -> None:
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)

    specification = build_api_token_specification(
        title="  Replacement workflow token ",
        description=" Rotate before expiry ",
        expires_at="2026-09-11T22:00:00Z",
        permissions=("jobs:READ", "jobs:WRITE"),
        now=now,
    )

    assert specification == {
        "title": "Replacement workflow token",
        "description": "Rotate before expiry",
        "provider": None,
        "requestedPermissions": [
            {"name": "jobs", "action": "READ"},
            {"name": "jobs", "action": "WRITE"},
        ],
        "expiresAt": 1_789_164_000_000,
    }


def test_token_creation_helpers_reject_unsafe_input() -> None:
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="timezone"):
        parse_expiry_timestamp("2026-09-11T22:00:00", now=now)
    with pytest.raises(ValueError, match="future"):
        parse_expiry_timestamp("2026-08-10T22:00:00Z", now=now)
    assert parse_requested_permissions(()) == ()
    with pytest.raises(ValueError, match="NAME:ACTION"):
        parse_requested_permissions(("jobs",))


def test_expiry_timestamp_after_months_uses_calendar_months() -> None:
    now = datetime(2026, 1, 31, 12, 30, tzinfo=timezone.utc)
    expected = datetime(2026, 2, 28, 12, 30, tzinfo=timezone.utc)

    assert expiry_timestamp_after_months(1, now=now) == int(expected.timestamp() * 1000)
    assert resolve_expiry_timestamp(expires_at=None, valid_for_months=1, now=now) == int(
        expected.timestamp() * 1000
    )

    with pytest.raises(ValueError, match="exactly one"):
        resolve_expiry_timestamp(expires_at=None, valid_for_months=None, now=now)
    with pytest.raises(ValueError, match="only one"):
        resolve_expiry_timestamp(
            expires_at="2026-02-28T12:30:00Z",
            valid_for_months=1,
            now=now,
        )
