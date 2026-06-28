#!/usr/bin/env node
import { spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { MAX_ITERATIONS } from './config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT = path.resolve(__dirname, '..');
const DEFAULT_INPUT = path.join(ROOT, 'examples', 'simulation_params.json');
const DEFAULT_BINARY = path.join(ROOT, 'target', 'release', 'seaforge_v2');
const SIM_DIR = path.join(ROOT, 'simulations');
const MISSION_BRIEFS_DIR = path.join(ROOT, 'mission-briefs');
const GLOBAL_DESIGN_MEMORY_FILE = path.join(ROOT, 'gemini_runner', 'design_memory.json');
const HULL_ZONE_KEYS = [
  'Keel',
  'BilgeStrake',
  'BottomPlating',
  'SidePlating',
  'BowFlare',
  'SternPlate',
  'TransomFrame',
  'WeatherDeck',
  'BulkheadFrame',
];
const HULL_ZONE_LABEL_TO_KEY = new Map([
  ['keel', 'Keel'],
  ['bilgestrake', 'BilgeStrake'],
  ['bottomplating', 'BottomPlating'],
  ['sideplating', 'SidePlating'],
  ['bowflare', 'BowFlare'],
  ['sternplate', 'SternPlate'],
  ['transomframe', 'TransomFrame'],
  ['weatherdeck', 'WeatherDeck'],
  ['bulkheadframe', 'BulkheadFrame'],
]);
const MATERIALS = [
  'MildSteelA',
  'Eh36',
  'Aluminum5083',
  'GrpEGlass',
  'CfrpEpoxy',
  'TitaniumGrade5',
  'NickelAlloy625',
  'KevlarComposite',
  'TungstenCarbide',
];
const WELD_QUALITIES = ['Economy', 'Standard', 'Premium'];
const SEAL_QUALITIES = ['Economy', 'Marine'];
const DEFAULT_PROPULSION = {
  max_power_kw: 300.0,
  fuel_capacity_kg: 2000.0,
  sfc_g_per_kwh: 220.0,
  propulsive_efficiency: 0.72,
  hull_drag_coeff: 0.007,
};
const EXPLORATION_STRATEGIES = [
  'targeted_reinforcement',
  'weld_quality_path',
  'material_substitution',
  'lightweight_composite_path',
  'fuel_drag_tradeoff',
  'cost_cut_from_best',
];

function loadEnvFile(file) {
  if (!fs.existsSync(file)) return;
  const text = fs.readFileSync(file, 'utf8');
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const eq = trimmed.indexOf('=');
    if (eq < 0) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim().replace(/^['"]|['"]$/g, '');
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

loadEnvFile(path.join(ROOT, '.env'));

function argValue(name, fallback = null) {
  const prefix = `--${name}=`;
  const inline = process.argv.find((arg) => arg.startsWith(prefix));
  if (inline) return inline.slice(prefix.length);
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : fallback;
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function readJsonIfExists(file, fallback = null) {
  if (!fs.existsSync(file)) return fallback;
  try {
    return readJson(file);
  } catch (_) {
    return fallback;
  }
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
}

function normalizeZoneKey(value) {
  if (!value) return null;
  const raw = String(value);
  if (HULL_ZONE_KEYS.includes(raw)) return raw;
  const compact = raw.replace(/[^A-Za-z0-9]/g, '').toLowerCase();
  return HULL_ZONE_LABEL_TO_KEY.get(compact) ?? null;
}

function coerceEnum(value, allowed, fallback) {
  const match = allowed.find((item) => item.toLowerCase() === String(value ?? '').toLowerCase());
  const fallbackMatch = allowed.find((item) => item.toLowerCase() === String(fallback ?? '').toLowerCase());
  return match ?? fallbackMatch ?? allowed[0];
}

function materialValue(value, fallback) {
  if (value && typeof value === 'object') {
    const grade = value.grade ?? value.label ?? null;
    return coerceEnum(grade, MATERIALS, fallback ?? 'MildSteelA');
  }
  return coerceEnum(value, MATERIALS, fallback ?? 'MildSteelA');
}

function normalizeZoneSpec(zone, fallback = {}) {
  const zoneKey = normalizeZoneKey(zone?.zone ?? fallback.zone);
  if (!zoneKey) return null;
  return {
    zone: zoneKey,
    material: materialValue(zone?.material, fallback.material),
    thickness_m: Number.isFinite(Number(zone?.thickness_m))
      ? Math.max(0.003, Math.min(Number(zone.thickness_m), 0.02))
      : fallback.thickness_m ?? 0.004,
    weld_quality: coerceEnum(zone?.weld_quality, WELD_QUALITIES, fallback.weld_quality ?? 'Economy'),
    seal_quality: coerceEnum(zone?.seal_quality, SEAL_QUALITIES, fallback.seal_quality ?? 'Economy'),
  };
}

function missionBriefFileById(missionId) {
  if (!missionId || !/^[A-Za-z0-9_-]+$/.test(missionId)) return null;
  if (!fs.existsSync(MISSION_BRIEFS_DIR)) return null;

  for (const file of fs.readdirSync(MISSION_BRIEFS_DIR)) {
    if (!file.endsWith('.json')) continue;
    const fullPath = path.join(MISSION_BRIEFS_DIR, file);
    const brief = readJson(fullPath);
    if (brief?.id === missionId) return fullPath;
  }

  return null;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function clearSimulationRuns() {
  fs.mkdirSync(SIM_DIR, { recursive: true });
  for (const entry of fs.readdirSync(SIM_DIR)) {
    if (entry === '.gitkeep') continue;
    fs.rmSync(path.join(SIM_DIR, entry), { recursive: true, force: true });
  }
}

function runRustSimulation(binary, paramsFile, resultFile) {
  const result = spawnSync(binary, ['simulate-params', paramsFile, resultFile], {
    cwd: ROOT,
    encoding: 'utf8',
    timeout: 120000,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Rust simulation failed:\n${result.stderr || result.stdout}`);
  }
  if (!fs.existsSync(resultFile)) {
    throw new Error('Rust simulation produced no result file');
  }
  return {
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function runRustBrief(binary, briefFile, resultFile, tier) {
  const result = spawnSync(binary, ['brief', briefFile, resultFile, `--tier=${tier}`], {
    cwd: ROOT,
    encoding: 'utf8',
    timeout: 120000,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Rust mission brief simulation failed:\n${result.stderr || result.stdout}`);
  }
  if (!fs.existsSync(resultFile)) {
    throw new Error('Rust mission brief simulation produced no result file');
  }
  return {
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  };
}

function extractJsonObject(text) {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const raw = fenced ? fenced[1] : text;
  const start = raw.indexOf('{');
  const end = raw.lastIndexOf('}');
  if (start < 0 || end < start) {
    throw new Error(`Gemini response did not contain a JSON object: ${text.slice(0, 500)}`);
  }
  return JSON.parse(raw.slice(start, end + 1));
}

function effectiveZonesFromResult(result) {
  return Array.isArray(result?.configuration?.zones)
    ? result.configuration.zones.map((zone) => ({
      zone: zone.zone_key ?? zone.zone,
      material: zone.material,
      thickness_m: zone.thickness_m,
      weld_quality: zone.weld_quality,
      seal_quality: zone.seal_quality,
    }))
    : [];
}

function completeZonesFromResult(result, candidateZones = []) {
  const byKey = new Map();

  for (const zone of effectiveZonesFromResult(result)) {
    const normalized = normalizeZoneSpec(zone);
    if (normalized) byKey.set(normalized.zone, normalized);
  }

  for (const zone of candidateZones) {
    const key = normalizeZoneKey(zone?.zone);
    const normalized = normalizeZoneSpec(zone, key ? byKey.get(key) : undefined);
    if (normalized) byKey.set(normalized.zone, normalized);
  }

  return HULL_ZONE_KEYS.map((zone) => byKey.get(zone) ?? {
    zone,
    material: 'MildSteelA',
    thickness_m: 0.004,
    weld_quality: 'Economy',
    seal_quality: 'Economy',
  });
}

function effectivePropulsionFromResult(result, document = {}) {
  const fromResult = result?.configuration?.propulsion ?? {};
  const fromDocument = document.propulsion ?? {};
  return {
    max_power_kw: Number(fromDocument.max_power_kw ?? fromResult.max_power_kw ?? DEFAULT_PROPULSION.max_power_kw),
    fuel_capacity_kg: Number(fromDocument.fuel_capacity_kg ?? fromResult.fuel_capacity_kg ?? DEFAULT_PROPULSION.fuel_capacity_kg),
    sfc_g_per_kwh: Number(fromDocument.sfc_g_per_kwh ?? fromResult.sfc_g_per_kwh ?? DEFAULT_PROPULSION.sfc_g_per_kwh),
    propulsive_efficiency: Number(fromDocument.propulsive_efficiency ?? fromResult.propulsive_efficiency ?? DEFAULT_PROPULSION.propulsive_efficiency),
    hull_drag_coeff: Number(fromDocument.hull_drag_coeff ?? fromResult.hull_drag_coeff ?? DEFAULT_PROPULSION.hull_drag_coeff),
  };
}

function normalizePropulsion(propulsion, fallback = DEFAULT_PROPULSION) {
  return {
    max_power_kw: Math.max(1, Number(propulsion?.max_power_kw ?? fallback.max_power_kw)),
    fuel_capacity_kg: Math.max(1, Number(propulsion?.fuel_capacity_kg ?? fallback.fuel_capacity_kg)),
    sfc_g_per_kwh: Math.max(1, Number(propulsion?.sfc_g_per_kwh ?? fallback.sfc_g_per_kwh)),
    propulsive_efficiency: Math.max(0.1, Math.min(Number(propulsion?.propulsive_efficiency ?? fallback.propulsive_efficiency), 1)),
    hull_drag_coeff: Math.max(0.001, Number(propulsion?.hull_drag_coeff ?? fallback.hull_drag_coeff)),
  };
}

function clampNumber(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function roundNumber(value, digits = 6) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function candidateSignature(document, mode) {
  if (mode === 'brief') {
    return JSON.stringify({
      zones: (document.zones ?? []).map((zone) => normalizeZoneSpec(zone)).filter(Boolean),
      propulsion: normalizePropulsion(document.propulsion, DEFAULT_PROPULSION),
    });
  }
  return JSON.stringify(document);
}

function materialRank(material) {
  const order = new Map(MATERIALS.map((item, index) => [item, index]));
  return order.get(materialValue(material, 'MildSteelA')) ?? 0;
}

function cheaperMaterial(material) {
  const current = materialValue(material, 'MildSteelA');
  const rank = materialRank(current);
  return MATERIALS[Math.max(0, rank - 1)] ?? current;
}

function strongerMaterial(material) {
  const current = materialValue(material, 'MildSteelA');
  const rank = materialRank(current);
  return MATERIALS[Math.min(MATERIALS.length - 1, rank + 1)] ?? current;
}

function downgradeWeld(weld) {
  if (weld === 'Premium') return 'Standard';
  if (weld === 'Standard') return 'Economy';
  return 'Economy';
}

function upgradeWeld(weld) {
  if (weld === 'Economy') return 'Standard';
  if (weld === 'Standard') return 'Premium';
  return 'Premium';
}

function zonesByRisk(result) {
  const failureZone = normalizeZoneKey(result?.failure?.detail?.failed_zone);
  const finalTick = Array.isArray(result?.ticks) ? result.ticks.at(-1) : null;
  const tickZones = Array.isArray(finalTick?.zones) ? finalTick.zones : [];
  const ranked = tickZones
    .map((zone) => ({
      zone: normalizeZoneKey(zone.zone),
      score: Number(zone.fatigue_consumed ?? 0) * 100
        + Number(zone.crack_half_length_mm ?? 0) * 2
        + Number(zone.corrosion_depth_mm ?? 0) * 10
        + Number(zone.peak_stress_mpa ?? 0) / 1000,
    }))
    .filter((zone) => zone.zone)
    .sort((a, b) => b.score - a.score)
    .map((zone) => zone.zone);

  return [...new Set([failureZone, ...ranked].filter(Boolean))];
}

function mutateExploratoryDocument(currentDocument, result, bestDocument, mode, iteration) {
  if (mode !== 'brief') return null;

  const strategy = EXPLORATION_STRATEGIES[(iteration - 1) % EXPLORATION_STRATEGIES.length];
  const seed = bestDocument ?? currentDocument;
  const next = cloneJson(seed);
  const resultZones = completeZonesFromResult(result, next.zones ?? []);
  const riskyZones = zonesByRisk(result);
  const primaryTarget = riskyZones[0] ?? resultZones[iteration % resultZones.length]?.zone ?? 'Keel';
  const secondaryTarget = riskyZones[1] ?? resultZones[(iteration + 3) % resultZones.length]?.zone ?? 'BottomPlating';
  const targetSet = new Set([primaryTarget, secondaryTarget]);

  next.zones = resultZones.map((zone, index) => {
    const mutated = { ...zone };
    const isTarget = targetSet.has(zone.zone);

    if (strategy === 'targeted_reinforcement' && isTarget) {
      mutated.material = strongerMaterial(mutated.material);
      mutated.thickness_m = roundNumber(clampNumber(mutated.thickness_m * 1.22, 0.003, 0.02));
      mutated.weld_quality = upgradeWeld(mutated.weld_quality);
    } else if (strategy === 'weld_quality_path') {
      if (isTarget) {
        mutated.weld_quality = upgradeWeld(mutated.weld_quality);
        mutated.thickness_m = roundNumber(clampNumber(mutated.thickness_m * 1.08, 0.003, 0.02));
      } else if ((index + iteration) % 4 === 0) {
        mutated.thickness_m = roundNumber(clampNumber(mutated.thickness_m * 0.92, 0.003, 0.02));
      }
    } else if (strategy === 'material_substitution' && isTarget) {
      mutated.material = mutated.material === 'Eh36' ? 'Aluminum5083' : strongerMaterial(mutated.material);
      mutated.thickness_m = roundNumber(clampNumber(mutated.thickness_m * 1.12, 0.003, 0.02));
    } else if (strategy === 'lightweight_composite_path') {
      if (isTarget) {
        mutated.material = zone.zone === 'Keel' || zone.zone === 'BilgeStrake' ? 'CfrpEpoxy' : 'GrpEGlass';
        mutated.thickness_m = roundNumber(clampNumber(mutated.thickness_m * 1.18, 0.004, 0.02));
        mutated.weld_quality = upgradeWeld(mutated.weld_quality);
        mutated.seal_quality = 'Marine';
      } else if ((index + iteration) % 3 === 0) {
        mutated.material = cheaperMaterial(mutated.material);
      }
    } else if (strategy === 'cost_cut_from_best') {
      if (!isTarget && (index + iteration) % 2 === 0) {
        mutated.material = cheaperMaterial(mutated.material);
        mutated.thickness_m = roundNumber(clampNumber(mutated.thickness_m * 0.84, 0.003, 0.02));
        mutated.weld_quality = downgradeWeld(mutated.weld_quality);
      }
    }

    return mutated;
  });

  const propulsion = normalizePropulsion(next.propulsion, effectivePropulsionFromResult(result, seed));
  if (strategy === 'fuel_drag_tradeoff') {
    next.propulsion = normalizePropulsion({
      ...propulsion,
      fuel_capacity_kg: propulsion.fuel_capacity_kg * 1.18,
      propulsive_efficiency: Math.min(propulsion.propulsive_efficiency + 0.03, 0.86),
      hull_drag_coeff: propulsion.hull_drag_coeff * 0.9,
      max_power_kw: propulsion.max_power_kw * 0.95,
    }, propulsion);
  } else if (strategy === 'cost_cut_from_best') {
    next.propulsion = normalizePropulsion({
      ...propulsion,
      fuel_capacity_kg: propulsion.fuel_capacity_kg * 0.86,
      max_power_kw: propulsion.max_power_kw * 0.92,
    }, propulsion);
  } else {
    next.propulsion = propulsion;
  }

  return {
    document: next,
    strategy,
    targets: [...targetSet],
  };
}

function strongerRepairMaterial(material, metric) {
  const normalized = String(material ?? '').toLowerCase();
  if (metric === 'corrosion' || metric === 'crack') {
    if (normalized.includes('mild') || normalized.includes('steel') || normalized.includes('eh36')) {
      return 'Aluminum5083';
    }
    if (normalized.includes('grp') || normalized.includes('aluminum')) {
      return 'CfrpEpoxy';
    }
    return material || 'Aluminum5083';
  }

  if (normalized.includes('mild') || normalized.includes('ah36') || normalized.includes('dh36')) {
    return 'Eh36';
  }
  if (normalized.includes('grp') || normalized.includes('aluminum')) {
    return 'CfrpEpoxy';
  }
  return material || 'Eh36';
}

function failureAnalysisFromResult(result) {
  const failure = result?.failure ?? null;
  const detail = failure?.detail ?? {};
  const failedZone = detail.failed_zone ?? null;
  const finalTick = Array.isArray(result?.ticks) ? result.ticks.at(-1) : null;
  const failedZoneTick = failedZone && Array.isArray(finalTick?.zones)
    ? finalTick.zones.find((zone) => zone.zone === failedZone)
    : null;

  return {
    status: result?.status,
    failed_part: detail.failed_zone ?? failure?.mode ?? null,
    failed_metric: detail.failed_metric ?? failure?.mode ?? null,
    failed_value: detail.failed_value ?? null,
    failure_mode: failure?.mode ?? null,
    segment_index: failure?.segment_index ?? null,
    segment_label: failure?.segment_label ?? null,
    distance_completed_nm: failure?.distance_completed_nm ?? result?.result?.distance_completed_nm ?? null,
    completion_pct: failure?.completion_pct ?? result?.result?.distance_completed_pct ?? null,
    elapsed_h: failure?.elapsed_h ?? result?.result?.time_elapsed_h ?? null,
    cause: failure?.why ?? null,
    suggested_fix: failure?.suggested_fix ?? null,
    failed_zone_tick: failedZoneTick,
  };
}

function localRepairAssessment(document, result) {
  const analysis = failureAnalysisFromResult(result);
  const zones = completeZonesFromResult(result, document.zones ?? []);
  const propulsion = effectivePropulsionFromResult(result, document);
  if (analysis.failure_mode === 'Fuel Exhaustion' || analysis.failed_metric === 'fuel') {
    const repairedPropulsion = normalizePropulsion({
      ...propulsion,
      fuel_capacity_kg: Math.min(Math.max(propulsion.fuel_capacity_kg * 1.45, propulsion.fuel_capacity_kg + 500), 8000),
      propulsive_efficiency: Math.min(propulsion.propulsive_efficiency + 0.04, 0.82),
      hull_drag_coeff: Math.max(propulsion.hull_drag_coeff * 0.92, 0.004),
    }, propulsion);
    return {
      assessment: `Propulsion failed by fuel exhaustion: ${analysis.cause ?? 'fuel reserve reached zero before destination'}`,
      failed_part: 'Propulsion',
      failed_metric: 'fuel',
      root_cause: analysis.cause,
      changes: [
        `Propulsion: fuel_capacity_kg ${propulsion.fuel_capacity_kg.toFixed(0)} -> ${repairedPropulsion.fuel_capacity_kg.toFixed(0)}`,
        `Propulsion: propulsive_efficiency ${propulsion.propulsive_efficiency.toFixed(2)} -> ${repairedPropulsion.propulsive_efficiency.toFixed(2)}`,
        `Propulsion: hull_drag_coeff ${propulsion.hull_drag_coeff.toFixed(4)} -> ${repairedPropulsion.hull_drag_coeff.toFixed(4)}`,
      ],
      zones,
      propulsion: repairedPropulsion,
      brief: { ...document, zones, propulsion: repairedPropulsion },
      model_used: 'local-propulsion-repair-fallback',
    };
  }
  const failedKey = normalizeZoneKey(analysis.failed_part);
  const coupledByFailure = {
    Keel: ['Keel', 'BilgeStrake', 'BottomPlating'],
    BowFlare: ['BowFlare', 'BottomPlating'],
    BilgeStrake: ['BilgeStrake', 'Keel', 'BottomPlating'],
    BottomPlating: ['BottomPlating', 'Keel', 'BilgeStrake'],
  };
  const targets = new Set(coupledByFailure[failedKey] ?? (failedKey ? [failedKey] : []));

  const repairedZones = zones.map((zone) => {
    if (!targets.has(zone.zone)) return zone;
    if (analysis.failed_metric === 'fatigue' || analysis.failure_mode === 'Fatigue Failure') {
      return {
        ...zone,
        material: strongerRepairMaterial(zone.material, 'fatigue'),
        thickness_m: Math.min(Math.max(zone.thickness_m * 1.75, 0.008), 0.02),
        weld_quality: 'Premium',
        seal_quality: zone.seal_quality === 'Economy' ? 'Marine' : zone.seal_quality,
      };
    }
    if (analysis.failed_metric === 'corrosion' || analysis.failed_metric === 'crack') {
      return {
        ...zone,
        material: strongerRepairMaterial(zone.material, analysis.failed_metric),
        thickness_m: Math.min(Math.max(zone.thickness_m * 1.5, 0.007), 0.02),
        weld_quality: zone.weld_quality === 'Economy' ? 'Standard' : zone.weld_quality,
        seal_quality: 'Marine',
      };
    }
    return {
      ...zone,
      thickness_m: Math.min(Math.max(zone.thickness_m * 1.25, 0.006), 0.02),
      weld_quality: zone.weld_quality === 'Economy' ? 'Standard' : zone.weld_quality,
      seal_quality: zone.seal_quality === 'Economy' ? 'Marine' : zone.seal_quality,
    };
  });

  return {
    assessment: `${analysis.failed_part ?? 'Component'} failed by ${analysis.failed_metric ?? analysis.failure_mode ?? 'unknown metric'}: ${analysis.cause ?? 'no simulator cause provided'}`,
    failed_part: analysis.failed_part,
    failed_metric: analysis.failed_metric,
    root_cause: analysis.cause,
    changes: repairedZones
      .filter((zone, index) => JSON.stringify(zone) !== JSON.stringify(zones[index]))
      .map((zone) => `${zone.zone}: ${zone.material}, ${(zone.thickness_m * 1000).toFixed(1)}mm, ${zone.weld_quality} weld, ${zone.seal_quality} seal`),
    zones: repairedZones,
    brief: { ...document, zones: repairedZones },
    model_used: 'local-material-repair-fallback',
  };
}

function summarizeResult(result) {
  const finalTick = Array.isArray(result.ticks) ? result.ticks.at(-1) : null;
  const finalZones = Array.isArray(finalTick?.zones) ? finalTick.zones : [];
  const worstZones = [...finalZones]
    .sort((a, b) => (b.fatigue_consumed ?? 0) - (a.fatigue_consumed ?? 0))
    .slice(0, 5)
    .map((zone) => ({
      zone: zone.zone,
      fatigue_pct: Math.round((zone.fatigue_consumed ?? 0) * 1000) / 10,
      corrosion_depth_mm: zone.corrosion_depth_mm,
      crack_half_length_mm: zone.crack_half_length_mm,
      peak_stress_mpa: zone.peak_stress_mpa,
    }));

  return {
    status: result.status,
    failure: result.failure,
    result: result.result,
    worst_zones: worstZones,
  };
}

function resultCostUsd(result) {
  const value = Number(result?.result?.total_config_cost_usd);
  return Number.isFinite(value) ? value : Infinity;
}

function potentialScore(result) {
  const completion = Number(result?.failure?.completion_pct ?? result?.result?.distance_completed_pct ?? 0);
  const cost = resultCostUsd(result);
  const costScore = Number.isFinite(cost) ? Math.max(0, 100 - ((cost - 5000) / 25000) * 100) : 0;
  const singleFixBonus = result?.failure?.detail?.failed_zone ? 12 : 0;
  const survivedBonus = result?.status === 'survived' ? 40 : 0;
  return Math.round((completion * 0.72 + costScore * 0.18 + singleFixBonus + survivedBonus) * 10) / 10;
}

function emptyDesignMemory(scope = 'campaign') {
  return {
    schema_version: 1,
    scope,
    updated_at: null,
    missions: {},
  };
}

function missionMemory(memory, missionId) {
  const key = missionId || 'unknown';
  if (!memory.missions) memory.missions = {};
  if (!memory.missions[key]) {
    memory.missions[key] = {
      runs_seen: 0,
      successes_seen: 0,
      failures_seen: 0,
      best_survivor_cost_usd: null,
      best_survivor_summary: null,
      best_potential_score: null,
      lessons: [],
      component_lessons: {},
      strategy_stats: {},
    };
  }
  return memory.missions[key];
}

function compactZoneConfig(document) {
  return (document?.zones ?? []).map((zone) => ({
    zone: zone.zone,
    material: zone.material,
    thickness_mm: Number.isFinite(Number(zone.thickness_m))
      ? Math.round(Number(zone.thickness_m) * 100000) / 100
      : null,
    weld_quality: zone.weld_quality,
    seal_quality: zone.seal_quality,
  }));
}

function pushBounded(list, item, limit = 18) {
  list.unshift(item);
  const seen = new Set();
  const unique = [];
  for (const entry of list) {
    const signature = JSON.stringify(entry);
    if (seen.has(signature)) continue;
    seen.add(signature);
    unique.push(entry);
    if (unique.length >= limit) break;
  }
  list.length = 0;
  list.push(...unique);
}

function recordDesignMemory(memory, { document, result, assessment, iteration, strategy, potential }) {
  const missionId = document?.id ?? 'params';
  const mission = missionMemory(memory, missionId);
  const cost = resultCostUsd(result);
  const failure = result?.failure ?? null;
  const failedPart = failure?.detail?.failed_zone ?? assessment?.failed_part ?? null;
  const failedMetric = failure?.detail?.failed_metric ?? assessment?.failed_metric ?? failure?.mode ?? null;
  const status = result?.status ?? 'unknown';
  const completion = Number(failure?.completion_pct ?? result?.result?.distance_completed_pct ?? 0);

  memory.updated_at = new Date().toISOString();
  mission.runs_seen += 1;
  if (status === 'survived') mission.successes_seen += 1;
  if (status === 'failed') mission.failures_seen += 1;

  const strategyKey = strategy ?? 'unknown';
  if (!mission.strategy_stats[strategyKey]) {
    mission.strategy_stats[strategyKey] = { runs: 0, successes: 0, best_cost_usd: null, best_potential_score: null };
  }
  const stat = mission.strategy_stats[strategyKey];
  stat.runs += 1;
  if (status === 'survived') stat.successes += 1;
  if (Number.isFinite(cost) && (stat.best_cost_usd === null || cost < stat.best_cost_usd)) {
    stat.best_cost_usd = Math.round(cost);
  }
  if (Number.isFinite(potential) && (stat.best_potential_score === null || potential > stat.best_potential_score)) {
    stat.best_potential_score = potential;
  }

  if (status === 'survived' && Number.isFinite(cost)) {
    if (mission.best_survivor_cost_usd === null || cost < mission.best_survivor_cost_usd) {
      mission.best_survivor_cost_usd = Math.round(cost);
      mission.best_survivor_summary = {
        iteration,
        strategy: strategyKey,
        cost_usd: Math.round(cost),
        propulsion: normalizePropulsion(document.propulsion, DEFAULT_PROPULSION),
        zones: compactZoneConfig(document),
      };
    }
  }

  if (Number.isFinite(potential) && (mission.best_potential_score === null || potential > mission.best_potential_score)) {
    mission.best_potential_score = potential;
  }

  const lesson = {
    iteration,
    status,
    strategy: strategyKey,
    cost_usd: Number.isFinite(cost) ? Math.round(cost) : null,
    completion_pct: Number.isFinite(completion) ? Math.round(completion * 10) / 10 : null,
    failed_part: failedPart,
    failed_metric: failedMetric,
    root_cause: assessment?.root_cause ?? failure?.why ?? null,
    takeaway: status === 'survived'
      ? `Configuration survived at $${Number.isFinite(cost) ? Math.round(cost) : 'unknown'}; use it as a cost ceiling.`
      : `${failedPart ?? 'Unknown component'} failed by ${failedMetric ?? 'unknown mode'} at ${Number.isFinite(completion) ? Math.round(completion) : 0}% completion.`,
  };
  pushBounded(mission.lessons, lesson, 24);

  if (failedPart) {
    if (!mission.component_lessons[failedPart]) {
      mission.component_lessons[failedPart] = [];
    }
    pushBounded(mission.component_lessons[failedPart], {
      iteration,
      status,
      metric: failedMetric,
      strategy: strategyKey,
      completion_pct: lesson.completion_pct,
      root_cause: lesson.root_cause,
      zone_config: compactZoneConfig(document).find((zone) => zone.zone === normalizeZoneKey(failedPart)) ?? null,
    }, 8);
  }
}

function compactDesignMemory(memory, missionId) {
  const mission = memory?.missions?.[missionId] ?? null;
  if (!mission) return null;
  const strategyStats = Object.fromEntries(
    Object.entries(mission.strategy_stats ?? {})
      .sort((a, b) => (b[1].best_potential_score ?? 0) - (a[1].best_potential_score ?? 0))
      .slice(0, 8),
  );
  return {
    runs_seen: mission.runs_seen,
    successes_seen: mission.successes_seen,
    failures_seen: mission.failures_seen,
    best_survivor_cost_usd: mission.best_survivor_cost_usd,
    best_survivor_summary: mission.best_survivor_summary,
    best_potential_score: mission.best_potential_score,
    lessons: (mission.lessons ?? []).slice(0, 10),
    component_lessons: mission.component_lessons ?? {},
    strategy_stats: strategyStats,
  };
}

function compactHistory(history) {
  return history.slice(-8).map((entry) => ({
    iteration: entry.iteration,
    status: entry.status,
    cost_usd: entry.total_config_cost_usd,
    failure_mode: entry.failure?.mode ?? null,
    failed_part: entry.failure?.detail?.failed_zone ?? null,
    failed_metric: entry.failure?.detail?.failed_metric ?? null,
    completion_pct: entry.failure?.completion_pct ?? entry.result?.distance_completed_pct ?? null,
    strategy: entry.strategy ?? null,
  }));
}

function compactAllowedParameters() {
  return {
    zone_names: HULL_ZONE_KEYS,
    materials: MATERIALS,
    weld_quality: WELD_QUALITIES,
    seal_quality: SEAL_QUALITIES,
    thickness_m: { min: 0.003, max: 0.020 },
    propulsion: {
      max_power_kw: { min: 1 },
      fuel_capacity_kg: { min: 1, cost_usd_per_kg: 1.15 },
      sfc_g_per_kwh: { min: 1 },
      propulsive_efficiency: { min: 0.1, max: 1.0 },
      hull_drag_coeff: { min: 0.001 },
    },
  };
}

function missionContext(document, mode) {
  if (mode !== 'brief') return null;
  return {
    id: document.id,
    name: document.name,
    distance_nm: document.distance_nm,
    origin: document.origin?.name,
    waypoints: Array.isArray(document.waypoints) ? document.waypoints.map((point) => point.name) : [],
    destination: document.destination?.name,
    primary_stressor: document.primary_stressor,
    failure_modes_under_test: document.failure_modes_under_test ?? [],
    environmental_profile: document.environmental_profile,
  };
}

function nextDocumentFromAssessment(assessment, currentDocument, mode, result = null) {
  if (mode === 'brief') {
    const nextBrief = assessment.brief && typeof assessment.brief === 'object'
      ? assessment.brief
      : assessment.params && typeof assessment.params === 'object'
        ? assessment.params
        : { ...currentDocument };

    if (Array.isArray(assessment.zones)) {
      nextBrief.zones = assessment.zones;
    }
    if (assessment.propulsion && typeof assessment.propulsion === 'object') {
      nextBrief.propulsion = assessment.propulsion;
    }
    if (!Array.isArray(nextBrief.zones)) {
      throw new Error('Gemini assessment did not include zones for the repaired material configuration');
    }
    const completeZones = completeZonesFromResult(result, nextBrief.zones);
    const propulsion = normalizePropulsion(nextBrief.propulsion, effectivePropulsionFromResult(result, currentDocument));
    return {
      ...currentDocument,
      ...nextBrief,
      id: currentDocument.id,
      name: currentDocument.name,
      origin: currentDocument.origin,
      waypoints: currentDocument.waypoints ?? [],
      destination: currentDocument.destination,
      distance_nm: currentDocument.distance_nm,
      primary_stressor: currentDocument.primary_stressor,
      failure_modes_under_test: currentDocument.failure_modes_under_test ?? [],
      environmental_profile: currentDocument.environmental_profile,
      zones: completeZones,
      propulsion,
    };
  }

  if (!assessment.params || typeof assessment.params !== 'object') {
    throw new Error('Gemini assessment did not include params object');
  }
  return assessment.params;
}

async function callGemini({ apiKey, model, document, mode, result, iteration, maxIterations, searchState = {} }) {
  const endpoint = `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent?key=${encodeURIComponent(apiKey)}`;
  const isBriefMode = mode === 'brief';
  const failureAnalysis = failureAnalysisFromResult(result);
  const currentZones = completeZonesFromResult(result, document.zones ?? []);
  const currentPropulsion = effectivePropulsionFromResult(result, document);
  const allowedParameters = compactAllowedParameters();
  const succeeded = result?.status === 'survived';
  const prompt = [
    'You are controlling a Rust naval simulation engine.',
    succeeded
      ? 'The latest simulation reached SUCCESS. Your job is now cost optimization: produce a cheaper candidate configuration that is still likely to survive the same mission.'
      : 'Given the input JSON and latest simulation result, diagnose the failure exactly, repair the material configuration, and produce the next run input.',
    isBriefMode
      ? 'Return ONLY a JSON object with this exact shape:'
      : 'Return ONLY a JSON object with this exact shape:',
    isBriefMode
      ? '{ "assessment": "exact diagnosis: failed part, failure cause, physical reason", "failed_part": "component name", "failed_metric": "fatigue|corrosion|crack|fuel|stability|seal|temperature", "root_cause": "specific physical cause", "changes": ["configuration change"], "zones": [ ...complete 9-zone material config... ], "propulsion": { "max_power_kw": number, "fuel_capacity_kg": number, "sfc_g_per_kwh": number, "propulsive_efficiency": number, "hull_drag_coeff": number } }'
      : '{ "assessment": "short diagnosis", "changes": ["short change"], "params": { ...complete next simulate-params JSON... } }',
    'Rules:',
    isBriefMode
      ? '- Do not return route, mission, or environmental fields. The runner preserves those. Return only diagnosis, changes, zones, and propulsion.'
      : '- Keep the same JSON schema as the input params.',
    isBriefMode
      ? '- Preserve id, name, origin, waypoints, destination, distance_nm, primary_stressor, failure_modes_under_test, and environmental_profile exactly.'
      : '- Do not remove route, hull, propulsion, construction, or conditions.',
    isBriefMode
      ? '- Return zones as a complete array of exactly 9 zone objects, one for every valid zone name: Keel, BilgeStrake, BottomPlating, SidePlating, BowFlare, SternPlate, TransomFrame, WeatherDeck, BulkheadFrame.'
      : '- Prefer targeted changes: material, thickness_m, weld_quality, seal_quality, propulsion fuel/drag, or route/conditions only when justified.',
    succeeded && isBriefMode
      ? '- Because the current run reached SUCCESS, search for the cheapest viable parameter configuration: reduce thickness, downgrade weld_quality, downgrade seal_quality, reduce fuel_capacity_kg, reduce max_power_kw, or choose cheaper materials where the latest margins suggest headroom.'
      : isBriefMode
        ? '- Make targeted material configuration changes to the failed component and directly coupled components. Keep unrelated zones unchanged unless the failure analysis justifies changing them.'
        : '- Prefer targeted changes: material, thickness_m, weld_quality, seal_quality, propulsion fuel/drag, or route/conditions only when justified.',
    succeeded
      ? '- Do not stop just because this run reached SUCCESS. Return a new cheaper or meaningfully different candidate unless every allowed cheaper or higher-potential branch is clearly unsafe or impossible.'
      : '- Repair enough to address the exact failed mode, but do not overbuild unrelated components.',
    succeeded
      ? '- Cost search step limit: change at most three hull zones plus propulsion in this candidate.'
      : '- Failure repair step limit: change at most two hull zones plus propulsion in this candidate. Do not globally upgrade the whole vessel in one response.',
    '- Never set every zone to maximum thickness or Premium weld in one iteration. The runner is intentionally exploring many combinations over multiple iterations.',
    isBriefMode
      ? '- For fuel exhaustion, change propulsion fields instead of route: fuel_capacity_kg, propulsive_efficiency, hull_drag_coeff, and only reduce material mass if structurally justified.'
      : '- For fuel exhaustion, prefer propulsion fuel_capacity_kg, propulsive_efficiency, or hull_drag_coeff before route changes.',
    '- Valid material names are exactly the values in ALLOWED_PARAMETERS_JSON.materials. EH40/ultra-high-strength steel is not allowed; EH36 is the only high-strength steel upgrade.',
    '- Valid weld_quality values are Economy, Standard, Premium. Valid seal_quality values are Economy, Marine.',
    isBriefMode
      ? '- If the current result reached SUCCESS, keep mission route/environment unchanged but make the configuration cheaper for the next trial.'
      : '- If the current result reached SUCCESS, keep route/conditions unchanged but make parameters cheaper for the next trial.',
    '- Avoid unrealistic values: thickness_m should usually stay between 0.003 and 0.020.',
    '- For fatigue failures, prioritize weld_quality, thickness_m, and stronger material in the failed zone only; do not upgrade unrelated zones.',
    '- For corrosion/crack failures, prioritize corrosion-resistant/cold-capable material, thickness_m, weld_quality, and seal_quality in the failed zone only.',
    '- Increased fuel_capacity_kg increases total configuration cost through fuel capacity cost.',
    '- Objective order: survive the full voyage first, then minimize total_config_cost_usd as much as possible.',
    '- Explore multiple combinations over iterations. Each response should be the single next best candidate to test.',
    '- If RECENT_SEARCH_HISTORY_JSON shows stagnation, try a different design family instead of tiny edits: weld-quality-first, material-substitution-first, lightweight-composite, fuel/drag tradeoff, or targeted reinforcement only on failing zones.',
    '- Compare against BEST_SURVIVOR_JSON. If the latest run is worse than the best survivor, branch from the best survivor unless the latest branch has obvious potential.',
    '- Compare against BEST_POTENTIAL_JSON too. If a failed candidate completed much more distance at lower cost with one fixable failure, explore that branch before abandoning it.',
    '- A candidate has potential if it fails late with lower cost, fails in only one fixable component, or exposes a cheaper material/weld/fuel pattern that can be repaired locally.',
    '- Use DESIGN_MEMORY_JSON as continuous learned experience from previous iterations/campaigns. Prefer patterns that worked, avoid patterns that repeatedly failed, but override memory when the latest physics result contradicts it.',
    '- Obey ALLOWED_PARAMETERS_JSON exactly for field names, enum values, zone names, and bounds.',
    `Iteration ${iteration} of ${maxIterations}.`,
    '',
    'ALLOWED_PARAMETERS_JSON:',
    JSON.stringify(allowedParameters, null, 2),
    '',
    ...(isBriefMode
      ? [
        'MISSION_CONTEXT_JSON:',
        JSON.stringify(missionContext(document, mode), null, 2),
        '',
      ]
      : [
        'CURRENT_PARAMS_JSON:',
        JSON.stringify(document, null, 2),
        '',
      ]),
    'CURRENT_COMPLETE_MATERIAL_ZONES_JSON:',
    JSON.stringify(currentZones, null, 2),
    '',
    'CURRENT_PROPULSION_JSON:',
    JSON.stringify(currentPropulsion, null, 2),
    '',
    'BEST_SURVIVOR_JSON:',
    JSON.stringify(searchState.bestSurvivor ?? null, null, 2),
    '',
    'BEST_POTENTIAL_JSON:',
    JSON.stringify(searchState.bestPotential ?? null, null, 2),
    '',
    'RECENT_SEARCH_HISTORY_JSON:',
    JSON.stringify(compactHistory(searchState.history ?? []), null, 2),
    '',
    'DESIGN_MEMORY_JSON:',
    JSON.stringify(searchState.designMemory ?? null, null, 2),
    '',
    'SEARCH_DIRECTIVE:',
    searchState.directive ?? 'balance repair and cost optimization',
    '',
    'STRUCTURED_FAILURE_ANALYSIS_JSON:',
    JSON.stringify(failureAnalysis, null, 2),
    '',
    'LATEST_RESULT_SUMMARY_JSON:',
    JSON.stringify(summarizeResult(result), null, 2),
  ].join('\n');

  console.error(`[gemini] attempt model=${model} iteration=${iteration}/${maxIterations}`);
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      contents: [{ role: 'user', parts: [{ text: prompt }] }],
      generationConfig: {
        responseMimeType: 'application/json',
        temperature: 0.2,
        maxOutputTokens: 4096,
      },
    }),
  });

  const body = await response.text();
  console.error(`[gemini] response model=${model} status=${response.status} ok=${response.ok}`);
  if (!response.ok) {
    console.error(`[gemini] error body model=${model}: ${body}`);
    throw new Error(`Gemini API ${response.status}: ${body}`);
  }

  const parsed = JSON.parse(body);
  const text = parsed.candidates?.[0]?.content?.parts?.map((part) => part.text || '').join('\n') || '';
  console.error(`[gemini] success model=${model} text_preview=${JSON.stringify(text.slice(0, 500))}`);
  return extractJsonObject(text);
}

async function callGeminiWithFallback({ apiKey, models, document, mode, result, iteration, maxIterations, searchState = {} }) {
  const errors = [];
  for (const model of models) {
    try {
      const assessment = await callGemini({
        apiKey,
        model,
        document,
        mode,
        result,
        iteration,
        maxIterations,
        searchState,
      });
      console.error(`[gemini] selected model=${model}`);
      return { assessment, model };
    } catch (error) {
      console.error(`[gemini] failed model=${model}: ${error.message}`);
      errors.push(`${model}: ${error.message}`);
      if (!/Gemini API (404|429)/.test(error.message) && !/RESOURCE_EXHAUSTED/.test(error.message)) {
        throw error;
      }
    }
  }

  throw new Error(`All Gemini model attempts failed:\n${errors.join('\n')}`);
}

async function main() {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    throw new Error('Set GEMINI_API_KEY in the environment. Do not commit API keys to source.');
  }

  const modelCandidates = (process.env.GEMINI_MODEL
    || 'gemini-3.5-flash,gemini-2.5-flash,gemini-1.5-flash')
    .split(',')
    .map((model) => model.trim())
    .filter(Boolean);
  const missionIdArg = argValue('mission-id', null);
  const briefArg = argValue('brief', null);
  const missionBriefFile = missionIdArg ? missionBriefFileById(missionIdArg) : null;
  if (missionIdArg && !missionBriefFile) {
    throw new Error(`Unknown mission id '${missionIdArg}'. Expected one of mission-briefs/*.json id values.`);
  }

  const mode = missionBriefFile || briefArg ? 'brief' : 'params';
  const inputFile = missionBriefFile
    ?? (briefArg ? path.resolve(ROOT, briefArg) : path.resolve(ROOT, argValue('input', DEFAULT_INPUT)));
  const tier = argValue('tier', 'lowest');
  const binary = path.resolve(ROOT, argValue('binary', DEFAULT_BINARY));
  const maxIterations = Number(argValue('max-iterations', String(MAX_ITERATIONS)));
  const runId = argValue('run-id', new Date().toISOString().replace(/[:.]/g, '-'));
  const runDir = path.join(SIM_DIR, runId);
  const campaignMemoryFile = path.join(runDir, 'design_memory.json');

  if (!fs.existsSync(binary)) {
    throw new Error(`Simulation binary not found: ${binary}. Run cargo build --release first.`);
  }

  let document = readJson(inputFile);
  if (hasFlag('clear-simulations')) {
    clearSimulationRuns();
  }

  const manifest = {
    run_id: runId,
    model: modelCandidates[0],
    model_candidates: modelCandidates,
    mode,
    tier: mode === 'brief' ? tier : undefined,
    mission_id: mode === 'brief' ? document.id : undefined,
    mission_name: mode === 'brief' ? document.name : undefined,
    started_at: new Date().toISOString(),
    input_file: path.relative(ROOT, inputFile),
    iterations: [],
    best_survivor: null,
    best_potential: null,
    search: {
      strategy: 'sequential adaptive exploration',
      exploration_strategies: EXPLORATION_STRATEGIES,
    },
    memory: {
      enabled: true,
      type: 'persistent design memory',
      global_file: path.relative(ROOT, GLOBAL_DESIGN_MEMORY_FILE),
      campaign_file: path.relative(ROOT, campaignMemoryFile),
    },
  };

  fs.mkdirSync(runDir, { recursive: true });
  const globalDesignMemory = readJsonIfExists(GLOBAL_DESIGN_MEMORY_FILE, emptyDesignMemory('global'));
  const campaignDesignMemory = readJsonIfExists(campaignMemoryFile, emptyDesignMemory('campaign'));
  globalDesignMemory.scope = 'global';
  campaignDesignMemory.scope = 'campaign';
  let bestSurvivorDocument = null;
  let bestPotentialDocument = cloneJson(document);
  const visitedCandidates = new Set([candidateSignature(document, mode)]);

  for (let i = 1; i <= maxIterations; i += 1) {
    let stopAfterIteration = false;
    let iterationStrategy = 'gemini';
    const iterationId = `iteration-${String(i).padStart(2, '0')}`;
    const iterationDir = path.join(runDir, iterationId);
    const paramsFile = path.join(iterationDir, 'params.json');
    const resultFile = path.join(iterationDir, 'result.json');
    const assessmentFile = path.join(iterationDir, 'assessment.json');
    const runDocument = cloneJson(document);

    writeJson(paramsFile, runDocument);
    const rust = mode === 'brief'
      ? runRustBrief(binary, paramsFile, resultFile, tier)
      : runRustSimulation(binary, paramsFile, resultFile);
    const result = readJson(resultFile);
    const costUsd = resultCostUsd(result);
    const candidatePotential = potentialScore(result);

    let assessment = {
      assessment: result.status === 'survived'
        ? 'Simulation reached SUCCESS. Continuing search for a cheaper viable configuration.'
        : 'Simulation failed before Gemini assessment completed.',
      changes: [],
      [mode === 'brief' ? 'brief' : 'params']: document,
    };

    if (result.status === 'survived') {
      const candidateBest = {
        id: `${runId}/${iterationId}`,
        run_id: runId,
        iteration: i,
        total_config_cost_usd: Number.isFinite(costUsd) ? costUsd : null,
        result_file: path.relative(ROOT, resultFile),
        params_file: path.relative(ROOT, paramsFile),
      };
      if (
        !manifest.best_survivor
        || (
          Number.isFinite(costUsd)
          && costUsd < Number(manifest.best_survivor.total_config_cost_usd ?? Infinity)
        )
      ) {
        manifest.best_survivor = candidateBest;
        bestSurvivorDocument = cloneJson(runDocument);
      }
    }
    if (
      !manifest.best_potential
      || candidatePotential > Number(manifest.best_potential.score ?? -Infinity)
      || (
        candidatePotential === Number(manifest.best_potential.score ?? -Infinity)
        && Number.isFinite(costUsd)
        && costUsd < Number(manifest.best_potential.total_config_cost_usd ?? Infinity)
      )
    ) {
      manifest.best_potential = {
        id: `${runId}/${iterationId}`,
        run_id: runId,
        iteration: i,
        score: candidatePotential,
        status: result.status,
        failure: result.failure ?? null,
        total_config_cost_usd: Number.isFinite(costUsd) ? costUsd : null,
        result_file: path.relative(ROOT, resultFile),
        params_file: path.relative(ROOT, paramsFile),
      };
      bestPotentialDocument = cloneJson(runDocument);
    }

    if (i < maxIterations) {
      try {
        const bestSurvivorContext = manifest.best_survivor
          ? {
            ...manifest.best_survivor,
            zones: bestSurvivorDocument?.zones ?? null,
            propulsion: bestSurvivorDocument?.propulsion ?? null,
          }
          : null;
        const bestPotentialContext = manifest.best_potential
          ? {
            ...manifest.best_potential,
            zones: bestPotentialDocument?.zones ?? null,
            propulsion: bestPotentialDocument?.propulsion ?? null,
          }
          : null;
        const gemini = await callGeminiWithFallback({
          apiKey,
          models: modelCandidates,
          document,
          mode,
          result,
          iteration: i,
          maxIterations,
          searchState: {
            bestSurvivor: bestSurvivorContext,
            bestPotential: bestPotentialContext,
            history: manifest.iterations,
            designMemory: {
              global: compactDesignMemory(globalDesignMemory, document.id ?? 'params'),
              campaign: compactDesignMemory(campaignDesignMemory, document.id ?? 'params'),
            },
            directive: result.status === 'survived'
              ? 'exploit the best survivor for lower cost, but branch into a different design family if recent trials are stuck'
              : 'repair the failure locally, or branch if this failure suggests a more promising architecture',
          },
        });
        assessment = gemini.assessment;
        assessment.model_used = gemini.model;
        manifest.model = gemini.model;
        let nextDocument = nextDocumentFromAssessment(assessment, document, mode, result);
        let nextSignature = candidateSignature(nextDocument, mode);
        const shouldForceExplore = result.status === 'survived'
          && (
            nextSignature === candidateSignature(document, mode)
            || visitedCandidates.has(nextSignature)
            || i % 3 === 0
          );

        if (shouldForceExplore) {
          const exploration = mutateExploratoryDocument(document, result, bestSurvivorDocument, mode, i);
          if (exploration) {
            nextDocument = exploration.document;
            nextSignature = candidateSignature(nextDocument, mode);
            iterationStrategy = `explore:${exploration.strategy}`;
            assessment.search_strategy = iterationStrategy;
            assessment.exploration_targets = exploration.targets;
            assessment.assessment = `${assessment.assessment ?? 'Gemini candidate reviewed.'} Branching into ${exploration.strategy} to test another design path.`;
          }
        }

        if (visitedCandidates.has(nextSignature)) {
          const exploration = mutateExploratoryDocument(document, result, bestSurvivorDocument, mode, i + 1);
          if (exploration) {
            nextDocument = exploration.document;
            nextSignature = candidateSignature(nextDocument, mode);
            iterationStrategy = `explore:${exploration.strategy}`;
            assessment.search_strategy = iterationStrategy;
            assessment.exploration_targets = exploration.targets;
            assessment.assessment = `${assessment.assessment ?? 'Duplicate candidate avoided.'} Replaced duplicate with ${exploration.strategy}.`;
          }
        }

        visitedCandidates.add(nextSignature);
        document = nextDocument;
        if (mode === 'brief') {
          assessment.repaired_zones = document.zones;
        }
      } catch (error) {
        if (mode === 'brief' && result.status === 'survived') {
          const exploration = mutateExploratoryDocument(document, result, bestSurvivorDocument, mode, i);
          if (exploration) {
            document = exploration.document;
            visitedCandidates.add(candidateSignature(document, mode));
            iterationStrategy = `explore:${exploration.strategy}`;
            assessment = {
              assessment: `Gemini could not produce the next candidate (${error.message}). Continuing with ${exploration.strategy}.`,
              changes: [`Local exploratory branch: ${exploration.strategy}`],
              zones: document.zones,
              propulsion: document.propulsion,
              brief: document,
              model_used: 'local-exploration-fallback',
              search_strategy: iterationStrategy,
              exploration_targets: exploration.targets,
              error: error.stack || error.message,
            };
          } else {
            assessment = {
              assessment: `Simulation reached SUCCESS, but no exploratory candidate could be produced: ${error.message}`,
              changes: [],
              brief: document,
              error: error.stack || error.message,
            };
            stopAfterIteration = true;
          }
        } else if (mode === 'brief') {
          assessment = localRepairAssessment(document, result);
          assessment.gemini_error = error.stack || error.message;
          document = nextDocumentFromAssessment(assessment, document, mode, result);
          visitedCandidates.add(candidateSignature(document, mode));
          iterationStrategy = assessment.model_used ?? 'local-repair';
          assessment.repaired_zones = document.zones;
        } else {
          assessment = {
            assessment: `Gemini assessment failed: ${error.message}`,
            changes: [],
            params: document,
            error: error.stack || error.message,
          };
          stopAfterIteration = true;
        }
      }
    }

    const memoryPayload = {
      document: runDocument,
      result,
      assessment,
      iteration: i,
      strategy: assessment.search_strategy ?? iterationStrategy,
      potential: candidatePotential,
    };
    recordDesignMemory(globalDesignMemory, memoryPayload);
    recordDesignMemory(campaignDesignMemory, memoryPayload);
    writeJson(GLOBAL_DESIGN_MEMORY_FILE, globalDesignMemory);
    writeJson(campaignMemoryFile, campaignDesignMemory);

    writeJson(assessmentFile, assessment);

    manifest.iterations.push({
      id: `${runId}/${iterationId}`,
      run_id: runId,
      iteration: i,
      status: result.status,
      failure: result.failure ?? null,
      result: result.result ?? null,
      total_config_cost_usd: Number.isFinite(costUsd) ? costUsd : null,
      strategy: assessment.search_strategy ?? iterationStrategy,
      params_file: path.relative(ROOT, paramsFile),
      result_file: path.relative(ROOT, resultFile),
      assessment_file: path.relative(ROOT, assessmentFile),
      rust_stdout: rust.stdout,
      rust_stderr: rust.stderr,
    });
    writeJson(path.join(runDir, 'manifest.json'), manifest);

    if (stopAfterIteration) break;
  }

  manifest.completed_at = new Date().toISOString();
  writeJson(path.join(runDir, 'manifest.json'), manifest);
  console.log(JSON.stringify(manifest, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
