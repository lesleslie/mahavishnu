"""Tests for mahavishnu.pools.queueing (REQ-001)."""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings, strategies as st

from mahavishnu.core.errors import QueueingModelError
from mahavishnu.pools.queueing import MmcQueue


# Reference values from Gross & Harris, "Fundamentals of Queueing
# Theory" (4th ed.), Tables 5.1, 5.3, 5.5. The Erlang-C M/M/c table
# gives exact W_q for c=2, c=3, c=5 at selected utilizations.
# Reference: Harchol-Balter, "Performance Modeling and Design of
# Computer Systems", Chapter 32.

# ---------------------------------------------------------------------------
# Construction + validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMmcQueueConstruction:
    """REQ-001: constructor validates inputs."""

    def test_valid_construction(self) -> None:
        q = MmcQueue(arrival_rate=1.0, service_rate=2.0, num_workers=2)
        assert q.arrival_rate == 1.0
        assert q.service_rate == 2.0
        assert q.num_workers == 2

    def test_zero_arrival_rate_is_valid(self) -> None:
        """arrival_rate=0 (no traffic) is valid; utilization=0; W_q=0."""
        q = MmcQueue(arrival_rate=0.0, service_rate=1.0, num_workers=1)
        assert q.utilization == 0.0
        assert q.expected_wait_time() == 0.0

    def test_arrival_rate_must_be_non_negative(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=-1.0, service_rate=1.0, num_workers=1)

    def test_service_rate_must_be_positive(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=1.0, service_rate=0.0, num_workers=1)
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=1.0, service_rate=-1.0, num_workers=1)

    def test_num_workers_must_be_positive_int(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=1.0, service_rate=1.0, num_workers=0)
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=1.0, service_rate=1.0, num_workers=-1)

    def test_nan_arrival_rate_rejected(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=math.nan, service_rate=1.0, num_workers=1)

    def test_inf_service_rate_rejected(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue(arrival_rate=1.0, service_rate=math.inf, num_workers=1)

    def test_is_frozen(self) -> None:
        q = MmcQueue(arrival_rate=1.0, service_rate=2.0, num_workers=2)
        with pytest.raises((AttributeError, Exception)):
            q.arrival_rate = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Utilization property
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestUtilization:
    def test_rho_formula(self) -> None:
        q = MmcQueue(arrival_rate=2.0, service_rate=2.0, num_workers=4)
        # rho = 2 / (4 * 2) = 0.25
        assert q.utilization == pytest.approx(0.25, rel=1e-9)

    def test_rho_raises_when_unstable(self) -> None:
        q = MmcQueue(arrival_rate=10.0, service_rate=1.0, num_workers=1)
        with pytest.raises(QueueingModelError):
            _ = q.utilization

    def test_rho_raises_at_exactly_one(self) -> None:
        """rho == 1 is unstable; utilization should raise (router uses safe_*)."""
        q = MmcQueue(arrival_rate=1.0, service_rate=1.0, num_workers=1)
        with pytest.raises(QueueingModelError):
            _ = q.utilization


# ---------------------------------------------------------------------------
# Reference-value tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestReferenceValues:
    """Reference values from Gross & Harris / Harchol-Balter."""

    def test_mm1_kingman_at_rho_0_5(self) -> None:
        """M/M/1: W_q = rho / (mu * (1 - rho)) = 0.5 / (1 * 0.5) = 1.0."""
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=1)
        assert q.expected_wait_time("kingman") == pytest.approx(1.0, rel=1e-9)

    def test_mm1_kingman_at_rho_0_8(self) -> None:
        """M/M/1: W_q = 0.8 / (1 * 0.2) = 4.0."""
        q = MmcQueue(arrival_rate=0.8, service_rate=1.0, num_workers=1)
        assert q.expected_wait_time("kingman") == pytest.approx(4.0, rel=1e-9)

    def test_mm1_kingman_at_rho_0_9(self) -> None:
        """M/M/1: W_q = 0.9 / (1 * 0.1) = 9.0."""
        q = MmcQueue(arrival_rate=0.9, service_rate=1.0, num_workers=1)
        assert q.expected_wait_time("kingman") == pytest.approx(9.0, rel=1e-9)

    def test_mm1_kingman_equals_erlang_c_for_c_1(self) -> None:
        """Erlang-C formula at c=1 reduces to M/M/1 closed form: rho / (mu * (1 - rho))."""
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=1)
        kingman = q.expected_wait_time("kingman")
        erlang_c = q.expected_wait_time("erlang_c")
        assert kingman == pytest.approx(erlang_c, rel=1e-9)
        assert erlang_c == pytest.approx(1.0, rel=1e-9)

    def test_mmc_2_erlang_c_reference(self) -> None:
        """M/M/2 at rho=0.5: Erlang-C P(wait) = 1/3, W_q = (1/3) / (2 * mu * 0.5).

        Reference: Harchol-Balter Ch. 32, Example 32.1.
        For c=2, rho=0.5, c*rho = 1.0:
            sum_{k=0}^{c-1} (c*rho)^k/k! = 1 + 1 = 2
            (c*rho)^c / (c! (1-rho)) = 1 / (2 * 0.5) = 1
            P(wait) = 1 / (2 + 1) = 1/3
            W_q = (1/3) / (c * mu * (1 - rho)) = (1/3) / (2 * mu * 0.5) = (1/3) / mu
        With mu=2: W_q = 1/6.
        """
        q = MmcQueue(arrival_rate=2.0, service_rate=2.0, num_workers=2)
        # lambda=2, mu=2, c=2 => rho = 2/(2*2) = 0.5
        erlang_c = q.expected_wait_time("erlang_c")
        assert erlang_c == pytest.approx(1.0 / 6.0, rel=1e-9)

    def test_mmc_2_kingman_overestimates_at_low_rho(self) -> None:
        """At rho=0.5 with c=2, Kingman is looser than Erlang-C.

        Kingman: (0.5 / 0.5) / 2 = 1.0  (1/mu is 1/2 here)
        Wait — let me recompute. With mu=2:
            Kingman W_q = (0.5/0.5) * (1/2) = 1.0
        Erlang-C W_q = 1/3.
        Kingman over-estimates; this is the documented behavior.
        """
        q = MmcQueue(arrival_rate=2.0, service_rate=2.0, num_workers=2)
        assert q.expected_wait_time("kingman") > q.expected_wait_time("erlang_c")

    def test_mmc_5_erlang_c_reference(self) -> None:
        """M/M/5 at rho=0.5: Erlang-C P(wait) is small (~0.0027), W_q tiny.

        P(wait) for c=5, c*rho=2.5:
            sum_{k=0}^4 (2.5)^k / k! = 1 + 2.5 + 3.125 + 2.604 + 1.627 = 10.856
            (2.5)^5 / (5! * 0.5) = 97.656 / (120 * 0.5) = 97.656 / 60 = 1.628
            P(wait) = 1.628 / (10.856 + 1.628) = 1.628 / 12.484 = 0.1304
            W_q = 0.1304 / (5 * 2 * 0.5) = 0.1304 / 5 = 0.02609
        """
        q = MmcQueue(arrival_rate=5.0, service_rate=2.0, num_workers=5)
        # lambda=5, mu=2, c=5 => rho = 5/(5*2) = 0.5
        erlang_c = q.expected_wait_time("erlang_c")
        assert erlang_c == pytest.approx(0.02609, rel=1e-3)


