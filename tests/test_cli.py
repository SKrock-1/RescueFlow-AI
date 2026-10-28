"""
RescueFlow AI — CLI Unit Tests.

Validates that command-line subcommands execute without uncaught errors.
"""

from __future__ import annotations

import argparse
from unittest.mock import patch

from app.cli import cmd_list_incidents, cmd_stats


def test_cli_list_incidents(capsys):
    """Verify that cmd_list_incidents outputs a formatted table."""
    args = argparse.Namespace(command="list")
    cmd_list_incidents(args)
    captured = capsys.readouterr()
    assert "ID" in captured.out
    assert "Order" in captured.out
    assert "Customer" in captured.out


def test_cli_stats(capsys):
    """Verify that cmd_stats outputs operational metrics."""
    args = argparse.Namespace(command="stats")
    cmd_stats(args)
    captured = capsys.readouterr()
    assert "Operational Metrics" in captured.out
    assert "Total Incidents" in captured.out
