"""
RescueFlow AI — Test Fixtures and Setup.
"""

from __future__ import annotations

import os

# Tests drop and re-seed the database before every test, so they must never
# touch the database the console and webhook server use. This has to be set
# before any app module creates the engine.
os.environ["DATABASE_URL"] = "sqlite:///test_rescueflow.db"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.engine import engine, init_db
from app.database.models import Base
from app.database.seed import seed_all
from app.providers.base import LLMProvider, LLMResponse


@pytest.fixture(autouse=True)
def setup_test_db():
    """Re-seed before every test.

    Incidents follow a strict lifecycle (a finished incident cannot run
    again), so each test needs its own fresh OPEN incidents.
    """
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
