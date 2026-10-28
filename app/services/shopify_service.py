"""
RescueFlow AI — Live Shopify E-Commerce Integration Service.

Connects RescueFlow AI directly to Shopify Admin REST API:
- Validates connection & fetches shop metadata
- Lists live orders from Shopify
- Fetches detailed customer, shipping, and line items
- Pushes autonomous resolution updates (tags, delivery notes) back to Shopify
- Creates live test orders for classroom demonstration
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from typing import Any

import os
from app.config import get_settings

logger = logging.getLogger("rescueflow.shopify")


class ShopifyService:
    """Client for interacting with Shopify Admin REST API."""

    def __init__(self, store_url: str | None = None, access_token: str | None = None):
        settings = get_settings()
        raw_url = (
            store_url
            or getattr(settings, "shopify_store_url", None)
            or os.getenv("SHOPIFY_STORE_URL", "rescueflow-demo-store.myshopify.com")
        )
        raw_token = (
            access_token
            or getattr(settings, "shopify_access_token", None)
            or os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        )
        self.store_url = str(raw_url).strip()
        self.access_token = str(raw_token).strip()
        self.api_version = "2024-01"

    @property
    def is_configured(self) -> bool:
        """Return True if both store URL and access token are provided."""
        return bool(self.store_url and self.access_token)

    def _request(
        self, endpoint: str, method: str = "GET", data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute an authenticated HTTP request to Shopify Admin API."""
        if not self.is_configured:
            return {"error": "Shopify credentials are not configured in .env"}

        url = f"https://{self.store_url}/admin/api/{self.api_version}/{endpoint}"
        headers = {
            "X-Shopify-Access-Token": self.access_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        body = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            try:
                resp_ctx = urllib.request.urlopen(req, timeout=15)
            except urllib.error.URLError as u_err:
                if "CERTIFICATE_VERIFY_FAILED" in str(u_err) or "certificate verify failed" in str(u_err):
                    logger.warning("Network proxy detected. Retrying request with unverified SSL context...")
                    ctx = ssl._create_unverified_context()
                    resp_ctx = urllib.request.urlopen(req, timeout=15, context=ctx)
                else:
                    raise u_err

            with resp_ctx as response:
                content = response.read().decode("utf-8")
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8") if e.fp else str(e)
            logger.error("Shopify API HTTPError %d: %s", e.code, error_msg)
            return {"error": f"Shopify API Error {e.code}: {error_msg}"}
        except Exception as e:
            logger.error("Shopify request failed: %s", e)
            return {"error": f"Connection failed: {str(e)}"}

    def test_connection(self) -> dict[str, Any]:
        """Verify API credentials and return shop information."""
        res = self._request("shop.json")
        if "shop" in res:
            shop = res["shop"]
            return {
                "success": True,
                "name": shop.get("name"),
                "domain": shop.get("myshopify_domain"),
                "email": shop.get("email"),
                "currency": shop.get("currency"),
                "country": shop.get("country_name"),
            }
        return {"success": False, "error": res.get("error", "Unknown error")}

    def list_orders(self, limit: int = 10, status: str = "any") -> list[dict[str, Any]]:
        """Fetch list of recent orders from the Shopify store."""
        res = self._request(f"orders.json?status={status}&limit={limit}")
        if "orders" in res:
            return res["orders"]
        return []

    def get_order(self, order_id: str | int) -> dict[str, Any]:
        """Fetch a specific order by ID."""
        return self._request(f"orders/{order_id}.json")

    def update_order_rescue_status(
        self,
        order_id: str | int,
        action: str,
        note_message: str,
        extra_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Update a live Shopify order with autonomous rescue metadata:
        - Appends 'rescueflow-rescued' and action tag to order tags
        - Appends resolution summary to order notes
        """
        # First retrieve existing tags so we don't overwrite them
        current = self.get_order(order_id)
        if "order" not in current:
            return {"error": f"Order {order_id} not found on Shopify"}

        existing_tags = current["order"].get("tags", "")
        tags_set = set(t.strip() for t in existing_tags.split(",") if t.strip())
        tags_set.add("rescueflow-rescued")
        tags_set.add(f"rf-{action.lower()}")
        if extra_tags:
            for t in extra_tags:
                tags_set.add(t.strip())

        existing_note = current["order"].get("note") or ""
        # Preserve original customer checkout note (before any [RescueFlow AI] entry)
        if "[RescueFlow AI]" in existing_note:
            base_customer_note = existing_note.split("[RescueFlow AI]")[0].strip()
        else:
            base_customer_note = existing_note.strip()

        if base_customer_note:
            new_note = f"{base_customer_note}\n\n[RescueFlow AI] {note_message.strip()}"
        else:
            new_note = f"[RescueFlow AI] {note_message.strip()}"

        payload = {
            "order": {
                "id": int(order_id),
                "tags": ", ".join(sorted(tags_set)),
                "note": new_note,
            }
        }
        return self._request(f"orders/{order_id}.json", method="PUT", data=payload)

    def create_test_order(
        self,
        customer_name: str = "Aarav Sharma",
        phone: str = "+919876543210",
        email: str = "customer@example.com",
        product_title: str = "Premium Noise-Cancelling Headphones",
        price: float = 249.99,
        address: str = "Flat 402, Green Glen Layout, Bellandur, Bengaluru",
        preferred_slot: str = "morning",
        is_vip: bool = False,
        special_notes: str = "",
        is_commercial: bool = False,
    ) -> dict[str, Any]:
        """Create a live test order in Shopify with rich customer preferences for demonstration."""
        first, *rest = customer_name.split(" ", 1)
        last = rest[0] if rest else "Customer"

        tags = ["rescueflow-monitored", f"slot-{preferred_slot.lower()}"]
        if is_vip:
            tags.append("vip-repeat-buyer")
        if is_commercial:
            tags.append("commercial-address")

        note_parts = [f"Customer Preferred Slot: {preferred_slot.title()} Window."]
        if special_notes:
            note_parts.append(special_notes)
        if is_commercial:
            note_parts.append("Office/Commercial address: Deliver during business hours only.")

        payload = {
            "order": {
                "line_items": [
                    {
                        "title": product_title,
                        "price": str(price),
                        "quantity": 1,
                    }
                ],
                "customer": {
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "phone": phone,
                    "orders_count": 5 if is_vip else 1,
                    "total_spent": "899.50" if is_vip else str(price),
                    "tags": ", ".join(tags),
                },
                "shipping_address": {
                    "first_name": first,
                    "last_name": last,
                    "address1": address,
                    "phone": phone,
                    "city": "Bengaluru",
                    "province": "Karnataka",
                    "country": "India",
                    "zip": "560103",
                    "company": "Tech Corp Bangalore" if is_commercial else "",
                },
                "financial_status": "paid",
                "tags": ", ".join(tags),
                "note": " | ".join(note_parts),
            }
        }
        res = self._request("orders.json", method="POST", data=payload)
        if "error" in res and "phone" in str(res["error"]).lower():
            # Fallback without customer phone to avoid duplicate phone errors
            logger.info("Shopify rejected phone; retrying order creation without phone...")
            payload["order"]["customer"].pop("phone", None)
            payload["order"]["shipping_address"].pop("phone", None)
            res = self._request("orders.json", method="POST", data=payload)
        return res

    def extract_shopify_customer_profile(self, order_raw: dict[str, Any]) -> dict[str, Any]:
        """
        Intelligently extracts customer profile, delivery preferences,
        VIP tier, and operational constraints from Shopify order data.
        """
        cust_data = order_raw.get("customer") or {}
        ship_data = order_raw.get("shipping_address") or {}
        tags_str = f"{cust_data.get('tags', '')}, {order_raw.get('tags', '')}".lower()
        order_note = (order_raw.get("note") or "").strip()
        cust_note = (cust_data.get("note") or "").strip()
        combined_notes = f"{order_note} {cust_note}".strip().lower()

        # 1. Determine Preferred Delivery Time Window
        preferred_time = "morning"  # default
        if any(k in tags_str or k in combined_notes for k in ["slot-evening", "evening", "night", "after 5", "after 6", "after 4", "post work", "late"]):
            preferred_time = "evening"
        elif any(k in tags_str or k in combined_notes for k in ["slot-afternoon", "afternoon", "post lunch", "12 to", "1 pm", "2 pm", "3 pm"]):
            preferred_time = "afternoon"
        elif any(k in tags_str or k in combined_notes for k in ["slot-morning", "morning", "early", "before 12", "am"]):
            preferred_time = "morning"

        # 2. Address Intelligence (Commercial / Tech Park vs Residential)
        company = ship_data.get("company") or ""
        addr1 = ship_data.get("address1") or ""
        addr2 = ship_data.get("address2") or ""
        full_address = f"{company} {addr1} {addr2}".strip()
        full_addr_lower = full_address.lower()

        is_commercial = any(
            k in full_addr_lower or k in tags_str
            for k in ["tech park", "floor", "tower", "office", "corp", "suite", "pvt ltd", "ltd", "infotech", "building", "desk", "reception", "commercial"]
        )

        # 3. Customer LTV & VIP Tier
        orders_count = int(cust_data.get("orders_count") or 1)
        try:
            total_spent = float(cust_data.get("total_spent") or 0.0)
        except (ValueError, TypeError):
            total_spent = 0.0

        is_vip = orders_count >= 3 or total_spent >= 400.0 or "vip" in tags_str

        # 4. Priority Derivation
        if is_vip or total_spent >= 300.0 or "urgent" in tags_str or "critical" in tags_str:
            priority = "critical" if (is_vip and total_spent >= 500.0) else "express"
        else:
            priority = "standard"

        # 5. Assemble Rich Special Instructions
        instructions: list[str] = []
        if order_note:
            instructions.append(f"Checkout Note: '{order_note}'")
        if is_commercial:
            instructions.append("Commercial Address: Must deliver during standard business hours.")
        if is_vip:
            instructions.append(f"VIP Tier: High-value buyer (${total_spent:.2f} spent across {orders_count} orders) - prioritize dedicated courier.")
        if any(k in combined_notes for k in ["call", "phone", "ring"]):
            instructions.append("Customer requested phone call prior to arrival.")
        if any(k in combined_notes for k in ["gate", "security", "guard", "buzzer"]):
            instructions.append("Gate clearance / security check-in required.")

        special_instructions = " | ".join(instructions) if instructions else "Standard delivery handling."

        return {
            "preferred_delivery_time": preferred_time,
            "is_vip": is_vip,
            "orders_count": orders_count,
            "total_spent": total_spent,
            "is_commercial": is_commercial,
            "priority": priority,
            "special_instructions": special_instructions,
            "full_address": full_address or "Online Order Address, Bengaluru, KA",
        }

    def sync_shopify_order_to_db(self, shopify_order_data: dict[str, Any]) -> int:
        """
        Import or update a Shopify order into the local RescueFlow SQLite database
        so the agent can investigate and rescue it with all available tools.
        Returns the local (order_id, incident_id).
        """
        from app.database.engine import get_db
        from app.database.models import Customer, Order, Delivery, DeliveryAttempt, Courier, Incident, AgentMemory
        from datetime import date as d_cls, time as t_cls, timedelta

        order_raw = shopify_order_data.get("order", shopify_order_data)
        shopify_id = order_raw["id"]
        order_name = order_raw.get("name", f"#{shopify_id}")
        local_order_num = f"SHP-{order_name.replace('#', '')}"

        cust_data = order_raw.get("customer") or {}
        ship_data = order_raw.get("shipping_address") or {}

        first_name = cust_data.get("first_name") or ship_data.get("first_name") or "Shopify"
        last_name = cust_data.get("last_name") or ship_data.get("last_name") or "Customer"
        full_name = f"{first_name} {last_name}".strip()
        phone = cust_data.get("phone") or ship_data.get("phone") or "+919876543210"
        email = cust_data.get("email") or "customer@example.com"

        profile_intel = self.extract_shopify_customer_profile(order_raw)

        with get_db() as db:
            # 1. Find or create customer
            customer = db.query(Customer).filter(Customer.phone == phone).first()
            if not customer:
                customer = Customer(
                    name=full_name,
                    phone=phone,
                    email=email,
                    address=profile_intel["full_address"],
                    preferred_delivery_time=profile_intel["preferred_delivery_time"],
                    preferred_contact_method="sms" if "call" not in profile_intel["special_instructions"].lower() else "call",
                    special_instructions=profile_intel["special_instructions"],
                )
                db.add(customer)
                db.flush()
            else:
                customer.preferred_delivery_time = profile_intel["preferred_delivery_time"]
                customer.special_instructions = profile_intel["special_instructions"]
                db.flush()

            # Seed Operational Memory facts from Shopify profile
            # Memory 1: Slot preference & instructions
            pref_mem = db.query(AgentMemory).filter(
                AgentMemory.customer_id == customer.id,
                AgentMemory.memory_type == "preference",
            ).first()
            if not pref_mem:
                db.add(AgentMemory(
                    customer_id=customer.id,
                    memory_type="preference",
                    content=f"Shopify Profile: Customer requested {profile_intel['preferred_delivery_time'].upper()} delivery. {profile_intel['special_instructions']}",
                    importance=0.90,
                ))

            # Memory 2: VIP Tier if applicable
            if profile_intel["is_vip"]:
                vip_mem = db.query(AgentMemory).filter(
                    AgentMemory.customer_id == customer.id,
                    AgentMemory.content.like("%VIP%"),
                ).first()
                if not vip_mem:
                    db.add(AgentMemory(
                        customer_id=customer.id,
                        memory_type="preference",
                        content=f"VIP Customer on Shopify (${profile_intel['total_spent']:.2f} spent over {profile_intel['orders_count']} orders). Assign top-rated couriers and avoid re-attempt delays.",
                        importance=0.95,
                    ))

            # Memory 3: Commercial / Office Address
            if profile_intel["is_commercial"]:
                comm_mem = db.query(AgentMemory).filter(
                    AgentMemory.customer_id == customer.id,
                    AgentMemory.content.like("%Commercial%"),
                ).first()
                if not comm_mem:
                    db.add(AgentMemory(
                        customer_id=customer.id,
                        memory_type="observation",
                        content=f"Destination is a commercial/office facility ({profile_intel['full_address']}). Deliver strictly during business hours.",
                        importance=0.88,
                    ))

            # 2. Find or create courier
            courier = db.query(Courier).first()
            courier_id = courier.id if courier else 1

            # 3. Find or create order
            order = db.query(Order).filter(Order.order_number == local_order_num).first()
            if not order:
                order = Order(
                    order_number=local_order_num,
                    customer_id=customer.id,
                    warehouse_id="WH-01",
                    package_size="medium",
                    priority=profile_intel["priority"],
                    status="FAILED",
                    expected_delivery_date=d_cls.today(),
                )
                db.add(order)
                db.flush()
            else:
                order.priority = profile_intel["priority"]
                db.flush()

            # 4. Find or create delivery
            delivery = db.query(Delivery).filter(Delivery.order_id == order.id).first()
            if not delivery:
                delivery = Delivery(
                    order_id=order.id,
                    courier_id=courier_id,
                    status="FAILED",
                    scheduled_date=d_cls.today(),
                    scheduled_start=t_cls(10, 0),
                    scheduled_end=t_cls(13, 0),
                    attempt_count=1,
                    current_location="Delivery Hub #4, Outer Ring Road",
                )
                db.add(delivery)
                db.flush()

            # 5. Create failed attempt if none
            attempt = db.query(DeliveryAttempt).filter(DeliveryAttempt.delivery_id == delivery.id).first()
            if not attempt:
                attempt = DeliveryAttempt(
                    delivery_id=delivery.id,
                    attempt_number=1,
                    reason="customer_unavailable",
                    location="Customer Address",
                    notes=f"Linked to live Shopify Order {order_name} (ID: {shopify_id})",
                )
                db.add(attempt)

            # 6. Create Incident for the agent to resolve
            incident = db.query(Incident).filter(Incident.order_id == order.id, Incident.status == "OPEN").first()
            if not incident:
                incident = Incident(
                    order_id=order.id,
                    incident_type="DELIVERY_FAILED",
                    severity="high",
                    description=f"Delivery attempt failed for live Shopify Order {order_name}: Customer unreachable at address.",
                    status="OPEN",
                )
                db.add(incident)
                db.flush()

            db.commit()
            return order.id, incident.id

    def push_resolution_to_shopify(
        self,
        local_order_number: str,
        action: str,
        summary: str,
    ) -> dict[str, Any]:
        """Check if local order is a Shopify order and update live store."""
        if not local_order_number.startswith("SHP-"):
            return {"skipped": "Not a Shopify order"}

        raw_num = local_order_number.replace("SHP-", "")
        # Find order by name in Shopify
        orders = self.list_orders(limit=20)
        matched_order = None
        for o in orders:
            if str(o.get("name", "")).replace("#", "") == raw_num or str(o.get("id")) == raw_num:
                matched_order = o
                break

        if not matched_order:
            return {"error": f"Order {local_order_number} not found on Shopify"}

        shopify_id = matched_order["id"]
        return self.update_order_rescue_status(
            order_id=shopify_id,
            action=action,
            note_message=summary,
            extra_tags=["autonomous-resolution"],
        )


# Singleton helper
_shopify_instance: ShopifyService | None = None


def get_shopify_service() -> ShopifyService:
    global _shopify_instance
    if _shopify_instance is None:
        _shopify_instance = ShopifyService()
    return _shopify_instance
