use crate::{
    cost::total_config_cost_usd,
    environment::VoyageRoute,
    physics::{
        corrosion::{corrosion_fatigue_multiplier, thickness_loss_m},
        resistance::{equilibrium_speed_ms, fuel_burned_kg},
        stability::{capsize_risk, estimate_kg, gm_minimum, metacentric_height_m},
        structural::{
            is_critical_crack, paris_crack_growth_per_cycle, segment_fatigue_damage,
            significant_stress_mpa, stress_intensity_factor,
        },
    },
    sim::outcome::{FailureDiagnosis, FailureMode, SimOutcome, ZoneSummary},
    vessel::{HullZone, VesselConfig, VesselState, ZoneState},
};

/// Run a complete voyage simulation for the given vessel configuration and route.
///
/// Each route segment is processed analytically — no inner time-stepping.
/// Fatigue uses the narrow-band Rayleigh spectral method.
/// Corrosion, stability, and fuel are updated between segments.
///
/// Returns a `SimOutcome` describing whether the vessel survived and why it failed if not.
pub fn run_voyage(config: &VesselConfig, route: &VoyageRoute) -> SimOutcome {
    let total_distance_nm = route.total_distance_nm();
    let total_cost = total_config_cost_usd(config);

    // Initialise zone states from config
    let zone_states: Vec<ZoneState> = config
        .zones
        .iter()
        .map(|z| ZoneState::new(z.zone))
        .collect();

    // Initial stability check before departure
    let initial_mass = config.total_mass_kg();
    let initial_kg = estimate_kg(config, config.propulsion.fuel_capacity_kg);
    let initial_gm = metacentric_height_m(&config.hull, initial_mass, initial_kg);

    let mut state = VesselState::initial(
        config.propulsion.fuel_capacity_kg,
        zone_states,
        initial_gm,
    );

    // Peak stress tracker for reporting
    let mut peak_stress: std::collections::HashMap<HullZone, f64> =
        HullZone::all().iter().map(|&z| (z, 0.0)).collect();

    for (seg_idx, segment) in route.segments.iter().enumerate() {
        let conditions = &segment.conditions;
        let current_mass = config.total_mass_kg() - (config.propulsion.fuel_capacity_kg - state.fuel_kg);
        let current_mass = current_mass.max(500.0);

        // ----------------------------------------------------------------
        // Stability check at start of segment
        // ----------------------------------------------------------------
        let kg = estimate_kg(config, state.fuel_kg);
        state.gm_m = metacentric_height_m(&config.hull, current_mass, kg);
        let gm_min = gm_minimum(&config.hull);

        if capsize_risk(state.gm_m, &config.hull, conditions.hs_m, conditions.encounter_angle_deg) {
            return build_failure(
                FailureMode::Capsize {
                    gm_m: state.gm_m,
                    gm_required_m: gm_min,
                },
                &state,
                seg_idx,
                &segment.label,
                total_distance_nm,
                total_cost,
                &peak_stress,
                config,
            );
        }

        // ----------------------------------------------------------------
        // Speed and segment duration
        // ----------------------------------------------------------------
        let speed_ms = equilibrium_speed_ms(config, current_mass, conditions);
        let speed_kts = speed_ms * 1.944;
        state.speed_kts = speed_kts;
        let duration_h = segment.distance_nm / speed_kts.max(0.1);
        let duration_s = duration_h * 3600.0;

        // ----------------------------------------------------------------
        // Fuel consumption
        // ----------------------------------------------------------------
        let fuel_burned = fuel_burned_kg(config, current_mass, segment.distance_nm, conditions);
        if fuel_burned >= state.fuel_kg {
            let distance_on_remaining = state.fuel_kg / fuel_burned.max(1.0) * segment.distance_nm;
            return build_failure(
                FailureMode::FuelExhaustion {
                    distance_remaining_nm: total_distance_nm
                        - state.distance_nm
                        - distance_on_remaining,
                },
                &state,
                seg_idx,
                &segment.label,
                total_distance_nm,
                total_cost,
                &peak_stress,
                config,
            );
        }
        state.fuel_kg -= fuel_burned;

        // ----------------------------------------------------------------
        // Per-zone structural assessment
        // ----------------------------------------------------------------
        let elapsed_h_snapshot = state.elapsed_h;
        for zone_spec in &config.zones {
            let zone = zone_spec.zone;
            let material = zone_spec.material;
            let mat_spec = material.spec();
            let zone_state = state.zone_mut(zone);

            // Cold-temperature embrittlement check
            if conditions.water_temp_c < mat_spec.min_temp_c {
                return build_failure(
                    FailureMode::ColdTemperatureBrittleness {
                        zone,
                        water_temp_c: conditions.water_temp_c,
                        min_rated_temp_c: mat_spec.min_temp_c,
                    },
                    &state,
                    seg_idx,
                    &segment.label,
                    total_distance_nm,
                    total_cost,
                    &peak_stress,
                    config,
                );
            }

            // Corrosion: update thickness loss
            let submerged = zone.is_submerged();
            let new_loss = thickness_loss_m(material, conditions, submerged, duration_h);
            zone_state.corrosion_depth_m += new_loss;

            // Guard against plate consumed through
            let net_t = zone_state.net_thickness_m(zone_spec.thickness_m);
            if net_t < 0.0005 {
                return build_failure(
                    FailureMode::FatigueFailure {
                        zone,
                        damage_accumulated: zone_state.fatigue_consumed,
                    },
                    &state,
                    seg_idx,
                    &segment.label,
                    total_distance_nm,
                    total_cost,
                    &peak_stress,
                    config,
                );
            }

            // Spectral fatigue damage over this segment
            let corr_multiplier =
                corrosion_fatigue_multiplier(material, conditions, elapsed_h_snapshot);
            let base_damage = segment_fatigue_damage(
                &config.hull,
                conditions,
                zone,
                zone_spec,
                mat_spec,
                duration_s,
            );
            zone_state.fatigue_consumed += base_damage * corr_multiplier;

            // Track peak stress for reporting
            let sig_stress = significant_stress_mpa(&config.hull, conditions, zone, zone_spec);
            let entry = peak_stress.entry(zone).or_insert(0.0);
            if sig_stress > *entry {
                *entry = sig_stress;
            }

            // Fatigue failure check
            if zone_state.is_fatigued() {
                return build_failure(
                    FailureMode::FatigueFailure {
                        zone,
                        damage_accumulated: zone_state.fatigue_consumed,
                    },
                    &state,
                    seg_idx,
                    &segment.label,
                    total_distance_nm,
                    total_cost,
                    &peak_stress,
                    config,
                );
            }

            // Paris-law crack growth
            let delta_stress = sig_stress * 2.0; // peak-to-trough range
            let tz = conditions.zero_crossing_period_s();
            let n_cycles = duration_s / tz.max(0.5);
            let dk = stress_intensity_factor(delta_stress, zone_state.crack_half_length_m.max(1e-6));
            let da_per_cycle = paris_crack_growth_per_cycle(dk, mat_spec);
            zone_state.crack_half_length_m += da_per_cycle * n_cycles;

            // Brittle fracture check: K_I ≥ K_IC
            let k_applied = stress_intensity_factor(sig_stress, zone_state.crack_half_length_m);
            if is_critical_crack(zone_state.crack_half_length_m, sig_stress, mat_spec.k_ic_mpa_sqrtm) {
                return build_failure(
                    FailureMode::BrittleFracture {
                        zone,
                        crack_half_length_m: zone_state.crack_half_length_m,
                        k_applied_mpa_sqrtm: k_applied,
                        k_ic_mpa_sqrtm: mat_spec.k_ic_mpa_sqrtm,
                    },
                    &state,
                    seg_idx,
                    &segment.label,
                    total_distance_nm,
                    total_cost,
                    &peak_stress,
                    config,
                );
            }

            // Seal failure: accumulate survival probability
            let hourly_survival = zone_spec.seal_quality.hourly_survival_prob();
            let seal_survival = hourly_survival.powf(duration_h);
            // Treat survival < 50% per segment as definitive failure
            if seal_survival < 0.50 {
                return build_failure(
                    FailureMode::SealBreachFlooding {
                        zone,
                        elapsed_h: state.elapsed_h,
                    },
                    &state,
                    seg_idx,
                    &segment.label,
                    total_distance_nm,
                    total_cost,
                    &peak_stress,
                    config,
                );
            }
        }

        // Advance voyage state
        state.distance_nm += segment.distance_nm;
        state.elapsed_h += duration_h;
    }

    // Mission complete — build survivor outcome
    let zone_summaries = build_zone_summaries(&state, &peak_stress, config);
    SimOutcome {
        failure: None,
        distance_completed_nm: state.distance_nm,
        total_distance_nm,
        time_elapsed_h: state.elapsed_h,
        fuel_remaining_kg: state.fuel_kg,
        final_gm_m: state.gm_m,
        zone_summaries,
        total_config_cost_usd: total_cost,
    }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

fn build_failure(
    mode: FailureMode,
    state: &VesselState,
    seg_idx: usize,
    seg_label: &str,
    total_distance_nm: f64,
    total_cost: f64,
    peak_stress: &std::collections::HashMap<HullZone, f64>,
    config: &VesselConfig,
) -> SimOutcome {
    let diagnosis = FailureDiagnosis {
        mode,
        distance_completed_nm: state.distance_nm,
        total_distance_nm,
        segment_index: seg_idx,
        segment_label: seg_label.to_string(),
        elapsed_h: state.elapsed_h,
    };
    SimOutcome {
        failure: Some(diagnosis),
        distance_completed_nm: state.distance_nm,
        total_distance_nm,
        time_elapsed_h: state.elapsed_h,
        fuel_remaining_kg: state.fuel_kg,
        final_gm_m: state.gm_m,
        zone_summaries: build_zone_summaries(state, peak_stress, config),
        total_config_cost_usd: total_cost,
    }
}

fn build_zone_summaries(
    state: &VesselState,
    peak_stress: &std::collections::HashMap<HullZone, f64>,
    _config: &VesselConfig,
) -> Vec<ZoneSummary> {
    state
        .zones
        .iter()
        .map(|zs| {
            ZoneSummary {
                zone: zs.zone,
                fatigue_consumed: zs.fatigue_consumed,
                corrosion_depth_mm: zs.corrosion_depth_m * 1000.0,
                crack_half_length_mm: zs.crack_half_length_m * 1000.0,
                peak_stress_mpa: *peak_stress.get(&zs.zone).unwrap_or(&0.0),
            }
        })
        .collect()
}
