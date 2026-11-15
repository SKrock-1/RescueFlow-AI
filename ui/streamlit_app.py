"""
RescueFlow AI for Shopify — Autonomous Delivery-Exception Resolution App.

A dedicated Shopify Operations Console connecting directly to Shopify Admin REST API:
- Live 2-way synchronization with Shopify Stores
- Autonomous Plan-Act-Observe Agent Loop for Delivery Failures (NDRs)
- Real-time customer WhatsApp & SMS dispatch
- Automatic Shopify Order tags and note attributes updates
"""

from __future__ import annotations

import html
import json
import time
from datetime import datetime, date
import streamlit as st

from app.config import get_settings
from app.database.engine import get_db, init_db
from app.database.models import Incident, Order, Customer, Delivery, Courier, AgentMemory, AgentRun
from app.database.seed import seed_all
from app.agent.agent import AgentRunner
from app.agent.engines import ENGINE_LABELS, create_runner, resolve_engine_name
from app.agent.observer import AgentObserver
from app.providers.factory import create_provider
from app.providers.base import LLMProvider, LLMResponse
from app.providers.mock_provider import MockProvider
from app.services.shopify_service import get_shopify_service
from app.schemas.models import TraceEvent
from app.services.rescue_view import (
    describe_proposal,
    last_notification,
    latest_incident,
    local_order_number,
    message_preview,
    proposal_checks,
    shopify_preview,
    state_label,
)

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
    .kpi-card-luxury.gray::before { background: #94A3B8; }

    /* Run-state chips: text always names the state; colour only supports it */
    .chip-state-green { background: #ECFDF5 !important; color: #065F46 !important; border-color: #A7F3D0 !important; font-weight: 700 !important; }
    .chip-state-blue { background: #EFF6FF !important; color: #1E40AF !important; border-color: #BFDBFE !important; font-weight: 700 !important; }
    .chip-state-orange { background: #FFF7ED !important; color: #9A3412 !important; border-color: #FED7AA !important; font-weight: 700 !important; }
    .chip-state-red { background: #FEF2F2 !important; color: #991B1B !important; border-color: #FECACA !important; font-weight: 700 !important; }
    .chip-state-gray { background: #F1F5F9 !important; color: #334155 !important; border-color: #CBD5E1 !important; font-weight: 700 !important; }

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
store_conn = (
    shopify_svc.test_connection()
    if shopify_svc.is_configured
    else {"success": False, "error": "Shopify is not configured in .env."}
)
store_connected = bool(store_conn.get("success"))

# ── Sidebar Configuration ──────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom: 0.5rem;">
        <span style="font-size: 1.8rem;">🛍️</span>
        <div>
            <h3 style="margin:0; font-size:1.2rem; font-weight:800; color:#0F172A;">RescueFlow AI</h3>
            <span style="font-size:0.75rem; color:#64748B; font-weight:600;">Delivery rescue console</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("#### Shopify store")
    if store_connected:
        st.markdown(f"**Store:** `{store_conn.get('name')}`")
        st.markdown(f"**Domain:** `{store_conn.get('domain')}`")
        st.caption("Connected: the store answered a test request when this page loaded.")
        st.link_button("Open Shopify Admin", f"https://{shopify_svc.store_url}/admin", use_container_width=True)
    else:
        st.error(f"Not connected. {store_conn.get('error', '')}")

    st.markdown("---")
    st.markdown("#### AI provider")
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

    engine_keys = list(ENGINE_LABELS)
    chosen_engine = st.selectbox(
        "Agent engine",
        options=engine_keys,
        index=engine_keys.index(resolve_engine_name()),
        format_func=lambda k: ENGINE_LABELS[k],
        help="Both engines use the same tools, guardrails, approval step and verification.",
    )
    st.session_state["chosen_engine"] = chosen_engine

    st.markdown("---")
    st.markdown("#### Demo actions")
    if st.button("Create a failed test order in Shopify", use_container_width=True):
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

    if st.button("Refresh orders", use_container_width=True):
        st.rerun()

# ── Header Banner ──────────────────────────────────────────────────────────
store_domain = shopify_svc.store_url if store_connected else "Not connected to Shopify"

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
        <span class="store-badge">{html.escape(store_domain)}</span>
        <div style="font-size: 0.75rem; color: #94A3B8; margin-top: 6px; font-family: monospace;">
            Shopify Admin REST API 2024-01
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Top Level Navigation Tabs ──────────────────────────────────────────────
tab_orders, tab_trace, tab_fleet = st.tabs([
    "Orders",
    "Agent trace",
    "Fleet and memory",
])

# ───────────────────────────────────────────────────────────────────────────
# TAB 1: SHOPIFY ORDERS & LIVE RESCUE
# ───────────────────────────────────────────────────────────────────────────
with tab_orders:
    live_orders = shopify_svc.list_orders(limit=20) if store_connected else []
    order_rows = []
    for o in live_orders:
        num = local_order_number(o)
        order_rows.append((o, num, latest_incident(num)))

    def _status_of(row):
        return row[2]["status"] if row[2] else None

    to_plan_states = {None, "OPEN", "FAILED", "REJECTED"}
    count_to_plan = sum(1 for r in order_rows if _status_of(r) in to_plan_states)
    count_awaiting = sum(1 for r in order_rows if _status_of(r) == "AWAITING_APPROVAL")
    count_rescued = sum(1 for r in order_rows if _status_of(r) == "RESOLVED")
    count_escalated = sum(1 for r in order_rows if _status_of(r) == "ESCALATED")

    st.markdown(f"""
    <div class="metric-grid">
        <div class="kpi-card-luxury amber">
            <div class="kpi-val">{count_to_plan}</div>
            <div class="kpi-lbl">To plan</div>
        </div>
        <div class="kpi-card-luxury blue">
            <div class="kpi-val">{count_awaiting}</div>
            <div class="kpi-lbl">Awaiting approval</div>
        </div>
        <div class="kpi-card-luxury green">
            <div class="kpi-val">{count_rescued}</div>
            <div class="kpi-lbl">Rescued, verified</div>
        </div>
        <div class="kpi-card-luxury gray">
            <div class="kpi-val">{count_escalated}</div>
            <div class="kpi-lbl">Escalated to ops</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.caption(f"Counts cover the {len(order_rows)} most recent Shopify orders and come from stored incident records.")

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("### Failed deliveries")
        st.caption("Plan a rescue to let the agent investigate. Nothing changes in Shopify or reaches the customer until you approve the plan.")

        if not store_connected:
            st.warning(f"Not connected to Shopify, so no orders can be loaded. {store_conn.get('error', '')}")

        filter_status = st.radio(
            "Show",
            ["All", "To plan", "Awaiting approval", "Done"],
            horizontal=True,
        )
        filter_map = {
            "To plan": to_plan_states,
            "Awaiting approval": {"AWAITING_APPROVAL"},
            "Done": {"RESOLVED", "ESCALATED"},
        }
        filtered_rows = [
            r for r in order_rows
            if filter_status == "All" or _status_of(r) in filter_map[filter_status]
        ]

        if store_connected and not filtered_rows:
            st.info(f"No orders in '{filter_status}'. Create a test order with the form beside this list.")

        for o, local_num, inc in filtered_rows:
            order_num = o.get("name", f"#{o.get('id')}")
            cust = o.get("customer") or {}
            cust_name = f"{cust.get('first_name') or ''} {cust.get('last_name') or ''}".strip() or "Guest customer"
            initials = "".join(part[0].upper() for part in cust_name.split()[:2]) or "SH"
            cust_phone = cust.get("phone") or (o.get("shipping_address") or {}).get("phone") or ""
            total_price = o.get("total_price", "0.00")
            currency = o.get("currency", "USD")
            financial = str(o.get("financial_status") or "").upper()
            tags = o.get("tags", "")
            note = o.get("note", "")
            status = inc["status"] if inc else None
            state_text, state_color = state_label(status)
            oid = o["id"]
            financial_html = (
                f'<span style="background: #F1F5F9; color: #334155; font-size: 0.75rem; font-weight: 700; '
                f'padding: 2px 8px; border-radius: 4px;">{html.escape(financial)}</span>'
                if financial else ""
            )
            phone_html = html.escape(cust_phone) if cust_phone else "No phone on file"

            with st.container():
                st.markdown(f"""
                <div class="order-box">
                    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px;">
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <div class="order-avatar" aria-hidden="true">{html.escape(initials)}</div>
                            <div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 1.25rem; font-weight: 800; color: #0F172A;">{html.escape(order_num)}</span>
                                    {financial_html}
                                </div>
                                <div style="color: #475569; font-size: 0.88rem; font-weight: 500;">
                                    {html.escape(cust_name)} · <span style="font-family: monospace;">{phone_html}</span>
                                </div>
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 1.1rem; font-weight: 700; color: #0F172A; font-family: 'JetBrains Mono', monospace;">
                                {html.escape(str(total_price))} <span style="font-size: 0.75rem; color: #475569;">{html.escape(currency)}</span>
                            </div>
                            <div style="margin-top: 4px;">
                                <span class="chip-tag chip-state-{state_color}" role="status">{html.escape(state_text)}</span>
                            </div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                flash = st.session_state.pop(f"flash_{oid}", None)
                if flash:
                    getattr(st, flash[0])(flash[1])

                items = o.get("line_items", [])
                item_str = ", ".join(f"{it.get('title')} (x{it.get('quantity')})" for it in items)
                if item_str:
                    st.markdown(f"**Items:** {item_str}")

                # Shopify profile chips (read from the order's tags)
                tags_list = [t.strip() for t in tags.split(",") if t.strip()]
                is_vip_order = any("vip" in t.lower() for t in tags_list)
                is_comm_order = any("commercial" in t.lower() for t in tags_list)
                pref_slot_tag = next((t.replace("slot-", "").title() for t in tags_list if t.startswith("slot-")), None)
                chips_html = []
                if is_vip_order:
                    chips_html.append("<span class='chip-tag'>VIP buyer</span>")
                if pref_slot_tag:
                    chips_html.append(f"<span class='chip-tag'>Prefers {html.escape(pref_slot_tag)}</span>")
                if is_comm_order:
                    chips_html.append("<span class='chip-tag'>Office address</span>")
                for t in tags_list:
                    if t.startswith("slot-") or t in ["vip-repeat-buyer", "commercial-address"]:
                        continue
                    chips_html.append(f"<span class='chip-tag'>{html.escape(t)}</span>")
                if chips_html:
                    st.markdown(f"**Shopify tags:** {' '.join(chips_html)}", unsafe_allow_html=True)

                if note:
                    with st.expander("Checkout note and RescueFlow notes in Shopify"):
                        st.markdown(note)

                # ── State-specific panel ──
                if status == "AWAITING_APPROVAL":
                    proposal = AgentRunner.get_pending_proposal(inc["id"])
                    if proposal:
                        tool = proposal["tool_name"]
                        args = proposal["arguments"]
                        checks = proposal_checks(inc["order_id"], tool, args)
                        blocked = any(not c.passed and c.blocking for c in checks)
                        with st.container(border=True):
                            st.markdown(f"**Proposed change:** {describe_proposal(tool, args)}")
                            if proposal["rationale"]:
                                st.caption(f"Agent's reasoning: {proposal['rationale']}")

                            st.markdown("**Policy checks**")
                            for c in checks:
                                if c.passed:
                                    mark = ":green[:material/check_circle: Passed]"
                                elif c.blocking:
                                    mark = ":red[:material/cancel: Failed]"
                                else:
                                    mark = ":orange[:material/warning: Warning]"
                                st.markdown(f"{mark} · **{c.label}**. {c.detail}")

                            preview = message_preview(inc["order_id"], tool, args)
                            st.markdown("**Customer message**")
                            if preview["text"]:
                                st.caption(f"{preview['channel']} to {preview['recipient']} · {preview['phone']} (simulated send)")
                                st.markdown("\n".join(f"> {line}" if line else ">" for line in preview["text"].split("\n")))
                            elif preview["channel"]:
                                st.warning(preview["note"])
                            else:
                                st.caption(preview["note"])

                            sp = shopify_preview(tool)
                            st.markdown("**Shopify changes if it succeeds**")
                            st.caption(f"Tags added: {', '.join(sp['tags'])}. Note appended: {sp['note']}")

                            a1, a2 = st.columns(2)
                            approve = a1.button("Approve and run", key=f"approve_{oid}", type="primary",
                                                disabled=blocked, use_container_width=True)
                            reject = a2.button("Reject plan", key=f"reject_{oid}", use_container_width=True)
                            if blocked:
                                st.caption("Approve is turned off because a required policy check failed. Reject this plan and plan again.")

                        if approve:
                            with st.status(f"Running the approved change for {order_num}", expanded=True) as box:
                                try:
                                    res = AgentRunner(provider=MockProvider()).execute_approved(inc["id"])
                                except ValueError as claim_err:
                                    box.update(label=f"{order_num}: not run", state="error")
                                    st.session_state[f"flash_{oid}"] = ("warning", str(claim_err))
                                    st.rerun()
                                outcome_text = state_label(res.status)[0]
                                box.write(f"Outcome: {outcome_text}. {res.decision_summary}")
                                ok = res.status in {"RESOLVED", "ESCALATED"}
                                if ok:
                                    push = shopify_svc.push_resolution_to_shopify(
                                        local_order_number=local_num,
                                        action=str(res.action_taken or "none"),
                                        summary=res.decision_summary,
                                        status=res.status,
                                    )
                                    shop_msg = (
                                        f"Shopify update failed: {push['error']}" if "error" in push
                                        else "Shopify tags and note updated."
                                    )
                                else:
                                    shop_msg = "Shopify was not changed."
                                box.write(shop_msg)
                                for n_ in res.notifications:
                                    box.write(f"{n_['channel'].upper()} message to {n_['recipient']} recorded (simulated send).")
                                box.update(label=f"{order_num}: {outcome_text}", state="complete" if ok else "error")
                            st.session_state[f"flash_{oid}"] = ("success" if ok else "error", f"{outcome_text}. {shop_msg}")
                            st.session_state["last_active_incident_id"] = inc["id"]
                            st.rerun()

                        if reject:
                            try:
                                AgentRunner(provider=MockProvider()).reject_proposal(
                                    inc["id"], "Rejected by operator in the console."
                                )
                                st.session_state[f"flash_{oid}"] = ("info", "Plan rejected. Nothing was changed.")
                            except ValueError as claim_err:
                                st.session_state[f"flash_{oid}"] = ("warning", str(claim_err))
                            st.rerun()

                elif status in {"RUNNING", "EXECUTING"}:
                    st.info("Work on this order is in progress. Refresh in a moment to see the result.")
                elif status == "FAILED":
                    st.error(f"Failed: {inc['decision']}")
                elif status == "REJECTED":
                    st.caption("The last plan was rejected. Nothing was changed.")
                elif status in {"RESOLVED", "ESCALATED"}:
                    if inc["decision"]:
                        (st.success if status == "RESOLVED" else st.info)(inc["decision"])
                    sent = last_notification(inc["id"])
                    if sent and sent.get("sent"):
                        stamp = sent["timestamp"].strftime("%d %b %Y, %H:%M UTC") if sent.get("timestamp") else ""
                        msg_html = html.escape(sent["message"]).replace("\n", "<br>")
                        header_html = (
                            f"{html.escape(sent['channel'].upper())} message to {html.escape(sent['recipient'])} · "
                            f"{html.escape(sent['contact'])} (simulated send)"
                        )
                        st.markdown(f"""
                        <div class="whatsapp-card">
                            <div style="font-weight: 700; font-size: 0.82rem; color: #1E3A8A; margin-bottom: 6px;">{header_html}</div>
                            <div class="whatsapp-msg">
                                {msg_html}
                                <div class="whatsapp-meta"><span>{stamp}</span></div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    elif sent:
                        st.caption(sent["reason"])

                # ── Actions ──
                b1, b2 = st.columns([3, 2])
                with b1:
                    if status not in {"AWAITING_APPROVAL", "RUNNING", "EXECUTING"}:
                        if status in {"FAILED", "REJECTED"}:
                            plan_label = "Plan again"
                        elif status in {"RESOLVED", "ESCALATED"}:
                            plan_label = "Plan a new rescue"
                        else:
                            plan_label = "Plan rescue"
                        plan_type = "secondary" if status in {"RESOLVED", "ESCALATED"} else "primary"
                        if st.button(plan_label, key=f"btn_plan_{oid}", type=plan_type, use_container_width=True):
                            with st.status(f"Planning a rescue for {order_num}", expanded=True) as box:
                                order_id, inc_id = shopify_svc.sync_shopify_order_to_db(o)
                                AgentRunner.supersede_open_incidents(order_id, keep_incident_id=inc_id)
                                chosen_prov_name = st.session_state.get("chosen_provider", settings.llm_provider)
                                box.write(
                                    f"Investigating with {ENGINE_LABELS[st.session_state.get('chosen_engine', resolve_engine_name())]} "
                                    f"and the `{chosen_prov_name}` provider. No changes are made until you approve."
                                )
                                engine = st.session_state.get("chosen_engine", resolve_engine_name())
                                runner = create_runner(engine=engine, provider=create_provider(chosen_prov_name), max_steps=8)
                                try:
                                    res = runner.resolve_incident(inc_id, plan_only=True)
                                except ValueError as claim_err:
                                    box.update(label=f"{order_num}: not started", state="error")
                                    st.session_state[f"flash_{oid}"] = ("warning", str(claim_err))
                                    st.rerun()
                                if res.status == "AWAITING_APPROVAL":
                                    box.update(label=f"{order_num}: plan ready for your approval", state="complete")
                                    flash_msg = ("info", "Plan ready. Review the proposed change below, then approve or reject it.")
                                else:
                                    box.update(label=f"{order_num}: {state_label(res.status)[0]}", state="error")
                                    flash_msg = ("error", res.decision_summary)
                            st.session_state[f"flash_{oid}"] = flash_msg
                            st.session_state["last_active_incident_id"] = inc_id
                            st.rerun()
                with b2:
                    st.link_button("Open in Shopify Admin", f"https://{shopify_svc.store_url}/admin/orders/{oid}", use_container_width=True)

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
    st.markdown("### Agent steps")
    st.caption("Every step the agent took for an incident: tool calls with their inputs and outputs, proposals, approvals and verification.")

    with get_db() as db:
        all_incidents = (
            db.query(Incident, Order, Customer)
            .join(Order, Incident.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .order_by(Incident.id.desc())
            .all()
        )

    if not all_incidents:
        st.info("No incidents yet. Plan a rescue on the Orders tab to see its steps here.")
    else:
        inc_options = {
            f"Incident #{inc.id} · {ord_.order_number} · {cust.name} · {state_label(inc.status)[0]}": inc.id
            for inc, ord_, cust in all_incidents
        }
        inc_keys = list(inc_options.keys())
        last_id = st.session_state.get("last_active_incident_id")
        default_idx = next((i for i, k in enumerate(inc_keys) if inc_options[k] == last_id), 0)
        sel_label = st.selectbox("Incident", options=inc_keys, index=default_idx)
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
            <div class="kpi-card-luxury gray">
                <div class="kpi-val" style="font-size: 1.4rem;">{html.escape(cust.name)}</div>
                <div class="kpi-lbl">Customer</div>
            </div>
            <div class="kpi-card-luxury green">
                <div class="kpi-val" style="font-size: 1.4rem;">{state_label(inc.status)[0]}</div>
                <div class="kpi-lbl">Incident status</div>
            </div>
            <div class="kpi-card-luxury amber">
                <div class="kpi-val" style="font-size: 1.4rem; color: #D97706;">{len(runs)} Steps</div>
                <div class="kpi-lbl">Steps</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("#### Steps")
        for r in runs:
            step_title = " · ".join(
                part for part in (f"Step {r.step_number}", r.action_type.replace("_", " "), r.tool_name or "", r.decision or "") if part
            )
            with st.expander(step_title, expanded=False):
                if r.arguments:
                    st.markdown("**Tool Arguments:**")
                    st.code(r.arguments, language="json")
                if r.result:
                    st.markdown("**Tool Output (Injected Back into LLM Context):**")
                    st.code(r.result, language="json")

        if inc.agent_decision:
            st.markdown("#### Outcome")
            with st.container(border=True):
                if inc.status == "RESOLVED":
                    st.success(inc.agent_decision)
                elif inc.status == "FAILED":
                    st.error(inc.agent_decision)
                else:
                    st.info(inc.agent_decision)

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
