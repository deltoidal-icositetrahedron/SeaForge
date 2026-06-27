use serde::{Deserialize, Serialize};

/// Propulsion plant specification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PropulsionSpec {
    /// Maximum continuous shaft power [kW]
    pub max_power_kw: f64,
    /// Usable fuel capacity [kg] (diesel, ρ ≈ 840 kg/m³)
    pub fuel_capacity_kg: f64,
    /// Specific fuel consumption [g/kWh] — typical marine diesel ≈ 210-240
    pub sfc_g_per_kwh: f64,
    /// Overall propulsive efficiency ηD = hull × propeller × shaft
    pub propulsive_efficiency: f64,
    /// Drag coefficient on projected frontal area (used for calm-water resistance)
    pub hull_drag_coeff: f64,
}

impl Default for PropulsionSpec {
    fn default() -> Self {
        // Twin 90 kW marine diesels, ~1700 nm fuel endurance at cruising power.
        // hull_drag_coeff is Ct (total resistance coefficient on wetted area) ≈ 0.015
        // for a clean semi-displacement hull at Froude numbers up to ~0.5.
        Self {
            max_power_kw: 180.0,
            fuel_capacity_kg: 5_000.0,
            sfc_g_per_kwh: 220.0,
            propulsive_efficiency: 0.65,
            hull_drag_coeff: 0.015,
        }
    }
}

impl PropulsionSpec {
    /// Fuel burn rate [kg/h] at a given shaft power fraction (0..1).
    pub fn fuel_rate_kg_h(&self, power_fraction: f64) -> f64 {
        let brake_kw = self.max_power_kw * power_fraction.clamp(0.0, 1.0);
        self.sfc_g_per_kwh * brake_kw / 1000.0
    }

    /// Effective thrust [N] at maximum power.
    pub fn max_thrust_n(&self, speed_ms: f64) -> f64 {
        if speed_ms <= 0.0 {
            return self.max_power_kw * 1000.0 * self.propulsive_efficiency / 0.1;
        }
        self.max_power_kw * 1000.0 * self.propulsive_efficiency / speed_ms
    }
}
