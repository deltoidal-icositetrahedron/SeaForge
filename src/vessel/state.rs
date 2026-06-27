use serde::{Deserialize, Serialize};

use crate::vessel::hull::HullZone;

/// Live structural state of one hull zone during a voyage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoneState {
    pub zone: HullZone,
    /// Cumulative Miner's fatigue damage [0.0 = new, 1.0 = exhausted]
    pub fatigue_consumed: f64,
    /// Thickness lost to corrosion [m]
    pub corrosion_depth_m: f64,
    /// Paris-law crack half-length [m]
    pub crack_half_length_m: f64,
}

impl ZoneState {
    pub fn new(zone: HullZone) -> Self {
        Self {
            zone,
            fatigue_consumed: 0.0,
            corrosion_depth_m: 0.0,
            crack_half_length_m: 0.0,
        }
    }

    /// Net structural thickness remaining [m].
    pub fn net_thickness_m(&self, nominal: f64) -> f64 {
        (nominal - self.corrosion_depth_m).max(0.001)
    }

    /// True when Miner's cumulative damage has reached the failure threshold.
    pub fn is_fatigued(&self) -> bool {
        self.fatigue_consumed >= 1.0
    }
}

/// Full vessel runtime state — updated each simulation step.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VesselState {
    /// Distance completed along the route [nm]
    pub distance_nm: f64,
    /// Mission elapsed time [hours]
    pub elapsed_h: f64,
    /// Remaining fuel [kg]
    pub fuel_kg: f64,
    /// Metacentric height [m] — recomputed each segment
    pub gm_m: f64,
    /// Current over-ground speed [knots]
    pub speed_kts: f64,
    /// Structural state per zone
    pub zones: Vec<ZoneState>,
}

impl VesselState {
    pub fn initial(fuel_capacity_kg: f64, zones: Vec<ZoneState>, gm_m: f64) -> Self {
        Self {
            distance_nm: 0.0,
            elapsed_h: 0.0,
            fuel_kg: fuel_capacity_kg,
            gm_m,
            speed_kts: 0.0,
            zones,
        }
    }

    pub fn zone_mut(&mut self, zone: HullZone) -> &mut ZoneState {
        self.zones
            .iter_mut()
            .find(|z| z.zone == zone)
            .expect("zone must exist")
    }

    pub fn zone(&self, zone: HullZone) -> &ZoneState {
        self.zones
            .iter()
            .find(|z| z.zone == zone)
            .expect("zone must exist")
    }
}
