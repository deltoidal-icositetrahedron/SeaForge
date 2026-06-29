use serde::{Deserialize, Serialize};

use crate::environment::OceanConditions;
use crate::vessel::HullZone;

/// Why the voyage ended in failure.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum FailureMode {
    /// GM dropped below the minimum stability threshold.
    Capsize {
        gm_m: f64,
        gm_required_m: f64,
    },
    /// Miner's fatigue damage reached 1.0 at a specific zone.
    FatigueFailure {
        zone: HullZone,
        damage_accumulated: f64,
    },
    /// Paris-law crack reached critical fracture toughness.
    BrittleFracture {
        zone: HullZone,
        crack_half_length_m: f64,
        k_applied_mpa_sqrtm: f64,
        k_ic_mpa_sqrtm: f64,
    },
    /// Fuel exhausted before reaching destination.
    FuelExhaustion {
        distance_remaining_nm: f64,
    },
    /// Seal failure led to progressive flooding.
    SealBreachFlooding {
        zone: HullZone,
        elapsed_h: f64,
    },
    /// Water temperature below material minimum service temperature.
    ColdTemperatureBrittleness {
        zone: HullZone,
        water_temp_c: f64,
        min_rated_temp_c: f64,
    },
}

impl FailureMode {
    pub fn label(&self) -> &'static str {
        match self {
            FailureMode::Capsize { .. }                   => "Capsize",
            FailureMode::FatigueFailure { .. }            => "Fatigue Failure",
            FailureMode::BrittleFracture { .. }           => "Brittle Fracture",
            FailureMode::FuelExhaustion { .. }            => "Fuel Exhaustion",
            FailureMode::SealBreachFlooding { .. }        => "Seal Breach / Flooding",
            FailureMode::ColdTemperatureBrittleness { .. }=> "Cold-Temperature Embrittlement",
        }
    }

    /// Human-readable explanation of why this failure happened and what to change.
    pub fn diagnosis(&self) -> (String, String) {
        match self {
            FailureMode::Capsize { gm_m, gm_required_m } => (
                format!(
                    "Metacentric height GM = {:.3} m fell below safety minimum {:.3} m. \
                     Likely cause: fuel burned off, raising CG; or heavy beam seas.",
                    gm_m, gm_required_m
                ),
                "Increase beam or reduce depth. Add ballast capacity, or widen waterplane area \
                 to raise BM. Avoid beam-sea headings in high sea states.".into(),
            ),
            FailureMode::FatigueFailure { zone, damage_accumulated } => (
                format!(
                    "Miner's cumulative damage reached {:.2} at {} — weld toe cracking likely. \
                     S-N curve exhausted by repeated wave loading.",
                    damage_accumulated, zone.label()
                ),
                "Upgrade weld class (Premium reduces SCF from 2.65 → 1.50) or increase plate \
                 thickness. Higher-grade steel improves yield but not fatigue class without \
                 weld improvement.".into(),
            ),
            FailureMode::BrittleFracture { zone, k_applied_mpa_sqrtm, k_ic_mpa_sqrtm, .. } => (
                format!(
                    "Applied K = {:.1} MPa·√m exceeded material toughness K_IC = {:.1} MPa·√m \
                     at {}. Crack grew to critical size.",
                    k_applied_mpa_sqrtm, k_ic_mpa_sqrtm, zone.label()
                ),
                "Use a tougher material grade (DH36/EH36 vs AH36), reduce initial weld defect \
                 size (Premium weld), or add crack-arrest strakes adjacent to high-stress zones.".into(),
            ),
            FailureMode::FuelExhaustion { distance_remaining_nm } => (
                format!(
                    "Fuel exhausted with {:.0} nm remaining. Wave resistance or headwinds \
                     exceeded design fuel budget.",
                    distance_remaining_nm
                ),
                "Increase fuel capacity, reduce hull drag coefficient, or reroute to avoid \
                 the heaviest sea states. Reducing payload mass also improves range.".into(),
            ),
            FailureMode::SealBreachFlooding { zone, elapsed_h } => (
                format!(
                    "Seal breach at {} after {:.1} h — progressive flooding compromised \
                     watertight integrity.",
                    zone.label(), elapsed_h
                ),
                "Upgrade to Marine-grade EPDM seals. Add redundant bilge pump capacity and \
                 automated flooding detection to allow controlled response.".into(),
            ),
            FailureMode::ColdTemperatureBrittleness { zone, water_temp_c, min_rated_temp_c } => (
                format!(
                    "Water temperature {:.1}°C is below material minimum service temperature \
                     {:.1}°C at {}. Material may undergo ductile-brittle transition.",
                    water_temp_c, min_rated_temp_c, zone.label()
                ),
                "Switch to a cold-rated grade: MildSteelE (rated to −40°C), DH36, or EH36. \
                 Alternatively reroute to avoid sub-zero water temperatures.".into(),
            ),
        }
    }
}

/// Snapshot of which failure occurred and where in the voyage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FailureDiagnosis {
    pub mode: FailureMode,
    pub distance_completed_nm: f64,
    pub total_distance_nm: f64,
    pub segment_index: usize,
    pub segment_label: String,
    pub elapsed_h: f64,
}

impl FailureDiagnosis {
    pub fn completion_pct(&self) -> f64 {
        if self.total_distance_nm > 0.0 {
            self.distance_completed_nm / self.total_distance_nm * 100.0
        } else {
            0.0
        }
    }
}

/// Per-zone summary returned at the end of a simulation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoneSummary {
    pub zone: HullZone,
    pub fatigue_consumed: f64,
    pub corrosion_depth_mm: f64,
    pub crack_half_length_mm: f64,
    pub peak_stress_mpa: f64,
}

/// State snapshot at the end of one route segment — used for replay.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SegmentSnapshot {
    pub segment_index: usize,
    pub segment_label: String,
    pub distance_completed_nm: f64,
    pub elapsed_h: f64,
    pub speed_kts: f64,
    pub fuel_remaining_kg: f64,
    pub gm_m: f64,
    pub zones: Vec<ZoneSummary>,
    /// Set only on the tick where failure occurred.
    pub failure: Option<String>,
    /// Position-sampled ocean conditions in effect at this tick.
    #[serde(default)]
    pub conditions: Option<OceanConditions>,
}

/// What the voyage simulation returns.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SimOutcome {
    /// None = survived. Some = failed at this point.
    pub failure: Option<FailureDiagnosis>,
    pub distance_completed_nm: f64,
    pub total_distance_nm: f64,
    pub time_elapsed_h: f64,
    pub fuel_remaining_kg: f64,
    pub final_gm_m: f64,
    pub zone_summaries: Vec<ZoneSummary>,
    pub total_config_cost_usd: f64,
    pub ticks: Vec<SegmentSnapshot>,
}

impl SimOutcome {
    pub fn survived(&self) -> bool {
        self.failure.is_none()
    }

    pub fn completion_pct(&self) -> f64 {
        if self.total_distance_nm > 0.0 {
            self.distance_completed_nm / self.total_distance_nm * 100.0
        } else {
            0.0
        }
    }
}
