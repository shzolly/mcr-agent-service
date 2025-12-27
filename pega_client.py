# pega_client.py
import os
import httpx
import base64
from typing import Any, Dict, Optional


class PegaClient:
    def __init__(self):
        self.base_url = os.environ["PEGA_BASE_URL"].rstrip("/")
        self.timeout_s = float(os.getenv("PEGA_TIMEOUT_S", "20"))

        # Basic Auth credentials
        self.username = os.getenv("PEGA_BASIC_USERNAME")
        self.password = os.getenv("PEGA_BASIC_PASSWORD")

        if not self.username or not self.password:
            raise RuntimeError("Missing PEGA_BASIC_USERNAME or PEGA_BASIC_PASSWORD")

    def _headers(self) -> Dict[str, str]:
        auth_bytes = f"{self.username}:{self.password}".encode("utf-8")
        auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_b64}",
        }

    async def call_tool(
        self,
        tool_name: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Call the unified Pega tool endpoint:
        POST /mcr/tickets/tools/{tool_name}
        """
        url = f"{self.base_url}/mcr/tickets/tools/{tool_name}"
        headers = self._headers()
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
