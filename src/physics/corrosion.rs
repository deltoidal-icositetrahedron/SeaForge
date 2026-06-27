use crate::{environment::OceanConditions, vessel::MaterialGrade};

/// Seawater corrosion rate [mm/year] for a given material and ocean chemistry.
///
/// The causal chain is: salinity + temperature + pH → electrochemical attack rate.
/// Higher salinity increases ion concentration (up to ~35 ppt peak), warmer water
/// accelerates reaction kinetics (Arrhenius), and lower pH dissolves passive oxide films.
pub fn corrosion_rate_mm_yr(
    material: MaterialGrade,
    conditions: &OceanConditions,
    submerged: bool,
) -> f64 {
    let base = material.spec().base_corrosion_rate_mm_yr;
    if base <= 0.0 {
        return 0.0; // CFRP and fully inert materials
    }

    // Salinity factor: peak near typical open-ocean (~35 ppt); drops in fresher water
    let salinity_factor = (conditions.salinity_ppt / 35.0).clamp(0.3, 1.4);

    // Temperature factor: Arrhenius-type doubling per ~10°C above 10°C baseline
    let temp_delta = conditions.water_temp_c - 10.0;
    let temp_factor = 2_f64.powf(temp_delta / 10.0).clamp(0.4, 3.5);

    // pH factor: passive oxide film dissolves below ocean-normal pH of 8.1
    let ph_factor = (1.0 + 0.18 * (8.1 - conditions.ph).max(0.0)).clamp(1.0, 2.2);

    // Permanently submerged zones are ~1.4× faster than waterline / splash zones
    let immersion_factor = if submerged { 1.40 } else { 1.00 };

    base * salinity_factor * temp_factor * ph_factor * immersion_factor
}

/// Thickness lost to corrosion over a time period [m].
pub fn thickness_loss_m(
    material: MaterialGrade,
    conditions: &OceanConditions,
    submerged: bool,
    duration_h: f64,
) -> f64 {
    let rate_mm_yr = corrosion_rate_mm_yr(material, conditions, submerged);
    // Convert [mm/yr] × [hours] → [m]
    rate_mm_yr * duration_h / (8760.0 * 1000.0)
}

/// Fatigue damage multiplier due to corrosion-induced surface pitting.
///
/// Corrosion pits act as local stress raisers, accelerating fatigue crack initiation.
/// Returns a multiplier > 1.0 that scales Miner's damage when corrosion is present.
pub fn corrosion_fatigue_multiplier(
    material: MaterialGrade,
    conditions: &OceanConditions,
    elapsed_h: f64,
) -> f64 {
    if !material.corrodes() {
        return 1.0;
    }
    let rate = corrosion_rate_mm_yr(material, conditions, true);
    // Pit depth grows proportionally to √time (diffusion-limited)
    let pit_depth_mm = rate * (elapsed_h / 8760.0).sqrt();
    // Pit stress concentration scales with pit depth; typical pit SCF ~ 1 + 2√(d/r) ≈ 1 + 8√d
    let pit_scf = 1.0 + 8.0 * pit_depth_mm.sqrt();
    pit_scf.clamp(1.0, 4.0)
}
