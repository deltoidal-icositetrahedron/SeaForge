use serde::{Deserialize, Serialize};

use crate::vessel::{
    hull::{HullGeometry, HullZone},
    materials::{MaterialGrade, SealQuality, WeldQuality},
    propulsion::PropulsionSpec,
};

/// Construction specification for one hull zone.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoneSpec {
    pub zone: HullZone,
    pub material: MaterialGrade,
    pub thickness_m: f64,
    pub weld_quality: WeldQuality,
    pub seal_quality: SealQuality,
}

/// Full vessel configuration — everything the optimizer can vary.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VesselConfig {
    pub hull: HullGeometry,
    pub zones: Vec<ZoneSpec>,
    pub propulsion: PropulsionSpec,
}

impl VesselConfig {
    /// Build a config with identical material + quality across all zones.
    pub fn uniform(
        hull: HullGeometry,
        material: MaterialGrade,
        thickness_m: f64,
        weld: WeldQuality,
        seal: SealQuality,
        propulsion: PropulsionSpec,
    ) -> Self {
        let zones = HullZone::all()
            .iter()
            .map(|&zone| ZoneSpec {
                zone,
                material,
                thickness_m,
                weld_quality: weld,
                seal_quality: seal,
            })
            .collect();
        Self { hull, zones, propulsion }
    }

    /// Retrieve the spec for a specific zone.
    pub fn zone(&self, zone: HullZone) -> &ZoneSpec {
        self.zones
            .iter()
            .find(|z| z.zone == zone)
            .expect("all zones must be present in VesselConfig")
    }

    /// Shell mass of the entire hull [kg], summed across zones.
    /// Each zone is approximated as a fraction of total wetted area.
    pub fn shell_mass_kg(&self) -> f64 {
        let draft = self.hull.draft_m;
        let total_area = self.hull.wetted_area_m2(draft);
        let zone_area_fraction = total_area / HullZone::all().len() as f64;
        self.zones.iter().map(|z| {
            let spec = z.material.spec();
            zone_area_fraction * z.thickness_m * spec.density_kg_m3
        }).sum()
    }

    /// Total vessel operating mass including fuel [kg].
    pub fn total_mass_kg(&self) -> f64 {
        let systems_kg = 280.0 + self.hull.loa_m * self.hull.beam_m * 22.0;
        self.shell_mass_kg() + systems_kg + self.propulsion.fuel_capacity_kg
    }
}
