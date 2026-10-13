"""Offline tests for the OpenAI SDK adapter."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai.base import AIProviderError
from app.services.ai.models import AIEmailOutput
from app.services.ai.openai_provider import OpenAIProvider


def test_openai_provider_requests_structured_output_without_network() -> None:
    parsed = AIEmailOutput(subject="Structured subject", body="Structured body")
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=parsed))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    provider = OpenAIProvider(
        api_key="unused-test-key",
        model="test-model",
        client=client,
    )

    raw = asyncio.run(
        provider.generate(
            system_prompt="System rules",
            user_prompt="User data",
            response_model=AIEmailOutput,
        )
    )

    assert json.loads(raw) == {
        "subject": "Structured subject",
        "body": "Structured body",
    }
    parse.assert_awaited_once_with(
        model="test-model",
        input=[
            {"role": "system", "content": "System rules"},
            {"role": "user", "content": "User data"},
        ],
        text_format=AIEmailOutput,
    )


def test_openai_provider_rejects_missing_parsed_output() -> None:
    parse = AsyncMock(return_value=SimpleNamespace(output_parsed=None))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    provider = OpenAIProvider(
        api_key="unused-test-key",
        model="test-model",
        client=client,
    )

    with pytest.raises(AIProviderError, match="no usable output"):
        asyncio.run(
            provider.generate(
                system_prompt="System rules",
                user_prompt="User data",
                response_model=AIEmailOutput,
            )
        )
