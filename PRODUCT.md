# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: project examiners and evaluators watching a live demo of RescueFlow AI, a college project. They need to see, quickly and credibly, what the agents decided, why, and whether it actually worked.

Secondary (the role the console simulates): delivery-operations staff at a D2C Shopify merchant who handle failed deliveries (NDRs) and approve rescues before they touch orders or customers.

## Product Purpose

RescueFlow AI resolves last-mile delivery failures (NDRs) for Shopify merchants. When a delivery fails, agents investigate the order, customer and courier capacity, propose a recovery (reschedule, reassign, or escalate), check it against delivery policy, execute it, write the result back to Shopify and notify the customer.

Success: an evaluator can follow one rescue from the failure event to a verified outcome without reading logs, and can trust every status the console shows.

## Positioning

The decision is inspectable end to end: each step, tool call, policy check and data change is visible and traceable to a stored record, and nothing is reported as done unless it was verified.

## Operating Context

- Streamlit console (`ui/streamlit_app.py`) plus a FastAPI webhook server (`app/server.py`) that receives carrier NDR events and customer replies.
- Shown in live demos and a viva; runs against a Shopify development store and seeded demo data.
- LLM calls go through a failover chain (NVIDIA NIM, Groq, offline heuristic), so provider rate limits (429) and failures are normal operating conditions the console must show honestly.
- Planned: a multi-agent version on Microsoft Agent Framework with a planner, policy critic, human approval gate and a single executing agent (see the upgrade plan doc).

## Capabilities and Constraints

- Mutations: reschedule delivery, reassign courier, update delivery status, escalate incident; Shopify tags and order notes are written back.
- Deterministic policy rules (office hours 09:00 to 18:00, courier active, max failed attempts) gate actions.
- Customer messages (WhatsApp/SMS) are simulated, not sent through a real provider.
- Terminology: NDR (non-delivery report), RTO (return to origin), rescue, escalation.

## Evidence on Hand

- Shopify development store and seeded demo customers, couriers and incidents (`app/database/seed.py`).
- Screenshots in `docs/images/`.
- No real merchant, real customer data, testimonials or measured business results exist. Do not fabricate metrics (for example sync rates or rescue rates); show only values computed from stored records.

## Product Principles

1. Never claim success the record does not show: every status comes from the stored incident and verified result.
2. Nothing irreversible without a preview: a change to Shopify or a customer message is shown and approved before it happens.
3. Show the reasoning, not just the answer: steps, policy checks and sources are one click away.
4. Failure is a first-class state: provider errors, escalations and blocked actions are explained in plain language with a next step.

## Accessibility & Inclusion

No formal standard required. Best effort: readable contrast in the theme used, state never conveyed by colour alone, keyboard-reachable actions.
