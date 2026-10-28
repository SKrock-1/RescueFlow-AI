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

