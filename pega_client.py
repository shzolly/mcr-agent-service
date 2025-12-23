# pega_client.py
import os
import httpx
from typing import Any, Dict, Optional

class PegaClient:
    def __init__(self):
        self.base_url = os.environ["PEGA_BASE_URL"].rstrip("/")
        self.timeout_s = float(os.getenv("PEGA_TIMEOUT_S", "20"))
        self.api_key = os.getenv("PEGA_API_KEY", "")  # optional
        self.bearer_token = os.getenv("PEGA_BEARER_TOKEN", "")  # optional

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def post(self, path: str, payload: Dict[str, Any], correlation_id: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = self._headers()
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
