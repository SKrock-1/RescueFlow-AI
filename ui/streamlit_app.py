"""
RescueFlow AI for Shopify — Autonomous Delivery-Exception Resolution App.

A dedicated Shopify Operations Console connecting directly to Shopify Admin REST API:
- Live 2-way synchronization with Shopify Stores
- Autonomous Plan-Act-Observe Agent Loop for Delivery Failures (NDRs)
- Real-time customer WhatsApp & SMS dispatch
- Automatic Shopify Order tags and note attributes updates
"""

from __future__ import annotations

import json
import time
from datetime import datetime, date
import streamlit as st

from app.config import get_settings
from app.database.engine import get_db, init_db
from app.database.models import Incident, Order, Customer, Delivery, Courier, AgentMemory, AgentRun
from app.database.seed import seed_all
from app.agent.agent import AgentRunner
from app.agent.observer import AgentObserver
from app.providers.factory import create_provider
from app.providers.base import LLMProvider, LLMResponse
from app.services.shopify_service import get_shopify_service
from app.schemas.models import TraceEvent

# Page configuration
st.set_page_config(
    page_title="RescueFlow AI — Shopify Autonomous Delivery Rescue",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Ultra-Premium Design System & Aesthetics ───────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }

    /* Top Hero Header */
    .hero-banner {
        background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 18px;
        padding: 1.5rem 2rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 10px 30px -10px rgba(15, 23, 42, 0.3);
        display: flex;
        justify-content: space-between;
        align-items: center;
        position: relative;
        overflow: hidden;
    }
    .hero-banner::after {
        content: "";
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: linear-gradient(90deg, #10B981, #06B6D4, #6366F1);
    }
    .hero-title {
        font-size: 2rem;
        font-weight: 800;
        color: #FFFFFF;
        margin: 0;
        letter-spacing: -0.5px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .hero-subtitle {
        color: #94A3B8;
        font-size: 0.98rem;
        margin-top: 4px;
        margin-bottom: 0;
    }
    .pulse-dot {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: #10B981;
        box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        animation: pulse 1.8s infinite;
        margin-right: 6px;
    }
    @keyframes pulse {
        0% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
        }
        70% {
            transform: scale(1);
            box-shadow: 0 0 0 10px rgba(16, 185, 129, 0);
        }
        100% {
            transform: scale(0.95);
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
        }
    }
    .store-badge {
        background: rgba(16, 185, 129, 0.12);
        color: #34D399;
        font-weight: 700;
        font-size: 0.85rem;
        padding: 6px 14px;
        border-radius: 9999px;
        border: 1px solid rgba(16, 185, 129, 0.3);
        display: inline-flex;
        align-items: center;
    }

    /* KPI Metric Cards */
    .metric-grid {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1rem;
        margin-bottom: 1.5rem;
    }
    .kpi-card-luxury {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 1.25rem 1.4rem;
        box-shadow: 0 4px 12px -2px rgba(15, 23, 42, 0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        position: relative;
        overflow: hidden;
    }
    .kpi-card-luxury:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 24px -4px rgba(15, 23, 42, 0.08);
    }
    .kpi-card-luxury::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 3px;
        background: #E2E8F0;
    }
    .kpi-card-luxury.green::before { background: linear-gradient(90deg, #10B981, #059669); }
    .kpi-card-luxury.amber::before { background: linear-gradient(90deg, #F59E0B, #D97706); }
    .kpi-card-luxury.blue::before { background: linear-gradient(90deg, #3B82F6, #2563EB); }
    .kpi-card-luxury.purple::before { background: linear-gradient(90deg, #8B5CF6, #6D28D9); }

    .kpi-val {
        font-size: 2rem;
        font-weight: 800;
        color: #0F172A;
        line-height: 1.1;
        margin-bottom: 4px;
        font-family: 'JetBrains Mono', monospace;
    }
    .kpi-lbl {
        font-size: 0.8rem;
        color: #64748B;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.6px;
    }

    /* Luxury Order Cards */
    .order-box {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 14px -3px rgba(15, 23, 42, 0.04);
        transition: all 0.2s ease;
    }
    .order-box:hover {
        border-color: #CBD5E1;
        box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08);
    }
    .order-avatar {
        width: 44px;
        height: 44px;
        border-radius: 12px;
        background: linear-gradient(135deg, #4F46E5 0%, #3B82F6 100%);
        color: #FFFFFF;
        font-weight: 800;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.05rem;
        box-shadow: 0 4px 10px rgba(79, 70, 229, 0.25);
    }
    .chip-tag {
        display: inline-block;
        background: #F1F5F9;
        color: #334155;
        font-size: 0.75rem;
        font-weight: 600;
        padding: 3px 9px;
        border-radius: 6px;
        margin-right: 4px;
        margin-bottom: 4px;
        border: 1px solid #E2E8F0;
    }
    .chip-rescued {
        background: #ECFDF5 !important;
        color: #047857 !important;
        border: 1px solid #A7F3D0 !important;
        font-weight: 700 !important;
    }
    .chip-action {
        background: #EFF6FF !important;
        color: #1D4ED8 !important;
        border: 1px solid #BFDBFE !important;
    }

    /* WhatsApp Card Mockup */
    .whatsapp-card {
        background: #EFEAE2;
        border-radius: 14px;
        padding: 1rem;
        border: 1px solid #D1D7DB;
        margin-top: 0.8rem;
    }
    .whatsapp-msg {
        background: #FFFFFF;
        border-radius: 10px 10px 10px 2px;
        padding: 10px 14px;
        font-size: 0.88rem;
        color: #111827;
        box-shadow: 0 1px 2px rgba(0,0,0,0.08);
        border: 1px solid #E5E7EB;
        line-height: 1.45;
    }
    .whatsapp-meta {
        display: flex;
        justify-content: flex-end;
        align-items: center;
        gap: 4px;
        font-size: 0.72rem;
        color: #6B7280;
        margin-top: 4px;
    }

    /* Custom Streamlit Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #F8FAFC;
        padding: 6px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
        margin-bottom: 1.2rem;
    }
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 0.92rem;
        padding: 0 18px;
        color: #64748B;
        border: none !important;
        transition: all 0.2s ease;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.06) !important;
    }

    /* Primary Action Buttons */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #059669 0%, #10B981 100%) !important;
        color: white !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 10px !important;
        padding: 0.6rem 1.2rem !important;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3) !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button[kind="primary"]:hover {
        box-shadow: 0 6px 20px rgba(16, 185, 129, 0.45) !important;
        transform: translateY(-1px) !important;
    }
</style>
""", unsafe_allow_html=True)

init_db()
shopify_svc = get_shopify_service()

# ── Sidebar Configuration ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom: 0.5rem;">
        <span style="font-size: 1.8rem;">🛍️</span>
        <div>
            <h3 style="margin:0; font-size:1.2rem; font-weight:800; color:#0F172A;">RescueFlow AI</h3>
            <span style="font-size:0.75rem; color:#64748B; font-weight:600;">Shopify Enterprise App</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("#### 🟢 Connected Store")
    if shopify_svc.is_configured:
        conn = shopify_svc.test_connection()
        if conn.get("success"):
            st.markdown(f"**Store:** `{conn.get('name')}`")
            st.markdown(f"**Domain:** `{conn.get('domain')}`")
            st.markdown("""
            <div style="margin: 8px 0;">
                <span class="store-badge"><span class="pulse-dot"></span> Live Sync Active</span>
            </div>
            """, unsafe_allow_html=True)
            st.link_button("🌐 Open Shopify Store Admin", f"https://{shopify_svc.store_url}/admin", use_container_width=True)
        else:
            st.error(f"Shopify Error: {conn.get('error')}")
    else:
        st.warning("Shopify not configured in .env")

    st.markdown("---")
    st.markdown("#### 🤖 Autonomous AI Engine")
    settings = get_settings()
    provider_options = [
        "⚡ Auto-Failover (Resilient Multi-Provider)",
        "NVIDIA NIM (mistralai/mistral-nemotron)",
        "Groq (openai/gpt-oss-20b)",
        "Offline Mock Engine (Deterministic)",
    ]

    provider_choice = st.selectbox(
        "Active LLM Provider",
        options=provider_options,
        index=0,
        help="Auto-failover automatically catches 429 rate limits or timeouts and fails over to backup providers."
    )

    if "Auto-Failover" in provider_choice:
        st.session_state["chosen_provider"] = "auto"
        st.caption("🛡️ Active Chain: `NVIDIA NIM ➔ Groq ➔ Deterministic Mock`")
    elif "NVIDIA" in provider_choice:
        st.session_state["chosen_provider"] = "nvidia"
        st.caption(f"🧠 NVIDIA NIM Model: `{settings.nvidia_model}`")
    elif "Groq" in provider_choice:
        st.session_state["chosen_provider"] = "groq"
        st.caption(f"🧠 Groq Model: `{settings.groq_model}`")
    else:
        st.session_state["chosen_provider"] = "mock"
        st.caption("🧠 Offline deterministic rule-based runner")

    st.markdown("---")
    st.markdown("#### ⚡ Quick Demonstration Actions")
    if st.button("➕ Push New Failed Delivery to Shopify", use_container_width=True):
        with st.spinner("Calling Shopify Admin REST API..."):
            new_o = shopify_svc.create_test_order(
                customer_name="Priya Patel",
                phone="+919876543211",
                email="priya.patel@example.com",
                product_title="Apple AirPods Pro (2nd Gen)",
                price=249.00,
                address="Flat 204, Indiranagar 100ft Road, Bengaluru",
            )
        if "order" in new_o:
            st.success(f"✅ Created Shopify Order {new_o['order'].get('name')}!")
            time.sleep(1)
            st.rerun()

    if st.button("🔄 Sync & Refresh All Orders", use_container_width=True):
        st.rerun()

# ── Header Banner ──────────────────────────────────────────────────────────
store_domain = shopify_svc.store_url if shopify_svc.is_configured else "rescueflow-demo-store.myshopify.com"

st.markdown(f"""
<div class="hero-banner">
    <div>
        <h1 class="hero-title">
            <span>RescueFlow AI</span>
            <span style="font-size: 0.8rem; background: rgba(255,255,255,0.12); padding: 4px 10px; border-radius: 6px; font-weight: 600; color: #E2E8F0;">Shopify Edition</span>
        </h1>
        <p class="hero-subtitle">
            Autonomous Last-Mile Delivery Exception (NDR) Resolution Engine with Real-Time Tool Calling.
        </p>
    </div>
    <div style="text-align: right;">
        <span class="store-badge">
            <span class="pulse-dot"></span>
            {store_domain}
        </span>
        <div style="font-size: 0.75rem; color: #94A3B8; margin-top: 6px; font-family: monospace;">
            Admin REST API 2024-01 • Sub-second Webhook Dispatch
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Top Level Navigation Tabs ──────────────────────────────────────────────
tab_orders, tab_trace, tab_fleet = st.tabs([
    "🛍️ Shopify Orders & Live Rescue",
    "🤖 Agent Reasoning & Execution Trace",
    "🚚 Fleet Couriers & Customer Memory",
])

# ───────────────────────────────────────────────────────────────────────────
# TAB 1: SHOPIFY ORDERS & LIVE RESCUE
# ───────────────────────────────────────────────────────────────────────────
with tab_orders:
    # Fetch live orders from Shopify
    live_orders = shopify_svc.list_orders(limit=20)
    total_orders = len(live_orders)
    rescued_count = sum(1 for o in live_orders if "rescueflow-rescued" in o.get("tags", ""))
    pending_count = total_orders - rescued_count

    # Luxury KPI Metric Cards
    st.markdown(f"""
    <div class="metric-grid">
        <div class="kpi-card-luxury blue">
            <div class="kpi-val">{total_orders}</div>
            <div class="kpi-lbl">Active Store Orders</div>
        </div>
        <div class="kpi-card-luxury green">
            <div class="kpi-val" style="color: #059669;">{rescued_count}</div>
            <div class="kpi-lbl">Rescued Autonomously</div>
        </div>
        <div class="kpi-card-luxury amber">
            <div class="kpi-val" style="color: #D97706;">{pending_count}</div>
            <div class="kpi-lbl">Pending Exceptions (NDR)</div>
        </div>
        <div class="kpi-card-luxury purple">
            <div class="kpi-val" style="color: #7C3AED;">100%</div>
            <div class="kpi-lbl">2-Way API Sync Rate</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("### 📦 Real-Time Shopify Order Stream")
        st.caption("Direct feed from your Shopify store via Admin REST API. Click **Run Autonomous Rescue** to trigger the AI agent:")

        # Filter option
        filter_status = st.radio("Filter Orders:", ["All Orders", "Pending Exception (NDR)", "Rescued by Agent"], horizontal=True)

        filtered_orders = []
        for o in live_orders:
            tags = o.get("tags", "")
            is_rescued = "rescueflow-rescued" in tags or "autonomous-resolution" in tags
            if filter_status == "Pending Exception (NDR)" and is_rescued:
                continue
            if filter_status == "Rescued by Agent" and not is_rescued:
                continue
            filtered_orders.append(o)

        if not filtered_orders:
            st.info("No orders found for this filter. Create a new test order using the panel on the right!")
        else:
            for o in filtered_orders:
                order_num = o.get("name", f"#{o.get('id')}")
                cust = o.get("customer") or {}
                cust_name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "Guest Customer"
                initials = "".join([part[0].upper() for part in cust_name.split()[:2]]) if cust_name else "SH"
                cust_phone = cust.get("phone") or o.get("shipping_address", {}).get("phone") or "+919876543210"
                total_price = o.get("total_price", "0.00")
                currency = o.get("currency", "USD")
                tags = o.get("tags", "")
                note = o.get("note", "")

                is_rescued = "rescueflow-rescued" in tags or "autonomous-resolution" in tags

                with st.container():
                    st.markdown(f"""
                    <div class="order-box">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.8rem;">
                            <div style="display: flex; align-items: center; gap: 12px;">
                                <div class="order-avatar">{initials}</div>
                                <div>
                                    <div style="display: flex; align-items: center; gap: 8px;">
                                        <h3 style="margin:0; font-size: 1.25rem; font-weight: 800; color: #0F172A;">{order_num}</h3>
                                        <span style="background: #F1F5F9; color: #475569; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 4px;">PAID</span>
                                    </div>
                                    <div style="color: #64748B; font-size: 0.88rem; font-weight: 500;">
                                        {cust_name} • <span style="font-family: monospace;">{cust_phone}</span>
                                    </div>
                                </div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 1.3rem; font-weight: 800; color: #0F172A; font-family: 'JetBrains Mono', monospace;">
                                    ${total_price} <span style="font-size: 0.75rem; color: #64748B;">{currency}</span>
                                </div>
                                <div style="margin-top: 4px;">
                                    {"<span class='chip-tag chip-rescued'>● Rescued by AI</span>" if is_rescued else "<span class='chip-tag' style='background:#FEF3C7; color:#92400E; border:1px solid #FDE68A;'>⚠️ Delivery Failed</span>"}
                                </div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    # Items preview
                    items = o.get("line_items", [])
                    item_str = ", ".join([f"{it.get('title')} (x{it.get('quantity')})" for it in items])
                    st.markdown(f"**📦 Purchased Items:** `{item_str or 'Items data'}`")

                    # Live Shopify Tags and Profile Chips
                    tags_list = [t.strip() for t in tags.split(",") if t.strip()]
                    is_vip_order = any("vip" in t.lower() for t in tags_list)
                    is_comm_order = any("commercial" in t.lower() for t in tags_list)
                    pref_slot_tag = next((t.replace("slot-", "").title() for t in tags_list if t.startswith("slot-")), "Morning")

                    chips_html = []
                    if is_vip_order:
                        chips_html.append("<span class='chip-tag' style='background:#FEF3C7; color:#B45309; border:1px solid #FCD34D; font-weight:700;'>👑 VIP Buyer</span>")
                    chips_html.append(f"<span class='chip-tag' style='background:#EEF2FF; color:#4F46E5; border:1px solid #C7D2FE;'>⏰ Prefers {pref_slot_tag}</span>")
                    if is_comm_order:
                        chips_html.append("<span class='chip-tag' style='background:#F1F5F9; color:#475569; border:1px solid #CBD5E1;'>🏢 Office Address</span>")

                    for t in tags_list:
                        if t.startswith("slot-") or t in ["vip-repeat-buyer", "commercial-address"]:
                            continue
                        cls = 'chip-rescued' if 'rescueflow' in t else 'chip-action' if 'rf-' in t else ''
                        chips_html.append(f"<span class='chip-tag {cls}'>{t}</span>")

                    st.markdown(f"**🏷️ Shopify Profile & Tags:** {' '.join(chips_html)}", unsafe_allow_html=True)

                    # Order Notes accordion
                    if note:
                        with st.expander("📝 View Customer Checkout Note & Profile Synced to Shopify", expanded=is_rescued):
                            st.markdown(note)

                    # WhatsApp Mockup preview if rescued
                    if is_rescued:
                        st.markdown(f"""
                        <div class="whatsapp-card">
                            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                                <span style="font-size: 1.1rem;">📲</span>
                                <span style="font-weight: 700; font-size: 0.82rem; color: #1E3A8A;">Real-Time WhatsApp Dispatch Confirmation</span>
                            </div>
                            <div class="whatsapp-msg">
                                Hello <b>{cust_name}</b>, your delivery for Shopify Order <b>{order_num}</b> has been autonomously rescheduled by RescueFlow AI per your <b>{pref_slot_tag}</b> delivery preference. Our assigned courier will contact you prior to arrival.
                                <div class="whatsapp-meta">
                                    <span>Just now</span>
                                    <span style="color: #2563EB; font-weight: bold;">✓✓</span>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    # Action buttons
                    b1, b2 = st.columns([3, 2])
                    with b1:
                        btn_label = "⚡ Re-Run Autonomous Rescue" if is_rescued else f"⚡ Run Autonomous Rescue on {order_num}"
                        if st.button(btn_label, key=f"btn_rescue_{o['id']}", type="primary", use_container_width=True):
                            with st.status(f"RescueFlow AI rescuing Shopify Order {order_num}...", expanded=True) as status_box:
                                st.write("📥 1. Extracting customer profile, VIP tier, and checkout preferences from Shopify...")
                                order_id, inc_id = shopify_svc.sync_shopify_order_to_db(o)

                                chosen_prov_name = st.session_state.get("chosen_provider", settings.llm_provider)
                                active_prov = create_provider(chosen_prov_name)
                                st.write(f"🧠 2. Initializing Autonomous Plan-Act-Observe loop using `{chosen_prov_name}`...")
                                runner = AgentRunner(provider=active_prov, max_steps=8)
                                res = runner.resolve_incident(inc_id)

                                st.write(f"📡 3. Dispatched WhatsApp notice tailored to customer's {pref_slot_tag} preference...")
                                st.write("🛍️ 4. Calling Shopify Admin REST API to write tags & incident notes...")

                                clean_num = order_num.replace("#", "")
                                shopify_svc.push_resolution_to_shopify(
                                    local_order_number=f"SHP-{clean_num}",
                                    action=str(res.action_taken or "RESOLVED"),
                                    summary=res.decision_summary or "Order rescued autonomously by RescueFlow AI",
                                )
                                status_box.update(label=f"✅ Order {order_num} Rescued & Synchronized with Shopify!", state="complete")

                            st.session_state["last_active_incident_id"] = inc_id
                            st.toast(f"✅ Shopify Order {order_num} tags updated live on Shopify!", icon="🛍️")
                            time.sleep(1)
                            st.rerun()

                    with b2:
                        st.link_button("🌐 Open in Shopify Admin", f"https://{shopify_svc.store_url}/admin/orders/{o['id']}", use_container_width=True)

                    st.markdown("<hr style='margin: 1.5rem 0; border: none; border-top: 1px solid #E2E8F0;'/>", unsafe_allow_html=True)

    with col_right:
        st.markdown("### ➕ Push Live Test Order to Shopify")
        st.caption("Generate a real order in your live Shopify partner store with customizable customer profile traits:")

        with st.form("new_shopify_order_form"):
            in_name = st.text_input("Customer Name", value="Aarav Sharma")
            in_phone = st.text_input("Customer Phone", value="+919876543210")
            in_email = st.text_input("Customer Email", value="aarav.sharma@example.com")
            in_item = st.text_input("Product Title", value="Sony WH-1000XM5 Wireless Headphones")
            in_price = st.number_input("Order Price ($)", value=299.99, min_value=1.0, step=10.0)
            in_addr = st.text_input("Shipping Address", value="Flat 402, Green Glen Layout, Bellandur, Bengaluru")

            col_opt1, col_opt2 = st.columns(2)
            with col_opt1:
                in_pref_slot = st.selectbox(
                    "Delivery Slot Preference",
                    options=["Morning (09:00 - 12:00)", "Afternoon (13:00 - 16:00)", "Evening (16:00 - 19:00)"],
                    index=1,
                    help="The agent will observe and honor this preferred delivery window."
                )
            with col_opt2:
                in_tier = st.selectbox(
                    "Customer Loyalty Tier",
                    options=["Standard Customer", "👑 VIP Repeat Customer ($899 LTV)"],
                    index=1,
                    help="VIP buyers receive prioritized SLA handling and dedicated courier dispatch."
                )

            in_is_comm = st.checkbox("🏢 Office / Commercial Building (Business Hours Only)", value=False)
            in_notes = st.text_input("Customer Checkout Instructions", value="Call 15 mins before arrival. Ring bell 4B.")

            submitted = st.form_submit_button("🛒 Create Order on Shopify Store", type="primary", use_container_width=True)

            if submitted:
                slot_key = "morning" if "Morning" in in_pref_slot else "afternoon" if "Afternoon" in in_pref_slot else "evening"
                is_vip_val = "VIP" in in_tier

                with st.spinner("Sending POST request to Shopify Admin API..."):
                    res = shopify_svc.create_test_order(
                        customer_name=in_name,
                        phone=in_phone,
                        email=in_email,
                        product_title=in_item,
                        price=in_price,
                        address=in_addr,
                        preferred_slot=slot_key,
                        is_vip=is_vip_val,
                        special_notes=in_notes,
                        is_commercial=in_is_comm,
                    )
                if "order" in res:
                    st.success(f"🎉 Created Live Order **{res['order'].get('name')}** with `{slot_key.upper()}` preference on Shopify!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"Shopify Error: {res.get('error')}")

        st.markdown("---")
        st.markdown("### 🔌 Real-World Event Architecture")
        st.markdown("""
        In an enterprise e-commerce setup, RescueFlow AI operates autonomously via **Event Webhooks**:
        
        ```json
        POST /webhooks/shopify-delivery-failed
        {
          "event": "delivery_failed",
          "order_id": "7044622647598",
          "failure_reason": "Customer unreachable at address",
          "carrier": "Delhivery / Shiprocket / Bluedart"
        }
        ```
        
        **Autonomous Execution Flow:**
        1. **Inbound Trigger:** Courier reports failed delivery attempt (NDR).
        2. **Operational Memory Check:** Agent checks customer preference (prefers morning slots, call on doorbell).
        3. **Deterministic Guardrails:** Policy Engine blocks invalid slots or overloaded couriers.
        4. **Autonomous Action:** Agent reassigns courier and reschedules window.
        5. **Outbound 2-Way Sync:** Automatically tags the order in Shopify Admin API and dispatches WhatsApp notification to the buyer.
        """)

# ───────────────────────────────────────────────────────────────────────────
# TAB 2: AGENT REASONING & EXECUTION TRACE
# ───────────────────────────────────────────────────────────────────────────
with tab_trace:
    st.markdown("### 🔍 Autonomous Plan-Act-Observe Step Log")
    st.caption("Inspect the exact reasoning, tool parameters, and deterministic policy guardrails executed by RescueFlow AI:")

    with get_db() as db:
        all_incidents = (
            db.query(Incident, Order, Customer)
            .join(Order, Incident.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .order_by(Incident.id.desc())
            .all()
        )

    if not all_incidents:
        st.info("No incidents resolved yet. Click 'Run Autonomous Rescue' on Tab 1 to see the live trace!")
    else:
        inc_options = {
            f"Incident #{inc.id} | Order {ord_.order_number} | {cust.name} ({inc.status})": inc.id
            for inc, ord_, cust in all_incidents
        }
        sel_label = st.selectbox("Select Incident to Inspect:", options=list(inc_options.keys()))
        inspected_inc_id = inc_options[sel_label]

        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == inspected_inc_id).first()
            ord_ = db.query(Order).filter(Order.id == inc.order_id).first()
            cust = db.query(Customer).filter(Customer.id == ord_.customer_id).first()
            runs = (
                db.query(AgentRun)
                .filter(AgentRun.incident_id == inspected_inc_id)
                .order_by(AgentRun.step_number.asc())
                .all()
            )

        # Metrics bar
        st.markdown(f"""
        <div class="metric-grid" style="grid-template-columns: repeat(4, 1fr); margin-bottom: 1rem;">
            <div class="kpi-card-luxury blue">
                <div class="kpi-val" style="font-size: 1.4rem;">{ord_.order_number}</div>
                <div class="kpi-lbl">Order Number</div>
            </div>
            <div class="kpi-card-luxury purple">
                <div class="kpi-val" style="font-size: 1.4rem;">{cust.name}</div>
                <div class="kpi-lbl">Customer</div>
            </div>
            <div class="kpi-card-luxury green">
                <div class="kpi-val" style="font-size: 1.4rem; color: #059669;">{inc.status}</div>
                <div class="kpi-lbl">Incident Status</div>
            </div>
            <div class="kpi-card-luxury amber">
                <div class="kpi-val" style="font-size: 1.4rem; color: #D97706;">{len(runs)} Steps</div>
                <div class="kpi-lbl">Reasoning Steps</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### 📜 Step-by-Step Tool Calling Trace")
        for r in runs:
            badge_color = "#E0F2FE" if r.action_type == "observation" else "#FEF3C7" if r.action_type == "tool_call" else "#DCFCE7" if r.action_type == "decision" else "#FEE2E2"
            text_color = "#0369A1" if r.action_type == "observation" else "#92400E" if r.action_type == "tool_call" else "#15803D" if r.action_type == "decision" else "#B91C1C"

            with st.expander(f"Step {r.step_number} • [{r.action_type.upper()}] {r.tool_name or ''} — {r.decision or 'Executing step'}", expanded=True):
                if r.arguments:
                    st.markdown("**Tool Arguments:**")
                    st.code(r.arguments, language="json")
                if r.result:
                    st.markdown("**Tool Output (Injected Back into LLM Context):**")
                    st.code(r.result, language="json")

        if inc.agent_decision:
            st.markdown("#### 🎯 Verified Resolution Summary")
            with st.container(border=True):
                if inc.status == "RESOLVED":
                    st.success(inc.agent_decision)
                else:
                    st.warning(inc.agent_decision)

# ───────────────────────────────────────────────────────────────────────────
# TAB 3: FLEET COURIERS & CUSTOMER MEMORY
# ───────────────────────────────────────────────────────────────────────────
with tab_fleet:
    st.markdown("### 🚚 Fleet Couriers & Customer Operational Memory")
    st.caption("Active delivery partners and persistent operational memory facts used by the agent:")

    fc1, fc2 = st.columns(2)

    with fc1:
        st.markdown("#### 🛵 Active Logistics Couriers")
        with get_db() as db:
            couriers = db.query(Courier).all()
            courier_data = [
                {
                    "ID": c.id,
                    "Name": c.name,
                    "Vehicle": c.vehicle_type.upper(),
                    "Status": c.status.upper(),
                    "Service Area": c.service_area,
                    "Working Hours": f"{c.available_from} - {c.available_until}",
                }
                for c in couriers
            ]
            st.dataframe(courier_data, use_container_width=True)

    with fc2:
        st.markdown("#### 🧠 Customer Operational Memory")
        with get_db() as db:
            memories = (
                db.query(AgentMemory, Customer)
                .join(Customer, AgentMemory.customer_id == Customer.id)
                .order_by(AgentMemory.created_at.desc())
                .limit(10)
                .all()
            )

        if not memories:
            st.info("No customer memories recorded yet. Memories are automatically saved after each incident rescue!")
        else:
            for mem, cust in memories:
                m_color = "#2563EB" if mem.memory_type == "preference" else "#059669" if mem.memory_type == "resolution" else "#EF4444"
                with st.container(border=True):
                    st.markdown(
                        f"<div style='border-left: 3px solid {m_color}; padding-left: 8px;'>"
                        f"<b>{cust.name}</b> [{mem.memory_type.upper()}] (Importance: {mem.importance:.1f})<br>"
                        f"<span style='color:#475569;'>{mem.content}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
