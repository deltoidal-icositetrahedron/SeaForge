# Gemini Simulation Runner

Runs SeaForge simulations, asks Gemini to diagnose failures, and reruns with revised parameters.

Do not commit API keys. Set the key in your shell:

```bash
export GEMINI_API_KEY="..."
export GEMINI_MODEL="gemini-3.5-pro"
node gemini_runner/run_gemini_simulations.js --input examples/simulation_params.json --max-iterations 4
```

Every simulation iteration is saved under:

```text
simulations/<run-id>/iteration-XX/
  params.json
  result.json
  assessment.json
```
