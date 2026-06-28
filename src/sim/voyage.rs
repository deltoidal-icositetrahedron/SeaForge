use crate::{
    cost::total_config_cost_usd,
    environment::VoyageRoute,
    physics::{
        corrosion::{corrosion_fatigue_multiplier, thickness_loss_m},
        ice::{gm_with_ice, spray_icing_rate_kg_per_h},
        resistance::{equilibrium_speed_ms, fuel_burned_kg},
        stability::{capsize_risk, estimate_kg, gm_minimum, metacentric_height_m},
        structural::{
            is_critical_crack, paris_crack_growth_per_cycle, segment_fatigue_damage,
            significant_stress_mpa, stress_intensity_factor,
        },
    },
    sim::outcome::{FailureDiagnosis, FailureMode, SegmentSnapshot, SimOutcome, ZoneSummary},
    vessel::{HullZone, VesselConfig, VesselState, ZoneState},
};

const STEP_H: f64 = 1.0;
const DAMAGE_RATE_MULTIPLIER: f64 = 3.4;
const CRACK_GROWTH_MULTIPLIER: f64 = 0.12;
const CORROSION_RATE_MULTIPLIER: f64 = 5.0;

pub fn run_voyage(config: &VesselConfig, route: &VoyageRoute) -> SimOutcome {
    let total_distance_nm = route.total_distance_nm();
    let total_cost = total_config_cost_usd(config);

    let zone_states: Vec<ZoneState> = config
        .zones
        .iter()
        .map(|z| ZoneState::new(z.zone, z.weld_quality.initial_crack_m() * 0.25))
        .collect();

    let initial_mass = config.total_mass_kg();
    let initial_kg = estimate_kg(config, config.propulsion.fuel_capacity_kg);
    let initial_gm = metacentric_height_m(&config.hull, initial_mass, initial_kg);

    let mut state = VesselState::initial(
        config.propulsion.fuel_capacity_kg,
        zone_states,
        initial_gm,
    );

    let mut peak_stress: std::collections::HashMap<HullZone, f64> =
        HullZone::all().iter().map(|&z| (z, 0.0)).collect();

    let mut ticks: Vec<SegmentSnapshot> = Vec::new();
    if let Some(first_segment) = route.segments.first() {
        ticks.push(snapshot_at(
            &state,
            0,
            &first_segment.label,
            0.0,
            &peak_stress,
            config,
            None,
        ));
    }

    for (seg_idx, segment) in route.segments.iter().enumerate() {
        let conditions = &segment.conditions;

        // ----------------------------------------------------------------
        // Stability check at segment start (conditions constant per segment)
        // ----------------------------------------------------------------
        let current_mass = (config.total_mass_kg()
            - (config.propulsion.fuel_capacity_kg - state.fuel_kg))
            .max(500.0);
        let kg = estimate_kg(config, state.fuel_kg);
        state.gm_m = metacentric_height_m(&config.hull, current_mass, kg);
        let gm_min = gm_minimum(&config.hull);

        if capsize_risk(state.gm_m, &config.hull, conditions.hs_m, conditions.encounter_angle_deg) {
            // Report the effective dynamic threshold, not just the static floor
            let beam_component = (conditions.encounter_angle_deg.to_radians().sin()).abs();
            let gm_effective_min = (gm_min + 0.015 * conditions.hs_m.powi(2) * beam_component)
                .max(gm_min);
            let mode = FailureMode::Capsize { gm_m: state.gm_m, gm_required_m: gm_effective_min };
            ticks.push(snapshot_at(&state, seg_idx, &segment.label, state.speed_kts, &peak_stress, config, Some(mode.label())));
            return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
        }

        // Speed is constant within a segment (conditions don't change)
        let speed_ms = equilibrium_speed_ms(config, current_mass, conditions);
        let speed_kts = speed_ms * 1.944;
        state.speed_kts = speed_kts;
        let seg_duration_h = segment.distance_nm / speed_kts.max(0.1);

        // ----------------------------------------------------------------
        // Inner time loop — hourly steps through the segment
        // ----------------------------------------------------------------
        let mut seg_elapsed_h = 0.0_f64;

        while seg_elapsed_h < seg_duration_h {
            let step_h = (seg_duration_h - seg_elapsed_h).min(STEP_H);
            let step_s = step_h * 3600.0;
            let step_distance_nm = segment.distance_nm * (step_h / seg_duration_h);

            let step_mass = (config.total_mass_kg()
                - (config.propulsion.fuel_capacity_kg - state.fuel_kg))
                .max(500.0);

            // Fuel consumption for this step
            let fuel_burned = fuel_burned_kg(config, step_mass, step_distance_nm, conditions);
            if fuel_burned >= state.fuel_kg {
                let distance_on_remaining =
                    state.fuel_kg / fuel_burned.max(1.0) * step_distance_nm;
                let mode = FailureMode::FuelExhaustion {
                    distance_remaining_nm: total_distance_nm
                        - state.distance_nm
                        - distance_on_remaining,
                };
                ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
            }
            state.fuel_kg -= fuel_burned;

            // ----------------------------------------------------------------
            // Spray-ice accretion (sub-4°C water → topside ice raises KG)
            // ----------------------------------------------------------------
            let ice_rate = spray_icing_rate_kg_per_h(&config.hull, conditions);
            if ice_rate > 0.0 {
                state.ice_mass_kg += ice_rate * step_h;
                let kg = estimate_kg(config, state.fuel_kg);
                let base_gm = metacentric_height_m(&config.hull, step_mass, kg);
                state.gm_m = gm_with_ice(base_gm, &config.hull, step_mass, kg, state.ice_mass_kg);
                if capsize_risk(state.gm_m, &config.hull, conditions.hs_m, conditions.encounter_angle_deg) {
                    let gm_min = gm_minimum(&config.hull);
                    let beam_component = (conditions.encounter_angle_deg.to_radians().sin()).abs();
                    let gm_effective_min = (gm_min + 0.015 * conditions.hs_m.powi(2) * beam_component).max(gm_min);
                    let mode = FailureMode::Capsize { gm_m: state.gm_m, gm_required_m: gm_effective_min };
                    ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                    return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
                }
            }

            // Per-zone structural assessment for this step
            let elapsed_h_snapshot = state.elapsed_h;
            for zone_spec in &config.zones {
                let zone = zone_spec.zone;
                let material = &zone_spec.material;
                let mat_spec = material.spec();
                let zone_state = state.zone_mut(zone);

                if conditions.water_temp_c < mat_spec.min_temp_c {
                    let mode = FailureMode::ColdTemperatureBrittleness {
                        zone,
                        water_temp_c: conditions.water_temp_c,
                        min_rated_temp_c: mat_spec.min_temp_c,
                    };
                    ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                    return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
                }

                let submerged = zone.is_submerged();
                let new_loss = thickness_loss_m(material, conditions, submerged, step_h)
                    * CORROSION_RATE_MULTIPLIER;
                zone_state.corrosion_depth_m += new_loss;

                let net_t = zone_state.net_thickness_m(zone_spec.thickness_m);
                let thickness_ratio = (zone_spec.thickness_m / net_t.max(0.0005)).clamp(1.0, 8.0);
                let fatigue_softening = 1.0 + zone_state.fatigue_consumed.clamp(0.0, 0.64) * 1.8;
                let crack_softening =
                    1.0 + (zone_state.crack_half_length_m / zone_spec.thickness_m.max(0.001))
                        .sqrt()
                        .clamp(0.0, 1.5);
                let weakening_multiplier =
                    (thickness_ratio.powf(2.2) * fatigue_softening * crack_softening)
                        .clamp(1.0, 18.0);

                if net_t < zone_spec.thickness_m * 0.35 {
                    zone_state.fatigue_consumed = 1.0;
                    let mode = FailureMode::FatigueFailure {
                        zone,
                        damage_accumulated: zone_state.fatigue_consumed,
                    };
                    ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                    return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
                }

                let corr_multiplier =
                    corrosion_fatigue_multiplier(material, conditions, elapsed_h_snapshot);
                let base_damage = segment_fatigue_damage(
                    &config.hull,
                    conditions,
                    zone,
                    zone_spec,
                    &mat_spec,
                    step_s,
                );
                zone_state.fatigue_consumed +=
                    base_damage * corr_multiplier * weakening_multiplier * DAMAGE_RATE_MULTIPLIER;

                let sig_stress =
                    significant_stress_mpa(&config.hull, conditions, zone, zone_spec)
                        * weakening_multiplier;
                let entry = peak_stress.entry(zone).or_insert(0.0);
                if sig_stress > *entry {
                    *entry = sig_stress;
                }

                if zone_state.is_fatigued() {
                    zone_state.fatigue_consumed = 1.0;
                    let mode = FailureMode::FatigueFailure {
                        zone,
                        damage_accumulated: zone_state.fatigue_consumed,
                    };
                    ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                    return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
                }

                let delta_stress = sig_stress * 2.0;
                let tz = conditions.zero_crossing_period_s();
                let n_cycles = step_s / tz.max(0.5);
                let dk = stress_intensity_factor(
                    delta_stress,
                    zone_state.crack_half_length_m.max(1e-6),
                );
                let da_per_cycle = paris_crack_growth_per_cycle(dk, &mat_spec);
                zone_state.crack_half_length_m +=
                    da_per_cycle * n_cycles * CRACK_GROWTH_MULTIPLIER * weakening_multiplier.sqrt();

                let k_applied =
                    stress_intensity_factor(sig_stress, zone_state.crack_half_length_m);
                if is_critical_crack(
                    zone_state.crack_half_length_m,
                    sig_stress,
                    mat_spec.k_ic_mpa_sqrtm,
                ) {
                    let mode = FailureMode::BrittleFracture {
                        zone,
                        crack_half_length_m: zone_state.crack_half_length_m,
                        k_applied_mpa_sqrtm: k_applied,
                        k_ic_mpa_sqrtm: mat_spec.k_ic_mpa_sqrtm,
                    };
                    ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                    return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
                }
            }

            // Advance state for this step
            state.distance_nm = (state.distance_nm + step_distance_nm).min(total_distance_nm);
            state.elapsed_h += step_h;
            seg_elapsed_h += step_h;

            ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, None));
        }

        // ----------------------------------------------------------------
        // Seal check per segment (cumulative exposure over full segment)
        // ----------------------------------------------------------------
        for zone_spec in &config.zones {
            let zone = zone_spec.zone;
            let hourly_survival = zone_spec.seal_quality.hourly_survival_prob();
            let seal_survival = hourly_survival.powf(seg_duration_h);
            if seal_survival < 0.50 {
                let mode = FailureMode::SealBreachFlooding {
                    zone,
                    elapsed_h: state.elapsed_h,
                };
                ticks.push(snapshot_at(&state, seg_idx, &segment.label, speed_kts, &peak_stress, config, Some(mode.label())));
                return build_failure(mode, &state, seg_idx, &segment.label, total_distance_nm, total_cost, &peak_stress, config, ticks);
            }
        }
    }

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
        ticks,
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
    ticks: Vec<SegmentSnapshot>,
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
        ticks,
    }
}

fn snapshot_at(
    state: &VesselState,
    seg_idx: usize,
    seg_label: &str,
    speed_kts: f64,
    peak_stress: &std::collections::HashMap<HullZone, f64>,
    config: &VesselConfig,
    failure: Option<&'static str>,
) -> SegmentSnapshot {
    SegmentSnapshot {
        segment_index: seg_idx,
        segment_label: seg_label.to_string(),
        distance_completed_nm: state.distance_nm,
        elapsed_h: state.elapsed_h,
        speed_kts,
        fuel_remaining_kg: state.fuel_kg,
        gm_m: state.gm_m,
        zones: build_zone_summaries(state, peak_stress, config),
        failure: failure.map(|s| s.to_string()),
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
        .map(|zs| ZoneSummary {
            zone: zs.zone,
            fatigue_consumed: zs.fatigue_consumed,
            corrosion_depth_mm: zs.corrosion_depth_m * 1000.0,
            crack_half_length_mm: zs.crack_half_length_m * 1000.0,
            peak_stress_mpa: *peak_stress.get(&zs.zone).unwrap_or(&0.0),
        })
        .collect()
}
