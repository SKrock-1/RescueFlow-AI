"""
RescueFlow AI — Core Agent Runner.

Implements the explicit, multi-step Plan-Act-Observe iterative agent loop
without external heavyweight agent frameworks.

Two ways to run it:
- ``resolve_incident(id)`` investigates and acts in one pass (autonomous mode).
- ``resolve_incident(id, plan_only=True)`` investigates and stops at the first
  data-changing action, storing it as a proposal for a human to approve.
  ``execute_approved(id)`` then carries out the approved proposal and
  ``reject_proposal(id)`` discards it.

Every executed change is re-read from the database before the incident is
marked RESOLVED, so the status shown to operators is never just the agent's
own claim.
"""

from __future__ import annotations

from datetime import date as date_cls, datetime, time as time_cls, timezone
import json
import logging
from typing import Any

from app.config import get_settings
from app.errors import (
    ToolNotFoundError,
    InvalidArgumentsError,
    ToolExecutionError,
)
from app.database.engine import get_db
from app.database.models import AgentRun, Incident, Order, Customer, Delivery, Courier
from app.agent.state import AgentState, AgentStatus
from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.agent.memory import (
    load_customer_memory,
    save_memory,
    summarize_relevant_memory,
)
from app.agent.trace import AgentTrace
from app.domain.lifecycle import (
    IncidentStatus,
    IllegalTransition,
    claim_incident,
    move_incident,
)
from app.agent.observer import AgentObserver
from app.providers.base import LLMProvider, LLMResponse
from app.providers.factory import create_provider
from app.services.policy import PolicyEngine
from app.services.notifications import NotificationDispatcher
from app.tools.registry import registry
from app.schemas.models import AgentResult, CandidateAction, ActionType

logger = logging.getLogger(__name__)

# Incident states in which a fresh plan may replace an older, unapproved one.
SUPERSEDABLE_STATES = {IncidentStatus.OPEN.value, IncidentStatus.AWAITING_APPROVAL.value}


def describe_provider_error(exc: Exception | str) -> str:
    """Turn a raw LLM provider exception into a short, operator-safe reason.

    Raw provider errors can include organisation IDs and request IDs, so they
    are never shown to customers or written to Shopify as-is.
    """
    text = str(exc).lower()
    if "429" in text or "rate limit" in text or "rate_limit" in text:
        return "The AI provider rate-limited the request (429)."
    if "timeout" in text or "timed out" in text:
        return "The AI provider timed out."
    if "401" in text or "403" in text or "api key" in text or "unauthorized" in text:
        return "The AI provider rejected the API key."
    return "The AI provider returned an error."


