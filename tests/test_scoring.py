"""
RescueFlow AI — Scoring Engine Unit Tests.

Tests deterministic scoring formulas, weights, and ranking.
"""

from app.services.scoring import score_option, rank_options, best_feasible_option, DEFAULT_WEIGHTS


def test_scoring_preferred_slot_ranks_higher():
    preferred = score_option(
        action="RESCHEDULE",
        matches_preference=True,
        slot_available=True,
        courier_available=True,
        sla_hours_remaining=24.0,
        estimated_delay_hours=2.0,
        previous_attempt_count=0,
    )

    non_preferred = score_option(
        action="RESCHEDULE",
        matches_preference=False,
        slot_available=True,
        courier_available=True,
        sla_hours_remaining=24.0,
        estimated_delay_hours=2.0,
        previous_attempt_count=0,
    )

    assert preferred.total_score > non_preferred.total_score
    assert preferred.breakdown["customer_preference"] > non_preferred.breakdown["customer_preference"]


def test_scoring_unavailable_is_infeasible():
    unavailable = score_option(
        action="RESCHEDULE",
        matches_preference=True,
        slot_available=False,
        courier_available=True,
        sla_hours_remaining=24.0,
        estimated_delay_hours=2.0,
        previous_attempt_count=0,
    )

    assert unavailable.feasible is False
    assert unavailable.availability_score == 0.0


def test_scoring_repeated_failures_lowers_score():
    no_failure = score_option(
        action="RESCHEDULE",
        matches_preference=True,
        slot_available=True,
        courier_available=True,
        sla_hours_remaining=24.0,
        estimated_delay_hours=2.0,
        previous_attempt_count=0,
    )

    three_failures = score_option(
        action="RESCHEDULE",
        matches_preference=True,
        slot_available=True,
        courier_available=True,
        sla_hours_remaining=24.0,
        estimated_delay_hours=2.0,
        previous_attempt_count=3,
    )

    assert no_failure.total_score > three_failures.total_score
    assert three_failures.history_score == 0.1


def test_rank_options_feasible_first():
    opt_infeasible_high = score_option(
        action="RESCHEDULE",
        matches_preference=True,
        slot_available=False,
        courier_available=False,
        sla_hours_remaining=48.0,
        estimated_delay_hours=0.0,
        previous_attempt_count=0,
    )
    opt_feasible_low = score_option(
        action="RESCHEDULE",
        matches_preference=False,
        slot_available=True,
        courier_available=True,
        sla_hours_remaining=2.0,
        estimated_delay_hours=10.0,
        previous_attempt_count=2,
    )

    ranked = rank_options([opt_infeasible_high, opt_feasible_low])
    assert ranked[0].feasible is True
    assert ranked[0] == opt_feasible_low


def test_best_feasible_option():
    opt1 = score_option("RESCHEDULE", False, True, True, 20.0, 5.0, 0)
    opt2 = score_option("RESCHEDULE", True, True, True, 20.0, 2.0, 0)
    opt3 = score_option("RESCHEDULE", True, False, True, 20.0, 2.0, 0)  # infeasible

    best = best_feasible_option([opt1, opt2, opt3])
    assert best == opt2
