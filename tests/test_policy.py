"""
RescueFlow AI — Policy Engine Unit Tests.

Unit tests for all 8 deterministic business policy rules.
"""

from datetime import time
from app.services.policy import PolicyEngine


def test_rule_1_prefer_customer_preference():
    engine = PolicyEngine()
    # Preferred is available, but proposed slot differs
    res1 = engine.rule_prefer_customer_preference(
        proposed_time_block="afternoon",
        customer_preference="morning",
        preferred_slot_available=True,
    )
    assert res1.passed is False

    # Preferred is morning and proposed is morning
    res2 = engine.rule_prefer_customer_preference(
        proposed_time_block="morning",
        customer_preference="morning",
        preferred_slot_available=True,
    )
    assert res2.passed is True


def test_rule_2_next_best_slot():
    engine = PolicyEngine()
    # Neither available
    res1 = engine.rule_next_best_slot(preferred_slot_available=False, alternative_slot_available=False)
    assert res1.passed is False

    # Alternative is available
    res2 = engine.rule_next_best_slot(preferred_slot_available=False, alternative_slot_available=True)
    assert res2.passed is True


def test_rule_3_courier_reassignment():
    engine = PolicyEngine()
    res1 = engine.rule_courier_reassignment(current_courier_available=False, alternative_courier_available=False)
    assert res1.passed is False

    res2 = engine.rule_courier_reassignment(current_courier_available=False, alternative_courier_available=True)
    assert res2.passed is True


def test_rule_4_repeated_failure_escalation():
    engine = PolicyEngine()
    res1 = engine.rule_repeated_failure_escalation(attempt_count=3, escalation_threshold=3)
    assert res1.passed is False  # Escalation required!

    res2 = engine.rule_repeated_failure_escalation(attempt_count=1, escalation_threshold=3)
    assert res2.passed is True


def test_rule_5_no_valid_solution():
    engine = PolicyEngine()
    res1 = engine.rule_no_valid_solution(has_feasible_option=False)
    assert res1.passed is False  # Must escalate

    res2 = engine.rule_no_valid_solution(has_feasible_option=True)
    assert res2.passed is True


def test_rule_6_courier_hours():
    engine = PolicyEngine()
    # Proposed slot outside availability
    res1 = engine.rule_courier_hours(
        proposed_start=time(7, 0),
        proposed_end=time(9, 0),
        courier_available_from=time(8, 0),
        courier_available_until=time(17, 0),
    )
    assert res1.passed is False

    # Proposed slot within availability
    res2 = engine.rule_courier_hours(
        proposed_start=time(9, 0),
        proposed_end=time(12, 0),
        courier_available_from=time(8, 0),
        courier_available_until=time(17, 0),
    )
    assert res2.passed is True


def test_rule_7_courier_active():
    engine = PolicyEngine()
    res1 = engine.rule_courier_active("inactive")
    assert res1.passed is False

    res2 = engine.rule_courier_active("on_break")
    assert res2.passed is False

    res3 = engine.rule_courier_active("active")
    assert res3.passed is True


def test_rule_8_verified_resolution():
    engine = PolicyEngine()
    res1 = engine.rule_verified_resolution(action_executed=True, verification_done=False)
    assert res1.passed is False

    res2 = engine.rule_verified_resolution(action_executed=True, verification_done=True)
    assert res2.passed is True
