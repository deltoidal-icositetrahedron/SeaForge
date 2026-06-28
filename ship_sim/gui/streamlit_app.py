"""Streamlit dashboard for ship_sim (optional GUI).

This is a thin presentation layer: it contains **no physics**. Every computation
goes through the same tested APIs the CLI uses -- scenario validation
(:mod:`ship_sim.io`), the engine and Monte Carlo (:mod:`ship_sim.simulation`),
reporting (:mod:`ship_sim.reporting`), and plotting
(:mod:`ship_sim.visualization`) -- via the helpers in
:mod:`ship_sim.gui.builders`.

Launch::

    pip install -e ".[gui]"
    streamlit run ship_sim/gui/streamlit_app.py

UI state (the editable scenario, last results) lives in ``st.session_state`` and
is kept separate from the simulation objects.
"""

from __future__ import annotations

from typing import Any, Dict, List

try:
    import streamlit as st
except ImportError as exc:  # pragma: no cover - exercised only without streamlit
    raise SystemExit(
        "Streamlit is required for the GUI. Install it with:\n"
        "    pip install 'ship_sim[gui]'\n"
        "then run:\n"
        "    streamlit run ship_sim/gui/streamlit_app.py"
    ) from exc

from ship_sim import DISCLAIMER, units
from ship_sim.gui import builders
from ship_sim.gui import route_map as rm
from ship_sim.io import build_providers

# Optional dependencies, handled gracefully.
try:
    from ship_sim import visualization as viz

    _HAS_VIZ = True
except Exception:  # pragma: no cover - depends on matplotlib availability
    _HAS_VIZ = False

try:
    import pandas as pd

    _HAS_PANDAS = True
except Exception:  # pragma: no cover
    _HAS_PANDAS = False

def _install_canvas_image_shim() -> None:
    """Make streamlit-drawable-canvas work with newer Streamlit.

    Streamlit (>= ~1.49) moved ``image_to_url`` to
    ``streamlit.elements.lib.image_utils`` and changed its 2nd argument from a
    ``width`` int to a ``LayoutConfig``. drawable-canvas 0.9.x still calls
    ``streamlit.elements.image.image_to_url(image, width, ...)`` at runtime, so
    we install a compatible shim onto that module if it's missing.
    """
    import streamlit.elements.image as st_image

    if hasattr(st_image, "image_to_url"):
        return
    try:
        from streamlit.elements.lib.image_utils import image_to_url as _new
        from streamlit.elements.lib.layout_utils import LayoutConfig
    except Exception:  # pragma: no cover - unknown Streamlit layout
        return

    def _image_to_url(image, width, clamp, channels, output_format, image_id):
        cfg = LayoutConfig(width=int(width) if isinstance(width, (int, float)) else None)
        return _new(image, cfg, clamp, channels, output_format, image_id)

    st_image.image_to_url = _image_to_url


try:
    _install_canvas_image_shim()
    from streamlit_drawable_canvas import st_canvas

    _HAS_CANVAS = True
except Exception:  # pragma: no cover - optional drag component
    _HAS_CANVAS = False


# ---------------------------------------------------------------------------
# Scenario <-> editable-table conversion (UI glue only, no physics)
# ---------------------------------------------------------------------------

def _scenario_tables(scenario) -> Dict[str, List[Dict[str, Any]]]:
    """Split a Scenario into table-style rows for the editors."""
    materials: Dict[str, Dict[str, Any]] = {}
    components: List[Dict[str, Any]] = []
    for comp in scenario.ship.components:
        mat = comp.material
        materials.setdefault(mat.name, mat.model_dump(mode="json"))
        row = comp.model_dump(mode="json")
        row.pop("material")
        row["material_name"] = mat.name
        components.append(row)
    waypoints = [wp.model_dump(mode="json") for wp in scenario.trajectory.waypoints]
    return {
        "materials": list(materials.values()),
        "components": components,
        "waypoints": waypoints,
    }


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

