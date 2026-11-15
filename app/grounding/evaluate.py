"""
RescueFlow AI — Retrieval evaluation: ``python -m app.grounding.evaluate``.

Measures how often the right policy section is in the top 5 results
(recall@5) and how high it ranks (mean reciprocal rank) for questions an
agent would ask, worded differently from the policy headings.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.grounding.knowledge import search_knowledge

LABELED_QUERIES: list[tuple[str, str]] = [
    ("courier rang the bell but nobody was home", "ndr-handling#customer-unavailable"),
    ("customer did not pick up the phone at the door", "ndr-handling#customer-unavailable"),
    ("the house number on the label does not exist", "ndr-handling#address-issue"),
    ("buyer said they do not want the package anymore", "ndr-handling#customer-refused"),
    ("cod buyer had no cash when the rider came", "ndr-handling#cash-on-delivery-payment-issue"),
    ("customer replied please come tomorrow after 3pm", "ndr-handling#customer-request"),
    ("this is the third time delivery failed, can we try again", "reattempt-policy#attempt-limit"),
    ("which time slot should we pick for the next try", "reattempt-policy#choosing-a-slot"),
    ("can we send the courier again later the same day", "reattempt-policy#spacing-between-attempts"),
    ("is it fine to give the parcel to a different rider", "reattempt-policy#courier-changes"),
    ("delivery to a tech park tower in the evening", "office-delivery#business-hours-only"),
    ("leave the parcel with the security guard at the office", "office-delivery#reception-and-security"),
    ("high value loyal customer missed their delivery", "vip-handling#priority-handling"),
    ("when must a person take over the case", "escalation-matrix#when-to-escalate"),
    ("what should the escalation note include", "escalation-matrix#what-an-escalation-must-contain"),
    ("can we whatsapp the customer at 11 pm", "customer-communication#quiet-hours"),
    ("what to write in the reschedule message", "customer-communication#content-of-a-reschedule-message"),
    ("how long does the carrier keep the parcel before returning it", "carrier-sla#reattempt-windows"),
    ("when should we send the order back to the warehouse", "carrier-sla#return-to-origin"),
    ("no phone number saved for the buyer, should we text them", "customer-communication#channel"),
]


@dataclass
class EvalResult:
    recall_at_5: float
    mrr: float
    misses: list[tuple[str, str, list[str]]]
    total: int


def evaluate_retrieval(k: int = 5) -> EvalResult:
    hits_at_k, reciprocal, misses = 0, 0.0, []
    for query, expected in LABELED_QUERIES:
        ids = [h.id for h in search_knowledge(query, k=k)]
        if expected in ids:
            hits_at_k += 1
            reciprocal += 1.0 / (ids.index(expected) + 1)
        else:
            misses.append((query, expected, ids))
    n = len(LABELED_QUERIES)
    return EvalResult(recall_at_5=hits_at_k / n, mrr=reciprocal / n, misses=misses, total=n)


def main() -> None:
    from app.database.engine import init_db

    init_db()
    result = evaluate_retrieval()
    print(f"Policy retrieval over {result.total} labeled questions")
    print(f"  recall@5: {result.recall_at_5:.0%}")
    print(f"  MRR:      {result.mrr:.2f}")
    for query, expected, got in result.misses:
        print(f"  miss: {query!r} expected {expected}, got {got}")


if __name__ == "__main__":
    main()
