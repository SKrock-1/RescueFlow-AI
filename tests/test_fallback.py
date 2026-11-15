from app.providers.base import LLMProvider, LLMResponse
from app.providers.fallback_provider import FallbackProvider
from app.providers.factory import create_provider
from app.errors import ProviderError


class Mock429Provider(LLMProvider):
    def generate(self, messages, tools=None, **kwargs):
        raise ProviderError("mock429", "Simulated RateLimit 429")


class MockSuccessProvider(LLMProvider):
    def generate(self, messages, tools=None, **kwargs):
        return LLMResponse(content="Recovered successfully")


def test_fallback_provider_recovers_from_failure():
    chain = FallbackProvider([Mock429Provider(), MockSuccessProvider()])
    res = chain.generate([{"role": "user", "content": "ping"}])
    assert res.content == "Recovered successfully"


def test_factory_creates_auto_chain():
    provider = create_provider("auto")
    assert isinstance(provider, FallbackProvider)
    assert len(provider.providers) >= 2



def test_failed_provider_cools_down_then_returns():
    calls = {"bad": 0}

    class Flaky(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            calls["bad"] += 1
            raise ProviderError("flaky", "timed out")

    now = {"t": 0.0}
    chain = FallbackProvider([Flaky(), MockSuccessProvider()], cooldown_seconds=60, clock=lambda: now["t"])
    chain.generate([{"role": "user", "content": "1"}])
    chain.generate([{"role": "user", "content": "2"}])
    assert calls["bad"] == 1          # skipped while cooling down
    now["t"] = 61
    chain.generate([{"role": "user", "content": "3"}])
    assert calls["bad"] == 2          # tried again after the cool-down
