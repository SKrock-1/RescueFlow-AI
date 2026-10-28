"""
RescueFlow AI — Deterministic Offline Mock Provider.

Used for offline demonstration, rapid local testing, and fallback when external LLM APIs are rate-limited or unavailable.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.providers.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class MockProvider(LLMProvider):
    """Deterministic mock provider that simulates multi-step delivery rescue reasoning."""

    def __init__(self) -> None:
        self.step = 0

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        self.step += 1

        # Extract context if present from messages
        last_msg = messages[-1]["content"] if messages else ""

        if self.step == 1:
            return LLMResponse(
                content="Inspecting order details and delivery failure context.",
                tool_calls=[
                    {
                        "id": f"call_{self.step}_get_order",
                        "type": "function",
                        "function": {
                            "name": "get_order",
                            "arguments": {"order_id": 1},
                        },
                    }
                ],
            )
        elif self.step == 2:
            return LLMResponse(
                content="Retrieving customer profile, VIP status, and delivery time slot preferences.",
                tool_calls=[
                    {
                        "id": f"call_{self.step}_get_profile",
                        "type": "function",
                        "function": {
                            "name": "get_customer_profile",
                            "arguments": {"customer_id": 1},
                        },
                    }
                ],
            )
        elif self.step == 3:
            return LLMResponse(
                content="Finding available delivery slots matching customer preferred time window.",
                tool_calls=[
                    {
                        "id": f"call_{self.step}_slots",
                        "type": "function",
                        "function": {
                            "name": "find_available_delivery_slots",
                            "arguments": {"customer_id": 1, "date": "2026-09-15"},
                        },
                    }
                ],
            )
        elif self.step == 4:
            return LLMResponse(
                content="Rescheduling delivery to customer preferred slot and updating courier notes.",
                tool_calls=[
                    {
                        "id": f"call_{self.step}_reschedule",
                        "type": "function",
                        "function": {
                            "name": "reschedule_delivery",
                            "arguments": {
                                "order_id": 1,
                                "date": "2026-09-15",
                                "start_time": "14:00",
                                "end_time": "17:00",
                            },
                        },
                    }
                ],
            )
        else:
            return LLMResponse(
                content="Resolution complete: Delivery rescheduled to next day afternoon window adhering to customer profile preferences. Courier notified with gate code instructions and WhatsApp update dispatched to customer.",
                tool_calls=[],
            )
