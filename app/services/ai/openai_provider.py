"""OpenAI adapter implementing the internal LLM provider boundary."""

from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel

from app.services.ai.base import AIProviderError


LOGGER = logging.getLogger(__name__)


class OpenAIProvider:
    """Adapt the OpenAI Responses API to the vendor-neutral provider protocol."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        self._client = client or AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=1,
        )

    async def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> str:
        """Request Pydantic-backed Structured Output and return normalized JSON."""

        try:
            response = await self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=response_model,
            )
        except (OpenAIError, asyncio.TimeoutError) as error:
            LOGGER.error("OpenAI provider request failed: %s", type(error).__name__)
            raise AIProviderError("The AI provider request failed.") from error

        parsed = response.output_parsed
        if parsed is None:
            LOGGER.error("OpenAI provider returned no parsed structured output")
            raise AIProviderError("The AI provider returned no usable output.")
        return parsed.model_dump_json()
