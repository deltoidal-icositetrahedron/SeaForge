"""Tests for Monte Carlo uncertainty propagation."""

from __future__ import annotations

import pytest

from ship_sim.models import (
    Material,
    ProceduralSettings,
    Scenario,
    Ship,
    ShipComponent,
    SimulationSettings,
    Trajectory,
    Waypoint,
)
from ship_sim.simulation.monte_carlo import PerturbationSpec, run_monte_carlo
from ship_sim.units import hours_to_seconds


def make_scenario() -> Scenario:
    mat = Material(
        name="EH36", density_kg_m3=7850.0, yield_strength_pa=355e6,
        ultimate_strength_pa=490e6, elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0002, galvanic_potential_v=-0.6,
        coating_breakdown_factor=1.2,
    )
    ship = Ship(
        name="MC Test", length_m=72.0, beam_m=12.5, draft_m=4.2,
        displacement_mass_kg=2.4e6, center_of_gravity_height_m=5.1,
        metacentric_height_m=0.85, projected_lateral_area_m2=540.0,
        roll_natural_period_s=10.0,
        components=[
            ShipComponent(name="bottom", material=mat, thickness_m=0.014, area_m2=500.0,
                          original_thickness_m=0.014, corrosion_allowance_m=0.003),
            ShipComponent(name="deck", material=mat, thickness_m=0.010, area_m2=300.0,
                          structural_importance=0.6, original_thickness_m=0.010,
                          corrosion_allowance_m=0.002),
        ],
    )
    traj = Trajectory(waypoints=[
        Waypoint(latitude_deg=20.0, longitude_deg=-30.0, time_s=0.0,
                 target_speed_m_s=6.0, heading_deg=300.0),
        Waypoint(latitude_deg=30.0, longitude_deg=-35.0, time_s=hours_to_seconds(9.0),
                 target_speed_m_s=6.0, heading_deg=315.0),
    ])
    return Scenario(
        name="mc", simulation=SimulationSettings(dt_hours=3.0), ship=ship,
        trajectory=traj, procedural=ProceduralSettings(seed=11),
    )


def test_reproducible_with_fixed_seed():
    sc = make_scenario()
    r1 = run_monte_carlo(sc, n_runs=10, random_seed=123)
    r2 = run_monte_carlo(sc, n_runs=10, random_seed=123)
    assert r1.samples["max_stability_risk"] == r2.samples["max_stability_risk"]
    assert r1.samples["cumulative_capsize_probability"] == \
        r2.samples["cumulative_capsize_probability"]
    assert r1.corrosion_by_component == r2.corrosion_by_component
    assert r1.input_samples == r2.input_samples


def test_different_seed_changes_output():
    sc = make_scenario()
    a = run_monte_carlo(sc, n_runs=10, random_seed=1)
    b = run_monte_carlo(sc, n_runs=10, random_seed=2)
    assert a.samples["max_stability_risk"] != b.samples["max_stability_risk"]


def test_correct_number_of_runs():
    sc = make_scenario()
    n = 12
    r = run_monte_carlo(sc, n_runs=n, random_seed=7)
    assert r.n_runs == n
    for values in r.samples.values():
        assert len(values) == n
    for values in r.corrosion_by_component.values():
        assert len(values) == n
    for values in r.input_samples.values():
        assert len(values) == n


def test_percentiles_ordered():
    sc = make_scenario()
    r = run_monte_carlo(sc, n_runs=40, random_seed=99)
    for metric in r.samples:
        d = r.distribution(metric)
        assert d["p5"] <= d["p50"] <= d["p95"]
    # And for per-component corrosion.
    summ = r.summary()
    for key, d in summ.items():
        assert d["p5"] <= d["p50"] <= d["p95"]


def test_probability_outputs_in_unit_interval():
    sc = make_scenario()
    r = run_monte_carlo(sc, n_runs=30, random_seed=5)
    for metric in ("max_stability_risk", "cumulative_capsize_probability"):
        for v in r.samples[metric]:
            assert 0.0 <= v <= 1.0
        d = r.distribution(metric)
        assert 0.0 <= d["p5"] <= d["p95"] <= 1.0
        assert 0.0 <= d["mean"] <= 1.0


def test_corrosion_loss_nonnegative():
    sc = make_scenario()
    r = run_monte_carlo(sc, n_runs=15, random_seed=3)
    for values in r.corrosion_by_component.values():
        assert all(v >= 0.0 for v in values)


def test_sensitivity_returns_ranked_correlations():
    sc = make_scenario()
    r = run_monte_carlo(sc, n_runs=60, random_seed=42)
    ranking = r.sensitivity("max_stability_risk")
    assert len(ranking) == len(r.input_samples)
    # Ranked by absolute correlation (descending) and all within [-1, 1].
    abscorr = [abs(c) for _, c in ranking]
    assert abscorr == sorted(abscorr, reverse=True)
    assert all(-1.0 <= c <= 1.0 for _, c in ranking)


def test_multiprocessing_matches_serial():
    sc = make_scenario()
    serial = run_monte_carlo(sc, n_runs=6, random_seed=77, backend="python")
    parallel = run_monte_carlo(sc, n_runs=6, random_seed=77,
                               backend="multiprocessing", n_jobs=2)
    # Per-index seeds make the two backends numerically identical.
    assert serial.samples["max_stability_risk"] == \
        pytest.approx(parallel.samples["max_stability_risk"])
    assert serial.corrosion_by_component == parallel.corrosion_by_component


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        run_monte_carlo(make_scenario(), n_runs=2, random_seed=1, backend="rust")


def test_custom_perturbation_spec():
    sc = make_scenario()
    # Zero perturbation => all runs identical (deterministic).
    spec = PerturbationSpec(
        corrosion_rate_rel_std=0.0, coating_breakdown_rel_std=0.0, salinity_abs_std=0.0,
        ph_abs_std=0.0, dissolved_oxygen_rel_std=0.0, wave_height_rel_std=0.0,
        wave_period_rel_std=0.0, wind_speed_rel_std=0.0, storm_abs_std=0.0,
        mass_rel_std=0.0, cog_height_rel_std=0.0, metacentric_height_rel_std=0.0,
    )
    r = run_monte_carlo(sc, n_runs=5, random_seed=1, perturbation=spec)
    # With no input perturbation AND procedural re-seeding disabled effect is small;
    # the perturbation multipliers are all exactly 1.0/0.0.
    for name, values in r.input_samples.items():
        expected = 1.0 if name.endswith("_mult") else 0.0
        assert all(v == expected for v in values)
