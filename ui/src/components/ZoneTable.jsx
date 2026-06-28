import React from 'react';

const PLACEHOLDER_ZONES = [
  'Keel', 'BilgeStrake', 'BottomPlating', 'SidePlating', 'BowFlare',
  'SternPlate', 'TransomFrame', 'WeatherDeck', 'BulkheadFrame',
];

function FatigueBar({ pct }) {
  const color = pct >= 100 ? '#ff3333' : pct >= 70 ? '#ffaa00' : '#00ff88';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div
        style={{
          width: 80,
          height: 3,
          background: '#111',
          border: '1px solid #1a1a1a',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            width: `${Math.min(pct, 100)}%`,
            height: '100%',
            background: color,
            transition: 'width 0.6s ease',
          }}
        />
      </div>
      <span style={{ color, fontSize: 11, minWidth: 38 }}>{pct.toFixed(1)}%</span>
    </div>
  );
}

export default function ZoneTable({ simResult }) {
  let zones = null;

  if (simResult?.zones) {
    zones = [...simResult.zones].sort(
      (a, b) => b.fatigue_consumed - a.fatigue_consumed
    );
  }

  function getRowStyle(fatigue) {
    if (fatigue === undefined) return {};
    if (fatigue >= 1.0) {
      return { borderLeft: '3px solid #ff3333', background: '#0d0000' };
    }
    if (fatigue >= 0.7) {
      return { borderLeft: '3px solid #ffaa00', background: '#0d0800' };
    }
    return {};
  }

  return (
    <div>
      <div className="section-header">STRUCTURAL ZONE ANALYSIS</div>
      <div style={{ overflowX: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>ZONE</th>
              <th>FATIGUE</th>
              <th>CORROSION (mm)</th>
              <th>CRACK (mm)</th>
              <th>PEAK STRESS (MPa)</th>
            </tr>
          </thead>
          <tbody>
            {zones
              ? zones.map((z) => {
                  const fatiguePct = z.fatigue_consumed * 100;
                  return (
                    <tr key={z.zone} style={getRowStyle(z.fatigue_consumed)}>
                      <td style={{ color: '#aaa', letterSpacing: '0.05em', fontSize: 11 }}>
                        {z.zone}
                      </td>
                      <td>
                        <FatigueBar pct={fatiguePct} />
                      </td>
                      <td style={{ color: '#888', fontSize: 11 }}>
                        {z.corrosion_depth_mm.toFixed(6)}
                      </td>
                      <td style={{ color: '#888', fontSize: 11 }}>
                        {z.crack_half_length_mm.toFixed(6)}
                      </td>
                      <td style={{ color: '#00ff88', fontSize: 12 }}>
                        {z.peak_stress_mpa.toFixed(1)}
                      </td>
                    </tr>
                  );
                })
              : PLACEHOLDER_ZONES.map((name) => (
                  <tr key={name}>
                    <td style={{ color: '#555', fontSize: 11 }}>{name}</td>
                    <td style={{ color: '#555', fontSize: 11 }}>---</td>
                    <td style={{ color: '#555', fontSize: 11 }}>---</td>
                    <td style={{ color: '#555', fontSize: 11 }}>---</td>
                    <td style={{ color: '#555', fontSize: 11 }}>---</td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
