"""
RescueFlow AI — Application Configuration.

Loads all settings from environment variables / .env file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Central configuration loaded from environment variables."""

    # ── LLM Provider ──
    llm_provider: Literal["groq", "nvidia"] = Field(
        default="groq", description="Active LLM provider"
    )

    # ── Groq ──
    groq_api_key: str = Field(default="", description="Groq API key")
    groq_model: str = Field(
        default="openai/gpt-oss-20b", description="Groq model name"
    )

    # ── NVIDIA NIM ──
    nvidia_api_key: str = Field(default="", description="NVIDIA API key")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="NVIDIA NIM base URL",
    )
    nvidia_model: str = Field(
        default="meta/muse-glimmer-30b", description="NVIDIA model name"
    )

    # ── Database ──
    database_url: str = Field(
        default="sqlite:///rescueflow.db", description="SQLAlchemy database URL"
    )

    # ── Agent ──
    max_agent_steps: int = Field(
        default=10, description="Maximum iterations for the agent loop"
    )
    agent_log_level: str = Field(default="INFO", description="Logging level")

    # ── Shopify Integration ──
    shopify_store_url: str = Field(
        default="rescueflow-demo-store.myshopify.com",
        description="Shopify store domain",
    )
    shopify_access_token: str = Field(
        default="", description="Shopify Admin API access token"
    )

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
