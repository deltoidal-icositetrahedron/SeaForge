# ship_sim

Modular simulation that estimates **ship corrosion, structural degradation, and
capsizing / stability risk over a route**, from user-provided or procedurally
generated inputs (geometry, materials, coatings, speed profile, trajectory,
weather, waves, currents, salinity, pH, temperature, dissolved oxygen, humidity,
pollution, and regional conditions).

> ⚠️ **ENGINEERING APPROXIMATION — NOT A CERTIFIED NAVAL SAFETY TOOL.**
> The models here are simplified, physically motivated engineering
> approximations intended for exploration, education, and comparative studies.
> They are **not** validated against classification-society rules and **must not**
> be used as the basis for real-world safety, design certification, or
> operational decisions.

## Project purpose

Provide a clean, testable, extensible Python framework that prioritizes physical
accuracy *as far as is reasonably implementable*: physically motivated models,
dimensional consistency, traceable intermediate quantities, and **tunable
coefficients** rather than opaque heuristic scores. Simplified empirical formulas
are used only where higher-fidelity modeling would be disproportionately complex,
and each simplification is documented in code.

## Unit conventions (SI internally)

| Quantity        | Internal unit | Notes |
|-----------------|---------------|-------|
| length          | meters (m)    | |
| mass            | kilograms (kg)| |
| time            | seconds (s)   | helpers for hours / (Julian) years |
| speed           | m/s           | helpers for knots |
| stress/strength | pascals (Pa)  | |
| temperature     | kelvin (K) for physics | **Celsius** for user-facing environmental input |
| corrosion rate  | m/s           | helpers for mm/year and m/year |

A "year" is the **Julian year** (365.25 days) everywhere, so "per year" rates are
unambiguous. See [`ship_sim/units.py`](ship_sim/units.py) for all converters
(`knots_to_mps`, `mm_per_year_to_m_per_s`, `celsius_to_kelvin`, `deg_to_rad`, …).

## High-level model description

