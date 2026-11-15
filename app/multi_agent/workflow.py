"""
RescueFlow AI — Multi-agent rescue workflow on Microsoft Agent Framework.

Graph (Agent Framework ``WorkflowBuilder``):

    Triage ──fan-out──► Customer Context ─┐
                    ├─► Logistics ────────┼─fan-in─► Merge ─► Planner ◄──┐
                    └─► Knowledge ────────┘                      │        │ rejected
                                                                 ▼        │ (max 2)
                                                            Policy Critic ┘
                                                                 │ approved
                                                                 ▼
                                                           Approval gate ── plan-only ──► stop (AWAITING_APPROVAL)
                                                                 │ autonomous
                                                                 ▼
                                                     Execution (only writer) ─► Verifier ─► done

Triage, Customer Context, Logistics, Planner and Policy Critic are Agent
Framework ``Agent``s with their own instructions (and, optionally, their own
model). Knowledge, the gate, Execution and Verifier are code executors.
Customer messages and memory are written afterwards by the shared close step.
All agents share one ``RescueCase`` and each writes only its own section.
"""

from __future__ import annotations

from datetime import date, timedelta
import json
import logging
from typing import Any, Never

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler

from app.af.clients import ProviderChatClient
from app.af.rescue_agent import _run_sync
from app.agent.agent import AgentRunner, RunContext
from app.agent.memory import load_customer_memory
from app.database.engine import get_db
from app.database.models import Incident, Order
from app.multi_agent import prompts, roles
from app.multi_agent.case import (
    Approved,
    ExecuteRequest,
    Findings,
    PlanRequest,
    Proposal,
    ProposalMade,
    Rejected,
    RescueCase,
    Review,
    VerifyRequest,
)
from app.providers.base import LLMProvider
from app.providers.fallback_provider import FallbackProvider
from app.providers.mock_provider import MockProvider
from app.schemas.models import AgentResult
from app.services.guardrails import policy_violation
from app.services.rescue_view import proposal_checks
from app.tools.registry import registry

logger = logging.getLogger(__name__)

MAX_REJECTIONS = 2           # after this many Critic rejections the Planner must escalate
PLANNABLE_TOOLS = {"reschedule_delivery", "escalate_incident"}
AGENT_LABELS = {
    "triage": "Triage",
    "context": "Customer Context",
    "logistics": "Logistics",
    "knowledge": "Knowledge",
    "planner": "Resolution Planner",
    "critic": "Policy Critic",
    "gate": "Approval gate",
    "execution": "Execution",
    "verifier": "Verifier",
}


