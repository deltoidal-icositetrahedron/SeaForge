"""Tests for Material and ShipComponent models and their validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ship_sim.models import Material, ShipComponent


def make_steel() -> Material:
    return Material(
        name="EH36 shipbuilding steel",
        density_kg_m3=7850.0,
        yield_strength_pa=355e6,
        ultimate_strength_pa=490e6,
        elastic_modulus_pa=210e9,
        base_corrosion_rate_m_per_year=0.0001,  # 0.1 mm/year
        corrosion_resistance_factor=1.0,
        galvanic_potential_v=-0.60,
        coating_breakdown_factor=1.0,
        fatigue_strength_pa=160e6,
        notes="Higher-strength hull steel.",
    )


def test_valid_material():
    steel = make_steel()
    assert steel.yield_strength_pa < steel.ultimate_strength_pa
    assert steel.density_kg_m3 == 7850.0


def test_material_rejects_ultimate_below_yield():
    with pytest.raises(ValidationError):
        Material(
            name="bad",
            density_kg_m3=7850.0,
            yield_strength_pa=490e6,
            ultimate_strength_pa=355e6,  # < yield => invalid
            elastic_modulus_pa=210e9,
            base_corrosion_rate_m_per_year=0.0001,
            galvanic_potential_v=-0.6,
        )


def test_material_rejects_nonpositive_density():
    with pytest.raises(ValidationError):
        Material(
            name="bad",
            density_kg_m3=0.0,
            yield_strength_pa=355e6,
            ultimate_strength_pa=490e6,
            elastic_modulus_pa=210e9,
            base_corrosion_rate_m_per_year=0.0001,
            galvanic_potential_v=-0.6,
        )


def test_material_rejects_negative_corrosion_rate():
    with pytest.raises(ValidationError):
        Material(
            name="bad",
            density_kg_m3=7850.0,
            yield_strength_pa=355e6,
            ultimate_strength_pa=490e6,
            elastic_modulus_pa=210e9,
            base_corrosion_rate_m_per_year=-1e-5,
            galvanic_potential_v=-0.6,
        )


def make_component(**overrides) -> ShipComponent:
    base = dict(
        name="bottom_plating",
        material=make_steel(),
        thickness_m=0.018,
        area_m2=120.0,
        exposed_fraction=1.0,
        structural_importance=1.0,
        location_on_ship="bottom_plating",
        vertical_position_m=0.0,
        original_thickness_m=0.020,
        corrosion_allowance_m=0.003,
        safety_factor_required=1.5,
    )
    base.update(overrides)
    return ShipComponent(**base)


def test_valid_component():
    comp = make_component()
    assert comp.thickness_m <= comp.original_thickness_m
    assert 0.0 <= comp.exposed_fraction <= 1.0


def test_component_rejects_zero_thickness():
    with pytest.raises(ValidationError):
        make_component(thickness_m=0.0)


def test_component_rejects_thickness_above_original():
    with pytest.raises(ValidationError):
        make_component(thickness_m=0.025, original_thickness_m=0.020)


def test_component_rejects_exposed_fraction_out_of_range():
    with pytest.raises(ValidationError):
        make_component(exposed_fraction=1.5)


def test_component_rejects_allowance_above_original():
    with pytest.raises(ValidationError):
        make_component(corrosion_allowance_m=0.05, original_thickness_m=0.020)
