from unittest.mock import MagicMock
from fastapi import BackgroundTasks
from app.server import root, health, handle_delivery_failed, handle_customer_reply, DeliveryFailedWebhook, CustomerReplyWebhook


def test_root_and_health():
    h = health()
    assert h == {"status": "ok"}

    r = root()
    assert r["service"] == "RescueFlow AI Webhook Engine"
    assert "delivery_failed" in r["supported_events"]


def test_delivery_failed_webhook_handler():
    bg = MagicMock(spec=BackgroundTasks)
    payload = DeliveryFailedWebhook(
        event="delivery_failed",
        order_id="1007",
        order_name="#1007",
        failure_reason="Customer unreachable at reception",
        carrier="Delhivery",
    )
    res = handle_delivery_failed(payload, bg)
    assert res["status"] == "accepted"
    assert res["mode"] == "autonomous_async"
    assert bg.add_task.called


def test_customer_reply_webhook_handler():
    bg = MagicMock(spec=BackgroundTasks)
    payload = CustomerReplyWebhook(
        order_number="#1007",
        customer_phone="+919876543210",
        message="Please deliver tomorrow afternoon",
    )
    res = handle_customer_reply(payload, bg)
    assert res["status"] == "accepted"
    assert bg.add_task.called
