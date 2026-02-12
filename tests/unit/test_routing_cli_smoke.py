"""Minimal smoke tests for routing CLI - structure only."""

import pytest


def test_routing_module_imports():
    """Routing module should be importable."""
    from mahavishnu import routing_cli
    assert routing_cli is not None
    assert hasattr(routing_cli, "routing_app")


def test_routing_app_has_commands():
    """Routing app should have commands."""
    from mahavishnu import routing_cli

    # Just verify the app has a commands attribute
    assert hasattr(routing_cli.routing_app, "commands")


def test_stats_command_exists():
    """Stats command should be defined."""
    from mahavishnu import routing_cli

    # Just verify command exists
    assert hasattr(routing_cli, "stats")


def test_set_budget_command_exists():
    """Set-budget command should be defined."""
    from mahavishnu import routing_cli

    assert hasattr(routing_cli, "set-budget")


def test_ab_test_commands_exist():
    """AB-test commands should be defined."""
    from mahavishnu import routing_cli

    # Just verify commands exist
    assert hasattr(routing_cli, "ab-test")
    assert hasattr(routing_cli.routing_app, "ab-test")


def test_recalculate_command_exists():
    """Recalculate command should be defined."""
    from mahavishnu import routing_cli

    assert hasattr(routing_cli, "recalculate")
