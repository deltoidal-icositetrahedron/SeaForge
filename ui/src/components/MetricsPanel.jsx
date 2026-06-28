import React from 'react';

function MetricCard({ label, value, unit, subValue, bar, barColor, barPct, warn }) {
  return (
    <div
      style={{
        background: '#0a0a0a',
        border: `1px solid ${warn ? '#330000' : '#1e1e1e'}`,
        padding: '12px',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        minWidth: 0,
      }}
    >
      <div style={{ fontSize: 9, letterSpacing: '0.2em', color: '#555', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 20,
          color: warn ? '#ff3333' : '#00ff88',
          fontFamily: "'Courier New', monospace",
          lineHeight: 1.2,
          marginTop: 2,
        }}
      >
        {value}
      </div>
      {unit && (
        <div style={{ fontSize: 10, color: '#555' }}>{unit}</div>
      )}
      {bar && (
        <div className="progress-bar-wrap" style={{ marginTop: 6 }}>
          <div
            className={`progress-bar-fill ${barColor || ''}`}
            style={{ width: `${Math.min(barPct, 100)}%` }}
          />
        </div>
      )}
      {subValue && (
        <div style={{ fontSize: 10, color: '#555', marginTop: 4 }}>{subValue}</div>
      )}
    </div>
  );
}

export default function MetricsPanel({ simResult }) {
  const r = simResult?.result;
  const cb = r?.cost_breakdown;

  const fuelPct = r
    ? (r.fuel_remaining_kg / 5000) * 100
    : 0;
  const fuelColor = fuelPct < 20 ? 'red' : fuelPct < 40 ? 'amber' : '';

  const distPct = r
    ? (r.distance_completed_nm / r.total_distance_nm) * 100
    : 0;

  const gmWarn = r && r.final_gm_m < 0.5;

  const costStr = r
    ? '$' + r.total_config_cost_usd.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
    : '---';

  const costSub = cb
    ? `MAT $${cb.material_usd.toFixed(0)} · WLD $${cb.weld_usd.toFixed(0)} · SL $${cb.seal_usd.toFixed(0)}`
    : null;

  return (
    <div>
      <div className="section-header">MISSION METRICS</div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(5, 1fr)',
          gap: 1,
          background: '#111',
          padding: 1,
        }}
      >
        <MetricCard
          label="DIST COMPLETED"
          value={r ? `${r.distance_completed_nm.toFixed(0)}` : '---'}
          unit={r ? `/ ${r.total_distance_nm} nm` : 'nm'}
          bar={!!r}
          barPct={distPct}
          barColor=""
        />
        <MetricCard
          label="TIME ELAPSED"
          value={r ? r.time_elapsed_h.toFixed(1) : '---'}
          unit="hours"
        />
        <MetricCard
          label="FUEL REMAINING"
          value={r ? r.fuel_remaining_kg.toFixed(0) : '---'}
          unit="kg"
          bar={!!r}
          barPct={fuelPct}
          barColor={fuelColor}
        />
        <MetricCard
          label="GM STABILITY"
          value={r ? r.final_gm_m.toFixed(3) : '---'}
          unit="meters"
          warn={gmWarn}
        />
        <MetricCard
          label="CONFIG COST"
          value={costStr}
          unit="total"
          subValue={costSub}
        />
      </div>
    </div>
  );
}
