use std::{fs, process};

use seaforge_v2::{
    cost::CostBreakdown,
    environment::{GeoPoint, OceanConditions, RouteSegment, VoyageRoute},
    sim::{run_voyage, FailureMode},
    vessel::{
        HullGeometry, HullZone, MaterialGrade, MaterialModel, PropulsionSpec, SealQuality, VesselConfig,
        WeldQuality, ZoneSpec,
    },
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

fn main() {
    let args: Vec<String> = std::env::args().collect();

    match args.get(1).map(|s| s.as_str()) {
        Some("simulate") => {
            // seaforge_v2 simulate <vessel_config.json> <route.json> <output.json>
            let config_path = args.get(2).expect("missing vessel config path");
            let route_path = args.get(3).expect("missing route path");
            let out_path = args.get(4).map(|s| s.as_str()).unwrap_or("sim_output.json");
            cmd_simulate(config_path, route_path, out_path);
        }
        Some("simulate-params") => {
            // seaforge_v2 simulate-params <params.json> <output.json>
            let params_path = args.get(2).expect("missing simulation params path");
            let out_path = args.get(3).map(|s| s.as_str()).unwrap_or("sim_output.json");
            cmd_simulate_params(params_path, out_path);
        }
        Some("optimize") => {
            // seaforge_v2 optimize <search_space.json> <route.json> <output.json>
            let space_path = args.get(2).expect("missing search space path");
            let route_path = args.get(3).expect("missing route path");
            let out_path = args
                .get(4)
                .map(|s| s.as_str())
                .unwrap_or("optimizer_output.json");
            cmd_optimize(space_path, route_path, out_path);
        }
        Some("brief") => {
            // seaforge_v2 brief <mission_brief.json> [output.json] [--tier=lowest|standard|premium|cheapest]
            let brief_path = args.get(2).expect("missing mission brief path");
            let out_path = args.get(3).map(|s| s.as_str()).unwrap_or("brief_output.json");
            let tier = args.iter()
                .find(|s| s.starts_with("--tier="))
                .and_then(|s| s.strip_prefix("--tier="))
                .unwrap_or("standard");
            cmd_brief(brief_path, out_path, tier);
        }
        Some("demo") | None => {
            // Built-in demo: writes demo_output.json
            let out_path = args
                .get(2)
                .map(|s| s.as_str())
                .unwrap_or("demo_output.json");
            cmd_demo(out_path);
        }
        Some(cmd) => {
            eprintln!("Unknown command: {}", cmd);
            eprintln!("Usage:");
            eprintln!("  seaforge_v2 demo [output.json]");
            eprintln!("  seaforge_v2 brief <mission_brief.json> [output.json] [--tier=lowest|standard|premium|cheapest]");
            eprintln!("  seaforge_v2 simulate <config.json> <route.json> [output.json]");
            eprintln!("  seaforge_v2 simulate-params <params.json> [output.json]");
            eprintln!("  seaforge_v2 optimize <search_space.json> <route.json> [output.json]");
            process::exit(1);
        }
    }
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

fn cmd_simulate(config_path: &str, route_path: &str, out_path: &str) {
    let config: VesselConfig = load_json(config_path, "vessel config");
    let route: VoyageRoute = load_json(route_path, "voyage route");
    let outcome = run_voyage(&config, &route);
    let envelope = build_output(&config, &route, &outcome, None);
    write_json(out_path, &envelope);
    println!("Simulation complete → {}", out_path);
    print_summary(&outcome);
}

fn cmd_simulate_params(params_path: &str, out_path: &str) {
    let params: SimulationParams = load_json(params_path, "simulation params");
    let (config, route) = params.into_config_and_route().unwrap_or_else(|message| {
        eprintln!("Invalid simulation params: {}", message);
        process::exit(1);
    });
    let outcome = run_voyage(&config, &route);
    let envelope = build_output(&config, &route, &outcome, None);
    write_json(out_path, &envelope);
    println!("Simulation complete → {}", out_path);
    print_summary(&outcome);
}

fn cmd_optimize(space_path: &str, route_path: &str, out_path: &str) {
    let space: SearchSpace = load_json(space_path, "search space");
    let route: VoyageRoute = load_json(route_path, "voyage route");
    let opt_result = run_optimizer(&space, &route);
    let envelope = opt_result.as_ai_output();
    write_json(out_path, &envelope);
    println!("Optimizer complete → {}", out_path);
    if let Some(ref winner) = opt_result.cheapest_survivor {
        println!(
            "  Cheapest survivor: ${:.0}  ({} / {} / {} / {:.1}mm)",
            winner.cost_usd,
            winner.material,
            winner.weld_quality,
            winner.seal_quality,
            winner.thickness_mm,
        );
    } else {
        println!("  No surviving configuration found.");
    }
}

// ---------------------------------------------------------------------------
// Compact single-run simulation parameters
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default, Deserialize)]
struct SimulationParams {
    #[serde(default)]
    hull: HullParams,
    #[serde(default)]
    propulsion: PropulsionParams,
    #[serde(default)]
    construction: ConstructionParams,
    #[serde(default)]
    zones: Option<Vec<ZoneSpec>>,
    #[serde(default)]
    route: RouteParams,
    #[serde(default)]
    conditions: ConditionsParams,
}