Inputs are validated [Pydantic v2](https://docs.pydantic.dev) models
([`ship_sim/models/`](ship_sim/models/)):

- **Material** — density, yield/ultimate/elastic/fatigue strengths, base
  corrosion rate, resistance & galvanic potential, coating breakdown.
- **ShipComponent** — material, current/original thickness, area, exposure,
  location & vertical position, corrosion allowance, required safety factor.
- **Ship** — principal particulars, mass & hydrostatics (KG, GM, waterplane &
  windage areas, roll period), list of components.
- **Trajectory / Waypoint** — timed route with target speeds; times must be
  strictly increasing.
- **RegionEnvironment / WeatherCondition / WaveCondition** — seawater chemistry,
  atmosphere, and sea state / currents that drive the physics.
- **Scenario** — bundles all of the above plus a **SimulationConfig** of tunable
  coefficients; serializable to/from JSON.
- **SimulationState / SimulationResult** — per-timestep and aggregated outputs,
  including traceable intermediate physics values (later phases).

All empirical constants live in [`ship_sim/config.py`](ship_sim/config.py)
(`SimulationConfig`) so the models can be calibrated without editing code.

## Quick start

```bash
# (optional) create an environment and install
pip install -e ".[dev]"

# run the built-in procedural demo simulation
python examples/demo_basic.py
python -m ship_sim.examples.demo_basic        # equivalent

# run from a scenario file
python examples/demo_basic.py --scenario examples/scenario_basic.json
python -m ship_sim.examples.demo_basic --scenario examples/scenario_basic.json

# run the tests
pytest
```

Demo options: `--scenario PATH` (load inputs), `--out PATH` (result file),
`--no-timeline` (write summaries only, omit the per-step timeline),
`--dt-hours H` (timestep for the built-in demo).

## Scenario files

A scenario is a JSON document validated against
[`Scenario`](ship_sim/models/scenario.py). Load and run it with
`ship_sim.io.load_scenario(path)` → `LoadedScenario` → `.build_engine().run()`.
See [`examples/scenario_basic.json`](examples/scenario_basic.json).

### Structure

```jsonc
{
  "name": "my_voyage",                 // required
  "description": "...",                // optional
  "simulation": {                      // required
    "dt_hours": 6.0,                   //   timestep: dt_s (SI) OR dt_hours
    "backend": "python",              //   backend preference (only "python" today)
    "fallback_nearest": false          //   nearest-segment fallback for Mode A
  },
  "ship": { ... },                     // required: geometry/mass/hydrostatics + components
  "trajectory": { "waypoints": [ ... ] }, // required: >= 2 waypoints, strictly increasing time_s

  // --- conditions: per channel, supply segments (Mode A) OR omit for procedural (Mode B) ---
  "weather_segments":     [ { "condition": { ...WeatherCondition... },
                              "start_time_hours": 0, "end_time_hours": 24,
                              "lat_bounds": [40, 60], "lon_bounds": [-20, -5] } ],
  "wave_segments":        [ { "condition": { ...WaveCondition... } } ],     // optional
  "environment_segments": [ { "condition": { ...RegionEnvironment... } } ], // optional

  "procedural": {                      // used for any channel WITHOUT segments
    "seed": 2026,                      //   fixed seed => reproducible
    "ranges": { "salinity_mean_ppt": 35.0 }  // optional ProceduralRanges overrides
  },

  "config": {                          // optional: override only the coefficients you want
    "corrosion": { "splash_zone_multiplier": 2.5 },
    "stability": { "capsize_time_at_max_risk_s": 1800.0 }
  }
}
```

### Required vs optional

- **Required:** `name`, `simulation` (with `dt_s` *or* `dt_hours`), `ship`,
  `trajectory`.
- **Optional:** `description`; `weather_segments` / `wave_segments` /
  `environment_segments` (any channel omitted is generated procedurally);
  `procedural` (defaults to `seed=0`); `config` (any omitted coefficient uses
  its documented default).
- A condition **segment** matches when the time is within
  `[start_time, end_time]` (if given) and the position is within `lat_bounds` /
  `lon_bounds` (if given); a segment with no bounds is a catch-all. With
  `fallback_nearest: true`, the nearest segment is used when none matches;
  otherwise an unmatched query raises.

### Units in scenario files

Everything is **SI**. Two user-friendly conveniences are converted on load:
`simulation.dt_hours` → seconds, and segment `start_time_hours` /
`end_time_hours` → seconds. If both the SI and the `_hours` form are given, the
SI value wins. Speeds in waypoints are m/s (use `units.knots_to_mps` when
authoring); temperatures in conditions are °C (converted to kelvin by the
physics).

### Interpreting result fields

`SimulationResult` (saved by `save_result`, see
[`results.py`](ship_sim/models/results.py)):

- `timeline` — per-timestep `SimulationState`s (position, conditions,
  per-component accumulated corrosion / effective thickness / rate, stability
  risk, capsize probability, and traceable `intermediate_physics_values`).
  Omitted when saved with `--no-timeline`.
- `final_corrosion_summary` — `by_component` (loss fraction, final effective
  thickness, accumulated loss, final rate, min safety margin),
  `min_safety_margin_by_component`, `most_corroded_component`, and
  `dominant_environmental_factors` (mean factor, ranked by deviation from 1.0).
- `final_stability_summary` — `max_risk_score`, `time_of_max_risk_s`,
  `position_of_max_risk`, `max_risk_dominant_contributions`, `final_risk_score`.
- `cumulative_capsize_probability` — voyage-integrated `1 - Π(1 - p_step)`.
  **Note:** the per-step hazard calibration is intentionally conservative and
  fully tunable via `config.stability.capsize_time_at_max_risk_s` /
  `capsize_risk_exponent`.
- `warnings` — deduplicated major events, stamped with first-occurrence time.
- `assumptions` — the simplifications applied by the pipeline.

## Status

Implemented: data models, unit helpers, configuration system, JSON scenario
I/O, procedural + segmented environment providers, trajectory interpolation, the
corrosion model, the stability/seakeeping/capsizing model, and the full
`ShipSimulationEngine`, with a runnable CLI demo. The `reporting/` and
`acceleration/` packages remain skeletons (planned next).
