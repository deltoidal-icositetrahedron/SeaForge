use crate::vessel::{HullZone, VesselConfig};

const BASE_WELD_COST_PER_M_USD: f64 = 45.0;
const BASE_SEAL_COST_PER_M_USD: f64 = 18.0;

/// Total material + fabrication cost [USD] for a vessel configuration.
pub fn total_config_cost_usd(config: &VesselConfig) -> f64 {
    material_cost_usd(config) + weld_cost_usd(config) + seal_cost_usd(config)
}

/// Raw material cost [USD]: mass × cost_per_kg, summed across zones.
pub fn material_cost_usd(config: &VesselConfig) -> f64 {
    let draft = config.hull.draft_m;
    let total_area = config.hull.wetted_area_m2(draft);
    let zone_area = total_area / HullZone::all().len() as f64;

    config.zones.iter().map(|z| {
        let spec = z.material.spec();
        let mass_kg = zone_area * z.thickness_m * spec.density_kg_m3;
        mass_kg * spec.cost_per_kg_usd
    }).sum()
}

/// Fabrication cost [USD] for structural welds.
/// Approximates total weld length from hull perimeter and frame spacing.
pub fn weld_cost_usd(config: &VesselConfig) -> f64 {
    let h = &config.hull;
    // Total weld length: hull perimeter repeated every frame spacing (~0.4m)
    let perimeter = 2.0 * h.loa_m + 2.0 * h.beam_m + 4.0 * h.depth_m;
    let frame_count = (h.loa_m / 0.4).ceil() as f64;
    let total_weld_m = perimeter + frame_count * (h.beam_m + h.depth_m * 2.0);

    // Use the first zone's weld quality as representative (uniform-hull common case)
    let weld_factor = config
        .zones
        .first()
        .map(|z| z.weld_quality.cost_factor())
        .unwrap_or(1.0);

    total_weld_m * BASE_WELD_COST_PER_M_USD * weld_factor
}

/// Sealing cost [USD] for all watertight penetrations and deck seals.
pub fn seal_cost_usd(config: &VesselConfig) -> f64 {
    let h = &config.hull;
    let seal_perimeter = 2.0 * h.loa_m + 2.0 * h.beam_m;

    let seal_factor = config
        .zones
        .first()
        .map(|z| z.seal_quality.cost_factor())
        .unwrap_or(1.0);

    seal_perimeter * BASE_SEAL_COST_PER_M_USD * seal_factor
}

/// Break down cost into material, weld, and seal components.
pub struct CostBreakdown {
    pub material_usd: f64,
    pub weld_usd: f64,
    pub seal_usd: f64,
    pub total_usd: f64,
}

impl CostBreakdown {
    pub fn for_config(config: &VesselConfig) -> Self {
        let material_usd = material_cost_usd(config);
        let weld_usd = weld_cost_usd(config);
        let seal_usd = seal_cost_usd(config);
        Self {
            material_usd,
            weld_usd,
            seal_usd,
            total_usd: material_usd + weld_usd + seal_usd,
        }
    }
}
