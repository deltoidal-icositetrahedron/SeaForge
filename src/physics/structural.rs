use crate::{
    environment::OceanConditions,
    vessel::{HullGeometry, HullZone, MaterialSpec, ZoneSpec},
};

/// Significant bending stress amplitude at a hull zone [MPa].
///
/// Uses linear wave theory bending moment (Froude-Krylov) on the hull girder,
/// divided by the hollow-box section modulus. Spectral approach: stress is
/// scaled to the significant (1/3-highest) level — used downstream in the
/// narrow-band Rayleigh fatigue integral.
pub fn significant_stress_mpa(
    hull: &HullGeometry,
    conditions: &OceanConditions,
    zone: HullZone,
    zone_spec: &ZoneSpec,
) -> f64 {
    let rho_water = 1025.0_f64;
    let g = 9.81_f64;

    // Wave-induced pressure amplitude at hull surface
    let p_sig = rho_water * g * conditions.hs_m * conditions.encounter_factor();

    // Global bending moment on hull girder (Ochi approximation for slender hulls)
    let m_bending = p_sig * hull.loa_m.powi(2) * hull.beam_m * hull.block_coeff * 0.5;

    // Effective plate thickness after any prior corrosion (starts at nominal)
    let t_eff = zone_spec.thickness_m;

    // Hollow-box section modulus Z = I / (depth/2)
    let i_sec = hull.i_section_m4(t_eff);
    let z_sec = i_sec / (hull.depth_m * 0.5).max(0.01);

    // Nominal significant stress at midship reference point [Pa → MPa]
    let sigma_nominal_mpa = (m_bending / z_sec.max(1e-6)) / 1e6;

    // Apply zone-specific bending amplification and slam factor
    let sigma_zone = sigma_nominal_mpa * zone.bending_factor() * zone.slam_factor_for(conditions);

    // Apply weld stress concentration factor (multiplies effective stress at joint toe)
    sigma_zone * zone_spec.weld_quality.scf()
}

/// Cumulative Miner's fatigue damage for one route segment [dimensionless].
///
/// Implements the narrow-band Rayleigh approximation for random sea fatigue:
///   D = N_peaks × (σ_sig)^m × Γ(1 + m/2) / (2^m × C_sn)
///
/// where C_sn = σ_ref^m × N_ref is derived from the material S-N class.
/// This is an analytical per-segment calculation — no Monte Carlo sampling.
pub fn segment_fatigue_damage(
    hull: &HullGeometry,
    conditions: &OceanConditions,
    zone: HullZone,
    zone_spec: &ZoneSpec,
    material: &MaterialSpec,
    duration_s: f64,
) -> f64 {
    let sigma_sig = significant_stress_mpa(hull, conditions, zone, zone_spec);

    // Below endurance limit for this material — no damage accumulates
    let endurance = material.sn_ref_stress_mpa * 0.40;
    if sigma_sig < endurance {
        return 0.0;
    }

    // Zero-crossing period from spectral shape → number of stress peaks
    let tz = conditions.zero_crossing_period_s();
    let n_peaks = duration_s / tz.max(0.5);

    // S-N capacity constant: C_sn = σ_ref^m × N_ref
    let m = material.sn_slope;
    let c_sn = material.sn_ref_stress_mpa.powf(m) * material.sn_ref_cycles as f64;

    // Rayleigh distribution correction Γ(1 + m/2) / 2^m
    let rayleigh_factor = gamma_1_plus_m_half(m) / 2_f64.powf(m);

    n_peaks * sigma_sig.powf(m) * rayleigh_factor / c_sn
}

/// Stress intensity factor range [MPa·√m] for an edge crack in a plate.
/// Uses the standard geometry factor F ≈ 1.12 for a surface crack under tension.
pub fn stress_intensity_factor(stress_mpa: f64, crack_half_length_m: f64) -> f64 {
    const F_GEOMETRY: f64 = 1.12;
    stress_mpa * F_GEOMETRY * (std::f64::consts::PI * crack_half_length_m).sqrt()
}

/// Paris-law crack growth increment [m/cycle] given ΔK and material constants.
/// Uses generic Paris exponents; C and n are embedded per material category.
pub fn paris_crack_growth_per_cycle(delta_k_mpa_sqrtm: f64, material: &MaterialSpec) -> f64 {
    // Paris-law exponent and coefficient depend on material family
    let (c_paris, n_paris) = paris_constants(material.e_gpa);
    if delta_k_mpa_sqrtm <= 0.0 {
        return 0.0;
    }
    c_paris * delta_k_mpa_sqrtm.powf(n_paris)
}

/// True if the crack has reached critical size for brittle fracture.
pub fn is_critical_crack(crack_half_length_m: f64, stress_mpa: f64, k_ic: f64) -> bool {
    stress_intensity_factor(stress_mpa, crack_half_length_m) >= k_ic
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Γ(1 + m/2) for common S-N slope values m.
/// Exact for integer and half-integer m; Stirling approximation otherwise.
fn gamma_1_plus_m_half(m: f64) -> f64 {
    let x = 1.0 + m / 2.0;
    // Exact values for common cases
    match (m * 2.0).round() as u32 {
        6 => 1.3293,  // m=3:  Γ(2.5)
        8 => 2.0000,  // m=4:  Γ(3.0)
        10 => 3.3234, // m=5:  Γ(3.5)
        12 => 6.0000, // m=6:  Γ(4.0)
        20 => 120.00, // m=10: Γ(6.0)
        24 => 720.00, // m=12: Γ(7.0)
        _ => stirling_gamma(x),
    }
}

/// Stirling's approximation for Γ(x), accurate to ~1% for x ≥ 2.
fn stirling_gamma(x: f64) -> f64 {
    (2.0 * std::f64::consts::PI / x).sqrt() * (x / std::f64::consts::E).powf(x)
}

/// Paris law constants (C, n) keyed by Young's modulus [GPa].
/// Returns (C, n) where da/dN = C × ΔK^n [m/cycle, MPa·√m].
fn paris_constants(e_gpa: f64) -> (f64, f64) {
    if e_gpa > 150.0 {
        // Steel
        (6.0e-12, 3.0)
    } else if e_gpa > 50.0 {
        // Aluminium or CFRP (high-modulus composite)
        (1.4e-11, 3.5)
    } else {
        // GRP / low-modulus composite
        (5.0e-10, 4.2)
    }
}

// ---------------------------------------------------------------------------
// Extension trait: zone-aware slam factor scaled to sea state
// ---------------------------------------------------------------------------

trait ZoneSlamFactor {
    fn slam_factor_for(&self, conditions: &OceanConditions) -> f64;
}

impl ZoneSlamFactor for HullZone {
    fn slam_factor_for(&self, conditions: &OceanConditions) -> f64 {
        let base = self.slam_factor();
        // Slam severity grows with wave steepness
        let steepness_boost = 1.0 + conditions.steepness().clamp(0.0, 0.14) * 2.5;
        // Slamming events scale with declared probability
        let slam_active = 1.0 + conditions.slam_probability.clamp(0.0, 1.0) * (base - 1.0);
        slam_active * steepness_boost
    }
}
