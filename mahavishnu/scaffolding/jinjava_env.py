"""Jinja2 environment factory with dual delimiter support."""

from __future__ import annotations

from jinja2 import Environment, StrictUndefined


def create_scaffold_env() -> Environment:
    """Create Jinja2 env for scaffold templates ({{ }} delimiters)."""
    env = Environment(undefined=StrictUndefined)
    env.filters["toml_array"] = _toml_array_filter
    env.filters["kebab_to_snake"] = lambda s: s.replace("-", "_")
    env.filters["snake_to_title"] = lambda s: s.replace("_", " ").title()
    return env


def create_template_env() -> Environment:
    """Create Jinja2 env for generated HTML templates ([[ ]] delimiters)."""
    return Environment(
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        comment_start_string="[#",
        comment_end_string="#]",
        undefined=StrictUndefined,
    )


def _toml_array_filter(value: list[str]) -> str:
    """Jinja2 filter: render a list as a TOML array."""
    items = ", ".join(f'"{v}"' for v in value)
    return f"[{items}]"
