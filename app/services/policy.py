"""
RescueFlow AI — Business Rule / Policy Engine.

Deterministic rules that constrain the agent's recovery actions.
Each rule is a pure function returning (passed: bool, message: str)
so it is independently unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any


@dataclass
class PolicyResult:
    """Result of evaluating a single policy rule."""
    rule_name: str
    passed: bool
    message: str


class PolicyEngine:
    """
    Evaluates business rules against a proposed recovery action.

    Usage:
        engine = PolicyEngine()
        results = engine.evaluate_all(action_context)
        violations = [r for r in results if not r.passed]
    """

    # ──────────────────────────────────────────
    # Rule 1: Prefer customer preference slot
    # ──────────────────────────────────────────
    @staticmethod
    def rule_prefer_customer_preference(
        proposed_time_block: str,  # "morning" / "afternoon" / "evening"
        customer_preference: str | None,
        preferred_slot_available: bool,
    ) -> PolicyResult:
        """If a slot matching customer preference exists, prefer it."""
        if customer_preference and preferred_slot_available and proposed_time_block != customer_preference:
            return PolicyResult(
                rule_name="prefer_customer_preference",
                passed=False,
                message=f"Customer prefers '{customer_preference}' and a matching slot is available, "
                        f"but proposed slot is '{proposed_time_block}'.",
            )
        return PolicyResult(
            rule_name="prefer_customer_preference",
            passed=True,
            message="Customer preference respected or no preferred slot available.",
        )

    # ──────────────────────────────────────────
    # Rule 2: Accept next-best slot if preferred unavailable
    # ──────────────────────────────────────────
    @staticmethod
    def rule_next_best_slot(
        preferred_slot_available: bool,
        alternative_slot_available: bool,
    ) -> PolicyResult:
        """If preferred unavailable, an alternative must exist."""
        if not preferred_slot_available and not alternative_slot_available:
            return PolicyResult(
                rule_name="next_best_slot",
                passed=False,
                message="No preferred or alternative delivery slot is available.",
            )
        return PolicyResult(
            rule_name="next_best_slot",
            passed=True,
            message="A delivery slot (preferred or alternative) is available.",
        )

    # ──────────────────────────────────────────
    # Rule 3: Reassign courier when necessary
    # ──────────────────────────────────────────
    @staticmethod
    def rule_courier_reassignment(
        current_courier_available: bool,
        alternative_courier_available: bool,
    ) -> PolicyResult:
        """If the current courier is unavailable, an alternative must be found."""
        if not current_courier_available and not alternative_courier_available:
            return PolicyResult(
                rule_name="courier_reassignment",
                passed=False,
                message="Current courier unavailable and no alternative courier found.",
            )
        return PolicyResult(
            rule_name="courier_reassignment",
            passed=True,
            message="Courier availability confirmed.",
        )

    # ──────────────────────────────────────────
    # Rule 4: Escalate on repeated failures
    # ──────────────────────────────────────────
    @staticmethod
    def rule_repeated_failure_escalation(
        attempt_count: int,
        escalation_threshold: int = 3,
    ) -> PolicyResult:
        """If multiple attempts have failed, escalation priority must increase."""
        if attempt_count >= escalation_threshold:
            return PolicyResult(
                rule_name="repeated_failure_escalation",
                passed=False,
                message=f"Delivery has failed {attempt_count} times (threshold={escalation_threshold}). "
                        f"Escalation is required.",
            )
        return PolicyResult(
            rule_name="repeated_failure_escalation",
            passed=True,
            message=f"Attempt count ({attempt_count}) is below escalation threshold.",
        )

    # ──────────────────────────────────────────
    # Rule 5: Escalate when no valid solution
    # ──────────────────────────────────────────
    @staticmethod
    def rule_no_valid_solution(
        has_feasible_option: bool,
    ) -> PolicyResult:
        """If no valid delivery solution exists, escalate."""
        if not has_feasible_option:
            return PolicyResult(
                rule_name="no_valid_solution",
                passed=False,
                message="No feasible delivery option exists. Must escalate.",
            )
        return PolicyResult(
            rule_name="no_valid_solution",
            passed=True,
            message="At least one feasible delivery option exists.",
        )

    # ──────────────────────────────────────────
    # Rule 6: No scheduling outside courier hours
    # ──────────────────────────────────────────
    @staticmethod
    def rule_courier_hours(
        proposed_start: time,
        proposed_end: time,
        courier_available_from: time,
        courier_available_until: time,
    ) -> PolicyResult:
        """Never schedule outside the courier's availability window."""
        if proposed_start < courier_available_from or proposed_end > courier_available_until:
            return PolicyResult(
                rule_name="courier_hours",
                passed=False,
                message=f"Proposed slot {proposed_start}-{proposed_end} falls outside "
                        f"courier availability {courier_available_from}-{courier_available_until}.",
            )
        return PolicyResult(
            rule_name="courier_hours",
            passed=True,
            message="Proposed slot is within courier availability.",
        )

    # ──────────────────────────────────────────
    # Rule 7: Never schedule inactive courier
    # ──────────────────────────────────────────
    @staticmethod
    def rule_courier_active(
        courier_status: str,
    ) -> PolicyResult:
        """Never assign a delivery to an inactive courier."""
        if courier_status != "active":
            return PolicyResult(
                rule_name="courier_active",
                passed=False,
                message=f"Courier status is '{courier_status}'. Only 'active' couriers can be assigned.",
            )
        return PolicyResult(
            rule_name="courier_active",
            passed=True,
            message="Courier is active.",
        )

    # ──────────────────────────────────────────
    # Rule 8: Never claim resolution before verification
    # ──────────────────────────────────────────
    @staticmethod
    def rule_verified_resolution(
        action_executed: bool,
        verification_done: bool,
    ) -> PolicyResult:
        """Resolution must be verified by re-checking state after mutation."""
        if action_executed and not verification_done:
            return PolicyResult(
                rule_name="verified_resolution",
                passed=False,
                message="Action was executed but not verified. Must confirm state change.",
            )
        return PolicyResult(
            rule_name="verified_resolution",
            passed=True,
            message="Resolution properly verified.",
        )

    # ──────────────────────────────────────────
    # Convenience: evaluate all applicable rules
    # ──────────────────────────────────────────
    def evaluate_all(self, context: dict[str, Any]) -> list[PolicyResult]:
        """
        Evaluate all applicable rules given an action context dict.

        Expected context keys (all optional — rules are skipped if data missing):
            proposed_time_block, customer_preference, preferred_slot_available,
            alternative_slot_available, current_courier_available,
            alternative_courier_available, attempt_count, has_feasible_option,
            proposed_start, proposed_end, courier_available_from,
            courier_available_until, courier_status, action_executed,
            verification_done
        """
        results: list[PolicyResult] = []

        # Rule 1
        if "proposed_time_block" in context:
            results.append(self.rule_prefer_customer_preference(
                context["proposed_time_block"],
                context.get("customer_preference"),
                context.get("preferred_slot_available", False),
            ))

        # Rule 2
        if "preferred_slot_available" in context:
            results.append(self.rule_next_best_slot(
                context["preferred_slot_available"],
                context.get("alternative_slot_available", False),
            ))

        # Rule 3
        if "current_courier_available" in context:
            results.append(self.rule_courier_reassignment(
                context["current_courier_available"],
                context.get("alternative_courier_available", False),
            ))

        # Rule 4
        if "attempt_count" in context:
            results.append(self.rule_repeated_failure_escalation(
                context["attempt_count"],
                context.get("escalation_threshold", 3),
            ))

        # Rule 5
        if "has_feasible_option" in context:
            results.append(self.rule_no_valid_solution(
                context["has_feasible_option"],
            ))

        # Rule 6
        if "proposed_start" in context and "courier_available_from" in context:
            results.append(self.rule_courier_hours(
                context["proposed_start"],
                context["proposed_end"],
                context["courier_available_from"],
                context["courier_available_until"],
            ))

        # Rule 7
        if "courier_status" in context:
            results.append(self.rule_courier_active(
                context["courier_status"],
            ))

        # Rule 8
        if "action_executed" in context:
            results.append(self.rule_verified_resolution(
                context["action_executed"],
                context.get("verification_done", False),
            ))

        return results

    def get_violations(self, context: dict[str, Any]) -> list[PolicyResult]:
        """Return only the rules that failed."""
        return [r for r in self.evaluate_all(context) if not r.passed]
