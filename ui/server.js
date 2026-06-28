import express from 'express';
import { spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';
import { MAX_ITERATIONS } from '../gemini_runner/config.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ROOT_DIR = path.resolve(__dirname, '..');

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

loadEnvFile(path.join(ROOT_DIR, '.env'));

const app = express();
const PORT = Number(process.env.PORT || 3001);

const BINARY = path.resolve(ROOT_DIR, 'target', 'release', 'seaforge_v2');
const RESULT_FILE = path.resolve(ROOT_DIR, 'result.json');
const SIMULATIONS_DIR = path.resolve(ROOT_DIR, 'simulations');
const GEMINI_RUNNER = path.resolve(ROOT_DIR, 'gemini_runner', 'run_gemini_simulations.js');
const MISSION_BRIEFS_DIR = path.resolve(ROOT_DIR, 'mission-briefs');

function safeUnlink(file) {
  try {
    if (file) fs.unlinkSync(file);
  } catch (_) {}
}

function safeReadJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (_) {
    return null;
  }
}

function clearSimulationRuns() {
  fs.mkdirSync(SIMULATIONS_DIR, { recursive: true });
  for (const entry of fs.readdirSync(SIMULATIONS_DIR)) {
    if (entry === '.gitkeep') continue;
    fs.rmSync(path.join(SIMULATIONS_DIR, entry), { recursive: true, force: true });
  }
}

