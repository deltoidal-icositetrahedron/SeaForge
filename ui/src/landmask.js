// Shared land/water mask built by rasterizing the SAME coastline geojson the
// globe displays (ne_110m), so validation matches exactly what the user sees.
// Used to block routes whose nodes sit on land or whose legs cross land.

const LAND_GEOJSON_URL = '/ne_110m_admin_0_countries.geojson';
const W = 1440; // 0.25deg longitude resolution
const H = 720;  // 0.25deg latitude resolution

let maskPromise = null;

function drawRing(ctx, ring, xOffset) {
  let prevLon = null;
  let wrap = xOffset;
  let started = false;
  for (const coord of ring) {
    let lon = coord?.[0];
    const lat = coord?.[1];
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    if (prevLon !== null) {
      while (lon - prevLon > 180) { lon -= 360; wrap += W; }
      while (lon - prevLon < -180) { lon += 360; wrap -= W; }
    }
    const x = ((lon + 180) / 360) * W + wrap;
    const y = ((90 - lat) / 180) * H;
    if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
    prevLon = lon;
  }
  if (started) ctx.closePath();
}

async function build() {
  const geo = await fetch(LAND_GEOJSON_URL).then((r) => {
    if (!r.ok) throw new Error(`land geojson HTTP ${r.status}`);
    return r.json();
  });

  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.fillStyle = '#ffffff';

  const polys = [];
  geo?.features?.forEach((f) => {
    const g = f.geometry;
    if (!g) return;
    if (g.type === 'Polygon') polys.push(g.coordinates);
    else if (g.type === 'MultiPolygon') g.coordinates.forEach((rings) => polys.push(rings));
  });
  polys.forEach((rings) => {
    [-W, 0, W].forEach((xOffset) => {
      ctx.beginPath();
      rings.forEach((ring) => drawRing(ctx, ring, xOffset));
      ctx.fill('evenodd');
    });
  });

  // Keep only the alpha channel as a compact land bitmap.
  const rgba = ctx.getImageData(0, 0, W, H).data;
  const land = new Uint8Array(W * H);
  for (let i = 0; i < land.length; i += 1) land[i] = rgba[i * 4 + 3] > 10 ? 1 : 0;

  const isLand = (lon, lat) => {
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) return false;
    let x = Math.floor(((lon + 180) / 360) * W);
    let y = Math.floor(((90 - lat) / 180) * H);
    x = ((x % W) + W) % W;
    y = Math.max(0, Math.min(H - 1, y));
    return land[y * W + x] === 1;
  };

  return { isLand };
}

// Cached singleton — fetched/rasterized once per session.
export function getLandMask() {
  if (!maskPromise) maskPromise = build();
  return maskPromise;
}

// Does the great-circle leg between two {lat,lon} points pass over land?
// Samples interior points along the slerp (endpoints are validated separately).
export function legCrossesLand(mask, a, b) {
  const toUnit = (p) => {
    const lat = (p.lat * Math.PI) / 180;
    const lon = (p.lon * Math.PI) / 180;
    const c = Math.cos(lat);
    return [c * Math.sin(lon), Math.sin(lat), c * Math.cos(lon)];
  };
  const ua = toUnit(a);
  const ub = toUnit(b);
  const dot = Math.max(-1, Math.min(1, ua[0] * ub[0] + ua[1] * ub[1] + ua[2] * ub[2]));
  const omega = Math.acos(dot);
  const angleDeg = (omega * 180) / Math.PI;
  const steps = Math.max(10, Math.round(angleDeg * 1.5));
  const sin = Math.sin(omega);

  for (let i = 1; i < steps; i += 1) {
    const t = i / steps;
    let v;
    if (omega < 1e-6) {
      v = [ua[0], ua[1], ua[2]];
    } else {
      const w0 = Math.sin((1 - t) * omega) / sin;
      const w1 = Math.sin(t * omega) / sin;
      v = [ua[0] * w0 + ub[0] * w1, ua[1] * w0 + ub[1] * w1, ua[2] * w0 + ub[2] * w1];
    }
    const norm = Math.hypot(v[0], v[1], v[2]) || 1;
    const lat = (Math.asin(Math.max(-1, Math.min(1, v[1] / norm))) * 180) / Math.PI;
    const lon = (Math.atan2(v[0] / norm, v[2] / norm) * 180) / Math.PI;
    if (mask.isLand(lon, lat)) return true;
  }
  return false;
}