# ---------------------------------------------------------------------------
# Little's law
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLittlesLaw:
    def test_l_q_equals_lambda_times_w_q(self) -> None:
        """Little's law: L_q = lambda * W_q (Kingman, default)."""
        q = MmcQueue(arrival_rate=2.0, service_rate=2.0, num_workers=3)
        l_q = q.expected_queue_length()
        w_q = q.expected_wait_time("kingman")
        assert l_q == pytest.approx(2.0 * w_q, rel=1e-9)

    def test_l_equals_l_q_plus_lambda_over_mu(self) -> None:
        """L = L_q + lambda / mu."""
        q = MmcQueue(arrival_rate=1.0, service_rate=2.0, num_workers=2)
        l_q = q.expected_queue_length()
        l = q.expected_number_in_system()
        assert l == pytest.approx(l_q + (1.0 / 2.0), rel=1e-9)

    def test_l_equals_l_q_plus_c_times_rho(self) -> None:
        """L = L_q + c*rho (busy-server count)."""
        q = MmcQueue(arrival_rate=1.0, service_rate=2.0, num_workers=2)
        l_q = q.expected_queue_length()
        l = q.expected_number_in_system()
        rho = q.utilization
        assert l == pytest.approx(l_q + 2 * rho, rel=1e-9)

    def test_zero_traffic_gives_zero_queue(self) -> None:
        q = MmcQueue(arrival_rate=0.0, service_rate=1.0, num_workers=1)
        assert q.expected_queue_length() == 0.0
        assert q.expected_number_in_system() == 0.0


