"""Optional GUI/dashboard for ship_sim.

The dashboard ([`streamlit_app.py`](streamlit_app.py)) is a thin Streamlit layer
over the tested simulation core -- it contains no physics and calls the same
scenario loader, engine, Monte Carlo, reporting, and visualization APIs as the
CLI. The dependency-light, unit-tested helpers live in :mod:`ship_sim.gui.builders`
(importable without Streamlit installed).

Launch with::

    pip install -e ".[gui]"
    streamlit run ship_sim/gui/streamlit_app.py
"""

from __future__ import annotations

from pathlib import Path

# Re-export the testable helpers (no Streamlit import here, so importing
# ``ship_sim.gui`` never requires Streamlit).
from . import builders
from .builders import (
    assemble_scenario_dict,
    default_demo_scenario,
    export_report_markdown,
    export_result_json,
    export_scenario_json,
    inline_components,
    run_deterministic,
    run_monte_carlo_scenario,
    scenario_to_editable,
    validate_scenario,
)


def streamlit_app_path() -> Path:
    """Absolute path to the Streamlit entry script (for ``streamlit run``)."""
    return Path(__file__).resolve().parent / "streamlit_app.py"


__all__ = [
    "builders",
    "streamlit_app_path",
    "default_demo_scenario",
    "scenario_to_editable",
    "validate_scenario",
    "inline_components",
    "assemble_scenario_dict",
    "run_deterministic",
    "run_monte_carlo_scenario",
    "export_scenario_json",
    "export_result_json",
    "export_report_markdown",
]
