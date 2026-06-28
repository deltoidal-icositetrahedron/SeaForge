import React from 'react';

// SVG coordinate space: viewBox "0 0 900 200"
// Norfolk  → SVG (120, 80)
// Bermuda  → SVG (780, 140)
// For routes with more/fewer waypoints we interpolate along the same line.

const NORFOLK_X  = 120;
const NORFOLK_Y  = 80;
const BERMUDA_X  = 780;
const BERMUDA_Y  = 140;

// Map a fraction 0..1 along the route to SVG coords
function routePoint(t) {
  return {
    x: NORFOLK_X + t * (BERMUDA_X - NORFOLK_X),
    y: NORFOLK_Y + t * (BERMUDA_Y - NORFOLK_Y),
  };
}

// Top-down Corsair icon (pointing roughly east/right)
function CorsairTopDown({ x, y, color, size = 1 }) {
  // Arrow-like polygon, pointing right
  const pts = [
    [0, -8],
    [14, 0],
    [0, 8],
    [3, 0],
  ].map(([px, py]) => `${x + px * size},${y + py * size}`).join(' ');

  return (
    <>
      <polygon points={pts} fill={color} opacity="0.9" />
      {/* Sensor arcs radiating forward */}
      <line
        x1={x + 14 * size} y1={y}
        x2={x + 14 * size + 60} y2={y - 16}
        stroke={color} strokeWidth="0.8" opacity="0.55"
      />
      <line
        x1={x + 14 * size} y1={y}
        x2={x + 14 * size + 70} y2={y}
        stroke={color} strokeWidth="0.8" opacity="0.55"
      />
      <line
        x1={x + 14 * size} y1={y}
        x2={x + 14 * size + 60} y2={y + 16}
        stroke={color} strokeWidth="0.8" opacity="0.55"
      />
    </>
  );
}

const rtCss = `
@keyframes blink-route {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.2; }
}
.blink-route { animation: blink-route 1.3s ease-in-out infinite; }
`;

