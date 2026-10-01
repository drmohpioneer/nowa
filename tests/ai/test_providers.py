import asyncio
from types import SimpleNamespace

import httpx
import pytest

from nowa.ai import adapters
from nowa.ai.adapters import GeminiAdapter, NotConfigured, OpenRouterAdapter, ProviderError
from nowa.ai.schema import TurnOutput
from tests.ai.support import output
from tests.ai.test_units import PROMPT


def test_missing_keys():
    for adapter in (
        GeminiAdapter("gemini-3.8-flash"),
        OpenRouterAdapter("anthropic/claude-haiku-4.5"),
    ):
        with pytest.raises(NotConfigured):
            asyncio.run(adapter.generate(PROMPT, TurnOutput, 8))


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_openrouter_errors(monkeypatch, status):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fictional-key")
    original = httpx.AsyncClient

    def handle(request):
        assert request.headers["Authorization"] == "Bearer fictional-key"
        return httpx.Response(status, json={"error": "fixture"})

    monkeypatch.setattr(
        adapters.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    with pytest.raises(ProviderError) as error:
        asyncio.run(OpenRouterAdapter("haiku").generate(PROMPT, TurnOutput, 8))
    assert error.value.response is None


def test_openrouter_structured_body_and_usage(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fictional-key")
    original = httpx.AsyncClient

    def handle(request):
        import json

        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "tools" not in body
        assert body["messages"][0]["content"] == PROMPT.system
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": output().model_dump_json()}}],
                "usage": {"prompt_tokens": 42, "completion_tokens": 8},
            },
        )

    monkeypatch.setattr(
        adapters.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    result = asyncio.run(OpenRouterAdapter("haiku").generate(PROMPT, TurnOutput, 8))
    assert result.input_tokens == 42 and result.output_tokens == 8
    assert TurnOutput.model_validate_json(result.text) == output()


def test_gemini_streaming_config_and_complete_result(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fictional-key")

    class Client:
        aio = None

        def __init__(self, **kwargs):
            self.aio = self
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def generate_content_stream(self, **kwargs):
            config = kwargs["config"]
            assert config.thinking_config.thinking_level.value == "LOW"
            assert config.response_json_schema["propertyOrdering"][0] == "triage"
            assert not config.tools and config.automatic_function_calling.disable
            assert config.http_options.retry_options.attempts == 1

            async def chunks():
                text = output().model_dump_json()
                for half in (text[:20], text[20:]):
                    yield SimpleNamespace(
                        text=half,
                        usage_metadata=SimpleNamespace(
                            prompt_token_count=10, candidates_token_count=20, thoughts_token_count=5
                        ),
                    )

            return chunks()

    monkeypatch.setattr(adapters.genai, "Client", Client)
    result = asyncio.run(GeminiAdapter("gemini-3.8-flash").generate(PROMPT, TurnOutput, 8))
    assert TurnOutput.model_validate_json(result.text) == output()
    assert result.input_tokens == 10 and result.output_tokens == 25