def _init_state() -> None:
    if "scenario" not in st.session_state:
        st.session_state.scenario = builders.default_demo_scenario()
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("mc_result", None)


# ---------------------------------------------------------------------------
# Sidebar: load / reset
# ---------------------------------------------------------------------------

def _sidebar() -> None:
    st.sidebar.header("Scenario source")
    uploaded = st.sidebar.file_uploader("Upload scenario JSON", type=["json"])
    if uploaded is not None and st.sidebar.button("Load uploaded scenario"):
        import json

        try:
            data = json.loads(uploaded.getvalue().decode("utf-8"))
            st.session_state.scenario = builders.validate_scenario(data)
            st.session_state.result = None
            st.session_state.mc_result = None
            st.sidebar.success("Scenario loaded and validated.")
        except Exception as err:
            st.sidebar.error(f"Invalid scenario:\n\n{err}")

    if st.sidebar.button("Reset to demo scenario"):
        st.session_state.scenario = builders.default_demo_scenario()
        st.session_state.result = None
        st.session_state.mc_result = None

    st.sidebar.caption(
        "The dashboard calls the same simulation core as the CLI; results match "
        "for the same inputs."
    )


# ---------------------------------------------------------------------------
# Tab: scenario & edit
# ---------------------------------------------------------------------------

def _tab_scenario() -> None:
    scenario = st.session_state.scenario
    st.subheader("Edit scenario")
    st.caption("Edit fields, then **Apply & validate** to rebuild the scenario.")

    name = st.text_input("Name", scenario.name)
    description = st.text_area("Description", scenario.description, height=68)

    st.markdown("**Simulation settings**")
    c1, c2, c3, c4 = st.columns(4)
    dt_hours = c1.number_input(
        "dt (hours)", min_value=0.01,
        value=units.seconds_to_hours(scenario.simulation.resolved_dt_s), step=1.0,
    )
    backends = builders.engine_backends()
    backend = c2.selectbox("engine backend", backends,
                           index=backends.index(scenario.simulation.backend)
                           if scenario.simulation.backend in backends else 0)
    seed = int(c3.number_input("procedural seed", value=int(scenario.procedural.seed), step=1))
    fallback = c4.checkbox("segment nearest-fallback", scenario.simulation.fallback_nearest)

    st.markdown("**Ship** (SI units)")
    s = scenario.ship
    g1, g2, g3 = st.columns(3)
    length = g1.number_input("length (m)", min_value=0.1, value=float(s.length_m))
    beam = g2.number_input("beam (m)", min_value=0.1, value=float(s.beam_m))
    draft = g3.number_input("draft (m)", min_value=0.1, value=float(s.draft_m))
    g4, g5, g6 = st.columns(3)
    disp = g4.number_input("displacement (kg)", min_value=1.0, value=float(s.displacement_mass_kg))
    kg = g5.number_input("KG: CoG height (m)", min_value=0.0, value=float(s.center_of_gravity_height_m))
    gm = g6.number_input("GM (m)", value=float(s.metacentric_height_m))
    g7, g8 = st.columns(2)
    roll = g7.number_input("roll natural period (s)", min_value=0.0,
                           value=float(s.roll_natural_period_s or 0.0))
    lat_area = g8.number_input("projected lateral area (m^2)", min_value=0.0,
                               value=float(s.projected_lateral_area_m2 or 0.0))

    tables = _scenario_tables(scenario)

    st.markdown("**Materials** (add/edit/remove rows)")
    materials = _edit_rows(tables["materials"], key="materials")

    st.markdown("**Components** (`material_name` must match a material above)")
    components = _edit_rows(tables["components"], key="components")

    st.markdown("**Trajectory waypoints** (time_s strictly increasing)")
    waypoints = _edit_rows(tables["waypoints"], key="waypoints")

    st.markdown("**Conditions**")
    st.caption(
        "Procedural generation is used for weather/waves/environment. To supply "
        "user segments, upload a scenario JSON containing *_segments arrays."
    )

    st.markdown("**Selected config coefficients** (others keep current values)")
    cfg = scenario.config
    k1, k2, k3 = st.columns(3)
    splash = k1.number_input("corrosion.splash_zone_multiplier", min_value=1.0,
                             value=float(cfg.corrosion.splash_zone_multiplier))
    capsize_tau = k2.number_input("stability.capsize_time_at_max_risk_s", min_value=1.0,
                                  value=float(cfg.stability.capsize_time_at_max_risk_s))
    warn_thr = k3.number_input("stability.risk_warning_threshold", min_value=0.0,
                               max_value=1.0, value=float(cfg.stability.risk_warning_threshold))

    if st.button("Apply & validate", type="primary"):
        ship_scalars = {
            "name": s.name, "length_m": length, "beam_m": beam, "draft_m": draft,
            "displacement_mass_kg": disp, "center_of_gravity_height_m": kg,
            "metacentric_height_m": gm,
            "roll_natural_period_s": roll or None,
            "projected_lateral_area_m2": lat_area or None,
            "waterplane_area_m2": s.waterplane_area_m2,
        }
        config = cfg.model_dump()
        config["corrosion"]["splash_zone_multiplier"] = splash
        config["stability"]["capsize_time_at_max_risk_s"] = capsize_tau
        config["stability"]["risk_warning_threshold"] = warn_thr
        data = builders.assemble_scenario_dict(
            name=name, description=description,
            simulation={"dt_hours": dt_hours, "backend": backend, "fallback_nearest": fallback},
            ship=ship_scalars, materials=materials, components=components,
            waypoints=waypoints, procedural={"seed": seed}, config=config,
        )
        try:
            st.session_state.scenario = builders.validate_scenario(data)
            st.session_state.result = None
            st.session_state.mc_result = None
            st.success("Scenario is valid and updated.")
        except Exception as err:
            st.error(f"Validation failed:\n\n{err}")