def _parse_date(value: Any) -> date_cls | None:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> time_cls | None:
    raw = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).time()
        except ValueError:
            continue
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class AgentRunner:
    """Orchestrates autonomous resolution of a delivery incident."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        max_steps: int | None = None,
        observers: list[AgentObserver] | None = None,
    ) -> None:
        self.settings = get_settings()
        self.provider = provider or create_provider()
        self.max_steps = max_steps or self.settings.max_agent_steps
        self.observers: list[AgentObserver] = list(observers or [])

    def add_observer(self, observer: AgentObserver) -> None:
        """Register an observer for real-time trace events."""
        self.observers.append(observer)

    def _record_trace_step(
        self,
        trace: AgentTrace,
        step_number: int,
        event_type: str,
        summary: str,
        tool_name: str | None = None,
        arguments: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        status: str = "success",
    ):
        event = trace.record_step(
            step_number=step_number,
            event_type=event_type,
            summary=summary,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            status=status,
        )
        for obs in self.observers:
            try:
                obs.on_step(event)
            except Exception as exc:
                logger.warning("Observer %s error: %s", obs, exc)
        return event

    # ──────────────────────────────────────────
    # Guardrails and verification
    # ──────────────────────────────────────────
    @staticmethod
    def _policy_violation(tool_name: str, arguments: dict[str, Any], default_order_id: int) -> str | None:
        """Return the guardrail message that blocks this mutation, or None if allowed."""
        if tool_name == "reschedule_delivery":
            target_order_id = arguments.get("order_id", default_order_id)
            with get_db() as db:
                deliv = db.query(Delivery).filter(Delivery.order_id == target_order_id).first()
                if deliv:
                    rule_res = PolicyEngine.rule_repeated_failure_escalation(deliv.attempt_count)
                    if not rule_res.passed:
                        return rule_res.message
        elif tool_name == "reassign_courier":
            target_courier_id = arguments.get("courier_id")
            if target_courier_id:
                with get_db() as db:
                    cour = db.query(Courier).filter(Courier.id == target_courier_id).first()
                    if cour:
                        rule_res = PolicyEngine.rule_courier_active(cour.status)
                        if not rule_res.passed:
                            return rule_res.message
        return None

    @staticmethod
    def _verify_mutation(tool_name: str, arguments: dict[str, Any], default_order_id: int) -> tuple[bool, str]:
        """Re-read the database and confirm the mutation actually landed."""
        order_id = _as_int(arguments.get("order_id", default_order_id)) or default_order_id
        with get_db() as db:
            deliv = db.query(Delivery).filter(Delivery.order_id == order_id).first()
            order = db.query(Order).filter(Order.id == order_id).first()

            if tool_name == "reschedule_delivery":
                want_date = _parse_date(arguments.get("date"))
                want_start = _parse_time(arguments.get("start_time"))
                want_end = _parse_time(arguments.get("end_time"))
                if not deliv:
                    return False, "No delivery record found after rescheduling."
                ok = (
                    deliv.scheduled_date == want_date
                    and deliv.scheduled_start == want_start
                    and deliv.scheduled_end == want_end
                    and deliv.status == "RESCHEDULED"
                )
                if ok:
                    return True, f"Delivery now scheduled for {want_date} {want_start:%H:%M}-{want_end:%H:%M}."
                return False, "The stored delivery date or window does not match the requested change."

            if tool_name == "reassign_courier":
                want_courier = _as_int(arguments.get("courier_id"))
                if deliv and deliv.courier_id == want_courier:
                    return True, f"Delivery now assigned to courier #{want_courier}."
                return False, "The stored courier does not match the requested reassignment."

            if tool_name == "update_delivery_status":
                want_status = str(arguments.get("status", "")).upper().strip()
                current = deliv.status if deliv else (order.status if order else None)
                if current == want_status:
                    return True, f"Delivery status is now {want_status}."
                return False, "The stored delivery status does not match the requested status."

            if tool_name == "escalate_incident":
                if order and order.status == "ESCALATED":
                    return True, "Order is marked as escalated to human operations."
                return False, "The order was not marked as escalated."

        return False, f"No verification check is defined for {tool_name}."

    # ──────────────────────────────────────────
    # Proposals (human approval gate)
    # ──────────────────────────────────────────
    @staticmethod
    def get_pending_proposal(incident_id: int) -> dict[str, Any] | None:
        """Return the latest stored proposal for an incident awaiting approval."""
        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == incident_id).first()
            if not inc or inc.status != AgentStatus.AWAITING_APPROVAL.value:
                return None
            run = (
                db.query(AgentRun)
                .filter(AgentRun.incident_id == incident_id, AgentRun.action_type == "proposal")
                .order_by(AgentRun.id.desc())
                .first()
            )
            if not run:
                return None
            return {
                "tool_name": run.tool_name,
                "arguments": json.loads(run.arguments) if run.arguments else {},
                "rationale": inc.agent_decision or "",
                "proposed_at": run.timestamp.isoformat() if run.timestamp else None,
            }

    @staticmethod
    def supersede_open_incidents(order_id: int, keep_incident_id: int | None = None) -> int:
        """Mark older unapproved plans for an order as superseded before a new plan runs."""
        count = 0
        with get_db() as db:
            rows = (
                db.query(Incident)
                .filter(Incident.order_id == order_id, Incident.status.in_(SUPERSEDABLE_STATES))
                .all()
            )
            for inc in rows:
                if keep_incident_id is not None and inc.id == keep_incident_id:
                    continue
                move_incident(inc, IncidentStatus.SUPERSEDED)
                count += 1
        return count

    def reject_proposal(self, incident_id: int, reason: str = "Rejected by operator.") -> AgentResult:
        """Discard a pending proposal without changing any order data."""
        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == incident_id).first()
            if not inc:
                raise ValueError(f"Incident {incident_id} not found in database.")
            order = db.query(Order).filter(Order.id == inc.order_id).first()
            order_id, customer_id = inc.order_id, (order.customer_id if order else 0)
            last_step = (
                db.query(AgentRun.step_number)
                .filter(AgentRun.incident_id == incident_id)
                .order_by(AgentRun.step_number.desc())
                .first()
            )
            if not claim_incident(db, incident_id, IncidentStatus.AWAITING_APPROVAL, IncidentStatus.REJECTED):
                raise ValueError(f"Incident {incident_id} is no longer awaiting approval.")
            inc.agent_decision = reason

        trace = AgentTrace(incident_id=incident_id)
        self._record_trace_step(
            trace=trace,
            step_number=(last_step[0] if last_step else 0) + 1,
            event_type="rejection",
            summary=reason,
        )
        return AgentResult(
            incident_id=incident_id,
            order_id=order_id,
            customer_id=customer_id,
            status="REJECTED",
            decision_summary=reason,
            trace=trace.events,
        )

    def execute_approved(self, incident_id: int) -> AgentResult:
        """Carry out the stored proposal for an incident after a human approved it."""
        proposal = self.get_pending_proposal(incident_id)
        if not proposal:
            raise ValueError(f"Incident {incident_id} has no proposal awaiting approval.")

        # Claim the approval so a double click or a second tab cannot run it twice.
        with get_db() as db:
            if not claim_incident(db, incident_id, IncidentStatus.AWAITING_APPROVAL, IncidentStatus.EXECUTING):
                raise ValueError(f"Incident {incident_id} is no longer awaiting approval.")

        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == incident_id).first()
            order = db.query(Order).filter(Order.id == inc.order_id).first()
            customer = db.query(Customer).filter(Customer.id == order.customer_id).first()
            order_id, order_number = order.id, order.order_number
            customer_id = customer.id if customer else 0
            incident_type = inc.incident_type
            last_step = (
                db.query(AgentRun.step_number)
                .filter(AgentRun.incident_id == incident_id)
                .order_by(AgentRun.step_number.desc())
                .first()
            )
        step = (last_step[0] if last_step else 0) + 1

        tool_name = proposal["tool_name"]
        arguments = dict(proposal["arguments"])
        trace = AgentTrace(incident_id=incident_id)
        errors: list[str] = []

        self._record_trace_step(
            trace=trace, step_number=step, event_type="approval",
            summary=f"Operator approved {tool_name}.", tool_name=tool_name, arguments=arguments,
        )

        status = AgentStatus.FAILED
        action_taken: str | None = None
        violation = self._policy_violation(tool_name, arguments, order_id)
        if violation:
            decision = f"Blocked by policy at execution time: {violation}"
            errors.append(decision)
            self._record_trace_step(
                trace=trace, step_number=step + 1, event_type="error",
                summary=decision, tool_name=tool_name, status="error",
            )
        else:
            try:
                tool_output = registry.execute(tool_name, arguments)
            except (ToolNotFoundError, InvalidArgumentsError, ToolExecutionError) as tool_err:
                tool_output = {"success": False, "error": str(tool_err)}
            self._record_trace_step(
                trace=trace, step_number=step + 1, event_type="tool_call",
                tool_name=tool_name, summary=f"Executed approved {tool_name}",
                arguments=arguments, result=tool_output,
                status="success" if tool_output.get("success") else "error",
            )

            if not tool_output.get("success"):
                reason = tool_output.get("reason") or tool_output.get("error") or "unknown error"
                decision = f"The approved action failed: {reason}"
                errors.append(decision)
            else:
                action_taken = tool_name
                verified, note = self._verify_mutation(tool_name, arguments, order_id)
                self._record_trace_step(
                    trace=trace, step_number=step + 2, event_type="verification",
                    tool_name=tool_name, summary=note,
                    result={"verified": verified, "detail": note},
                    status="success" if verified else "error",
                )
                if not verified:
                    decision = f"The action ran but could not be verified: {note}"
                    errors.append(decision)
                elif tool_name == "escalate_incident":
                    status = AgentStatus.ESCALATED
                    decision = f"Escalated to human operations after approval. {proposal['rationale']}".strip()
                else:
                    status = AgentStatus.RESOLVED
                    decision = f"{note} {proposal['rationale']}".strip()

        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == incident_id).first()
            if inc:
                move_incident(inc, IncidentStatus(status.value))
                inc.agent_decision = decision

        memory_updates, notifications = self._finalize(
            status=status, action_name_taken=action_taken, customer_id=customer_id,
            order_id=order_id, order_number=order_number, incident_type=incident_type,
            final_decision_text=decision, trace=trace, step_number=step + 3, errors=errors,
        )

        return AgentResult(
            incident_id=incident_id,
            order_id=order_id,
            customer_id=customer_id,
            status=status.value,
            action_taken=action_taken,
            decision_summary=decision,
            trace=trace.events,
            memory_updates=memory_updates,
            notifications=notifications,
            errors=errors,
        )

    # ──────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────
    def resolve_incident(self, incident_id: int, plan_only: bool = False) -> AgentResult:
        """Execute the end-to-end resolution loop for an incident.

        With ``plan_only=True`` the agent investigates but stops at its first
        data-changing action and stores it as a proposal (AWAITING_APPROVAL).
        """
        logger.info("Starting resolution for Incident #%d (plan_only=%s)", incident_id, plan_only)

        # 1. Fetch initial incident, order, and customer from DB
        with get_db() as db:
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if not incident:
                raise ValueError(f"Incident {incident_id} not found in database.")
            if not claim_incident(db, incident_id, IncidentStatus.OPEN, IncidentStatus.RUNNING):
                db.refresh(incident)
                raise IllegalTransition(
                    f"Incident {incident_id} is {incident.status}; only OPEN incidents can be run. "
                    f"Create a new incident to try again."
                )

            order = db.query(Order).filter(Order.id == incident.order_id).first()
            if not order:
                raise ValueError(f"Order {incident.order_id} associated with Incident {incident_id} not found.")

            customer = db.query(Customer).filter(Customer.id == order.customer_id).first()
            customer_name = customer.name if customer else "Unknown Customer"
            customer_id = customer.id if customer else 0
            incident_type = incident.incident_type
            incident_description = incident.description
            order_number = order.order_number
            order_id = order.id

        # 2. Initialize Agent State & Trace
        state = AgentState(
            incident_id=incident_id,
            order_id=order_id,
            customer_id=customer_id,
            goal=f"Resolve incident '{incident_type}' for order {order_number} ({customer_name}).",
            max_steps=self.max_steps,
            status=AgentStatus.INVESTIGATING,
        )
        trace = AgentTrace(incident_id=incident_id)

        self._record_trace_step(
            trace=trace,
            step_number=0,
            event_type="observation",
            summary=f"Incident opened: '{incident_type}' on order {order_number}.",
            result={"description": incident_description, "customer": customer_name},
        )

        # 3. Load Persistent Memory
        memory_summary = summarize_relevant_memory(customer_id, incident_type)
        customer_memories = load_customer_memory(customer_id)
        state.memory = customer_memories

        self._record_trace_step(
            trace=trace,
            step_number=0,
            event_type="observation",
            summary="Loaded customer operational memory from database.",
            result={"entries_count": len(customer_memories)},
        )

        # 4. Construct initial messages for LLM
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"DELIVERY INCIDENT REPORT:\n"
                    f"- Incident ID: {incident_id}\n"
                    f"- Order ID: {order_id} (Order Number: {order_number})\n"
                    f"- Customer ID: {customer_id} ({customer_name})\n"
                    f"- Incident Type: {incident_type}\n"
                    f"- Description: {incident_description}\n\n"
                    f"CUSTOMER MEMORY & CONTEXT:\n{memory_summary}\n\n"
                    f"INSTRUCTIONS:\n"
                    f"Investigate the incident with your tools, evaluate available recovery options, "
                    f"execute the appropriate resolution action, verify the result, and provide your final explanation."
                ),
            },
        ]

        tool_schemas = registry.get_openai_tools()

        step_counter = 0
        final_decision_text = ""
        action_executed = False
        mutation_verified = False
        provider_failed = False
        action_name_taken: str | None = None
        proposed_action: dict[str, Any] | None = None
        candidate_actions_list: list[CandidateAction] = []

        # 5. Iterative Agent Loop (Plan-Act-Observe)
        while step_counter < self.max_steps and proposed_action is None:
            step_counter += 1
            state.current_step = step_counter

            logger.info("Agent Step %d / %d (Status: %s)", step_counter, self.max_steps, state.status.value)

            try:
                llm_response: LLMResponse = self.provider.generate(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=0.1,
                )
            except Exception as exc:
                reason = describe_provider_error(exc)
                logger.error("LLM provider failed: %s", exc)
                state.errors.append(f"LLM provider failed: {reason}")
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter,
                    event_type="error",
                    summary=f"LLM provider failed: {reason}",
                    status="error",
                )
                provider_failed = True
                final_decision_text = (
                    f"No action was taken. {reason} Retry, or switch to another provider."
                )
                break

            if llm_response.has_tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": llm_response.content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": json.dumps(tc["function"]["arguments"]),
                            },
                        }
                        for tc in llm_response.tool_calls
                    ],
                })

                for tc in llm_response.tool_calls:
                    tool_name = tc["function"]["name"]
                    arguments = tc["function"]["arguments"]
                    tool_call_id = tc["id"]

                    # Transition state machine appropriately
                    if registry.is_mutation(tool_name):
                        if state.status in {AgentStatus.INVESTIGATING, AgentStatus.EVALUATING}:
                            state.transition_to(AgentStatus.ACTING)
                    elif state.status == AgentStatus.INVESTIGATING:
                        if tool_name in {"get_courier_availability", "find_available_delivery_slots"}:
                            state.transition_to(AgentStatus.EVALUATING)

                    # ── Deterministic Policy Guardrail Check ──
                    policy_violation_msg = (
                        self._policy_violation(tool_name, arguments, order_id)
                        if registry.is_mutation(tool_name) else None
                    )

                    # ── Human approval gate: stop before the first allowed mutation ──
                    if plan_only and registry.is_mutation(tool_name) and not policy_violation_msg:
                        proposal_args = dict(arguments)
                        # The agent may only act on the order this incident belongs to.
                        proposal_args["order_id"] = order_id
                        proposed_action = {"tool_name": tool_name, "arguments": proposal_args}
                        state.transition_to(AgentStatus.AWAITING_APPROVAL)
                        final_decision_text = (llm_response.content or "").strip()
                        self._record_trace_step(
                            trace=trace,
                            step_number=step_counter,
                            event_type="proposal",
                            tool_name=tool_name,
                            summary=f"Proposed {tool_name}; waiting for operator approval.",
                            arguments=proposal_args,
                            status="pending",
                        )
                        break

                    if policy_violation_msg:
                        tool_output = {
                            "success": False,
                            "error": f"Policy Guardrail Blocked: {policy_violation_msg}",
                            "policy_blocked": True,
                        }
                        tool_status = "error"
                        state.errors.append(tool_output["error"])
                    else:
                        try:
                            tool_output = registry.execute(tool_name, arguments)
                            tool_status = "success" if tool_output.get("success", True) else "error"
                        except (ToolNotFoundError, InvalidArgumentsError, ToolExecutionError) as tool_err:
                            tool_output = {"success": False, "error": str(tool_err)}
                            tool_status = "error"
                            state.errors.append(str(tool_err))

                    # Track candidate actions when slots or escalation are evaluated
                    if tool_name == "find_available_delivery_slots" and tool_output.get("success"):
                        for slot_dict in tool_output.get("slots", []):
                            candidate_actions_list.append(
                                CandidateAction(
                                    action=ActionType.RESCHEDULE,
                                    date=slot_dict.get("date"),
                                    start_time=slot_dict.get("start_time"),
                                    end_time=slot_dict.get("end_time"),
                                    courier_id=slot_dict.get("courier_id"),
                                    reason=f"Slot with courier {slot_dict.get('courier_name')} ({slot_dict.get('time_block')})",
                                    score=float(slot_dict.get("score", 0.0)),
                                    feasible=True,
                                )
                            )
                    elif tool_name == "escalate_incident":
                        candidate_actions_list.append(
                            CandidateAction(
                                action=ActionType.ESCALATE,
                                reason=arguments.get("reason", "Escalation initiated"),
                                score=1.0,
                                feasible=True,
                            )
                        )

                    self._record_trace_step(
                        trace=trace,
                        step_number=step_counter,
                        event_type="tool_call",
                        tool_name=tool_name,
                        summary=f"Called {tool_name}",
                        arguments=arguments,
                        result=tool_output,
                        status=tool_status,
                    )

                    # Track mutation execution & verify it against the database
                    if registry.is_mutation(tool_name) and tool_output.get("success", False):
                        action_executed = True
                        action_name_taken = tool_name
                        if tool_name != "escalate_incident":
                            state.transition_to(AgentStatus.VERIFYING)
                        mutation_verified, verify_note = self._verify_mutation(tool_name, arguments, order_id)
                        self._record_trace_step(
                            trace=trace,
                            step_number=step_counter,
                            event_type="verification",
                            tool_name=tool_name,
                            summary=verify_note,
                            result={"verified": mutation_verified, "detail": verify_note},
                            status="success" if mutation_verified else "error",
                        )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(tool_output),
                    })

                    # Escalation hands the order to a person: no further agent actions.
                    if tool_name == "escalate_incident" and tool_output.get("success"):
                        final_decision_text = (llm_response.content or "").strip() or (
                            f"Escalated to human operations: {arguments.get('reason', '')}".strip()
                        )
                        break

                if action_name_taken == "escalate_incident":
                    break
                continue

            else:
                final_decision_text = (llm_response.content or "").strip()
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter,
                    event_type="decision",
                    summary="Final agent decision formulated.",
                    result={"decision": final_decision_text},
                )
                break

        # 6. Post-loop validation and terminal state assignment
        if proposed_action is not None:
            state.finish(AgentStatus.AWAITING_APPROVAL)
            if not final_decision_text:
                final_decision_text = f"Proposed {proposed_action['tool_name']}; waiting for operator approval."
        elif provider_failed:
            state.finish(AgentStatus.FAILED)
        elif step_counter >= self.max_steps and not final_decision_text:
            state.finish(AgentStatus.FAILED)
            final_decision_text = f"Agent stopped: exceeded maximum iteration limit of {self.max_steps} steps without final resolution."
            self._record_trace_step(
                trace=trace,
                step_number=step_counter,
                event_type="error",
                summary="Exceeded max agent steps.",
                status="error",
            )
        elif action_name_taken == "escalate_incident":
            state.finish(AgentStatus.ESCALATED)
        elif action_executed and mutation_verified:
            state.finish(AgentStatus.RESOLVED)
        elif action_executed:
            state.finish(AgentStatus.FAILED)
            final_decision_text = (
                f"The change could not be verified in the database, so this is not marked as resolved. "
                f"{final_decision_text}"
            ).strip()
        elif "escalat" in final_decision_text.lower():
            if plan_only:
                # Escalating also messages the customer, so it goes through approval too.
                proposed_action = {
                    "tool_name": "escalate_incident",
                    "arguments": {"order_id": order_id, "reason": final_decision_text[:300]},
                }
                state.finish(AgentStatus.AWAITING_APPROVAL)
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter,
                    event_type="proposal",
                    tool_name="escalate_incident",
                    summary="Proposed escalate_incident; waiting for operator approval.",
                    arguments=proposed_action["arguments"],
                    status="pending",
                )
            else:
                state.finish(AgentStatus.ESCALATED)
        else:
            state.finish(AgentStatus.FAILED)
            final_decision_text = (
                f"The agent finished without taking a recovery action. {final_decision_text}"
            ).strip()

        # 7. Update Incident record in database
        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == incident_id).first()
            if inc:
                move_incident(inc, IncidentStatus(state.status.value))
                inc.agent_decision = final_decision_text
                db.flush()

        memory_updates: list[str] = []
        notifications_sent: list[dict[str, Any]] = []
        if state.status != AgentStatus.AWAITING_APPROVAL:
            memory_updates, notifications_sent = self._finalize(
                status=state.status, action_name_taken=action_name_taken, customer_id=customer_id,
                order_id=order_id, order_number=order_number, incident_type=incident_type,
                final_decision_text=final_decision_text, trace=trace,
                step_number=step_counter + 1, errors=state.errors,
            )

        logger.info(
            "Agent finished for Incident #%d. Final Status: %s in %d steps.",
            incident_id, state.status.value, step_counter
        )

        return AgentResult(
            incident_id=incident_id,
            order_id=order_id,
            customer_id=customer_id,
            status=state.status.value,
            action_taken=action_name_taken,
            proposed_action=proposed_action,
            decision_summary=final_decision_text,
            trace=trace.events,
            candidate_actions=candidate_actions_list,
            memory_updates=memory_updates,
            notifications=notifications_sent,
            errors=state.errors,
        )

    # ──────────────────────────────────────────
    # Memory and customer notification after a terminal outcome
    # ──────────────────────────────────────────
    def _finalize(
        self,
        status: AgentStatus,
        action_name_taken: str | None,
        customer_id: int,
        order_id: int,
        order_number: str,
        incident_type: str,
        final_decision_text: str,
        trace: AgentTrace,
        step_number: int,
        errors: list[str],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """Persist memory and notify the customer for RESOLVED or ESCALATED outcomes only."""
        memory_updates: list[str] = []
        if status == AgentStatus.RESOLVED and action_name_taken == "reschedule_delivery":
            save_memory(
                customer_id=customer_id,
                memory_type="resolution",
                content=f"Successfully resolved {incident_type} by rescheduling order {order_number}.",
                importance=0.85,
            )
            memory_updates.append(f"Recorded successful rescheduling memory for customer #{customer_id}.")
        elif status == AgentStatus.ESCALATED:
            save_memory(
                customer_id=customer_id,
                memory_type="escalation",
                content=f"Incident {incident_type} for order {order_number} escalated to human ops: {final_decision_text[:100]}",
                importance=0.90,
            )
            memory_updates.append(f"Recorded escalation record in customer #{customer_id} memory.")

        notifications_sent: list[dict[str, Any]] = []
        if status not in {AgentStatus.RESOLVED, AgentStatus.ESCALATED}:
            return memory_updates, notifications_sent
        if status == AgentStatus.RESOLVED and action_name_taken != "reschedule_delivery":
            return memory_updates, notifications_sent

        with get_db() as db:
            cust = db.query(Customer).filter(Customer.id == customer_id).first()
            deliv = db.query(Delivery).filter(Delivery.order_id == order_id).first()
            cust_phone = (cust.phone if cust else "") or ""
            cust_name_notif = cust.name if cust else "Customer"
            sched = (
                (deliv.scheduled_date, deliv.scheduled_start, deliv.scheduled_end) if deliv else (None, None, None)
            )

        if not cust_phone.strip():
            msg = f"No customer notification sent: no phone number on file for {cust_name_notif}."
            errors.append(msg)
            self._record_trace_step(
                trace=trace, step_number=step_number, event_type="notification",
                summary=msg, result={"status": "NOT_SENT", "reason": "missing_phone"}, status="error",
            )
            return memory_updates, notifications_sent

        try:
            if status == AgentStatus.RESOLVED:
                notif = NotificationDispatcher.notify_customer_rescheduled(
                    customer_name=cust_name_notif,
                    phone=cust_phone,
                    order_number=order_number,
                    new_date=str(sched[0] or "Next business day"),
                    start_time=str(sched[1] or "09:00"),
                    end_time=str(sched[2] or "12:00"),
                    channel="whatsapp",
                )
                notif_type = "rescheduled"
            else:
                notif = NotificationDispatcher.notify_customer_escalated(
                    customer_name=cust_name_notif,
                    phone=cust_phone,
                    order_number=order_number,
                    reason=final_decision_text[:200],
                    channel="sms",
                )
                notif_type = "escalated"

            notifications_sent.append({
                "channel": notif.channel,
                "recipient": notif.recipient_name,
                "contact": notif.recipient_contact,
                "type": notif_type,
                "status": notif.status,
                "message_preview": notif.message[:120],
            })
            self._record_trace_step(
                trace=trace,
                step_number=step_number,
                event_type="notification",
                summary=f"{notif.channel.upper()} {notif_type} message sent to {cust_name_notif} ({cust_phone})",
                result={
                    "channel": notif.channel,
                    "type": notif_type,
                    "status": notif.status,
                    "recipient": cust_name_notif,
                    "contact": cust_phone,
                    "message": notif.message,
                },
            )
            memory_updates.append(f"{notif.channel.upper()} notification dispatched to {cust_name_notif}.")
        except Exception as notif_err:
            logger.warning("Notification dispatch failed: %s", notif_err)
            errors.append(f"Notification dispatch failed: {notif_err}")

        return memory_updates, notifications_sent
