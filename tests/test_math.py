"""Tests for the shared numeric helpers in ship_sim._math."""

from __future__ import annotations


import pytest

from ship_sim._math import clamp, clamp01, logistic, saturating


def test_clamp():
    assert clamp(5.0, 0.0, 10.0) == 5.0
    assert clamp(-1.0, 0.0, 10.0) == 0.0
    assert clamp(11.0, 0.0, 10.0) == 10.0


def test_clamp01():
    assert clamp01(0.5) == 0.5
    assert clamp01(-0.2) == 0.0
    assert clamp01(1.5) == 1.0


def test_logistic_range_and_midpoint():
    assert logistic(0.0) == pytest.approx(0.5)
    assert 0.0 < logistic(-50.0) < 1e-9
    assert 1.0 - logistic(50.0) < 1e-9
    # Monotonic increasing.
    assert logistic(-1.0) < logistic(0.0) < logistic(1.0)
    # Symmetry.
    assert logistic(2.0) + logistic(-2.0) == pytest.approx(1.0)


def test_logistic_stable_for_large_magnitudes():
    # Must not overflow for very negative/positive inputs.
    assert logistic(-1000.0) == pytest.approx(0.0)
    assert logistic(1000.0) == pytest.approx(1.0)


def test_saturating_monotonic_and_bounded():
    assert saturating(0.0, 1.0) == 0.0
    assert saturating(-5.0, 1.0) == 0.0  # negatives floored
    assert 0.0 < saturating(1.0, 1.0) < 1.0
    assert saturating(1.0, 1.0) == pytest.approx(0.5)
    # Monotonic increasing, approaching 1 as value >> scale.
    assert saturating(1.0, 1.0) < saturating(10.0, 1.0) < 1.0
    assert saturating(1e6, 1.0) == pytest.approx(1.0, abs=1e-5)
