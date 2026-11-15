"""
RescueFlow AI — The shared case file (blackboard) for the multi-agent workflow.

Every agent reads the whole ``RescueCase`` and writes only its own section.
The messages that travel along workflow edges carry the same case object, so
the graph's edges decide *who runs next* and the case decides *what they know*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Proposal:
    """What the Planner wants to do."""

    tool_name: str
    arguments: dict[str, Any]
    rationale: str
    version: int = 1
    citations: list[str] = field(default_factory=list)


@dataclass
class Review:
    """What the Policy Critic decided about one proposal."""

    version: int
    approved: bool
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RescueCase:
    incident_id: int
    order_id: int
    order_number: str
    customer_id: int
    customer_name: str
    incident_type: str
    description: str
    plan_only: bool

    # Each agent's section
    triage: dict[str, Any] = field(default_factory=dict)          # Triage
    context: dict[str, Any] = field(default_factory=dict)         # Customer Context
    logistics: dict[str, Any] = field(default_factory=dict)       # Logistics
    knowledge: dict[str, Any] = field(default_factory=dict)       # Knowledge
    proposals: list[Proposal] = field(default_factory=list)       # Planner
    reviews: list[Review] = field(default_factory=list)           # Policy Critic
    execution: dict[str, Any] = field(default_factory=dict)       # Execution
    verification: dict[str, Any] = field(default_factory=dict)    # Verifier

    outcome: str = ""            # proposed | executed | blocked | escalated_without_action
    decision_text: str = ""

    @property
    def current_proposal(self) -> Proposal | None:
        return self.proposals[-1] if self.proposals else None

    def planning_facts(self) -> dict[str, Any]:
        """A trimmed case file for the Planner and Critic, to fit free-tier token limits."""
        k = self.knowledge or {}

        def short(items, n):
            return [{"id": i["id"], "title": i.get("title", ""), "text": i.get("text", "")[:n]} for i in items]

        logistics = dict(self.logistics or {})
        logistics["candidate_slots"] = [
            {key: s.get(key) for key in ("date", "time_block", "start_time", "end_time", "courier_name",
                                          "matches_preference", "score")}
            for s in (logistics.get("candidate_slots") or [])[:6]
        ]
        context = {key: v for key, v in (self.context or {}).items() if key != "profile"}
        return {
            "incident": {"order_id": self.order_id, "order_number": self.order_number,
                         "customer_name": self.customer_name, "description": self.description[:300]},
            "triage": self.triage,
            "customer_context": context,
            "logistics": logistics,
            "knowledge": {
                "sources": short(k.get("sources", []), 260),
                "customer_memory": short(k.get("customer_memory", []), 160),
                "similar_cases": short(k.get("similar_cases", []), 200),
            },
            "previous_proposals": [
                {"version": p.version, "tool_name": p.tool_name, "arguments": p.arguments,
                 "rationale": p.rationale[:300]}
                for p in self.proposals
            ],
            "critic_reviews": [
                {"version": r.version, "approved": r.approved, "reason": r.reason} for r in self.reviews
            ],
        }

    def facts(self) -> dict[str, Any]:
        """The case as plain data, for agent prompts."""
        return {
            "incident": {
                "incident_id": self.incident_id,
                "order_id": self.order_id,
                "order_number": self.order_number,
                "customer_id": self.customer_id,
                "customer_name": self.customer_name,
                "incident_type": self.incident_type,
                "description": self.description,
            },
            "triage": self.triage,
            "customer_context": self.context,
            "logistics": self.logistics,
            "knowledge": self.knowledge,
            "previous_proposals": [
                {"version": p.version, "tool_name": p.tool_name, "arguments": p.arguments,
                 "rationale": p.rationale, "citations": p.citations}
                for p in self.proposals
            ],
            "critic_reviews": [
                {"version": r.version, "approved": r.approved, "reason": r.reason} for r in self.reviews
            ],
        }


# ── Messages that travel along workflow edges ──
@dataclass
class Findings:
    """A specialist finished its section of the case."""

    agent: str
    case: RescueCase


@dataclass
class PlanRequest:
    """Ask the Planner for a (new) proposal."""

    case: RescueCase


@dataclass
class ProposalMade:
    case: RescueCase


@dataclass
class Rejected:
    """Critic rejected the proposal; the Planner must try again."""

    case: RescueCase


@dataclass
class Approved:
    """Critic approved the proposal; it goes to the approval gate."""

    case: RescueCase


@dataclass
class ExecuteRequest:
    case: RescueCase


@dataclass
class VerifyRequest:
    case: RescueCase
