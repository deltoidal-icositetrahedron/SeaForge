import express from 'express';
import { spawnSync } from 'child_process';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = 3001;

const BINARY = path.resolve(__dirname, '..', 'target', 'release', 'seaforge_v2');
const RESULT_FILE = path.resolve(__dirname, '..', 'result.json');

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
  const configFile = path.join(os.tmpdir(), `seaforge_config_${ts}.json`);
  const routeFile = path.join(os.tmpdir(), `seaforge_route_${ts}.json`);
  const outFile = path.join(os.tmpdir(), `seaforge_out_${ts}.json`);

  try {
    fs.writeFileSync(configFile, JSON.stringify(req.body.config, null, 2));
    fs.writeFileSync(routeFile, JSON.stringify(req.body.route, null, 2));

    const result = spawnSync(BINARY, ['simulate', configFile, routeFile, outFile], {
      encoding: 'utf8',
      timeout: 60000,
    });

    fs.unlinkSync(configFile);
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
    try { fs.unlinkSync(configFile); } catch (_) {}
    try { fs.unlinkSync(routeFile); } catch (_) {}
    try { fs.unlinkSync(outFile); } catch (_) {}
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
