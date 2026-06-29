#!/usr/bin/env python3
"""Generate a 1-degree global ocean/weather constants grid for SeaForge.

Output: data/ocean_grid.bin  (read by src/environment/ocean_grid.rs)
        data/ocean_grid.meta.json  (provenance / human-readable summary)

Per 1deg cell we store 8 environmental constants that map directly onto the
Rust `OceanConditions` struct (encounter_angle is vessel-relative, not gridded):

    hs_m, tp_s, jonswap_gamma, water_temp_c, salinity_ppt, ph,
    wind_speed_ms, slam_probability

Data sources (best-effort, "as accurate as possible"):
  * water_temp_c  -> real NOAA OISST v2.1 sea-surface temperature (ERDDAP),
                     averaged over four seasonal snapshots; falls back to a
                     latitudinal climatology if the network is unavailable.
  * everything else -> physically-grounded climatology (zonal wind belts,
                       fetch/wind-driven sea state, subtropical salinity maxima,
                       CO2-driven pH), modulated by the real SST field where it
                       informs the physics (e.g. warmer water -> lower density).

The grid is intentionally smooth; the Rust sampler bilinearly interpolates it,
so a 1deg store yields continuous per-tick conditions along any route.
"""
import json
import struct
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT_BIN = ROOT / "data" / "ocean_grid.bin"
OUT_META = ROOT / "data" / "ocean_grid.meta.json"

NLAT = 180
NLON = 360
DLAT = 1.0
DLON = 1.0
LAT0 = -89.5   # cell-center latitude of row 0 (south)
LON0 = -179.5  # cell-center longitude of col 0 (west)

VARS = [
    "hs_m", "tp_s", "jonswap_gamma", "water_temp_c",
    "salinity_ppt", "ph", "wind_speed_ms", "slam_probability",
]

OISST_DATASET = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.csv"
OISST_DATES = ["2022-01-01", "2022-04-01", "2022-07-01", "2022-10-01"]

# Grid coordinate vectors (cell centers).
lats = LAT0 + np.arange(NLAT) * DLAT          # -89.5 .. 89.5
lons = LON0 + np.arange(NLON) * DLON          # -179.5 .. 179.5
LatG, LonG = np.meshgrid(lats, lons, indexing="ij")   # (NLAT, NLON)


def fetch_real_sst():
    """Average a few seasonal OISST snapshots into a 1deg annual-mean SST field.

    Returns an (NLAT, NLON) array in degC with NaN where unavailable, or None
    if every request failed.
    """
    fields = []
    for date in OISST_DATES:
        # Server-side stride (:4:) downsamples OISST's 0.25deg grid to ~1deg.
        query = (
            f"{OISST_DATASET}?sst"
            f"%5B({date}T12:00:00Z)%5D%5B(0.0)%5D"
            f"%5B(-89.875):4:(89.875)%5D%5B(-179.875):4:(179.875)%5D"
        )
        try:
            print(f"  fetching OISST {date} ...", file=sys.stderr)
            with urllib.request.urlopen(query, timeout=60) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - network is best-effort
            print(f"    failed: {exc}", file=sys.stderr)
            continue

        grid = np.full((NLAT, NLON), np.nan, dtype=np.float64)
        for line in raw.splitlines()[2:]:  # skip 2 header lines
            parts = line.split(",")
            if len(parts) < 5 or not parts[4]:
                continue
            try:
                lat = float(parts[2]); lon = float(parts[3]); sst = float(parts[4])
            except ValueError:
                continue
            r = int(round((lat - LAT0) / DLAT))
            c = int(round((lon - LON0) / DLON))
            if 0 <= r < NLAT and 0 <= c < NLON:
                grid[r, c] = sst
        if np.isfinite(grid).any():
            fields.append(grid)

    if not fields:
        return None
    stack = np.stack(fields)
    return np.nanmean(stack, axis=0)


def parametric_sst():
    """Latitudinal annual-mean SST fallback (warm equator, cold poles)."""
    abslat = np.abs(LatG)
    sst = 28.0 * np.cos(np.radians(abslat * 0.95)) ** 1.4 - 2.0
    return np.clip(sst, -1.8, 31.0)


def zonal_wind_ms():
    """Climatological surface wind speed by latitude: doldrums, trades,
    roaring forties/furious fifties, calmer poles."""
    lat = LatG
    abslat = np.abs(lat)
    doldrums = 3.0 + 4.0 * np.exp(-((abslat - 0.0) / 6.0) ** 2)        # weak ~equator
    trades = 7.5 * np.exp(-((abslat - 16.0) / 10.0) ** 2)              # steady trades
    horse = -2.5 * np.exp(-((abslat - 30.0) / 6.0) ** 2)              # subtropical calm
    westerlies = 12.5 * np.exp(-((abslat - 52.0) / 12.0) ** 2)        # storm belts
    polar = 5.0 * np.exp(-((abslat - 80.0) / 10.0) ** 2)
    wind = 4.5 + doldrums * 0.2 + trades + horse + westerlies + polar
    # Southern Ocean is notoriously windier than the northern mirror.
    wind += np.where(lat < -35, 2.2 * np.exp(-((abslat - 55.0) / 14.0) ** 2), 0.0)
    return np.clip(wind, 2.0, 22.0)


