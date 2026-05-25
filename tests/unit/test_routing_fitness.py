"""Tests for routing fitness signal parsing and selection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.pools.routing_fitness import (
    FitnessSignal,
    RoutingFitnessReader,
    _sanitize_key_component,
)


class TestFitnessSignal:
    """Tests for FitnessSignal conversion helpers."""

    def test_from_dict_applies_type_conversion_and_defaults(self):
        signal = FitnessSignal.from_dict(
            {
                "score": "0.75",
                "samples": "12",
                "failure_rate": "0.25",
                "p99_latency_ms": "123.4",
                "updated_at": "2026-05-25T12:00:00+00:00",
                "window_start": "2026-05-25T11:00:00+00:00",
                "component_count": "3",
            }
        )

        assert signal.score == 0.75
        assert signal.samples == 12
        assert signal.failure_rate == 0.25
        assert signal.p99_latency_ms == 123.4
        assert signal.updated_at == "2026-05-25T12:00:00+00:00"
        assert signal.window_start == "2026-05-25T11:00:00+00:00"
        assert signal.component_count == 3

    def test_from_dict_uses_defaults_for_missing_values(self):
        signal = FitnessSignal.from_dict({})

        assert signal == FitnessSignal()


class TestSanitizeKeyComponent:
    """Tests for the key-component sanitizer."""

    def test_sanitize_allows_safe_values(self):
        assert _sanitize_key_component("code_generation_1") == "code_generation_1"

    def test_sanitize_rewrites_unsafe_values(self):
        assert _sanitize_key_component("code/gen:bad") == "code_gen_bad"

    def test_sanitize_returns_placeholder_for_empty_output(self):
        assert _sanitize_key_component("") == "unknown"


class TestRoutingFitnessReader:
    """Tests for Dhara-backed selector lookup."""

    @pytest.mark.asyncio
    async def test_get_fitness_signals_returns_empty_without_backend(self):
        reader = RoutingFitnessReader()

        assert await reader.get_fitness_signals("code_generation") == {}

    @pytest.mark.asyncio
    async def test_get_fitness_signals_reads_and_parses_entries(self):
        dhara_state = MagicMock()
        dhara_state.list_prefix = AsyncMock(
            return_value=[
                (
                    "routing_fitness/code_generation/least_loaded",
                    {"score": 0.9, "samples": 10},
                ),
                (
                    "routing_fitness/code_generation/random",
                    {"score": 0.6, "samples": 8},
                ),
            ]
        )
        reader = RoutingFitnessReader(dhara_state=dhara_state)

        signals = await reader.get_fitness_signals("code_generation")

        assert set(signals) == {"least_loaded", "random"}
        assert signals["least_loaded"].score == 0.9
        assert signals["random"].samples == 8
        dhara_state.list_prefix.assert_awaited_once_with("routing_fitness/code_generation/")

    @pytest.mark.asyncio
    async def test_get_fitness_signals_ignores_bad_entries_and_backend_errors(self):
        dhara_state = MagicMock()
        dhara_state.list_prefix = AsyncMock(
            return_value=[
                ("routing_fitness/code_generation/", {"score": 1.0}),
                ("bad-key", {"score": 0.1}),
                (
                    "routing_fitness/code_generation/least_loaded",
                    object(),
                ),
            ]
        )
        reader = RoutingFitnessReader(dhara_state=dhara_state)

        signals = await reader.get_fitness_signals("code_generation")

        assert signals == {}

    @pytest.mark.asyncio
    async def test_get_fitness_signals_returns_empty_on_backend_failure(self):
        dhara_state = MagicMock()
        dhara_state.list_prefix = AsyncMock(side_effect=RuntimeError("dhara down"))
        reader = RoutingFitnessReader(dhara_state=dhara_state)

        assert await reader.get_fitness_signals("code_generation") == {}

    @pytest.mark.asyncio
    async def test_get_best_selector_chooses_highest_score(self):
        dhara_state = MagicMock()
        dhara_state.list_prefix = AsyncMock(
            return_value=[
                (
                    "routing_fitness/code_generation/least_loaded",
                    {"score": 0.9},
                ),
                (
                    "routing_fitness/code_generation/random",
                    {"score": 0.4},
                ),
            ]
        )
        reader = RoutingFitnessReader(dhara_state=dhara_state)

        assert await reader.get_best_selector("code_generation") == "least_loaded"

    @pytest.mark.asyncio
    async def test_get_best_selector_returns_none_without_signals(self):
        dhara_state = MagicMock()
        dhara_state.list_prefix = AsyncMock(return_value=[])
        reader = RoutingFitnessReader(dhara_state=dhara_state)

        assert await reader.get_best_selector("code_generation") is None