function missionBriefById(missionId) {
  if (!missionId || !/^[A-Za-z0-9_-]+$/.test(missionId)) return null;
  if (!fs.existsSync(MISSION_BRIEFS_DIR)) return null;

  for (const file of fs.readdirSync(MISSION_BRIEFS_DIR)) {
    if (!file.endsWith('.json')) continue;
    const brief = safeReadJson(path.join(MISSION_BRIEFS_DIR, file));
    if (brief?.id === missionId) return brief;
  }

  return null;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function evaluateSimulation(result) {
  const voyagePct = clamp(Number(result?.result?.distance_completed_pct ?? 0), 0, 100);
  const elapsedH = Number(result?.failure?.elapsed_h ?? result?.result?.time_elapsed_h ?? 0);
  const routeSegments = Array.isArray(result?.voyage?.route_segments) ? result.voyage.route_segments : [];
  const distanceNm = Number(result?.result?.distance_completed_nm ?? 0);
  const avgSpeedKts = elapsedH > 0 && distanceNm > 0 ? distanceNm / elapsedH : 58;
  const totalDistanceNm = voyagePct > 0 && distanceNm > 0 ? distanceNm / (voyagePct / 100) : distanceNm;
  const expectedH = totalDistanceNm > 0 ? totalDistanceNm / Math.max(avgSpeedKts, 1) : routeSegments.length * 8;
  const timeScore = result?.status === 'survived'
    ? 100
    : clamp((elapsedH / Math.max(expectedH, 1)) * 100, 0, 100);

  const failedPart = result?.failure?.detail?.failed_zone ?? '';
  const componentPenalty = {
    Keel: 34,
    'Bottom Plating': 30,
    'Bilge Strake': 28,
    'Bow Flare': 24,
    'Side Plating': 20,
    'Stern Plate': 18,
    'Weather Deck': 16,
    'Transom Frame': 14,
    'Bulkhead Frame': 12,
    Propulsion: 22,
  }[failedPart] ?? (result?.status === 'survived' ? 0 : 18);
  const componentScore = clamp(100 - componentPenalty, 0, 100);

  const lastTick = Array.isArray(result?.ticks) ? result.ticks.at(-1) : null;
  const zones = Array.isArray(lastTick?.zones) ? lastTick.zones : [];
  const maxFatigue = Math.max(0, ...zones.map((zone) => Number(zone.fatigue_consumed ?? 0)));
  const maxCrackMm = Math.max(0, ...zones.map((zone) => Number(zone.crack_half_length_mm ?? 0)));
  const maxCorrosionMm = Math.max(0, ...zones.map((zone) => Number(zone.corrosion_depth_mm ?? 0)));
  const gmM = Number(lastTick?.gm_m ?? result?.result?.final_gm_m ?? 0);
  const fuelRemainingKg = Number(lastTick?.fuel_remaining_kg ?? result?.result?.fuel_remaining_kg ?? 0);
  const severityPenalty = Math.min(70, maxFatigue * 42)
    + Math.min(15, maxCrackMm * 0.6)
    + Math.min(10, maxCorrosionMm * 8)
    + (gmM > 0 ? Math.min(12, Math.max(0, 0.8 - gmM) * 15) : 0)
    + (fuelRemainingKg > 0 ? Math.min(10, Math.max(0, 250 - fuelRemainingKg) / 25) : 10);
  const severityScore = clamp(100 - severityPenalty, 0, 100);

  const costUsd = Number(result?.result?.total_config_cost_usd ?? 0);
  const costScore = clamp(100 - ((costUsd - 5000) / 15000) * 100, 0, 100);

  const score = clamp(
    voyagePct * 0.34
      + timeScore * 0.20
      + componentScore * 0.14
      + severityScore * 0.20
      + costScore * 0.12,
    0,
    100,
  );

  return {
    score_pct: Math.round(score),
    distance_pct: Math.round(voyagePct),
    time_to_failure_h: Number.isFinite(elapsedH) ? Math.round(elapsedH * 10) / 10 : null,
    first_failed_component: failedPart || null,
    severity_score: Math.round(severityScore),
    material_cost_usd: Number.isFinite(costUsd) ? Math.round(costUsd) : null,
  };
}

function simulationEntries() {
  if (!fs.existsSync(SIMULATIONS_DIR)) return [];
  const entries = [];

  for (const runId of fs.readdirSync(SIMULATIONS_DIR)) {
    const runDir = path.join(SIMULATIONS_DIR, runId);
    if (!fs.statSync(runDir).isDirectory()) continue;
    const manifest = safeReadJson(path.join(runDir, 'manifest.json'));

    for (const name of fs.readdirSync(runDir)) {
      if (!name.startsWith('iteration-')) continue;
      const iterationDir = path.join(runDir, name);
      if (!fs.statSync(iterationDir).isDirectory()) continue;
      const result = safeReadJson(path.join(iterationDir, 'result.json'));
      const assessment = safeReadJson(path.join(iterationDir, 'assessment.json'));
      const params = safeReadJson(path.join(iterationDir, 'params.json'));
      if (!result) continue;

      entries.push({
        id: `${runId}/${name}`,
        run_id: runId,
        iteration: Number(name.replace('iteration-', '')),
        status: result.status,
        failure: result.failure ?? null,
        result: result.result ?? null,
        eval: evaluateSimulation(result),
        assessment: assessment
          ? {
            assessment: assessment.assessment,
            failed_part: assessment.failed_part ?? null,
            failed_metric: assessment.failed_metric ?? null,
            root_cause: assessment.root_cause ?? null,
            model_used: assessment.model_used ?? null,
            changes: assessment.changes ?? [],
          }
          : null,
        params,
        created_at: manifest?.started_at ?? runId,
      });
    }
  }

  return entries.sort((a, b) => b.id.localeCompare(a.id));
}

function runnerErrorPayload(result) {
  const stderr = result.stderr ? result.stderr.toString() : '';
  const stdout = result.stdout ? result.stdout.toString() : '';
  const message = stderr.split('\n').find(Boolean)
    || stdout.split('\n').find(Boolean)
    || 'Gemini simulation runner failed';
  return {
    error: message,
    stderr,
    stdout,
  };
}

// CORS headers
app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

app.use(express.json({ limit: '10mb' }));

// GET /api/health
app.get('/api/health', (req, res) => {
  const exists = fs.existsSync(BINARY);
  res.json({
    status: exists ? 'ok' : 'error',
    binary: BINARY,
    exists,
  });
});

// GET /api/result — read saved result.json from project root
app.get('/api/result', (req, res) => {
  if (!fs.existsSync(RESULT_FILE)) {
    return res.status(404).json({ error: 'result.json not found. Run: npm run sim' });
  }
  try {
    const raw = fs.readFileSync(RESULT_FILE, 'utf8');
    const parsed = JSON.parse(raw);
    res.json(parsed);
  } catch (e) {
    res.status(500).json({ error: `Failed to parse result.json: ${e.message}` });
  }
});

// GET /api/simulations — list all saved Gemini/Rust simulation iterations
app.get('/api/simulations', (_req, res) => {
  res.json({ simulations: simulationEntries() });
});

// GET /api/simulation?id=<run-id/iteration-XX> — load a saved simulation result
app.get('/api/simulation', (req, res) => {
  const id = String(req.query.id ?? '');
  if (!/^[A-Za-z0-9_-]+\/iteration-\d+$/.test(id)) {
    return res.status(400).json({ error: 'GET /api/simulation requires id=<run-id/iteration-XX>' });
  }

  const resultFile = path.join(SIMULATIONS_DIR, id, 'result.json');
  const assessmentFile = path.join(SIMULATIONS_DIR, id, 'assessment.json');
  const paramsFile = path.join(SIMULATIONS_DIR, id, 'params.json');
  const result = safeReadJson(resultFile);
  if (!result) {
    return res.status(404).json({ error: 'simulation result not found' });
  }

  res.json({
    id,
    result,
    assessment: safeReadJson(assessmentFile),
    params: safeReadJson(paramsFile),
  });
});

// POST /api/gemini/run — run Gemini-guided simulation iterations
app.post('/api/gemini/run', (req, res) => {
  try {
    const requestedMissionId = req.body.mission_id ?? req.body.brief?.id ?? null;
    const brief = missionBriefById(String(requestedMissionId ?? ''));
    const tier = req.body.tier ?? 'lowest';
    const maxIterations = Number(req.body.max_iterations ?? MAX_ITERATIONS);
    const runStamp = new Date().toISOString().replace(/[:.]/g, '-');
    const missionId = brief?.id ? String(brief.id).replace(/[^A-Za-z0-9_-]/g, '_') : null;
    const runId = req.body.run_id ?? (missionId ? `${missionId}_${runStamp}` : runStamp);

    if (!process.env.GEMINI_API_KEY) {
      return res.status(400).json({
        error: 'GEMINI_API_KEY is not set on the API server process',
      });
    }

    if (!brief) {
      return res.status(400).json({
        error: `POST /api/gemini/run requires a valid selected mission_id; got ${requestedMissionId ?? 'none'}`,
      });
    }

    clearSimulationRuns();

    const runnerArgs = [
      GEMINI_RUNNER,
      '--clear-simulations',
      `--mission-id=${brief.id}`,
      `--max-iterations=${maxIterations}`,
      `--run-id=${runId}`,
      `--binary=${BINARY}`,
      `--tier=${tier}`,
    ];

    const result = spawnSync(
      process.execPath,
      runnerArgs,
      {
        cwd: path.resolve(__dirname, '..'),
        encoding: 'utf8',
        timeout: 300000,
        env: process.env,
      },
    );

    if (result.error) {
      return res.status(500).json({ error: result.error.message });
    }
    if (result.status !== 0) {
      return res.status(500).json(runnerErrorPayload(result));
    }

    res.json(JSON.parse(result.stdout));
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /api/demo
app.post('/api/demo', (req, res) => {
  const result = spawnSync(BINARY, ['demo'], { encoding: 'utf8', timeout: 30000 });
  if (result.error) {
    return res.status(500).json({ error: result.error.message });
  }
  const stdout = result.stdout ? result.stdout.toString() : '';
  if (!stdout.trim()) {
    const stderr = result.stderr ? result.stderr.toString() : '';
    return res.status(500).json({ error: 'Binary produced no output', stderr });
  }
  try {
    const parsed = JSON.parse(stdout);
    res.json(parsed);
  } catch (e) {
    res.status(500).json({ error: 'Failed to parse binary output', raw: stdout.slice(0, 500) });
  }
});

// POST /api/simulate
app.post('/api/simulate', (req, res) => {
  const ts = Date.now();
  const paramsFile = path.join(os.tmpdir(), `seaforge_params_${ts}.json`);
  const configFile = path.join(os.tmpdir(), `seaforge_config_${ts}.json`);
  const routeFile = path.join(os.tmpdir(), `seaforge_route_${ts}.json`);
  const outFile = path.join(os.tmpdir(), `seaforge_out_${ts}.json`);
  const params = req.body.params ?? (!req.body.config ? req.body : null);

  try {
    let args;

    if (params) {
      fs.writeFileSync(paramsFile, JSON.stringify(params, null, 2));
      args = ['simulate-params', paramsFile, outFile];
    } else {
      if (!req.body.config || !req.body.route) {
        return res.status(400).json({
          error: 'POST /api/simulate requires either { params } or { config, route }',
        });
      }
      fs.writeFileSync(configFile, JSON.stringify(req.body.config, null, 2));
      fs.writeFileSync(routeFile, JSON.stringify(req.body.route, null, 2));
      args = ['simulate', configFile, routeFile, outFile];
    }

    const result = spawnSync(BINARY, args, {
      encoding: 'utf8',
      timeout: 60000,
    });

    safeUnlink(paramsFile);
    safeUnlink(configFile);
    safeUnlink(routeFile);

    if (result.error) {
      return res.status(500).json({ error: result.error.message });
    }
    if (!fs.existsSync(outFile)) {
      const stderr = result.stderr ? result.stderr.toString() : '';
      return res.status(500).json({ error: 'Binary produced no output file', stderr });
    }
    const parsed = JSON.parse(fs.readFileSync(outFile, 'utf8'));
    safeUnlink(outFile);
    res.json(parsed);
  } catch (e) {
    safeUnlink(paramsFile);
    safeUnlink(configFile);
    safeUnlink(routeFile);
    safeUnlink(outFile);
    res.status(500).json({ error: e.message });
  }
});

// POST /api/brief — run the brief command with a mission JSON and optional tier
app.post('/api/brief', (req, res) => {
  const { brief, tier = 'cheapest', zones = null } = req.body;
  if (!brief) {
    return res.status(400).json({ error: 'POST /api/brief requires { brief, tier?, zones? }' });
  }

  const ts = Date.now();
  const briefFile = path.join(os.tmpdir(), `seaforge_brief_${ts}.json`);
  const outFile   = path.join(os.tmpdir(), `seaforge_brief_out_${ts}.json`);

  try {
    const briefPayload = zones ? { ...brief, zones } : brief;
    fs.writeFileSync(briefFile, JSON.stringify(briefPayload, null, 2));

    const result = spawnSync(
      BINARY,
      ['brief', briefFile, outFile, `--tier=${tier}`],
      { encoding: 'utf8', timeout: 60000 },
    );

    safeUnlink(briefFile);

    if (result.error) {
      return res.status(500).json({ error: result.error.message });
    }
    if (!fs.existsSync(outFile)) {
      const stderr = result.stderr ? result.stderr.toString() : '';
      return res.status(500).json({ error: 'Binary produced no output file', stderr });
    }

    const parsed = JSON.parse(fs.readFileSync(outFile, 'utf8'));
    safeUnlink(outFile);
    res.json(parsed);
  } catch (e) {
    safeUnlink(briefFile);
    safeUnlink(outFile);
    res.status(500).json({ error: e.message });
  }
});

// POST /api/optimize
app.post('/api/optimize', (req, res) => {
  const ts = Date.now();
  const searchSpaceFile = path.join(os.tmpdir(), `seaforge_search_${ts}.json`);
  const routeFile = path.join(os.tmpdir(), `seaforge_route_opt_${ts}.json`);
  const outFile = path.join(os.tmpdir(), `seaforge_opt_out_${ts}.json`);

  try {
    fs.writeFileSync(searchSpaceFile, JSON.stringify(req.body.search_space, null, 2));
    fs.writeFileSync(routeFile, JSON.stringify(req.body.route, null, 2));

    const result = spawnSync(BINARY, ['optimize', searchSpaceFile, routeFile, outFile], {
      encoding: 'utf8',
      timeout: 120000,
    });

    fs.unlinkSync(searchSpaceFile);
    fs.unlinkSync(routeFile);

    if (result.error) {
      return res.status(500).json({ error: result.error.message });
    }
    if (!fs.existsSync(outFile)) {
      const stderr = result.stderr ? result.stderr.toString() : '';
      return res.status(500).json({ error: 'Binary produced no output file', stderr });
    }
    const parsed = JSON.parse(fs.readFileSync(outFile, 'utf8'));
    fs.unlinkSync(outFile);
    res.json(parsed);
  } catch (e) {
    try { fs.unlinkSync(searchSpaceFile); } catch (_) {}
    try { fs.unlinkSync(routeFile); } catch (_) {}
    try { fs.unlinkSync(outFile); } catch (_) {}
    res.status(500).json({ error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`SEAFORGE V2 API server running on http://localhost:${PORT}`);
  console.log(`Binary path: ${BINARY}`);
  console.log(`Binary exists: ${fs.existsSync(BINARY)}`);

  const configFile = path.resolve(__dirname, '..', 'examples', 'vessel_config.json');
  const routeFile  = path.resolve(__dirname, '..', 'examples', 'voyage_route.json');
  if (fs.existsSync(BINARY) && fs.existsSync(configFile) && fs.existsSync(routeFile)) {
    console.log('Running initial simulation...');
    const result = spawnSync(BINARY, ['simulate', configFile, routeFile, RESULT_FILE], {
      encoding: 'utf8',
      timeout: 60000,
    });
    if (result.error) {
      console.error('Initial simulation failed:', result.error.message);
    } else {
      console.log('Initial simulation complete → result.json');
    }
  } else {
    console.log('Skipping initial simulation (binary or example files not found)');
  }
});