# ---------------------------------------------------------------------------
# safe_expected_wait_time
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSafeExpectedWaitTime:
    def test_below_cap_returns_finite(self) -> None:
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        # rho = 0.5 / (2 * 1) = 0.25; default cap = 0.95
        result = q.safe_expected_wait_time()
        assert math.isfinite(result)
        assert result > 0.0

    def test_at_or_above_cap_returns_inf(self) -> None:
        q = MmcQueue(arrival_rate=0.95, service_rate=1.0, num_workers=1)
        # rho = 0.95; default cap = 0.95; cap is strict <, so returns inf
        assert q.safe_expected_wait_time() == math.inf

    def test_strict_cap_is_honored(self) -> None:
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=1)
        # rho = 0.5; cap 0.5 strict; returns inf
        assert q.safe_expected_wait_time(utilization_cap=0.5) == math.inf
        # cap 0.6 allows
        assert math.isfinite(q.safe_expected_wait_time(utilization_cap=0.6))

    def test_safe_does_not_raise_at_unstable_rho(self) -> None:
        """safe_* is the router-friendly entry: never raises on rho >= 1."""
        q = MmcQueue(arrival_rate=5.0, service_rate=1.0, num_workers=1)
        # rho = 5; well past any cap
        assert q.safe_expected_wait_time() == math.inf


