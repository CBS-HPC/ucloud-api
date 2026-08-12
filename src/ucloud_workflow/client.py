from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .settings import Settings


class UCloudAPIError(RuntimeError):
    """Raised when the UCloud API returns an error response."""


class UCloudClient:
    """Thin HTTP client for the UCloud endpoints used by the workflow."""

    def __init__(self, settings: Settings, *, timeout: float = 30.0) -> None:
        self.settings = settings
        self._client = httpx.Client(
            base_url=settings.server.rstrip("/"),
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {settings.token}",
                "Project": settings.project,
                "Accept": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "UCloudClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> httpx.Response:
        response = self._client.request(method, path, params=params, json=json)
        if response.status_code >= 400:
            raise UCloudAPIError(
                f"{method} {path} failed with HTTP {response.status_code}: {response.text}"
            )
        return response

    def browse_wallets(self, *, include_children: bool = True) -> dict[str, Any]:
        return self.request(
            "GET",
            "/api/accounting/v2/browseWallets",
            params={"includeChildren": str(include_children).lower()},
        ).json()

    def browse_jobs(
        self,
        *,
        items_per_page: int = 1,
        sort_by: str = "CREATED_AT",
        include_parameters: bool = True,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "/api/jobs/browse",
            params={
                "itemsPerPage": items_per_page,
                "sortBy": sort_by,
                "includeParameters": str(include_parameters).lower(),
            },
        ).json()

    def retrieve_job(
        self,
        job_id: str,
        *,
        include_updates: bool = True,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "/api/jobs/retrieve",
            params={
                "id": job_id,
                "includeUpdates": str(include_updates).lower(),
            },
        ).json()

    def submit_job(self, specification: Mapping[str, Any]) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/jobs",
            json={"items": [dict(specification)]},
        ).json()

    def terminate_job(self, job_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/jobs/terminate",
            json={"items": [{"id": job_id}]},
        ).json()

    def browse_api_tokens(
        self,
        *,
        items_per_page: int = 100,
        filter_hidden: bool = False,
    ) -> dict[str, Any]:
        """Return non-secret API-token metadata, including ``specification.expiresAt``."""
        return self.request(
            "GET",
            "/api/tokens/browse",
            params={
                "itemsPerPage": items_per_page,
                "filterHidden": str(filter_hidden).lower(),
            },
        ).json()

    def create_api_token(self, specification: Mapping[str, Any]) -> dict[str, Any]:
        """Create one API token. The returned secret is available only in this response."""
        return self.request("POST", "/api/tokens", json=dict(specification)).json()

    def retrieve_api_token_options(self) -> dict[str, Any]:
        """Return token providers and permissions available to the authenticated user."""
        return self.request("GET", "/api/tokens/retrieveOptions").json()