def main():
    online = "--offline" not in sys.argv
    sst = fetch_real_sst() if online else None
    sst_source = "NOAA OISST v2.1 (ERDDAP), 4-season mean"
    if sst is None:
        print("  no real SST; using latitudinal fallback", file=sys.stderr)
        sst = parametric_sst()
        sst_source = "parametric latitudinal climatology (network unavailable)"
    else:
        # Fill land/ice NaNs with the parametric field so interpolation is smooth.
        fallback = parametric_sst()
        sst = np.where(np.isfinite(sst), sst, fallback)

    abslat = np.abs(LatG)
    wind = zonal_wind_ms()

    # Fully-developed sea: Hs ~ scales with wind^2 (Pierson-Moskowitz-ish),
    # boosted slightly in the high-latitude storm belts (long fetch).
    storm_belt = 1.0 + 0.6 * np.exp(-((abslat - 52.0) / 14.0) ** 2)
    hs = np.clip(0.022 * wind ** 2 * storm_belt, 0.4, 11.0)

    # Peak period from wave age (longer swell with stronger, more developed seas).
    tp = np.clip(3.5 + 0.55 * wind + 1.8 * storm_belt, 5.0, 17.0)

    # JONSWAP peakedness: open-ocean swell ~2.2, steeper fetch-limited mid-lats.
    gamma = np.clip(2.0 + 1.4 * np.exp(-((abslat - 45.0) / 25.0) ** 2), 1.6, 4.2)

    # Subtropical salinity maxima (~37), fresher equator (rain) and poles (melt).
    salinity = (
        34.8
        + 2.1 * np.exp(-((abslat - 25.0) / 14.0) ** 2)   # subtropical highs
        - 1.1 * np.exp(-((abslat - 0.0) / 6.0) ** 2)      # ITCZ rainfall
        - 1.8 * np.exp(-((abslat - 75.0) / 14.0) ** 2)    # polar melt
    )
    salinity = np.clip(salinity, 30.0, 38.0)

    # Surface pH: ~8.1 global mean, marginally lower in warm CO2-rich tropics
    # and cold high-solubility poles trend slightly lower too.
    ph = np.clip(8.12 - 0.02 * np.cos(np.radians(abslat)) - 0.03 * (sst > 26), 7.92, 8.18)

    # Wave steepness -> slamming probability proxy.
    lambda_p = 9.81 * tp ** 2 / (2.0 * np.pi)
    steepness = hs / np.maximum(lambda_p, 1.0)
    slam = np.clip((steepness - 0.008) / 0.05 + 0.05 * (wind / 20.0), 0.02, 0.98)

    planes = {
        "hs_m": hs, "tp_s": tp, "jonswap_gamma": gamma, "water_temp_c": sst,
        "salinity_ppt": salinity, "ph": ph, "wind_speed_ms": wind,
        "slam_probability": slam,
    }

    OUT_BIN.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_BIN, "wb") as f:
        f.write(b"OCGRID02")
        f.write(struct.pack("<iii", NLAT, NLON, len(VARS)))
        f.write(struct.pack("<dddd", LAT0, LON0, DLAT, DLON))
        for name in VARS:
            f.write(planes[name].astype("<f4").tobytes())

    meta = {
        "format": "OCGRID02",
        "nlat": NLAT, "nlon": NLON, "nvars": len(VARS),
        "lat0": LAT0, "lon0": LON0, "dlat": DLAT, "dlon": DLON,
        "var_order": VARS,
        "row_major": "index = lat_row * nlon + lon_col; row 0 = -89.5 (south)",
        "sources": {
            "water_temp_c": sst_source,
            "others": "physically-grounded zonal climatology (wind belts, "
                      "fetch/wind sea state, subtropical salinity, CO2 pH)",
        },
        "summary": {
            name: {"min": float(np.nanmin(p)), "max": float(np.nanmax(p)),
                   "mean": float(np.nanmean(p))}
            for name, p in planes.items()
        },
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"wrote {OUT_BIN} ({OUT_BIN.stat().st_size/1e6:.2f} MB) and {OUT_META.name}")
    for name, p in planes.items():
        print(f"  {name:16s} min={np.nanmin(p):8.3f} mean={np.nanmean(p):8.3f} max={np.nanmax(p):8.3f}")


if __name__ == "__main__":
    main()
