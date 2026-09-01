import asyncio
import json

import httpx
import pytest

from backend.app.ai.client import OpenAICompatibleLLMClient
from backend.app.ai.errors import (
    AIConfigurationError,
    LLMAuthenticationError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMResponseError,
)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return OpenAICompatibleLLMClient(
        api_key="test-secret",
        base_url="https://llm.example/v1",
        model_name="test-model",
        http_client=http_client,
    ), http_client


def test_llm_client_returns_message_content_and_contract_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://llm.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-secret"
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"trend":"neutral"}'}}]},
        )

    async def run_test():
        client, http_client = make_client(handler)
        try:
            return await client.complete_json(
                [{"role": "user", "content": "test"}]
            )
        finally:
            await http_client.aclose()

    content = asyncio.run(run_test())

    assert content == '{"trend":"neutral"}'


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (429, LLMRateLimitError),
        (500, LLMResponseError),
    ],
)
def test_llm_client_maps_http_errors(status_code, error_type):
    async def run_test():
        client, http_client = make_client(
            lambda request: httpx.Response(status_code, json={"error": "hidden"})
        )
        try:
            with pytest.raises(error_type) as captured:
                await client.complete_json([])
            return captured
        finally:
            await http_client.aclose()

    captured = asyncio.run(run_test())

    assert "test-secret" not in str(captured.value)


def test_llm_client_maps_network_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async def run_test():
        client, http_client = make_client(handler)
        try:
            with pytest.raises(LLMConnectionError):
                await client.complete_json([])
        finally:
            await http_client.aclose()

    asyncio.run(run_test())


def test_llm_client_maps_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("invalid response", request=request)

    async def run_test():
        client, http_client = make_client(handler)
        try:
            with pytest.raises(LLMConnectionError):
                await client.complete_json([])
        finally:
            await http_client.aclose()

    asyncio.run(run_test())


def test_llm_client_rejects_missing_content():
    async def run_test():
        client, http_client = make_client(
            lambda request: httpx.Response(200, json={"choices": []})
        )
        try:
            with pytest.raises(LLMResponseError):
                await client.complete_json([])
        finally:
            await http_client.aclose()

    asyncio.run(run_test())


def test_llm_client_requires_configuration():
    with pytest.raises(AIConfigurationError):
        OpenAICompatibleLLMClient(
            api_key="",
            base_url="https://llm.example/v1",
            model_name="test-model",
        )
