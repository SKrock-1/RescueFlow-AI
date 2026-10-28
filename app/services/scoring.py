"""
RescueFlow AI — Deterministic Scoring Engine.

Scores candidate recovery options using configurable weights.
The LLM interprets context; Python calculates objective scores.
This makes the system a hybrid AI + deterministic decision engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ────────────────────────────────────────────
# Default Weights (configurable)
# ────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "customer_preference": 0.30,
    "availability": 0.25,
    "sla": 0.20,
    "delay": 0.15,
    "history": 0.10,
}


@dataclass
class ScoredOption:
    """A recovery option with its computed score breakdown."""

    action: str  # RESCHEDULE / REASSIGN_COURIER / ESCALATE / …
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    courier_id: int | None = None
    reason: str = ""

    # Score factors (0.0 – 1.0 each)
    preference_score: float = 0.0
    availability_score: float = 0.0
    sla_score: float = 0.0
    delay_score: float = 0.0
    history_score: float = 0.0

    # Computed
    total_score: float = 0.0
    feasible: bool = True
    breakdown: dict[str, float] = field(default_factory=dict)


def score_option(
    action: str,
    matches_preference: bool,
    slot_available: bool,
    courier_available: bool,
    sla_hours_remaining: float,
    estimated_delay_hours: float,
    previous_attempt_count: int,
    date: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    courier_id: int | None = None,
    reason: str = "",
    weights: dict[str, float] | None = None,
) -> ScoredOption:
    """
    Score a single recovery option deterministically.

    Args:
        action: The recovery action type.
        matches_preference: Whether the slot matches customer preference.
        slot_available: Whether the proposed slot is actually available.
        courier_available: Whether a courier is available for the slot.
        sla_hours_remaining: Hours until SLA breach.
        estimated_delay_hours: Estimated additional delay in hours.
        previous_attempt_count: Number of prior failed attempts.
        date: Proposed date string.
        start_time: Proposed start time string.
        end_time: Proposed end time string.
        courier_id: Proposed courier ID.
        reason: Human-readable reason for this option.
        weights: Override default weights.

    Returns:
        ScoredOption with computed total_score.
    """
    w = weights or DEFAULT_WEIGHTS

    opt = ScoredOption(
        action=action,
        date=date,
        start_time=start_time,
        end_time=end_time,
        courier_id=courier_id,
        reason=reason,
    )

    # ── Factor 1: Customer preference (binary) ──
    opt.preference_score = 1.0 if matches_preference else 0.3

    # ── Factor 2: Availability (binary) ──
    if not slot_available or not courier_available:
        opt.availability_score = 0.0
        opt.feasible = False
    else:
        opt.availability_score = 1.0

    # ── Factor 3: SLA impact ──
    if sla_hours_remaining <= 0:
        opt.sla_score = 0.0
    elif sla_hours_remaining <= 4:
        opt.sla_score = 0.3
    elif sla_hours_remaining <= 12:
        opt.sla_score = 0.6
    elif sla_hours_remaining <= 24:
        opt.sla_score = 0.8
    else:
        opt.sla_score = 1.0

    # ── Factor 4: Delay (lower is better) ──
    if estimated_delay_hours <= 2:
        opt.delay_score = 1.0
    elif estimated_delay_hours <= 6:
        opt.delay_score = 0.7
    elif estimated_delay_hours <= 12:
        opt.delay_score = 0.5
    elif estimated_delay_hours <= 24:
        opt.delay_score = 0.3
    else:
        opt.delay_score = 0.1

    # ── Factor 5: History (more failures → lower score) ──
    if previous_attempt_count == 0:
        opt.history_score = 1.0
    elif previous_attempt_count == 1:
        opt.history_score = 0.7
    elif previous_attempt_count == 2:
        opt.history_score = 0.4
    else:
        opt.history_score = 0.1  # 3+ failures

    # ── Weighted total ──
    opt.total_score = round(
        w["customer_preference"] * opt.preference_score
        + w["availability"] * opt.availability_score
        + w["sla"] * opt.sla_score
        + w["delay"] * opt.delay_score
        + w["history"] * opt.history_score,
        4,
    )

    opt.breakdown = {
        "customer_preference": round(w["customer_preference"] * opt.preference_score, 4),
        "availability": round(w["availability"] * opt.availability_score, 4),
        "sla": round(w["sla"] * opt.sla_score, 4),
        "delay": round(w["delay"] * opt.delay_score, 4),
        "history": round(w["history"] * opt.history_score, 4),
    }

    return opt


def rank_options(options: list[ScoredOption]) -> list[ScoredOption]:
    """Return options sorted by total_score descending, feasible first."""
    return sorted(
        options,
        key=lambda o: (o.feasible, o.total_score),
        reverse=True,
    )


def best_feasible_option(options: list[ScoredOption]) -> ScoredOption | None:
    """Return the highest-scoring feasible option, or None."""
    ranked = rank_options(options)
    for opt in ranked:
        if opt.feasible:
            return opt
    return None
