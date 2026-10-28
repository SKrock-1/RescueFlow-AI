import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.services.shopify_service import get_shopify_service
from app.agent.agent import AgentRunner
from app.agent.observer import ConsoleProgressObserver

svc = get_shopify_service()

import random
rand_id = random.randint(1000, 9999)
print("1. Creating a live test order on Shopify with AFTERNOON preference & VIP tier...")
created = svc.create_test_order(
    customer_name="Rohan Mehra",
    phone=f"+9198765{rand_id}",
    email=f"rohan.mehra{rand_id}@example.com",
    product_title="Bose QuietComfort 45 Headphones",
    price=329.00,
    address="Tower 4, Bagmane Tech Park, CV Raman Nagar, Bengaluru",
    preferred_slot="afternoon",
    is_vip=True,
    special_notes="Call 10 mins before arrival. Deliver at Reception.",
    is_commercial=True,
)

if "order" not in created:
    print("Failed to create test order:", created)
    sys.exit(1)

order_raw = created["order"]
print(f"Created Shopify Order: {order_raw['name']} (ID: {order_raw['id']})")
print(f"Shopify Tags: {order_raw.get('tags')}")
print(f"Shopify Note: {order_raw.get('note')}")

print("\n2. Syncing Shopify Order into RescueFlow AI with Profile Intelligence...")
order_id, incident_id = svc.sync_shopify_order_to_db(order_raw)
print(f"Synced successfully! Local Order ID: {order_id} | Incident ID: {incident_id}")

print("\n3. Running RescueFlow AI Agent on this Order...")
runner = AgentRunner(observers=[ConsoleProgressObserver()], max_steps=8)
result = runner.resolve_incident(incident_id)

print("\n4. Agent Resolution Results:")
print(f"Status:       {result.status}")
print(f"Action Taken: {result.action_taken}")
print(f"Summary:      {result.decision_summary}")

print("\n5. Pushing Resolution back to Shopify Store...")
clean_num = order_raw["name"].replace("#", "")
push_res = svc.push_resolution_to_shopify(
    local_order_number=f"SHP-{clean_num}",
    action=str(result.action_taken or "RESOLVED"),
    summary=result.decision_summary or "Rescued autonomously",
)

if "order" in push_res:
    up_o = push_res["order"]
    print(f"Updated Shopify Tags: {up_o.get('tags')}")
    print(f"Updated Shopify Note:\n{up_o.get('note')}")
else:
    print("Push error:", push_res)
