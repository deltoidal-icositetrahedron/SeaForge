# SeaForge

A naval simulation engine (Rust) with a React/Three.js globe UI. It simulates a
vessel's voyage and the **damage mechanisms** that can end it — corrosion,
wave-induced fatigue, crack growth/fracture, hull-girder stress, and
stability/capsize — then searches for survivable, low-cost configurations.

- `src/` — Rust simulation engine (`cargo build --release` → `seaforge_v2`).
- `ui/` — Vite + React + Three.js front end and an Express API (`ui/server.js`).
- `gemini_runner/` — optional LLM-in-the-loop config optimizer (Google Gemini).
- `ml/` — optional NumPy surrogate + generator that learns ship designs from the
  simulator.

## Run

```bash
cargo build --release            # build the simulation binary
cd ui && npm install
npx concurrently "npm run api" "npm run dev"   # API :3001 + UI :5173
# open http://localhost:5173
```

`npm run sim` runs one simulation from the CLI.

---

# Scientific basis & references

The simulator is a **simplified engineering implementation** of established
naval-architecture and materials methods — it is not a certified tool and does
not reproduce any single paper's full model, but each mechanism is grounded in
the literature below, mapped to the source file that implements it.

## Corrosion — `src/physics/corrosion.rs`
Environmental-factor corrosion rate (`base × salinity × temperature × pH ×
submersion`) with an Arrhenius/Q₁₀ temperature factor `2^(ΔT/10)`, diffusion-limited
pit growth `∝ √t`, and a pit stress-concentration term feeding corrosion-fatigue.
- Melchers, R.E. (2003). *Modeling of Marine Immersion Corrosion for Mild and Low-Alloy Steels — Part 1: Phenomenological Model.* Corrosion, 59(4), 319–334.
- Guedes Soares, C., & Garbatov, Y. (1999). *Reliability of maintained, corrosion-protected plates subjected to non-linear corrosion and compressive loads.* Marine Structures, 12(6), 425–445.
- Arrhenius, S. (1889) / van't Hoff Q₁₀ rule — temperature dependence of reaction rate.
- Inglis, C.E. (1913). *Stresses in a plate due to the presence of cracks and sharp corners.* Trans. INA, 55, 219–241. — pit/notch stress concentration.

## Wave-induced fatigue — `src/physics/structural.rs`
Narrow-band Rayleigh spectral fatigue: `D = N·σ_sig^m·Γ(1+m/2)/(2^m·C_sn)`,
`C_sn = σ_ref^m·N_ref`, with an endurance cut-off.
- Basquin, O.H. (1910). *The exponential law of endurance tests.* Proc. ASTM, 10, 625–630. — S-N curve.
- Miner, M.A. (1945). *Cumulative damage in fatigue.* J. Applied Mechanics, 12(3), A159–A164.
- Rice, S.O. (1944/45). *Mathematical analysis of random noise.* Bell System Tech. J., 23–24. — Rayleigh peak distribution.
- Wirsching, P.H., & Light, M.C. (1980). *Fatigue under wide-band random stresses.* J. Structural Division (ASCE), 106(7), 1593–1607. — the Γ(1+m/2)/2^m spectral factor.
- DNV-RP-C203, *Fatigue Design of Offshore Steel Structures.*

## Hull-girder wave bending stress — `src/physics/structural.rs`
Linear-wave (Froude-Krylov) bending moment / hollow-box section modulus
`Z = I/(D/2)`, scaled to the significant level, × weld stress-concentration factor.
- Froude, W. (1861) & Krylov, A.N. (1896) — Froude-Krylov wave excitation.
- Ochi, M.K. (1978). *Wave statistics for the design of ships and ocean structures.* Trans. SNAME, 86.
- Lewis, E.V. (ed.) (1988). *Principles of Naval Architecture, Vols. I–II.* SNAME.

## Crack growth & brittle fracture — `src/physics/structural.rs`
`K = σ·F·√(πa)` (F ≈ 1.12), Paris-law growth `da/dN = C·ΔK^n`, fracture when `K ≥ K_IC`.
- Griffith, A.A. (1921). *The phenomena of rupture and flow in solids.* Phil. Trans. R. Soc. A, 221, 163–198.
- Irwin, G.R. (1957). *Analysis of stresses and strains near the end of a crack traversing a plate.* J. Applied Mechanics, 24, 361–364. — stress-intensity factor.
- Paris, P., & Erdogan, F. (1963). *A critical analysis of crack propagation laws.* J. Basic Engineering, 85(4), 528–533.
- BS 7910, *Guide to methods for assessing the acceptability of flaws in metallic structures.*

## Stability & capsize — `src/physics/stability.rs`
`GM = KB + BM − KG` with KB via Morrish's formula and `BM = I_waterplane/V`;
`GM_min ≥ 0.07·B`; static + dynamic beam-sea-resonance capsize criterion.
- Lewis, E.V. (ed.) (1988). *Principles of Naval Architecture, Vol. I.* SNAME. — KB/BM/GM, Morrish's approximation.
- Biran, A., & López-Pulido, R. (2014). *Ship Hydrostatics and Stability,* 2nd ed., Butterworth-Heinemann.
- IMO (2008). *International Code on Intact Stability (2008 IS Code),* Res. MSC.267(85).
- IMO (2020). *Interim Guidelines on the Second Generation Intact Stability Criteria,* MSC.1/Circ.1627.

## Sea state / wave spectrum — `src/environment/ocean.rs`
JONSWAP γ; `Tz ≈ 0.710·Tp` (γ=3.3) → `0.77·Tp` (γ=1, Pierson-Moskowitz);
deep-water steepness `λ_p = g·Tp²/2π`.
- Hasselmann, K., et al. (1973). *Measurements of wind-wave growth and swell decay during the Joint North Sea Wave Project (JONSWAP).* Dtsch. Hydrogr. Z., A(8), No. 12.
- Pierson, W.J., & Moskowitz, L. (1964). *A proposed spectral form for fully developed wind seas…* J. Geophysical Research, 69(24), 5181–5190.
- DNV-RP-C205, *Environmental Conditions and Environmental Loads.* — JONSWAP spectral-moment relations.
- Airy, G.B. (1845) — linear (deep-water) wave theory / dispersion.

---

> **Disclaimer:** SeaForge is an engineering approximation for exploration and
> education. It is not validated against classification-society rules and must
> not be used for real-world design, safety, or operational decisions.
