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

async function callGemini({ apiKey, model, document, mode, result, iteration, maxIterations }) {
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
      ? '- Do not stop just because this run reached SUCCESS. Return a new cheaper candidate unless every allowed cheaper combination is clearly unsafe or impossible.'
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

async function callGeminiWithFallback({ apiKey, models, document, mode, result, iteration, maxIterations }) {
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
  };

  fs.mkdirSync(runDir, { recursive: true });

  for (let i = 1; i <= maxIterations; i += 1) {
    let stopAfterIteration = false;
    const iterationId = `iteration-${String(i).padStart(2, '0')}`;
    const iterationDir = path.join(runDir, iterationId);
    const paramsFile = path.join(iterationDir, 'params.json');
    const resultFile = path.join(iterationDir, 'result.json');
    const assessmentFile = path.join(iterationDir, 'assessment.json');

    writeJson(paramsFile, document);
    const rust = mode === 'brief'
      ? runRustBrief(binary, paramsFile, resultFile, tier)
      : runRustSimulation(binary, paramsFile, resultFile);
    const result = readJson(resultFile);
    const costUsd = resultCostUsd(result);

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
      }
    }

    if (i < maxIterations) {
      try {
        const gemini = await callGeminiWithFallback({
          apiKey,
          models: modelCandidates,
          document,
          mode,
          result,
          iteration: i,
          maxIterations,
        });
        assessment = gemini.assessment;
        assessment.model_used = gemini.model;
        manifest.model = gemini.model;
        const nextDocument = nextDocumentFromAssessment(assessment, document, mode, result);
        if (result.status === 'survived' && JSON.stringify(nextDocument) === JSON.stringify(document)) {
          assessment.assessment = `${assessment.assessment ?? 'Simulation reached SUCCESS.'} No cheaper candidate was returned; stopping optimization.`;
          stopAfterIteration = true;
        }
        document = nextDocument;
        if (mode === 'brief') {
          assessment.repaired_zones = document.zones;
        }
      } catch (error) {
        if (mode === 'brief' && result.status === 'survived') {
          assessment = {
            assessment: `Simulation reached SUCCESS, but Gemini could not produce a cheaper candidate: ${error.message}`,
            changes: [],
            brief: document,
            error: error.stack || error.message,
          };
          stopAfterIteration = true;
        } else if (mode === 'brief') {
          assessment = localRepairAssessment(document, result);
          assessment.gemini_error = error.stack || error.message;
          document = nextDocumentFromAssessment(assessment, document, mode, result);
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

    writeJson(assessmentFile, assessment);

    manifest.iterations.push({
      id: `${runId}/${iterationId}`,
      run_id: runId,
      iteration: i,
      status: result.status,
      failure: result.failure ?? null,
      result: result.result ?? null,
      total_config_cost_usd: Number.isFinite(costUsd) ? costUsd : null,
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
