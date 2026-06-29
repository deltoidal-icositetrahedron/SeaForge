import React, { useEffect, useMemo, useState } from 'react';
import GlobePicker from './GlobePicker.jsx';
import { getLandMask, legCrossesLand } from '../landmask.js';

const STRESSORS = [
  ['sustained_structural_fatigue', 'Structural fatigue'],
  ['corrosion_crack_cascade', 'Corrosion / crack cascade'],
  ['capsize_stability', 'Capsize / stability'],
  ['ice_accretion_cold_embrittlement', 'Ice / cold embrittlement'],
  ['fuel_exhaustion', 'Fuel exhaustion'],
  ['combined', 'Combined'],
];
const SLAMMING = ['low', 'moderate', 'high', 'extreme'];
const ICE = ['none', 'low', 'moderate', 'very_high'];
const FAILURE_MODES = ['breaks_in_half', 'sink', 'capsize'];

const R_NM = 3440.065;
function haversineNm(a, b) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R_NM * Math.asin(Math.min(1, Math.sqrt(h)));
}

const mono = "'Courier New', monospace";

const labelStyle = {
  fontFamily: mono,
  fontSize: 9,
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  color: 'rgba(0,0,0,0.4)',
  marginBottom: 4,
  display: 'block',
};

const inputStyle = {
  fontFamily: mono,
  fontSize: 11,
  padding: '6px 8px',
  border: '1px solid rgba(0,0,0,0.18)',
  background: '#fff',
  color: 'rgba(0,0,0,0.8)',
  width: '100%',
  boxSizing: 'border-box',
  outline: 'none',
};

function field(label, child) {
  return (
    <div style={{ minWidth: 0 }}>
      <span style={labelStyle}>{label}</span>
      {child}
    </div>
  );
}

function roleLabel(index, count) {
  if (index === 0) return 'Origin';
  if (index === count - 1 && count > 1) return 'Destination';
  return `Waypoint ${index}`;
}

function roleColor(index, count) {
  if (index === 0) return '#1a7f37';
  if (index === count - 1 && count > 1) return '#b42318';
  return '#1f4fd6';
}

