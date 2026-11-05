import time
from typing import Any, Dict, Optional
import httpx
from app.config import settings


class PayPalAPIError(Exception):
    """Exception raised for errors returned by PayPal API."""

    def __init__(self, status_code: int, response_body: Any, message: str = ""):
        self.status_code = status_code
        self.response_body = response_body
        self.message = message or f"PayPal API returned status {status_code}: {response_body}"
        super().__init__(self.message)


class PayPalClient:
    """PayPal REST API Client for Sandbox."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        secret: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.client_id = client_id or settings.PAYPAL_CLIENT_ID
        self.secret = secret or settings.PAYPAL_SECRET
        self.base_url = (base_url or settings.PAYPAL_BASE_URL).rstrip("/")
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """Obtain or return a cached OAuth 2.0 Bearer access token."""
        now = time.time()
        # Return cached token if valid for at least another 60 seconds
        if not force_refresh and self._access_token and now < (self._token_expires_at - 60):
            return self._access_token

        if not self.client_id or not self.secret:
            raise PayPalAPIError(
                status_code=401,
                response_body={"error": "missing_credentials"},
                message="PayPal Client ID and Secret must be configured.",
            )

        token_url = f"{self.base_url}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }
        data = {"grant_type": "client_credentials"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    token_url,
                    headers=headers,
                    data=data,
                    auth=(self.client_id, self.secret),
                )
            except httpx.RequestError as exc:
                raise PayPalAPIError(
                    status_code=500,
                    response_body=str(exc),
                    message=f"Network error requesting PayPal token: {exc}",
                )

        if response.status_code != 200:
            try:
                err_body = response.json()
            except Exception:
                err_body = response.text
            raise PayPalAPIError(
                status_code=response.status_code,
                response_body=err_body,
                message=f"Failed to obtain PayPal access token ({response.status_code}): {err_body}",
            )

        payload = response.json()
        self._access_token = payload.get("access_token", "")
        expires_in = payload.get("expires_in", 32400)
        self._token_expires_at = now + float(expires_in)
        return self._access_token

    async def get_headers(self) -> Dict[str, str]:
        """Return authorization and content headers for PayPal REST API calls."""
        token = await self.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


# Global default client instance
paypal_client = PayPalClient()