export default function RouteTimeline({ route, simResult }) {
  const segments    = route?.segments  || [];
  const origin      = route?.origin;
  const destination = route?.destination;
  const status      = simResult?.status;
  const failureIdx  = simResult?.failure?.segment_index ?? null;    // 0-based
  const failureDist = simResult?.failure?.distance_completed_nm ?? null;

  // Total distance across all segments
  const totalDist = segments.reduce((s, sg) => s + (sg.distance_nm || 0), 0);

  // Compute completed fraction along the full route
  let completedFraction = 0;
  if (status === 'survived') {
    completedFraction = 1;
  } else if (status === 'failed' && failureIdx !== null) {
    let distSoFar = 0;
    for (let i = 0; i < failureIdx; i++) {
      distSoFar += segments[i]?.distance_nm || 0;
    }
    distSoFar += failureDist || 0;
    completedFraction = totalDist > 0 ? Math.min(distSoFar / totalDist, 1) : 0;
  }

  const vesselPos = simResult ? routePoint(completedFraction) : null;
  const vesselColor = status === 'failed' ? '#ff3333' : '#00ff88';

  // Failure zone box around the failure vessel position
  const failureBoxVisible = status === 'failed' && vesselPos;

  // Segment midpoint labels
  let cumulDist = 0;
  const segMidpoints = segments.map((seg, i) => {
    const segStart = cumulDist / totalDist;
    cumulDist += seg.distance_nm || 0;
    const segEnd = cumulDist / totalDist;
    const mid = (segStart + segEnd) / 2;
    const pt = routePoint(mid);
    return { pt, seg, index: i };
  });

  const isFailed   = status === 'failed';
  const isSurvived = status === 'survived';

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <style>{rtCss}</style>

      {/* Header */}
      <div style={{
        fontSize: 9,
        letterSpacing: '0.22em',
        color: '#3a5a78',
        textTransform: 'uppercase',
        padding: '6px 12px',
        borderBottom: '1px solid #0d1a26',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontFamily: "'Courier New', Courier, monospace",
        background: '#04090f',
      }}>
        <span style={{ color: '#4a7a9a' }}>
          TACTICAL ROUTE MAP — {segments.length} SEGMENT{segments.length !== 1 ? 'S' : ''}
        </span>
        {origin && destination && (
          <span style={{ color: '#334455' }}>
            {origin.lat_deg?.toFixed(2)}°N {Math.abs(origin.lon_deg)?.toFixed(2)}°W
            &nbsp;&#10132;&nbsp;
            {destination.lat_deg?.toFixed(2)}°N {Math.abs(destination.lon_deg)?.toFixed(2)}°W
          </span>
        )}
      </div>

      {/* Map area */}
      <div style={{
        position: 'relative',
        width: '100%',
        height: 200,
        background: '#080c10',
        backgroundImage: [
          'linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px)',
          'linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)',
        ].join(', '),
        backgroundSize: '40px 40px',
        overflow: 'hidden',
      }}>

        <svg
          viewBox="0 0 900 200"
          style={{ width: '100%', height: '100%', display: 'block' }}
          xmlns="http://www.w3.org/2000/svg"
        >
          <defs>
            <filter id="rt-glow">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {/* ── FAILURE ZONE (red semi-transparent rect) ── */}
          {failureBoxVisible && (
            <rect
              x={vesselPos.x - 55}
              y={vesselPos.y - 35}
              width={110}
              height={70}
              fill="rgba(255,30,30,0.07)"
              stroke="rgba(255,30,30,0.2)"
              strokeWidth="0.8"
            />
          )}

          {/* ── ROUTE LINE (dim, full route) ── */}
          <line
            x1={NORFOLK_X} y1={NORFOLK_Y}
            x2={BERMUDA_X} y2={BERMUDA_Y}
            stroke="#1e3040"
            strokeWidth="1.5"
            strokeDasharray="6 4"
          />

          {/* ── COMPLETED PORTION (bright green) ── */}
          {simResult && completedFraction > 0 && (() => {
            const end = routePoint(completedFraction);
            return (
              <line
                x1={NORFOLK_X} y1={NORFOLK_Y}
                x2={end.x} y2={end.y}
                stroke={isFailed ? '#ff3333' : '#00ff88'}
                strokeWidth="1.5"
                opacity="0.7"
              />
            );
          })()}

          {/* ── SEGMENT MIDPOINT LABELS ── */}
          {segMidpoints.map(({ pt, seg, index }) => {
            const hs   = seg.conditions?.hs_m || 0;
            const dist = seg.distance_nm || 0;
            const isSegFailed = index === failureIdx;
            const color = isSegFailed ? '#ff5522' : '#2a4a62';
            return (
              <g key={`mid-${index}`}>
                {/* Tick mark on route */}
                <circle cx={pt.x} cy={pt.y} r={2} fill={color} opacity="0.7" />
                {/* Label above/below line */}
                <text
                  x={pt.x}
                  y={pt.y - 10}
                  textAnchor="middle"
                  fontSize="7.5"
                  fill={color}
                  fontFamily="'Courier New', Courier, monospace"
                  opacity="0.85"
                >
                  {dist.toFixed(0)} NM  Hs {hs.toFixed(1)}m
                </text>
                {isSegFailed && (
                  <text
                    x={pt.x}
                    y={pt.y + 18}
                    textAnchor="middle"
                    fontSize="7"
                    fill="#ff3333"
                    fontFamily="'Courier New', Courier, monospace"
                    className="blink-route"
                  >
                    FAILURE POINT
                  </text>
                )}
              </g>
            );
          })}

          {/* ── WAYPOINT A (origin / Norfolk) ── */}
          <circle
            cx={NORFOLK_X} cy={NORFOLK_Y} r={6}
            fill="#000"
            stroke={isSurvived || (simResult && completedFraction > 0) ? '#00ff88' : '#336688'}
            strokeWidth="1.5"
          />
          <circle cx={NORFOLK_X} cy={NORFOLK_Y} r={2} fill="#00ff88" opacity="0.8" />
          <text
            x={NORFOLK_X} y={NORFOLK_Y - 12}
            textAnchor="middle"
            fontSize="8"
            fill="#4a8a7a"
            fontFamily="'Courier New', Courier, monospace"
          >
            NORFOLK VA
          </text>
          <text
            x={NORFOLK_X} y={NORFOLK_Y - 4}
            textAnchor="middle"
            fontSize="6.5"
            fill="#2a4455"
            fontFamily="'Courier New', Courier, monospace"
            dy="14"
          >
            36.85°N 76.30°W
          </text>

          {/* ── WAYPOINT B (destination / Bermuda) ── */}
          <circle
            cx={BERMUDA_X} cy={BERMUDA_Y} r={6}
            fill="#000"
            stroke={isSurvived ? '#00ff88' : '#334455'}
            strokeWidth="1.5"
          />
          <circle cx={BERMUDA_X} cy={BERMUDA_Y} r={2} fill={isSurvived ? '#00ff88' : '#334455'} opacity="0.6" />
          <text
            x={BERMUDA_X} y={BERMUDA_Y - 12}
            textAnchor="middle"
            fontSize="8"
            fill={isSurvived ? '#4a8a7a' : '#334455'}
            fontFamily="'Courier New', Courier, monospace"
          >
            {destination?.lat_deg ? `${destination.lat_deg.toFixed(2)}°N` : 'BERMUDA'}
          </text>
          <text
            x={BERMUDA_X} y={BERMUDA_Y - 4}
            textAnchor="middle"
            fontSize="6.5"
            fill="#223344"
            fontFamily="'Courier New', Courier, monospace"
            dy="14"
          >
            {destination?.lon_deg
              ? `${Math.abs(destination.lon_deg).toFixed(2)}°W`
              : '64.78°W'}
          </text>

          {/* ── CORSAIR VESSEL ICON ── */}
          {vesselPos && (
            <g filter={status !== 'failed' ? 'url(#rt-glow)' : undefined}>
              <CorsairTopDown
                x={vesselPos.x}
                y={vesselPos.y}
                color={vesselColor}
                size={1}
              />
            </g>
          )}

          {/* ── TERMINAL TEXT (bottom-left) ── */}
          <text
            x="12" y="168"
            fontSize="8"
            fill="#334455"
            fontFamily="'Courier New', Courier, monospace"
            letterSpacing="0.08em"
          >
            MISSION: {origin ? `${origin.lat_deg?.toFixed(2)}°N → DEST` : 'NORFOLK → DESTINATION'}
          </text>
          <text
            x="12" y="179"
            fontSize="8"
            fill="#2a3d50"
            fontFamily="'Courier New', Courier, monospace"
            letterSpacing="0.08em"
          >
            DIST: {totalDist.toFixed(0)} NM  SEGS: {segments.length}
          </text>
          <text
            x="12" y="190"
            fontSize="8"
            fill={isFailed ? '#cc2222' : isSurvived ? '#22aa55' : '#334455'}
            fontFamily="'Courier New', Courier, monospace"
            letterSpacing="0.08em"
          >
            STATUS: {isFailed ? 'MISSION FAILURE' : isSurvived ? 'MISSION COMPLETE' : simResult ? 'UNDERWAY' : 'AWAITING DATA'}
          </text>

          {/* ── COMPLETION % (bottom-right) ── */}
          {simResult && (
            <text
              x="888" y="190"
              textAnchor="end"
              fontSize="8"
              fill={isFailed ? '#882222' : '#224433'}
              fontFamily="'Courier New', Courier, monospace"
              letterSpacing="0.06em"
            >
              {(completedFraction * 100).toFixed(1)}% COMPLETE
            </text>
          )}
        </svg>
      </div>

      {/* ── SEGMENT STATUS STRIP ── */}
      {segments.length > 0 && (
        <div style={{
          display: 'flex',
          borderTop: '1px solid #0d1a26',
          background: '#04090f',
          padding: '4px 12px',
          gap: 12,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}>
          {segments.map((seg, i) => {
            const isSegFailed    = i === failureIdx;
            const isSegCompleted = status === 'survived' || (failureIdx !== null && i < failureIdx);
            const color = isSegFailed ? '#ff3333' : isSegCompleted ? '#00aa55' : '#2a3d50';
            const hs    = seg.conditions?.hs_m || 0;
            const hsColor = hs >= 5 ? '#ff4422' : hs >= 3 ? '#ffaa00' : '#338855';
            const label = seg.label ? seg.label.split('(')[0].trim() : `SEG ${i + 1}`;
            return (
              <div key={i} style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontFamily: "'Courier New', Courier, monospace",
                fontSize: 8,
              }}>
                <div style={{
                  width: 6,
                  height: 6,
                  background: color,
                  flexShrink: 0,
                  borderRadius: isSegFailed ? 0 : '50%',
                }} />
                <span style={{ color: '#2a4455', letterSpacing: '0.08em' }}>
                  SEG {String(i + 1).padStart(2, '0')}
                </span>
                <span style={{ color: color, letterSpacing: '0.06em', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {label}
                </span>
                <span style={{ color: '#1e3040' }}>{(seg.distance_nm || 0).toFixed(0)} NM</span>
                <span style={{ color: hsColor }}>Hs {hs.toFixed(1)}m</span>
                {isSegFailed && (
                  <span style={{ color: '#ff3333', letterSpacing: '0.1em' }} className="blink-route">
                    &#9651; FAIL
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