def _edit_rows(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Editable table that returns a list of row dicts (add/edit/remove)."""
    if _HAS_PANDAS:
        edited = st.data_editor(pd.DataFrame(rows), num_rows="dynamic", key=key,
                                use_container_width=True)
        return edited.to_dict(orient="records")
    # Fallback without pandas: raw JSON editing.
    import json

    text = st.text_area(f"{key} (JSON)", json.dumps(rows, indent=2), key=key)
    try:
        return json.loads(text)
    except Exception:
        st.error(f"{key}: invalid JSON; keeping previous values.")
        return rows


# ---------------------------------------------------------------------------
# Tab: run
# ---------------------------------------------------------------------------

def _tab_run() -> None:
    scenario = st.session_state.scenario
    dur_days = units.seconds_to_hours(scenario.trajectory.duration_s) / 24.0
    st.subheader("Run")
    st.write(
        f"**{scenario.name}** — {len(scenario.ship.components)} components, "
        f"{len(scenario.trajectory.waypoints)} waypoints, {dur_days:.1f} days, "
        f"dt = {units.seconds_to_hours(scenario.simulation.resolved_dt_s):.1f} h"
    )

    st.markdown("**Deterministic simulation**")
    if st.button("Run deterministic", type="primary"):
        with st.spinner("Running simulation..."):
            try:
                st.session_state.result = builders.run_deterministic(scenario)
                st.success("Done. See the Results and Plots tabs.")
            except Exception as err:
                st.error(f"Run failed:\n\n{err}")

    st.divider()
    st.markdown("**Monte Carlo uncertainty**")
    m1, m2, m3 = st.columns(3)
    n_runs = int(m1.number_input("runs", min_value=1, value=100, step=10))
    mc_seed = int(m2.number_input("seed", value=2026, step=1))
    mc_backends = builders.monte_carlo_backends()
    mc_backend = m3.selectbox("MC execution", mc_backends)
    if st.button("Run Monte Carlo"):
        st.caption("Note: a running study cannot be cancelled mid-flight.")
        with st.spinner(f"Running {n_runs} Monte Carlo simulations..."):
            try:
                st.session_state.mc_result = builders.run_monte_carlo_scenario(
                    scenario, n_runs=n_runs, random_seed=mc_seed, backend=mc_backend
                )
                st.success("Monte Carlo complete. See the Plots tab.")
            except Exception as err:
                st.error(f"Monte Carlo failed:\n\n{err}")


# ---------------------------------------------------------------------------
# Tab: results
# ---------------------------------------------------------------------------

def _tab_results() -> None:
    result = st.session_state.result
    if result is None:
        st.info("Run a deterministic simulation first (Run tab).")
        return

    ss = result.final_stability_summary
    cs = result.final_corrosion_summary

    st.subheader("Stability")
    c1, c2 = st.columns(2)
    c1.metric("Cumulative capsize probability", f"{result.cumulative_capsize_probability:.4f}")
    c2.metric("Max stability risk score (0-1)", f"{ss.get('max_risk_score', 0.0):.3f}")
    t = ss.get("time_of_max_risk_s")
    if t is not None:
        pos = ss.get("position_of_max_risk") or {}
        st.caption(
            f"Max risk at t = {units.seconds_to_hours(t):.1f} h "
            f"({units.seconds_to_hours(t)/24:.2f} d), "
            f"lat {pos.get('latitude_deg', float('nan')):.2f}, "
            f"lon {pos.get('longitude_deg', float('nan')):.2f}"
        )
    contribs = ss.get("max_risk_dominant_contributions") or {}
    if contribs:
        st.markdown("**Dominant risk contributors** (weighted)")
        st.dataframe(
            {"contributor": list(contribs.keys()),
             "weighted_contribution": [round(v, 3) for v in contribs.values()]},
            use_container_width=True,
        )

    st.subheader("Corrosion (top components)")
    rows = []
    for name, c in cs.get("by_component", {}).items():
        rows.append({
            "component": name,
            "thickness lost (%)": round(c["thickness_loss_fraction"] * 100, 2),
            "final eff. (mm)": round(c["final_effective_thickness_m"] * 1e3, 2),
            "final rate (mm/yr)": round(c["final_corrosion_rate_mm_per_year"], 3),
            "min safety factor": round(c["min_safety_margin"], 2),
        })
    rows.sort(key=lambda r: r["thickness lost (%)"], reverse=True)
    st.dataframe(rows[:5], use_container_width=True)
    st.caption(f"Most corroded: {cs.get('most_corroded_component')}")

    st.subheader(f"Warning events ({len(result.warnings)})")
    for w in result.warnings[:15]:
        st.write("- " + w)


# ---------------------------------------------------------------------------
# Tab: plots
# ---------------------------------------------------------------------------

def _tab_plots() -> None:
    if not _HAS_VIZ:
        st.warning("Plotting needs matplotlib: `pip install 'ship_sim[viz]'`.")
        return
    result = st.session_state.result
    mc = st.session_state.mc_result

    if result is not None:
        comp_names = sorted(result.timeline[0].accumulated_corrosion_m_by_component) \
            if result.timeline else []
        choice = st.selectbox("Corrosion component", ["(all)"] + comp_names)
        comp = None if choice == "(all)" else choice
        _show_fig(viz.plot_corrosion_over_time(result, component_name=comp), "corrosion.png")
        _show_fig(viz.plot_effective_thickness_over_time(result, component_name=comp),
                  "thickness.png")
        _show_fig(viz.plot_stability_risk_over_time(result), "stability.png")
        _show_fig(viz.plot_environment_over_time(result), "environment.png")
        _show_fig(viz.plot_wave_weather_over_time(result), "wave_weather.png")
    else:
        st.info("Run a deterministic simulation to see time-series plots.")

    if mc is not None:
        st.subheader("Monte Carlo distributions")
        _show_fig(viz.plot_monte_carlo_distributions(mc), "monte_carlo.png")


def _show_fig(fig, filename: str) -> None:
    st.pyplot(fig)
    st.download_button("Download PNG", builders.figure_to_png_bytes(fig),
                       file_name=filename, mime="image/png", key=f"dl_{filename}")


# ---------------------------------------------------------------------------
# Tab: route designer (custom 100 x 100 mi interactive map)
# ---------------------------------------------------------------------------

_CANVAS_PX = 600
_POINT_RADIUS = 7


def _route_state_init() -> None:
    sc = st.session_state.scenario
    if "route_center" not in st.session_state:
        wp0 = sc.trajectory.waypoints[0]
        st.session_state.route_center = (wp0.latitude_deg, wp0.longitude_deg)
    if "route_latlon" not in st.session_state:
        _seed_default_route()
    st.session_state.setdefault("route_canvas_ver", 0)
    st.session_state.setdefault("route_seed_pending", True)
    st.session_state.setdefault("route_last_sig", None)


def _make_frame() -> "rm.RouteFrame":
    clat, clon = st.session_state.route_center
    return rm.RouteFrame(clat, clon, size_miles=100.0,
                         width_px=_CANVAS_PX, height_px=_CANVAS_PX)


def _seed_default_route() -> None:
    """Seed a short diagonal local route centered in the square."""
    frame = _make_frame()
    pts_px = [
        (0.30 * frame.width_px, 0.72 * frame.height_px),
        (0.50 * frame.width_px, 0.50 * frame.height_px),
        (0.72 * frame.width_px, 0.28 * frame.height_px),
    ]
    st.session_state.route_latlon = [frame.px_to_lonlat(x, y) for x, y in pts_px]
    st.session_state.route_canvas_ver = st.session_state.get("route_canvas_ver", 0) + 1
    st.session_state.route_seed_pending = True
    st.session_state.route_last_sig = None


def _scenario_with_route(scenario, latlon, speed_m_s):
    """Replace the scenario's trajectory with the drawn route at 1/4-mile dt."""
    times = rm.cumulative_times_s(latlon, speed_m_s)
    dt_s = (0.25 * 1609.34) / speed_m_s  # one timestep per quarter mile
    data = scenario.model_dump(mode="json")
    data["trajectory"] = {
        "waypoints": [
            {
                "latitude_deg": max(-89.9, min(89.9, la)),
                "longitude_deg": ((lo + 180.0) % 360.0) - 180.0,
                "time_s": t,
                "target_speed_m_s": speed_m_s,
            }
            for (la, lo), t in zip(latlon, times)
        ]
    }
    data["simulation"]["dt_s"] = dt_s
    data["simulation"]["dt_hours"] = None
    return builders.validate_scenario(data)


def _latlon_to_en(frame, latlon):
    """Convert (lat, lon) waypoints to (east, north) miles from the frame center."""
    return [
        ((lo - frame.center_lon) * frame.miles_per_deg_lon,
         (la - frame.center_lat) * rm.MILES_PER_DEG_LAT)
        for la, lo in latlon
    ]


def _en_to_latlon(frame, en):
    """Convert (east, north) miles from center back to (lat, lon)."""
    return [
        (frame.center_lat + n / rm.MILES_PER_DEG_LAT,
         frame.center_lon + e / frame.miles_per_deg_lon)
        for e, n in en
    ]


def _waypoint_table_editor(frame, latlon):
    """Reliable inline editor: waypoints as east/north miles from center.

    Renders inline (no custom-component iframe), so it always works. Add rows to
    add waypoints, delete rows to remove, edit numbers to move. Returns the new
    (lat, lon) list.
    """
    en = _latlon_to_en(frame, latlon)
    df = pd.DataFrame(en, columns=["east_mi", "north_mi"])
    edited = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, key="route_en_table",
        column_config={
            "east_mi": st.column_config.NumberColumn(
                "East (mi)", help="East of center; -50..+50", min_value=-50.0, max_value=50.0),
            "north_mi": st.column_config.NumberColumn(
                "North (mi)", help="North of center; -50..+50", min_value=-50.0, max_value=50.0),
        },
    )
    rows = edited.to_dict(orient="records")
    new_en = [
        (max(-50.0, min(50.0, float(r["east_mi"]))),
         max(-50.0, min(50.0, float(r["north_mi"]))))
        for r in rows
        if r.get("east_mi") is not None and r.get("north_mi") is not None
    ]
    return _en_to_latlon(frame, new_en)


