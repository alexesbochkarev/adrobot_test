from typing import Any

import httpx
from fastapi import Request


class KeitaroError(Exception):
    def __init__(self, code: str, *, uncertain: bool = False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


class KeitaroClient:
    """Admin API transport. Never retries writes or exposes upstream response bodies."""

    def __init__(self, client: httpx.Client):
        self.client = client

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        write = method != "GET"
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise KeitaroError("keitaro_timeout", uncertain=write) from None
        except httpx.RequestError:
            raise KeitaroError("keitaro_unavailable", uncertain=write) from None
        if response.status_code >= 500:
            raise KeitaroError("keitaro_server_error", uncertain=write)
        if response.status_code in (401, 403):
            raise KeitaroError("keitaro_access_denied")
        if response.status_code == 404:
            raise KeitaroError("keitaro_not_found")
        if response.status_code == 429:
            raise KeitaroError("keitaro_rate_limited", uncertain=write)
        if not 200 <= response.status_code < 300:
            raise KeitaroError("keitaro_request_rejected", uncertain=write and response.is_redirect)
        try:
            return response.json()
        except ValueError:
            raise KeitaroError("keitaro_invalid_response", uncertain=write) from None

    def list_items(self, resource: str, **params: str) -> list[dict[str, Any]]:
        data = self.request("GET", resource, params=params)
        if not isinstance(data, list) or any(
            not isinstance(item, dict)
            or not isinstance(item.get("id"), int)
            or not isinstance(item.get("name"), str)
            for item in data
        ):
            raise KeitaroError("keitaro_invalid_response")
        return data

    def get_offer(self, offer_id: int) -> dict[str, Any]:
        data = self.request("GET", f"offers/{offer_id}")
        if not isinstance(data, dict) or data.get("id") != offer_id:
            raise KeitaroError("keitaro_invalid_response")
        return data

    def create_campaign(self, payload: dict[str, Any]) -> int:
        return self._created_id(self.request("POST", "campaigns", json=payload))

    def create_stream(self, payload: dict[str, Any]) -> int:
        return self._created_id(self.request("POST", "streams", json=payload))

    def enable_campaign(self, campaign_id: int) -> None:
        data = self.request("POST", f"campaigns/{campaign_id}/enable")
        if (
            not isinstance(data, dict)
            or data.get("id") != campaign_id
            or data.get("state") != "active"
        ):
            raise KeitaroError("keitaro_invalid_response", uncertain=True)

    @staticmethod
    def _created_id(data: Any) -> int:
        if not isinstance(data, dict) or type(data.get("id")) is not int or data["id"] <= 0:
            raise KeitaroError("keitaro_invalid_response", uncertain=True)
        return data["id"]


def get_keitaro(request: Request) -> KeitaroClient:
    client = request.app.state.keitaro
    if client is None:
        raise KeitaroError("keitaro_not_configured")
    return client
