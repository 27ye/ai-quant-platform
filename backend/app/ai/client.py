from typing import Dict, List, Optional, Protocol

import httpx

from backend.app.ai.errors import (
    AIConfigurationError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
)


class LLMClient(Protocol):
    model_name: str

    async def complete_json(self, messages: List[Dict[str, str]]) -> str:
        """Return the assistant message content as a JSON string."""


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: float = 30.0,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not api_key.strip():
            raise AIConfigurationError("LLM_API_KEY is not configured")
        if not base_url.strip():
            raise AIConfigurationError("LLM_BASE_URL is not configured")
        if not model_name.strip():
            raise AIConfigurationError("LLM_MODEL is not configured")
        if timeout_seconds <= 0:
            raise AIConfigurationError("LLM_TIMEOUT_SECONDS must be positive")

        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def complete_json(self, messages: List[Dict[str, str]]) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            if self._http_client is not None:
                response = await self._http_client.post(
                    self._completion_url,
                    json=payload,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.post(
                        self._completion_url,
                        json=payload,
                        headers=headers,
                    )
        except httpx.RequestError as exc:
            raise LLMConnectionError("LLM request failed or timed out") from exc

        if response.status_code in (401, 403):
            raise LLMAuthenticationError("LLM authentication failed")
        if response.status_code == 429:
            raise LLMRateLimitError("LLM rate limit exceeded")
        if response.status_code >= 400:
            raise LLMResponseError(
                f"LLM endpoint returned HTTP {response.status_code}"
            )

        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("LLM response is missing message content") from exc

        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError("LLM response message content is empty")
        return content.strip()

    @property
    def _completion_url(self) -> str:
        return f"{self._base_url}/chat/completions"
