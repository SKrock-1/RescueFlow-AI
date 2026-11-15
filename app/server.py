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
from app.agent.engines import create_runner
from app.database.engine import get_db, init_db
from app.database.models import Incident, Order, ProcessedEvent
from app.providers.factory import create_provider
from app.services.shopify_service import get_shopify_service

logger = logging.getLogger("rescueflow.server")

app = FastAPI(
    title="RescueFlow AI — Enterprise Webhook Engine",
    description="Sub-second autonomous event-driven delivery exception resolution API.",
    version="1.1.0",
)
init_db()


class DeliveryFailedWebhook(BaseModel):
    event: str = Field(default="delivery_failed", description="Event name")
    order_id: str | int = Field(description="Shopify or carrier order ID")
    order_name: str | None = Field(default=None, description="Order label (e.g., #1007)")
    failure_reason: str = Field(default="Customer unreachable", description="Failure reason")
    carrier: str | None = Field(default="Shiprocket", description="Carrier name")
    event_id: str | None = Field(default=None, description="Carrier event ID; repeated IDs are ignored")


class CustomerReplyWebhook(BaseModel):
    order_number: str = Field(description="Order number (e.g. #1007 or SHP-1007)")
    customer_phone: str = Field(description="Customer phone number")
    message: str = Field(description="Inbound customer message text")
    event_id: str | None = Field(default=None, description="Message ID; repeated IDs are ignored")


def _run_autonomous_rescue(
    order_id_or_name: str | int,
    reason: str,
    new_failure: bool = False,
    customer_message: str | None = None,
) -> None:
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

        # Sync to DB: an NDR counts a failed attempt; a reply is passed to the agent.
        note = f'Customer replied: "{customer_message}"' if customer_message else None
        local_order_id, inc_id = shopify_svc.sync_shopify_order_to_db(
            order_data,
            failure_reason=None if customer_message else reason,
            new_failure=new_failure,
            context_note=note,
        )
        # A newer event replaces any plan still waiting for approval on this order.
        AgentRunner.supersede_open_incidents(local_order_id, keep_incident_id=inc_id)

        # Run with resilient fallback provider
        runner = create_runner(provider=create_provider("auto"), max_steps=8)
        result = runner.resolve_incident(inc_id)

        # 2-way sync resolution back to Shopify
        ord_num = str(order_data.get("name", "")).replace("#", "")
        shopify_svc.push_resolution_to_shopify(
            local_order_number=f"SHP-{ord_num}",
            action=str(result.action_taken or "none"),
            summary=result.decision_summary or "Autonomous resolution committed via webhook trigger.",
            status=result.status,
        )
        logger.info("Autonomous rescue for order %s finished with status %s.", ord_num, result.status)
    except Exception as exc:
        logger.exception("Error in background rescue task: %s", exc)


def _first_time(event_id: str | None, kind: str) -> bool:
    """Record a webhook event ID; False if it was seen before (carriers retry)."""
    if not event_id:
        return True
    from sqlalchemy.exc import IntegrityError

    try:
        with get_db() as db:
            db.add(ProcessedEvent(event_id=f"{kind}:{event_id}", kind=kind))
            db.flush()
        return True
    except IntegrityError:
        return False


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
    if not _first_time(payload.event_id, "delivery_failed"):
        return {
            "status": "duplicate",
            "message": f"Event {payload.event_id} was already received; no new rescue scheduled.",
            "event": payload.event,
        }
    background_tasks.add_task(
        _run_autonomous_rescue,
        order_id_or_name=target_ident,
        reason=payload.failure_reason,
        new_failure=True,
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
    if not _first_time(payload.event_id, "customer_reply"):
        return {
            "status": "duplicate",
            "message": f"Message {payload.event_id} was already received; nothing scheduled.",
        }
    background_tasks.add_task(
        _run_autonomous_rescue,
        order_id_or_name=payload.order_number,
        reason="customer_reply",
        customer_message=payload.message,
    )
    return {
        "status": "accepted",
        "message": f"Customer response recorded for {payload.order_number}. Re-alignment scheduled.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.server:app", host="0.0.0.0", port=8000, reload=True)
