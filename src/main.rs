use std::{fs, process};

use seaforge_v2::{
    cost::CostBreakdown,
    environment::{GeoPoint, OceanConditions, RouteSegment, VoyageRoute},
    sim::run_voyage,
    vessel::{
        HullGeometry, MaterialGrade, PropulsionSpec, SealQuality, VesselConfig, WeldQuality,
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
            let route_path  = args.get(3).expect("missing route path");
            let out_path    = args.get(4).map(|s| s.as_str()).unwrap_or("sim_output.json");
            cmd_simulate(config_path, route_path, out_path);
        }
        Some("optimize") => {
            // seaforge_v2 optimize <search_space.json> <route.json> <output.json>
            let space_path = args.get(2).expect("missing search space path");
            let route_path = args.get(3).expect("missing route path");
            let out_path   = args.get(4).map(|s| s.as_str()).unwrap_or("optimizer_output.json");
            cmd_optimize(space_path, route_path, out_path);
        }
        Some("demo") | None => {
            // Built-in demo: writes demo_output.json
            let out_path = args.get(2).map(|s| s.as_str()).unwrap_or("demo_output.json");
            cmd_demo(out_path);
        }
        Some(cmd) => {
            eprintln!("Unknown command: {}", cmd);
            eprintln!("Usage:");
            eprintln!("  seaforge_v2 demo [output.json]");
            eprintln!("  seaforge_v2 simulate <config.json> <route.json> [output.json]");
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

fn cmd_optimize(space_path: &str, route_path: &str, out_path: &str) {
    let space: SearchSpace = load_json(space_path, "search space");
    let route: VoyageRoute = load_json(route_path, "voyage route");
    let opt_result = run_optimizer(&space, &route);
    let envelope = opt_result.as_ai_output();
    write_json(out_path, &envelope);
    println!("Optimizer complete → {}", out_path);
    if let Some(ref winner) = opt_result.cheapest_survivor {
        println!("  Cheapest survivor: ${:.0}  ({} / {} / {} / {:.1}mm)",
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

fn cmd_demo(out_path: &str) {
    println!("╔══════════════════════════════════════════════════════════╗");
    println!("║           SeaForge v2 — Mission Voyage Simulator        ║");
    println!("╚══════════════════════════════════════════════════════════╝\n");

    let route = build_norfolk_to_brest();
    println!("Mission: Norfolk, VA → Brest, France  ({:.0} nm, {} segments)\n",
        route.total_distance_nm(), route.segments.len());

    let hull = HullGeometry::default();
    let propulsion = PropulsionSpec::default();

    // ------------------------------------------------------------------
    // Demo: economy configuration — expected to fail
    // ------------------------------------------------------------------
    let economy = VesselConfig::uniform(
        hull.clone(), MaterialGrade::MildSteelA, 0.005,
        WeldQuality::Economy, SealQuality::Economy, propulsion.clone(),
    );
    println!("─── Economy build (Mild Steel A / Economy welds / Economy seals) ───");
    let economy_outcome = run_voyage(&economy, &route);
    print_summary(&economy_outcome);

    // ------------------------------------------------------------------
    // Optimizer sweep
    // ------------------------------------------------------------------
    let space = SearchSpace::default_sweep(hull.clone(), propulsion.clone());
    println!("─── Optimizer: {} configurations ───\n", space.config_count());
    let opt = run_optimizer(&space, &route);

    println!("Evaluated {}, {} survived.\n", opt.configs_tested, opt.survivors_found);

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
                "MildSteelA".into(), "MildSteelE".into(),
                "Ah36".into(), "Dh36".into(), "Aluminum5083".into(),
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
    let mut failure_counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut tested = 0usize;

    for mat_str in &space.materials {
        let Some(material) = parse_material(mat_str) else { continue };
        for weld_str in &space.weld_qualities {
            let Some(weld) = parse_weld(weld_str) else { continue };
            for seal_str in &space.seal_qualities {
                let Some(seal) = parse_seal(seal_str) else { continue };
                for &thick in &space.thicknesses_m {
                    let config = VesselConfig::uniform(
                        space.hull.clone(), material, thick, weld, seal,
                        space.propulsion.clone(),
                    );
                    let outcome = run_voyage(&config, route);
                    tested += 1;

                    if outcome.survived() {
                        let worst_fatigue = outcome.zone_summaries.iter()
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
                        *failure_counts.entry(diag.mode.label().to_string()).or_insert(0) += 1;
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
        serde_json::json!({
            "mode": d.mode.label(),
            "distance_completed_nm": d.distance_completed_nm,
            "completion_pct": d.completion_pct(),
            "segment_index": d.segment_index,
            "segment_label": d.segment_label,
            "elapsed_h": d.elapsed_h,
            "why": why,
            "suggested_fix": fix,
        })
    });

    let zone_json: Vec<Value> = outcome.zone_summaries.iter().map(|z| {
        serde_json::json!({
            "zone": z.zone.label(),
            "fatigue_consumed": z.fatigue_consumed,
            "corrosion_depth_mm": z.corrosion_depth_mm,
            "crack_half_length_mm": z.crack_half_length_mm,
            "peak_stress_mpa": z.peak_stress_mpa,
        })
    }).collect();

    let ticks_json: Vec<Value> = outcome.ticks.iter().map(|t| {
        let zones: Vec<Value> = t.zones.iter().map(|z| serde_json::json!({
            "zone": z.zone.label(),
            "fatigue_consumed": z.fatigue_consumed,
            "corrosion_depth_mm": z.corrosion_depth_mm,
            "crack_half_length_mm": z.crack_half_length_mm,
            "peak_stress_mpa": z.peak_stress_mpa,
        })).collect();
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
    }).collect();

    let breakdown = CostBreakdown::for_config(config);

    serde_json::json!({
        "schema_version": "1.0",
        "status": if outcome.survived() { "survived" } else { "failed" },
        "voyage": {
            "total_distance_nm": route.total_distance_nm(),
            "segments": route.segments.len(),
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
            },
        },
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
// Route definitions
// ---------------------------------------------------------------------------

fn build_norfolk_to_brest() -> VoyageRoute {
    let norfolk   = GeoPoint::new(36.85, -76.30);
    let azores    = GeoPoint::new(38.72, -27.22);
    let bay_biscay = GeoPoint::new(46.00, -8.00);
    let brest     = GeoPoint::new(48.39, -4.49);

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
    Some(match s {
        "MildSteelA"  => MaterialGrade::MildSteelA,
        "MildSteelE"  => MaterialGrade::MildSteelE,
        "Ah36"        => MaterialGrade::Ah36,
        "Dh36"        => MaterialGrade::Dh36,
        "Eh36"        => MaterialGrade::Eh36,
        "Aluminum5083" => MaterialGrade::Aluminum5083,
        "GrpEGlass"   => MaterialGrade::GrpEGlass,
        "CfrpEpoxy"   => MaterialGrade::CfrpEpoxy,
        _ => return None,
    })
}

fn parse_weld(s: &str) -> Option<WeldQuality> {
    Some(match s {
        "Premium"  => WeldQuality::Premium,
        "Standard" => WeldQuality::Standard,
        "Economy"  => WeldQuality::Economy,
        _ => return None,
    })
}

fn parse_seal(s: &str) -> Option<SealQuality> {
    Some(match s {
        "Marine"     => SealQuality::Marine,
        "Commercial" => SealQuality::Commercial,
        "Economy"    => SealQuality::Economy,
        _ => return None,
    })
}

// ---------------------------------------------------------------------------
// I/O helpers
// ---------------------------------------------------------------------------

fn load_json<T: for<'de> Deserialize<'de>>(path: &str, label: &str) -> T {
    let text = fs::read_to_string(path)
        .unwrap_or_else(|e| { eprintln!("Cannot read {} '{}': {}", label, path, e); process::exit(1); });
    serde_json::from_str(&text)
        .unwrap_or_else(|e| { eprintln!("Invalid JSON in {} '{}': {}", label, path, e); process::exit(1); })
}

fn write_json(path: &str, value: &serde_json::Value) {
    let text = serde_json::to_string_pretty(value).expect("serialisation failed");
    fs::write(path, text)
        .unwrap_or_else(|e| { eprintln!("Cannot write '{}': {}", path, e); process::exit(1); });
}

fn print_summary(outcome: &seaforge_v2::SimOutcome) {
    match &outcome.failure {
        None => {
            println!("  ✓ SURVIVED  {:.0}/{:.0} nm  ({:.1}h)  fuel left {:.0} kg  cost ${:.0}",
                outcome.distance_completed_nm, outcome.total_distance_nm,
                outcome.time_elapsed_h, outcome.fuel_remaining_kg,
                outcome.total_config_cost_usd);
        }
        Some(d) => {
            let (why, fix) = d.mode.diagnosis();
            println!("  ✗ FAILED — {} at segment {} ({:.0} nm, {:.1}h)",
                d.mode.label(), d.segment_index + 1,
                d.distance_completed_nm, d.elapsed_h);
            println!("    Why: {}", why);
            println!("    Fix: {}", fix);
        }
    }
    println!();
}
