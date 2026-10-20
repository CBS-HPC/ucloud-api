from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .settings import Settings


class UCloudAPIError(RuntimeError):
    """Raised when the UCloud API returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


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
        timeout: float | None = None,
    ) -> httpx.Response:
        response = self._client.request(method, path, params=params, json=json,
                                        **({"timeout": timeout} if timeout is not None else {}))
        if response.status_code >= 400:
            raise UCloudAPIError(
                f"{method} {path} failed with HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
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
        include_application: bool = False,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "/api/jobs/browse",
            params={
                "itemsPerPage": items_per_page,
                "sortBy": sort_by,
                "includeParameters": str(include_parameters).lower(),
                **({"includeApplication": "true"} if include_application else {}),
            },
        ).json()

    def retrieve_job(
        self,
        job_id: str,
        *,
        include_updates: bool = True,
        include_application: bool = False,
        request_timeout: float | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            "/api/jobs/retrieve",
            params={
                "id": job_id,
                "includeUpdates": str(include_updates).lower(),
                **({"includeApplication": "true", "includeParameters": "true"} if include_application else {}),
            },
            **({"timeout": request_timeout} if request_timeout is not None else {}),
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

    def browse_resources(
        self, namespace: str, *, items_per_page: int = 100, next_page: str | None = None,
    ) -> dict[str, Any]:
        self._validate_resource_namespace(namespace)
        params = {"itemsPerPage": items_per_page, "includeOthers": "true"}
        if next_page is not None:
            params["next"] = next_page
        return self.request("GET", f"/api/{namespace}/browse", params=params).json()

    def retrieve_resource(self, namespace: str, resource_id: str) -> dict[str, Any]:
        self._validate_resource_namespace(namespace)
        return self.request("GET", f"/api/{namespace}/retrieve", params={"id": resource_id}).json()

    def retrieve_resource_products(self, namespace: str) -> dict[str, Any]:
        self._validate_resource_namespace(namespace)
        return self.request("GET", f"/api/{namespace}/retrieveProducts").json()

    def create_resource(self, namespace: str, specification: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_resource_namespace(namespace)
        return self.request("POST", f"/api/{namespace}", json={"items": [dict(specification)]}).json()

    def delete_resource(self, namespace: str, resource_id: str) -> dict[str, Any]:
        self._validate_resource_namespace(namespace)
        response = self.request("DELETE", f"/api/{namespace}", json={"items": [{"id": resource_id}]})
        return response.json() if response.content else {}

    def update_resource(self, namespace: str, operation: str, item: Mapping[str, Any]) -> dict[str, Any]:
        self._validate_resource_namespace(namespace)
        if operation not in {"updateAcl", "updateLabels"} and not (namespace == "networkips" and operation == "firewall"):
            raise ValueError("Unsupported resource update")
        response = self.request("POST", f"/api/{namespace}/{operation}", json={"items": [dict(item)]})
        return response.json() if response.content else {}

    @staticmethod
    def _validate_resource_namespace(namespace: str) -> None:
        if namespace not in {"ingresses", "networkips", "licenses"}:
            raise ValueError("Unsupported resource namespace")

    def browse_ssh_keys(self, *, items_per_page: int = 100, next_page: str | None = None) -> dict[str, Any]:
        params = {"itemsPerPage": items_per_page}
        if next_page is not None:
            params["next"] = next_page
        return self.request("GET", "/api/ssh/browse", params=params).json()

    def retrieve_ssh_key(self, key_id: str) -> dict[str, Any]:
        return self.request("GET", "/api/ssh/retrieve", params={"id": key_id}).json()

    def register_ssh_key(self, title: str, public_key: str) -> dict[str, Any]:
        return self.request("POST", "/api/ssh", json={"items": [{"title": title, "key": public_key}]}).json()

    def delete_ssh_key(self, key_id: str) -> dict[str, Any]:
        response = self.request("DELETE", "/api/ssh", json={"items": [{"id": key_id}]})
        return response.json() if response.content else {}

    def retrieve_compute_products(self) -> dict[str, Any]:
        return self.request("GET", "/api/jobs/retrieveProducts").json()
