import asyncio
from dataclasses import dataclass
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from nowa.ai.prompt import Prompt
from nowa.ai.schema import gemini_schema
from nowa.config import get_settings


@dataclass(frozen=True)
class RawResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    def __init__(self, response: RawResult | None = None) -> None:
        super().__init__("Provider unavailable")
        self.response = response


class NotConfigured(ProviderError):
    pass


class LLMAdapter(Protocol):
    model: str

    async def generate(
        self, prompt: Prompt, schema: type[BaseModel], timeout_s: float
    ) -> RawResult: ...


class GeminiAdapter:
    def __init__(self, model: str) -> None:
        self.model = model

    async def generate(
        self, prompt: Prompt, schema: type[BaseModel], timeout_s: float
    ) -> RawResult:
        key = get_settings().gemini_api_key
        if not key:
            raise NotConfigured()
        chunks: list[str] = []
        received = False
        input_tokens = output_tokens = 0
        try:
            async with genai.Client(api_key=key).aio as client:
                async with asyncio.timeout(timeout_s):
                    config = types.GenerateContentConfig(
                        system_instruction=prompt.system,
                        response_mime_type="application/json",
                        response_json_schema=gemini_schema(schema),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                        http_options=types.HttpOptions(
                            # Gemini requires 10 s; asyncio enforces our deadline.
                            timeout=int(max(timeout_s, 10) * 1000),
                            retry_options=types.HttpRetryOptions(attempts=1),
                        ),
                    )
                    if self.model.startswith("gemini-3"):
                        config.thinking_config = types.ThinkingConfig(
                            thinking_level=types.ThinkingLevel.LOW
                        )
                    stream = await client.models.generate_content_stream(
                        model=self.model,
                        contents=prompt.conversation,
                        config=config,
                    )
                    async for chunk in stream:
                        received = True
                        chunks.append(chunk.text or "")
                        if chunk.usage_metadata:
                            input_tokens = chunk.usage_metadata.prompt_token_count or 0
                            output_tokens = (chunk.usage_metadata.candidates_token_count or 0) + (
                                chunk.usage_metadata.thoughts_token_count or 0
                            )
        except TimeoutError as exc:
            # A cancelled stream is not a response, even after partial chunks.
            raise ProviderError() from exc
        except (errors.APIError, httpx.HTTPError, OSError) as exc:
            raw = RawResult("".join(chunks), self.model, input_tokens, output_tokens)
            raise ProviderError(raw if received else None) from exc
        return RawResult("".join(chunks), self.model, input_tokens, output_tokens)


class OpenRouterAdapter:
    def __init__(self, model: str) -> None:
        self.model = model

    async def generate(
        self, prompt: Prompt, schema: type[BaseModel], timeout_s: float
    ) -> RawResult:
        key = get_settings().openrouter_api_key
        if not key:
            raise NotConfigured()
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            try:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": prompt.system},
                            {"role": "user", "content": prompt.conversation},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": schema.__name__,
                                "strict": True,
                                "schema": schema.model_json_schema(),
                            },
                        },
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderError() from exc
            try:
                body = response.json()
                usage = body.get("usage", {})
                return RawResult(
                    body["choices"][0]["message"]["content"],
                    self.model,
                    int(usage.get("prompt_tokens", 0)),
                    int(usage.get("completion_tokens", 0)),
                )
            except (ValueError, KeyError, IndexError, TypeError):
                return RawResult("", self.model)


class FixedReplyAdapter:
    model = "fixed"

    async def generate(
        self, prompt: Prompt, schema: type[BaseModel], timeout_s: float
    ) -> RawResult:
        return RawResult(
            '{"triage":"unclear","intent":"other","fields":{"day":null,"name":null,'
            '"phone":null,"area":null,"booking_for":"unknown"},'
            '"is_health_question":false,"reply":""}',
            self.model,
        )


class FixtureAdapter:
    def __init__(
        self,
        result: str | BaseModel | Exception,
        model: str = "fixture",
        *,
        delay: float = 0,
        input_tokens: int = 100,
        output_tokens: int = 50,
    ) -> None:
        self.model = model
        self.result = result
        self.delay = delay
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.prompts: list[Prompt] = []

    async def generate(
        self, prompt: Prompt, schema: type[BaseModel], timeout_s: float
    ) -> RawResult:
        self.prompts.append(prompt)
        await asyncio.sleep(self.delay)
        if isinstance(self.result, Exception):
            raise self.result
        text = self.result if isinstance(self.result, str) else self.result.model_dump_json()
        return RawResult(text, self.model, self.input_tokens, self.output_tokens)


def default_chain() -> list[LLMAdapter]:
    chain: list[LLMAdapter] = []
    for entry in get_settings().ai_chain.split(","):
        provider, model = entry.strip().split(":", 1)
        chain.append(
            GeminiAdapter(model.strip())
            if provider == "gemini"
            else OpenRouterAdapter(model.strip())
        )
    chain.append(FixedReplyAdapter())
    return chain
