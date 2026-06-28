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

## Reports

[`ship_sim.reporting`](ship_sim/reporting/reports.py) turns a `SimulationResult`
into readable Markdown:

```python
from ship_sim.reporting import (
    generate_corrosion_report, generate_stability_report, generate_overall_risk_report,
)
print(generate_overall_risk_report(result))
```

Or from the demo: `python examples/demo_basic.py --report`.

### Example report output (built-in demo)

```markdown
# Overall risk report

> ENGINEERING APPROXIMATION -- NOT a certified naval safety assessment.

## Final risk summary
- Cumulative capsize probability: **1.0000**
- Maximum stability-risk score: **0.733** at t = 204.0 h (8.50 d)
- Total metal lost (all components): 0.00 mm; most corroded: `side_shell_waterline`

## Top 5 corrosion-critical components
| # | component | thickness lost | min safety factor |
|---:|---|---:|---:|
| 1 | side_shell_waterline | 0.01% | 1.89 |
| 2 | bottom_plating | 0.01% | 2.04 |
| 3 | main_deck | 0.01% | 1.87 |
| 4 | superstructure_front | 0.00% | 1.68 |

## Top 5 stability-critical timesteps
| # | time | risk | dominant driver |
|---:|---|---:|---|
| 1 | t = 204.0 h (8.50 d) | 0.733 | storm intensity |
| 2 | t = 102.0 h (4.25 d) | 0.730 | storm intensity |
| 3 | t = 96.0 h (4.00 d) | 0.708 | storm intensity |
| ... |

## Major warnings
- [t=150.00 h] Roll-resonance risk: encounter period 11.3 s near roll period 9.5 s ...
- [t=204.00 h] High capsize-risk score (0.73).
- ...

## Recommended model improvements
- Integrate time-dependent coating breakdown and galvanic coupling ...
- Add a proper GZ curve and IMO weather-criterion checks instead of a GM proxy ...

## Recommended real-world data to improve accuracy
- Measured corrosion coupon data for the actual coatings/alloys and waters ...
- As-built hydrostatics (real GZ curve, KG, loading conditions, roll trials) ...

## Limitations
- Simplified, empirical corrosion model (factor product), not first-principles.
- No detailed electrochemical-cell modeling.
- No CFD; no strip theory / full seakeeping solver; no finite-element model.
- No classification-society rule compliance.
- No cargo-shift, free-surface, or flooding model.
- No guarantee of real-world safety; outputs are comparative/illustrative only.
```

The **corrosion report** additionally answers which components corroded most (by
absolute loss and by percentage), when the corrosion rate peaked, which
environmental factors dominated (e.g. `splash_factor`, `coating_factor`,
`temperature_factor`), and whether the corrosion allowance was exceeded. The
**stability report** breaks the peak risk into its drivers (wind / wave / GM /
resonance / speed / structural / storm), counts warning-level timesteps, and
states the cumulative capsize probability and the model's strongest limitations.

## Monte Carlo uncertainty

`ship_sim.simulation.monte_carlo.run_monte_carlo(scenario, n_runs, random_seed,
backend="python")` runs many perturbed simulations and aggregates distributions.
It is **separate from the deterministic engine** — it only orchestrates repeated
engine runs. Each run perturbs material corrosion rates, coating breakdown,
salinity, pH, dissolved oxygen, wave height/period, wind speed, storm intensity,
ship mass, KG, and GM (std devs configurable via `PerturbationSpec`). Per-run
seeds are spawned from `random_seed`, so results are **reproducible** and
identical whether run serially or with `backend="multiprocessing"` (stdlib;
`joblib` is a drop-in alternative).

```python
from ship_sim.simulation.monte_carlo import run_monte_carlo
result = run_monte_carlo(scenario, n_runs=100, random_seed=2026, backend="multiprocessing")
print(result.distribution("max_stability_risk"))   # {p5, p50, p95, mean, std}
print(result.summary())                             # all metrics + per-component corrosion
print(result.sensitivity("max_stability_risk"))     # inputs ranked by |Pearson r|
```

Distributions are returned (p5/p50/p95/mean/std) for: final corrosion by
component, max stability risk, cumulative capsize probability, time of maximum
risk, and number of warnings. `sensitivity()` ranks which uncertain inputs most
influence a chosen output.

Demo: `python examples/monte_carlo_demo.py --runs 100 --backend multiprocessing`.
Example sensitivity output (built-in demo, GM dominates as expected):

```
Sensitivity (Pearson corr. with max stability risk; |r| ranked):
  metacentric height (GM)  r=-0.560  #################
  wind speed               r=+0.307  #########
  storm intensity          r=+0.206  ######
  wave period              r=+0.119  ####
  ...
```

