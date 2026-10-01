import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from time import monotonic
from typing import Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from nowa.ai.adapters import FixedReplyAdapter, LLMAdapter, ProviderError
from nowa.ai.prompt import Prompt

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Attempt:
    model: str
    responded: bool
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None
    seconds: float = 0.0


@dataclass
class ChainResult(Generic[T]):
    output: T | None
    model: str
    attempts: list[Attempt] = field(default_factory=list)
    safe_mode: bool = False


async def run_structured(
    prompt: Prompt,
    schema: type[T],
    chain: Sequence[LLMAdapter],
    *,
    turn_budget_s: float = 20,
    provider_timeout_s: float = 12,
) -> ChainResult[T]:
    deadline = asyncio.get_running_loop().time() + turn_budget_s
    attempts: list[Attempt] = []
    failures = 0
    for adapter in chain:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return ChainResult(None, "budget", attempts, True)
        if isinstance(adapter, FixedReplyAdapter):
            return ChainResult(None, adapter.model, attempts, True)
        started = monotonic()
        try:
            async with asyncio.timeout(min(remaining, provider_timeout_s)):
                raw = await adapter.generate(prompt, schema, min(remaining, provider_timeout_s))
        except ProviderError as exc:
            partial = exc.response
            attempts.append(
                Attempt(
                    adapter.model,
                    partial is not None,
                    partial.input_tokens if partial else 0,
                    partial.output_tokens if partial else 0,
                    error=type(exc).__name__,
                    seconds=monotonic() - started,
                )
            )
            continue
        except (TimeoutError, httpx.HTTPError, OSError) as exc:
            attempts.append(
                Attempt(
                    adapter.model, False, error=type(exc).__name__, seconds=monotonic() - started
                )
            )
            continue
        seconds = monotonic() - started
        try:
            output = schema.model_validate_json(raw.text)
        except ValidationError as exc:
            attempts.append(
                Attempt(
                    raw.model,
                    True,
                    raw.input_tokens,
                    raw.output_tokens,
                    type(exc).__name__,
                    seconds,
                )
            )
            failures += 1
            if failures == 2:
                return ChainResult(None, raw.model, attempts, True)
            continue
        attempts.append(
            Attempt(raw.model, True, raw.input_tokens, raw.output_tokens, seconds=seconds)
        )
        return ChainResult(output, raw.model, attempts)
    return ChainResult(None, "fixed", attempts, True)