export default function MissionCreator({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [objective, setObjective] = useState('');
  // First point defaults to the Greenwich meridian on the equator.
  const [points, setPoints] = useState([{ name: '', lat: 0, lon: 0 }]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [stressor, setStressor] = useState(STRESSORS[0][0]);
  const [slamming, setSlamming] = useState('moderate');
  const [ice, setIce] = useState('low');
  const [failureModes, setFailureModes] = useState(['sink']);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [landMask, setLandMask] = useState(null);

  useEffect(() => {
    let alive = true;
    getLandMask().then((m) => { if (alive) setLandMask(m); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  // Land validation: a node on a land cell, or a leg whose great-circle path
  // crosses land, makes the route invalid. If the mask hasn't loaded (or failed),
  // we fail open and don't block.
  const { invalidPoints, invalidLegs, firstIssue } = useMemo(() => {
    const ip = new Set();
    const il = new Set();
    if (!landMask) return { invalidPoints: ip, invalidLegs: il, firstIssue: null };
    points.forEach((p, i) => { if (landMask.isLand(p.lon, p.lat)) ip.add(i); });
    for (let i = 0; i < points.length - 1; i += 1) {
      if (legCrossesLand(landMask, points[i], points[i + 1])) il.add(i);
    }
    let firstIssue = null;
    if (ip.size) {
      firstIssue = `${roleLabel([...ip][0], points.length)} is on land — drag it onto water.`;
    } else if (il.size) {
      const i = [...il][0];
      firstIssue = `Leg ${roleLabel(i, points.length)} → ${roleLabel(i + 1, points.length)} crosses land — move a node so the path stays on water.`;
    }
    return { invalidPoints: ip, invalidLegs: il, firstIssue };
  }, [landMask, points]);

  const routeHasLand = invalidPoints.size > 0 || invalidLegs.size > 0;

  const addPoint = () => {
    if (routeHasLand) { setError(firstIssue); return; }
    setPoints((list) => {
      if (list.length === 0) return [{ name: '', lat: 0, lon: 0 }];
      // Spawn near the last point (offset east) so it lands on-globe and draggable.
      const last = list[list.length - 1];
      const next = { name: '', lat: Math.max(-85, Math.min(85, last.lat)), lon: ((last.lon + 12 + 540) % 360) - 180 };
      setSelectedIndex(list.length);
      return [...list, next];
    });
  };

  const removePoint = (index) => setPoints((list) => {
    const next = list.filter((_, i) => i !== index);
    setSelectedIndex((sel) => Math.max(0, Math.min(sel, next.length - 1)));
    return next;
  });

  const renamePoint = (index, value) => setPoints((list) => (
    list.map((p, i) => (i === index ? { ...p, name: value } : p))
  ));

  const toggleFailureMode = (mode) => setFailureModes((modes) => (
    modes.includes(mode) ? modes.filter((m) => m !== mode) : [...modes, mode]
  ));

  const distanceNm = useMemo(() => {
    if (points.length < 2) return null;
    let total = 0;
    for (let i = 0; i < points.length - 1; i += 1) total += haversineNm(points[i], points[i + 1]);
    return Math.round(total);
  }, [points]);

  const canSubmit = name.trim() && points.length >= 2 && !routeHasLand && !submitting;

  const submit = () => {
    if (!name.trim()) { setError('Mission needs a name.'); return; }
    if (points.length < 2) { setError('Add at least two points (origin and destination) on the globe.'); return; }
    if (routeHasLand) { setError(firstIssue); return; }
    setSubmitting(true);
    setError(null);
    const toGeo = (p, fallback) => ({ name: p.name.trim() || fallback, lat_deg: p.lat, lon_deg: p.lon });
    const payload = {
      name: name.trim(),
      objective: objective.trim(),
      origin: toGeo(points[0], 'Origin'),
      destination: toGeo(points[points.length - 1], 'Destination'),
      waypoints: points.slice(1, -1).map((p, i) => toGeo(p, `Waypoint ${i + 1}`)),
      distance_nm: distanceNm,
      primary_stressor: stressor,
      failure_modes_under_test: failureModes,
      environmental_profile: { slamming_probability: slamming, ice_accretion_risk: ice },
    };
    fetch('/api/missions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((r) => (r.ok ? r.json() : r.json().then((d) => Promise.reject(new Error(d.error || `HTTP ${r.status}`)))))
      .then((data) => onCreated(data.mission))
      .catch((e) => setError(e.message))
      .finally(() => setSubmitting(false));
  };

  const selectStyle = { ...inputStyle, appearance: 'auto' };

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(0,0,0,0.32)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="no-scrollbar"
        style={{
          width: 560, maxHeight: '90vh', overflowY: 'auto',
          background: '#C3C4CA', border: '1px solid rgba(0,0,0,0.25)',
          boxShadow: '0 12px 40px rgba(0,0,0,0.3)', padding: 20,
          fontFamily: mono,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
          <span style={{ fontSize: 13, letterSpacing: '0.06em', color: 'rgba(0,0,0,0.78)' }}>NEW MISSION</span>
          <span onClick={onClose} style={{ cursor: 'pointer', fontSize: 14, color: 'rgba(0,0,0,0.5)' }}>✕</span>
        </div>

        <div style={{ display: 'grid', gap: 14 }}>
          {field('Mission name', (
            <input style={inputStyle} value={name} placeholder="e.g. Tasman Storm Run"
              onChange={(e) => setName(e.target.value)} />
          ))}
          {field('Objective (optional)', (
            <input style={inputStyle} value={objective} placeholder="What is this voyage testing?"
              onChange={(e) => setObjective(e.target.value)} />
          ))}

          {/* Globe-based route builder */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ ...labelStyle, marginBottom: 0 }}>Route — drag points across the globe</span>
              <button onClick={addPoint} disabled={routeHasLand}
                style={{
                  ...inputStyle, width: 'auto', padding: '4px 12px',
                  cursor: routeHasLand ? 'not-allowed' : 'pointer',
                  background: routeHasLand ? 'rgba(0,0,0,0.12)' : 'rgba(0,0,0,0.78)',
                  color: routeHasLand ? 'rgba(0,0,0,0.35)' : '#fff',
                  border: '1px solid rgba(0,0,0,0.2)', fontSize: 13, lineHeight: 1,
                }}
                title={routeHasLand ? 'Fix the route (off land) before adding points' : 'Add a point'}>+</button>
            </div>
            <div style={{ height: 300, border: '1px solid rgba(0,0,0,0.18)', background: '#C3C4CA', position: 'relative' }}>
              <GlobePicker
                points={points}
                selectedIndex={selectedIndex}
                onChange={setPoints}
                onSelect={setSelectedIndex}
                invalidPoints={invalidPoints}
                invalidLegs={invalidLegs}
              />
              <div style={{
                position: 'absolute', bottom: 6, left: 8, fontSize: 9,
                color: 'rgba(0,0,0,0.45)', pointerEvents: 'none',
              }}>
                drag a dot to move it · rotate the globe by dragging empty space
              </div>
            </div>
            {routeHasLand && (
              <div style={{
                marginTop: 6, fontSize: 10, color: '#a11',
                background: 'rgba(170,17,17,0.08)', border: '1px solid rgba(170,17,17,0.3)',
                padding: '6px 8px',
              }}>
                ⚠ {firstIssue}
              </div>
            )}
          </div>

          {/* Ordered point list */}
          <div style={{ display: 'grid', gap: 4 }}>
            {points.map((p, i) => {
              const selected = i === selectedIndex;
              const onLand = invalidPoints.has(i);
              return (
                <div key={i}
                  onClick={() => setSelectedIndex(i)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                    fontSize: 10, color: onLand ? '#a11' : 'rgba(0,0,0,0.7)', padding: '5px 8px',
                    background: onLand ? 'rgba(170,17,17,0.08)' : selected ? 'rgba(31,79,214,0.10)' : 'rgba(255,255,255,0.5)',
                    border: `1px solid ${onLand ? 'rgba(170,17,17,0.45)' : selected ? 'rgba(31,79,214,0.4)' : 'rgba(0,0,0,0.1)'}`,
                  }}>
                  <span style={{ width: 8, height: 8, borderRadius: 8, background: onLand ? '#d11' : roleColor(i, points.length), flexShrink: 0 }} />
                  <span style={{ width: 78, color: onLand ? '#a11' : 'rgba(0,0,0,0.5)', flexShrink: 0 }}>
                    {roleLabel(i, points.length)}{onLand ? ' ⚠' : ''}
                  </span>
                  <input
                    style={{ ...inputStyle, fontSize: 10, padding: '3px 6px', flex: 1 }}
                    value={p.name} placeholder="name (optional)"
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => renamePoint(i, e.target.value)} />
                  <span style={{ width: 96, textAlign: 'right', color: 'rgba(0,0,0,0.55)', flexShrink: 0 }}>
                    {p.lat.toFixed(1)}, {p.lon.toFixed(1)}
                  </span>
                  <span onClick={(e) => { e.stopPropagation(); removePoint(i); }} title="Remove"
                    style={{ cursor: 'pointer', opacity: 0.6, padding: '0 3px', flexShrink: 0 }}>✕</span>
                </div>
              );
            })}
            <div style={{ fontSize: 9, color: 'rgba(0,0,0,0.4)', paddingLeft: 2 }}>
              {points.length < 2
                ? 'Add another point — the last point becomes the destination.'
                : `${points.length} points · ${distanceNm} nm`}
            </div>
          </div>

          {/* Physics presets */}
          <div style={{ borderTop: '1px solid rgba(0,0,0,0.12)', paddingTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {field('Primary stressor', (
              <select style={selectStyle} value={stressor} onChange={(e) => setStressor(e.target.value)}>
                {STRESSORS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
              </select>
            ))}
            {field('Slamming', (
              <select style={selectStyle} value={slamming} onChange={(e) => setSlamming(e.target.value)}>
                {SLAMMING.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            ))}
            {field('Ice risk', (
              <select style={selectStyle} value={ice} onChange={(e) => setIce(e.target.value)}>
                {ICE.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            ))}
            {field('Route distance', (
              <div style={{ ...inputStyle, background: 'rgba(255,255,255,0.4)', color: 'rgba(0,0,0,0.6)' }}>
                {distanceNm != null ? `${distanceNm} nm` : '— add 2+ points'}
              </div>
            ))}
          </div>

          <div>
            <span style={labelStyle}>Failure modes under test</span>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {FAILURE_MODES.map((mode) => {
                const on = failureModes.includes(mode);
                return (
                  <span key={mode} onClick={() => toggleFailureMode(mode)}
                    style={{
                      cursor: 'pointer', fontSize: 10, padding: '4px 9px',
                      border: '1px solid rgba(0,0,0,0.2)',
                      background: on ? 'rgba(0,0,0,0.72)' : 'transparent',
                      color: on ? '#fff' : 'rgba(0,0,0,0.55)',
                    }}>{mode.replaceAll('_', ' ')}</span>
                );
              })}
            </div>
          </div>

          {error && (
            <div style={{ fontSize: 10, color: '#a11', background: 'rgba(170,17,17,0.08)', border: '1px solid rgba(170,17,17,0.3)', padding: '6px 8px' }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 }}>
            <button onClick={onClose}
              style={{ ...inputStyle, width: 'auto', cursor: 'pointer', background: 'transparent', color: 'rgba(0,0,0,0.55)' }}>
              Cancel
            </button>
            <button onClick={submit} disabled={!canSubmit}
              style={{
                ...inputStyle, width: 'auto', cursor: canSubmit ? 'pointer' : 'default',
                background: canSubmit ? 'rgba(0,0,0,0.82)' : 'rgba(0,0,0,0.1)',
                color: canSubmit ? '#fff' : 'rgba(0,0,0,0.35)',
              }}>
              {submitting ? 'Creating…' : 'Create mission'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