impl SimulationParams {
    fn into_config_and_route(self) -> Result<(VesselConfig, VoyageRoute), String> {
        let hull = self.hull.apply(default_sim_hull());
        validate_hull(&hull)?;

        let propulsion = self.propulsion.apply(default_sim_propulsion());
        validate_propulsion(&propulsion)?;

        let config = if let Some(zones) = self.zones {
            if zones.is_empty() {
                return Err("zones must not be empty when provided".into());
            }
            for zone in &zones {
                if zone.thickness_m <= 0.0 {
                    return Err(format!("zone {:?} thickness_m must be positive", zone.zone));
                }
            }
            VesselConfig {
                hull: hull.clone(),
                zones,
                propulsion: propulsion.clone(),
            }
        } else {
            let construction = self.construction.apply(default_construction());
            if construction.thickness_m <= 0.0 {
                return Err("construction.thickness_m must be positive".into());
            }
            VesselConfig::uniform(
                hull.clone(),
                construction.material,
                construction.thickness_m,
                construction.weld_quality,
                construction.seal_quality,
                propulsion.clone(),
            )
        };

        let route_params = self.route.apply(default_route());
        if route_params.distance_nm <= 0.0 {
            return Err("route.distance_nm must be positive".into());
        }

        let conditions = self.conditions.apply(default_open_atlantic_conditions());
        validate_conditions(&conditions)?;

        let route = VoyageRoute {
            origin: route_params.origin,
            destination: route_params.destination,
            segments: vec![RouteSegment {
                from: route_params.origin,
                to: route_params.destination,
                distance_nm: route_params.distance_nm,
                heading_deg: route_params.heading_deg,
                label: route_params.label,
                conditions,
            }],
        };

        Ok((config, route))
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
struct HullParams {
    loa_m: Option<f64>,
    beam_m: Option<f64>,
    depth_m: Option<f64>,
    draft_m: Option<f64>,
    block_coeff: Option<f64>,
    waterplane_coeff: Option<f64>,
}

impl HullParams {
    fn apply(self, mut base: HullGeometry) -> HullGeometry {
        if let Some(value) = self.loa_m {
            base.loa_m = value;
        }
        if let Some(value) = self.beam_m {
            base.beam_m = value;
        }
        if let Some(value) = self.depth_m {
            base.depth_m = value;
        }
        if let Some(value) = self.draft_m {
            base.draft_m = value;
        }
        if let Some(value) = self.block_coeff {
            base.block_coeff = value;
        }
        if let Some(value) = self.waterplane_coeff {
            base.waterplane_coeff = value;
        }
        base
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
struct PropulsionParams {
    max_power_kw: Option<f64>,
    fuel_capacity_kg: Option<f64>,
    sfc_g_per_kwh: Option<f64>,
    propulsive_efficiency: Option<f64>,
    hull_drag_coeff: Option<f64>,
}

impl PropulsionParams {
    fn apply(self, mut base: PropulsionSpec) -> PropulsionSpec {
        if let Some(value) = self.max_power_kw {
            base.max_power_kw = value;
        }
        if let Some(value) = self.fuel_capacity_kg {
            base.fuel_capacity_kg = value;
        }
        if let Some(value) = self.sfc_g_per_kwh {
            base.sfc_g_per_kwh = value;
        }
        if let Some(value) = self.propulsive_efficiency {
            base.propulsive_efficiency = value;
        }
        if let Some(value) = self.hull_drag_coeff {
            base.hull_drag_coeff = value;
        }
        base
    }
}

#[derive(Debug, Clone, Default, Deserialize)]
struct ConstructionParams {
    material: Option<MaterialModel>,
    thickness_m: Option<f64>,
    weld_quality: Option<WeldQuality>,
    seal_quality: Option<SealQuality>,
}

impl ConstructionParams {
    fn apply(self, mut base: UniformConstruction) -> UniformConstruction {
        if let Some(value) = self.material {
            base.material = value;
        }
        if let Some(value) = self.thickness_m {
            base.thickness_m = value;
        }
        if let Some(value) = self.weld_quality {
            base.weld_quality = value;
        }
        if let Some(value) = self.seal_quality {
            base.seal_quality = value;
        }
        base
    }
}

#[derive(Debug, Clone)]
struct UniformConstruction {
    material: MaterialModel,
    thickness_m: f64,
    weld_quality: WeldQuality,
    seal_quality: SealQuality,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct RouteParams {
    origin: Option<GeoPoint>,
    destination: Option<GeoPoint>,
    distance_nm: Option<f64>,
    heading_deg: Option<f64>,
    label: Option<String>,
}

impl RouteParams {
    fn apply(self, mut base: SingleSegmentRoute) -> SingleSegmentRoute {
        if let Some(value) = self.origin {
            base.origin = value;
        }
        if let Some(value) = self.destination {
            base.destination = value;
        }
        if let Some(value) = self.distance_nm {
            base.distance_nm = value;
        }
        if let Some(value) = self.heading_deg {
            base.heading_deg = value;
        }
        if let Some(value) = self.label {
            base.label = value;
        }
        base
    }
}

#[derive(Debug, Clone)]
struct SingleSegmentRoute {
    origin: GeoPoint,
    destination: GeoPoint,
    distance_nm: f64,
    heading_deg: f64,
    label: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct ConditionsParams {
    hs_m: Option<f64>,
    tp_s: Option<f64>,
    jonswap_gamma: Option<f64>,
    encounter_angle_deg: Option<f64>,
    water_temp_c: Option<f64>,
    salinity_ppt: Option<f64>,
    ph: Option<f64>,
    wind_speed_ms: Option<f64>,
    slam_probability: Option<f64>,
}

impl ConditionsParams {
    fn apply(self, mut base: OceanConditions) -> OceanConditions {
        if let Some(value) = self.hs_m {
            base.hs_m = value;
        }
        if let Some(value) = self.tp_s {
            base.tp_s = value;
        }
        if let Some(value) = self.jonswap_gamma {
            base.jonswap_gamma = value;
        }
        if let Some(value) = self.encounter_angle_deg {
            base.encounter_angle_deg = value;
        }
        if let Some(value) = self.water_temp_c {
            base.water_temp_c = value;
        }
        if let Some(value) = self.salinity_ppt {
            base.salinity_ppt = value;
        }
        if let Some(value) = self.ph {
            base.ph = value;
        }
        if let Some(value) = self.wind_speed_ms {
            base.wind_speed_ms = value;
        }
        if let Some(value) = self.slam_probability {
            base.slam_probability = value;
        }
        base
    }
}

fn default_sim_hull() -> HullGeometry {
    HullGeometry {
        loa_m: 7.315,
        beam_m: 2.5,
        depth_m: 0.85,
        draft_m: 0.40,
        block_coeff: 0.44,
        waterplane_coeff: 0.76,
    }
}

fn default_sim_propulsion() -> PropulsionSpec {
    PropulsionSpec {
        max_power_kw: 300.0,
        fuel_capacity_kg: 2000.0,
        sfc_g_per_kwh: 220.0,
        propulsive_efficiency: 0.72,
        hull_drag_coeff: 0.007,
    }
}

fn default_construction() -> UniformConstruction {
    UniformConstruction {
        material: MaterialModel::Grade(MaterialGrade::MildSteelA),
        thickness_m: 0.004,
        weld_quality: WeldQuality::Economy,
        seal_quality: SealQuality::Economy,
    }
}

fn default_route() -> SingleSegmentRoute {
    SingleSegmentRoute {
        origin: GeoPoint::new(35.00, -74.50),
        destination: GeoPoint::new(32.30, -64.78),
        distance_nm: 580.0,
        heading_deg: 110.0,
        label: "Cape Hatteras -> Bermuda (open Atlantic)".into(),
    }
}

fn default_open_atlantic_conditions() -> OceanConditions {
    OceanConditions {
        hs_m: 3.2,
        tp_s: 10.0,
        jonswap_gamma: 3.5,
        encounter_angle_deg: 15.0,
        water_temp_c: 22.0,
        salinity_ppt: 36.0,
        ph: 8.1,
        wind_speed_ms: 14.0,
        slam_probability: 0.42,
    }
}

fn validate_hull(hull: &HullGeometry) -> Result<(), String> {
    if hull.loa_m <= 0.0 || hull.beam_m <= 0.0 || hull.depth_m <= 0.0 || hull.draft_m <= 0.0 {
        return Err("hull loa_m, beam_m, depth_m, and draft_m must be positive".into());
    }
    if !(0.0..=1.0).contains(&hull.block_coeff) || hull.block_coeff == 0.0 {
        return Err("hull.block_coeff must be within (0, 1]".into());
    }
    if !(0.0..=1.0).contains(&hull.waterplane_coeff) || hull.waterplane_coeff == 0.0 {
        return Err("hull.waterplane_coeff must be within (0, 1]".into());
    }
    Ok(())
}

fn validate_propulsion(propulsion: &PropulsionSpec) -> Result<(), String> {
    if propulsion.max_power_kw <= 0.0 {
        return Err("propulsion.max_power_kw must be positive".into());
    }
    if propulsion.fuel_capacity_kg <= 0.0 {
        return Err("propulsion.fuel_capacity_kg must be positive".into());
    }
    if propulsion.sfc_g_per_kwh <= 0.0 {
        return Err("propulsion.sfc_g_per_kwh must be positive".into());
    }
    if !(0.0..=1.0).contains(&propulsion.propulsive_efficiency)
        || propulsion.propulsive_efficiency == 0.0
    {
        return Err("propulsion.propulsive_efficiency must be within (0, 1]".into());
    }
    if propulsion.hull_drag_coeff <= 0.0 {
        return Err("propulsion.hull_drag_coeff must be positive".into());
    }
    Ok(())
}

fn validate_conditions(conditions: &OceanConditions) -> Result<(), String> {
    if conditions.hs_m < 0.0 {
        return Err("conditions.hs_m must be non-negative".into());
    }
    if conditions.tp_s <= 0.0 {
        return Err("conditions.tp_s must be positive".into());
    }
    if conditions.jonswap_gamma <= 0.0 {
        return Err("conditions.jonswap_gamma must be positive".into());
    }
    if conditions.salinity_ppt < 0.0 {
        return Err("conditions.salinity_ppt must be non-negative".into());
    }
    if !(0.0..=14.0).contains(&conditions.ph) {
        return Err("conditions.ph must be within [0, 14]".into());
    }
    if conditions.wind_speed_ms < 0.0 {
        return Err("conditions.wind_speed_ms must be non-negative".into());
    }
    if !(0.0..=1.0).contains(&conditions.slam_probability) {
        return Err("conditions.slam_probability must be within [0, 1]".into());
    }
    Ok(())
}

fn cmd_demo(out_path: &str) {
    println!("╔══════════════════════════════════════════════════════════╗");
    println!("║           SeaForge v2 — Mission Voyage Simulator        ║");
    println!("╚══════════════════════════════════════════════════════════╝\n");

    let route = build_norfolk_to_brest();
    println!(
        "Mission: Norfolk, VA → Brest, France  ({:.0} nm, {} segments)\n",
        route.total_distance_nm(),
        route.segments.len()
    );

    let hull = HullGeometry::default();
    let propulsion = PropulsionSpec::default();

    // ------------------------------------------------------------------
    // Demo: economy configuration — expected to fail
    // ------------------------------------------------------------------
    let economy = VesselConfig::uniform(
        hull.clone(),
        MaterialModel::Grade(MaterialGrade::MildSteelA),
        0.005,
        WeldQuality::Economy,
        SealQuality::Economy,
        propulsion.clone(),
    );
    println!("─── Economy build (Mild Steel A / Economy welds / Economy seals) ───");
    let economy_outcome = run_voyage(&economy, &route);
    print_summary(&economy_outcome);

    // ------------------------------------------------------------------
    // Optimizer sweep
    // ------------------------------------------------------------------
    let space = SearchSpace::default_sweep(hull.clone(), propulsion.clone());
    println!(
        "─── Optimizer: {} configurations ───\n",
        space.config_count()
    );
    let opt = run_optimizer(&space, &route);

    println!(
        "Evaluated {}, {} survived.\n",
        opt.configs_tested, opt.survivors_found
    );

    if let Some(ref w) = opt.cheapest_survivor {
        println!("╔══════════════════════════════════════════╗");
        println!("║   CHEAPEST SURVIVING CONFIGURATION       ║");
        println!("╠══════════════════════════════════════════╣");
        println!("║  Material  : {:35} ║", w.material);
        println!("║  Thickness : {:.1} mm {:31} ║", w.thickness_mm, "");
        println!("║  Weld      : {:35} ║", w.weld_quality);
        println!("║  Seal      : {:35} ║", w.seal_quality);
        println!("║  Cost      : ${:<8.0} {:26} ║", w.cost_usd, "");
        println!("╚══════════════════════════════════════════╝\n");
    } else {
        println!("No surviving configuration found in search space.\n");
    }

    // Build complete AI output
    let envelope = opt.as_ai_output();
    write_json(out_path, &envelope);
    println!("Full output written → {}\n", out_path);
}

// ---------------------------------------------------------------------------
// Optimizer
// ---------------------------------------------------------------------------

/// The parameter space the optimizer sweeps over.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchSpace {
    pub hull: HullGeometry,
    pub propulsion: PropulsionSpec,
    pub materials: Vec<String>,
    pub weld_qualities: Vec<String>,
    pub seal_qualities: Vec<String>,
    pub thicknesses_m: Vec<f64>,
}

impl SearchSpace {
    pub fn default_sweep(hull: HullGeometry, propulsion: PropulsionSpec) -> Self {
        Self {
            hull,
            propulsion,
            materials: vec![
                "MildSteelA".into(),
                "MildSteelE".into(),
                "Ah36".into(),
                "Dh36".into(),
                "Aluminum5083".into(),
            ],
            weld_qualities: vec!["Economy".into(), "Standard".into(), "Premium".into()],
            seal_qualities: vec!["Economy".into(), "Commercial".into(), "Marine".into()],
            thicknesses_m: vec![0.004, 0.005, 0.006, 0.008],
        }
    }

    pub fn config_count(&self) -> usize {
        self.materials.len()
            * self.weld_qualities.len()
            * self.seal_qualities.len()
            * self.thicknesses_m.len()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SurvivorEntry {
    pub material: String,
    pub thickness_mm: f64,
    pub weld_quality: String,
    pub seal_quality: String,
    pub cost_usd: f64,
    pub fuel_remaining_kg: f64,
    pub final_gm_m: f64,
    pub worst_zone_fatigue: f64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct OptimizerResult {
    pub configs_tested: usize,
    pub survivors_found: usize,
    pub cheapest_survivor: Option<SurvivorEntry>,
    pub all_survivors: Vec<SurvivorEntry>,
    pub failure_summary: std::collections::HashMap<String, usize>,
}

impl OptimizerResult {
    fn as_ai_output(&self) -> serde_json::Value {
        serde_json::json!({
            "schema_version": "1.0",
            "optimizer": {
                "configs_tested": self.configs_tested,
                "survivors_found": self.survivors_found,
                "cheapest_survivor": self.cheapest_survivor,
                "all_survivors": self.all_survivors,
                "failure_summary": self.failure_summary,
            }
        })
    }
}

fn run_optimizer(space: &SearchSpace, route: &VoyageRoute) -> OptimizerResult {
    let mut survivors: Vec<SurvivorEntry> = Vec::new();
    let mut failure_counts: std::collections::HashMap<String, usize> =
        std::collections::HashMap::new();
    let mut tested = 0usize;

    for mat_str in &space.materials {
        let Some(material) = parse_material(mat_str) else {
            continue;
        };
        for weld_str in &space.weld_qualities {
            let Some(weld) = parse_weld(weld_str) else {
                continue;
            };
            for seal_str in &space.seal_qualities {
                let Some(seal) = parse_seal(seal_str) else {
                    continue;
                };
                for &thick in &space.thicknesses_m {
                    let config = VesselConfig::uniform(
                        space.hull.clone(),
                        MaterialModel::Grade(material),
                        thick,
                        weld,
                        seal,
                        space.propulsion.clone(),
                    );
                    let outcome = run_voyage(&config, route);
                    tested += 1;

                    if outcome.survived() {
                        let worst_fatigue = outcome
                            .zone_summaries
                            .iter()
                            .map(|z| z.fatigue_consumed)
                            .fold(0.0_f64, f64::max);
                        survivors.push(SurvivorEntry {
                            material: mat_str.clone(),
                            thickness_mm: thick * 1000.0,
                            weld_quality: weld_str.clone(),
                            seal_quality: seal_str.clone(),
                            cost_usd: outcome.total_config_cost_usd,
                            fuel_remaining_kg: outcome.fuel_remaining_kg,
                            final_gm_m: outcome.final_gm_m,
                            worst_zone_fatigue: worst_fatigue,
                        });
                    } else if let Some(ref diag) = outcome.failure {
                        *failure_counts
                            .entry(diag.mode.label().to_string())
                            .or_insert(0) += 1;
                    }
                }
            }
        }
    }

    survivors.sort_by(|a, b| a.cost_usd.partial_cmp(&b.cost_usd).unwrap());
    let cheapest = survivors.first().cloned();
    let found = survivors.len();

    OptimizerResult {
        configs_tested: tested,
        survivors_found: found,
        cheapest_survivor: cheapest,
        all_survivors: survivors,
        failure_summary: failure_counts,
    }
}

// ---------------------------------------------------------------------------
// AI-friendly full output envelope
// ---------------------------------------------------------------------------

fn build_output(
    config: &VesselConfig,
    route: &VoyageRoute,
    outcome: &seaforge_v2::SimOutcome,
    optimizer: Option<&OptimizerResult>,
) -> serde_json::Value {
    let failure_json = outcome.failure.as_ref().map(|d| {
        let (why, fix) = d.mode.diagnosis();
        let failure_detail = match &d.mode {
            FailureMode::FatigueFailure { zone, damage_accumulated } => serde_json::json!({
                "failed_zone": zone.label(),
                "failed_metric": "fatigue",
                "failed_value": "100%",
                "raw_fatigue_consumed": damage_accumulated,
            }),
            FailureMode::BrittleFracture { zone, crack_half_length_m, .. } => serde_json::json!({
                "failed_zone": zone.label(),
                "failed_metric": "crack",
                "failed_value": format!("{:.1} mm", crack_half_length_m * 1000.0),
            }),
            FailureMode::SealBreachFlooding { zone, .. } => serde_json::json!({
                "failed_zone": zone.label(),
                "failed_metric": "seal",
                "failed_value": "failed",
            }),
            FailureMode::ColdTemperatureBrittleness { zone, water_temp_c, .. } => serde_json::json!({
                "failed_zone": zone.label(),
                "failed_metric": "temperature",
                "failed_value": format!("{:.1}°C", water_temp_c),
            }),
            FailureMode::Capsize { gm_m, .. } => serde_json::json!({
                "failed_zone": "Vessel",
                "failed_metric": "stability",
                "failed_value": format!("GM {:.2} m", gm_m),
            }),
            FailureMode::FuelExhaustion { .. } => serde_json::json!({
                "failed_zone": "Propulsion",
                "failed_metric": "fuel",
                "failed_value": "0%",
            }),
        };
        serde_json::json!({
            "mode": d.mode.label(),
            "distance_completed_nm": d.distance_completed_nm,
            "completion_pct": d.completion_pct(),
            "segment_index": d.segment_index,
            "segment_label": d.segment_label,
            "elapsed_h": d.elapsed_h,
            "why": why,
            "suggested_fix": fix,
            "detail": failure_detail,
        })
    });

    let zone_json: Vec<Value> = outcome
        .zone_summaries
        .iter()
        .map(|z| {
            serde_json::json!({
                "zone": z.zone.label(),
                "fatigue_consumed": z.fatigue_consumed,
                "corrosion_depth_mm": z.corrosion_depth_mm,
                "crack_half_length_mm": z.crack_half_length_mm,
                "peak_stress_mpa": z.peak_stress_mpa,
            })
        })
        .collect();

    let route_segments_json: Vec<Value> = route
        .segments
        .iter()
        .map(|segment| {
            serde_json::json!({
                "from": {
                    "lat_deg": segment.from.lat_deg,
                    "lon_deg": segment.from.lon_deg,
                },
                "to": {
                    "lat_deg": segment.to.lat_deg,
                    "lon_deg": segment.to.lon_deg,
                },
                "distance_nm": segment.distance_nm,
                "heading_deg": segment.heading_deg,
                "label": segment.label,
                "conditions": {
                    "hs_m": segment.conditions.hs_m,
                    "tp_s": segment.conditions.tp_s,
                    "jonswap_gamma": segment.conditions.jonswap_gamma,
                    "encounter_angle_deg": segment.conditions.encounter_angle_deg,
                    "water_temp_c": segment.conditions.water_temp_c,
                    "salinity_ppt": segment.conditions.salinity_ppt,
                    "ph": segment.conditions.ph,
                    "wind_speed_ms": segment.conditions.wind_speed_ms,
                    "slam_probability": segment.conditions.slam_probability,
                },
            })
        })
        .collect();

    let ticks_json: Vec<Value> = outcome
        .ticks
        .iter()
        .map(|t| {
            let zones: Vec<Value> = t
                .zones
                .iter()
                .map(|z| {
                    serde_json::json!({
                        "zone": z.zone.label(),
                        "fatigue_consumed": z.fatigue_consumed,
                        "corrosion_depth_mm": z.corrosion_depth_mm,
                        "crack_half_length_mm": z.crack_half_length_mm,
                        "peak_stress_mpa": z.peak_stress_mpa,
                    })
                })
                .collect();
            serde_json::json!({
                "segment_index": t.segment_index,
                "segment_label": t.segment_label,
                "distance_completed_nm": t.distance_completed_nm,
                "elapsed_h": t.elapsed_h,
                "speed_kts": t.speed_kts,
                "fuel_remaining_kg": t.fuel_remaining_kg,
                "gm_m": t.gm_m,
                "zones": zones,
                "failure": t.failure,
            })
        })
        .collect();

    let breakdown = CostBreakdown::for_config(config);
    let primary_zone = config.zones.first();
    let configuration_json = primary_zone.map(|zone| {
        let material_spec = zone.material.spec();
        serde_json::json!({
            "material": zone.material,
            "material_label": material_spec.label,
            "thickness_m": zone.thickness_m,
            "thickness_mm": zone.thickness_m * 1000.0,
            "weld_quality": zone.weld_quality,
            "weld_label": zone.weld_quality.label(),
            "seal_quality": zone.seal_quality,
            "seal_label": zone.seal_quality.label(),
            "shell_mass_kg": config.shell_mass_kg(),
            "propulsion": {
                "max_power_kw": config.propulsion.max_power_kw,
                "fuel_capacity_kg": config.propulsion.fuel_capacity_kg,
                "sfc_g_per_kwh": config.propulsion.sfc_g_per_kwh,
                "propulsive_efficiency": config.propulsion.propulsive_efficiency,
                "hull_drag_coeff": config.propulsion.hull_drag_coeff,
            },
            "zones": config.zones.iter().map(|z| serde_json::json!({
                "zone": z.zone.label(),
                "zone_key": format!("{:?}", z.zone),
                "material": z.material,
                "material_label": z.material.spec().label,
                "thickness_m": z.thickness_m,
                "thickness_mm": z.thickness_m * 1000.0,
                "weld_quality": z.weld_quality,
                "weld_label": z.weld_quality.label(),
                "seal_quality": z.seal_quality,
                "seal_label": z.seal_quality.label(),
            })).collect::<Vec<_>>(),
        })
    });

    serde_json::json!({
        "schema_version": "1.0",
        "status": if outcome.survived() { "survived" } else { "failed" },
        "voyage": {
            "total_distance_nm": route.total_distance_nm(),
            "segments": route.segments.len(),
            "origin": {
                "lat_deg": route.origin.lat_deg,
                "lon_deg": route.origin.lon_deg,
            },
            "destination": {
                "lat_deg": route.destination.lat_deg,
                "lon_deg": route.destination.lon_deg,
            },
            "route_segments": route_segments_json,
        },
        "result": {
            "distance_completed_nm": outcome.distance_completed_nm,
            "distance_completed_pct": outcome.completion_pct(),
            "time_elapsed_h": outcome.time_elapsed_h,
            "fuel_remaining_kg": outcome.fuel_remaining_kg,
            "final_gm_m": outcome.final_gm_m,
            "total_config_cost_usd": outcome.total_config_cost_usd,
            "cost_breakdown": {
                "material_usd": breakdown.material_usd,
                "weld_usd": breakdown.weld_usd,
                "seal_usd": breakdown.seal_usd,
                "fuel_capacity_usd": breakdown.fuel_capacity_usd,
            },
        },
        "configuration": configuration_json,
        "failure": failure_json,
        "zones": zone_json,
        "ticks": ticks_json,
        "optimizer": optimizer.map(|o| serde_json::json!({
            "configs_tested": o.configs_tested,
            "survivors_found": o.survivors_found,
            "cheapest_survivor": o.cheapest_survivor,
        })),
    })
}

// ---------------------------------------------------------------------------
// Mission brief command
// ---------------------------------------------------------------------------

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
struct MissionBrief {
    id: String,
    name: String,
    origin: BriefGeoPoint,
    destination: BriefGeoPoint,
    #[serde(default)]
    waypoints: Vec<BriefWaypoint>,
    distance_nm: f64,
    #[serde(default)]
    expected_duration_days: f64,
    primary_stressor: String,
    #[serde(default)]
    failure_modes_under_test: Vec<String>,
    environmental_profile: EnvProfile,
    #[serde(default)]
    zones: Option<Vec<ZoneSpec>>,
    #[serde(default)]
    propulsion: PropulsionParams,
}

#[derive(Debug, Clone, Deserialize)]
struct BriefGeoPoint {
    lat_deg: f64,
    lon_deg: f64,
    #[serde(default)]
    name: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct BriefWaypoint {
    name: String,
    lat_deg: f64,
    lon_deg: f64,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Deserialize)]
struct EnvProfile {
    wave_height_m: ValueRange,
    wave_period_s: ValueRange,
    slamming_probability: String,
    water_temp_c: ValueRange,
    salinity_ppt: f64,
    #[serde(default = "default_ice_risk")]
    ice_accretion_risk: String,
    #[serde(default)]
    ph: Option<f64>,
}

fn default_ice_risk() -> String {
    "none".into()
}

#[derive(Debug, Clone, Deserialize)]
struct ValueRange {
    avg: f64,
    #[serde(default)]
    max: Option<f64>,
    #[serde(default)]
    min: Option<f64>,
}

fn cmd_brief(brief_path: &str, out_path: &str, tier: &str) {
    let brief: MissionBrief = load_json(brief_path, "mission brief");

    // Build ordered point list: origin → waypoints → destination
    let mut points: Vec<(GeoPoint, String)> = Vec::new();
    points.push((
        GeoPoint::new(brief.origin.lat_deg, brief.origin.lon_deg),
        brief.origin.name.clone().unwrap_or_else(|| "Origin".into()),
    ));
    for wp in &brief.waypoints {
        points.push((GeoPoint::new(wp.lat_deg, wp.lon_deg), wp.name.clone()));
    }
    points.push((
        GeoPoint::new(brief.destination.lat_deg, brief.destination.lon_deg),
        brief.destination.name.clone().unwrap_or_else(|| "Destination".into()),
    ));

    let total_legs = points.len() - 1;
    let mut segments: Vec<RouteSegment> = Vec::new();

    for i in 0..total_legs {
        let (from, from_name) = &points[i];
        let (to, to_name) = &points[i + 1];
        let dist = haversine_nm(*from, *to);
        let heading = initial_bearing_deg(*from, *to);
        let conditions =
            conditions_for_leg(&brief.environmental_profile, &brief.primary_stressor, i, total_legs);
        segments.push(RouteSegment {
            from: *from,
            to: *to,
            distance_nm: dist,
            heading_deg: heading,
            label: format!("{} → {}", from_name, to_name),
            conditions,
        });
    }

    // Scale haversine distances to match the declared total — waypoints may be offshore
    // detours that inflate the computed route vs. the brief's expected_distance_nm.
    let haversine_total: f64 = segments.iter().map(|s| s.distance_nm).sum();
    if haversine_total > 0.0 && (haversine_total - brief.distance_nm).abs() / haversine_total > 0.05 {
        let scale = brief.distance_nm / haversine_total;
        for seg in &mut segments {
            seg.distance_nm *= scale;
        }
    }

    let route = VoyageRoute {
        origin: points.first().unwrap().0,
        destination: points.last().unwrap().0,
        segments,
    };

    // Vessel config by tier
    let hull = default_sim_hull();
    let propulsion = brief.propulsion.clone().apply(default_sim_propulsion());
    if let Err(err) = validate_propulsion(&propulsion) {
        eprintln!("mission brief propulsion invalid: {}", err);
        process::exit(1);
    }
    if let Some(zones) = brief.zones.clone() {
        if zones.is_empty() {
            eprintln!("mission brief zones cannot be empty");
            process::exit(1);
        }
        if zones.iter().any(|z| z.thickness_m <= 0.0) {
            eprintln!("mission brief zone thicknesses must be positive");
            process::exit(1);
        }

        println!(
            "Mission brief: {} [{}]  tier: custom",
            brief.name, brief.id,
        );
        println!(
            "Route: {} legs  ·  {:.0} nm  ·  stressor: {}",
            route.segments.len(),
            route.total_distance_nm(),
            brief.primary_stressor,
        );

        let config = VesselConfig {
            hull,
            zones,
            propulsion,
        };
        let outcome = run_voyage(&config, &route);
        let envelope = build_output(&config, &route, &outcome, None);
        write_json(out_path, &envelope);
        print_summary(&outcome);
        println!("Output → {}", out_path);
        return;
    }

    if tier == "cheapest" {
        println!(
            "Mission brief: {} [{}]  tier: cheapest",
            brief.name, brief.id,
        );
        println!(
            "Route: {} legs  ·  {:.0} nm  ·  stressor: {}",
            route.segments.len(),
            route.total_distance_nm(),
            brief.primary_stressor,
        );

        let space = SearchSpace::default_sweep(hull.clone(), propulsion.clone());
        let (config, opt) = run_per_zone_optimizer(&space, &route);
        let outcome = run_voyage(&config, &route);
        let envelope = build_output(&config, &route, &outcome, Some(&opt));
        write_json(out_path, &envelope);
        print_summary(&outcome);
        if opt.cheapest_survivor.is_some() {
            println!("Cheapest survivor: per-zone material configuration");
        } else {
            println!("No surviving per-zone configuration found; returned best-progress run.");
        }
        println!("Output → {}", out_path);
        return;
    }

    let (mat, thick, weld, seal) = match tier {
        "lowest"  => (MaterialGrade::MildSteelA, 0.004, WeldQuality::Economy,  SealQuality::Economy),
        "premium" => (MaterialGrade::Eh36,        0.008, WeldQuality::Premium,  SealQuality::Marine),
        _         => (MaterialGrade::Ah36,         0.006, WeldQuality::Standard, SealQuality::Marine),
    };
    let config = VesselConfig::uniform(hull, MaterialModel::Grade(mat), thick, weld, seal, propulsion);

    println!(
        "Mission brief: {} [{}]  tier: {}",
        brief.name, brief.id, tier
    );
    println!(
        "Route: {} legs  ·  {:.0} nm  ·  stressor: {}",
        route.segments.len(),
        route.total_distance_nm(),
        brief.primary_stressor,
    );

    let outcome = run_voyage(&config, &route);
    let envelope = build_output(&config, &route, &outcome, None);
    write_json(out_path, &envelope);
    print_summary(&outcome);
    println!("Output → {}", out_path);
}

/// Great-circle distance between two geographic points [nautical miles].
fn haversine_nm(from: GeoPoint, to: GeoPoint) -> f64 {
    const R_NM: f64 = 3440.065; // Earth mean radius in nautical miles
    let lat1 = from.lat_deg.to_radians();
    let lat2 = to.lat_deg.to_radians();
    let dlat = (to.lat_deg - from.lat_deg).to_radians();
    let dlon = (to.lon_deg - from.lon_deg).to_radians();
    let a = (dlat / 2.0).sin().powi(2) + lat1.cos() * lat2.cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().atan2((1.0 - a).sqrt());
    R_NM * c
}

/// Initial (forward) bearing from `from` to `to` [degrees true, 0 = north].
fn initial_bearing_deg(from: GeoPoint, to: GeoPoint) -> f64 {
    let lat1 = from.lat_deg.to_radians();
    let lat2 = to.lat_deg.to_radians();
    let dlon = (to.lon_deg - from.lon_deg).to_radians();
    let y = dlon.sin() * lat2.cos();
    let x = lat1.cos() * lat2.sin() - lat1.sin() * lat2.cos() * dlon.cos();
    (y.atan2(x).to_degrees() + 360.0) % 360.0
}

/// Derive per-leg `OceanConditions` from the brief's environmental profile, calibrated
/// to the primary stressor and the leg's position along the route.
fn conditions_for_leg(
    profile: &EnvProfile,
    stressor: &str,
    leg_idx: usize,
    total_legs: usize,
) -> OceanConditions {
    // t ∈ [0, 1]: fractional position along route (0 = departure, 1 = arrival)
    let t = if total_legs > 1 {
        leg_idx as f64 / (total_legs - 1) as f64
    } else {
        0.5
    };
    // Bell curve peaking at route midpoint
    let mid_peak = 1.0 - (2.0 * t - 1.0).powi(2);

    let base_hs = profile.wave_height_m.avg;
    let max_hs = profile.wave_height_m.max.unwrap_or(base_hs * 1.8);
    let base_tp = profile.wave_period_s.avg;
    let max_tp = profile.wave_period_s.max.unwrap_or(base_tp * 1.4);
    let base_temp = profile.water_temp_c.avg;
    let min_temp = profile.water_temp_c.min.unwrap_or(base_temp - 3.0);
    let max_temp = profile.water_temp_c.max.unwrap_or(base_temp + 2.0);
    let salinity = profile.salinity_ppt;
    let ph = profile.ph.unwrap_or(8.10);
    let base_slam = slam_prob_from_str(&profile.slamming_probability);

    match stressor {
        "sustained_structural_fatigue" => {
            // North Atlantic: conditions worsen mid-ocean, ease on approach to UK
            let hs = base_hs + (max_hs - base_hs) * (0.22 + 0.78 * mid_peak);
            let tp = base_tp + (max_tp - base_tp) * (0.18 + 0.72 * mid_peak);
            OceanConditions {
                hs_m: hs,
                tp_s: tp.max(6.0),
                jonswap_gamma: 3.6, // steeper storm swell, more damaging fatigue spectrum
                encounter_angle_deg: 4.0 + 10.0 * mid_peak,  // near head seas for sustained slamming
                water_temp_c: base_temp - (base_temp - min_temp) * (0.30 + 0.70 * t),
                salinity_ppt: salinity,
                ph,
                wind_speed_ms: 14.0 + 14.0 * mid_peak,
                slam_probability: (base_slam * (0.78 + 0.45 * mid_peak)).min(0.99),
            }
        }

        "capsize_stability" => {
            // Cape Horn: conditions escalate sharply toward Drake Passage (~70% along route),
            // peak with confused beam cross-swell, then ease slightly to Falklands.
            let horn_factor = if t < 0.70 {
                t / 0.70 // ramp up
            } else {
                1.0 - (t - 0.70) / 0.30 * 0.25 // slight easing — still severe
            }
            .clamp(0.0, 1.0);

            let hs = base_hs + (max_hs - base_hs) * horn_factor.powi(2);
            let tp = base_tp + (max_tp - base_tp) * horn_factor;
            OceanConditions {
                hs_m: hs,
                tp_s: tp.max(8.0),
                jonswap_gamma: 1.4 - 0.25 * horn_factor, // lengthening Southern Ocean swell
                // Encounter angle sweeps toward beam seas at peak (cross-swell attack)
                encounter_angle_deg: 15.0 + 65.0 * horn_factor,
                water_temp_c: base_temp + (min_temp - base_temp) * t,
                salinity_ppt: salinity,
                ph,
                wind_speed_ms: 12.0 + 20.0 * horn_factor,
                slam_probability: (base_slam * (0.35 + 1.05 * horn_factor.powi(2))).min(0.98),
            }
        }

        "corrosion_crack_cascade" => {
            // Persian Gulf: flat wave regime; chemistry constant and brutal.
            // Kill chain is slow: salinity 42 ppt + 32°C water → rapid corrosion → pitting crack.
            let slight_var = 0.12 * (2.0 * t - 1.0).abs();
            OceanConditions {
                hs_m: base_hs * (1.0 + slight_var),
                tp_s: base_tp,
                jonswap_gamma: 4.8, // fetch-limited steep Gulf chop
                encounter_angle_deg: 25.0,
                water_temp_c: max_temp - (max_temp - base_temp) * t * 0.25, // stays hot
                salinity_ppt: salinity, // 42 ppt throughout
                ph,                     // 7.9 — mildly acidic for electrochemical corrosion
                wind_speed_ms: 7.5,
                slam_probability: base_slam,
            }
        }

        "ice_accretion_cold_embrittlement" => {
            // Bering Sea: temperature is coldest at the open-sea midpoint (~50% of route).
            // Bell-curve cold factor guarantees min_temp is reached at the peak.
            // High winds drive spray icing; cold embrittlement threatens steel welds.
            let cold_factor = 1.0 - (2.0 * t - 1.0).powi(2); // peaks to 1.0 at t = 0.5

            let temp = base_temp + (min_temp - base_temp) * cold_factor;
            let hs = base_hs * (1.0 + 0.60 * cold_factor);
            OceanConditions {
                hs_m: hs,
                tp_s: base_tp,
                jonswap_gamma: 2.8,
                encounter_angle_deg: 18.0,
                water_temp_c: temp,
                salinity_ppt: salinity,
                ph,
                wind_speed_ms: 13.0 + 11.0 * cold_factor, // gale-force in open Bering
                slam_probability: (base_slam * (1.0 + 0.60 * cold_factor)).min(0.95),
            }
        }

        "fuel_exhaustion" => {
            // Pacific Fuel Run: benign but relentless. Slight quartering trade-wind swell.
            // The challenge is pure distance — no environmental severity.
            OceanConditions {
                hs_m: base_hs,
                tp_s: base_tp,
                jonswap_gamma: 2.2, // long open-Pacific swell, close to Pierson-Moskowitz
                encounter_angle_deg: 38.0, // persistent quartering NE trade-wind swell
                water_temp_c: max_temp - (max_temp - min_temp) * t * 0.6,
                salinity_ppt: salinity,
                ph,
                wind_speed_ms: 8.5,
                slam_probability: base_slam,
            }
        }

        // "combined" and fallback — South China Sea sweep
        _ => {
            // Short-period steep chop (high JONSWAP γ) + warm-high-salinity corrosion +
            // oblique cross-swell. All failure modes activated in parallel.
            let hs = base_hs + (max_hs - base_hs) * mid_peak * 0.55;
            let tp = base_tp
                + (profile.wave_period_s.max.unwrap_or(base_tp * 1.5) - base_tp)
                    * mid_peak
                    * 0.45;
            OceanConditions {
                hs_m: hs,
                tp_s: tp.max(5.0),
                jonswap_gamma: 5.8, // steep fetch-limited South China Sea chop
                // Cross-swell: oblique angle varies sinusoidally along route
                encounter_angle_deg: 22.0 + 35.0 * (t * std::f64::consts::PI).sin(),
                water_temp_c: max_temp - (max_temp - base_temp) * t * 0.25,
                salinity_ppt: salinity,
                ph,
                wind_speed_ms: 9.0 + 7.0 * mid_peak,
                slam_probability: (base_slam * (0.65 + 0.70 * mid_peak)).min(0.90),
            }
        }
    }
}

fn slam_prob_from_str(s: &str) -> f64 {
    match s {
        "none" => 0.02,
        "low" => 0.12,
        "moderate" => 0.32,
        "high" => 0.55,
        "extreme" => 0.80,
        _ => 0.25,
    }
}

#[derive(Debug, Clone)]
struct ZoneCandidate {
    material: MaterialGrade,
    thickness_m: f64,
    weld: WeldQuality,
    seal: SealQuality,
}

fn zone_candidate_cost_order(candidate: &ZoneCandidate, hull: &HullGeometry, propulsion: &PropulsionSpec) -> f64 {
    let config = VesselConfig::uniform(
        hull.clone(),
        MaterialModel::Grade(candidate.material),
        candidate.thickness_m,
        candidate.weld,
        candidate.seal,
        propulsion.clone(),
    );
    CostBreakdown::for_config(&config).total_usd
}

fn failure_zone(mode: &FailureMode) -> Option<HullZone> {
    match mode {
        FailureMode::FatigueFailure { zone, .. }
        | FailureMode::BrittleFracture { zone, .. }
        | FailureMode::SealBreachFlooding { zone, .. }
        | FailureMode::ColdTemperatureBrittleness { zone, .. } => Some(*zone),
        FailureMode::Capsize { .. } | FailureMode::FuelExhaustion { .. } => None,
    }
}

fn zone_index(zone: HullZone) -> usize {
    HullZone::all()
        .iter()
        .position(|candidate| *candidate == zone)
        .unwrap_or(0)
}

fn build_per_zone_config(
    hull: HullGeometry,
    propulsion: PropulsionSpec,
    candidates: &[ZoneCandidate],
    selections: &[usize],
) -> VesselConfig {
    let zones = HullZone::all()
        .iter()
        .enumerate()
        .map(|(idx, zone)| {
            let candidate = &candidates[selections[idx]];
            ZoneSpec {
                zone: *zone,
                material: MaterialModel::Grade(candidate.material),
                thickness_m: candidate.thickness_m,
                weld_quality: candidate.weld,
                seal_quality: candidate.seal,
            }
        })
        .collect();

    VesselConfig {
        hull,
        zones,
        propulsion,
    }
}

fn survivor_entry_from_config(config: &VesselConfig, outcome: &seaforge_v2::sim::SimOutcome) -> SurvivorEntry {
    let worst_fatigue = outcome
        .zone_summaries
        .iter()
        .map(|z| z.fatigue_consumed)
        .fold(0.0_f64, f64::max);

    SurvivorEntry {
        material: "Mixed per-zone".into(),
        thickness_mm: config
            .zones
            .iter()
            .map(|z| z.thickness_m * 1000.0)
            .fold(0.0_f64, f64::max),
        weld_quality: "Mixed per-zone".into(),
        seal_quality: "Mixed per-zone".into(),
        cost_usd: outcome.total_config_cost_usd,
        fuel_remaining_kg: outcome.fuel_remaining_kg,
        final_gm_m: outcome.final_gm_m,
        worst_zone_fatigue: worst_fatigue,
    }
}

fn run_per_zone_optimizer(space: &SearchSpace, route: &VoyageRoute) -> (VesselConfig, OptimizerResult) {
    let mut candidates: Vec<ZoneCandidate> = Vec::new();

    for mat_str in &space.materials {
        let Some(material) = parse_material(mat_str) else {
            continue;
        };
        for weld_str in &space.weld_qualities {
            let Some(weld) = parse_weld(weld_str) else {
                continue;
            };
            for seal_str in &space.seal_qualities {
                let Some(seal) = parse_seal(seal_str) else {
                    continue;
                };
                for &thickness_m in &space.thicknesses_m {
                    candidates.push(ZoneCandidate {
                        material,
                        thickness_m,
                        weld,
                        seal,
                    });
                }
            }
        }
    }

    candidates.sort_by(|a, b| {
        zone_candidate_cost_order(a, &space.hull, &space.propulsion)
            .partial_cmp(&zone_candidate_cost_order(b, &space.hull, &space.propulsion))
            .unwrap()
    });

    let fallback_candidate = ZoneCandidate {
        material: MaterialGrade::MildSteelA,
        thickness_m: 0.004,
        weld: WeldQuality::Economy,
        seal: SealQuality::Economy,
    };
    if candidates.is_empty() {
        candidates.push(fallback_candidate);
    }

    let mut selections = vec![0usize; HullZone::all().len()];
    let mut tested = 0usize;
    let mut failure_counts: std::collections::HashMap<String, usize> =
        std::collections::HashMap::new();
    let max_iterations = HullZone::all().len() * candidates.len();
    let mut best_config = build_per_zone_config(
        space.hull.clone(),
        space.propulsion.clone(),
        &candidates,
        &selections,
    );
    let mut best_distance = -1.0_f64;

    for _ in 0..max_iterations {
        let config = build_per_zone_config(
            space.hull.clone(),
            space.propulsion.clone(),
            &candidates,
            &selections,
        );
        let outcome = run_voyage(&config, route);
        tested += 1;

        if outcome.distance_completed_nm > best_distance {
            best_distance = outcome.distance_completed_nm;
            best_config = config.clone();
        }

        if outcome.survived() {
            let survivor = survivor_entry_from_config(&config, &outcome);
            return (
                config,
                OptimizerResult {
                    configs_tested: tested,
                    survivors_found: 1,
                    cheapest_survivor: Some(survivor.clone()),
                    all_survivors: vec![survivor],
                    failure_summary: failure_counts,
                },
            );
        }

        let Some(failure) = outcome.failure.as_ref() else {
            break;
        };
        *failure_counts
            .entry(failure.mode.label().to_string())
            .or_insert(0) += 1;

        let target_zone = failure_zone(&failure.mode).unwrap_or_else(|| {
            outcome
                .zone_summaries
                .iter()
                .max_by(|a, b| a.fatigue_consumed.partial_cmp(&b.fatigue_consumed).unwrap())
                .map(|z| z.zone)
                .unwrap_or(HullZone::Keel)
        });
        let mut idx = zone_index(target_zone);
        if selections[idx] + 1 >= candidates.len() {
            let next = selections
                .iter()
                .enumerate()
                .filter(|(_, selection)| **selection + 1 < candidates.len())
                .min_by_key(|(_, selection)| **selection)
                .map(|(zone_idx, _)| zone_idx);
            let Some(next_idx) = next else {
                break;
            };
            idx = next_idx;
        }
        selections[idx] += 1;
    }

    (
        best_config,
        OptimizerResult {
            configs_tested: tested,
            survivors_found: 0,
            cheapest_survivor: None,
            all_survivors: Vec::new(),
            failure_summary: failure_counts,
        },
    )
}

// ---------------------------------------------------------------------------
// Route definitions
// ---------------------------------------------------------------------------

fn build_norfolk_to_brest() -> VoyageRoute {
    let norfolk = GeoPoint::new(36.85, -76.30);
    let azores = GeoPoint::new(38.72, -27.22);
    let bay_biscay = GeoPoint::new(46.00, -8.00);
    let brest = GeoPoint::new(48.39, -4.49);

    VoyageRoute {
        origin: norfolk,
        destination: brest,
        segments: vec![
            RouteSegment {
                from: norfolk,
                to: azores,
                distance_nm: 1900.0,
                heading_deg: 75.0,
                label: "Norfolk → Azores (North Atlantic crossing)".into(),
                conditions: OceanConditions {
                    hs_m: 2.5,
                    tp_s: 9.0,
                    jonswap_gamma: 3.3,
                    encounter_angle_deg: 10.0,
                    water_temp_c: 18.0,
                    salinity_ppt: 36.0,
                    ph: 8.10,
                    wind_speed_ms: 10.0,
                    slam_probability: 0.12,
                },
            },
            RouteSegment {
                from: azores,
                to: bay_biscay,
                distance_nm: 1100.0,
                heading_deg: 55.0,
                label: "Azores → Bay of Biscay (North Atlantic storm belt)".into(),
                conditions: OceanConditions {
                    hs_m: 5.5,
                    tp_s: 13.0,
                    jonswap_gamma: 4.5,
                    encounter_angle_deg: 5.0,
                    water_temp_c: 13.0,
                    salinity_ppt: 35.0,
                    ph: 8.05,
                    wind_speed_ms: 18.0,
                    slam_probability: 0.38,
                },
            },
            RouteSegment {
                from: bay_biscay,
                to: brest,
                distance_nm: 250.0,
                heading_deg: 30.0,
                label: "Bay of Biscay → Brest (coastal approach)".into(),
                conditions: OceanConditions {
                    hs_m: 3.5,
                    tp_s: 11.0,
                    jonswap_gamma: 3.3,
                    encounter_angle_deg: 40.0,
                    water_temp_c: 12.0,
                    salinity_ppt: 34.5,
                    ph: 8.05,
                    wind_speed_ms: 13.0,
                    slam_probability: 0.22,
                },
            },
        ],
    }
}

// ---------------------------------------------------------------------------
// Parsers for string → enum
// ---------------------------------------------------------------------------

fn parse_material(s: &str) -> Option<MaterialGrade> {
    MaterialGrade::from_key(s)
}

fn parse_weld(s: &str) -> Option<WeldQuality> {
    Some(match s {
        "Premium" => WeldQuality::Premium,
        "Standard" => WeldQuality::Standard,
        "Economy" => WeldQuality::Economy,
        _ => return None,
    })
}

fn parse_seal(s: &str) -> Option<SealQuality> {
    Some(match s {
        "Marine" => SealQuality::Marine,
        "Commercial" => SealQuality::Commercial,
        "Economy" => SealQuality::Economy,
        _ => return None,
    })
}

// ---------------------------------------------------------------------------
// I/O helpers
// ---------------------------------------------------------------------------

fn load_json<T: for<'de> Deserialize<'de>>(path: &str, label: &str) -> T {
    let text = fs::read_to_string(path).unwrap_or_else(|e| {
        eprintln!("Cannot read {} '{}': {}", label, path, e);
        process::exit(1);
    });
    serde_json::from_str(&text).unwrap_or_else(|e| {
        eprintln!("Invalid JSON in {} '{}': {}", label, path, e);
        process::exit(1);
    })
}

fn write_json(path: &str, value: &serde_json::Value) {
    let text = serde_json::to_string_pretty(value).expect("serialisation failed");
    fs::write(path, text).unwrap_or_else(|e| {
        eprintln!("Cannot write '{}': {}", path, e);
        process::exit(1);
    });
}

fn print_summary(outcome: &seaforge_v2::SimOutcome) {
    match &outcome.failure {
        None => {
            println!(
                "  ✓ SURVIVED  {:.0}/{:.0} nm  ({:.1}h)  fuel left {:.0} kg  cost ${:.0}",
                outcome.distance_completed_nm,
                outcome.total_distance_nm,
                outcome.time_elapsed_h,
                outcome.fuel_remaining_kg,
                outcome.total_config_cost_usd
            );
        }
        Some(d) => {
            let (why, fix) = d.mode.diagnosis();
            println!(
                "  ✗ FAILED — {} at segment {} ({:.0} nm, {:.1}h)",
                d.mode.label(),
                d.segment_index + 1,
                d.distance_completed_nm,
                d.elapsed_h
            );
            println!("    Why: {}", why);
            println!("    Fix: {}", fix);
        }
    }
    println!();
}
