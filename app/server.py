"""
RescueFlow AI — Production Event & Webhook Server.

Ingests real-time Non-Delivery Reports (NDR) from carrier APIs and Shopify order webhooks.
Dispatches autonomous rescue pipelines asynchronously via BackgroundTasks.
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.agent.agent import AgentRunner
from app.database.engine import get_db
from app.database.models import Incident, Order
from app.providers.factory import create_provider
from app.services.shopify_service import get_shopify_service

logger = logging.getLogger("rescueflow.server")

app = FastAPI(
    title="RescueFlow AI — Enterprise Webhook Engine",
    description="Sub-second autonomous event-driven delivery exception resolution API.",
    version="1.1.0",
)


class DeliveryFailedWebhook(BaseModel):
    event: str = Field(default="delivery_failed", description="Event name")
    order_id: str | int = Field(description="Shopify or carrier order ID")
    order_name: str | None = Field(default=None, description="Order label (e.g., #1007)")
    failure_reason: str = Field(default="Customer unreachable", description="Failure reason")
    carrier: str | None = Field(default="Shiprocket", description="Carrier name")


class CustomerReplyWebhook(BaseModel):
    order_number: str = Field(description="Order number (e.g. #1007 or SHP-1007)")
    customer_phone: str = Field(description="Customer phone number")
    message: str = Field(description="Inbound customer message text")


def _run_autonomous_rescue(order_id_or_name: str | int, reason: str) -> None:
    """Background worker executing the full Plan-Act-Observe loop."""
    logger.info("Executing background rescue for order: %s (Reason: %s)", order_id_or_name, reason)
    try:
        shopify_svc = get_shopify_service()
        # Fetch fresh order from Shopify
        shopify_order = shopify_svc.get_order(order_id_or_name)
        if "order" not in shopify_order:
            orders = shopify_svc.list_orders(limit=25)
            matched = None
            clean_str = str(order_id_or_name).replace("#", "").strip()
            for o in orders:
                if str(o.get("name", "")).replace("#", "") == clean_str or str(o.get("id")) == clean_str:
                    matched = o
                    break
            if not matched:
                logger.error("Order %s not found on Shopify; background rescue halted.", order_id_or_name)
                return
            order_data = matched
        else:
            order_data = shopify_order["order"]

        # Sync to DB and get incident ID
        _, inc_id = shopify_svc.sync_shopify_order_to_db(order_data)

        # Run with resilient fallback provider
        runner = AgentRunner(provider=create_provider("auto"), max_steps=8)
        result = runner.resolve_incident(inc_id)

        # 2-way sync resolution back to Shopify
        ord_num = str(order_data.get("name", "")).replace("#", "")
        shopify_svc.push_resolution_to_shopify(
            local_order_number=f"SHP-{ord_num}",
            action=str(result.action_taken or "RESOLVED"),
            summary=result.decision_summary or "Autonomous resolution committed via webhook trigger.",
        )
        logger.info("Successfully completed autonomous rescue for order %s!", ord_num)
    except Exception as exc:
        logger.exception("Error in background rescue task: %s", exc)


@app.get("/")
def root():
    return {
        "service": "RescueFlow AI Webhook Engine",
        "status": "online",
        "supported_events": ["delivery_failed", "customer_reply"],
        "docs_url": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhooks/ndr", status_code=202)
def handle_delivery_failed(
    payload: DeliveryFailedWebhook,
    background_tasks: BackgroundTasks,
):
    """
    Ingest delivery failure webhook from carriers (Shiprocket, Delhivery, etc.)
    or Shopify order fulfillment updates.
    """
    target_ident = payload.order_name or payload.order_id
    background_tasks.add_task(
        _run_autonomous_rescue,
        order_id_or_name=target_ident,
        reason=payload.failure_reason,
    )
    return {
        "status": "accepted",
        "message": f"Autonomous rescue pipeline scheduled for order {target_ident}",
        "event": payload.event,
        "mode": "autonomous_async",
    }


@app.post("/webhooks/customer-reply", status_code=202)
def handle_customer_reply(
    payload: CustomerReplyWebhook,
    background_tasks: BackgroundTasks,
):
    """
    Ingest interactive WhatsApp / SMS replies from customers.
    """
    background_tasks.add_task(
        _run_autonomous_rescue,
        order_id_or_name=payload.order_number,
        reason=f"Customer WhatsApp Reply: {payload.message}",
    )
    return {
        "status": "accepted",
        "message": f"Customer response recorded for {payload.order_number}. Re-alignment scheduled.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.server:app", host="0.0.0.0", port=8000, reload=True)
