use serde::{Deserialize, Serialize};

/// Sea state and water chemistry conditions at a voyage segment.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OceanConditions {
    /// Significant wave height Hs [m]
    pub hs_m: f64,
    /// Spectral peak period Tp [s]
    pub tp_s: f64,
    /// JONSWAP peakedness parameter γ (1.0 open ocean, 3.3 default, up to 7 fetch-limited)
    pub jonswap_gamma: f64,
    /// Wave encounter angle relative to vessel heading [degrees]
    /// 0° = head seas, 90° = beam seas, 180° = following seas
    pub encounter_angle_deg: f64,
    /// Water temperature at hull depth [°C]
    pub water_temp_c: f64,
    /// Salinity [g/kg, ppt] — typical open ocean ≈ 35
    pub salinity_ppt: f64,
    /// Seawater pH — typical ocean 8.1, acidified zones down to 7.8
    pub ph: f64,
    /// Surface wind speed [m/s]
    pub wind_speed_ms: f64,
    /// Probability of slamming impact per wave encounter [0..1]
    pub slam_probability: f64,
}

impl OceanConditions {
    /// Zero-crossing period Tz [s] derived from JONSWAP spectral shape.
    /// For γ = 3.3: Tz ≈ 0.710 × Tp; approaches 0.77 × Tp for γ = 1 (Pierson-Moskowitz).
    pub fn zero_crossing_period_s(&self) -> f64 {
        let gamma_correction = 1.0 - 0.132 * (self.jonswap_gamma - 1.0).max(0.0).sqrt();
        self.tp_s * gamma_correction.clamp(0.68, 0.78)
    }

    /// Encounter angle factor — reduces effective wave loading for non-head seas.
    pub fn encounter_factor(&self) -> f64 {
        let angle_rad = self.encounter_angle_deg.to_radians();
        (angle_rad.cos().abs() * 0.65 + 0.35).clamp(0.35, 1.0)
    }

    /// Wave steepness — proxy for breaking / slamming severity.
    pub fn steepness(&self) -> f64 {
        let lambda_p = 9.81 * self.tp_s.powi(2) / (2.0 * std::f64::consts::PI);
        if lambda_p > 0.0 { self.hs_m / lambda_p } else { 0.0 }
    }
}

impl Default for OceanConditions {
    fn default() -> Self {
        Self {
            hs_m: 2.5,
            tp_s: 9.0,
            jonswap_gamma: 3.3,
            encounter_angle_deg: 0.0,
            water_temp_c: 15.0,
            salinity_ppt: 35.0,
            ph: 8.1,
            wind_speed_ms: 10.0,
            slam_probability: 0.15,
        }
    }
}