def _drag_canvas_expander(frame, metric, grid):
    """Optional drag-canvas (its frontend may not render in all browsers)."""
    if not _HAS_CANVAS:
        return
    with st.expander("🖱️  Drag-to-edit canvas (optional; hard-refresh if blank)"):
        st.caption(
            "If this area is empty, your browser couldn't load the canvas "
            "component — use the table above instead. **Add** mode: click to add. "
            "**Move/Delete** mode: drag a point; select and press Delete to remove."
        )
        mode_label = st.radio("Canvas mode", ["Add (click)", "Move / Delete (drag)"],
                              horizontal=True, key="canvas_mode")
        mode = "point" if mode_label.startswith("Add") else "transform"
        path_px = [frame.lonlat_to_px(la, lo) for la, lo in st.session_state.route_latlon]
        bg = rm.render_background(frame, metric=metric, grid=grid, path_px=path_px)
        initial = rm.make_initial_drawing(path_px, _POINT_RADIUS) \
            if st.session_state.route_seed_pending else None
        st.session_state.route_seed_pending = False
        result = st_canvas(
            fill_color="rgba(255,80,80,0.7)", stroke_width=2, stroke_color="#000000",
            background_image=bg, update_streamlit=True,
            height=frame.height_px, width=frame.width_px, drawing_mode=mode,
            point_display_radius=_POINT_RADIUS, initial_drawing=initial,
            key=f"route_canvas_{st.session_state.route_canvas_ver}",
        )
        if st.button("Use these canvas points", key="apply_canvas"):
            if result is not None and result.json_data is not None:
                parsed = rm.parse_points_px(result.json_data, _POINT_RADIUS)
                if parsed:
                    st.session_state.route_latlon = [frame.px_to_lonlat(x, y) for x, y in parsed]
                    st.rerun()


