"""Thin wrapper so the Monte Carlo demo runs as ``python examples/monte_carlo_demo.py``.

The implementation lives in :mod:`ship_sim.examples.monte_carlo_demo` (which also
supports ``python -m ship_sim.examples.monte_carlo_demo``). See that module's
docstring for usage and options.
"""

from __future__ import annotations

from ship_sim.examples.monte_carlo_demo import main

if __name__ == "__main__":
    main()
