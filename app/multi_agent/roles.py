"""
RescueFlow AI — Deterministic role logic for the specialised agents.

Two uses:
1. ``RoleAwareMockProvider`` answers as each agent offline, so the whole
   multi-agent workflow runs in demos and tests without an API key.
2. When a real model returns something that is not valid JSON, the agent
   falls back to the same logic, so one bad reply cannot derail the case.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.providers.base import LLMProvider, LLMResponse

FACTS_MARKER = "FACTS:\n"
TASK_MARKER = "\n\nTASK:"


def parse_json(text: str | None) -> dict[str, Any] | None:
    """First JSON object in a model reply, or None."""
    if not text:
        return None
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for chunk in candidates:
        try:
            value = json.loads(chunk)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def _window_named(text: str) -> str | None:
    text = (text or "").lower()
    for window in ("morning", "afternoon", "evening"):
        if window in text:
            return window
    return None


def triage(facts: dict[str, Any]) -> dict[str, Any]:
    desc = (facts.get("incident", {}).get("description") or "").lower()
    request = None
    match = re.search(r'customer replied: "([^"]+)"', desc)
    if match:
        request = match.group(1)
    if request:
        category = "customer_request"
    elif "address" in desc or "location" in desc:
        category = "address_issue"
    elif "refus" in desc:
        category = "refused"
    elif "cod" in desc or "cash" in desc or "payment" in desc:
        category = "cod_payment"
    elif "unreachable" in desc or "unavailable" in desc or "not home" in desc or "failed" in desc:
        category = "customer_unavailable"
    else:
        category = "other"
    return {
        "category": category,
        "severity": "high",
        "customer_request": request,
        "summary": f"Delivery exception classified as {category.replace('_', ' ')}.",
    }


def context(facts: dict[str, Any]) -> dict[str, Any]:
    profile = facts.get("profile") or {}
    constraints = []
    if profile.get("special_instructions"):
        constraints.append(str(profile["special_instructions"]))
    commercial = str(profile.get("address_type", "")).lower() == "commercial"
    if commercial:
        constraints.append("Office address: deliver 09:00-18:00 on weekdays.")
    preferred = profile.get("preferred_delivery_time")
    return {
        "preferred_window": preferred,
        "is_vip": bool(profile.get("is_vip")),
        "is_commercial_address": commercial,
        "constraints": constraints,
        "summary": f"Customer prefers {preferred or 'no particular'} delivery"
                   f"{'; VIP' if profile.get('is_vip') else ''}{'; office address' if commercial else ''}.",
    }


def logistics(facts: dict[str, Any]) -> dict[str, Any]:
    slots = facts.get("candidate_slots") or []
    order = sorted(
        range(len(slots)),
        key=lambda i: (not slots[i].get("matches_preference"), -float(slots[i].get("score", 0))),
    )
    attempts = int((facts.get("history") or {}).get("attempt_count") or 0)
    return {
        "failed_attempts": attempts,
        "feasible": bool(slots) and attempts < 3,
        "best_slot_indexes": order[:3],
        "summary": f"{len(slots)} candidate slot(s); {attempts} failed attempt(s) so far.",
    }


def _rejected_windows(case: dict[str, Any]) -> set[tuple[str, str]]:
    rejected_versions = {r["version"] for r in case.get("critic_reviews", []) if not r["approved"]}
    out = set()
    for p in case.get("previous_proposals", []):
        if p["version"] in rejected_versions and p["tool_name"] == "reschedule_delivery":
            out.add((str(p["arguments"].get("date")), str(p["arguments"].get("start_time"))))
    return out


def _cite(case: dict[str, Any], *preferred: str) -> str:
    """Citations for offline plans: the preferred policy ids that were retrieved, else the top sources."""
    sources = [s["id"] for s in (case.get("knowledge") or {}).get("sources", [])]
    picked = [p for p in preferred if p in sources] or sources[:2]
    return (" " + " ".join(f"[{p}]" for p in picked)) if picked else ""


def planner(case: dict[str, Any]) -> dict[str, Any]:
    answer = _plan(case)
    if answer["tool_name"] == "escalate_incident":
        cites = _cite(case, "reattempt-policy#attempt-limit", "escalation-matrix#when-to-escalate")
    else:
        preferred = ["ndr-handling#customer-request"] if (case.get("triage") or {}).get("customer_request") else []
        preferred += ["ndr-handling#customer-unavailable", "reattempt-policy#choosing-a-slot"]
        if (case.get("customer_context") or {}).get("is_commercial_address"):
            preferred.insert(0, "office-delivery#business-hours-only")
        cites = _cite(case, *preferred)
    answer["rationale"] = answer["rationale"] + cites
    return answer


def _plan(case: dict[str, Any]) -> dict[str, Any]:
    logistics_ = case.get("logistics") or {}
    ctx = case.get("customer_context") or {}
    triage_ = case.get("triage") or {}
    slots = logistics_.get("candidate_slots") or []
    if int(logistics_.get("failed_attempts") or 0) >= 3:
        return {"tool_name": "escalate_incident",
                "arguments": {"reason": "Three or more failed attempts; policy requires a person to take over."},
                "rationale": "Repeated failures exceed the automatic retry limit."}

    wanted = _window_named(triage_.get("customer_request") or "") or ctx.get("preferred_window")
    tried = _rejected_windows(case)
    ranked = [slots[i] for i in logistics_.get("best_slot_indexes", []) if 0 <= i < len(slots)] or slots
    ordered = [s for s in ranked if s.get("time_block") == wanted] + [s for s in ranked if s.get("time_block") != wanted]
    if ctx.get("is_commercial_address"):
        ordered = [s for s in ordered if s.get("time_block") != "evening"]
    for slot in ordered:
        if (str(slot.get("date")), str(slot.get("start_time"))) in tried:
            continue
        return {
            "tool_name": "reschedule_delivery",
            "arguments": {"date": slot["date"], "start_time": slot["start_time"], "end_time": slot["end_time"]},
            "rationale": f"{slot['time_block'].title()} slot on {slot['date']} with {slot.get('courier_name', 'the courier')}"
                         f" matches {'the customer request' if wanted == triage_.get('customer_request') else 'the preferred window' if slot.get('time_block') == wanted else 'availability'}.",
        }
    return {"tool_name": "escalate_incident",
            "arguments": {"reason": "No acceptable delivery slot remains."},
            "rationale": "Every feasible slot was rejected or none exist."}


def critic(case: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    if proposal.get("tool_name") != "reschedule_delivery":
        return {"verdict": "approve", "reason": "Escalation hands the order to a person."}
    ctx = case.get("customer_context") or {}
    slots = (case.get("logistics") or {}).get("candidate_slots") or []
    wanted = _window_named((case.get("triage") or {}).get("customer_request") or "") or ctx.get("preferred_window")
    chosen = next((s for s in slots if s.get("date") == proposal["arguments"].get("date")
                   and s.get("start_time") == proposal["arguments"].get("start_time")), None)
    if wanted and chosen and chosen.get("time_block") != wanted and any(s.get("time_block") == wanted for s in slots):
        return {"verdict": "reject", "reason": f"Customer wants {wanted}; a {wanted} slot is available."}
    return {"verdict": "approve", "reason": "Matches the customer's window and constraints."}


ROLE_FALLBACKS = {"TRIAGE": triage, "CONTEXT": context, "LOGISTICS": logistics, "PLANNER": planner}


def _facts_from(messages: list[dict[str, Any]]) -> dict[str, Any]:
    user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "") or ""
    if FACTS_MARKER in user:
        body = user.split(FACTS_MARKER, 1)[1].split(TASK_MARKER, 1)[0]
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}
    return {}


class RoleAwareMockProvider(LLMProvider):
    """Offline provider that answers as whichever RescueFlow agent is asking."""

    def generate(self, messages, tools=None, **kwargs) -> LLMResponse:
        system = next((m["content"] for m in messages if m.get("role") == "system"), "") or ""
        role_match = re.search(r"ROLE: (\w+)", system)
        role = role_match.group(1) if role_match else ""
        facts = _facts_from(messages)
        if role == "CRITIC":
            answer = critic(facts.get("case", {}), facts.get("proposal", {}))
        elif role in ROLE_FALLBACKS:
            answer = ROLE_FALLBACKS[role](facts)
        else:
            answer = {"summary": "No role recognised."}
        return LLMResponse(content=json.dumps(answer))
