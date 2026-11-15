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


def test_rate_limits_cool_down_for_less_time():
    class RateLimited(LLMProvider):
        def generate(self, messages, tools=None, **kwargs):
            raise ProviderError("groq", "Error code: 429 rate limit")

    now = {"t": 0.0}
    chain = FallbackProvider([RateLimited(), MockSuccessProvider()], cooldown_seconds=120, clock=lambda: now["t"])
    chain.generate([{"role": "user", "content": "1"}])
    assert chain._is_cooling(0)
    now["t"] = 31
    assert not chain._is_cooling(0)


def test_chain_reports_which_provider_answered():
    class NamedModel(LLMProvider):
        model = "openai/gpt-oss-20b"

        def generate(self, messages, tools=None, **kwargs):
            return LLMResponse(content="ok")

    chain = FallbackProvider([Mock429Provider(), NamedModel(), MockSuccessProvider()])
    chain.generate([{"role": "user", "content": "ping"}])
    assert chain.last_answered_by == "openai/gpt-oss-20b"

    offline = FallbackProvider([Mock429Provider(), MockSuccessProvider()])
    offline.generate([{"role": "user", "content": "ping"}])
    assert offline.last_answered_by == "offline rules"


def test_groq_retry_after_parsing():
    from app.providers.groq_provider import retry_after_seconds

    assert retry_after_seconds("Error code: 429 - Please try again in 1.43s.") == 1.43
    assert retry_after_seconds("429 rate limit: try again in 850ms") == 0.85
    assert retry_after_seconds("Error code: 500") is None