class MultiAgentRescue(AgentRunner):
    """Engine 'multi_agent': specialised agents coordinated by an Agent Framework workflow."""

    engine_name = "multi_agent"

    def __init__(self, *args: Any, role_providers: dict[str, LLMProvider] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # The single-agent mock speaks in tool calls; each specialist needs answers in its role.
        if isinstance(self.provider, MockProvider):
            self.provider = roles.RoleAwareMockProvider()
        elif isinstance(self.provider, FallbackProvider):
            self.provider.providers = [
                roles.RoleAwareMockProvider() if isinstance(p, MockProvider) else p
                for p in self.provider.providers
            ]
        self.role_providers = dict(role_providers or {})

    # ── helpers used by the executors ──
    def provider_for(self, role: str) -> LLMProvider:
        return self.role_providers.get(role, self.provider)

    async def ask(self, run: RunContext, role: str, instructions: str, facts: dict[str, Any], task: str,
                  fallback) -> dict[str, Any]:
        """Run one specialist Agent and return its JSON answer (or the role's fallback)."""
        client = ProviderChatClient(self.provider_for(role), tool_schemas=[], max_iterations=2)
        agent = Agent(client=client, instructions=instructions, name=f"rescueflow_{role}")
        try:
            response = await agent.run(f"{roles.FACTS_MARKER}{json.dumps(facts, default=str)}{roles.TASK_MARKER} {task}")
        except Exception as exc:
            self._provider_failed(run, exc)
            raise
        answer = roles.parse_json(client.last_assistant_text or response.text)
        used_fallback = answer is None
        if used_fallback:
            answer = fallback()
        self.note(run, role, answer.get("summary") or answer.get("reason") or answer.get("rationale") or "",
                  answer, used_fallback=used_fallback)
        return answer

    def note(self, run: RunContext, role: str, summary: str, result: dict[str, Any] | None = None,
             used_fallback: bool = False, status: str = "success") -> None:
        run.step_counter += 1
        label = AGENT_LABELS.get(role, role)
        text = f"{label}: {summary}".strip().rstrip(":")
        if used_fallback:
            text += " (model reply was not valid JSON; used the built-in rule)"
        self._record_trace_step(
            trace=run.trace, step_number=run.step_counter, event_type="agent",
            tool_name=role, summary=text, result=result, status=status,
        )

    def tool(self, run: RunContext, role: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """A read-only tool call made on behalf of a specialist, recorded in the trace."""
        output = registry.execute(name, args)
        self._record_trace_step(
            trace=run.trace, step_number=run.step_counter + 1, event_type="tool_call", tool_name=name,
            summary=f"{AGENT_LABELS[role]} called {name}", arguments=args, result=output,
            status="success" if output.get("success", True) else "error",
        )
        return output

    # ── engine entry point ──
    def resolve_incident(self, incident_id: int, plan_only: bool = False) -> AgentResult:
        run = self._open_run(incident_id, plan_only)
        case = RescueCase(
            incident_id=run.incident_id, order_id=run.order_id, order_number=run.order_number,
            customer_id=run.customer_id, customer_name=run.customer_name,
            incident_type=run.incident_type, description=run.incident_description, plan_only=plan_only,
        )
        workflow = build_workflow(self, run)
        try:
            _run_sync(workflow.run(case))
        except Exception as exc:
            logger.exception("Multi-agent workflow failed for incident %d", incident_id)
            if not run.provider_failed:
                # Not a model error: report it as what it is.
                run.provider_failed = True
                run.state.errors.append(f"Workflow error: {type(exc).__name__}: {exc}")
                run.final_decision_text = (
                    f"No action was taken: the workflow stopped with an internal error ({type(exc).__name__})."
                )
        else:
            if not run.final_decision_text:
                run.final_decision_text = case.decision_text
        return self._close_run(run)


# ──────────────────────────────────────────
# Executors
# ──────────────────────────────────────────
class _Step(Executor):
    def __init__(self, id: str, engine: MultiAgentRescue, run: RunContext) -> None:
        super().__init__(id)
        self.engine = engine
        self.rc = run


class TriageAgent(_Step):
    @handler
    async def classify(self, case: RescueCase, ctx: WorkflowContext[RescueCase]) -> None:
        facts = {"incident": case.facts()["incident"]}
        case.triage = await self.engine.ask(
            self.rc, "triage", prompts.TRIAGE, facts, "Classify this delivery exception.",
            lambda: roles.triage(facts),
        )
        await ctx.send_message(case)


class ContextAgent(_Step):
    @handler
    async def gather(self, case: RescueCase, ctx: WorkflowContext[Findings]) -> None:
        order = self.engine.tool(self.rc, "context", "get_order", {"order_id": case.order_id})
        profile = self.engine.tool(self.rc, "context", "get_customer_profile", {"customer_id": case.customer_id})
        facts = {"order": order, "profile": profile}
        answer = await self.engine.ask(
            self.rc, "context", prompts.CONTEXT, facts, "Summarise what the team must respect.",
            lambda: roles.context(facts),
        )
        answer.setdefault("preferred_window", profile.get("preferred_delivery_time"))
        case.context = answer
        await ctx.send_message(Findings("context", case))


class LogisticsAgent(_Step):
    @handler
    async def assess(self, case: RescueCase, ctx: WorkflowContext[Findings]) -> None:
        history = self.engine.tool(self.rc, "logistics", "get_delivery_history", {"order_id": case.order_id})
        slots: list[dict[str, Any]] = []
        for days_ahead in (1, 2):
            day = (date.today() + timedelta(days=days_ahead)).isoformat()
            found = self.engine.tool(self.rc, "logistics", "find_available_delivery_slots",
                                     {"customer_id": case.customer_id, "date": day})
            slots += found.get("slots", []) if found.get("success") else []
            if len(slots) >= 6:
                break
        candidates = [
            {k: s.get(k) for k in ("date", "time_block", "start_time", "end_time", "courier_id",
                                    "courier_name", "matches_preference", "score")}
            for s in slots[:8]
        ]
        facts = {"history": history, "candidate_slots": candidates}
        answer = await self.engine.ask(
            self.rc, "logistics", prompts.LOGISTICS, facts, "Assess delivery feasibility.",
            lambda: roles.logistics(facts),
        )
        # Facts come from the database, not from the model.
        answer["failed_attempts"] = int(history.get("attempt_count") or 0)
        answer["candidate_slots"] = candidates
        case.logistics = answer
        await ctx.send_message(Findings("logistics", case))


class KnowledgeAgent(_Step):
    """Past cases and stored memories for this customer (Phase 3 replaces this with pgvector + Mem0)."""

    @handler
    async def recall(self, case: RescueCase, ctx: WorkflowContext[Findings]) -> None:
        memories = load_customer_memory(case.customer_id)[:5]
        with get_db() as db:
            past = (
                db.query(Incident, Order)
                .join(Order, Incident.order_id == Order.id)
                .filter(Order.customer_id == case.customer_id, Incident.id != case.incident_id,
                        Incident.status.in_(["RESOLVED", "ESCALATED"]))
                .order_by(Incident.id.desc())
                .limit(3)
                .all()
            )
            past_cases = [
                {"incident_id": inc.id, "order": order.order_number, "outcome": inc.status,
                 "decision": (inc.agent_decision or "")[:200]}
                for inc, order in past
            ]
        case.knowledge = {
            "memories": [{"type": m["memory_type"], "content": m["content"]} for m in memories],
            "similar_cases": past_cases,
        }
        self.engine.note(self.rc, "knowledge",
                         f"{len(memories)} memory fact(s) and {len(past_cases)} past case(s) for this customer.",
                         case.knowledge)
        await ctx.send_message(Findings("knowledge", case))


class MergeFindings(_Step):
    @handler
    async def merge(self, items: list[Findings], ctx: WorkflowContext[PlanRequest]) -> None:
        await ctx.send_message(PlanRequest(items[0].case))


class PlannerAgent(_Step):
    @handler
    async def first_plan(self, request: PlanRequest, ctx: WorkflowContext[ProposalMade]) -> None:
        await self._plan(request.case, ctx)

    @handler
    async def replan(self, rejected: Rejected, ctx: WorkflowContext[ProposalMade]) -> None:
        await self._plan(rejected.case, ctx)

    async def _plan(self, case: RescueCase, ctx: WorkflowContext[ProposalMade]) -> None:
        rejections = sum(1 for r in case.reviews if not r.approved)
        if rejections >= MAX_REJECTIONS:
            answer = {
                "tool_name": "escalate_incident",
                "arguments": {"reason": f"The Policy Critic rejected {rejections} plans: {case.reviews[-1].reason}"},
                "rationale": "No plan passed review, so a person must decide.",
            }
            self.engine.note(self.rc, "planner", answer["rationale"], answer)
        else:
            facts = case.facts()
            answer = await self.engine.ask(
                self.rc, "planner", prompts.PLANNER, facts, "Propose one recovery action.",
                lambda: roles.planner(facts),
            )
            if answer.get("tool_name") not in PLANNABLE_TOOLS or not isinstance(answer.get("arguments"), dict):
                answer = roles.planner(facts)
                self.engine.note(self.rc, "planner", "Reply named no usable action; used the built-in rule.", answer)
        args = dict(answer["arguments"])
        args["order_id"] = case.order_id  # an agent may only act on its own incident's order
        case.proposals.append(Proposal(
            tool_name=answer["tool_name"], arguments=args,
            rationale=str(answer.get("rationale") or ""), version=len(case.proposals) + 1,
        ))
        await ctx.send_message(ProposalMade(case))


class CriticAgent(_Step):
    @handler
    async def review(self, made: ProposalMade, ctx: WorkflowContext[Approved | Rejected]) -> None:
        case = made.case
        proposal = case.current_proposal
        checks = proposal_checks(case.order_id, proposal.tool_name, proposal.arguments)
        hard = policy_violation(proposal.tool_name, proposal.arguments, case.order_id)
        failed = [c for c in checks if not c.passed and c.blocking]
        check_rows = [{"label": c.label, "passed": c.passed, "blocking": c.blocking, "detail": c.detail} for c in checks]

        if hard or failed:
            reason = hard or f"{failed[0].label} failed: {failed[0].detail}"
            review = Review(proposal.version, False, reason, check_rows)
            self.engine.note(self.rc, "critic", f"Rejected plan v{proposal.version}. {reason}",
                             {"verdict": "reject", "reason": reason, "checks": check_rows}, status="error")
        else:
            facts = {"case": case.facts(), "proposal": {
                "version": proposal.version, "tool_name": proposal.tool_name,
                "arguments": proposal.arguments, "rationale": proposal.rationale}}
            answer = await self.engine.ask(
                self.rc, "critic", prompts.CRITIC, facts, "Approve or reject this proposal.",
                lambda: roles.critic(facts["case"], facts["proposal"]),
            )
            approved = str(answer.get("verdict", "approve")).lower().startswith("approve")
            review = Review(proposal.version, approved, str(answer.get("reason") or ""), check_rows)

        case.reviews.append(review)
        await ctx.send_message(Approved(case) if review.approved else Rejected(case))


class ApprovalGate(_Step):
    @handler
    async def gate(self, approved: Approved, ctx: WorkflowContext[ExecuteRequest, RescueCase]) -> None:
        case = approved.case
        proposal = case.current_proposal
        if not case.plan_only:
            self.engine.note(self.rc, "gate", "Autonomous mode: approved plan goes straight to Execution.")
            await ctx.send_message(ExecuteRequest(case))
            return
        decision, blocked = self.engine._before_tool(self.rc, proposal.tool_name, proposal.arguments, proposal.rationale)
        if decision == "propose":
            case.outcome = "proposed"
            case.decision_text = proposal.rationale
            self.engine.note(self.rc, "gate", "Plan stored; waiting for an operator to approve it.")
        else:
            case.outcome = "blocked"
            case.decision_text = (blocked or {}).get("error", "Plan was blocked at the approval gate.")
            self.engine.note(self.rc, "gate", case.decision_text, blocked, status="error")
        await ctx.yield_output(case)


class ExecutionAgent(_Step):
    """The only step that changes data."""

    @handler
    async def apply_change(self, request: ExecuteRequest, ctx: WorkflowContext[VerifyRequest, RescueCase]) -> None:
        case = request.case
        proposal = case.current_proposal
        decision, blocked = self.engine._before_tool(self.rc, proposal.tool_name, proposal.arguments, proposal.rationale)
        if decision == "block":
            output = blocked or {"success": False}
        else:
            output = registry.execute(proposal.tool_name, proposal.arguments)
        self.rc.step_counter += 1
        self.engine._after_tool(self.rc, proposal.tool_name, proposal.arguments, output, proposal.rationale, verify=False)
        case.execution = output
        if output.get("success"):
            case.outcome = "executed"
            case.decision_text = self.rc.final_decision_text or proposal.rationale
            await ctx.send_message(VerifyRequest(case))
        else:
            case.outcome = "blocked"
            case.decision_text = f"The approved action failed: {output.get('reason') or output.get('error')}"
            await ctx.yield_output(case)


class VerifierAgent(_Step):
    @handler
    async def verify(self, request: VerifyRequest, ctx: WorkflowContext[Never, RescueCase]) -> None:
        case = request.case
        proposal = case.current_proposal
        self.rc.step_counter += 1
        ok = self.engine._verify_after(self.rc, proposal.tool_name, proposal.arguments)
        case.verification = {"verified": ok}
        await ctx.yield_output(case)


def build_workflow(engine: MultiAgentRescue, run: RunContext):
    """Wire the specialised agents into the rescue graph."""
    triage = TriageAgent("triage", engine, run)
    context = ContextAgent("context", engine, run)
    logistics = LogisticsAgent("logistics", engine, run)
    knowledge = KnowledgeAgent("knowledge", engine, run)
    merge = MergeFindings("merge", engine, run)
    planner = PlannerAgent("planner", engine, run)
    critic = CriticAgent("critic", engine, run)
    gate = ApprovalGate("gate", engine, run)
    execution = ExecutionAgent("execution", engine, run)
    verifier = VerifierAgent("verifier", engine, run)

    return (
        WorkflowBuilder(start_executor=triage, name="rescueflow_multi_agent",
                        description="Triage, parallel investigation, planner-critic review, approval gate, execution.")
        .add_fan_out_edges(triage, [context, logistics, knowledge])
        .add_fan_in_edges([context, logistics, knowledge], merge)
        .add_edge(merge, planner)
        .add_edge(planner, critic)
        .add_edge(critic, planner, condition=lambda message: isinstance(message, Rejected))
        .add_edge(critic, gate, condition=lambda message: isinstance(message, Approved))
        .add_edge(gate, execution)
        .add_edge(execution, verifier)
        .build()
    )
