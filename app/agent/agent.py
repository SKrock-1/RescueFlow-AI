"""
RescueFlow AI — Core Agent Runner.

Implements the explicit, multi-step Plan-Act-Observe iterative agent loop
without external heavyweight agent frameworks.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import get_settings
from app.errors import (
    RescueFlowError,
    ToolNotFoundError,
    InvalidArgumentsError,
    ToolExecutionError,
    AgentMaxStepsError,
    EscalationRequired,
)
from app.database.engine import get_db
from app.database.models import Incident, Order, Customer, Delivery, Courier
from app.agent.state import AgentState, AgentStatus
from app.agent.prompts import AGENT_SYSTEM_PROMPT
from app.agent.memory import (
    load_customer_memory,
    save_memory,
    summarize_relevant_memory,
)
from app.agent.trace import AgentTrace
from app.agent.observer import AgentObserver
from app.providers.base import LLMProvider, LLMResponse
from app.providers.factory import create_provider
from app.services.policy import PolicyEngine
from app.services.notifications import NotificationDispatcher
from app.tools.registry import registry
from app.schemas.models import AgentResult, CandidateAction, ActionType

logger = logging.getLogger(__name__)


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

    def resolve_incident(self, incident_id: int) -> AgentResult:
        """Execute the end-to-end autonomous resolution loop for an incident."""
        logger.info("Starting resolution for Incident #%d", incident_id)

        # 1. Fetch initial incident, order, and customer from DB
        with get_db() as db:
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if not incident:
                raise ValueError(f"Incident {incident_id} not found in database.")

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

        # Get available tool schemas from registry
        tool_schemas = registry.get_openai_tools()

        step_counter = 0
        final_decision_text = ""
        action_executed = False
        mutation_verified = False
        action_name_taken: str | None = None
        candidate_actions_list: list[CandidateAction] = []

        # 5. Iterative Agent Loop (Plan-Act-Observe)
        while step_counter < self.max_steps:
            step_counter += 1
            state.current_step = step_counter

            logger.info("Agent Step %d / %d (Status: %s)", step_counter, self.max_steps, state.status.value)

            try:
                # Call LLM Provider
                llm_response: LLMResponse = self.provider.generate(
                    messages=messages,
                    tools=tool_schemas,
                    temperature=0.1,
                )
            except Exception as exc:
                err_msg = f"LLM provider failed: {exc}"
                logger.error(err_msg)
                state.errors.append(err_msg)
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter,
                    event_type="error",
                    summary=err_msg,
                    status="error",
                )
                # Fallback to escalation
                state.transition_to(AgentStatus.ESCALATED)
                final_decision_text = f"Automated resolution aborted due to AI provider error: {exc}. Escalated."
                break

            # If LLM returned tool calls:
            if llm_response.has_tool_calls:
                # Append assistant message with tool calls
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
                    if tool_name == "escalate_incident":
                        state.transition_to(AgentStatus.ESCALATED)
                    elif registry.is_mutation(tool_name):
                        if state.status in {AgentStatus.INVESTIGATING, AgentStatus.EVALUATING}:
                            state.transition_to(AgentStatus.ACTING)
                    elif state.status == AgentStatus.INVESTIGATING:
                        if tool_name in {"get_courier_availability", "find_available_delivery_slots"}:
                            state.transition_to(AgentStatus.EVALUATING)

                    # ── Deterministic Policy Guardrail Check ──
                    policy_violation_msg: str | None = None
                    if tool_name == "reschedule_delivery":
                        target_order_id = arguments.get("order_id", order_id)
                        with get_db() as db:
                            deliv = db.query(Delivery).filter(Delivery.order_id == target_order_id).first()
                            if deliv:
                                rule_res = PolicyEngine.rule_repeated_failure_escalation(deliv.attempt_count)
                                if not rule_res.passed:
                                    policy_violation_msg = rule_res.message
                    elif tool_name == "reassign_courier":
                        target_courier_id = arguments.get("courier_id")
                        if target_courier_id:
                            with get_db() as db:
                                cour = db.query(Courier).filter(Courier.id == target_courier_id).first()
                                if cour:
                                    rule_res = PolicyEngine.rule_courier_active(cour.status)
                                    if not rule_res.passed:
                                        policy_violation_msg = rule_res.message

                    if policy_violation_msg:
                        tool_output = {
                            "success": False,
                            "error": f"Policy Guardrail Blocked: {policy_violation_msg}",
                            "policy_blocked": True,
                        }
                        tool_status = "error"
                        state.errors.append(tool_output["error"])
                    else:
                        # Execute the tool safely via registry
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

                    # Track mutation execution & verification
                    if registry.is_mutation(tool_name) and tool_output.get("success", False):
                        action_executed = True
                        action_name_taken = tool_name
                        if tool_name != "escalate_incident":
                            state.transition_to(AgentStatus.VERIFYING)
                        mutation_verified = True

                    # Record in trace & notify observers
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

                    # Append tool result to conversation history
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(tool_output),
                    })

                # Loop continues to feed tool results back to LLM
                continue

            else:
                # LLM returned pure text without tool calls -> Final Decision reached
                final_decision_text = llm_response.content.strip()
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter,
                    event_type="decision",
                    summary="Final agent decision formulated.",
                    result={"decision": final_decision_text},
                )
                break

        # 6. Post-loop validation and terminal state assignment
        if step_counter >= self.max_steps and not final_decision_text:
            state.transition_to(AgentStatus.FAILED)
            final_decision_text = f"Agent stopped: exceeded maximum iteration limit of {self.max_steps} steps without final resolution."
            self._record_trace_step(
                trace=trace,
                step_number=step_counter,
                event_type="error",
                summary="Exceeded max agent steps.",
                status="error",
            )
        elif action_name_taken == "escalate_incident":
            state.status = AgentStatus.ESCALATED
        elif action_executed and mutation_verified:
            state.status = AgentStatus.RESOLVED
        elif "escalat" in final_decision_text.lower():
            state.status = AgentStatus.ESCALATED
        elif not action_executed and state.status not in {AgentStatus.ESCALATED, AgentStatus.FAILED}:
            state.status = AgentStatus.RESOLVED

        # 7. Update Incident record in database
        with get_db() as db:
            inc = db.query(Incident).filter(Incident.id == incident_id).first()
            if inc:
                inc.status = state.status.value
                inc.agent_decision = final_decision_text
                db.flush()

        # 8. Persist memory updates if successfully resolved or escalated
        memory_updates: list[str] = []
        if state.status == AgentStatus.RESOLVED and action_name_taken == "reschedule_delivery":
            saved = save_memory(
                customer_id=customer_id,
                memory_type="resolution",
                content=f"Successfully resolved {incident_type} by rescheduling order {order_number}.",
                importance=0.85,
            )
            memory_updates.append(f"Recorded successful rescheduling memory for customer #{customer_id}.")
        elif state.status == AgentStatus.ESCALATED:
            saved = save_memory(
                customer_id=customer_id,
                memory_type="escalation",
                content=f"Incident {incident_type} for order {order_number} escalated to human ops: {final_decision_text[:100]}",
                importance=0.90,
            )
            memory_updates.append(f"Recorded escalation record in customer #{customer_id} memory.")

        # 9. Dispatch real-world customer notifications
        notifications_sent: list[dict[str, Any]] = []
        with get_db() as db:
            cust = db.query(Customer).filter(Customer.id == customer_id).first()
            deliv = db.query(Delivery).filter(Delivery.order_id == order_id).first()
            cust_phone = cust.phone if cust else "N/A"
            cust_name_notif = cust.name if cust else "Customer"

        try:
            if state.status == AgentStatus.RESOLVED and action_name_taken == "reschedule_delivery":
                sched_date = deliv.scheduled_date if deliv else "Next business day"
                sched_start = deliv.scheduled_start if deliv else "09:00"
                sched_end = deliv.scheduled_end if deliv else "12:00"
                notif = NotificationDispatcher.notify_customer_rescheduled(
                    customer_name=cust_name_notif,
                    phone=cust_phone,
                    order_number=order_number,
                    new_date=str(sched_date),
                    start_time=str(sched_start),
                    end_time=str(sched_end),
                    channel="whatsapp",
                )
                notifications_sent.append({
                    "channel": notif.channel,
                    "recipient": notif.recipient_name,
                    "contact": notif.recipient_contact,
                    "type": "rescheduled",
                    "status": notif.status,
                    "message_preview": notif.message[:120],
                })
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter + 1,
                    event_type="notification",
                    summary=f"WhatsApp notification sent to {cust_name_notif} ({cust_phone})",
                    result={"channel": "whatsapp", "status": "SENT"},
                )
                memory_updates.append(f"WhatsApp notification dispatched to {cust_name_notif}.")

            elif state.status == AgentStatus.ESCALATED:
                notif = NotificationDispatcher.notify_customer_escalated(
                    customer_name=cust_name_notif,
                    phone=cust_phone,
                    order_number=order_number,
                    reason=final_decision_text[:200],
                    channel="sms",
                )
                notifications_sent.append({
                    "channel": notif.channel,
                    "recipient": notif.recipient_name,
                    "contact": notif.recipient_contact,
                    "type": "escalated",
                    "status": notif.status,
                    "message_preview": notif.message[:120],
                })
                self._record_trace_step(
                    trace=trace,
                    step_number=step_counter + 1,
                    event_type="notification",
                    summary=f"SMS escalation alert sent to {cust_name_notif} ({cust_phone})",
                    result={"channel": "sms", "status": "SENT"},
                )
                memory_updates.append(f"SMS escalation notification dispatched to {cust_name_notif}.")
        except Exception as notif_err:
            logger.warning("Notification dispatch failed: %s", notif_err)
            state.errors.append(f"Notification dispatch failed: {notif_err}")

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
            decision_summary=final_decision_text,
            trace=trace.events,
            candidate_actions=candidate_actions_list,
            memory_updates=memory_updates,
            notifications=notifications_sent,
            errors=state.errors,
        )
