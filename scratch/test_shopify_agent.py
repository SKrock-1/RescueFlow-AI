import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.services.shopify_service import get_shopify_service
from app.agent.agent import AgentRunner
from app.agent.observer import ConsoleProgressObserver

svc = get_shopify_service()
orders = svc.list_orders(limit=1)

if not orders:
    print("No orders found on Shopify!")
    sys.exit(0)

order_data = orders[0]
print(f"Syncing Shopify order: {order_data['name']} (ID: {order_data['id']}) to local DB...")
order_id, incident_id = svc.sync_shopify_order_to_db(order_data)
print(f"Synced successfully! Local Order ID: {order_id} | Incident ID: {incident_id}")

print("\n--- RUNNING RESCUEFLOW AI AGENT ON LIVE SHOPIFY ORDER ---")
runner = AgentRunner(observers=[ConsoleProgressObserver()], max_steps=8)
result = runner.resolve_incident(incident_id)

print("\n--- EXECUTION COMPLETED ---")
print(f"Result Status: {result.status}")
print(f"Action Taken:  {result.action_taken}")
print(f"Summary:       {result.decision_summary}")
print(f"Notifications: {len(result.notifications)} dispatched")
for n in result.notifications:
    print(f"  [{n.get('channel', 'sms').upper()}] To: {n.get('recipient_name')} ({n.get('recipient_phone')}) | Type: {n.get('notification_type')}")

# Push update back to live Shopify store
order_name = order_data.get("name", "").replace("#", "")
push_res = svc.push_resolution_to_shopify(
    local_order_number=f"SHP-{order_name}",
    action=str(result.action_taken or "RESOLVED"),
    summary=result.decision_summary or "Order rescued autonomously by RescueFlow AI"
)

if "order" in push_res:
    updated_order = push_res["order"]
    print("\n--- LIVE SHOPIFY STORE UPDATED VIA REST API ---")
    print(f"Store: {svc.store_url}")
    print(f"Order: {updated_order.get('name')} (ID: {updated_order.get('id')})")
    print(f"Tags on Shopify: {updated_order.get('tags')}")
    print(f"Note on Shopify: {updated_order.get('note')}")
else:
    print(f"Push to Shopify result: {push_res}")
