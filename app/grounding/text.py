"""RescueFlow AI — Text helpers shared by embeddings and keyword search."""

from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    "a an and are as at be been but by can do does for from has have he her his how i if in into is it its "
    "may me must my no not of on or our she so than that the their them then there these they this to too "
    "up us was we were what when where which who will with you your".split()
)


# Delivery-domain thesaurus: phrases that mean the same thing map to one concept
# token, added next to the original words. Keyword and vector search both use it,
# so "customer not home" finds the "Customer unavailable" procedure.
CONCEPTS: dict[str, tuple[str, ...]] = {
    "concept_unavailable": ("unavailable", "not home", "not at home", "unreachable", "no answer",
                            "did not answer", "absent", "missed", "away", "not available"),
    "concept_refused": ("refused", "refuse", "refusal", "rejected the parcel", "declined", "do not want",
                        "not want", "dont want", "no longer wants", "cancel the order"),
    "concept_cod": ("cash on delivery", "cod", "cash", "payment", "pay at the door", "unpaid"),
    "concept_commercial": ("office", "commercial", "tech park", "tower", "business", "reception", "workplace"),
    "concept_vip": ("vip", "repeat buyer", "repeat customer", "loyal", "high value", "lifetime spend"),
    "concept_escalate": ("escalate", "escalation", "escalated", "hand over", "operations", "person"),
    "concept_attempt": ("attempt", "reattempt", "retry", "retries", "failed delivery", "ndr"),
    "concept_address": ("address", "location", "landmark", "wrong address", "incomplete address", "gate",
                        "house number", "flat number", "street", "pin code", "pincode", "does not exist"),
    "concept_message": ("message", "whatsapp", "sms", "notify", "notification", "contact the customer"),
    "concept_rto": ("rto", "return to origin", "return"),
    "concept_slot": ("slot", "window", "time", "reschedule", "rescheduled", "morning", "afternoon", "evening"),
    "concept_request": ("customer replied", "asked for", "requested", "request", "prefers", "preferred"),
    "concept_quiet": ("quiet hours", "night", "late at night", "midnight", "early morning", "21 00", "08 00",
                      "9 pm", "10 pm", "11 pm", "12 am", "1 am", "2 am", "5 am", "6 am", "7 am"),
    "concept_courier": ("courier", "rider", "driver", "delivery boy", "delivery partner", "agent on the bike"),
}


def _fold(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens without stopwords, plus domain concept tokens."""
    lowered = (text or "").lower()
    tokens = [_fold(t) for t in _TOKEN.findall(lowered) if t not in STOPWORDS and len(t) >= 2]
    padded = f" {' '.join(_TOKEN.findall(lowered))} "
    for concept, phrases in CONCEPTS.items():
        if any(f" {p} " in padded for p in phrases):
            tokens.append(concept)
    return tokens


def slugify(text: str) -> str:
    return "-".join(_TOKEN.findall((text or "").lower())) or "section"