(Small correlations at low `n` are sampling noise — increase `--runs` to tighten
them.)

## Visualization

[`ship_sim.visualization`](ship_sim/visualization.py) provides simple Matplotlib
plots (no seaborn). Matplotlib is optional: `pip install -e ".[viz]"` (or
`.[dev]`). Each function builds one figure with unit-labeled axes, saves it when
`output_path` is given, and **returns the `Figure`**.

```python
import matplotlib; matplotlib.use("Agg")   # for headless/file-only use
from ship_sim import visualization as viz

viz.plot_corrosion_over_time(result, component_name=None, output_path="corrosion.png")
viz.plot_stability_risk_over_time(result, output_path="stability.png")
viz.plot_environment_over_time(result, output_path="environment.png")
viz.plot_wave_weather_over_time(result, output_path="wave_weather.png")
viz.plot_monte_carlo_distributions(mc_result, output_path="mc.png")
```

- `plot_corrosion_over_time` — accumulated metal loss (mm) vs time, per component
  (or one component).
- `plot_stability_risk_over_time` — risk score (0-1) with per-timestep capsize
  probability on a twin axis.
- `plot_environment_over_time` — salinity (ppt), water temperature (°C), pH,
  dissolved O₂ (mg/L) as stacked panels.
- `plot_wave_weather_over_time` — wind speed (m/s), storm intensity (0-1),
  significant wave height (m), peak period (s).
- `plot_monte_carlo_distributions` — histograms (with medians) of max stability
  risk, cumulative capsize probability, warning count, and total metal loss.

The plots read from a `SimulationResult` (so it must include a `timeline` — do
not strip it with `--no-timeline`) and a `MonteCarloResult`.

## Status

Implemented: data models, unit helpers, configuration system, JSON scenario
I/O, procedural + segmented environment providers, trajectory interpolation, the
corrosion model, the stability/seakeeping/capsizing model, the full
`ShipSimulationEngine`, Markdown reporting, Monte Carlo uncertainty propagation
(with sensitivity analysis), Matplotlib visualization, a runnable CLI demo, an
optional Streamlit dashboard, and an acceleration abstraction (`python` +
vectorized `numpy` backends) with benchmarks.

### Acceleration & performance

`ship_sim.acceleration` exposes `list_available_backends()`,
`choose_backend(preferred)`, and an `AccelerationBackend` interface with a
vectorized NumPy corrosion-batch kernel (numerically identical to the Python
reference). Compiled backends (`numba`/`rust`/`cpp`) are *planned but
intentionally not shipped*: the [benchmarks](benchmarks/) show the numeric
kernels are not the bottleneck (1–5M component-updates/sec) — the engine cost is
per-timestep Python/Pydantic object construction — so a compiled inner loop would
not help, and pure Python/NumPy is fast enough for normal scenarios. Large Monte
Carlo studies should use process-level parallelism (`joblib`/`multiprocessing`).
Run `python benchmarks/benchmark_engine.py` and
`python benchmarks/benchmark_monte_carlo.py`.

## GUI / dashboard (optional)