def _tab_route() -> None:
    _route_state_init()
    st.subheader("Route designer — 100 × 100 mi square")
    st.caption(
        "Blue ocean, white path on a fixed 100 × 100 mi square (no basemap). Edit "
        "waypoints in the table (add/remove rows, change East/North miles from "
        "center). Pick an *Ocean layer* to shade the sea by an environmental metric."
    )

    c1, c2, c3 = st.columns(3)
    metric = c1.selectbox("Ocean layer", rm.metric_options())
    speed_kn = c2.number_input("Speed (kn)", min_value=0.5, value=12.0, step=1.0)
    auto = c3.checkbox("Auto-rerun on edit", value=True)

    speed_m_s = units.knots_to_mps(speed_kn)
    cur = st.session_state.route_latlon
    dur_s = rm.cumulative_times_s(cur, speed_m_s)[-1] if len(cur) >= 2 else 0.01

    b1, b2, b3 = st.columns(3)
    rerun_clicked = b1.button("Rerun simulation", type="primary")
    if b2.button("Reset route"):
        _seed_default_route()
        st.rerun()
    snap_day = b3.slider("Ocean-layer snapshot (day)", 0.0, max(0.01, dur_s / 86400.0), 0.0)

    frame = _make_frame()

    # --- inline editor (always renders) drives the route ----------------
    left, right = st.columns([1, 2])
    with left:
        st.session_state.route_latlon = _waypoint_table_editor(frame, st.session_state.route_latlon)
    latlon = st.session_state.route_latlon

    # --- metric field + map image (inline <img>, always renders) --------
    env_p, wx_p, wave_p = build_providers(st.session_state.scenario)
    grid = None
    if rm.is_metric(metric):
        with st.spinner(f"Sampling {metric} field..."):
            grid = rm.sample_metric_grid(metric, env_p, wx_p, wave_p, frame,
                                         snap_day * 86400.0, n=32)
    path_px = [frame.lonlat_to_px(la, lo) for la, lo in latlon]
    bg = rm.render_background(frame, metric=metric, grid=grid, path_px=path_px)
    with right:
        st.image(bg, caption="Ocean (blue) and route (white). North = up, East = right.")

    dist = rm.path_distance_miles(latlon) if len(latlon) >= 2 else 0.0
    m1, m2, m3 = st.columns(3)
    m1.metric("Path distance", f"{dist:.1f} mi")
    m2.metric("Waypoints", str(len(latlon)))
    if grid is not None:
        m3.caption(
            f"{metric}: {grid.min():.2f}–{grid.max():.2f} {rm.metric_unit(metric)} "
            f"(snapshot day {snap_day:.1f})"
        )

    _drag_canvas_expander(frame, metric, grid)

    if len(latlon) < 2:
        st.warning("Add at least 2 waypoints (rows) to simulate.")
        return

    sig = (tuple((round(a, 5), round(b, 5)) for a, b in latlon), round(speed_kn, 3))
    if rerun_clicked or (auto and sig != st.session_state.route_last_sig):
        with st.spinner(f"Simulating {dist:.0f} mi route at ¼-mile steps..."):
            try:
                sc2 = _scenario_with_route(st.session_state.scenario, latlon, speed_m_s)
                st.session_state.result = builders.run_deterministic(sc2)
                st.session_state.route_last_sig = sig
            except Exception as err:
                st.error(f"Run failed:\n\n{err}")

    res_obj = st.session_state.result
    if res_obj is not None:
        ss = res_obj.final_stability_summary
        r1, r2, r3 = st.columns(3)
        r1.metric("Cumulative capsize prob.", f"{res_obj.cumulative_capsize_probability:.4f}")
        r2.metric("Max stability risk (0-1)", f"{ss.get('max_risk_score', 0.0):.3f}")
        r3.metric("Timesteps (¼-mile)", str(len(res_obj.timeline)))
        st.caption("Full plots and reports are in the Results, Plots, and Export tabs.")


