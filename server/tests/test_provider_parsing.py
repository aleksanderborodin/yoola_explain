"""Malformed model replies must degrade (ProviderError or unverified), never
crash the request. Repro: gemma returned {"results": ["...", "..."]} — a list
of strings — for a Russian PDF, and the old dict-access 500'd the pipeline."""

import asyncio

import pytest

from yoola.config import Settings
from yoola.provider import OpenAICompatProvider, ProviderError


class StubChatProvider(OpenAICompatProvider):
    def __init__(self, reply: str):
        # The field uses a validation_alias, so the env-var name is the kwarg.
        settings = Settings(_env_file=None, YOOLA_LLM_API_KEY="stub")
        super().__init__(settings)
        self._reply = reply

    async def _chat(self, model, system, user, max_tokens):
        return self._reply


ITEMS = [("arbitration", "claim A", ["q1"]), ("refunds", "claim B", ["q2"])]


def test_verifier_tolerates_string_results():
    provider = StubChatProvider('{"results": ["supported", "not supported"]}')
    verdict = asyncio.run(provider.verify_claims(ITEMS))
    assert verdict == {"arbitration": False, "refunds": False}  # unverified, not a crash


def test_verifier_tolerates_partial_and_mixed_results():
    provider = StubChatProvider(
        '{"results": [{"key": "arbitration", "supported": true}, "garbage", {"supported": true}]}'
    )
    verdict = asyncio.run(provider.verify_claims(ITEMS))
    assert verdict == {"arbitration": True, "refunds": False}


def test_verifier_invalid_json_raises_provider_error():
    provider = StubChatProvider("{not json at all")
    with pytest.raises(ProviderError):
        asyncio.run(provider.verify_claims(ITEMS))


def test_recheck_malformed_items_raise_provider_error():
    provider = StubChatProvider('{"categories": ["just a string"]}')
    with pytest.raises(ProviderError):
        asyncio.run(provider.recheck_categories({"arbitration": "ctx"}, ()))
