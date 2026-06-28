# Benchmarks

Profiling to decide whether a compiled backend is justified. **Run:**

```bash
python benchmarks/benchmark_engine.py        # timesteps/sec, component-updates/sec, memory
python benchmarks/benchmark_monte_carlo.py   # MC runs/sec, python-vs-numpy batch, memory
```

## Representative results (Python 3.11, single core)

| metric | value |
|---|---|
| engine timesteps / sec | ~100 |
| engine component-updates / sec | ~3,000 |
| Monte Carlo full runs / sec (5-day voyage, 6 components) | ~8 |
| corrosion batch — python | ~1.1M updates/sec |
| corrosion batch — numpy | ~4.9M updates/sec (≈4.3× python) |
| peak memory (1500 steps × 30 comps) | ~22 MB |

## Conclusion: no compiled backend needed (yet)

- The corrosion/stability **math is not the bottleneck** — the standalone
  corrosion kernels already run at 1–5M component-updates/sec, far above the
  engine's ~3,000/sec.
- The engine's per-timestep cost is dominated by **Python object / Pydantic
  state construction and the rich traceable `intermediate_physics_values`**, not
  numeric work. A Rust/C++/Numba kernel for the math would therefore **not**
  speed up the engine meaningfully.
- For **normal scenarios** (days–weeks at hourly–6-hourly steps, a few dozen
  components) runs complete in well under a second to a few seconds — fast
  enough.
- For **large Monte Carlo studies**, the right lever is process-level
  parallelism (`joblib`/`multiprocessing`) since runs are embarrassingly
  parallel — again, not a compiled inner loop.

So the project ships only the `python` and `numpy` backends
([`ship_sim/acceleration/backend.py`](../ship_sim/acceleration/backend.py)). The
abstraction keeps `numba`/`rust`/`cpp` as clean future options should a profiled
workload ever demand them (e.g. millions of MC runs, or moving the whole
timestep loop — not just the math — into a compiled extension).
