"""
RescueFlow AI — Command-Line Interface (CLI).

Provides interactive terminal execution, incident inspection,
and batch operational runs with real-time telemetry.

Usage:
    python -m app.cli list
    python -m app.cli run <incident_id>
    python -m app.cli seed
    python -m app.cli stats
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.database.engine import get_db, init_db
from app.database.models import Incident, Order, Customer, AgentRun
from app.database.seed import seed_all
from app.agent.agent import AgentRunner
from app.agent.observer import ConsoleProgressObserver
from app.providers.factory import create_provider


def cmd_list_incidents(args: argparse.Namespace) -> None:
    """List all incidents in the database."""
    with get_db() as db:
        incidents = (
            db.query(Incident, Order, Customer)
            .join(Order, Incident.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .order_by(Incident.id.asc())
            .all()
        )

        if not incidents:
            print("No incidents found. Run 'python -m app.cli seed' to populate test data.")
            return

        print("\n" + "=" * 92)
        print(f"{'ID':<4} | {'Order':<10} | {'Customer':<18} | {'Type':<22} | {'Severity':<8} | {'Status':<12}")
        print("-" * 92)

        for inc, ord_, cust in incidents:
            status_color = (
                "\033[92m" if inc.status == "RESOLVED"
                else "\033[93m" if inc.status == "OPEN"
                else "\033[95m" if inc.status == "ESCALATED"
                else "\033[0m"
            )
            reset = "\033[0m"
            print(
                f"{inc.id:<4} | {ord_.order_number:<10} | {cust.name[:18]:<18} | "
                f"{inc.incident_type[:22]:<22} | {inc.severity:<8} | {status_color}{inc.status:<12}{reset}"
            )
        print("=" * 92 + "\n")


def cmd_run_incident(args: argparse.Namespace) -> None:
    """Run autonomous resolution agent on a specific incident."""
    incident_id = args.incident_id
    print(f"\n\033[1;36m=== RescueFlow AI - Autonomous Resolution for Incident #{incident_id} ===\033[0m\n")

    observer = ConsoleProgressObserver()
    provider = create_provider(provider_name=args.provider) if args.provider else None
    runner = AgentRunner(provider=provider, max_steps=args.steps, observers=[observer])

    try:
        result = runner.resolve_incident(incident_id=incident_id)
    except Exception as exc:
        print(f"\n\033[91mResolution failed with exception: {exc}\033[0m\n")
        sys.exit(1)

    # Summary Report
    print("\n" + "=" * 70)
    print("\033[1mFINAL AGENT RESOLUTION REPORT\033[0m")
    print("=" * 70)

    status_color = "\033[92m" if result.status == "RESOLVED" else "\033[95m" if result.status == "ESCALATED" else "\033[91m"
    print(f"Status:          {status_color}\033[1m{result.status}\033[0m")
    print(f"Action Taken:    {result.action_taken or 'None'}")
    print(f"Total Steps:     {len(result.trace)}")

    if result.candidate_actions:
        print(f"\nCandidate Actions Evaluated: {len(result.candidate_actions)}")
        for i, c in enumerate(result.candidate_actions[:3], start=1):
            print(f"  [{i}] {c.action.value} | Score: {c.score:.3f} | {c.reason}")

    if result.memory_updates:
        print("\nMemory Updates:")
        for m in result.memory_updates:
            print(f"  • {m}")

    print("\nDecision Explanation:")
    for line in result.decision_summary.split("\n"):
        print(f"  {line}")

    print("=" * 70 + "\n")


def cmd_seed(args: argparse.Namespace) -> None:
    """Re-seed the database with realistic demonstration scenarios."""
    print("Re-seeding RescueFlow AI database...")
    seed_all()
    print("\033[92mDatabase successfully re-seeded.\033[0m")


def cmd_stats(args: argparse.Namespace) -> None:
    """Display operational resolution metrics."""
    with get_db() as db:
        total = db.query(Incident).count()
        resolved = db.query(Incident).filter(Incident.status == "RESOLVED").count()
        escalated = db.query(Incident).filter(Incident.status == "ESCALATED").count()
        open_ = db.query(Incident).filter(Incident.status == "OPEN").count()
        runs = db.query(AgentRun).count()

    print("\n" + "=" * 45)
    print("\033[1mRescueFlow AI - Operational Metrics\033[0m")
    print("-" * 45)
    print(f"Total Incidents:         {total}")
    print(f"Resolved Autonomously:   \033[92m{resolved}\033[0m")
    print(f"Escalated to Ops:        \033[95m{escalated}\033[0m")
    print(f"Pending/Open:            \033[93m{open_}\033[0m")
    print(f"Recorded Agent Runs:     {runs}")
    print("=" * 45 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="rescueflow",
        description="RescueFlow AI — Autonomous Delivery-Exception Resolution CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # list
    subparsers.add_parser("list", help="List all incidents with status")

    # run
    run_parser = subparsers.add_parser("run", help="Run agent resolution on an incident")
    run_parser.add_argument("incident_id", type=int, help="Incident numeric ID")
    run_parser.add_argument(
        "--provider",
        choices=["groq", "nvidia", "mock", "auto"],
        default=None,
        help="Override LLM provider (or 'auto' for resilient failover)",
    )
    run_parser.add_argument("--steps", type=int, default=10, help="Max agent iteration steps")

    # seed
    subparsers.add_parser("seed", help="Reset and re-seed database with demonstration data")

    # stats
    subparsers.add_parser("stats", help="Show operational resolution metrics")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list_incidents(args)
    elif args.command == "run":
        cmd_run_incident(args)
    elif args.command == "seed":
        cmd_seed(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
