use crate::vessel::{HullGeometry, VesselConfig};

/// Metacentric height GM [m] for a given displacement and hull form.
///
/// GM = KB + BM - KG
///
/// KB  — centre of buoyancy above keel  (Morrish's formula)
/// BM  — metacentric radius             (I_waterplane / V_displaced)
/// KG  — centre of gravity above keel   (estimated from weight distribution)
pub fn metacentric_height_m(hull: &HullGeometry, mass_kg: f64, kg_m: f64) -> f64 {
    let draft = hull.draft_at_mass(mass_kg).max(0.05);
    let v = mass_kg / 1025.0; // displaced volume [m³]

    // Morrish's formula: KB = T × (Cb/(3(Cb − Cw)) + 1/2 × (5/6 − Cb/Cw))
    // Simplified for typical ASV hull forms:
    let kb = draft * (0.53 + 0.08 * hull.block_coeff);

    // BM = second moment of waterplane area / displaced volume
    let i_wp = hull.i_waterplane_m4();
    let bm = i_wp / v.max(0.01);

    kb + bm - kg_m
}

/// Estimate KG [m] from vessel configuration and current fuel load.
/// Higher fuel consumption raises KG as ballast fuel is consumed from lower tanks.
pub fn estimate_kg(config: &VesselConfig, fuel_remaining_kg: f64) -> f64 {
    let hull = &config.hull;

    // Light ship KG ≈ 55% of hull depth for typical ASV with low centre of mass
    let kg_lightship = hull.depth_m * 0.55;

    // Fuel is stored low; as fuel burns, CG rises slightly
    let fuel_fraction = fuel_remaining_kg / config.propulsion.fuel_capacity_kg.max(1.0);
    // Full fuel: KG pulled 0.06 × D downward; empty tanks: no effect
    let fuel_offset = -hull.depth_m * 0.06 * fuel_fraction;

    (kg_lightship + fuel_offset).clamp(hull.depth_m * 0.30, hull.depth_m * 0.80)
}

/// Minimum acceptable GM [m] for safe operation in open ocean.
/// DNV rule of thumb: GM_min ≥ 0.07 × B for small vessels.
pub fn gm_minimum(hull: &HullGeometry) -> f64 {
    0.07 * hull.beam_m
}

/// True if the vessel is at risk of capsize given current GM and sea state Hs.
/// Combines static stability margin with dynamic excitation from beam seas.
pub fn capsize_risk(gm_m: f64, hull: &HullGeometry, hs_m: f64, encounter_angle_deg: f64) -> bool {
    let gm_min = gm_minimum(hull);

    // Static: insufficient righting moment
    if gm_m < gm_min {
        return true;
    }

    // Dynamic: beam-sea resonance can capsize vessels with GM < 0.5×B even if positive
    let beam_sea_component = (encounter_angle_deg.to_radians().sin()).abs();
    let dynamic_threshold = gm_min + 0.015 * hs_m * hs_m * beam_sea_component;

    gm_m < dynamic_threshold
}
