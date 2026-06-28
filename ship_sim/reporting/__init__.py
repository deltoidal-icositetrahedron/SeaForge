"""Human-readable reporting from simulation results."""

from __future__ import annotations

from .reports import (
    MODEL_LIMITATIONS,
    RECOMMENDED_DATA,
    RECOMMENDED_IMPROVEMENTS,
    generate_corrosion_report,
    generate_overall_risk_report,
    generate_stability_report,
)

__all__ = [
    "generate_corrosion_report",
    "generate_stability_report",
    "generate_overall_risk_report",
    "MODEL_LIMITATIONS",
    "RECOMMENDED_IMPROVEMENTS",
    "RECOMMENDED_DATA",
]
