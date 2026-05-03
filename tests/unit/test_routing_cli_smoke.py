"""Minimal smoke tests for routing CLI - structure only."""


def test_routing_module_imports():
    """Routing module should be importable."""
    from mahavishnu import routing_cli

    assert routing_cli is not None
    assert hasattr(routing_cli, "routing_app")


def test_routing_app_is_typer():
    """Routing app should be a Typer instance."""
    import typer

    from mahavishnu import routing_cli

    assert isinstance(routing_cli.routing_app, typer.Typer)


def test_stats_command_registered():
    """Stats command should be registered on the routing app."""
    from mahavishnu import routing_cli

    # Typer registers commands via decorators; verify the function exists
    assert hasattr(routing_cli, "routing_stats")


def test_reset_command_registered():
    """Reset command should be registered on the routing app."""
    from mahavishnu import routing_cli

    assert hasattr(routing_cli, "routing_reset")


def test_add_routing_commands_function():
    """add_routing_commands helper should exist."""
    from mahavishnu import routing_cli

    assert hasattr(routing_cli, "add_routing_commands")
    assert callable(routing_cli.add_routing_commands)
