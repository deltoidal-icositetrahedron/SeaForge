use crate::{environment::OceanConditions, vessel::VesselConfig};

const RHO_SEAWATER: f64 = 1025.0;
const G: f64 = 9.81;

/// Calm-water resistance [N] using total resistance coefficient on wetted area.
///
/// hull_drag_coeff here is Ct (total resistance coefficient, typically 0.012–0.025
/// for small high-speed hulls), applied to wetted surface area — not Cd on frontal area.
/// This formulation gives physically realistic resistance for displacement/semi-planing ASVs.
fn calm_water_resistance_n(config: &VesselConfig, mass_kg: f64, speed_ms: f64) -> f64 {
    let draft = config.hull.draft_at_mass(mass_kg);
    let wetted = config.hull.wetted_area_m2(draft);
    0.5 * RHO_SEAWATER * config.propulsion.hull_drag_coeff * wetted * speed_ms.powi(2)
}

/// Added wave resistance [N] — Boese formulation simplified for head seas.
/// Scales with Hs² / λ_p × beam × L (energy radiated by ship in waves).
fn wave_added_resistance_n(config: &VesselConfig, conditions: &OceanConditions) -> f64 {
    let lambda_p = G * conditions.tp_s.powi(2) / (2.0 * std::f64::consts::PI);
    let r_aw = RHO_SEAWATER * G * conditions.hs_m.powi(2)
        * config.hull.beam_m.powi(2)
        / (16.0 * lambda_p.max(0.5));
    r_aw * conditions.encounter_factor()
}

/// Wind resistance [N] on above-waterline area.
fn wind_resistance_n(config: &VesselConfig, wind_speed_ms: f64) -> f64 {
    const RHO_AIR: f64 = 1.225;
    const CD_ABOVE_WATER: f64 = 0.75;
    let above_water_area = config.hull.beam_m * (config.hull.depth_m - config.hull.draft_m);
    0.5 * RHO_AIR * CD_ABOVE_WATER * above_water_area * wind_speed_ms.powi(2)
}

/// Total resistance [N] at a given speed, mass, and sea state.
pub fn total_resistance_n(
    config: &VesselConfig,
    mass_kg: f64,
    speed_ms: f64,
    conditions: &OceanConditions,
) -> f64 {
    calm_water_resistance_n(config, mass_kg, speed_ms)
        + wave_added_resistance_n(config, conditions)
        + wind_resistance_n(config, conditions.wind_speed_ms)
}

/// Equilibrium speed [m/s] at maximum continuous power.
///
/// Solves R_total(v) = T_available iteratively. Convergence in ~8 Newton steps.
pub fn equilibrium_speed_ms(
    config: &VesselConfig,
    mass_kg: f64,
    conditions: &OceanConditions,
) -> f64 {
    let p_shaft = config.propulsion.max_power_kw * 1000.0 * config.propulsion.propulsive_efficiency;

    // Initial guess: calm-water cube-root relation
    let draft = config.hull.draft_at_mass(mass_kg);
    let wetted = config.hull.wetted_area_m2(draft);
    let k = 0.5 * RHO_SEAWATER * config.propulsion.hull_drag_coeff * wetted;
    let mut v = (p_shaft / k.max(1.0)).cbrt();

    for _ in 0..12 {
        let r = total_resistance_n(config, mass_kg, v, conditions);
        let thrust = if v > 0.01 { p_shaft / v } else { p_shaft / 0.01 };
        let residual = thrust - r;
        // Derivative of (P/v - R(v)) ≈ -P/v² - dR/dv
        let dr_dv = 2.0 * calm_water_resistance_n(config, mass_kg, v) / v.max(0.01);
        let jacobian = -p_shaft / v.powi(2).max(1e-4) - dr_dv;
        let delta = residual / jacobian.abs().max(1.0);
        v = (v - delta).clamp(0.5, 30.0);
        if residual.abs() < 10.0 { break; }
    }

    v.max(0.5)
}

/// Fuel consumption [kg] for a segment.
pub fn fuel_burned_kg(
    config: &VesselConfig,
    mass_kg: f64,
    distance_nm: f64,
    conditions: &OceanConditions,
) -> f64 {
    let speed_ms = equilibrium_speed_ms(config, mass_kg, conditions);
    let speed_kts = speed_ms * 1.944;
    if speed_kts <= 0.0 {
        return f64::INFINITY;
    }
    let duration_h = distance_nm / speed_kts;
    // Power fraction = R × v / (P_shaft)
    let r = total_resistance_n(config, mass_kg, speed_ms, conditions);
    let p_shaft = config.propulsion.max_power_kw * 1000.0 * config.propulsion.propulsive_efficiency;
    let power_fraction = (r * speed_ms / p_shaft).clamp(0.0, 1.0);
    config.propulsion.fuel_rate_kg_h(power_fraction) * duration_h
}