# ---------------------------------------------------------------------------
# Tab: export
# ---------------------------------------------------------------------------

def _tab_export() -> None:
    scenario = st.session_state.scenario
    result = st.session_state.result
    st.subheader("Export")

    st.download_button("Scenario JSON", builders.export_scenario_json(scenario),
                       file_name="scenario.json", mime="application/json")

    if result is not None:
        include_tl = st.checkbox("Include full timeline in result JSON", value=False)
        st.download_button(
            "Result JSON",
            builders.export_result_json(result, include_timeline=include_tl),
            file_name="result.json", mime="application/json",
        )
        st.download_button(
            "Markdown report", builders.export_report_markdown(result),
            file_name="report.md", mime="text/markdown",
        )
    else:
        st.info("Run a simulation to enable result/report export.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="ship_sim dashboard", layout="wide")
    _init_state()
    st.title("ship_sim — corrosion & stability dashboard")
    st.warning(
        "ENGINEERING APPROXIMATION — NOT a certified naval safety tool. " + DISCLAIMER
    )
    _sidebar()

    tabs = st.tabs(
        ["Scenario & edit", "Run", "Results", "Plots", "Route", "Export"]
    )
    with tabs[0]:
        _tab_scenario()
    with tabs[1]:
        _tab_run()
    with tabs[2]:
        _tab_results()
    with tabs[3]:
        _tab_plots()
    with tabs[4]:
        _tab_route()
    with tabs[5]:
        _tab_export()


# Streamlit runs this script with __name__ == "__main__".
if __name__ == "__main__":
    main()
