"""Tests for mahavishnu/scaffolding/jinjava_env.py."""

from __future__ import annotations

from jinja2 import Environment, TemplateSyntaxError

import pytest

from mahavishnu.scaffolding.jinjava_env import (
    _toml_array_filter,
    create_scaffold_env,
    create_template_env,
)


class TestCreateScaffoldEnv:
    def test_returns_jinja2_environment(self) -> None:
        env = create_scaffold_env()
        assert isinstance(env, Environment)

    def test_uses_strict_undefined(self) -> None:
        env = create_scaffold_env()
        template = env.from_string("Hello {{ name }}")
        with pytest.raises(Exception):
            template.render()

    def test_has_toml_array_filter(self) -> None:
        env = create_scaffold_env()
        assert "toml_array" in env.filters

    def test_has_kebab_to_snake_filter(self) -> None:
        env = create_scaffold_env()
        t = env.from_string("{{ 'my-variable-name' | kebab_to_snake }}")
        assert t.render() == "my_variable_name"

    def test_has_snake_to_title_filter(self) -> None:
        env = create_scaffold_env()
        t = env.from_string("{{ 'my_var_name' | snake_to_title }}")
        assert t.render() == "My Var Name"

    def test_standard_delimiters(self) -> None:
        env = create_scaffold_env()
        t = env.from_string("{{ '{{' }} and {{ '}}' }}")
        assert "{{" in t.render()
        assert "}}" in t.render()


class TestCreateTemplateEnv:
    def test_returns_jinja2_environment(self) -> None:
        env = create_template_env()
        assert isinstance(env, Environment)

    def test_uses_strict_undefined(self) -> None:
        env = create_template_env()
        template = env.from_string("Hello [[ name ]]")
        with pytest.raises(Exception):
            template.render()

    def test_custom_variable_delimiters(self) -> None:
        env = create_template_env()
        t = env.from_string("[[ name ]]")
        assert t.render(name="Alice") == "Alice"

    def test_custom_block_delimiters(self) -> None:
        env = create_template_env()
        src = "[% for item in items %][[ item ]]/[% endfor %]"
        t = env.from_string(src)
        assert t.render(items=["a", "b"]) == "a/b/"

    def test_custom_comment_delimiters(self) -> None:
        env = create_template_env()
        t = env.from_string("Hello [# comment #] World")
        assert "comment" not in t.render()
        assert "World" in t.render()

    def test_different_from_scaffold_env(self) -> None:
        scaffold_env = create_scaffold_env()
        template_env = create_template_env()
        # Scaffold uses {{ }}, template uses [[ ]]
        s_t = scaffold_env.from_string("{{ 'x' }}")
        t_t = template_env.from_string("[[ 'x' ]]")
        assert s_t.render() == "x"
        assert t_t.render() == "x"
        # The environments have different start/end strings
        assert scaffold_env.variable_start_string == "{{"
        assert template_env.variable_start_string == "[["


class TestTomlArrayFilter:
    def test_empty_list(self) -> None:
        result = _toml_array_filter([])
        assert result == "[]"

    def test_single_element(self) -> None:
        result = _toml_array_filter(["item1"])
        assert result == '["item1"]'

    def test_multiple_elements(self) -> None:
        result = _toml_array_filter(["item1", "item2", "item3"])
        assert result == '["item1", "item2", "item3"]'

    def test_escapes_double_quotes(self) -> None:
        result = _toml_array_filter(['say "hello"'])
        assert result == '["say \\"hello\\""]'

    def test_escapes_backslashes(self) -> None:
        result = _toml_array_filter(["path\\to\\file"])
        assert result == '["path\\\\to\\\\file"]'

    def test_used_in_scaffold_env(self) -> None:
        env = create_scaffold_env()
        t = env.from_string("{{ ['a', 'b'] | toml_array }}")
        assert t.render() == '["a", "b"]'