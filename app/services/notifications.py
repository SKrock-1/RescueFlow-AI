"""
RescueFlow AI — Customer & Courier Notification Service.

Formats and dispatches automated notifications (WhatsApp, SMS, Email)
following autonomous exception resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NotificationMessage:
    channel: str  # "whatsapp" | "sms" | "email"
    recipient_name: str
    recipient_contact: str
    order_number: str
    message: str
    timestamp: str
    status: str = "DELIVERED"


class NotificationDispatcher:
    """Dispatches multi-channel customer and driver notifications."""

    @staticmethod
    def build_rescheduled_message(
        customer_name: str, order_number: str, new_date: str, start_time: str, end_time: str
    ) -> str:
        """Text of the reschedule message, used for both sending and approval previews."""
        return (
            f"📦 *RescueFlow Update for Order {order_number}*\n\n"
            f"Hi {customer_name}, we missed you during today's delivery attempt.\n\n"
            f"✅ We have rescheduled your delivery to:\n"
            f"📅 *Date:* {new_date}\n"
            f"⏰ *Window:* {start_time} - {end_time}\n\n"
            f"This window was chosen based on your delivery preferences. "
            f"Reply 'CHANGE' if you would prefer a different time."
        )

    @staticmethod
    def build_escalated_message(order_number: str, phone: str) -> str:
        """Text of the escalation message, used for both sending and approval previews."""
        return (
            f"RescueFlow notice: delivery for order {order_number} could not be completed "
            f"and has been passed to our logistics support team. "
            f"A representative will call you at {phone} to arrange delivery."
        )

    @staticmethod
    def notify_customer_rescheduled(
        customer_name: str,
        phone: str,
        order_number: str,
        new_date: str,
        start_time: str,
        end_time: str,
        channel: str = "whatsapp",
    ) -> NotificationMessage:
        """Send delivery rescheduled notification to customer."""
        msg_text = NotificationDispatcher.build_rescheduled_message(
            customer_name, order_number, new_date, start_time, end_time
        )

        notif = NotificationMessage(
            channel=channel,
            recipient_name=customer_name,
            recipient_contact=phone,
            order_number=order_number,
            message=msg_text,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="SENT",
        )

        logger.info("Dispatched %s notification to %s (%s)", channel.upper(), customer_name, phone)
        return notif

    @staticmethod
    def notify_customer_escalated(
        customer_name: str,
        phone: str,
        order_number: str,
        reason: str,
        channel: str = "sms",
    ) -> NotificationMessage:
        """Send incident escalation notification to customer."""
        msg_text = NotificationDispatcher.build_escalated_message(order_number, phone)

        notif = NotificationMessage(
            channel=channel,
            recipient_name=customer_name,
            recipient_contact=phone,
            order_number=order_number,
            message=msg_text,
            timestamp=datetime.now(timezone.utc).isoformat(),
            status="SENT",
        )

        logger.warning("Dispatched ESCALATION %s to %s", channel.upper(), customer_name)
        return notif
