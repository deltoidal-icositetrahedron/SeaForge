"""Thin wrapper so the demo runs as ``python examples/demo_basic.py``.

The implementation lives in :mod:`ship_sim.examples.demo_basic` (which also
supports ``python -m ship_sim.examples.demo_basic``). See that module's
docstring for usage and options (e.g. ``--scenario examples/scenario_basic.json``).
"""

from __future__ import annotations

from ship_sim.examples.demo_basic import main

if __name__ == "__main__":
    main()
