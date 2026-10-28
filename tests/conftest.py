"""
RescueFlow AI — Test Fixtures and Setup.
"""

from __future__ import annotations

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.engine import engine, init_db
from app.database.models import Base
from app.database.seed import seed_all
from app.providers.base import LLMProvider, LLMResponse


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Ensure database is initialized and seeded before running tests."""
    seed_all()
    yield


class MockLLM(LLMProvider):
    """Configurable mock LLM provider for unit and integration testing."""

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self.responses = responses or []
        self.call_index = 0
        self.recorded_calls: list[dict] = []

    def generate(self, messages, tools=None, **kwargs) -> LLMResponse:
        self.recorded_calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        if self.call_index < len(self.responses):
            resp = self.responses[self.call_index]
            self.call_index += 1
            return resp
        return LLMResponse(content="Default mock decision: Task completed successfully.")
