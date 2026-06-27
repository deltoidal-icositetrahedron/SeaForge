use serde::{Deserialize, Serialize};

/// Structural region of the hull for per-zone damage tracking.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum HullZone {
    Keel,
    BilgeStrake,
    BottomPlating,
    SidePlating,
    BowFlare,
    SternPlate,
    TransomFrame,
    WeatherDeck,
    BulkheadFrame,
}

impl HullZone {
    pub fn all() -> &'static [HullZone] {
        &[
            HullZone::Keel,
            HullZone::BilgeStrake,
            HullZone::BottomPlating,
            HullZone::SidePlating,
            HullZone::BowFlare,
            HullZone::SternPlate,
            HullZone::TransomFrame,
            HullZone::WeatherDeck,
            HullZone::BulkheadFrame,
        ]
    }

    /// Longitudinal bending stress amplification relative to midship bottom (reference = 1.0).
    pub fn bending_factor(self) -> f64 {
        match self {
            HullZone::Keel          => 1.35,
            HullZone::BilgeStrake   => 1.20,
            HullZone::BottomPlating => 1.10,
            HullZone::SidePlating   => 0.75,
            HullZone::BowFlare      => 1.05,
            HullZone::SternPlate    => 0.85,
            HullZone::TransomFrame  => 0.60,
            HullZone::WeatherDeck   => 0.90,
            HullZone::BulkheadFrame => 0.70,
        }
    }

    /// Impact pressure multiplier from wave slamming.
    pub fn slam_factor(self) -> f64 {
        match self {
            HullZone::BowFlare      => 2.80,
            HullZone::Keel          => 1.80,
            HullZone::BilgeStrake   => 1.40,
            HullZone::BottomPlating => 1.20,
            _                       => 1.00,
        }
    }

    /// True if this zone is continuously submerged (accelerated corrosion).
    pub fn is_submerged(self) -> bool {
        matches!(self, HullZone::Keel | HullZone::BilgeStrake | HullZone::BottomPlating)
    }

    pub fn label(self) -> &'static str {
        match self {
            HullZone::Keel          => "Keel",
            HullZone::BilgeStrake   => "Bilge Strake",
            HullZone::BottomPlating => "Bottom Plating",
            HullZone::SidePlating   => "Side Plating",
            HullZone::BowFlare      => "Bow Flare",
            HullZone::SternPlate    => "Stern Plate",
            HullZone::TransomFrame  => "Transom Frame",
            HullZone::WeatherDeck   => "Weather Deck",
            HullZone::BulkheadFrame => "Bulkhead Frame",
        }
    }
}

/// Moulded hull form dimensions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HullGeometry {
    /// Length overall [m]
    pub loa_m: f64,
    /// Moulded beam [m]
    pub beam_m: f64,
    /// Moulded depth to main deck [m]
    pub depth_m: f64,
    /// Design waterline draft [m]
    pub draft_m: f64,
    /// Block coefficient Cb = V / (L × B × T)
    pub block_coeff: f64,
    /// Waterplane area coefficient Cw
    pub waterplane_coeff: f64,
}

impl HullGeometry {
    /// Displaced volume at design draft [m³]
    pub fn displacement_m3(&self) -> f64 {
        self.loa_m * self.beam_m * self.draft_m * self.block_coeff
    }

    /// Displaced mass in seawater at design draft [kg]
    pub fn design_displacement_kg(&self) -> f64 {
        self.displacement_m3() * 1025.0
    }

    /// Waterplane area [m²]
    pub fn waterplane_area_m2(&self) -> f64 {
        self.loa_m * self.beam_m * self.waterplane_coeff
    }

    /// Second moment of waterplane area about centreline [m⁴]
    pub fn i_waterplane_m4(&self) -> f64 {
        self.loa_m * self.beam_m.powi(3) * self.waterplane_coeff / 12.0
    }

    /// Hull section second moment of area about neutral axis [m⁴]
    /// Uses hollow rectangular box with uniform plating thickness t [m].
    pub fn i_section_m4(&self, plate_thickness_m: f64) -> f64 {
        let b = self.beam_m;
        let d = self.depth_m;
        let t = plate_thickness_m.max(0.001);
        let b_inner = (b - 2.0 * t).max(0.0);
        let d_inner = (d - 2.0 * t).max(0.0);
        (b * d.powi(3) - b_inner * d_inner.powi(3)) / 12.0
    }

    /// Draft at an arbitrary displacement [kg], keeping same Cb and Cw.
    pub fn draft_at_mass(&self, mass_kg: f64) -> f64 {
        mass_kg / (1025.0 * self.loa_m * self.beam_m * self.block_coeff)
    }

    /// Wetted surface area approximation [m²] (Mumford formula)
    pub fn wetted_area_m2(&self, draft_m: f64) -> f64 {
        self.loa_m * (1.7 * draft_m + self.beam_m * self.block_coeff)
    }
}

impl Default for HullGeometry {
    fn default() -> Self {
        // Representative ocean-going ASV at ~7m LOA
        Self {
            loa_m: 7.3,
            beam_m: 2.4,
            depth_m: 1.1,
            draft_m: 0.32,
            block_coeff: 0.58,
            waterplane_coeff: 0.78,
        }
    }
}