An optional [Streamlit](https://streamlit.io) dashboard provides a point-and-click
front end. It is a **thin layer with no physics**: it calls the same scenario
loader, engine, Monte Carlo, reporting, and visualization APIs as the CLI, so
**GUI results match CLI results for identical inputs**. The dependency-light,
unit-tested glue lives in [`ship_sim/gui/builders.py`](ship_sim/gui/builders.py)
(importable without Streamlit); only the dashboard view needs Streamlit.

```bash
pip install -e ".[gui]"                      # streamlit + matplotlib + pandas
streamlit run ship_sim/gui/streamlit_app.py
```

The dashboard supports:

- **Scenario loading** — upload a JSON scenario (validated with readable errors)
  or start from the built-in demo; parsed ship/trajectory/materials/conditions
  are shown.
- **Editing** — simulation settings (dt, backend, seed), ship hull
  scalars (dimensions, displacement, KG, GM, roll period), and add/edit/remove
  **materials**, **components**, and **trajectory waypoints** via editable tables;
  selected config coefficients; **Apply & validate** re-runs the model validators.
- **Run controls** — deterministic run and Monte Carlo (choose runs/seed and a
  `python`/`multiprocessing` execution backend), with a spinner for long runs.
- **Results dashboard** — cumulative capsize probability, max stability risk and
  when/where it occurred, top corrosion-critical components, dominant risk
  contributors, and warning events (all with units).
- **Interactive plots** — corrosion and remaining thickness by component,
  stability risk, environment and wave/weather series, and Monte Carlo
  distributions; each downloadable as PNG.
- **Route designer** — a custom **100 × 100 mi** square (blue ocean, white path,
  no tile basemap) where you **add / drag / delete** waypoints; an *Ocean layer*
  selector shades the sea by an environmental metric (dissolved O₂, temperature,
  salinity, pH, pollution, wind, storm, wave height), with a day-snapshot slider.
  Path **distance updates live**; the simulation reruns per edit at **¼-mile
  resolution** (auto-rerun toggle or a manual button). Falls back to a waypoint
  table if the canvas component isn't installed.
- **Export** — edited scenario JSON, result JSON (with/without timeline), and a
  combined Markdown report.

**Dashboard limitations:** it does not add any modeling capability beyond the
core library; a running simulation cannot be cancelled mid-flight (only a busy
spinner is shown); the map shows points without per-segment coloring; and all the
[model limitations](#model-limitations) below apply unchanged — it remains an
engineering approximation, not a certified safety tool.

## Model limitations

`ship_sim` is an **engineering approximation**, not a certified analysis. Its
results are useful for exploration, teaching, and *relative* comparison between
scenarios — not for real-world safety, design, or operational decisions. The
main simplifications:

- **Corrosion** is a simplified empirical factor-product model (a base rate
  scaled by dimensionless environmental factors). There is **no detailed
  electrochemical-cell modeling** — no anode/cathode kinetics, polarization
  curves, mixed-potential theory, or local pitting electrochemistry. **Galvanic
  coupling** between dissimilar metals is not modeled, and the coating is treated
  as intact (no time-dependent breakdown integrated yet).
- **Hydrodynamics** are heavily reduced: **no CFD**, **no strip theory or panel
  methods**, and roll response is a parameterized resonance/encounter model
  rather than a solved equation of motion. Wind heeling and green water are
  coarse; wave steepness uses deep-water dispersion only.
- **Stability** uses a small-angle restoring-moment proxy (`Δ·g·GM·sin φ`), not
  a full **GZ curve**, and does **not** evaluate IMO/IACS intact- or
  damage-stability criteria. There is **no cargo-shift, free-surface, or
  flooding model**, and GM is held constant (corrosion-driven weight/KG changes
  ignored). The capsize-probability calibration is deliberately conservative and
  tunable, not validated.
- **Structure** maps thickness loss to strength with a thin-plate proxy — **no
  finite-element model**, no load redistribution, and **no fatigue / cyclic
  loading** analysis.
- **Environment** can be procedurally generated (synthetic, not a forecast) or
  user-segmented; the procedural generator is plausible but uncalibrated, and
  the built-in coefficients are order-of-magnitude defaults, not measured values.
- **No classification-society compliance** and **no guarantee of real-world
  safety**.

Every run's `SimulationResult.assumptions` and the generated reports restate the
applicable limitations.

## Future improvements

Roughly in order of fidelity gained, the project could grow toward:

- **Real hydrodynamics** — solve the coupled roll/heave/pitch equations of
  motion with proper added mass and damping instead of a parameterized proxy.
- **Strip theory or panel (BEM) methods** — frequency-domain RAOs for motions
  and wave loads; a clean step up from the current encounter model.
- **CFD** — high-fidelity flow, wind loading, green-water, and slamming for
  cases the reduced models cannot capture.
- **Wave-spectrum modeling** — full JONSWAP / Pierson–Moskowitz spectra with
  directional spreading and irregular-sea response statistics, rather than a
  single Hs/Tp pair.
- **AIS / weather / ocean API integration** — drive routes and conditions from
  real AIS tracks and metocean/reanalysis services (wind, waves, currents,
  temperature, salinity) instead of procedural generation.
- **Real marine-corrosion datasets** — calibrate the corrosion coefficients
  against measured coupon/UT-gauging data for specific alloys, coatings, and
  waters, with quantified uncertainty.
- **Galvanic coupling between dissimilar metals** — model mixed-potential and
  area-ratio effects at steel/aluminium (and anode) interfaces.
- **Detailed coating-breakdown models** — time- and stress-dependent coating
  degradation and cathodic-protection (sacrificial-anode) depletion.
- **Fatigue and cyclic loading** — S–N / fracture-mechanics crack growth driven
  by the wave-encounter load history, coupled to corrosion (corrosion-fatigue).

These are intentionally **not** implemented yet; the architecture (tunable
config, pluggable providers, the acceleration backend interface, and independent
physics modules) is designed to make adding them incremental.