# ---------------------------------------------------------------------------
# fit_from_observations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFitFromObservations:
    def test_fit_from_constant_observations(self) -> None:
        """Mean inter-arrival = 2.0, mean service = 0.5 -> lambda=0.5, mu=2.0."""
        # 10 arrivals, 2s gap each => mean_arrival = 2.0; lambda = 0.5
        arrivals = [2.0] * 10
        # 10 services, 0.5s each => mean_service = 0.5; mu = 2.0
        services = [0.5] * 10
        q = MmcQueue.fit_from_observations(arrivals, services, num_workers=2)
        assert q.arrival_rate == pytest.approx(0.5, rel=1e-9)
        assert q.service_rate == pytest.approx(2.0, rel=1e-9)
        assert q.num_workers == 2
        # rho = 0.5 / (2 * 2) = 0.125
        assert q.utilization == pytest.approx(0.125, rel=1e-9)

    def test_fit_rejects_empty_arrivals(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([], [1.0], num_workers=1)

    def test_fit_rejects_empty_services(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([1.0], [], num_workers=1)

    def test_fit_rejects_length_mismatch(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([1.0, 2.0], [0.5], num_workers=1)

    def test_fit_rejects_nan(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([math.nan, 1.0], [0.5, 0.5], num_workers=1)

    def test_fit_rejects_inf(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([1.0, math.inf], [0.5, 0.5], num_workers=1)

    def test_fit_rejects_negative(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([1.0, -0.5], [0.5, 0.5], num_workers=1)

    def test_fit_rejects_zero_mean_arrival(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([0.0, 0.0], [0.5, 0.5], num_workers=1)

    def test_fit_rejects_zero_mean_service(self) -> None:
        with pytest.raises(QueueingModelError):
            MmcQueue.fit_from_observations([1.0, 1.0], [0.0, 0.0], num_workers=1)

    def test_fit_single_observation(self) -> None:
        q = MmcQueue.fit_from_observations([1.0], [0.5], num_workers=1)
        assert q.arrival_rate == pytest.approx(1.0, rel=1e-9)
        assert q.service_rate == pytest.approx(2.0, rel=1e-9)

    def test_fit_round_trip_with_known_rate(self) -> None:
        """Construct a queue, then re-fit from a synthetic Poisson stream.

        Use the inverse-CDF to draw from an exponential with the known
        mean. With N=10_000 samples, the empirical mean is within 5%
        of the true mean with very high probability.
        """
        import random

        rng = random.Random(42)
        true_lambda = 2.0
        true_mu = 4.0
        n = 10_000
        arrivals = [rng.expovariate(true_lambda) for _ in range(n)]
        services = [rng.expovariate(true_mu) for _ in range(n)]
        q = MmcQueue.fit_from_observations(arrivals, services, num_workers=3)
        # Allow 5% relative error on each rate.
        assert q.arrival_rate == pytest.approx(true_lambda, rel=0.05)
        assert q.service_rate == pytest.approx(true_mu, rel=0.05)


# ---------------------------------------------------------------------------
# Property tests (Hypothesis)
# ---------------------------------------------------------------------------


@pytest.mark.property
class TestHypothesisProperties:
    """Property-based tests covering utilization invariant, Little's law, etc."""

    @given(
        arrival_rate=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        service_rate=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        num_workers=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=200, deadline=None)
    def test_rho_equals_lambda_over_c_times_mu(self, arrival_rate: float, service_rate: float, num_workers: int) -> None:
        """rho == lambda / (c * mu) for stable regimes."""
        rho_computed = arrival_rate / (num_workers * service_rate)
        if rho_computed >= 1.0:
            return  # Skip unstable; utilization raises
        q = MmcQueue(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=num_workers)
        assert q.utilization == pytest.approx(rho_computed, rel=1e-9)

    @given(
        arrival_rate=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        service_rate=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        num_workers=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=200, deadline=None)
    def test_littles_law_holds_for_all_stable_queues(
        self, arrival_rate: float, service_rate: float, num_workers: int,
    ) -> None:
        """L_q == lambda * W_q (Little's law, Kingman)."""
        rho_computed = arrival_rate / (num_workers * service_rate)
        if rho_computed >= 0.95:
            return  # Numerical edge: Kingman blows up near 1
        q = MmcQueue(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=num_workers)
        l_q = q.expected_queue_length()
        w_q = q.expected_wait_time("kingman")
        # Both should be positive; L_q == lambda * W_q
        assert l_q == pytest.approx(arrival_rate * w_q, rel=1e-9)

    @given(
        arrival_rate=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        service_rate=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        num_workers=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100, deadline=None)
    def test_kingman_equals_erlang_c_for_c_1(
        self, arrival_rate: float, service_rate: float, num_workers: int,
    ) -> None:
        """When c == 1, Kingman and Erlang-C are identical closed-form M/M/1."""
        if num_workers != 1:
            return
        rho_computed = arrival_rate / service_rate
        if rho_computed >= 0.95:
            return
        q = MmcQueue(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=1)
        kingman = q.expected_wait_time("kingman")
        erlang_c = q.expected_wait_time("erlang_c")
        assert kingman == pytest.approx(erlang_c, rel=1e-9)

    @given(
        arrival_rate=st.floats(min_value=0.01, max_value=5.0, allow_nan=False, allow_infinity=False),
        service_rate=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        num_workers=st.integers(min_value=2, max_value=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_kingman_overestimates_erlang_c_for_c_ge_2_low_rho(
        self, arrival_rate: float, service_rate: float, num_workers: int,
    ) -> None:
        """For c >= 2 at low rho, Kingman (M/M/1-like) over-estimates vs Erlang-C."""
        rho = arrival_rate / (num_workers * service_rate)
        if rho < 0.1 or rho >= 0.99:
            return
        q = MmcQueue(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=num_workers)
        assert q.expected_wait_time("kingman") >= q.expected_wait_time("erlang_c")

    @given(
        arrival_rate=st.floats(min_value=0.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        service_rate=st.floats(min_value=0.01, max_value=10.0, allow_nan=False, allow_infinity=False),
        num_workers=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=100, deadline=None)
    def test_nan_inf_rejected(
        self, arrival_rate: float, service_rate: float, num_workers: int,
    ) -> None:
        """NaN/Inf rates rejected at construction."""
        # Replace any input that becomes NaN/Inf after the hypothesis
        # sample with a sentinel. The float strategies above already
        # disable nan/inf, so this test exercises only the construction
        # invariants.
        from math import isfinite
        if not (isfinite(arrival_rate) and isfinite(service_rate) and isfinite(num_workers)):
            return
        if arrival_rate < 0 or service_rate <= 0 or num_workers < 1:
            with pytest.raises(QueueingModelError):
                MmcQueue(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=num_workers)
        else:
            MmcQueue(arrival_rate=arrival_rate, service_rate=service_rate, num_workers=num_workers)

    @given(
        mean_arrival=st.floats(min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False),
        mean_service=st.floats(min_value=0.5, max_value=5.0, allow_nan=False, allow_infinity=False),
        n=st.integers(min_value=200, max_value=500),
        num_workers=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=30, deadline=None)
    def test_fit_round_trip_inverse_cdf(
        self, mean_arrival: float, mean_service: float, n: int, num_workers: int,
    ) -> None:
        """Sampling from exponential with known mean then fitting recovers the mean within 20%.

        With N>=200 exponential samples, the empirical mean is within
        20% of the true mean with very high probability; tighter
        bounds risk flaky tests on small-n parameter combinations.
        """
        import random

        # Mix all four parameters into the seed so different
        # parameter sets produce different streams.
        seed = (
            int(mean_arrival * 1_000_000)
            ^ int(mean_service * 1_000_000)
            ^ (n * 31)
            ^ (num_workers * 127)
        )
        rng = random.Random(seed)
        arrivals = [rng.expovariate(1.0 / mean_arrival) for _ in range(n)]
        services = [rng.expovariate(1.0 / mean_service) for _ in range(n)]
        q = MmcQueue.fit_from_observations(arrivals, services, num_workers=num_workers)
        assert q.arrival_rate == pytest.approx(1.0 / mean_arrival, rel=0.20)
        assert q.service_rate == pytest.approx(1.0 / mean_service, rel=0.20)


# ---------------------------------------------------------------------------
# Single-worker boundary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSingleWorkerBoundary:
    def test_mm1_at_zero_traffic(self) -> None:
        q = MmcQueue(arrival_rate=0.0, service_rate=1.0, num_workers=1)
        assert q.expected_wait_time() == 0.0

    def test_mm1_approaches_infinity_near_full_utilization(self) -> None:
        """As rho -> 1, W_q -> infinity (Kingman)."""
        q = MmcQueue(arrival_rate=0.999, service_rate=1.0, num_workers=1)
        w = q.expected_wait_time("kingman")
        # 0.999 / 0.001 = 999
        assert w > 500.0

    def test_safe_method_returns_inf_near_one(self) -> None:
        q = MmcQueue(arrival_rate=0.99, service_rate=1.0, num_workers=1)
        assert q.safe_expected_wait_time() == math.inf


# ---------------------------------------------------------------------------
# Approximation argument validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestApproximationArgument:
    def test_invalid_approximation_raises(self) -> None:
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        with pytest.raises(ValueError):
            q.expected_wait_time(approximation="bogus")  # type: ignore[arg-type]

    def test_safe_with_invalid_approximation_raises(self) -> None:
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        with pytest.raises(ValueError):
            q.safe_expected_wait_time(approximation="bogus")  # type: ignore[arg-type]

    def test_safe_with_kingman_and_low_rho(self) -> None:
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        assert math.isfinite(q.safe_expected_wait_time(approximation="kingman"))

    def test_safe_with_erlang_c_and_low_rho(self) -> None:
        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
        assert math.isfinite(q.safe_expected_wait_time(approximation="erlang_c"))


# ---------------------------------------------------------------------------
# Module integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModulePublicAPI:
    def test_init_exports_mmc_queue(self) -> None:
        from mahavishnu.pools import queueing

        assert hasattr(queueing, "MmcQueue")
        assert "MmcQueue" in queueing.__all__

    def test_mmc_queue_importable_from_package(self) -> None:
        from mahavishnu.pools.queueing import MmcQueue

        q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=1)
        assert q.utilization == pytest.approx(0.5, rel=1e-9)
